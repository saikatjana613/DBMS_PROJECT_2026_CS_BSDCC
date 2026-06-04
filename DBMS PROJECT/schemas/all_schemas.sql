-- ============================================================================
-- ALL BENCHMARK DATABASE SCHEMAS — SQLite Compatible
-- ============================================================================
-- SQLite is a lightweight relational database management system (RDBMS)
-- stored inside a single file. It is a serverless, self-contained SQL
-- database engine. It allows you to:
--      Create tables, Store data, Run SQL queries, Perform joins,
--      Use indexes, Execute transactions
--      without installing a heavy database server.
-- ============================================================================
-- LLM-R2 DBMS Project with Google Gemini
-- ============================================================================
-- This file contains schemas for three benchmark databases used in the
-- LLM-R2 paper (PVLDB 2024):
--   1. TPC-H    (8 tables)  — Transaction Processing Performance Council - support benchmark
--   2. IMDB/JOB (21 tables) — Join Order Benchmark on movie data
--   3. DSB      (6 tables)  — Decision Support Benchmark 
-- ============================================================================
-- Approach: Uses consistent naming conventions with prefixes
--           (tpch_*, imdb_*, dsb_*)
-- ============================================================================


-- ╔═══════════════════════════════════════════════════════════════════════════╗
-- ║                     SECTION 1: TPC-H SCHEMA (8 TABLES)                  ║
-- ║  Decision support benchmark. Scale factor 10 = ~10GB.                   ║
-- ║  22 query templates, 5000 queries used in LLM-R2 experiments.           ║
-- ╚═══════════════════════════════════════════════════════════════════════════╝

-- Region lookup table
CREATE TABLE IF NOT EXISTS tpch_region (
    r_regionkey INTEGER PRIMARY KEY,
    r_name VARCHAR(25) NOT NULL,
    r_comment VARCHAR(152)
);

-- Nation lookup table
CREATE TABLE IF NOT EXISTS tpch_nation (
    n_nationkey INTEGER PRIMARY KEY,
    n_name VARCHAR(25) NOT NULL,
    n_regionkey INTEGER NOT NULL,
    n_comment VARCHAR(152),
    FOREIGN KEY (n_regionkey) REFERENCES tpch_region(r_regionkey)
);

-- Customer information
CREATE TABLE IF NOT EXISTS tpch_customer (
    c_custkey INTEGER PRIMARY KEY,
    c_name VARCHAR(25) NOT NULL,
    c_address VARCHAR(40) NOT NULL,
    c_nationkey INTEGER NOT NULL,
    c_phone VARCHAR(15),
    c_acctbal DECIMAL(15,2),
    c_mktsegment VARCHAR(10),
    c_comment VARCHAR(117),
    FOREIGN KEY (c_nationkey) REFERENCES tpch_nation(n_nationkey)
);

-- Orders fact table
CREATE TABLE IF NOT EXISTS tpch_orders (
    o_orderkey INTEGER PRIMARY KEY,
    o_custkey INTEGER NOT NULL,
    o_orderstatus CHAR(1),
    o_totalprice DECIMAL(15,2),
    o_orderdate DATE,
    o_orderpriority VARCHAR(15),
    o_clerk VARCHAR(15),
    o_shippriority INTEGER,
    o_comment VARCHAR(79),
    FOREIGN KEY (o_custkey) REFERENCES tpch_customer(c_custkey)
);

-- Lineitem detail table
CREATE TABLE IF NOT EXISTS tpch_lineitem (
    l_orderkey INTEGER NOT NULL,
    l_linenumber INTEGER NOT NULL,
    l_partkey INTEGER NOT NULL,
    l_suppkey INTEGER NOT NULL,
    l_quantity DECIMAL(15,2),
    l_extendedprice DECIMAL(15,2),
    l_discount DECIMAL(15,2),
    l_tax DECIMAL(15,2),
    l_returnflag CHAR(1),
    l_linestatus CHAR(1),
    l_shipdate DATE,
    l_commitdate DATE,
    l_receiptdate DATE,
    l_shipinstruct VARCHAR(25),
    l_shipmode VARCHAR(10),
    l_comment VARCHAR(44),
    PRIMARY KEY (l_orderkey, l_linenumber),
    FOREIGN KEY (l_orderkey) REFERENCES tpch_orders(o_orderkey)
);

