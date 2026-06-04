"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  db_setup.py — Database Schema Creation & Synthetic Data Population        ║
╚══════════════════════════════════════════════════════════════════════════════╝

PURPOSE:
    Creates and populates all three benchmark databases (TPC-H, IMDB, DSB).

WHAT THIS FILE DOES:
    Creates three benchmark database schemas inside a single SQLite file
    and fills them with realistic synthetic data:
        1. TPC-H   — 8 tables  (region, nation, customer, orders, lineitem,
                                 supplier, part, partsupp)
        2. IMDB/JOB — 21 tables (title, cast_info, movie_companies, etc.)
        3. DSB     — 6 tables  (date_dim, item, store, customer,
                                 customer_demographics, store_sales)

APPROACH:
    Uses consistent table naming with prefixes (tpch_*, imdb_*, dsb_*).
    Reads table definitions from an external SQL schema file (all_schemas.sql)
    for production-grade schema with foreign keys, NOT NULL constraints, and
    indexes. Falls back to inline schema creation if the SQL file is missing.
    Generates synthetic data with realistic distributions (seeded at 42).

HOW IT WORKS:
    1. load_and_execute_schema() reads all_schemas.sql and executes every
       CREATE TABLE / CREATE INDEX statement against the SQLite connection.
    2. populate_tpch() / populate_imdb() / populate_dsb() insert synthetic
       rows using random (seeded at 42) for reproducibility.
    3. setup_all_databases() is the single entry point — it creates the DB,
       loads the schema, populates data, and returns the open connection.

CONNECTION TO all_schemas.sql:
    ┌─────────────────────────────────────────────────────────────────────────┐
    │  SQL Schema File : all_schemas.sql                                      │
    │  Location        : C:\\Users\\ASUS\\Desktop\\DBMS_PROJECT\\schemas\\    │
    │  Full Path       : C:\\Users\\ASUS\\Desktop\\DBMS_PROJECT\\schemas\\    │
    │                    all_schemas.sql                                      │
    │                                                                         │
    │  This file contains all CREATE TABLE and CREATE INDEX statements        │
    │  for the 35 benchmark tables (8 TPC-H + 21 IMDB + 6 DSB) with           │
    │  proper VARCHAR/DECIMAL types, FOREIGN KEY constraints, NOT NULL        │
    │  constraints, and 30+ performance indexes.                              │
    │                                                                         │
    │  db_setup.py reads this file at startup ──► executes each SQL           │
    │  statement ──► then populates the created tables with synthetic         │
    │  data using Python's random module.                                     │
    └─────────────────────────────────────────────────────────────────────────┘

CONTENTS:
    - load_and_execute_schema() — Reads all_schemas.sql and creates tables
    - populate_tpch()           — Inserts TPC-H synthetic data
    - populate_imdb()           — Inserts IMDB/JOB synthetic data
    - populate_dsb()            — Inserts DSB synthetic data
    - setup_all_databases()     — Single entry point for full setup
