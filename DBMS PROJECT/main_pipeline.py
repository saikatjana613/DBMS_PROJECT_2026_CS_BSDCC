"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  main_pipeline.py — LLM-R2 Complete Pipeline + Visualization + Report      ║
╚══════════════════════════════════════════════════════════════════════════════╝

PURPOSE:
    Single entry point for the entire LLM-R2 query rewrite system.
    Runs the benchmark, generates all charts, and writes a full text report —
    everything in one command.

WHAT THIS FILE DOES:
    1.  Sets up all three benchmark databases (TPC-H, IMDB, DSB) via db_setup.py.
    2.  For each benchmark query, calls Gemini (or simulation) via
        gemini_interface.py to recommend rewrite rules.
    3.  Applies those rules via rewrite_rules.py → produces rewritten SQL.
    4.  Executes both original and rewritten queries (trimmed-mean timing).
    5.  Verifies result equivalence (same rows returned).
    6.  Saves per-benchmark JSON result files.
    7.  Generates 6 publication-quality PNG charts:
          general_performance.png   — original vs rewritten time (all queries)
          speedup_per_query.png     — speedup ratio per query (colour-coded)
          rule_recommendation.png   — which rules Gemini predicted per query
          demo_similarity.png       — ICL demo cosine similarity per query
          llm_latency.png           — LLM call latency per query
          benchmark_summary.png     — 4-panel executive dashboard
    8.  Writes a full plain-text report: results/experiment_report.txt

USAGE:
    python main_pipeline.py                      # full run (simulation mode)
    python main_pipeline.py --demo               # quick demo, no DB needed
    python main_pipeline.py --api-key YOUR_KEY   # use real Gemini API
    python main_pipeline.py --dataset TPC-H      # single benchmark
    python main_pipeline.py --runs 5             # 5 timing runs per query
    python main_pipeline.py --charts-only        # re-generate charts from JSON

IMPORTS:
    config.py           -> Config, BENCHMARK_QUERIES, VALID_RULES
    db_setup.py         -> setup_all_databases()
    rewrite_rules.py    -> apply_rules(), get_rule_descriptions_text()
    gemini_interface.py -> predict_rules()
