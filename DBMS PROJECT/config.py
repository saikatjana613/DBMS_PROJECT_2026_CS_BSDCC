"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  config.py — Central Configuration for the LLM-R2 Query Rewrite System    ║
╚══════════════════════════════════════════════════════════════════════════════╝

PURPOSE:
    Single source of truth for the entire LLM-R2 system.
    Every other file imports constants, rules, and queries from here.
    A change here automatically propagates to all modules.

WHAT THIS FILE DOES:
    Stores every shared constant, configuration parameter, rule definition,
    and benchmark query in ONE place so that no other file needs to hard-code
    these values. All other modules (main_pipeline.py, db_setup.py,
    rewrite_rules.py, gemini_interface.py) import directly from here.

APPROACH:
    Single source of truth for the entire LLM-R2 system. All constants,
    rule definitions, and benchmark queries are defined here and imported
    by other modules. No duplication anywhere.

HOW IT WORKS:
    1. Config dataclass      — holds runtime parameters (DB path, API key,
                               timing, results directory, demo settings).
    2. VALID_RULES dict      — maps each of the 10 Apache Calcite rewrite-rule
                               names to a human-readable explanation.
    3. BENCHMARK_QUERIES     — organises the TPC-H, IMDB/JOB, and DSB test
                               queries the pipeline evaluates.
    4. Helper functions      — get_rule_names(), get_rule_description(),
                               get_rule_descriptions_text() used by the
                               Gemini prompt builder.
    5. Table name lists      — TPCH_TABLES, IMDB_TABLES, DSB_TABLES for
                               schema validation and introspection.

CONTENTS:
    - Config dataclass          : DB path, API settings, timing params, results dir
    - VALID_RULES               : 10 Apache Calcite rewrite rules with descriptions
    - TPCH_QUERIES              : 5 TPC-H benchmark SQL queries
    - IMDB_QUERIES              : 3 IMDB/JOB benchmark SQL queries
    - DSB_QUERIES               : 3 DSB benchmark SQL queries
    - BENCHMARK_QUERIES         : All queries grouped by benchmark name
    - TPCH_TABLES / IMDB_TABLES / DSB_TABLES : Table name lists per benchmark

USED BY:
    ┌──────────────────────────────────────────────────────────────────────┐
    │  main_pipeline.py   ──► Config, VALID_RULES, BENCHMARK_QUERIES      │
    │  db_setup.py        ──► TPCH_TABLES, IMDB_TABLES, DSB_TABLES        │
    │  rewrite_rules.py   ──► VALID_RULES, get_rule_names()               │
    │  gemini_interface.py──► VALID_RULES, get_rule_descriptions_text()   │
    └──────────────────────────────────────────────────────────────────────┘
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List
import os


# =============================================================================
# CONFIGURATION DATACLASS
# =============================================================================