-- Supplier information
CREATE TABLE IF NOT EXISTS tpch_supplier (
    s_suppkey INTEGER PRIMARY KEY,
    s_name VARCHAR(25) NOT NULL,
    s_address VARCHAR(40),
    s_nationkey INTEGER NOT NULL,
    s_phone VARCHAR(15),
    s_acctbal DECIMAL(15,2),
    s_comment VARCHAR(101),
    FOREIGN KEY (s_nationkey) REFERENCES tpch_nation(n_nationkey)
);

-- Part information
CREATE TABLE IF NOT EXISTS tpch_part (
    p_partkey INTEGER PRIMARY KEY,
    p_name VARCHAR(55) NOT NULL,
    p_mfgr VARCHAR(25),
    p_brand VARCHAR(10),
    p_type VARCHAR(25),
    p_size INTEGER,
    p_container VARCHAR(10),
    p_retailprice DECIMAL(15,2),
    p_comment VARCHAR(23)
);

-- Part-Supplier relationship
CREATE TABLE IF NOT EXISTS tpch_partsupp (
    ps_partkey INTEGER NOT NULL,
    ps_suppkey INTEGER NOT NULL,
    ps_availqty INTEGER,
    ps_supplycost DECIMAL(15,2),
    ps_comment VARCHAR(199),
    PRIMARY KEY (ps_partkey, ps_suppkey),
    FOREIGN KEY (ps_partkey) REFERENCES tpch_part(p_partkey),
    FOREIGN KEY (ps_suppkey) REFERENCES tpch_supplier(s_suppkey)
);

-- Create indexes for TPC-H performance
CREATE INDEX IF NOT EXISTS idx_tpch_customer_nation ON tpch_customer(c_nationkey);
CREATE INDEX IF NOT EXISTS idx_tpch_customer_segment ON tpch_customer(c_mktsegment);
CREATE INDEX IF NOT EXISTS idx_tpch_orders_custkey ON tpch_orders(o_custkey);
CREATE INDEX IF NOT EXISTS idx_tpch_orders_date ON tpch_orders(o_orderdate);
CREATE INDEX IF NOT EXISTS idx_tpch_lineitem_orderkey ON tpch_lineitem(l_orderkey);
CREATE INDEX IF NOT EXISTS idx_tpch_lineitem_partkey ON tpch_lineitem(l_partkey);
CREATE INDEX IF NOT EXISTS idx_tpch_lineitem_suppkey ON tpch_lineitem(l_suppkey);
CREATE INDEX IF NOT EXISTS idx_tpch_lineitem_shipdate ON tpch_lineitem(l_shipdate);
CREATE INDEX IF NOT EXISTS idx_tpch_supplier_nation ON tpch_supplier(s_nationkey);
CREATE INDEX IF NOT EXISTS idx_tpch_partsupp_part ON tpch_partsupp(ps_partkey);
CREATE INDEX IF NOT EXISTS idx_tpch_partsupp_supp ON tpch_partsupp(ps_suppkey);


-- ╔═══════════════════════════════════════════════════════════════════════════╗
-- ║                   SECTION 2: IMDB / JOB SCHEMA (21 TABLES)              ║
-- ║  Internet Movie Database. Used with Join Order Benchmark (JOB).         ║
-- ║  113 complex multi-join queries. 5000 queries in LLM-R2 experiments.    ║
-- ║  Source: github.com/gregrahn/join-order-benchmark                       ║
-- ╚═══════════════════════════════════════════════════════════════════════════╝

-- Kind type lookup table
CREATE TABLE IF NOT EXISTS imdb_kind_type (
    id INTEGER PRIMARY KEY,
    kind TEXT
);

-- Role type lookup table
CREATE TABLE IF NOT EXISTS imdb_role_type (
    id INTEGER PRIMARY KEY,
    role TEXT
);

-- Company type lookup table
CREATE TABLE IF NOT EXISTS imdb_company_type (
    id INTEGER PRIMARY KEY,
    kind VARCHAR(20)
);

-- Info type lookup table
CREATE TABLE IF NOT EXISTS imdb_info_type (
    id INTEGER PRIMARY KEY,
    info TEXT
);

-- Link type lookup table
CREATE TABLE IF NOT EXISTS imdb_link_type (
    id INTEGER PRIMARY KEY,
    link TEXT
);