"""

import os
import sys
import sqlite3
import random

# ─── Reproducibility ─────────────────────────────────────────────────────────
random.seed(42)


# =============================================================================
# FILE PATHS — Connection between db_setup.py and all_schemas.sql
# =============================================================================

# The SQL schema file that defines all 35 benchmark tables, foreign keys,
# and performance indexes.  db_setup.py reads this file to create the
# database structure before populating it with synthetic data.
SCHEMA_DIR  = r"C:\Users\skh60\Downloads\DBMS PROJECT\schemas"
SCHEMA_FILE = os.path.join(SCHEMA_DIR, "all_schemas.sql")

# Default SQLite database output path
DEFAULT_DB_PATH = os.path.join(
    r"C:\Users\skh60\Downloads\DBMS PROJECT", "dbms_project.db"
)


# =============================================================================
# CONSTANTS — Shared reference data for synthetic generation
# =============================================================================

REGIONS = ['AFRICA', 'AMERICA', 'ASIA', 'EUROPE', 'MIDDLE EAST']

NATIONS = [
    'ALGERIA', 'ARGENTINA', 'BRAZIL', 'CANADA', 'EGYPT', 'ETHIOPIA',
    'FRANCE', 'GERMANY', 'INDIA', 'INDONESIA', 'IRAN', 'IRAQ', 'JAPAN',
    'JORDAN', 'KENYA', 'MOROCCO', 'MOZAMBIQUE', 'PERU', 'CHINA',
    'ROMANIA', 'SAUDI ARABIA', 'VIETNAM', 'RUSSIA',
    'UNITED KINGDOM', 'UNITED STATES',
]

MARKET_SEGMENTS = ['AUTOMOBILE', 'BUILDING', 'FURNITURE', 'HOUSEHOLD', 'MACHINERY']

PRIORITIES = ['1-URGENT', '2-HIGH', '3-MEDIUM', '4-NOT SPECIFIED', '5-LOW']

SHIP_MODES = ['REG AIR', 'AIR', 'RAIL', 'SHIP', 'TRUCK', 'MAIL', 'FOB']


# =============================================================================
# SCHEMA LOADER — Reads and executes all_schemas.sql
# =============================================================================

def load_and_execute_schema(conn: sqlite3.Connection,
                            schema_path: str = SCHEMA_FILE) -> bool:
    """
    Read the external SQL schema file and execute every statement.

    This function bridges db_setup.py ──► all_schemas.sql:
        1. Opens all_schemas.sql from the configured path.
        2. Strips out SQL comments (lines starting with '--').
        3. Splits the file on semicolons to isolate each statement.
        4. Executes each CREATE TABLE / CREATE INDEX statement.

    Args:
        conn:        Open sqlite3 connection to the target database.
        schema_path: Absolute path to all_schemas.sql.

    Returns:
        True if schema was loaded from file, False if fallback was used.
    """
    print(f"\n  ───────────────── Schema Source ──────────────────────────────")
    print(f"      File : all_schemas.sql                                      ")
    print(f"      Path : {schema_path}")
    if not os.path.exists(schema_path):
        print(f"\n  ⚠  Schema file NOT found at: {schema_path}")
        print(f"  ⚠  Falling back to inline schema creation...")
        _create_schemas_inline(conn)
        return False

    # Read the SQL file
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_sql = f.read()

    # Remove comment-only lines but preserve inline content
    lines = schema_sql.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip pure comment lines and decorative lines
        if stripped.startswith('--') or stripped.startswith('╔') or \
           stripped.startswith('║') or stripped.startswith('╚') or \
           stripped.startswith('='):
            continue
        cleaned_lines.append(line)

    cleaned_sql = '\n'.join(cleaned_lines)

    # Split into individual statements and execute
    statements = [s.strip() for s in cleaned_sql.split(';') if s.strip()]

    tables_created = 0
    indexes_created = 0
    errors = 0

    for stmt in statements:
        # Skip empty or whitespace-only statements
        if not stmt or stmt.isspace():
            continue
        try:
            conn.execute(stmt)
            if 'CREATE TABLE' in stmt.upper():
                tables_created += 1
            elif 'CREATE INDEX' in stmt.upper():
                indexes_created += 1
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                print(f"  ⚠  SQL Warning: {e}")
                errors += 1

    conn.commit()
    print(f"\n  ✓ Schema loaded from all_schemas.sql")
    print(f"    • {tables_created} tables created")
    print(f"    • {indexes_created} indexes created")
    if errors:
        print(f"    • {errors} warnings (non-fatal)")

    return True


def _create_schemas_inline(conn: sqlite3.Connection) -> None:
    """
    Fallback: create minimal schemas directly in Python if all_schemas.sql
    is not found.  This version lacks foreign keys and indexes but provides
    the same table structure so data population still works.
    """
    cursor = conn.cursor()

    # ── TPC-H (8 tables) ────────────────────────────────────────────────
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS tpch_region (
        r_regionkey INTEGER PRIMARY KEY, r_name TEXT, r_comment TEXT);
    CREATE TABLE IF NOT EXISTS tpch_nation (
        n_nationkey INTEGER PRIMARY KEY, n_name TEXT, n_regionkey INTEGER,
        n_comment TEXT);
    CREATE TABLE IF NOT EXISTS tpch_customer (
        c_custkey INTEGER PRIMARY KEY, c_name TEXT, c_address TEXT,
        c_nationkey INTEGER, c_phone TEXT, c_acctbal REAL,
        c_mktsegment TEXT, c_comment TEXT);
    CREATE TABLE IF NOT EXISTS tpch_orders (
        o_orderkey INTEGER PRIMARY KEY, o_custkey INTEGER,
        o_orderstatus TEXT, o_totalprice REAL, o_orderdate TEXT,
        o_orderpriority TEXT, o_clerk TEXT, o_shippriority INTEGER,
        o_comment TEXT);
    CREATE TABLE IF NOT EXISTS tpch_lineitem (
        l_orderkey INTEGER, l_partkey INTEGER, l_suppkey INTEGER,
        l_linenumber INTEGER, l_quantity REAL, l_extendedprice REAL,
        l_discount REAL, l_tax REAL, l_returnflag TEXT, l_linestatus TEXT,
        l_shipdate TEXT, l_commitdate TEXT, l_receiptdate TEXT,
        l_shipinstruct TEXT, l_shipmode TEXT, l_comment TEXT,
        PRIMARY KEY (l_orderkey, l_linenumber));
    CREATE TABLE IF NOT EXISTS tpch_supplier (
        s_suppkey INTEGER PRIMARY KEY, s_name TEXT, s_address TEXT,
        s_nationkey INTEGER, s_phone TEXT, s_acctbal REAL, s_comment TEXT);
    CREATE TABLE IF NOT EXISTS tpch_part (
        p_partkey INTEGER PRIMARY KEY, p_name TEXT, p_mfgr TEXT,
        p_brand TEXT, p_type TEXT, p_size INTEGER, p_container TEXT,
        p_retailprice REAL, p_comment TEXT);
    CREATE TABLE IF NOT EXISTS tpch_partsupp (
        ps_partkey INTEGER, ps_suppkey INTEGER, ps_availqty INTEGER,
        ps_supplycost REAL, ps_comment TEXT,
        PRIMARY KEY (ps_partkey, ps_suppkey));
    """)

    # ── IMDB / JOB (21 tables) ──────────────────────────────────────────
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS imdb_kind_type (id INTEGER PRIMARY KEY, kind TEXT);
    CREATE TABLE IF NOT EXISTS imdb_company_type (id INTEGER PRIMARY KEY, kind TEXT);
    CREATE TABLE IF NOT EXISTS imdb_role_type (id INTEGER PRIMARY KEY, role TEXT);
    CREATE TABLE IF NOT EXISTS imdb_info_type (id INTEGER PRIMARY KEY, info TEXT);
    CREATE TABLE IF NOT EXISTS imdb_link_type (id INTEGER PRIMARY KEY, link TEXT);
    CREATE TABLE IF NOT EXISTS imdb_comp_cast_type (id INTEGER PRIMARY KEY, kind TEXT);
    CREATE TABLE IF NOT EXISTS imdb_keyword (id INTEGER PRIMARY KEY, keyword TEXT, phonetic_code TEXT);
    CREATE TABLE IF NOT EXISTS imdb_company_name (id INTEGER PRIMARY KEY, name TEXT, country_code TEXT, imdb_id INTEGER, name_pcode_nf TEXT, name_pcode_sf TEXT, md5sum TEXT);
    CREATE TABLE IF NOT EXISTS imdb_name (id INTEGER PRIMARY KEY, name TEXT, imdb_index TEXT, imdb_id INTEGER, gender TEXT, name_pcode_cf TEXT, name_pcode_nf TEXT, surname_pcode TEXT, md5sum TEXT);
    CREATE TABLE IF NOT EXISTS imdb_char_name (id INTEGER PRIMARY KEY, name TEXT, imdb_index TEXT, imdb_id INTEGER, name_pcode_nf TEXT, surname_pcode TEXT, md5sum TEXT);
    CREATE TABLE IF NOT EXISTS imdb_title (id INTEGER PRIMARY KEY, title TEXT, imdb_index TEXT, kind_id INTEGER, production_year INTEGER, imdb_id INTEGER, phonetic_code TEXT, episode_of_id INTEGER, season_nr INTEGER, episode_nr INTEGER, series_years TEXT, md5sum TEXT);
    CREATE TABLE IF NOT EXISTS imdb_aka_name (id INTEGER PRIMARY KEY, person_id INTEGER, name TEXT, imdb_index TEXT, name_pcode_cf TEXT, name_pcode_nf TEXT, surname_pcode TEXT, md5sum TEXT);
    CREATE TABLE IF NOT EXISTS imdb_aka_title (id INTEGER PRIMARY KEY, movie_id INTEGER, title TEXT, imdb_index TEXT, kind_id INTEGER, production_year INTEGER, phonetic_code TEXT, episode_of_id INTEGER, season_nr INTEGER, episode_nr INTEGER, note TEXT, md5sum TEXT);
    CREATE TABLE IF NOT EXISTS imdb_cast_info (id INTEGER PRIMARY KEY, person_id INTEGER, movie_id INTEGER, person_role_id INTEGER, note TEXT, nr_order INTEGER, role_id INTEGER);
    CREATE TABLE IF NOT EXISTS imdb_movie_companies (id INTEGER PRIMARY KEY, movie_id INTEGER, company_id INTEGER, company_type_id INTEGER, note TEXT);
    CREATE TABLE IF NOT EXISTS imdb_movie_info (id INTEGER PRIMARY KEY, movie_id INTEGER, info_type_id INTEGER, info TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS imdb_movie_info_idx (id INTEGER PRIMARY KEY, movie_id INTEGER, info_type_id INTEGER, info TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS imdb_movie_keyword (id INTEGER PRIMARY KEY, movie_id INTEGER, keyword_id INTEGER);
    CREATE TABLE IF NOT EXISTS imdb_movie_link (id INTEGER PRIMARY KEY, movie_id INTEGER, linked_movie_id INTEGER, link_type_id INTEGER);
    CREATE TABLE IF NOT EXISTS imdb_person_info (id INTEGER PRIMARY KEY, person_id INTEGER, info_type_id INTEGER, info TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS imdb_complete_cast (id INTEGER PRIMARY KEY, movie_id INTEGER, subject_id INTEGER, status_id INTEGER);
    """)

    # ── DSB (6 tables) ──────────────────────────────────────────────────
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS dsb_date_dim (
        d_date_sk INTEGER PRIMARY KEY, d_date_id TEXT, d_date TEXT,
        d_year INTEGER, d_moy INTEGER, d_dom INTEGER, d_dow INTEGER,
        d_day_name TEXT, d_quarter_name TEXT);
    CREATE TABLE IF NOT EXISTS dsb_item (
        i_item_sk INTEGER PRIMARY KEY, i_item_id TEXT, i_item_desc TEXT,
        i_current_price REAL, i_wholesale_cost REAL, i_brand TEXT,
        i_class TEXT, i_category TEXT, i_manufact TEXT, i_size TEXT,
        i_color TEXT);
    CREATE TABLE IF NOT EXISTS dsb_store (
        s_store_sk INTEGER PRIMARY KEY, s_store_id TEXT, s_store_name TEXT,
        s_city TEXT, s_county TEXT, s_state TEXT, s_zip TEXT,
        s_country TEXT);
    CREATE TABLE IF NOT EXISTS dsb_customer (
        c_customer_sk INTEGER PRIMARY KEY, c_customer_id TEXT,
        c_current_cdemo_sk INTEGER, c_first_name TEXT, c_last_name TEXT,
        c_birth_year INTEGER, c_email_address TEXT);
    CREATE TABLE IF NOT EXISTS dsb_customer_demographics (
        cd_demo_sk INTEGER PRIMARY KEY, cd_gender TEXT,
        cd_marital_status TEXT, cd_education_status TEXT,
        cd_credit_rating TEXT, cd_dep_count INTEGER);
    CREATE TABLE IF NOT EXISTS dsb_store_sales (
        ss_sold_date_sk INTEGER, ss_item_sk INTEGER,
        ss_customer_sk INTEGER, ss_cdemo_sk INTEGER,
        ss_store_sk INTEGER, ss_ticket_number INTEGER,
        ss_quantity INTEGER, ss_sales_price REAL, ss_net_paid REAL,
        ss_net_profit REAL,
        PRIMARY KEY (ss_item_sk, ss_ticket_number));
    """)

    conn.commit()
    print("  ✓ Inline fallback schemas created (no indexes or foreign keys)")


# =============================================================================
# TPC-H DATA POPULATION
# =============================================================================

def populate_tpch(conn: sqlite3.Connection) -> None:
    """
    Populate TPC-H tables with synthetic data.

    Generates:
        - 5 regions, 25 nations
        - 500 customers, 2000 orders, ~6000 lineitems
        - 50 suppliers, 200 parts, ~400 partsupp relationships
    """
    cursor = conn.cursor()

    # ── Regions (5) ──────────────────────────────────────────────────────
    for i, region in enumerate(REGIONS):
        cursor.execute(
            "INSERT OR IGNORE INTO tpch_region VALUES (?, ?, ?)",
            (i, region, f'Region {region} comments')
        )

    # ── Nations (25) ─────────────────────────────────────────────────────
    for i, nation in enumerate(NATIONS):
        cursor.execute(
            "INSERT OR IGNORE INTO tpch_nation VALUES (?, ?, ?, ?)",
            (i, nation, i % 5, f'Nation {nation} comments')
        )

    # ── Customers (500) ──────────────────────────────────────────────────
    customers = []
    for i in range(1, 501):
        customers.append((
            i, f'Customer#{i}', f'Address {i}', i % 25,
            f'555-{i:04d}',
            round(random.uniform(-1000, 10000), 2),
            random.choice(MARKET_SEGMENTS),
            f'Customer comment {i}'
        ))
    cursor.executemany(
        "INSERT OR IGNORE INTO tpch_customer VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        customers
    )

    # ── Orders (2000) ────────────────────────────────────────────────────
    orders = []
    for i in range(1, 2001):
        y = random.randint(1992, 1998)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        orders.append((
            i, random.randint(1, 500),
            random.choice(['O', 'F', 'P']),
            round(random.uniform(1000, 500000), 2),
            f'{y}-{m:02d}-{d:02d}',
            random.choice(PRIORITIES),
            f'Clerk#{i % 100}', 0, f'Order comment {i}'
        ))
    cursor.executemany(
        "INSERT OR IGNORE INTO tpch_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        orders
    )

    # ── Lineitems (~6000) ────────────────────────────────────────────────
    lineitems = []
    for i in range(1, 2001):
        num_lines = random.randint(2, 5)
        for ln in range(1, num_lines):
            qty = random.randint(1, 50)
            price = round(random.uniform(900, 100000), 2)
            disc = round(random.uniform(0, 0.1), 2)
            tax = round(random.uniform(0, 0.08), 2)
            y = random.randint(1992, 1998)
            m = random.randint(1, 12)
            d = random.randint(1, 28)
            ship_date = f'{y}-{m:02d}-{d:02d}'
            commit_date = f'{y}-{m:02d}-{min(d + 5, 28):02d}'
            receipt_date = f'{y}-{m:02d}-{min(d + 10, 28):02d}'
            lineitems.append((
                i, random.randint(1, 200), random.randint(1, 50), ln,
                qty, price, disc, tax,
                random.choice(['R', 'A', 'N']),
                random.choice(['O', 'F']),
                ship_date, commit_date, receipt_date,
                'DELIVER IN PERSON',
                random.choice(SHIP_MODES),
                f'Lineitem comment {i}_{ln}'
            ))
    cursor.executemany(
        "INSERT OR IGNORE INTO tpch_lineitem VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        lineitems
    )

    # ── Suppliers (50) ───────────────────────────────────────────────────
    suppliers = []
    for i in range(1, 51):
        suppliers.append((
            i, f'Supplier#{i}', f'Supplier Address {i}', i % 25,
            f'555-SUP-{i:04d}',
            round(random.uniform(-500, 5000), 2),
            f'Supplier comment {i}'
        ))
    cursor.executemany(
        "INSERT OR IGNORE INTO tpch_supplier VALUES (?, ?, ?, ?, ?, ?, ?)",
        suppliers
    )

    # ── Parts (200) ──────────────────────────────────────────────────────
    parts = []
    for i in range(1, 201):
        parts.append((
            i, f'Part#{i}', f'Manufacturer#{i % 5}', f'Brand#{i % 10}',
            f'Type {i % 20}', random.randint(1, 50), f'Container{i % 5}',
            round(random.uniform(100, 2000), 2), f'Part comment {i}'
        ))
    cursor.executemany(
        "INSERT OR IGNORE INTO tpch_part VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        parts
    )

    # ── PartSupp (~400) ──────────────────────────────────────────────────
    partsupp = []
    for i in range(1, 201):
        for s in range(1, random.randint(2, 4)):
            partsupp.append((
                i, (i + s) % 50 + 1,
                random.randint(1, 9999),
                round(random.uniform(1, 1000), 2),
                f'Partsupp comment {i}_{s}'
            ))
    cursor.executemany(
        "INSERT OR IGNORE INTO tpch_partsupp VALUES (?, ?, ?, ?, ?)",
        partsupp
    )

    conn.commit()

    # ── Stats ────────────────────────────────────────────────────────────
    row_counts = {}
    for table in ['tpch_region', 'tpch_nation', 'tpch_customer',
                   'tpch_orders', 'tpch_lineitem', 'tpch_supplier',
                   'tpch_part', 'tpch_partsupp']:
        row_counts[table] = cursor.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]

    print(f"  ✓ TPC-H data populated:")
    print(f"    • {row_counts['tpch_region']} regions, "
          f"{row_counts['tpch_nation']} nations")
    print(f"    • {row_counts['tpch_customer']} customers, "
          f"{row_counts['tpch_orders']} orders, "
          f"{row_counts['tpch_lineitem']} lineitems")
    print(f"    • {row_counts['tpch_supplier']} suppliers, "
          f"{row_counts['tpch_part']} parts, "
          f"{row_counts['tpch_partsupp']} partsupp")


# =============================================================================
# IMDB DATA POPULATION
# =============================================================================

def populate_imdb(conn: sqlite3.Connection) -> None:
    """
    Populate IMDB/JOB tables with synthetic data.

    Generates:
        - 7 kind types, 5 company types, 12 role types, 30 info types,
          16 link types, 4 comp_cast types
        - 500 keywords, 300 companies, 400 persons, 300 characters
        - 600 titles, 2000 cast entries, 800 movie-company links
        - 1500 movie_info, 600 movie_info_idx, 1200 movie_keyword, 400 movie_link
    """
    cursor = conn.cursor()

    # ── Lookup / Type Tables ─────────────────────────────────────────────
    kind_types = [
        'movie', 'tv series', 'tv movie', 'video movie',
        'tv mini series', 'video game', 'episode'
    ]
    for i, kind in enumerate(kind_types, 1):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_kind_type VALUES (?, ?)", (i, kind))

    company_types = [
        'production companies', 'distributors', 'special effects',
        'miscellaneous', ''
    ]
    for i, ct in enumerate(company_types, 1):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_company_type VALUES (?, ?)", (i, ct))

    role_types = [
        'actor', 'actress', 'producer', 'writer', 'cinematographer',
        'composer', 'costume designer', 'director', 'editor',
        'miscellaneous crew', 'production designer', 'guest'
    ]
    for i, role in enumerate(role_types, 1):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_role_type VALUES (?, ?)", (i, role))

    info_types = [
        'runtimes', 'color info', 'genres', 'languages', 'certificates',
        'sound mix', 'tech info', 'countries', 'taglines', 'keywords',
        'alternate versions', 'crazy credits', 'goofs', 'soundtrack',
        'quotes', 'release dates', 'trivia', 'mini biography',
        'birth notes', 'birth date', 'height', 'spouse', 'trade mark',
        'other works', 'birth name', 'salary history', 'where now',
        'plot', 'top 250 rank', 'bottom 10 rank'
    ]
    for i, info in enumerate(info_types, 1):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_info_type VALUES (?, ?)", (i, info))

    link_types = [
        'follows', 'followed by', 'remake of', 'remade as', 'references',
        'referenced in', 'spoofs', 'spoofed in', 'features', 'featured in',
        'spin off from', 'spin off', 'version of', 'similar to',
        'edited into', 'edited from'
    ]
    for i, link in enumerate(link_types, 1):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_link_type VALUES (?, ?)", (i, link))

    for i in range(1, 5):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_comp_cast_type VALUES (?, ?)",
            (i, f'cast_type_{i}'))

    # ── Keywords (500) ───────────────────────────────────────────────────
    kw_pool = [
        'murder', 'love', 'death', 'revenge', 'police', 'friend', 'money',
        'family', 'fight', 'escape', 'prison', 'war', 'school', 'hospital',
        'dream', 'fire', 'gun', 'car', 'child', 'dog'
    ]
    for i in range(1, 501):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_keyword VALUES (?, ?, ?)",
            (i, f'{random.choice(kw_pool)}-{i}', None))

    # ── Company Names (300) ──────────────────────────────────────────────
    countries = [
        '[us]', '[gb]', '[de]', '[fr]', '[in]',
        '[jp]', '[kr]', '[it]', '[es]', '[ca]'
    ]
    for i in range(1, 301):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_company_name VALUES "
            "(?, ?, ?, ?, ?, ?, ?)",
            (i, f'Company {i}', random.choice(countries),
             None, None, None, None))

    # ── Person Names (400) ───────────────────────────────────────────────
    genders = ['m', 'f', None]
    for i in range(1, 401):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_name VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (i, f'Person {i}', None, None, random.choice(genders),
             None, None, None, None))

    # ── Character Names (300) ────────────────────────────────────────────
    for i in range(1, 301):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_char_name VALUES "
            "(?, ?, ?, ?, ?, ?, ?)",
            (i, f'Character {i}', None, None, None, None, None))

    # ── Titles (600) ─────────────────────────────────────────────────────
    for i in range(1, 601):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_title VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (i, f'Movie {i}', None, random.randint(1, 7),
             random.randint(1950, 2023), None, None, None, None, None,
             None, None))

    # ── Cast Info (2000) ─────────────────────────────────────────────────
    for i in range(1, 2001):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_cast_info VALUES "
            "(?, ?, ?, ?, ?, ?, ?)",
            (i, random.randint(1, 400), random.randint(1, 600),
             random.randint(1, 300), None, i % 20, random.randint(1, 12)))

    # ── Movie Companies (800) ────────────────────────────────────────────
    notes = [
        '(co-production)', '(presents)',
        '(as Metro-Goldwyn-Mayer Pictures)', '(production)', None
    ]
    for i in range(1, 801):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_movie_companies VALUES "
            "(?, ?, ?, ?, ?)",
            (i, random.randint(1, 600), random.randint(1, 300),
             random.randint(1, 5), random.choice(notes)))

    # ── Movie Info (1500) ────────────────────────────────────────────────
    for i in range(1, 1501):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_movie_info VALUES (?, ?, ?, ?, ?)",
            (i, random.randint(1, 600), random.randint(1, 30),
             f'info-{i}', None))

    # ── Movie Info Idx (600) ─────────────────────────────────────────────
    for i in range(1, 601):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_movie_info_idx VALUES "
            "(?, ?, ?, ?, ?)",
            (i, random.randint(1, 600), random.choice([28, 29, 30]),
             str(random.randint(1, 250)), None))

    # ── Movie Keywords (1200) ────────────────────────────────────────────
    for i in range(1, 1201):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_movie_keyword VALUES (?, ?, ?)",
            (i, random.randint(1, 600), random.randint(1, 500)))

    # ── Movie Links (400) ────────────────────────────────────────────────
    for i in range(1, 401):
        cursor.execute(
            "INSERT OR IGNORE INTO imdb_movie_link VALUES (?, ?, ?, ?)",
            (i, random.randint(1, 600), random.randint(1, 600),
             random.randint(1, 16)))

    conn.commit()

    # ── Stats ────────────────────────────────────────────────────────────
    title_count = cursor.execute(
        "SELECT COUNT(*) FROM imdb_title").fetchone()[0]
    cast_count = cursor.execute(
        "SELECT COUNT(*) FROM imdb_cast_info").fetchone()[0]
    company_count = cursor.execute(
        "SELECT COUNT(*) FROM imdb_movie_companies").fetchone()[0]

    print(f"  ✓ IMDB data populated:")
    print(f"    • {title_count} titles, {cast_count} cast entries, "
          f"{company_count} movie-company links")