@dataclass
class Config:
    """
    Runtime configuration for the LLM-R2 system.

    Attributes:
        db_path            : Path to the SQLite benchmark database file.
        gemini_api_key     : Google Gemini API key. Reads from the
                             GEMINI_API_KEY environment variable by default.
        simulation_mode    : When True, Gemini calls are simulated locally
                             (no real API calls, no API key needed).
                             Set to False to use the real Gemini model.
        temperature        : Sampling temperature for Gemini (0.0 = fully
                             deterministic, best for reproducibility).
        max_tokens         : Maximum output tokens per Gemini response.
        n_timing_runs      : How many times each query is executed to get
                             a stable average execution time.
        timeout_seconds    : Maximum seconds allowed per query execution.
        results_dir        : Directory where JSON result files are saved.
        demo_method        : Strategy for selecting ICL demonstrations.
                             "similarity" uses semantic embedding search;
                             "random" picks randomly from the pool.
        max_demo_pool_size : Maximum number of demonstrations kept in the
                             ICL demonstration pool.
    """

    # ── Database ─────────────────────────────────────────────────────────
    db_path: str = "dbms_project.db"

    # ── LLM Configuration ────────────────────────────────────────────────
    # Choose one: "gemini", "ollama", or "simulation"
    llm_provider: str = "ollama"  # "gemini" | "ollama" | "simulation"

    # ── Gemini API ───────────────────────────────────────────────────────
    gemini_api_key: Optional[str] = field(
        default_factory=lambda: os.environ.get('GEMINI_API_KEY')
    )
    simulation_mode: bool = False    # Set False for real LLM calls (NOW ENABLED!)
    temperature: float = 0.3         # 0.3 = balanced reasoning (was 0.0 = frozen)
    max_tokens: int = 1024           # Increased from 200 for better reasoning

    # ── Ollama Local LLM ─────────────────────────────────────────────────
    ollama_model: str = "qwen2.5-coder:7b"    # e.g. "qwen2.5-coder:7b", "gemma4:e4b", "mistral", etc.
    ollama_base_url: str = "http://localhost:11434"  # Default Ollama endpoint
    ollama_temperature: float = 0.3
    ollama_top_p: float = 0.9

    # ── Timing ───────────────────────────────────────────────────────────
    n_timing_runs: int = 3           # Runs per query for averaging
    timeout_seconds: int = 30        # Per-query execution timeout

    # ── Results ──────────────────────────────────────────────────────────
    results_dir: str = "results"

    # ── Demonstration Pool (ICL) ─────────────────────────────────────────
    demo_method: str = "similarity"  # "similarity" | "random"
    max_demo_pool_size: int = 100

    # ─────────────────────────────────────────────────────────────────────
    def __post_init__(self) -> None:
        """Ensure the results directory exists on startup."""
        os.makedirs(self.results_dir, exist_ok=True)

    def is_api_ready(self) -> bool:
        """Return True if Gemini API key is set and simulation is off."""
        return (not self.simulation_mode) and bool(self.gemini_api_key)

    def summary(self) -> str:
        """Return a human-readable summary of the current config."""
        mode = "REAL API" if self.is_api_ready() else "SIMULATION"
        return (
            f"Config Summary\n"
            f"  DB Path        : {self.db_path}\n"
            f"  Gemini Mode    : {mode}\n"
            f"  Temperature    : {self.temperature}\n"
            f"  Max Tokens     : {self.max_tokens}\n"
            f"  Timing Runs    : {self.n_timing_runs}\n"
            f"  Timeout        : {self.timeout_seconds}s\n"
            f"  Results Dir    : {self.results_dir}\n"
            f"  Demo Method    : {self.demo_method}\n"
            f"  Demo Pool Size : {self.max_demo_pool_size}"
        )


# =============================================================================
# VALID REWRITE RULES — 10 Apache Calcite Rules
# =============================================================================

VALID_RULES: Dict[str, str] = {
    # ── Filter / Predicate Rules ─────────────────────────────────────────
    "FILTER_INTO_JOIN":
        "Push WHERE filter inside JOIN to reduce rows before joining.",

    "JOIN_EXTRACT_FILTER":
        "Extract filter from JOIN ON clause for independent optimization.",

    # ── Aggregation Rules ────────────────────────────────────────────────
    "AGGREGATE_PROJECT_MERGE":
        "Merge outer SELECT with GROUP BY subquery into a single pass.",

    "AGGREGATE_UNION_AGGREGATE":
        "Push aggregation through UNION to avoid double aggregation.",

    # ── Sorting Rules ────────────────────────────────────────────────────
    "SORT_REMOVE":
        "Remove ORDER BY when data is already sorted on primary key / indexed column.",                                                                                 

    "SORT_UNION_TRANSPOSE":
        "Push SORT into UNION branches for merge-sort instead of a global sort.",   

    "SORT_PROJECT_TRANSPOSE":
        "Push SORT below Project so sorting operates on fewer columns.",

    # ── Projection / Plan Rules ──────────────────────────────────────────
    "PROJECT_TO_CALC":
        "Convert Project node to Calc node for downstream rule chaining (plan-level).",                                                                                

    # ── Join Rules ───────────────────────────────────────────────────────
    "JOIN_COMMUTE":
        "Swap join inputs so the smaller table becomes the build side of a hash join.",                                                                                

    # ── New SQLite Specific Advanced Rules ─────────────────────────────────
    "HAVING_TO_WHERE":
        "Move a HAVING clause that does not contain aggregation into the WHERE clause.",

    "DISTINCT_TO_GROUP_BY":
        "Rewrite SELECT DISTINCT to a GROUP BY equivalent which can be faster in SQLite.",

    "CROSS_JOIN_OPT":
        "Force a left-to-right evaluation plan in SQLite by explicitly declaring CROSS JOIN.",

    "LIKE_TO_INSTR":
        "Transform an un-anchored LIKE predicate (e.g., LIKE '%word%') into an INSTR() > 0 call.",

    # ── No-op ────────────────────────────────────────────────────────────
    "EMPTY":
        "No rewrite needed — query is already optimal.",
}


