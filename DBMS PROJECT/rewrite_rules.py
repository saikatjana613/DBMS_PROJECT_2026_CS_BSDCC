"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  rewrite_rules.py — SQL Query Rewrite Rule Engine                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

PURPOSE:
    Implements all 10 Apache Calcite-inspired SQL rewrite rules as pure
    Python functions that transform SQL text into an equivalent but
    potentially faster form.

WHAT THIS FILE DOES:
    Provides a rule engine that takes a SQL query and a list of rule names,
    applies each rule's regex-based transformation in sequence, and returns
    the rewritten SQL along with which rules actually changed the query.

APPROACH:
    Each rule is a function  apply_<rule_name>(sql) -> (new_sql, changed)
    that uses regex pattern matching to detect rewritable structures in
    the SQL string and returns the transformed SQL plus a boolean flag.

HOW IT WORKS:
    • The RULE_FUNCTIONS dictionary maps rule names to their functions.
    • apply_rules(sql, rule_names) applies a sequence of rules in order,
      tracking which ones actually changed the query.

    Implemented rules that actively rewrite SQL text:
        1. FILTER_INTO_JOIN        — pushes WHERE filters before the join
        2. JOIN_EXTRACT_FILTER     — separates join key from extra filters
        3. AGGREGATE_PROJECT_MERGE — removes redundant outer SELECT wrapper
        4. SORT_REMOVE             — drops ORDER BY on indexed/key columns
        5. SORT_UNION_TRANSPOSE    — pushes sort into UNION branches

    Plan-level-only rules (no SQL text change, but included for completeness):
        6. PROJECT_TO_CALC
        7. AGGREGATE_UNION_AGGREGATE
        8. SORT_PROJECT_TRANSPOSE
        9. JOIN_COMMUTE

CONNECTION TO OTHER FILES:
    ┌──────────────────────────────────────────────────────────────────────┐
    │  Imports VALID_RULES from config.py                                 │
    │  Called by main_pipeline.py after Gemini recommends rules           │
    │  get_rule_descriptions_text() used by gemini_interface.py           │
    └──────────────────────────────────────────────────────────────────────┘

AIM:
    Provide a self-contained rule engine that the main pipeline calls after
    Gemini recommends which rules to apply to a given query.
