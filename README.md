# DBMS Project 2026 (CS & BSDCC)

## Project Name

**LLM-R²: A Large Language Model Enhanced Rule-Based SQL Query Rewrite System**

## Project Team

| Name | Roll No. | GitHub Username |
|------|----------|----------------|
| Saikat Jana | CS2524 | @saikatjana613 |
| Farhin | CS2507 | @farhin27 |
| Rajneesh Yadav | BSDCC2415 | @rajneesh-yadav-047 |
| Priyam Priyadarshi | BSDCC2413 | @PRIYAM-ISIK |
| Md Ali Mumtaz | BSDCC2410 | @Ali-isi01 |

---

## Project Description

This project focuses on Database Management System (DBMS) query optimization using SQL rewrite rules, Large Language Model (LLM) verification, and experimental evaluation. The system analyzes SQL queries, applies optimization techniques, validates transformations using LLM-based verification, and compares performance before and after optimization.

## 
## Repository Structure

```text
DBMS_PROJECT_2026_CS_BSDCC/
│
├── DBMS Final Project Report.pdf
├── DBMS Provided Original Paper.pdf
│
└── DBMS PROJECT/
    │
    ├── schemas/
    │   └── all_schemas.sql
    │
    ├── config.py
    ├── db_setup.py
    ├── dbms_project.db
    ├── extract_queries.py
    ├── gemini_interface.py
    ├── main_pipeline.py
    ├── plot.py
    └── rewrite_rules.py
    │
    ├── results/
    │   ├── benchmark_summary.png
    │   ├── demo_similarity.png
    │   ├── dsb_comparison.png
    │   ├── dsb_results.json
    │   ├── general_performance.png
    │   ├── imdb_comparison.png
    │   ├── imdb_results.json
    │   ├── improvement_heatmap.png
    │   ├── llm_latency.png
    │   ├── rule_recommendation.png
    │   ├── speedup_per_query.png
    │   ├── tpc-h_comparison.png
    │   └── tpc-h_results.json
    │
    └── dataset_distribution.png
        



```

# Execution Instructions

## Prerequisites

- Python 3.8 or higher
- Internet connection (for package installation)
- Google Gemini API key (optional - simulation mode works without)

## Installation

```bash
pip install google-generativeai sqlparse matplotlib numpy tqdm
```

## Running the Project

### Full benchmark run (simulation mode)

```bash
python main_pipeline.py
```

### Quick demo (no database required)

```bash
python main_pipeline.py --demo
```

### Single benchmark

```bash
python main_pipeline.py --dataset TPC-H
```

### With real Gemini API

```bash
python main_pipeline.py --api-key YOUR_GEMINI_API_KEY
```

### More accurate timing (5 runs)

```bash
python main_pipeline.py --runs 5
```