# ── Helper Functions ──────────────────────────────────────────────────────────

def get_rule_names() -> List[str]:
    """Return an ordered list of all valid rule names."""
    return list(VALID_RULES.keys())


def get_rule_description(rule_name: str) -> str:
    """
    Return the human-readable description for a single rule.

    Args:
        rule_name: One of the 10 rule keys in VALID_RULES.

    Returns:
        Description string, or 'Unknown rule' if key not found.
    """
    return VALID_RULES.get(rule_name, "Unknown rule")


def get_rule_descriptions_text() -> str:
    """
    Return a formatted multiline string of all rules and their descriptions.
    Used directly in the Gemini ICL prompt template.

    Example output:
        - FILTER_INTO_JOIN: Push WHERE filter inside JOIN ...
        - JOIN_EXTRACT_FILTER: Extract filter from JOIN ON clause ...
        ...
    """
    return "\n".join(
        [f"  - {name}: {desc}" for name, desc in VALID_RULES.items()]
    )


def is_valid_rule(rule_name: str) -> bool:
    """Return True if rule_name is one of the 10 known rules."""
    return rule_name in VALID_RULES


def filter_valid_rules(rules: List[str]) -> List[str]:
    """
    Filter a list of rule names, keeping only those that exist in VALID_RULES.

    Args:
        rules: Raw list of rule names (e.g., parsed from Gemini response).

    Returns:
        List containing only valid, known rule names.
    """
    return [r for r in rules if is_valid_rule(r)]


# =============================================================================
# BENCHMARK QUERIES
# =============================================================================

# ── TPC-H Queries (5 queries) ────────────────────────────────────────────────
# Decision Support Benchmark — tests filter pushdown, multi-table joins,
# aggregations, and sort operations.

TPCH_QUERIES: Dict[str, str] = {

    "Q1 - Customer Orders": """
        SELECT c.c_name, c.c_address, o.o_orderkey, o.o_totalprice
        FROM tpch_customer c, tpch_orders o
        WHERE c.c_custkey = o.o_custkey
          AND c.c_mktsegment = 'AUTOMOBILE'
          AND o.o_totalprice > 1000
    """,
    # Expected rules: FILTER_INTO_JOIN (push c_mktsegment filter into join)

    "Q2 - Lineitem Aggregation": """
        SELECT l.l_orderkey,
               SUM(l.l_quantity)      AS total_qty,
               SUM(l.l_extendedprice) AS total_price
        FROM tpch_lineitem l
        GROUP BY l.l_orderkey
        ORDER BY total_price DESC
    """,
    # Expected rules: AGGREGATE_PROJECT_MERGE, SORT_PROJECT_TRANSPOSE

    "Q3 - Three Table Join": """
        SELECT c.c_name, o.o_orderdate, l.l_extendedprice
        FROM tpch_customer c, tpch_orders o, tpch_lineitem l
        WHERE c.c_custkey = o.o_custkey
          AND l.l_orderkey = o.o_orderkey
          AND c.c_mktsegment = 'BUILDING'
          AND o.o_orderdate > '1995-01-01'
    """,
    # Expected rules: FILTER_INTO_JOIN, JOIN_COMMUTE

    "Q4 - Regional Revenue": """
        SELECT n.n_name,
               SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
        FROM tpch_customer c, tpch_orders o, tpch_lineitem l, tpch_nation n
        WHERE c.c_custkey = o.o_custkey
          AND l.l_orderkey = o.o_orderkey
          AND c.c_nationkey = n.n_nationkey
        GROUP BY n.n_name
        ORDER BY revenue DESC
    """,
    # Expected rules: FILTER_INTO_JOIN, AGGREGATE_PROJECT_MERGE

    "Q5 - Priority Order Revenue": """
        SELECT l.l_orderkey,
               SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue,
               o.o_orderdate
        FROM tpch_customer c, tpch_orders o, tpch_lineitem l
        WHERE c.c_mktsegment = 'AUTOMOBILE'
          AND c.c_custkey = o.o_custkey
          AND l.l_orderkey = o.o_orderkey
          AND o.o_orderdate < '1995-03-07'
        GROUP BY l.l_orderkey, o.o_orderdate
    """,
    # Expected rules: FILTER_INTO_JOIN, AGGREGATE_PROJECT_MERGE
}


# ── IMDB / JOB Queries (3 queries) ───────────────────────────────────────────
# Join Order Benchmark — tests complex multi-join reordering and filter pushdown
# on the Internet Movie Database schema.

