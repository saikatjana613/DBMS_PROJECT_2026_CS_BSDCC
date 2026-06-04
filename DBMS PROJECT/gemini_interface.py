"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  gemini_interface.py — Gemini API + Demonstration Selection                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

PURPOSE:
    Handles the "LLM" part of the LLM-R2 pipeline.

WHAT THIS FILE DOES:
    1. Selects the most similar demonstration from DEMO_POOL using
       lightweight feature-based cosine similarity (no ML library needed).
    2. Builds an In-Context-Learning (ICL) prompt with the selected demo.
    3. Calls Google Gemini to get rule recommendations —
       or falls back to a heuristic simulation when no API key is set.
    4. Parses the response into a validated list of rule names.

APPROACH:
    Feature extraction:
        extract_query_features(sql) produces a 9-dimensional binary/integer
        vector capturing structural properties (has_join, has_where, etc.).
        compute_similarity() computes cosine similarity between two vectors.
        select_best_demo() picks the demonstration with highest similarity.

    Gemini interaction:
        build_prompt() constructs the structured prompt with rule list + demo.
        call_gemini() sends the prompt to the API (or returns None to signal
        simulation). simulate_gemini() analyses query structure to predict
        rules heuristically.

    predict_rules() orchestrates all four steps and returns a result dict.

HOW IT WORKS:
    predict_rules(query, api_key) is the single entry point that the
    main pipeline calls. It returns a dict with recommended rules,
    demo info, similarity scores, latency, and whether simulation was used.

CONNECTION TO OTHER FILES:
    Called by main_pipeline.py for each benchmark query
"""

import os
import json
import re
import time  # ✅ Fixed: Import the whole time module
from difflib import SequenceMatcher
from typing import Dict, List, Any, Optional, Tuple

# =============================================================================
# Gemini SDK
# =============================================================================

try:
    from google import genai
    from google.genai import types
    
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    print("[Warning] google-genai not installed.")
    print("Install using: pip install -U google-genai")

# =============================================================================
# Ollama SDK
# =============================================================================

try:
    import requests
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    print("[Warning] requests not installed (needed for Ollama).")
    print("Install using: pip install requests")

# =============================================================================
# Gemini Configuration
# =============================================================================

GEMINI_MODEL = "gemini-2.0-pro"
GEMINI_FALLBACK = "gemini-2.0-flash"

GEMINI_TEMP = 0.3
GEMINI_MAX_TOKENS = 1024

# =============================================================================
# Demonstration Pool
# =============================================================================

DEMO_POOL = [
    {
        "query": "SELECT c.name, SUM(o.amount) FROM customers c, orders o "
                 "WHERE c.id = o.cust_id AND c.region = 'ASIA' "
                 "GROUP BY c.name",
        "rules": ["Filter Pushdown"],
        "explanation": "Move filter closer to scan"
    },
    {
        "query": "SELECT l.orderkey, SUM(l.quantity) "
                 "FROM lineitem l "
                 "GROUP BY l.orderkey "
                 "ORDER BY l.orderkey",
        "rules": ["Aggregation Merge"],
        "explanation": "Merge aggregation and ordering"
    },
    {
        "query": "SELECT id,title FROM movies "
                 "UNION ALL "
                 "SELECT id,title FROM tv_shows "
                 "ORDER BY title",
        "rules": ["UNION Sort Transpose"],
        "explanation": "Push sorting into UNION branches"
    },
    {
        "query": "SELECT * FROM products "
                 "WHERE price > 100 "
                 "AND category='Electronics'",
        "rules": ["EMPTY"],
        "explanation": "Already optimal"
    },
    {
        "query": "SELECT p.name,SUM(s.amount) "
                 "FROM sales s "
                 "JOIN products p ON s.prod_id=p.id "
                 "WHERE s.date>'2024-01-01' "
                 "GROUP BY p.name "
                 "HAVING SUM(s.amount)>1000",
        "rules": [
            "Filter Pushdown",
            "Aggregation Merge"
        ],
        "explanation": "Push filters and merge aggregation"
    },
    {
        "query": "SELECT category, SUM(price) FROM products "
                 "GROUP BY category HAVING category != 'Electronics'",
        "rules": ["Having to Where"],
        "explanation": "Filter before aggregation"
    },
    {
        "query": "SELECT DISTINCT city, state FROM customers",
        "rules": ["Distinct to Group By"],
        "explanation": "Convert DISTINCT to GROUP BY"
    },
    {
        "query": "SELECT * FROM employees WHERE name LIKE '%John%'",
        "rules": ["Like to Instr"],
        "explanation": "Use INSTR instead of LIKE for performance"
    }
]

# =============================================================================
# Similarity
# =============================================================================

def compute_similarity(sql1: str, sql2: str) -> float:
    """
    Similarity score between SQL queries using SequenceMatcher.
    """
    sql1 = " ".join(sql1.lower().split())
    sql2 = " ".join(sql2.lower().split())
    
    return SequenceMatcher(None, sql1, sql2).ratio()


def select_demo(sql: str) -> Tuple[Dict[str, Any], float]:
    """
    Select most similar demo query from DEMO_POOL.
    Returns (demo_dict, similarity_score).
    """
    best_demo = None
    best_score = -1.0
    
    for demo in DEMO_POOL:
        score = compute_similarity(sql, demo["query"])
        
        if score > best_score:
            best_score = score
            best_demo = demo
    
    return best_demo, best_score

# =============================================================================
# Prompt Builder
# =============================================================================

def build_prompt(sql: str, demo: Dict[str, Any], sample_idx: int = 0) -> str:
    """
    Build a sophisticated structured prompt with the selected demonstration.
    Includes detailed rule explanations, optimization cost hints, and system limits.
    """
    
    if sample_idx == 0:
        approach = "Standard Balanced Approach: Recommend the most proven logical rules for the query structure."
    elif sample_idx == 1:
        approach = "Aggressive Rewrite Approach: Prioritize complex and aggressive restructurings, looking for edge-case optimizations or rule cascades that are non-obvious."
    else:
        approach = "Minimalist / Alternative Approach: Try to find a completely different set of rules, perhaps focusing only on simple predicate/filter moves, or returning ['EMPTY'] if not completely safe."

    return f"""