-- Comp_cast_type (complete cast type)
CREATE TABLE IF NOT EXISTS imdb_comp_cast_type (
    id INTEGER PRIMARY KEY,
    kind TEXT
);

-- Keyword table
CREATE TABLE IF NOT EXISTS imdb_keyword (
    id INTEGER PRIMARY KEY,
    keyword TEXT,
    phonetic_code TEXT
);

-- Company name table
CREATE TABLE IF NOT EXISTS imdb_company_name (
    id INTEGER PRIMARY KEY,
    name TEXT,
    country_code TEXT,
    imdb_id INTEGER,
    name_pcode_nf TEXT,
    name_pcode_sf TEXT,
    md5sum TEXT
);

-- Name table (actors, actresses, crew)
CREATE TABLE IF NOT EXISTS imdb_name (
    id INTEGER PRIMARY KEY,
    name TEXT,
    imdb_index TEXT,
    imdb_id INTEGER,
    gender TEXT,
    name_pcode_cf TEXT,
    name_pcode_nf TEXT,
    surname_pcode TEXT,
    md5sum TEXT
);

-- Char_name table
CREATE TABLE IF NOT EXISTS imdb_char_name (
    id INTEGER PRIMARY KEY,
    name TEXT,
    imdb_index TEXT,
    imdb_id INTEGER,
    name_pcode_nf TEXT,
    surname_pcode TEXT,
    md5sum TEXT
);

-- Title table (movies, TV shows)
CREATE TABLE IF NOT EXISTS imdb_title (
    id INTEGER PRIMARY KEY,
    title TEXT,
    imdb_index TEXT,
    kind_id INTEGER,
    production_year INTEGER,
    imdb_id INTEGER,
    phonetic_code TEXT,
    episode_of_id INTEGER,
    season_nr INTEGER,
    episode_nr INTEGER,
    series_years TEXT,
    md5sum TEXT,
    FOREIGN KEY (kind_id) REFERENCES imdb_kind_type(id)
);

-- Aka_name table (alternate names for people)
CREATE TABLE IF NOT EXISTS imdb_aka_name (
    id INTEGER PRIMARY KEY,
    person_id INTEGER,
    name TEXT,
    imdb_index VARCHAR(5),
    name_pcode_cf VARCHAR(5),
    name_pcode_nf VARCHAR(5),
    surname_pcode TEXT,
    md5sum TEXT,
    FOREIGN KEY (person_id) REFERENCES imdb_name(id)
);

-- Aka_title table (alternate titles for movies)
CREATE TABLE IF NOT EXISTS imdb_aka_title (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER,
    title TEXT,
    imdb_index VARCHAR(5),
    kind_id INTEGER,
    production_year INTEGER,
    phonetic_code TEXT,
    episode_of_id INTEGER,
    season_nr INTEGER,
    episode_nr INTEGER,
    note TEXT,
    md5sum TEXT,
    FOREIGN KEY (movie_id) REFERENCES imdb_title(id),
    FOREIGN KEY (kind_id) REFERENCES imdb_kind_type(id)
);

-- ============================================================================
-- Relationship tables
-- ============================================================================

-- Cast_info table
CREATE TABLE IF NOT EXISTS imdb_cast_info (
    id INTEGER PRIMARY KEY,
    person_id INTEGER,
    movie_id INTEGER,
    person_role_id INTEGER,
    note TEXT,
    nr_order INTEGER,
    role_id INTEGER,
    FOREIGN KEY (movie_id) REFERENCES imdb_title(id),
    FOREIGN KEY (person_id) REFERENCES imdb_name(id),
    FOREIGN KEY (role_id) REFERENCES imdb_role_type(id)
);

-- Movie_companies table
CREATE TABLE IF NOT EXISTS imdb_movie_companies (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER,
    company_id INTEGER,
    company_type_id INTEGER,
    note TEXT,
    FOREIGN KEY (movie_id) REFERENCES imdb_title(id),
    FOREIGN KEY (company_id) REFERENCES imdb_company_name(id),
    FOREIGN KEY (company_type_id) REFERENCES imdb_company_type(id)
);