IMDB_QUERIES: Dict[str, str] = {

    "JOB1 - Movie Production": """
        SELECT MIN(t.title) AS movie_title
        FROM imdb_title t, imdb_movie_companies mc, imdb_company_type ct
        WHERE t.id = mc.movie_id
          AND ct.id = mc.company_type_id
          AND ct.kind = 'production companies'
    """,
    # Expected rules: FILTER_INTO_JOIN (push ct.kind filter)

    "JOB2 - Cast Information": """
        SELECT t.title, t.production_year
        FROM imdb_title t, imdb_cast_info ci
        WHERE t.id = ci.movie_id
          AND t.production_year > 2000
    """,
    # Expected rules: FILTER_INTO_JOIN (push production_year filter)

    "JOB3 - Movie Keywords": """
        SELECT t.title, k.keyword
        FROM imdb_title t, imdb_movie_keyword mk, imdb_keyword k
        WHERE t.id = mk.movie_id
          AND mk.keyword_id = k.id
          AND k.keyword LIKE '%murder%'
    """,
    # Expected rules: FILTER_INTO_JOIN (push keyword LIKE filter)
}


# ── DSB Queries (3 queries) ───────────────────────────────────────────────────
# Decision Support Benchmark — tests aggregation pushdown, demographic joins,
# and date-based grouping.

DSB_QUERIES: Dict[str, str] = {

    "DSB1 - Store Sales by Category": """
        SELECT i.i_category,
               SUM(ss.ss_sales_price) AS total_sales
        FROM dsb_store_sales ss, dsb_item i, dsb_date_dim d
        WHERE ss.ss_item_sk = i.i_item_sk
          AND ss.ss_sold_date_sk = d.d_date_sk
          AND d.d_year = 2002
        GROUP BY i.i_category
    """,
    # Expected rules: FILTER_INTO_JOIN, AGGREGATE_PROJECT_MERGE

    "DSB2 - Customer Demographics": """
        SELECT cd.cd_education_status,
               COUNT(*) AS customer_count
        FROM dsb_customer c, dsb_customer_demographics cd
        WHERE c.c_current_cdemo_sk = cd.cd_demo_sk
        GROUP BY cd.cd_education_status
    """,
    # Expected rules: AGGREGATE_PROJECT_MERGE

    "DSB3 - Store Sales by Date": """
        SELECT d.d_year, d.d_moy,
               SUM(ss.ss_quantity) AS total_qty
        FROM dsb_store_sales ss, dsb_date_dim d
        WHERE ss.ss_sold_date_sk = d.d_date_sk
        GROUP BY d.d_year, d.d_moy
        ORDER BY d.d_year, d.d_moy
    """,
    # Expected rules: AGGREGATE_PROJECT_MERGE, SORT_PROJECT_TRANSPOSE
}


# ── All Benchmark Queries (grouped) ──────────────────────────────────────────

BENCHMARK_QUERIES: Dict[str, Dict[str, str]] = {
    "TPC-H": TPCH_QUERIES,
    "IMDB":  IMDB_QUERIES,
    "DSB":   DSB_QUERIES,
}


# =============================================================================
# DATABASE TABLE LISTS
# =============================================================================
# Used for schema validation, introspection, and display.

TPCH_TABLES: List[str] = [
    "tpch_region",
    "tpch_nation",
    "tpch_customer",
    "tpch_orders",
    "tpch_lineitem",
    "tpch_supplier",
    "tpch_part",
    "tpch_partsupp",
]

IMDB_TABLES: List[str] = [
    "imdb_kind_type",
    "imdb_company_type",
    "imdb_role_type",
    "imdb_info_type",
    "imdb_link_type",
    "imdb_comp_cast_type",
    "imdb_keyword",
    "imdb_company_name",
    "imdb_name",
    "imdb_char_name",
    "imdb_title",
    "imdb_cast_info",
    "imdb_movie_companies",
    "imdb_movie_info",
    "imdb_movie_info_idx",
    "imdb_movie_keyword",
    "imdb_movie_link",
    "imdb_aka_name",
    "imdb_aka_title",
    "imdb_person_info",
    "imdb_complete_cast",
]

DSB_TABLES: List[str] = [
    "dsb_date_dim",
    "dsb_item",
    "dsb_store",
    "dsb_customer",
    "dsb_customer_demographics",
    "dsb_store_sales",
]