"""

import re
from typing import List, Tuple

from config import VALID_RULES


# =============================================================================
# Rule 1: FILTER_INTO_JOIN (Selection Pushdown)
# =============================================================================

def apply_filter_into_join(sql: str) -> Tuple[str, bool]:
    """
    Push WHERE filters down BEFORE the join so fewer rows enter the join.

    Handles N-table comma-joins (2, 3, 4, or more tables).

    BEFORE (2-table):
        SELECT c.c_name, o.o_orderkey FROM tpch_customer c, tpch_orders o
        WHERE c.c_custkey = o.o_custkey AND c.c_mktsegment = 'AUTOMOBILE'
              AND o.o_totalprice > 1000
    AFTER:
        SELECT c.c_name, o.o_orderkey
        FROM (SELECT * FROM tpch_customer WHERE c_mktsegment = 'AUTOMOBILE') AS c
        INNER JOIN (SELECT * FROM tpch_orders WHERE o_totalprice > 1000) AS o
        ON c.c_custkey = o.o_custkey

    BEFORE (3-table):
        SELECT c.c_name, o.o_orderdate, l.l_extendedprice
        FROM tpch_customer c, tpch_orders o, tpch_lineitem l
        WHERE c.c_custkey = o.o_custkey AND l.l_orderkey = o.o_orderkey
              AND c.c_mktsegment = 'BUILDING' AND o.o_orderdate > '1995-01-01'
    AFTER:
        SELECT c.c_name, o.o_orderdate, l.l_extendedprice
        FROM (SELECT * FROM tpch_customer WHERE c_mktsegment = 'BUILDING') AS c,
             (SELECT * FROM tpch_orders WHERE o_orderdate > '1995-01-01') AS o,
             tpch_lineitem l
        WHERE c.c_custkey = o.o_custkey AND l.l_orderkey = o.o_orderkey

    Key detail: inside each pushed-down subquery the table alias does NOT
    exist yet, so 'c.c_mktsegment' must become 'c_mktsegment' (alias stripped).
    """
    sql_upper = sql.upper()
    if ' WHERE ' not in sql_upper:
        return sql, False

    # ── Parse: SELECT ... FROM table1 alias1, table2 alias2, ... WHERE ... ──
    pattern = r'(?i)(SELECT\s+.+?)\s+FROM\s+(.+?)\s+WHERE\s+(.+)'
    match = re.match(pattern, sql.strip(), re.DOTALL)
    if not match:
        return sql, False

    select_clause = match.group(1)
    from_clause = match.group(2).strip()
    where_and_rest = match.group(3).strip().rstrip(';')

    # ── Extract table entries from the FROM clause ───────────────────────────
    table_entries = re.findall(
        r'(?i)(\w+(?:\.\w+)?)(?:\s+AS)?\s+(\w+)',
        from_clause
    )
    if len(table_entries) < 2:
        return sql, False  # Single table, no join to push into

    tables = [(table, alias) for table, alias in table_entries]

    alias_set = {alias.lower() for _, alias in tables}

    # ── Separate trailing GROUP BY / ORDER BY / LIMIT from where_clause ──────
    trailing = ""
    for kw in ['GROUP BY', 'ORDER BY', 'LIMIT', 'HAVING']:
        idx = where_and_rest.upper().find(kw)
        if idx != -1:
            trailing = " " + where_and_rest[idx:]
            where_and_rest = where_and_rest[:idx].strip()
            break

    # ── Split WHERE conditions on AND ────────────────────────────────────────
    conditions = [c.strip() for c in re.split(r'\s+AND\s+', where_and_rest,
                                               flags=re.IGNORECASE)]

    # ── Classify conditions ──────────────────────────────────────────────────
    # For each condition, determine which aliases it references
    join_conds = []              # conditions referencing 2+ aliases (join conditions)
    table_filters = {}           # alias -> [conditions referencing only that alias]
    other_conds = []             # conditions that don't reference any known alias

    for cond in conditions:
        cond_lower = cond.lower()
        # Find which aliases appear in this condition
        refs = []
        for _, alias in tables:
            if alias.lower() + '.' in cond_lower:
                refs.append(alias)

        if len(refs) == 0:
            # No alias found — keep as-is in WHERE
            other_conds.append(cond)
        elif len(refs) == 1:
            # Single-table filter — candidate for pushdown
            alias = refs[0]
            table_filters.setdefault(alias, []).append(cond)
        else:
            # Multi-alias condition — join condition, keep in WHERE
            join_conds.append(cond)

    # ── Check if there are any filters to push down ──────────────────────────
    if not table_filters:
        return sql, False  # No single-table filters to push down

    # ── Helper: strip alias prefix for use inside subquery ───────────────────
    def strip_alias(conditions_list, alias):
        """Remove 'alias.' prefix so the filter works inside the subquery."""
        cleaned = []
        for c in conditions_list:
            cleaned.append(re.sub(
                r'(?i)\b' + re.escape(alias) + r'\.', '', c
            ))
        return cleaned

    # ── Build FROM sources ───────────────────────────────────────────────────
    new_from_parts = []
    for table_name, alias in tables:
        # Instead of wrapping in a subquery (which destroys SQLite indexes),
        # we keep the table as-is and will append its filters to the ON clause.
        src = f"{table_name} {alias}"
        new_from_parts.append(src)

    # ── Reconstruct query ────────────────────────────────────────────────────
    # Gather ALL conditions (join conditions + single-table filters + others)
    # We push the single table filters directly into the ON clause to ensure
    # indexes are preserved while enforcing early elimination in the join tree.
    all_on_conds = join_conds.copy()
    for alias, f_list in table_filters.items():
        all_on_conds.extend(f_list)
    remaining_where = other_conds

    if len(tables) == 2 and all_on_conds:
        # For 2-table joins, use INNER JOIN ... ON syntax
        new_sql = (f"{select_clause} FROM {new_from_parts[0]} "
                   f"INNER JOIN {new_from_parts[1]} "
                   f"ON {' AND '.join(all_on_conds)}")
        if remaining_where:
            new_sql += f" WHERE {' AND '.join(remaining_where)}"
    else:
        # For 3+ tables or if no ON conditions, just use WHERE with everything
        all_where = all_on_conds + remaining_where
        new_sql = (f"{select_clause} FROM {', '.join(new_from_parts)} "
                   f"WHERE {' AND '.join(all_where)}")

    # Append trailing clauses (GROUP BY, ORDER BY, etc.)
    new_sql += trailing

    return new_sql.rstrip(';') + ';', True


# =============================================================================
# Rule 2: JOIN_EXTRACT_FILTER
# =============================================================================

def apply_join_extract_filter(sql: str) -> Tuple[str, bool]:
    """
    Extract extra filter from JOIN ON clause so optimizer can push it down.

    BEFORE: SELECT * FROM t1 a JOIN t2 b ON a.id = b.id AND b.status = 'X'
    AFTER:  SELECT * FROM t1 a, t2 b WHERE a.id = b.id AND b.status = 'X'
    """
    pattern = (r'(?i)(SELECT\s+.+?)\s+FROM\s+(\w+)\s+(\w+)\s+'
               r'(?:INNER\s+)?JOIN\s+(\w+)\s+(\w+)\s+ON\s+(.+?)'
               r'(?:GROUP|ORDER|LIMIT|;|$)')
    match = re.search(pattern, sql, re.DOTALL)
    if not match:
        return sql, False

    on_clause = match.group(6).strip()
    conds = [c.strip() for c in re.split(r'\s+AND\s+', on_clause,
                                          flags=re.IGNORECASE)]
    if len(conds) <= 1:
        return sql, False

    select_part = match.group(1)
    t1, a1 = match.group(2), match.group(3)
    t2, a2 = match.group(4), match.group(5)
    where_str = ' AND '.join(conds)
    remainder = sql[match.end():]
    new_sql = f"{select_part} FROM {t1} {a1}, {t2} {a2} WHERE {where_str}{remainder}"
    return new_sql, True


# =============================================================================
# Rule 3: AGGREGATE_PROJECT_MERGE
# =============================================================================

def apply_constant_folding(sql: str) -> Tuple[str, bool]:
    """
    Constant-fold simple arithmetic expressions ONLY in SELECT projections.
    Avoid folding in WHERE/HAVING clauses to preserve filter semantics.
    """
    # Only fold expressions in SELECT...FROM part, not in WHERE/HAVING
    match = re.match(r'(?is)(SELECT\s+.+?)(\s+FROM\s+.+)', sql, re.DOTALL)
    if not match:
        return sql, False
    
    select_part = match.group(1)
    rest = match.group(2)
    
    def eval_match(m):
        left, op, right = m.group(1), m.group(2), m.group(3)
        try:
            left_val = float(left)
            right_val = float(right)
            if op == '+':
                res = left_val + right_val
            elif op == '-':
                res = left_val - right_val
            elif op == '*':
                res = left_val * right_val
            elif op == '/':
                if right_val == 0:
                    return m.group(0)
                res = left_val / right_val
            else:
                return m.group(0)
            if res.is_integer():
                return str(int(res))
            return str(res)
        except Exception:
            return m.group(0)
    
    # Only fold in SELECT list, not after FROM
    pattern = re.compile(r'\(?\s*([0-9]+(?:\.[0-9]+)?)\s*([+\-*/])\s*([0-9]+(?:\.[0-9]+)?)\s*\)?')
    new_select = select_part
    for _ in range(2):  # Max 2 iterations
        new_select = pattern.sub(eval_match, new_select)
    
    new_sql = new_select + rest
    return new_sql, new_sql != sql

# =============================================================================
# Rule 7: LIMIT_PUSH_DOWN
# =============================================================================

def apply_limit_push_down(sql: str) -> Tuple[str, bool]:
    """Push a global LIMIT into UNION ALL branches when ORDER BY is present."""
    sql_upper = sql.upper()
    if 'UNION ALL' not in sql_upper or 'ORDER BY' not in sql_upper or 'LIMIT' not in sql_upper:
        return sql, False
    order_match = re.search(r'(?i)ORDER\s+BY\s+(.+?)(?=\s+LIMIT\b|;|$)', sql)
    limit_match = re.search(r'(?i)LIMIT\s+(\d+)', sql)
    if not order_match or not limit_match:
        return sql, False
    order_clause = order_match.group(0).strip()
    limit_clause = limit_match.group(0).strip()
    union_sql = sql[:order_match.start()].strip().rstrip(';')
    union_parts = re.split(r'(?i)\s+UNION ALL\s+', union_sql, flags=re.IGNORECASE)
    if len(union_parts) < 2:
        return sql, False
    new_parts = []
    for part in union_parts:
        part = part.strip().rstrip(';')
        new_parts.append(f"({part} {order_clause} {limit_clause})")
    new_sql = f" {' UNION ALL '.join(new_parts)} {order_clause} {limit_clause};"
    return new_sql, True

# =============================================================================
# Rule 8: SUBQUERY_TO_JOIN
# =============================================================================

def apply_subquery_to_join(sql: str) -> Tuple[str, bool]:
    """Convert simple IN/EXISTS subqueries into equivalent joins."""
    if not re.search(r'(?i)\b(IN|EXISTS)\s*\(\s*SELECT\b', sql):
        return sql, False

    in_pattern = re.compile(
        r'(?is)(\b\w+\.?\w*\b)\s+IN\s*\(\s*SELECT\s+(\w+\.?\w*)\s+FROM\s+(\w+)(?:\s+AS)?\s+(\w+)\s+WHERE\s+(.+?)\)',
        flags=re.IGNORECASE
    )
    match = in_pattern.search(sql)
    if not match:
        return sql, False

    outer_col, inner_col, table, alias, sub_where = match.groups()
    join_clause = f"{outer_col} = {inner_col}"
    transformed = re.sub(
        in_pattern,
        '',
        sql,
        count=1
    )
    transformed = re.sub(
        r'(?i)FROM\s+(.+?)\s+WHERE',
        lambda m: f"FROM {m.group(1)}, {table} {alias} WHERE {join_clause} AND",
        transformed,
        count=1
    )
    if transformed != sql:
        return transformed, True
    return sql, False

# =============================================================================
# Rule 9: JOIN_COMMUTE
# =============================================================================

def apply_join_commute(sql: str) -> Tuple[str, bool]:
    """Reorder comma joins so the most selective tables appear first."""
    sql_upper = sql.upper()
    if ' FROM ' not in sql_upper or ' WHERE ' not in sql_upper:
        return sql, False
    match = re.search(r'(?is)(SELECT\s+.+?\s+FROM\s+)(.+?)\s+WHERE\s+(.+?)(?=\bGROUP BY\b|\bORDER BY\b|\bLIMIT\b|;|$)', sql)
    if not match:
        return sql, False
    select_part, from_clause, where_clause = match.groups()
    table_entries = [t.strip() for t in from_clause.split(',')]
    if len(table_entries) < 2:
        return sql, False
    alias_filters = {}
    for entry in table_entries:
        tokens = entry.split()
        alias = tokens[-1]
        alias_filters[alias] = 0
    conditions = [c.strip() for c in re.split(r'\s+AND\s+', where_clause, flags=re.IGNORECASE)]
    for cond in conditions:
        for alias in alias_filters:
            if re.search(rf'(?i)\b{re.escape(alias)}\.', cond):
                alias_filters[alias] += 1
    sorted_entries = sorted(
        table_entries,
        key=lambda entry: alias_filters.get(entry.split()[-1], 0),
        reverse=True
    )
    if sorted_entries == table_entries:
        return sql, False
    remainder = sql[match.end():]
    new_sql = f"{select_part}{', '.join(sorted_entries)} WHERE {where_clause}{remainder}"
    return new_sql, True

# =============================================================================
# Rule 7: AGGREGATE_UNION_AGGREGATE
# =============================================================================

def apply_aggregate_union_aggregate(sql: str) -> Tuple[str, bool]:
    """AGGREGATE_UNION_AGGREGATE — pushes aggregation through UNION in query plan."""
    return sql, False


# =============================================================================
# Rule 3: AGGREGATE_PROJECT_MERGE
# =============================================================================

def apply_aggregate_project_merge(sql: str) -> Tuple[str, bool]:
    """
    Remove unnecessary outer SELECT wrapper around a GROUP BY subquery.

    BEFORE: SELECT city, total FROM (SELECT c.city, SUM(o.amt) AS total
            FROM ... GROUP BY c.city) t
    AFTER:  SELECT c.city, SUM(o.amt) AS total FROM ... GROUP BY c.city
    """
    pattern = (r'(?i)SELECT\s+(\w+)\s*,\s*(\w+)\s+FROM\s*\(\s*'
               r'(SELECT\s+.+?GROUP\s+BY\s+.+?)\s*\)\s*(?:AS\s+)?\w+')
    match = re.search(pattern, sql, re.DOTALL)
    if match:
        inner = match.group(3).strip().rstrip(';')
        return inner + ';', True
    return sql, False


# =============================================================================
# Rule 4: SORT_REMOVE
# =============================================================================

def apply_sort_remove(sql: str) -> Tuple[str, bool]:
    """
    Remove ORDER BY when it references a primary-key / indexed column
    (already physically sorted).

    BEFORE: SELECT * FROM customers ORDER BY id
    AFTER:  SELECT * FROM customers
    """
    sql_upper = sql.upper()
    if 'ORDER BY' not in sql_upper:
        return sql, False

    after_order = sql_upper.split('ORDER BY')[1].split(';')[0]
    if any(k in after_order for k in ['_KEY', ' ID', '_SK']):
        new_sql = re.sub(
            r'\s+ORDER\s+BY\s+\w+(\.\w+)?\s*(ASC|DESC)?\s*',
            ' ', sql, flags=re.IGNORECASE)
        return new_sql.strip(), True
    return sql, False


# =============================================================================
# Rule 5: SORT_UNION_TRANSPOSE
# =============================================================================

def apply_sort_union_transpose(sql: str) -> Tuple[str, bool]:
    """
    Push a global ORDER BY into each UNION branch for cheaper merge sort.

    BEFORE: SELECT id FROM A UNION ALL SELECT id FROM B ORDER BY id
    AFTER:  (SELECT id FROM A ORDER BY id) UNION ALL
            (SELECT id FROM B ORDER BY id)
    """
    if 'UNION' not in sql.upper() or 'ORDER BY' not in sql.upper():
        return sql, False

    parts = re.split(r'\s+UNION\s+ALL\s+', sql, flags=re.IGNORECASE)
    if len(parts) != 2:
        return sql, False

    order_match = re.search(r'\s+ORDER\s+BY\s+(.+?)(?:;|$)',
                            parts[-1], re.IGNORECASE)
    if not order_match:
        return sql, False

    order_clause = order_match.group(0).rstrip(';').strip()
    clean_last = re.sub(r'\s+ORDER\s+BY\s+.+?(?:;|$)', '',
                        parts[-1], flags=re.IGNORECASE).strip()
    new_sql = (f"({parts[0].strip()} {order_clause}) "
               f"UNION ALL ({clean_last} {order_clause});")
    return new_sql, True

# =============================================================================
# Rule 8: SORT_PROJECT_TRANSPOSE
# =============================================================================

def apply_sort_project_transpose(sql: str) -> Tuple[str, bool]:
    """SORT_PROJECT_TRANSPOSE — pushes Sort below Project in query plan."""
    return sql, False


# =============================================================================
# Rule 9: PROJECT_TO_CALC
# =============================================================================

def apply_project_to_calc(sql: str) -> Tuple[str, bool]:
    """PROJECT_TO_CALC — fuses Filter+Project in the query plan. No text change."""
    return sql, False

# =============================================================================
# Newly Added Optimization Rules (SQLite Specific)
# =============================================================================

def apply_having_to_where(sql: str) -> Tuple[str, bool]:
    """Move non-aggregate filters from HAVING to WHERE."""
    upper_sql = sql.upper()
    if 'HAVING' not in upper_sql:
        return sql, False
    pattern = r'(?i)(.*?)\s+GROUP\s+BY\s+(.+?)\s+HAVING\s+(.+)'
    match = re.search(pattern, sql, re.DOTALL)
    if not match:
        return sql, False
    pre_group, group_by, having_clause = match.groups()
    if any(agg in having_clause.upper() for agg in ['SUM(', 'COUNT(', 'AVG(', 'MAX(', 'MIN(']):
        return sql, False
    if ' WHERE ' in pre_group.upper():
        new_pre = pre_group + f" AND {having_clause}"
    else:
        new_pre = pre_group + f" WHERE {having_clause}"
    return f"{new_pre} GROUP BY {group_by}".rstrip(';') + ';', True

def apply_distinct_to_group_by(sql: str) -> Tuple[str, bool]:
    """Convert SELECT DISTINCT into GROUP BY."""
    if 'DISTINCT' not in sql.upper():
        return sql, False
    pattern = r'(?i)(SELECT)\s+DISTINCT\s+(.+?)\s+FROM\s+(.+)'
    match = re.search(pattern, sql, re.DOTALL)
    if not match:
        return sql, False
    select_kw, cols, rest = match.groups()
    
    trailing = ""
    rest_upper = rest.upper()
    for kw in ['ORDER BY', 'LIMIT']:
        idx = rest_upper.find(kw)
        if idx != -1:
            trailing = " " + rest[idx:]
            rest = rest[:idx]
            rest_upper = rest_upper[:idx]
            break
            
    if 'GROUP BY' in rest_upper:
        return sql, False
        
    new_sql = f"{select_kw} {cols} FROM {rest} GROUP BY {cols}{trailing}"
    return new_sql.rstrip(';') + ';', True

def apply_cross_join_opt(sql: str) -> Tuple[str, bool]:
    """Forces left-to-right explicit join order in SQLite bypassing heuristic planner."""
    if ',' not in sql:
        return sql, False
    pattern = r'(?i)(FROM\s+)(.+?)(\s+WHERE\s+|\s+GROUP\s+BY\s+|\s+ORDER\s+BY\s+|$)'
    match = re.search(pattern, sql, re.DOTALL)
    if not match:
        return sql, False
    from_inner = match.group(2)
    if ',' in from_inner and 'JOIN' not in from_inner.upper():
        new_inner = from_inner.replace(',', ' CROSS JOIN ')
        new_sql = sql[:match.start(2)] + new_inner + sql[match.end(2):]
        return new_sql.rstrip(';') + ';', True
    return sql, False

def apply_like_to_instr(sql: str) -> Tuple[str, bool]:
    """Convert LIKE '%text%' to INSTR(col, 'text') > 0 which is faster in SQLite."""
    pattern = r"(?i)(\w+(?:\.\w+)?)\s+LIKE\s+'%([^%'\n]+)%'"
    if not re.search(pattern, sql):
        return sql, False
    new_sql = re.sub(pattern, r"INSTR(\1, '\2') > 0", sql)
    return new_sql, True


# =============================================================================
# Rule Function Registry
# =============================================================================

RULE_FUNCTIONS = {
    "FILTER_INTO_JOIN":          apply_filter_into_join,
    "JOIN_EXTRACT_FILTER":       apply_join_extract_filter,
    "AGGREGATE_PROJECT_MERGE":   apply_aggregate_project_merge,
    "SORT_REMOVE":               apply_sort_remove,
    "SORT_UNION_TRANSPOSE":      apply_sort_union_transpose,
    "CONSTANT_FOLDING":          apply_constant_folding,
    "LIMIT_PUSH_DOWN":           apply_limit_push_down,
    "SUBQUERY_TO_JOIN":          apply_subquery_to_join,
    "PROJECT_TO_CALC":           apply_project_to_calc,
    "AGGREGATE_UNION_AGGREGATE": apply_aggregate_union_aggregate,
    "SORT_PROJECT_TRANSPOSE":    apply_sort_project_transpose,
    "JOIN_COMMUTE":              apply_join_commute,
    "HAVING_TO_WHERE":           apply_having_to_where,
    "DISTINCT_TO_GROUP_BY":      apply_distinct_to_group_by,
    "CROSS_JOIN_OPT":            apply_cross_join_opt,
    "LIKE_TO_INSTR":             apply_like_to_instr,
}


# =============================================================================
# Public API
# =============================================================================

def apply_rules(sql: str, rule_names: List[str]) -> Tuple[str, List[str]]:
    """
    Apply a sequence of rewrite rules to a SQL query.

    Parameters
    ----------
    sql        : str        — the original SQL string
    rule_names : list[str]  — ordered list of rule names to try

    Returns
    -------
    (new_sql, applied) where applied is the list of rules that changed the SQL.
    """
    current_sql = sql
    applied = []
    for rule_name in rule_names:
        if rule_name == "EMPTY":
            continue
        func = RULE_FUNCTIONS.get(rule_name)
        if func:
            new_sql, changed = func(current_sql)
            if changed:
                current_sql = new_sql
                applied.append(rule_name)
    return current_sql, applied


def get_all_rule_names() -> List[str]:
    """Return list of all rule name strings."""
    return list(VALID_RULES.keys())


def get_rule_descriptions_text() -> str:
    """
    Return a formatted string of all rules for use in LLM prompts.

    Format:
        ["FILTER_INTO_JOIN": "Push WHERE filter inside JOIN ..."],
        ["JOIN_EXTRACT_FILTER": "Extract filter from JOIN ON clause ..."],
        ...
    """
    lines = []
    for name, desc in VALID_RULES.items():
        lines.append(f'["{name}": "{desc}"]')
    return ',\n'.join(lines)