You are an expert SQL query optimizer for an SQLite-based engine.
Your task: Recommend specific SQL rewrite rules that will significantly improve query execution time.

STRATEGY MODIFIER FOR THIS REQUEST:
{approach}

Your recommendations will be passed to a regex-based rewrite engine. 
Therefore, you must ONLY recommend rules if the semantic structure of the query perfectly matches the rule's capability. If applying a rule would make the query slower or crash, you MUST recommend ["EMPTY"].

CRITICAL OPTIMIZATION GOALS:
1. Reduce row counts BEFORE expensive JOINs (Filter Pushdown, Limit Pushdown)
2. Simplify or eliminate redundant aggregations and subqueries
3. Enable hash-joins to build on the smaller table (Join Reordering)

AVAILABLE REWRITE RULES:

1. Filter Pushdown
   - Action: Moves WHERE conditions ONLY if it reduces rows massively before joins. DO NOT recommend wrapping in subqueries if it's just a simple 2-table join like `JOB2` with a simple inequality, as turning 2-table implicit joins into INNER JOIN syntaxes might hurt SQLite's query plan planner.
   - Ideal Context: A query joining 3+ massive tables with highly selective WHERE conditions on one or more of the tables.
   - DANGER: Do NOT recommend this for small dimension tables or string matches (LIKE), as wrapping tables in subqueries destroys SQLite primary key indexes and causes massive slow-downs! Only for huge tables with numeric/date constraints. DO NOT recommend this rule if the query only has a simple 2-table join and doing so will only create an INNER JOIN without a subquery, which hurts performance (e.g. `imdb_title t INNER JOIN imdb_cast_info ci ON ...`).

2. Aggregation Merge
   - Action: Removes redundant outer SELECT wrappers around an already-grouped subquery.
   - Ideal Context: An outer query doing simple projection over an inner query that has GROUP BY.

3. UNION Sort Transpose
   - Action: Pushes ORDER BY into each branch of a UNION ALL.
   - Ideal Context: UNION queries with a global ORDER BY, enabling merge-sorts.