ALL_TABLES: List[str] = TPCH_TABLES + IMDB_TABLES + DSB_TABLES


# =============================================================================
# BACKWARD-COMPATIBILITY ALIAS
# =============================================================================
# rewrite_rules.py and other older modules import RULE_DESCRIPTIONS.
# This alias keeps them working without any changes.

RULE_DESCRIPTIONS = VALID_RULES


# =============================================================================
# DEMO POOL — Pre-built (query → rules) demonstrations for ICL Prompting
# =============================================================================
# gemini_interface.py imports DEMO_POOL directly from here.
# Each entry is a dict with:
#   query       : example SQL query
#   rules       : list of known-good rule names for that query
#   explanation : human-readable rationale (included in the Gemini prompt)

DEMO_POOL: List[Dict] = [
    {
        "query": (
            "SELECT c.name, SUM(o.amount) "
            "FROM customers c, orders o "
            "WHERE c.city = 'Delhi' AND c.id = o.cust_id "
            "GROUP BY c.name"
        ),
        "rules": ["FILTER_INTO_JOIN", "AGGREGATE_PROJECT_MERGE"],
        "explanation": (
            "Filter city='Delhi' pushed before join reduces rows 5x. "
            "Aggregate+Project merged into single pass."
        ),
    },
    {
        "query": (
            "SELECT l_orderkey, "
            "SUM(l_extendedprice * (1 - l_discount)) AS revenue, "
            "o_orderdate "
            "FROM tpch_customer, tpch_orders, tpch_lineitem "
            "WHERE c_mktsegment = 'AUTOMOBILE' "
            "AND c_custkey = o_custkey "
            "AND l_orderkey = o_orderkey "
            "GROUP BY l_orderkey, o_orderdate "
            "ORDER BY revenue DESC"
        ),
        "rules": ["FILTER_INTO_JOIN", "AGGREGATE_PROJECT_MERGE"],
        "explanation": (
            "Segment filter pushed before 3-way join. "
            "Aggregate+Project merged."
        ),
    },
    {
        "query": (
            "SELECT s_name, COUNT(*) "
            "FROM tpch_supplier, tpch_nation "
            "WHERE s_nationkey = n_nationkey "
            "AND n_name = 'GERMANY' "
            "GROUP BY s_name ORDER BY s_name"
        ),
        "rules": ["FILTER_INTO_JOIN", "SORT_REMOVE"],
        "explanation": "Nation filter pushed down. Sort removed if indexed.",
    },
    {
        "query": (
            "SELECT t.title, mc.note "
            "FROM imdb_title t JOIN imdb_movie_companies mc "
            "ON t.id = mc.movie_id AND mc.company_type_id = 1"
        ),
        "rules": ["JOIN_EXTRACT_FILTER"],
        "explanation": (
            "company_type_id filter extracted from ON clause "
            "for independent pushdown."
        ),
    },
    {
        "query": (
            "SELECT id, title FROM imdb_title "
            "UNION ALL "
            "SELECT id, title FROM imdb_aka_title "
            "ORDER BY title"
        ),
        "rules": ["SORT_UNION_TRANSPOSE"],
        "explanation": (
            "Global ORDER BY pushed into each UNION branch "
            "for cheaper merge sort."
        ),
    },
    {
        "query": "SELECT * FROM tpch_part ORDER BY p_partkey",
        "rules": ["SORT_REMOVE"],
        "explanation": (
            "ORDER BY on primary key (already sorted in "
            "B-tree index) is redundant."
        ),
    },
    {
        "query": (
            "SELECT p_brand, COUNT(*) "
            "FROM tpch_part, tpch_partsupp "
            "WHERE p_partkey = ps_partkey "
            "GROUP BY p_brand"
        ),
        "rules": ["EMPTY"],
        "explanation": "Query already optimal — no applicable rewrite.",
    },
    {
        "query": (
            "SELECT city, total FROM ("
            "SELECT c.c_mktsegment AS city, SUM(o.o_totalprice) AS total "
            "FROM tpch_customer c JOIN tpch_orders o ON c.c_custkey = o.o_custkey "
            "GROUP BY c.c_mktsegment) t"
        ),
        "rules": ["AGGREGATE_PROJECT_MERGE"],
        "explanation": (
            "Outer SELECT wrapper removed — inner query "
            "already produces final result."
        ),
    },
]

# =============================================================================
# Global Configuration Instance
# =============================================================================

LLM_CONFIG = Config()
