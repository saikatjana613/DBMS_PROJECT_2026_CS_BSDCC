# Execution Instructions

## Prerequisites

- Python 3.8 or higher
- Internet connection (for package installation)
- Google Gemini API key (optional - simulation mode works without)

## Installation

```bash
pip install google-generativeai sqlparse matplotlib numpy tqdm

# Full benchmark run (simulation mode)
python main_pipeline.py

# Quick demo (no database required)
python main_pipeline.py --demo

# Single benchmark
python main_pipeline.py --dataset TPC-H

# With real Gemini API
python main_pipeline.py --api-key YOUR_GEMINI_API_KEY

# More accurate timing (5 runs)
python main_pipeline.py --runs 5