-- Movie_info table
CREATE TABLE IF NOT EXISTS imdb_movie_info (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER,
    info_type_id INTEGER,
    info TEXT,
    note TEXT,
    FOREIGN KEY (movie_id) REFERENCES imdb_title(id),
    FOREIGN KEY (info_type_id) REFERENCES imdb_info_type(id)
);

-- Movie_info_idx table
CREATE TABLE IF NOT EXISTS imdb_movie_info_idx (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER,
    info_type_id INTEGER,
    info TEXT,
    note TEXT,
    FOREIGN KEY (movie_id) REFERENCES imdb_title(id),
    FOREIGN KEY (info_type_id) REFERENCES imdb_info_type(id)
);

-- Movie_keyword table
CREATE TABLE IF NOT EXISTS imdb_movie_keyword (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER,
    keyword_id INTEGER,
    FOREIGN KEY (movie_id) REFERENCES imdb_title(id),
    FOREIGN KEY (keyword_id) REFERENCES imdb_keyword(id)
);

-- Movie_link table
CREATE TABLE IF NOT EXISTS imdb_movie_link (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER,
    linked_movie_id INTEGER,
    link_type_id INTEGER,
    FOREIGN KEY (movie_id) REFERENCES imdb_title(id),
    FOREIGN KEY (linked_movie_id) REFERENCES imdb_title(id),
    FOREIGN KEY (link_type_id) REFERENCES imdb_link_type(id)
);

-- Person_info table
CREATE TABLE IF NOT EXISTS imdb_person_info (
    id INTEGER PRIMARY KEY,
    person_id INTEGER,
    info_type_id INTEGER,
    info TEXT,
    note TEXT,
    FOREIGN KEY (person_id) REFERENCES imdb_name(id),
    FOREIGN KEY (info_type_id) REFERENCES imdb_info_type(id)
);

-- Complete_cast table
CREATE TABLE IF NOT EXISTS imdb_complete_cast (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER,
    subject_id INTEGER,
    status_id INTEGER,
    FOREIGN KEY (movie_id) REFERENCES imdb_title(id),
    FOREIGN KEY (subject_id) REFERENCES imdb_comp_cast_type(id),
    FOREIGN KEY (status_id) REFERENCES imdb_comp_cast_type(id)
);

-- Create indexes for IMDB performance
CREATE INDEX IF NOT EXISTS idx_imdb_title_kind ON imdb_title(kind_id);
CREATE INDEX IF NOT EXISTS idx_imdb_title_year ON imdb_title(production_year);
CREATE INDEX IF NOT EXISTS idx_imdb_cast_info_movie ON imdb_cast_info(movie_id);
CREATE INDEX IF NOT EXISTS idx_imdb_cast_info_person ON imdb_cast_info(person_id);
CREATE INDEX IF NOT EXISTS idx_imdb_movie_companies_movie ON imdb_movie_companies(movie_id);
CREATE INDEX IF NOT EXISTS idx_imdb_movie_companies_company ON imdb_movie_companies(company_id);
CREATE INDEX IF NOT EXISTS idx_imdb_movie_info_movie ON imdb_movie_info(movie_id);
CREATE INDEX IF NOT EXISTS idx_imdb_movie_info_idx_movie ON imdb_movie_info_idx(movie_id);
CREATE INDEX IF NOT EXISTS idx_imdb_movie_keyword_movie ON imdb_movie_keyword(movie_id);
CREATE INDEX IF NOT EXISTS idx_imdb_movie_keyword_keyword ON imdb_movie_keyword(keyword_id);
CREATE INDEX IF NOT EXISTS idx_imdb_movie_link_movie ON imdb_movie_link(movie_id);
CREATE INDEX IF NOT EXISTS idx_imdb_aka_name_person ON imdb_aka_name(person_id);
CREATE INDEX IF NOT EXISTS idx_imdb_aka_title_movie ON imdb_aka_title(movie_id);
CREATE INDEX IF NOT EXISTS idx_imdb_person_info_person ON imdb_person_info(person_id);
CREATE INDEX IF NOT EXISTS idx_imdb_complete_cast_movie ON imdb_complete_cast(movie_id);


-- ╔═══════════════════════════════════════════════════════════════════════════╗
-- ║                   SECTION 3: DSB SCHEMA (6 KEY TABLES)                  ║
-- ║  Decision Support Benchmark.                          ║
-- ║  Complex data distributions, 2000 queries in LLM-R2 experiments.        ║
-- ╚═══════════════════════════════════════════════════════════════════════════╝