4. Predicate Move-Around
   - Action: Extracts filters from JOIN ON clauses into the WHERE clause (or vice-versa) for independent optimization.
   - Ideal Context: Complex ON clauses containing literal comparisons (e.g. ON a.id = b.id AND a.val = 5).

5. Join Reordering
   - Action: Swaps JOIN inputs.
   - Ideal Context: When joining a massive fact table to a tiny dimension table, ensure the small table is the build side.
   - DANGER: Do NOT recommend this for small tables (like in demographics) or queries that run in < 5ms. Swapping join orders without index knowledge usually makes SQLite slower!

6. Subquery to JOIN
   - Action: Converts IN / EXISTS subqueries into explicit JOINs.
   - Ideal Context: Correlated subqueries or large IN clauses that databases struggle to optimize natively.

7. Limit Pushdown
   - Action: Pushes LIMIT into UNION branches or subqueries.
   - Ideal Context: UNIONs or subqueries wrapped by an outer LIMIT.

8. Constant Folding
   - Action: Pre-evaluates arithmetic expressions (e.g., 2 * 3 -> 6).
   - Ideal Context: Mathematical expressions in the SELECT list.

9. Having to Where
   - Action: Moves HAVING clause conditions to WHERE when possible.
   - Ideal Context: Queries where filtering can occur before aggregation.

10. Distinct to Group By
    - Action: Converts SELECT DISTINCT to GROUP BY with COUNT.
    - Ideal Context: DISTINCT queries that can benefit from aggregation.

11. Cross Join Opt
    - Action: Optimizes CROSS JOINs with filters into INNER JOINs.
    - Ideal Context: CROSS JOINs that have filtering conditions applicable to INNER JOINs.

12. Like to Instr
    - Action: Replaces LIKE with INSTR for performance.
    - Ideal Context: LIKE patterns that can be translated to INSTR function calls.

EXAMPLE DEMONSTRATION:
---
Query:
{demo["query"]}

Recommended Rules:
{demo["rules"]}

Reasoning:
{demo["explanation"]}
---

NOW ANALYZE THIS QUERY:

SQL:
{sql}

Carefully analyze:
- Will filtering early reduce the intermediate join sizes?
- Is there a nested subquery that can be flattened or transformed to a JOIN?
- Is the rewrite safe for SQLite?

Respond with ONLY valid JSON (no markdown, no explanation):

{{
    "rules": ["Rule Name 1", "Rule Name 2"],
    "explanation": "Brief reasoning"
}}

If no optimization applies, or if changing the query would slow it down:

{{
    "rules": ["EMPTY"],
    "explanation": "Query already optimal or insufficient context for rewrite"
}}
"""

# =============================================================================
# Response Parsing
# =============================================================================

# LLM-friendly rule names and their mapping to actual function names
VALID_RULES = [
    "Filter Pushdown",
    "Aggregation Merge",
    "UNION Sort Transpose",
    "Predicate Move-Around",
    "Join Reordering",
    "Subquery to JOIN",
    "Limit Pushdown",
    "Constant Folding",
    "Having to Where",
    "Distinct to Group By",
    "Cross Join Opt",
    "Like to Instr",
    "EMPTY"
]

# Mapping from LLM rule names to actual rewrite function rule names
LLM_TO_FUNCTION_RULE_MAP = {
    "Filter Pushdown": "FILTER_INTO_JOIN",
    "Predicate Move-Around": "JOIN_EXTRACT_FILTER",
    "Aggregation Merge": "AGGREGATE_PROJECT_MERGE",
    "UNION Sort Transpose": "SORT_UNION_TRANSPOSE",
    "Join Reordering": "JOIN_COMMUTE",
    "Having to Where": "HAVING_TO_WHERE",
    "Distinct to Group By": "DISTINCT_TO_GROUP_BY",
    "Cross Join Opt": "CROSS_JOIN_OPT",
    "Like to Instr": "LIKE_TO_INSTR",
    "EMPTY": "EMPTY",
}


def parse_response(response_text: str) -> List[str]:
    """
    Parse Gemini response to extract validated rule names and map to actual rule functions.
    Returns list of actual rule function names (e.g., "FILTER_INTO_JOIN" not "Filter Pushdown").
    """
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        
        if start >= 0 and end > start:
            obj = json.loads(response_text[start:end])
            rules = obj.get("rules", [])
            
            if isinstance(rules, list):
                # Map LLM rule names to actual function names
                mapped_rules = []
                for r in rules:
                    if r in LLM_TO_FUNCTION_RULE_MAP:
                        mapped_rules.append(LLM_TO_FUNCTION_RULE_MAP[r])
                    elif r in VALID_RULES:
                        # Rule exists in VALID_RULES, try to find mapping
                        mapped_rules.append(LLM_TO_FUNCTION_RULE_MAP.get(r, r))
                
                if mapped_rules:
                    return mapped_rules
    except Exception:
        pass
    
    # Fallback: search for rule names in text
    detected = []
    for rule in VALID_RULES:
        if rule.lower() in response_text.lower():
            detected.append(LLM_TO_FUNCTION_RULE_MAP.get(rule, rule))
    
    return detected if detected else ["EMPTY"]

# =============================================================================
# Gemini API Call
# =============================================================================

def call_gemini_api(
    prompt: str,
    api_key: str
) -> Tuple[str, float]:
    """
    Call Gemini API with fallback to secondary model.
    Returns (response_text, latency_seconds).
    """
    client = genai.Client(api_key=api_key)
    
    config = types.GenerateContentConfig(
        temperature=GEMINI_TEMP,
        max_output_tokens=GEMINI_MAX_TOKENS
    )
    
    last_error = None
    
    for model in [GEMINI_MODEL, GEMINI_FALLBACK]:
        try:
            start = time.perf_counter()
            
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config
            )
            
            elapsed = time.perf_counter() - start
            
            text = response.text or ""
            
            return text, elapsed
            
        except Exception as e:
            print(f"[Gemini {model} failed] {e}")
            last_error = e
    
    raise RuntimeError(
        f"All Gemini models failed: {last_error}"
    )


# =============================================================================
# Ollama API Caller
# =============================================================================

def call_ollama_api(
    prompt: str,
    config: "Config",
) -> Tuple[str, float]:
    """
    Call Ollama API with the given prompt.
    
    Args:
        prompt: The prompt to send to Ollama
        config: Configuration object with ollama settings
    
    Returns:
        Tuple of (response text, elapsed time in seconds)
    
    Raises:
        RuntimeError: If Ollama is not reachable
    """
    
    if not OLLAMA_AVAILABLE:
        raise RuntimeError(
            "requests library not available. "
            "Install with: pip install requests"
        )
    
    import time
    
    start_time = time.time()
    
    try:
        # Build Ollama API endpoint
        base_url = config.ollama_base_url.rstrip("/")
        url = f"{base_url}/api/generate"
        
        payload = {
            "model": config.ollama_model,
            "prompt": prompt,
            "stream": False,
            "temperature": config.ollama_temperature,
            "top_p": config.ollama_top_p,
        }
        
        # Make request with timeout
        response = requests.post(
            url,
            json=payload,
            timeout=120,
        )
        
        elapsed = time.time() - start_time
        
        # Check for HTTP errors
        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama API error {response.status_code}: {response.text}"
            )
        
        # Parse response
        result = response.json()
        text = result.get("response", "")
        
        print(f"[✓ Ollama API succeeded] Model: {config.ollama_model}, "
              f"Time: {elapsed:.2f}s")
        
        return text, elapsed
        
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {config.ollama_base_url}. "
            f"Make sure Ollama is running: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            "Ollama API timed out. Model may be too large or busy."
        )
    except Exception as e:
        raise RuntimeError(f"Ollama API error: {e}")


# =============================================================================
# Simulation Mode - Structural Query Analysis
# =============================================================================

def _analyze_query_structure(sql: str) -> List[str]:
    """
    Analyze SQL structure to determine which rewrite rules apply.
    Uses cost heuristics to only recommend rules when they're likely to help.
    """
    sql_upper = " ".join(sql.upper().split())
    rules = []
    
    # Basic query properties
    has_where = " WHERE " in sql_upper
    has_group_by = "GROUP BY" in sql_upper
    has_order_by = "ORDER BY" in sql_upper
    has_union = "UNION" in sql_upper
    has_limit = "LIMIT" in sql_upper
    has_subquery = sql_upper.count("SELECT") > 1
    has_join = " JOIN " in sql_upper
    
    # 1. Check for Filter Pushdown opportunities (SELECTIVE)
    if has_where and (has_join or sql_upper.count(',') >= 1):
        # Only recommend if:
        # - Multiple tables exist
        # - WHERE has conditions that could reduce early
        from_match = re.search(r'FROM\s+(.+?)\s+WHERE', sql_upper, re.DOTALL)
        if from_match:
            from_clause = from_match.group(1)
            # Count actual table references
            table_count = from_clause.count(',') + 1 if ',' in from_clause else 1
            
            where_start = sql_upper.index("WHERE") + 5
            where_end = len(sql_upper)
            for kw in ["GROUP BY", "ORDER BY", "LIMIT", "HAVING"]:
                idx = sql_upper.find(kw, where_start)
                if idx != -1 and idx < where_end:
                    where_end = idx
            where_clause = sql_upper[where_start:where_end]
            
            # Count conditions that could be table-specific
            conditions = [c.strip() for c in re.split(r'\s+AND\s+', where_clause)]
            single_table_conditions = sum(1 for c in conditions if '=' not in c or c.count('.') <= 1)
            
            # Recommend FILTER_INTO_JOIN if:
            # - Multiple tables exist
            # - At least one simple condition per table
            # - Not too many conditions (avoid explosion)
            if table_count >= 2 and single_table_conditions >= 1 and len(conditions) <= 5:
                rules.append("Filter Pushdown")
        
        # Check for JOIN with multiple ON conditions (Predicate Move-Around)
        if has_join and " ON " in sql_upper:
            on_match = re.search(
                r'ON\s+(.+?)(?:WHERE|AND|GROUP|ORDER|LIMIT|$)',
                sql_upper,
                re.DOTALL
            )
            if on_match:
                on_clause = on_match.group(1)
                on_conditions = [c.strip() for c in re.split(r'\s+AND\s+', on_clause)]
                # Only recommend if join has multiple conditions (could separate)
                if len(on_conditions) > 1:
                    rules.append("Predicate Move-Around")
    
    # 2. Check for Aggregation Merge opportunities (SELECTIVE)
    if has_group_by and has_order_by:
        # Only recommend if they operate on similar columns
        group_match = re.search(r'GROUP BY\s+(.+?)(?:HAVING|ORDER|LIMIT|$)', sql_upper, re.DOTALL)
        order_match = re.search(r'ORDER BY\s+(.+?)(?:LIMIT|$)', sql_upper, re.DOTALL)
        
        if group_match and order_match:
            group_clause = group_match.group(1)
            order_clause = order_match.group(1)
            
            # Extract column names
            group_cols = set(re.findall(r'\b\w+\b', group_clause.upper()))
            order_cols = set(re.findall(r'\b\w+\b', order_clause.upper()))
            
            # Recommend if there's significant overlap
            if len(group_cols & order_cols) >= 1:
                rules.append("Aggregation Merge")
    
    # 3. Check for UNION Sort Transpose (only if worth it)
    if has_union and has_order_by:
        # Count UNION occurrences - only worth it with multiple branches
        union_count = sql_upper.count("UNION")
        if union_count >= 1:  # At least 2 branches
            rules.append("UNION Sort Transpose")
    
    # 4. Check for Limit Pushdown (good for aggregates)
    if has_limit and (has_union or has_order_by):
        # Only recommend if there's aggregation or sorting that could benefit
        if has_group_by or has_order_by:
            rules.append("Limit Pushdown")
    
    # 5. Check for Subquery to JOIN conversion (careful - can be expensive)
    if has_subquery and re.search(r'\bIN\s*\(\s*SELECT\b', sql_upper):
        # Only recommend for small result sets
        if "LIMIT" in sql_upper:  # Assumes subquery is bounded
            rules.append("Subquery to JOIN")
    
    # 6. Check for Constant Folding (safe, low cost)
    if re.search(r'\d+\s*[\+\-\*\/]\s*\d+', sql_upper):
        rules.append("Constant Folding")
    
    # 7. Check for Join Reordering (only worth it with 3+ tables)
    if sql_upper.count('JOIN') >= 2 or (sql_upper.count(',') >= 2 and has_where):
        # Only recommend if there are selective filters
        if has_where:
            rules.append("Join Reordering")

    # 8. Check for Having to Where
    if "HAVING" in sql_upper:
        having_match = re.search(r'HAVING\s+(.+)', sql_upper)
        if having_match:
            having_clause = having_match.group(1)
            # if no aggregation functions in having, recommend Having to Where
            if not any(agg in having_clause for agg in ['SUM(', 'COUNT(', 'AVG(', 'MAX(', 'MIN(']):
                rules.append("Having to Where")

    # 9. Check for Distinct to Group By
    if "SELECT DISTINCT" in sql_upper and "GROUP BY" not in sql_upper:
        rules.append("Distinct to Group By")

    # 10. Check for Cross Join Opt
    if "CROSS JOIN" in sql_upper or ("," in sql_upper and "JOIN" not in sql_upper and has_where):
        rules.append("Cross Join Opt")

    # 11. Check for Like to Instr
    if "LIKE" in sql_upper:
        rules.append("Like to Instr")

    # Remove duplicates while preserving order
    seen = set()
    unique_rules = []
    for rule in rules:
        if rule not in seen:
            seen.add(rule)
            unique_rules.append(rule)
    rules = unique_rules
    
    # If no rules found, mark as EMPTY
    if not rules:
        rules.append("EMPTY")
    
    return rules


def simulate_prediction(sql: str) -> Tuple[List[str], float, float]:
    """
    Simulate Gemini prediction using structural SQL analysis.
    Returns (mapped_rules, similarity_score, latency_seconds).
    The rules returned are actual function rule names like "FILTER_INTO_JOIN".
    """
    # Select best demo for similarity reporting
    demo, similarity = select_demo(sql)
    
    # Simulate API thinking time
    time.sleep(0.05)  # 50ms simulation
    
    # Analyze query structure to recommend rules (returns LLM-style names)
    llm_rules = _analyze_query_structure(sql)
    
    # Map LLM rule names to actual function names
    mapped_rules = [LLM_TO_FUNCTION_RULE_MAP.get(rule, rule) for rule in llm_rules]
    
    return mapped_rules, similarity, 0.05

# =============================================================================
# Main API - predict_rules()
# =============================================================================

def predict_rules(
    sql: str,
    api_key: Optional[str] = None,
    config: Optional["Config"] = None,
    sample_idx: int = 0
) -> Dict[str, Any]:
    """
    Main entry point for rule prediction.
    Supports multiple LLM providers: Gemini, Ollama, or simulation.

    Args:
        sql: The SQL query to analyze
        api_key: Optional Gemini API key (falls back to GEMINI_API_KEY env var)
        config: Optional LLMConfig object with provider settings
                If None, uses environment variables and defaults
        sample_idx: Used to pass variations to the system prompt

    Returns:
        Dict with keys:
            - rules: List of recommended rule names
            - llm_latency_sec: Time taken for prediction
            - used_simulation: Whether simulation was used
            - similarity: ICL demo similarity score
    """
    # Load config if not provided
    if config is None:
        try:
            from config import LLM_CONFIG
            config = LLM_CONFIG
        except ImportError:
            print("[⚠️ WARNING] Could not load LLM_CONFIG from config.py")
            config = None

    # Select demonstration for potential API call
    demo, similarity = select_demo(sql)

    # Build prompt (used by API, not simulation)
    prompt = build_prompt(sql, demo, sample_idx=sample_idx)

    # Get API key from parameter or environment
    api_key = (
        api_key
        or os.environ.get("GEMINI_API_KEY")
    )
    
    # Determine which provider to use
    provider = "simulation"  # default
    if config:
        provider = getattr(config, "llm_provider", "simulation")
    
    # Try Gemini API if configured
    if provider == "gemini" and api_key and GENAI_AVAILABLE:
        try:
            print(f"[✓ USING REAL GEMINI API] Calling gemini-2.0-pro with {len(prompt)} chars")
            response_text, latency = call_gemini_api(prompt, api_key)
            rules = parse_response(response_text)
            print(f"[✓ GEMINI RESPONSE] Got {len(rules)} rule(s): {rules} (latency: {latency:.3f}s)")
            
            return {
                "rules": rules,
                "llm_latency_sec": latency,
                "used_simulation": False,
                "similarity": similarity
            }
        except Exception as e:
            print(f"[✗ GEMINI ERROR] {e}")
            print(f"[→ FALLING BACK TO SIMULATION MODE]")
    
    # Try Ollama if configured
    elif provider == "ollama" and config and OLLAMA_AVAILABLE:
        try:
            print(f"[✓ USING OLLAMA] Calling {config.ollama_model} at {config.ollama_base_url}")
            response_text, latency = call_ollama_api(prompt, config)
            rules = parse_response(response_text)
            print(f"[✓ OLLAMA RESPONSE] Got {len(rules)} rule(s): {rules} (latency: {latency:.3f}s)")
            
            return {
                "rules": rules,
                "llm_latency_sec": latency,
                "used_simulation": False,
                "similarity": similarity
            }
        except Exception as e:
            print(f"[✗ OLLAMA ERROR] {e}")
            print(f"[→ FALLING BACK TO SIMULATION MODE]")
    
    # No LLM provider available, warn about why
    else:
        if provider == "gemini":
            if not api_key:
                print(f"[⚠ NO API KEY] GEMINI_API_KEY not set - using SIMULATION mode")
            if not GENAI_AVAILABLE:
                print(f"[⚠ LIBRARY NOT INSTALLED] google-genai not available - using SIMULATION mode")
        elif provider == "ollama":
            if not OLLAMA_AVAILABLE:
                print(f"[⚠ LIBRARY NOT INSTALLED] requests not available - using SIMULATION mode")
            elif not config:
                print(f"[⚠ NO CONFIG] LLMConfig not loaded - using SIMULATION mode")
    
    # Fall back to simulation
    print(f"[! SIMULATION MODE] Using structural analysis for rule prediction")
    rules, similarity, latency = simulate_prediction(sql)
    
    return {
        "rules": rules,
        "llm_latency_sec": latency,
        "used_simulation": True,
        "similarity": similarity
    }

# =============================================================================
# Rule Description Helper
# =============================================================================

def get_rule_descriptions_text() -> str:
    """
    Return a formatted string describing all available rewrite rules.
    """
    return """