# =============================================================================
# DSB DATA POPULATION
# =============================================================================

def populate_dsb(conn: sqlite3.Connection) -> None:
    """
    Populate DSB (Decision Support Benchmark) tables with synthetic data.

    Generates:
        - ~1344 date dimension entries (4 years × 12 months × 28 days)
        - 300 items, 20 stores, 200 customer demographics, 400 customers
        - 3000 store sales transactions
    """
    cursor = conn.cursor()

    # ── Date Dimension (~1344 dates for 4 years) ─────────────────────────
    days = [
        'Monday', 'Tuesday', 'Wednesday', 'Thursday',
        'Friday', 'Saturday', 'Sunday'
    ]
    dk = 1
    for y in range(2000, 2004):
        for m in range(1, 13):
            for d in range(1, 29):
                cursor.execute(
                    "INSERT OR IGNORE INTO dsb_date_dim VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (dk, f'AAAAAA{dk}', f'{y}-{m:02d}-{d:02d}',
                     y, m, d, dk % 7, days[dk % 7],
                     f'{y}Q{(m - 1) // 3 + 1}'))
                dk += 1
    max_date_sk = dk - 1

    # ── Items (300) ──────────────────────────────────────────────────────
    categories = [
        'Music', 'Books', 'Electronics', 'Sports', 'Home',
        'Women', 'Men', 'Children', 'Jewelry', 'Shoes'
    ]
    colors = [
        'red', 'blue', 'green', 'white', 'black',
        'yellow', 'purple', 'orange', 'brown', 'pink'
    ]
    sizes = [
        'small', 'medium', 'large', 'extra large',
        'petite', 'economy', 'N/A'
    ]
    for i in range(1, 301):
        cursor.execute(
            "INSERT OR IGNORE INTO dsb_item VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (i, f'ITEM{i}', f'Item description {i}',
             round(random.uniform(1, 500), 2),
             round(random.uniform(0.5, 250), 2),
             f'Brand#{i % 20}', f'Class{i % 10}',
             random.choice(categories), f'Manufact{i % 15}',
             random.choice(sizes), random.choice(colors)))

    # ── Stores (20) ──────────────────────────────────────────────────────
    states = [
        'TN', 'CA', 'NY', 'TX', 'FL', 'IL', 'OH', 'PA',
        'GA', 'NC', 'MI', 'NJ', 'VA', 'WA', 'MA'
    ]
    for i in range(1, 21):
        cursor.execute(
            "INSERT OR IGNORE INTO dsb_store VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            (i, f'STORE{i}', f'Store {i}', f'City{i}', f'County{i}',
             random.choice(states), f'{10000 + i}', 'United States'))

    # ── Customer Demographics (200) ──────────────────────────────────────
    education_levels = [
        'Primary', 'Secondary', 'College', '2 yr Degree',
        '4 yr Degree', 'Advanced Degree', 'Unknown'
    ]
    credit_ratings = ['Low Risk', 'Medium Risk', 'High Risk', 'Unknown']
    for i in range(1, 201):
        cursor.execute(
            "INSERT OR IGNORE INTO dsb_customer_demographics VALUES "
            "(?, ?, ?, ?, ?, ?)",
            (i, random.choice(['M', 'F']),
             random.choice(['S', 'M', 'D', 'W', 'U']),
             random.choice(education_levels),
             random.choice(credit_ratings),
             random.randint(0, 6)))

    # ── Customers (400) ──────────────────────────────────────────────────
    for i in range(1, 401):
        cursor.execute(
            "INSERT OR IGNORE INTO dsb_customer VALUES "
            "(?, ?, ?, ?, ?, ?, ?)",
            (i, f'CUST{i}', random.randint(1, 200),
             f'First{i}', f'Last{i}',
             random.randint(1940, 2000), f'cust{i}@email.com'))

    # ── Store Sales (3000) ───────────────────────────────────────────────
    for i in range(1, 3001):
        cursor.execute(
            "INSERT OR IGNORE INTO dsb_store_sales VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (random.randint(1, max_date_sk),
             random.randint(1, 300), random.randint(1, 400),
             random.randint(1, 200), random.randint(1, 20),
             i, random.randint(1, 100),
             round(random.uniform(1, 500), 2),
             round(random.uniform(1, 500), 2),
             round(random.uniform(-200, 300), 2)))

    conn.commit()

    # ── Stats ────────────────────────────────────────────────────────────
    sales_count = cursor.execute(
        "SELECT COUNT(*) FROM dsb_store_sales").fetchone()[0]
    item_count = cursor.execute(
        "SELECT COUNT(*) FROM dsb_item").fetchone()[0]
    customer_count = cursor.execute(
        "SELECT COUNT(*) FROM dsb_customer").fetchone()[0]

    print(f"  ✓ DSB data populated:")
    print(f"    • {max_date_sk} dates, {item_count} items, 20 stores")
    print(f"    • {customer_count} customers, 200 demographics, "
          f"{sales_count} store sales")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def setup_all_databases(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Create and populate all three benchmark databases.

    Workflow:
        1. Connect to SQLite database (creates file if it doesn't exist).
        2. Load schema from all_schemas.sql (foreign keys, indexes, types).
        3. Populate TPC-H tables with synthetic data.
        4. Populate IMDB/JOB tables with synthetic data.
        5. Populate DSB tables with synthetic data.
        6. Return the open connection for downstream use.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        sqlite3.Connection: Open database connection with row_factory set.
    """
    print("=" * 70)
    print("  SETTING UP ALL BENCHMARK DATABASES")
    print("  LLM-R2 DBMS Project with Google Gemini")
    print("=" * 70)

    # ── Step 0: Show connection info ─────────────────────────────────────
    print(f"\n  Database    : {db_path}")
    print(f"  Schema file : {SCHEMA_FILE}")

    # ── Step 1: Create database connection ───────────────────────────────
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Enable foreign key enforcement in SQLite
    conn.execute("PRAGMA foreign_keys = ON")

    # ── Step 2: Load schema from all_schemas.sql ─────────────────────────
    print("\n[1/4] Loading schema from all_schemas.sql...")
    schema_loaded = load_and_execute_schema(conn)

    # ── Step 3: Populate TPC-H ───────────────────────────────────────────
    print("\n[2/4] Populating TPC-H tables...")
    populate_tpch(conn)

    # ── Step 4: Populate IMDB ────────────────────────────────────────────
    print("\n[3/4] Populating IMDB/JOB tables...")
    populate_imdb(conn)

    # ── Step 5: Populate DSB ─────────────────────────────────────────────
    print("\n[4/4] Populating DSB tables...")
    populate_dsb(conn)

    # ── Summary ──────────────────────────────────────────────────────────
    total_tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    total_indexes = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
        "AND name LIKE 'idx_%'"
    ).fetchone()[0]

    print("\n" + "=" * 70)
    print("  ALL DATABASES READY!")
    print(f"  Database saved to : {db_path}")
    print(f"  Schema source     : {'all_schemas.sql' if schema_loaded else 'inline fallback'}")
    print(f"  Total tables      : {total_tables}")
    print(f"  Total indexes     : {total_indexes}")
    print("=" * 70)

    return conn


# =============================================================================
# SCRIPT EXECUTION
# =============================================================================

if __name__ == "__main__":
    conn = setup_all_databases()
    conn.close()