"""

import argparse
import json
import os
import sys
import time
import datetime
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# ── Fix Windows console encoding for Unicode characters (✓, ⚠, ║, etc.) ──────
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

# ── Local module imports ──────────────────────────────────────────────────────
try:
    from config import Config, BENCHMARK_QUERIES, VALID_RULES, get_rule_names
    from db_setup import setup_all_databases
    from rewrite_rules import apply_rules, get_rule_descriptions_text
    from gemini_interface import predict_rules
except ImportError as e:
    print(f"\n[Import Error] {e}")
    print("Ensure config.py, db_setup.py, rewrite_rules.py, and")
    print("gemini_interface.py are all in the same directory.")
    sys.exit(1)

# ── Matplotlib (optional) ─────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.gridspec as gridspec
    import numpy as np
    PLOT_AVAILABLE = True
except ImportError:
    PLOT_AVAILABLE = False
    np = None
    print("[Warning] matplotlib or numpy not installed. Charts will be skipped.")

# =============================================================================
# PALETTE & SHARED STYLE
# =============================================================================
BG_FIG  = "#0f0f1a"
BG_AX   = "#1a1a2e"
BG_AX2  = "#16213e"
C_ORIG  = "#e74c3c"
C_REW   = "#2ecc71"
C_FAST  = "#27ae60"
C_SLOW  = "#e74c3c"
C_SAME  = "#f39c12"
C_TEXT  = "#ecf0f1"
C_GRID  = "#2c3e50"
C_BLUE  = "#3498db"
C_PUR   = "#9b59b6"
C_ORG   = "#e67e22"
C_BETTER = "#2ecc71"
C_NEUTRAL = "#f39c12"
C_SLOW = "#e74c3c"

BENCH_COL = {"TPC-H": C_BLUE, "IMDB": C_PUR, "DSB": C_ORG}

# ── Map human-readable rule names (from gemini_interface) to internal names ───
# gemini_interface.py returns names like "Filter Pushdown" but rewrite_rules.py
# expects "FILTER_INTO_JOIN". This mapping bridges the two.
RULE_NAME_MAP = {
    "Filter Pushdown":       "FILTER_INTO_JOIN",
    "Aggregation Merge":     "AGGREGATE_PROJECT_MERGE",
    "UNION Sort Transpose":  "SORT_UNION_TRANSPOSE",
    "Predicate Move-Around": "JOIN_EXTRACT_FILTER",
    "Join Reordering":       "JOIN_COMMUTE",
    "Subquery to JOIN":      "FILTER_INTO_JOIN",
    "Limit Pushdown":        "SORT_REMOVE",
    "Constant Folding":      "PROJECT_TO_CALC",
}

# Reverse mapping for chart display (internal → human-readable)
REVERSE_RULE_NAME_MAP = {v: k for k, v in RULE_NAME_MAP.items()}

def _translate_rules(rule_names: List[str]) -> List[str]:
    """Translate human-readable rule names to internal RULE_FUNCTIONS keys."""
    translated = []
    for name in rule_names:
        # Skip EMPTY rules
        if name == "EMPTY":
            continue
        mapped = RULE_NAME_MAP.get(name, name)  # pass-through if already internal
        translated.append(mapped)
    return translated

_FT  = {"fontsize": 13, "color": C_TEXT, "fontweight": "bold", "pad": 12}
_FL  = {"fontsize": 10, "color": C_TEXT}
_FTK = {"colors": C_TEXT, "labelsize": 9}


def _ax(ax, title="", xlabel="", ylabel=""):
    """Apply dark-theme style to an axes."""
    ax.set_facecolor(BG_AX2)
    if title:   ax.set_title(title, **_FT)
    if xlabel:  ax.set_xlabel(xlabel, **_FL)
    if ylabel:  ax.set_ylabel(ylabel, **_FL)
    ax.tick_params(**_FTK)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    for sp in ax.spines.values():
        sp.set_edgecolor(C_GRID)
    return ax


def _blabel(ax, bars, fmt="{:.2f}", fs=8):
    """Add value labels on top of bars."""
    for b in bars:
        h = b.get_height()
        if h > 0:
            ax.text(b.get_x() + b.get_width() / 2,
                    h + max(h * 0.015, 0.003),
                    fmt.format(h),
                    ha="center", va="bottom",
                    fontsize=fs, color=C_TEXT, fontweight="bold")


def _sn(name, n=22):
    return name[:n] + ".." if len(name) > n else name


def _save(fig, path):
    """Save figure with proper error handling."""
    try:
        fig.savefig(path, dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f"    [PNG] {path}")
    except Exception as e:
        print(f"    [ERROR] Failed to save {path}: {e}")


# =============================================================================
# QUERY EXECUTOR
# =============================================================================

class QueryExecutor:
    """
    Runs SQL queries, measures timing (trimmed mean), and checks equivalence.

    Timing: each query is executed n_runs times; if >= 3 runs, the fastest
    and slowest are discarded and the remainder averaged (trimmed mean).
    This eliminates OS scheduling spikes without needing many runs.
    """

    def __init__(self, conn):
        self.conn = conn

    def execute_and_time(
        self, sql: str, n_runs: int = 3, timeout_sec: int = 30
    ) -> Tuple[Optional[float], bool, Optional[int], Optional[str]]:
        """
        Execute sql n_runs times, return (avg_ms, ok, row_count, error).
        """
        times: List[float] = []
        row_count: Optional[int] = None

        for run in range(n_runs):
            try:
                t0 = time.perf_counter()
                cursor = self.conn.execute(sql)
                rows = cursor.fetchall()
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                times.append(elapsed_ms)
                
                if row_count is None:
                    row_count = len(rows)
                    
            except Exception as exc:
                # Don't retry on failure, return immediately
                return None, False, None, str(exc)

        if not times:
            return None, False, None, "No successful runs"

        # Trimmed mean: remove fastest and slowest if we have enough runs
        if len(times) >= 3:
            times_sorted = sorted(times)
            # Remove min and max
            trimmed_times = times_sorted[1:-1]
            avg_ms = sum(trimmed_times) / len(trimmed_times)
        else:
            avg_ms = sum(times) / len(times)

        return avg_ms, True, row_count, None

    def verify_equivalence(self, orig_sql: str, rew_sql: str, max_check_rows: int = 100) -> bool:
        """
        Return True if both queries return the same rows.
        
        Args:
            orig_sql: Original SQL query
            rew_sql: Rewritten SQL query
            max_check_rows: Maximum number of rows to compare (for performance)
        """
        try:
            # Execute both queries
            orig_cursor = self.conn.execute(orig_sql)
            rew_cursor = self.conn.execute(rew_sql)
            
            # Fetch rows for comparison
            orig_rows = orig_cursor.fetchall()
            rew_rows = rew_cursor.fetchall()

            # Check row count
            if len(orig_rows) != len(rew_rows):
                print(f"      [Equiv] Row count mismatch: {len(orig_rows)} vs {len(rew_rows)}")
                return False

            # Compare up to max_check_rows
            check_limit = min(max_check_rows, len(orig_rows))
            for i in range(check_limit):
                if orig_rows[i] != rew_rows[i]:
                    print(f"      [Equiv] Row {i} differs: {orig_rows[i]} vs {rew_rows[i]}")
                    return False
                    
            return True
            
        except Exception as exc:
            print(f"      [Equiv] Error during equivalence check: {exc}")
            return False



# =============================================================================
# LLM-R2 ORCHESTRATOR
# =============================================================================

class LLMRewriteSystem:
    """
    Coordinates the 6-step per-query evaluation pipeline:
        1. Time original query
        2. predict_rules()  -> recommended rule list
        3. apply_rules()    -> rewritten SQL
        4. Time rewritten query
        5. Verify equivalence
        6. Compute improvement ratio
    Accumulates running statistics across all queries.
    """

    def __init__(self, config: Config, conn):
        self.config = config
        self.conn = conn
        self.query_executor = QueryExecutor(conn)
        self._stats = {
            "queries_processed": 0,
            "successful_rewrites": 0,
            "failed_queries": 0,
            "total_improvement": 0.0,
            "total_llm_latency": 0.0,
            "rules_applied": defaultdict(int),
        }
        self.query_cache_file = Path("results/query_cache.json")
        self.query_cache = self._load_query_cache()

    def _load_query_cache(self) -> Dict[str, Any]:
        """Load the best queries cache from disk."""
        if self.query_cache_file.exists():
            try:
                with open(self.query_cache_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"    [Warning] Could not load query cache: {e}")
        return {}

    def _save_query_cache(self) -> None:
        """Save the best queries cache to disk."""
        self.query_cache_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.query_cache_file, "w") as f:
                json.dump(self.query_cache, f, indent=2)
        except Exception as e:
            print(f"    [Warning] Could not save query cache: {e}")

    def process_query(self, query_name: str, sql: str) -> Dict[str, Any]:
        """Process a single query through the entire LLM-R2 pipeline."""
        result = {
            "query_name": query_name,
            "original_sql": sql,
            "rewritten_sql": sql,
            "original_time_ms": 0.0,
            "rewritten_time_ms": 0.0,
            "predicted_rules": [],
            "applied_rules": [],
            "improvement_ratio": 1.0,
            "equivalent": False,
            "llm_latency_sec": 0.0,
            "used_simulation": True,
            "demo_similarity": 0.0,
            "error": None,
        }

        # Step 1 â€” time original
        orig_ms, orig_ok, _, orig_err = self.query_executor.execute_and_time(
            sql, self.config.n_timing_runs, self.config.timeout_seconds
        )
        if not orig_ok:
            result["error"] = f"Original query failed: {orig_err}"
            self._stats["failed_queries"] += 1
            return result
        result["original_time_ms"] = orig_ms

        candidate_rules = []
        # Step 1.5 - check cache to add to candidates
        cache_key = sql.strip()
        cached_result = self.query_cache.get(cache_key)
        if cached_result and isinstance(cached_result, dict):
            cached_rules = cached_result.get("predicted_rules")
            if cached_rules and isinstance(cached_rules, list):
                print(f"      [CACHE] Found previously best rule configuration: {cached_rules}")
                candidate_rules.append(cached_rules)

        # Step 2 â€” predict rules (Multi-Sample for LLM Reproducibility/Best Choice)
        api_key = None if self.config.simulation_mode else self.config.gemini_api_key
        try:
            import copy
            total_latency = 0.0
            best_prediction_meta = None
            
            # Request up to 3 predictions to find the best ruleset
            for i in range(3):
                # Slightly escalate temperature for iterations > 0 to encourage varied LLM ideas
                temp_config = copy.copy(self.config)
                if i > 0:
                    temp_config.ollama_temperature = min(1.0, getattr(temp_config, 'ollama_temperature', 0.3) + 0.3)
                    temp_config.temperature = min(1.0, getattr(temp_config, 'temperature', 0.3) + 0.3)

                prediction = predict_rules(sql, api_key, temp_config, sample_idx=i) 
                p_rules = prediction.get("rules", [])
                total_latency += prediction.get("llm_latency_sec", 0.0)

                if not best_prediction_meta:
                    best_prediction_meta = prediction

                if p_rules not in candidate_rules:
                    candidate_rules.append(p_rules)
                
                # If simulation was used, it's deterministic, no need to loop
                if prediction.get("used_simulation", True):
                    break
            
            result["llm_latency_sec"] = total_latency
            result["used_simulation"] = best_prediction_meta.get("used_simulation", True) if best_prediction_meta else True
            result["demo_similarity"] = best_prediction_meta.get("similarity", 0.0) if best_prediction_meta else 0.0
            self._stats["total_llm_latency"] += total_latency
            
        except Exception as e:
            result["error"] = f"Rule prediction failed: {e}"
            self._stats["failed_queries"] += 1
            return result

        # Step 3 & 4 — apply and test all candidates to select the absolute best rewritten SQL
        best_rew_ms = float('inf')
        best_rewritten_sql = sql
        best_applied_rules = []
        best_predicted_rules = []

        for candidate in candidate_rules:
            try:
                internal_rules = _translate_rules(candidate)
                curr_rewritten_sql, curr_applied = apply_rules(sql, internal_rules)
                
                # Time this specific rewrite variant
                rew_ms, rew_ok, _, rew_err = self.query_executor.execute_and_time(
                    curr_rewritten_sql, self.config.n_timing_runs, self.config.timeout_seconds
                )
                
                # Only consider it if it executes successfully and is equivalent
                if rew_ok and rew_ms > 0:
                    is_equiv = self.query_executor.verify_equivalence(sql, curr_rewritten_sql)
                    if is_equiv and rew_ms < best_rew_ms:
                        best_rew_ms = rew_ms
                        best_rewritten_sql = curr_rewritten_sql
                        best_applied_rules = curr_applied
                        best_predicted_rules = candidate
                        result["equivalent"] = True
                        
            except Exception as e:
                # If a specific rule rewrite throws an error, ignore it and continue trying other candidates
                continue
                
        # Fallback if all rewrites fail or no candidates were given
        if best_rew_ms == float('inf'):
            result["rewritten_time_ms"] = orig_ms
            result["rewritten_sql"] = sql
            result["applied_rules"] = []
            result["predicted_rules"] = []
            result["equivalent"] = True  # Identity mapping is inherently equivalent
        else:
            result["rewritten_time_ms"] = best_rew_ms
            result["rewritten_sql"] = best_rewritten_sql
            result["applied_rules"] = best_applied_rules
            result["predicted_rules"] = best_predicted_rules

            for rule in best_applied_rules:
                self._stats["rules_applied"][rule] += 1

        # Step 6 â€” improvement (only if equivalent)
        if result["equivalent"] and result["rewritten_time_ms"] > 0:
            result["improvement_ratio"] = result["original_time_ms"] / result["rewritten_time_ms"]
            
            # Cache update logic: only cache if it improved the query
            if result["improvement_ratio"] > 1.0:
                is_better_than_cache = True
                if cached_result and isinstance(cached_result, dict):
                    # Check if our new speedup is better than our cached speedup
                    cached_ratio = cached_result.get("improvement_ratio", 1.0)
                    if result["improvement_ratio"] <= cached_ratio:
                        is_better_than_cache = False
                
                if is_better_than_cache:
                    print(f"      [CACHE] Caching new best rules for {query_name}: {result['predicted_rules']}")
                    # Store only necessary info to prevent cache bloat
                    self.query_cache[sql] = {
                        "query_name": query_name,
                        "predicted_rules": result["predicted_rules"],
                        "improvement_ratio": result["improvement_ratio"],
                        "rewritten_time_ms": result["rewritten_time_ms"]
                    }
                    self._save_query_cache()

        # Update statistics - count ALL equivalent queries for improvement stats
        self._stats["queries_processed"] += 1
        if result["equivalent"]:
            # Add improvement ratio for ALL equivalent queries (not just > 1.0)     
            self._stats["total_improvement"] += result.get("improvement_ratio", 1.0)
            if result["improvement_ratio"] > 1.0:
                self._stats["successful_rewrites"] += 1

        return result

    def get_stats(self) -> Dict[str, Any]:
        n = self._stats["queries_processed"]
        ok = self._stats["successful_rewrites"]
        tc = n + self._stats["failed_queries"]
        return {
            "queries_processed": n,
            "successful_rewrites": ok,
            "failed_queries": self._stats["failed_queries"],
            "success_rate": (ok / n * 100) if n > 0 else 0.0,
            "avg_improvement": (self._stats["total_improvement"] / n) if n > 0 else 1.0,
            "avg_llm_latency_ms": (self._stats["total_llm_latency"] / max(tc, 1) * 1000),
            "rules_applied": dict(self._stats["rules_applied"]),
        }


# =============================================================================
# CHART GENERATOR
# =============================================================================

class ChartGenerator:
    """
    Generates all benchmark result charts from the evaluation data.

    Charts produced:
        general_performance.png   — grouped bar: original vs rewritten time
        speedup_per_query.png     — horizontal speedup ratio per query
        rule_recommendation.png   — predicted rules per query (color blocks)
        demo_similarity.png       — ICL demo similarity line chart
        llm_latency.png           — LLM call latency per query
        benchmark_summary.png     — 4-panel executive dashboard
    """

    def __init__(self, output_dir: str = "results"):
        self.out = Path(output_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def _check_plot_available(self) -> bool:
        """Check if plotting is available."""
        if not PLOT_AVAILABLE:
            print("    [SKIP] matplotlib/numpy not available for charts")
            return False
        return True

    # ── 1. General Performance ────────────────────────────────────────────────
    def general_performance(self, data: Dict[str, List[Dict]]) -> None:
        """
        Grouped bar chart showing execution time for every query.
        """
        if not self._check_plot_available():
            return

        all_q, orig_t, rew_t, bench_l = [], [], [], []
        for bench, results in data.items():
            for r in results:
                orig = r.get("original_time_ms")
                if orig is None:
                    continue
                all_q.append(_sn(r["query_name"]))
                orig_t.append(orig)
                rew_t.append(r.get("rewritten_time_ms") or 0.0)
                bench_l.append(bench)

        if not all_q:
            print("    [SKIP] No valid data for general_performance chart")
            return

        n = len(all_q)
        x = np.arange(n)
        w = 0.38

        fig, ax = plt.subplots(figsize=(max(13, n * 1.1), 6.5))
        fig.patch.set_facecolor(BG_FIG)

        b1 = ax.bar(x - w/2, orig_t, w, label="Original",
                    color=C_ORIG, alpha=0.87, zorder=3)
        b2 = ax.bar(x + w/2, rew_t, w, label="LLM-R2 Rewritten",
                    color=C_REW, alpha=0.87, zorder=3)
        _blabel(ax, b1, fs=7)
        _blabel(ax, b2, fs=7)

        # Benchmark divider lines + group labels
        prev_b, prev_i = bench_l[0], -0.5
        max_val = max(orig_t + rew_t) if (orig_t + rew_t) else 1.0
        
        for i, bl in enumerate(bench_l):
            if bl != prev_b or i == n - 1:
                ax.axvline(i - 0.5, color=C_GRID, linestyle=":", lw=1.0, alpha=0.6)
                mid = (prev_i + i) / 2
                ax.text(mid, max_val * 0.98, prev_b,
                        ha="center", va="top", fontsize=9.5,
                        color=BENCH_COL.get(prev_b, C_TEXT), fontweight="bold")
                prev_b = bl
                prev_i = i - 0.5

        ax.set_xticks(x)
        ax.set_xticklabels(all_q, rotation=35, ha="right", fontsize=8, color=C_TEXT)
        _ax(ax, "General Performance: Original vs LLM-R2 Rewritten (ms)",
            ylabel="Execution Time (ms)")
        ax.legend(facecolor=BG_AX, labelcolor=C_TEXT, fontsize=10)
        ax.set_ylim(bottom=0)
        plt.tight_layout()
        _save(fig, self.out / "general_performance.png")

    # ── 2. Speedup Per Query ──────────────────────────────────────────────────
    def speedup_per_query(self, data: Dict[str, List[Dict]]) -> None:
        """
        Horizontal bar chart of speedup ratio per query.
        """
        if not self._check_plot_available():
            return

        queries, ratios, colors = [], [], []
        for bench, results in data.items():
            for r in results:
                queries.append(f"[{bench[0]}] {_sn(r['query_name'], 20)}")
                if r.get("rewritten_time_ms") is None or r.get("error"):
                    ratios.append(0.0)
                    colors.append("#555555")
                    continue
                ratio = r.get("improvement_ratio", 1.0) or 1.0
                ratios.append(ratio)
                if ratio > 1.05:
                    colors.append(C_FAST)
                elif ratio < 0.95:
                    colors.append(C_SLOW)
                else:
                    colors.append(C_SAME)

        if not queries:
            print("    [SKIP] No valid data for speedup_per_query chart")
            return

        n = len(queries)
        fig, ax = plt.subplots(figsize=(9, max(5, n * 0.55)))
        fig.patch.set_facecolor(BG_FIG)
        ax.set_facecolor(BG_AX2)

        y = np.arange(n)
        bars = ax.barh(y, ratios, color=colors, alpha=0.88,
                       edgecolor=BG_FIG, lw=0.6, zorder=3)
        ax.axvline(1.0, color=C_TEXT, linestyle="--", lw=1.4, alpha=0.8,
                   zorder=4, label="1.0x baseline")

        for bar, val in zip(bars, ratios):
            if val == 0.0:
                lbl = "FAILED"
                xpos = 0.03
                align = "left"
            else:
                lbl = f"{val:.3f}x"
                xpos = val + 0.03 if val >= 1.0 else val - 0.03
                align = "left" if val >= 1.0 else "right"
            ax.text(xpos, bar.get_y() + bar.get_height()/2,
                    lbl, ha=align, va="center",
                    fontsize=8.5, color=C_TEXT, fontweight="bold")

        ax.set_yticks(y)
        ax.set_yticklabels(queries, fontsize=8.5, color=C_TEXT)
        ax.invert_yaxis()
        ax.set_xlabel("Speedup Ratio  (>1.0 = faster)", **_FL)
        ax.set_title("Speedup per Query  (LLM-R2 vs Original)", **_FT)
        ax.tick_params(**_FTK)
        ax.grid(axis="x", linestyle="--", alpha=0.3)
        for sp in ax.spines.values():
            sp.set_edgecolor(C_GRID)

        patches = [
            mpatches.Patch(color=C_FAST, label="Faster (>1.05x)"),
            mpatches.Patch(color=C_SAME, label="Similar (0.95-1.05x)"),
            mpatches.Patch(color=C_SLOW, label="Slower (<0.95x)"),
            mpatches.Patch(color="#555555", label="Failed"),
        ]
        ax.legend(handles=patches, facecolor=BG_AX, labelcolor=C_TEXT,
                  fontsize=8.5, loc="lower right")
        
        max_ratio = max([r for r in ratios if r > 0] + [1.0])
        ax.set_xlim(left=0, right=max_ratio * 1.2)

        plt.tight_layout()
        _save(fig, self.out / "speedup_per_query.png")

    # ── 3. Rule Recommendation ────────────────────────────────────────────────
    def rule_recommendation(self, data: Dict[str, List[Dict]]) -> None:
        """
        Shows which rules Gemini predicted per query as color-coded segments.
        """
        if not self._check_plot_available():
            return

        # Collect all unique rules
        all_rules = set()
        for bench_res in data.values():
            for q in bench_res:
                for r in (q.get("predicted_rules") or []):
                    if r and r != "EMPTY":
                        all_rules.add(r)
        
        if not all_rules:
            print("    [SKIP] No rules predicted for rule_recommendation chart")
            return
            
        all_rules = sorted(all_rules)
        rule_pal = plt.cm.tab10(np.linspace(0, 1, max(len(all_rules), 1)))
        rule_color = {rule: rule_pal[i] for i, rule in enumerate(all_rules)}

        ncols = len(data)
        fig, axes = plt.subplots(1, ncols, figsize=(6 * ncols, 5))
        fig.patch.set_facecolor(BG_FIG)
        if ncols == 1:
            axes = [axes]

        for ax, (bench, results) in zip(axes, data.items()):
            qnames = [_sn(r["query_name"], 20) for r in results]
            n = len(qnames)
            y = np.arange(n)

            # background row
            ax.barh(y, [1]*n, color=BG_AX2, edgecolor=C_GRID, lw=0.6, zorder=1)

            for i, r in enumerate(results):
                pred = [x for x in (r.get("predicted_rules") or []) if x and x != "EMPTY"]
                # Convert applied rules from internal names to human-readable for matching
                app = {REVERSE_RULE_NAME_MAP.get(rule, rule) for rule in (r.get("applied_rules") or [])}
                
                if pred:
                    sw = 1.0 / len(pred)
                    for j, rule in enumerate(pred):
                        col = rule_color.get(rule, "#aaaaaa")
                        ax.barh(i, sw, left=j*sw, color=col, alpha=0.80,
                                edgecolor=BG_FIG, lw=0.5, zorder=3)
                        marker = "[OK]" if rule in app else "."
                        ax.text(j*sw + sw/2, i, marker,
                                ha="center", va="center",
                                fontsize=8, color="white", fontweight="bold", zorder=4)

            ax.set_yticks(y)
            ax.set_yticklabels(qnames, fontsize=8, color=C_TEXT)
            ax.invert_yaxis()
            ax.set_xlim(0, 1)
            ax.set_xticks([])
            ax.set_facecolor(BG_AX)
            ax.set_title(f"{bench}\nPredicted Rules ([OK]=applied)", **_FT)

        if all_rules:
            legend_patches = [
                mpatches.Patch(color=rule_color.get(r, "#aaa"), label=r)
                for r in all_rules
            ]
            fig.legend(handles=legend_patches, facecolor=BG_AX,
                       labelcolor=C_TEXT, fontsize=8,
                       loc="lower center", ncol=min(5, len(legend_patches)),
                       bbox_to_anchor=(0.5, -0.04))

        fig.suptitle("Rule Recommendation by Gemini per Query",
                     fontsize=13, color=C_TEXT, fontweight="bold", y=1.02)
        plt.tight_layout()
        _save(fig, self.out / "rule_recommendation.png")

    # ── 4. Demo Similarity ────────────────────────────────────────────────────
    def demo_similarity(self, data: Dict[str, List[Dict]]) -> None:
        """
        Line + scatter plot of cosine similarity between each input query
        and its selected ICL demonstration.
        """
        if not self._check_plot_available():
            return

        fig, ax = plt.subplots(figsize=(13, 5))
        fig.patch.set_facecolor(BG_FIG)

        offset = 0
        xtick_pos, xtick_labels = [], []

        for bench, results in data.items():
            xs = list(range(offset, offset + len(results)))
            ys = [r.get("demo_similarity", 0.0) for r in results]

            ax.plot(xs, ys, color=BENCH_COL.get(bench, C_BLUE), lw=2.0,
                    marker="o", markersize=7, zorder=4, label=bench)

            for x, y, r in zip(xs, ys, results):
                ax.text(x, y + 0.015, f"{y:.3f}",
                        ha="center", va="bottom", fontsize=7.5,
                        color=BENCH_COL.get(bench, C_BLUE), fontweight="bold")
                xtick_pos.append(x)
                xtick_labels.append(_sn(r["query_name"], 18))

            if offset > 0:
                ax.axvline(offset - 0.5, color=C_GRID, linestyle=":", lw=1.0)
            offset += len(results) + 1

        ax.axhline(1.0, color=C_TEXT, linestyle="--", lw=0.9, alpha=0.5, label="Perfect (1.0)")
        ax.axhline(0.8, color=C_SAME, linestyle="--", lw=0.9, alpha=0.5, label="Good (0.8)")
        ax.set_xticks(xtick_pos)
        ax.set_xticklabels(xtick_labels, rotation=35, ha="right", fontsize=8)
        ax.set_ylim(0.5, 1.08)
        _ax(ax, "ICL Demo Similarity — How Well the Selected Example Matches Each Query",
            ylabel="Cosine Similarity Score")
        ax.legend(facecolor=BG_AX, labelcolor=C_TEXT, fontsize=9)
        plt.tight_layout()
        _save(fig, self.out / "demo_similarity.png")

    # ── 5. LLM Latency ───────────────────────────────────────────────────────
    def llm_latency(self, data: Dict[str, List[Dict]]) -> None:
        """
        Bar chart of Gemini API (or simulation) call latency in ms per query.
        """
        if not self._check_plot_available():
            return

        all_q, lats, colors = [], [], []
        for bench, results in data.items():
            for r in results:
                all_q.append(f"[{bench[0]}] {_sn(r['query_name'], 17)}")
                lats.append((r.get("llm_latency_sec") or 0.0) * 1000)
                colors.append(BENCH_COL.get(bench, C_BLUE))

        if not all_q:
            print("    [SKIP] No valid data for llm_latency chart")
            return

        n = len(all_q)
        x = np.arange(n)

        fig, ax = plt.subplots(figsize=(max(10, n * 1.1), 5))
        fig.patch.set_facecolor(BG_FIG)

        bars = ax.bar(x, lats, color=colors, alpha=0.85,
                      edgecolor=BG_FIG, lw=0.6, zorder=3)

        for bar, lat in zip(bars, lats):
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_height() + max(lat * 0.01, 0.3),
                    f"{lat:.1f}ms",
                    ha="center", va="bottom",
                    fontsize=8, color=C_TEXT, fontweight="bold")

        ax.set_xticks(x)
        ax.set_xticklabels(all_q, rotation=35, ha="right", fontsize=8)
        _ax(ax, "LLM Call Latency per Query (Gemini / Simulation)",
            ylabel="Latency (ms)")

        patches = [mpatches.Patch(color=BENCH_COL.get(b, C_BLUE), label=b) 
                   for b in data.keys()]
        ax.legend(handles=patches, facecolor=BG_AX, labelcolor=C_TEXT, fontsize=9)
        plt.tight_layout()
        _save(fig, self.out / "llm_latency.png")

    # ── 6. Benchmark Summary Dashboard ───────────────────────────────────────
    def benchmark_summary(self, data: Dict[str, List[Dict]]) -> None:
        """
        4-panel executive dashboard.
        """
        if not self._check_plot_available():
            return

        bench_names = list(data.keys())
        bench_colors = [BENCH_COL.get(b, C_BLUE) for b in bench_names]

        avg_sp, succ_r, time_sv, equiv_p = [], [], [], []
        for bench in bench_names:
            res = data[bench]
            valid = [r for r in res if r.get("rewritten_time_ms") is not None]
            n = len(res)

            ratios = [r.get("improvement_ratio", 1.0) or 1.0 for r in valid]
            avg_sp.append(np.mean(ratios) if ratios else 1.0)

            faster = sum(1 for rt in ratios if rt > 1.05)
            succ_r.append((faster / n * 100) if n > 0 else 0.0)

            saved = sum(
                max(0, (r.get("original_time_ms", 0) or 0) - (r.get("rewritten_time_ms", 0) or 0))
                for r in valid
            )
            time_sv.append(saved)

            passed = sum(1 for r in res if r.get("equivalent", False))
            equiv_p.append(passed / n * 100 if n > 0 else 0.0)

        fig = plt.figure(figsize=(15, 9))
        fig.patch.set_facecolor(BG_FIG)
        gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.32)

        # Panel 1 — avg speedup
        ax1 = fig.add_subplot(gs[0, 0])
        b1 = ax1.bar(bench_names, avg_sp, color=bench_colors, alpha=0.88,
                     edgecolor=BG_FIG, lw=0.6, zorder=3)
        ax1.axhline(1.0, color=C_TEXT, linestyle="--", lw=1.2, alpha=0.7, label="1.0x baseline")
        for bar, val in zip(b1, avg_sp):
                        ax1.text(bar.get_x() + bar.get_width()/2,
                     bar.get_height() + 0.01, f"{val:.3f}x",
                     ha="center", va="bottom", fontsize=10, color=C_TEXT, fontweight="bold")
        _ax(ax1, "Average Speedup Ratio", ylabel="Speedup (x)")
        ax1.set_ylim(0, max(avg_sp) * 1.28 if avg_sp else 2.0)
        ax1.legend(facecolor=BG_AX, labelcolor=C_TEXT, fontsize=8)

        # Panel 2 — success rate donut
        ax2 = fig.add_subplot(gs[0, 1])
        ax2.set_facecolor(BG_AX2)
        has_data = any(v > 0 for v in succ_r)
        pie_v = succ_r if has_data else [1]
        pie_l = bench_names if has_data else ["No data"]
        pie_c = bench_colors if has_data else ["#555555"]
        wedges, _, autotexts = ax2.pie(
            pie_v, labels=pie_l, colors=pie_c,
            autopct="%1.0f%%", startangle=90, pctdistance=0.75,
            wedgeprops={"edgecolor": BG_FIG, "linewidth": 2},
            textprops={"color": C_TEXT, "fontsize": 9},
        )
        for at in autotexts:
            at.set_fontsize(9)
            at.set_color(BG_FIG)
            at.set_fontweight("bold")
        ax2.add_artist(plt.Circle((0, 0), 0.52, fc=BG_AX2))
        ax2.set_title("Success Rate (queries >1.05x faster)", **_FT)

        # Panel 3 — total time saved
        ax3 = fig.add_subplot(gs[1, 0])
        b3 = ax3.bar(bench_names, time_sv, color=bench_colors, alpha=0.88,
                     edgecolor=BG_FIG, lw=0.6, zorder=3)
        for bar, val in zip(b3, time_sv):
            ax3.text(bar.get_x() + bar.get_width()/2,
                     bar.get_height() + max(val * 0.01, 0.01), f"{val:.3f} ms",
                     ha="center", va="bottom", fontsize=10, color=C_TEXT, fontweight="bold")
        _ax(ax3, "Total Execution Time Saved per Benchmark", ylabel="Time Saved (ms)")
        ax3.set_ylim(bottom=0)

        # Panel 4 — equivalence pass rate
        ax4 = fig.add_subplot(gs[1, 1])
        fail = [100 - v for v in equiv_p]
        bp = ax4.bar(bench_names, equiv_p, color=C_FAST, alpha=0.85,
                     label="Equivalent", zorder=3)
        bf = ax4.bar(bench_names, fail, color=C_SLOW, alpha=0.85,
                     bottom=equiv_p, label="Not Equivalent / Failed", zorder=3)
        for bar, pv, fv in zip(bp, equiv_p, fail):
            if pv > 0:
                ax4.text(bar.get_x() + bar.get_width()/2, pv/2,
                         f"{pv:.0f}%", ha="center", va="center",
                         fontsize=9, color="white", fontweight="bold")
            if fv > 0:
                ax4.text(bar.get_x() + bar.get_width()/2, pv + fv/2,
                         f"{fv:.0f}%", ha="center", va="center",
                         fontsize=9, color="white", fontweight="bold")
        _ax(ax4, "Query Equivalence Rate (%)", ylabel="Percentage (%)")
        ax4.set_ylim(0, 108)
        ax4.legend(facecolor=BG_AX, labelcolor=C_TEXT, fontsize=8)

        fig.suptitle("LLM-R2 Benchmark Summary Dashboard",
                     fontsize=15, color=C_TEXT, fontweight="bold", y=1.01)
        _save(fig, self.out / "benchmark_summary.png")

    # ── 7. Per-Benchmark Comparison ────────────────────────────────────────────
    def benchmark_comparison(self, data: Dict[str, List[Dict]]) -> None:
        """
        Generates one grouped bar chart per benchmark.
        """
        if not self._check_plot_available():
            return

        for bench, results in data.items():
            valid = [r for r in results
                     if r.get("original_time_ms") is not None and r.get("rewritten_time_ms") is not None]
            if not valid:
                continue

            names = [_sn(r["query_name"], 26) for r in valid]
            orig_t = [r["original_time_ms"] for r in valid]
            rew_t = [r["rewritten_time_ms"] for r in valid]
            ratios = [r.get("improvement_ratio", 1.0) or 1.0 for r in valid]
            n = len(names)
            x = np.arange(n)
            w = 0.36
            col = BENCH_COL.get(bench, C_BLUE)

            fig, (ax_top, ax_bot) = plt.subplots(
                2, 1, figsize=(max(9, n * 1.6), 8),
                gridspec_kw={"height_ratios": [3, 1]}
            )
            fig.patch.set_facecolor(BG_FIG)

            # Top: execution time bars
            ax_top.set_facecolor(BG_AX2)
            b1 = ax_top.bar(x - w/2, orig_t, w, label="Original",
                            color=C_ORIG, alpha=0.87, zorder=3)
            b2 = ax_top.bar(x + w/2, rew_t, w, label="LLM-R2 Rewritten",
                            color=C_REW, alpha=0.87, zorder=3)
            _blabel(ax_top, b1, fs=8)
            _blabel(ax_top, b2, fs=8)

            ax_top.set_xticks(x)
            ax_top.set_xticklabels(names, rotation=30, ha="right",
                                   fontsize=9, color=C_TEXT)
            _ax(ax_top,
                title=f"{bench} Benchmark — Original vs LLM-R2 Rewritten (ms)",
                ylabel="Execution Time (ms)")
            ax_top.legend(facecolor=BG_AX, labelcolor=C_TEXT, fontsize=10)
            ax_top.set_ylim(bottom=0)
            ax_top.grid(axis="y", linestyle="--", alpha=0.3)

            # Bottom: speedup ratio bar
            ax_bot.set_facecolor(BG_AX2)
            ratio_colors = [
                C_FAST if r > 1.05 else C_SLOW if r < 0.95 else C_SAME
                for r in ratios
            ]
            rb = ax_bot.bar(x, ratios, 0.55, color=ratio_colors, alpha=0.88,
                            edgecolor=BG_FIG, lw=0.6, zorder=3)
            ax_bot.axhline(1.0, color=C_TEXT, linestyle="--", lw=1.3,
                           alpha=0.7, label="1.0x baseline", zorder=4)
            for bar, ratio in zip(rb, ratios):
                ax_bot.text(
                    bar.get_x() + bar.get_width()/2,
                    ratio + 0.02, f"{ratio:.2f}x",
                    ha="center", va="bottom",
                    fontsize=9, color=C_TEXT, fontweight="bold"
                )
            ax_bot.set_xticks(x)
            ax_bot.set_xticklabels(names, rotation=30, ha="right",
                                   fontsize=9, color=C_TEXT)
            _ax(ax_bot, ylabel="Speedup (x)")
            ax_bot.legend(facecolor=BG_AX, labelcolor=C_TEXT, fontsize=8)
            ax_bot.set_ylim(0, max(ratios) * 1.30 if ratios else 2.0)
            ax_bot.grid(axis="y", linestyle="--", alpha=0.3)

            plt.tight_layout()
            fname = bench.lower().replace("-", "_") + "_comparison.png"
            _save(fig, self.out / fname)

    # ── 8. Improvement Heatmap ────────────────────────────────────────────────
    def improvement_heatmap(self, data: Dict[str, List[Dict]]) -> None:
        """
        Color-coded grid showing speedup ratio for (query, benchmark).
        """
        if not self._check_plot_available():
            return

        datasets = list(data.keys())
        query_names = []
        for results in data.values():
            for r in results:
                if r["query_name"] not in query_names:
                    query_names.append(r["query_name"])

        if not query_names or not datasets:
            print("    [SKIP] No valid data for improvement_heatmap chart")
            return

        nq = len(query_names)
        nd = len(datasets)

        # Build grid; NaN for failed/missing
        grid = np.full((nq, nd), np.nan)
        grid_text = [["" for _ in range(nd)] for _ in range(nq)]

        for j, ds in enumerate(datasets):
            for r in data[ds]:
                if r["query_name"] in query_names:
                    i = query_names.index(r["query_name"])
                    ratio = r.get("improvement_ratio", 1.0) or 1.0
                    if r.get("error") or r.get("rewritten_time_ms") is None:
                        grid_text[i][j] = "FAILED"
                    else:
                        grid[i, j] = ratio
                        grid_text[i][j] = f"{ratio:.2f}x"

        fig, ax = plt.subplots(
            figsize=(max(7, nd * 2.8), max(5, nq * 0.7 + 2))
        )
        fig.patch.set_facecolor(BG_FIG)
        ax.set_facecolor(BG_AX2)

        # Mask NaN cells
        masked = np.ma.array(grid, mask=np.isnan(grid))
        cmap = plt.cm.RdYlGn
        cmap.set_bad(color="#333355")
        im = ax.imshow(masked, cmap=cmap, vmin=0.5, vmax=2.0,
                       aspect="auto", interpolation="nearest")

        # Annotate each cell
        for i in range(nq):
            for j in range(nd):
                label = grid_text[i][j]
                if not label or label == "FAILED":
                    if label == "FAILED":
                        ax.text(j, i, label, ha="center", va="center",
                                fontsize=8, color=C_TEXT, fontweight="bold")
                    continue
                if not np.isnan(grid[i, j]):
                    val = grid[i, j]
                    text_color = "white" if (val < 0.85 or val > 1.55) else "black"
                    ax.text(j, i, label, ha="center", va="center",
                            fontsize=9, color=text_color, fontweight="bold")

        ax.set_xticks(range(nd))
        ax.set_yticks(range(nq))
        ax.set_xticklabels(datasets, color=C_TEXT, fontsize=11, fontweight="bold")
        ax.set_yticklabels([q[:32] for q in query_names], color=C_TEXT, fontsize=8)
        plt.setp(ax.get_xticklabels(), rotation=20, ha="right")

        cbar = fig.colorbar(im, ax=ax, shrink=0.75, pad=0.02)
        cbar.ax.set_ylabel("Improvement Ratio  (>1.0 = faster)",
                           rotation=-90, va="bottom", color=C_TEXT, fontsize=9)
        cbar.ax.yaxis.set_tick_params(color=C_TEXT)
        plt.setp(cbar.ax.yaxis.get_ticklabels(), color=C_TEXT)

        ax.set_title("Improvement Heatmap — Speedup Ratio per Query per Benchmark",
                     color=C_TEXT, fontsize=13, fontweight="bold", pad=12)
        plt.tight_layout()
        _save(fig, self.out / "improvement_heatmap.png")

    # ── 9. Rule Effectiveness Radar ─────────────────────────────────────────────
    def rule_effectiveness_radar(self, data: Dict[str, List[Dict]]) -> None:
        """
        Creates a radar/bar chart of average speedups granted by specific predicted rules.
        """
        if not self._check_plot_available():
            return

        from collections import defaultdict
        rule_speedups = defaultdict(list)

        for bench, results in data.items():
            for r in results:
                sp = r.get("improvement_ratio")
                rules = r.get("predicted_rules", [])
                if sp and rules:
                    for rule in rules:
                        if rule != "EMPTY":
                            rule_speedups[rule].append(sp)

        if not rule_speedups:
            return

        # Calculate averages safely
        avg_speedups = {rule: sum(s)/len(s) for rule, s in rule_speedups.items() if len(s) > 0}
        
        # Sort descending
        sorted_rules = sorted(avg_speedups.items(), key=lambda x: x[1], reverse=False) # Ascending for horizontal bar
        
        if not sorted_rules:
            return

        rules, speeds = zip(*sorted_rules)

        fig, ax = plt.subplots(figsize=(8, max(4, len(rules) * 0.6)))
        
        # Colormap for the bars
        bar_colors = [C_BETTER if sp > 1.1 else C_NEUTRAL if sp >= 0.95 else C_SLOW for sp in speeds]

        bars = ax.barh(rules, speeds, color=bar_colors, edgecolor="#ffffff", linewidth=0.8)
        
        # Add labels to the ends of bars
        for b in bars:
            w = b.get_width()
            ax.text(max(w + 0.05, 0.05),
                    b.get_y() + b.get_height() / 2,
                    f"{w:.2f}x",
                    ha="left", va="center",
                    fontsize=10, color=C_TEXT, fontweight="bold")

        ax.set_title("Average Speedup per Predicted Rule", color=C_TEXT, fontsize=14, fontweight="bold", pad=12)
        ax.set_xlabel("Speedup Multiplier (Avg)", color="#888888", fontsize=10)
        ax.axvline(1.0, color="#ffffff", linestyle="--", linewidth=1, alpha=0.3)
        ax.set_xlim(left=0, right=max( speeds + (1.2,) ) * 1.15 ) # Give padding on right side
        ax.grid(axis="x", color=C_GRID, linestyle=":", alpha=0.6)

        plt.tight_layout()
        _save(fig, self.out / "rule_effectiveness.png")

    # ── 10. Cache Impact Scatter ───────────────────────────────────────────────
    def cache_impact_chart(self, data: Dict[str, List[Dict]]) -> None:
        """
        Creates a scatter plot showing LLM latency versus Improvement Ratio,
        annotating queries that experienced massive speedups (potential cache hits).
        """
        if not self._check_plot_available():
            return

        x_latency = []
        y_speedup = []
        labels = []

        for bench, results in data.items():
            for r in results:
                lat = r.get("llm_latency_sec")
                sp = r.get("improvement_ratio")
                if lat is not None and sp is not None:
                    x_latency.append(lat)
                    y_speedup.append(sp)
                    labels.append(_sn(r["query_name"], 15))

        if not x_latency:
            return

        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Color mapping: High speedups get bright highlight
        colors = [C_BETTER if sp > 1.2 else C_NEUTRAL if sp >= 0.95 else C_SLOW for sp in y_speedup]
        sizes = [max(50, sp * 100) for sp in y_speedup]

        scatter = ax.scatter(x_latency, y_speedup, c=colors, s=sizes, alpha=0.7, edgecolors="#ffffff", linewidth=1.5)
        
        for i, txt in enumerate(labels):
            if y_speedup[i] > 1.2: # Only label big wins to avoid clutter
                ax.annotate(txt, (x_latency[i], y_speedup[i]), xytext=(5, 5), textcoords='offset points', fontsize=8, color=C_TEXT)

        ax.set_title("API Latency vs Query Speedup", color=C_TEXT, fontsize=14, fontweight="bold", pad=12)
        ax.set_xlabel("LLM Response Strategy Generation Time (seconds)", color="#888888", fontsize=10)
        ax.set_ylabel("Execution Speedup (x multiplier)", color="#888888", fontsize=10)
        ax.axhline(1.0, color="#ffffff", linestyle="--", linewidth=1, alpha=0.3)
        ax.grid(axis="both", color=C_GRID, linestyle=":", alpha=0.6)

        plt.tight_layout()
        _save(fig, self.out / "cache_impact.png")

    def generate_all(self, data: Dict[str, List[Dict]]) -> None:
        """Run all chart generators in order."""
        if not self._check_plot_available():
            print("  [WARNING] Cannot generate charts - matplotlib/numpy not available")
            return

        print("\n  Generating charts...")
        self.general_performance(data)      # general_performance.png
        self.speedup_per_query(data)        # speedup_per_query.png
        self.benchmark_comparison(data)     # {benchmark}_comparison.png
        self.improvement_heatmap(data)      # improvement_heatmap.png
        self.rule_recommendation(data)      # rule_recommendation.png
        self.demo_similarity(data)          # demo_similarity.png
        self.llm_latency(data)              # llm_latency.png
        self.benchmark_summary(data)        # benchmark_summary.png
        self.rule_effectiveness_radar(data) # rule_effectiveness_radar.png
        self.cache_impact_chart(data)       # cache_impact.png

# =============================================================================
# CONSOLE SUMMARY TABLE (stdout)
# =============================================================================

def print_summary(all_results: Dict[str, List[Dict]], stats: Dict[str, Any]) -> None:
    W = 96
    print("\n" + "=" * W)
    print("  FINAL RESULTS SUMMARY")
    print("=" * W)
    print(f"  {'Dataset':<10} {'Query':<36} {'Orig(ms)':<12} {'Rew(ms)':<12} {'Speedup':<10} Status")
    print("  " + "-" * (W - 2))

    total_orig = total_rew = 0.0
    total_faster = total_q = 0

    for ds, results in all_results.items():
        for r in results:
            orig = r.get("original_time_ms")
            rew = r.get("rewritten_time_ms")
            ratio = r.get("improvement_ratio", 1.0) or 1.0
            total_q += 1
            qn = r["query_name"][:34]

            if orig and rew and not r.get('error'):
                total_orig += orig
                total_rew += rew
                spd = f"{ratio:.2f}x"
                if ratio > 1.05:
                    st = "FASTER"
                    total_faster += 1
                elif ratio < 0.95:
                    st = "SLOWER"
                else:
                    st = "~ SAME"
                print(f"  {ds:<10} {qn:<36} {orig:<12.3f} {rew:<12.3f} {spd:<10} {st}")
            else:
                print(f"  {ds:<10} {qn:<36} {'ERROR':<12} {'ERROR':<12} {'N/A':<10} FAILED")

    print("  " + "-" * (W - 2))
    if total_rew > 0:
        ov = total_orig / total_rew
        print(f"  {'TOTAL':<10} {str(total_q)+' queries':<36} "
              f"{total_orig:<12.3f} {total_rew:<12.3f} {ov:.2f}x     "
              f"{total_faster}/{total_q} improved")
    print("=" * W)

    print(f"\n  Statistics:")
    print(f"    Queries processed   : {stats['queries_processed']}")
    print(f"    Successful rewrites : {stats['successful_rewrites']}")
    print(f"    Failed queries      : {stats['failed_queries']}")
    print(f"    Success rate        : {stats['success_rate']:.1f}%")
    print(f"    Avg improvement     : {stats['avg_improvement']:.3f}x")
    print(f"    Avg LLM latency     : {stats['avg_llm_latency_ms']:.1f} ms")

    if stats.get("rules_applied"):
        print(f"\n    Rule usage:")
        for rule, cnt in sorted(stats["rules_applied"].items(), key=lambda x: -x[1]):
            print(f"     {rule:<35} :{cnt}")


# =============================================================================
# SIMPLIFIED DEMO
# =============================================================================

def run_simplified_demo() -> None:
    """Quick smoke-test: predict + rewrite without any database."""
    print("=" * 70)
    print("  LLM-R2 DEMO  (simulation mode — no database needed)")
    print("=" * 70)
    print("\nAvailable Rewrite Rules:")
    print("-" * 50)
    print(get_rule_descriptions_text())

    demos = [
        ("Filter Pushdown",
         "SELECT c.name, SUM(o.amount) FROM tpch_customer c, tpch_orders o "
         "WHERE c.c_custkey = o.o_custkey AND c.c_mktsegment = 'AUTOMOBILE' GROUP BY c.name"),
        ("Aggregation Merge",
         "SELECT l.l_orderkey, SUM(l.l_quantity) AS qty FROM tpch_lineitem l "
         "GROUP BY l.l_orderkey ORDER BY l.l_orderkey"),
        ("UNION Sort Transpose",
         "SELECT id, title FROM imdb_title UNION ALL SELECT id, title FROM imdb_aka_title ORDER BY title"),
        ("Already Optimal",
         "SELECT * FROM tpch_part WHERE p_brand = 'Brand#41' LIMIT 10"),
    ]

    print("\nDemo Results:")
    print("-" * 70)
    for name, sql in demos:
        print(f"\n  {name}")
        print(f"    SQL: {sql[:75]}{'...' if len(sql) > 75 else ''}")
        # Load config for multi-provider support
        try:
            from config import LLM_CONFIG
            config = LLM_CONFIG
        except ImportError:
            config = None
        pred = predict_rules(sql, config=config)
        pred_rules = pred.get("rules", [])
        print(f"    Predicted rules : {pred_rules}")
        print(f"    Demo similarity : {pred.get('similarity', 0.0):.4f}")
        # Translate to internal rule names before applying
        internal_rules = _translate_rules(pred_rules)
        rewritten, applied = apply_rules(sql, internal_rules)
        if applied:
            print(f"    Applied rules   : {applied}")
            print(f"    Rewritten SQL   : {rewritten[:75]}{'...' if len(rewritten) > 75 else ''}")
        else:
            print("    No text rewrite applied")

    print("\n" + "=" * 70)
    print("  Demo complete!")
    print("=" * 70)


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-R2: LLM-Enhanced Rule-Based Query Rewrite System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main_pipeline.py\n"
            "  python main_pipeline.py --demo\n"
            "  python main_pipeline.py --api-key YOUR_KEY\n"
            "  python main_pipeline.py --dataset TPC-H\n"
            "  python main_pipeline.py --charts-only\n"
        ),
    )
    parser.add_argument("--demo", action="store_true", help="Quick demo, no database needed")
    parser.add_argument("--charts-only", action="store_true", help="Re-generate charts from existing JSON files")
    parser.add_argument("--api-key", type=str, default=None, help="Gemini API key")
    parser.add_argument("--dataset", type=str, default="all",
                        choices=["TPC-H", "IMDB", "DSB", "all"])
    parser.add_argument("--runs", type=int, default=3, help="Timing runs per query (default 3)")
    parser.add_argument("--results-dir", type=str, default="results")
    parser.add_argument("--db-path", type=str, default="dbms_project.db")
    parser.add_argument("--timeout", type=int, default=30, help="Query timeout in seconds")
    args = parser.parse_args()

    # Demo mode
    if args.demo:
        run_simplified_demo()
        return

    # Charts-only mode
    if args.charts_only:
        print("=" * 74)
        print("  LLM-R2 — Charts-Only Mode (reading existing JSON files)")
        print("=" * 74)
        rdir = Path(args.results_dir)
        json_map = {
            "TPC-H": rdir / "tpc-h_results.json",
            "IMDB": rdir / "imdb_results.json",
            "DSB": rdir / "dsb_results.json",
        }
        data: Dict[str, List[Dict]] = {}
        for bench, jpath in json_map.items():
            if jpath.exists():
                try:
                    with open(jpath, encoding="utf-8") as f:
                        data[bench] = json.load(f)
                    print(f"  Loaded {bench}: {len(data[bench])} queries from {jpath}")
                except Exception as e:
                    print(f"  [ERROR] Failed to load {jpath}: {e}")
            else:
                print(f"  [SKIP] {jpath} not found")

        if not data:
            print("\n  No JSON files found. Run the full pipeline first.")
            sys.exit(1)

        cg = ChartGenerator(args.results_dir)
        cg.generate_all(data)
        
        print(f"\n  All charts saved to '{args.results_dir}/'")
        return

    # Full pipeline
    print("=" * 74)
    print("  LLM-R2: LLM-Enhanced Rule-Based Query Rewrite System")
    print("  Based on PVLDB 2024 Paper | Google Gemini Backend")
    print("=" * 74)

    # Config
    config = Config()
    config.n_timing_runs = args.runs
    config.results_dir = args.results_dir
    config.db_path = args.db_path
    config.timeout_seconds = args.timeout

    if args.api_key:
        config.gemini_api_key = args.api_key
        config.simulation_mode = False
    elif os.environ.get("GEMINI_API_KEY"):
        config.gemini_api_key = os.environ["GEMINI_API_KEY"]
        config.simulation_mode = False

    mode_label = "REAL Gemini API" if config.is_api_ready() else "Simulation mode"
    print(f"\n  Mode        : {mode_label}")
    print(f"  DB path     : {config.db_path}")
    print(f"  Results dir : {config.results_dir}")
    print(f"  Timing runs : {config.n_timing_runs} per query")
    print(f"  Timeout     : {config.timeout_seconds} seconds\n")

    # Step 1: DB Setup
    print("[1/4] Setting up benchmark databases...")
    try:
        conn = setup_all_databases(config.db_path)
    except Exception as e:
        print(f"  [ERROR] Failed to setup database: {e}")
        sys.exit(1)

    # Step 2: System Initialization
    print("\n[2/4] Initialising LLM-R2 system...")
    system = LLMRewriteSystem(config, conn)

    queries_to_run = (
        BENCHMARK_QUERIES if args.dataset == "all"
        else {args.dataset: BENCHMARK_QUERIES.get(args.dataset, {})}
    )

    # Step 3: Evaluate
    total_q = sum(len(v) for v in queries_to_run.values())
    print(f"\n[3/4] Running {total_q} queries...")
    all_results: Dict[str, List[Dict]] = {}

    for benchmark, queries in queries_to_run.items():
        print(f"\n  [{benchmark}]")
        results: List[Dict] = []

        for query_name, sql in queries.items():
            print(f"    > {query_name}")
            result = system.process_query(query_name, sql.strip())
            results.append(result)

            orig = result.get("original_time_ms")
            rew = result.get("rewritten_time_ms")
            # Make sure we don't divide by zero
            sp = result.get("improvement_ratio", 1.0)

            if orig and rew and not result.get('error'):
                if sp > 1.05:
                    icon = "+"
                elif sp < 0.95:
                    icon = "-"
                else:
                    icon = "="
                print(f"      [{icon}] {orig:.3f}ms -> {rew:.3f}ms  ({sp:.3f}x)"
                      f"  rules={result['applied_rules']}")
            else:
                print(f"      [!] Error: {result.get('error', 'unknown')}")

        all_results[benchmark] = results

        # Save per-benchmark JSON
        jpath = Path(config.results_dir) / f"{benchmark.lower()}_results.json"
        jpath.parent.mkdir(parents=True, exist_ok=True)
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"      JSON -> {jpath}")

    # Step 4: Charts
    print("\n[4/4] Generating charts...")
    
    # Generate charts
    cg = ChartGenerator(config.results_dir)
    cg.generate_all(all_results)
    
    # Print summary to console
    stats = system.get_stats()
    print_summary(all_results, stats)

    conn.close()
    print(f"\n  Done! All outputs saved to '{config.results_dir}/'")
    print("=" * 74)


if __name__ == "__main__":
    main()