Filter Pushdown:
    Move filters closer to scans. Example: pushing WHERE conditions
    on individual tables before JOIN operations.

Aggregation Merge:
    Merge aggregation and ordering operations. Example: combining
    GROUP BY with ORDER BY when they operate on the same columns.

UNION Sort Transpose:
    Push ORDER BY into UNION branches. Example: sorting each
    UNION subquery individually instead of the combined result.

Predicate Move-Around:
    Reorder predicates for better selectivity. Example: moving
    more selective filters earlier in the execution plan.

Join Reordering:
    Reorder joins for better execution. Example: joining smaller
    tables first to reduce intermediate result sizes.

Subquery to JOIN:
    Convert correlated subqueries to JOINs. Example: replacing
    WHERE EXISTS subqueries with explicit JOIN operations.

Limit Pushdown:
    Push LIMIT into subqueries. Example: limiting rows earlier
    in the query plan to reduce data processing.

Constant Folding:
    Evaluate constants at compile time. Example: pre-computing
    arithmetic expressions like 'price * 1.1' as constants.

Having to Where:
    Move HAVING clause conditions to WHERE when possible.
    Example: filtering on aggregated values before the aggregation.

Distinct to Group By:
    Convert SELECT DISTINCT to GROUP BY with COUNT.
    Example: replacing DISTINCT queries with GROUP BY aggregations.

Cross Join Opt:
    Optimize CROSS JOINs with filters into INNER JOINs.
    Example: converting CROSS JOINs with conditions to INNER JOINs.

Like to Instr:
    Replace LIKE with INSTR for performance.
    Example: translating LIKE patterns to INSTR function calls.
"""