-- Date dimension table
CREATE TABLE IF NOT EXISTS dsb_date_dim (
    d_date_sk INTEGER PRIMARY KEY,
    d_date_id TEXT,
    d_date TEXT,
    d_year INTEGER,
    d_moy INTEGER,
    d_dom INTEGER,
    d_dow INTEGER,
    d_day_name TEXT,
    d_quarter_name TEXT
);

-- Item table (products)
CREATE TABLE IF NOT EXISTS dsb_item (
    i_item_sk INTEGER PRIMARY KEY,
    i_item_id TEXT,
    i_item_desc TEXT,
    i_current_price DECIMAL(15,2),
    i_wholesale_cost DECIMAL(15,2),
    i_brand TEXT,
    i_class TEXT,
    i_category TEXT,
    i_manufact TEXT,
    i_size TEXT,
    i_color TEXT
);

-- Store table
CREATE TABLE IF NOT EXISTS dsb_store (
    s_store_sk INTEGER PRIMARY KEY,
    s_store_id TEXT,
    s_store_name TEXT,
    s_city TEXT,
    s_county TEXT,
    s_state TEXT,
    s_zip TEXT,
    s_country TEXT
);

-- Customer dimension table
CREATE TABLE IF NOT EXISTS dsb_customer (
    c_customer_sk INTEGER PRIMARY KEY,
    c_customer_id TEXT,
    c_current_cdemo_sk INTEGER,
    c_first_name TEXT,
    c_last_name TEXT,
    c_birth_year INTEGER,
    c_email_address TEXT
);

-- Customer demographics table
CREATE TABLE IF NOT EXISTS dsb_customer_demographics (
    cd_demo_sk INTEGER PRIMARY KEY,
    cd_gender TEXT,
    cd_marital_status TEXT,
    cd_education_status TEXT,
    cd_credit_rating TEXT,
    cd_dep_count INTEGER
);

-- Store sales fact table
CREATE TABLE IF NOT EXISTS dsb_store_sales (
    ss_sold_date_sk INTEGER,
    ss_item_sk INTEGER,
    ss_customer_sk INTEGER,
    ss_cdemo_sk INTEGER,
    ss_store_sk INTEGER,
    ss_ticket_number INTEGER,
    ss_quantity INTEGER,
    ss_sales_price DECIMAL(15,2),
    ss_net_paid DECIMAL(15,2),
    ss_net_profit DECIMAL(15,2),
    PRIMARY KEY (ss_item_sk, ss_ticket_number),
    FOREIGN KEY (ss_sold_date_sk) REFERENCES dsb_date_dim(d_date_sk),
    FOREIGN KEY (ss_item_sk) REFERENCES dsb_item(i_item_sk),
    FOREIGN KEY (ss_customer_sk) REFERENCES dsb_customer(c_customer_sk),
    FOREIGN KEY (ss_cdemo_sk) REFERENCES dsb_customer_demographics(cd_demo_sk),
    FOREIGN KEY (ss_store_sk) REFERENCES dsb_store(s_store_sk)
);

-- Create indexes for DSB performance
CREATE INDEX IF NOT EXISTS idx_dsb_date_dim_year ON dsb_date_dim(d_year);
CREATE INDEX IF NOT EXISTS idx_dsb_date_dim_month ON dsb_date_dim(d_moy);
CREATE INDEX IF NOT EXISTS idx_dsb_item_category ON dsb_item(i_category);
CREATE INDEX IF NOT EXISTS idx_dsb_item_brand ON dsb_item(i_brand);
CREATE INDEX IF NOT EXISTS idx_dsb_customer_demo ON dsb_customer(c_current_cdemo_sk);
CREATE INDEX IF NOT EXISTS idx_dsb_store_sales_date ON dsb_store_sales(ss_sold_date_sk);
CREATE INDEX IF NOT EXISTS idx_dsb_store_sales_item ON dsb_store_sales(ss_item_sk);
CREATE INDEX IF NOT EXISTS idx_dsb_store_sales_customer ON dsb_store_sales(ss_customer_sk);
CREATE INDEX IF NOT EXISTS idx_dsb_store_sales_store ON dsb_store_sales(ss_store_sk);