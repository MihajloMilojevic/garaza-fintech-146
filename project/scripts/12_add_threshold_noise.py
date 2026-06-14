"""
12_add_threshold_noise.py
=========================
One-time data migration: add independent Gaussian noise to dynamic_t_block
and dynamic_t_review in threshold_decisions, then recompute dynamic_verdict
and verdicts_differ so the table stays internally consistent.

Noise design
------------
  seed        : 42  (fixed — reproducible)
  noise_block ~ N(0, σ=4.0)   applied to dynamic_t_block  independently
  noise_review~ N(0, σ=3.5)   applied to dynamic_t_review independently

  σ=4.0 was chosen as ~56% of the natural std of t_block (~7.2), giving
  meaningful regression signal without swamping the risk-score trend.
  σ=3.5 on review is slightly smaller so the two targets move independently
  (gap variance ≈ √(4²+3.5²) ≈ 5.3 points, replacing the rigid constant-25).

Clamp order of operations
--------------------------
  1. t_block_noisy  = clip(t_block  + noise_block,  10.0, 95.0)
  2. t_review_noisy = clip(t_review + noise_review,  5.0, 95.0)
  3. Ordering: if t_review_noisy >= t_block_noisy → t_review_noisy = t_block_noisy - 1.0
     (safety only; expected frequency ~0.1% given the ~25-point starting gap)

  No tight inner clamps (old 40/95/20/70 removed). Only outer safety bounds
  [5, 95] prevent nonsensical values.

Outputs
-------
  Overwrites  project/exports/threshold_decisions.parquet
  Updates     project/sanctions_screening.db  (threshold_decisions table)
  Logs before/after stats to  project/logs/generation_log.txt
"""

import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_DIR  = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
EXPORTS_DIR  = os.path.join(PROJECT_DIR, "exports")
DB_PATH      = os.path.join(PROJECT_DIR, "sanctions_screening.db")
LOG_PATH     = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")

TD_PARQUET   = os.path.join(EXPORTS_DIR, "threshold_decisions.parquet")
SR_PARQUET   = os.path.join(EXPORTS_DIR, "screening_results.parquet")

# ── Noise parameters (document here so they appear in logs) ───────────────────
RNG_SEED     = 42
SIGMA_BLOCK  = 4.0
SIGMA_REVIEW = 3.5
T_MAX        = 95.0
T_MIN_BLOCK  = 10.0
T_MIN_REVIEW = 5.0
STATIC_THRESHOLD = 65.0


# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("12_add_threshold_noise")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


# ── Verdict helpers ────────────────────────────────────────────────────────────

def dynamic_verdict(match_score: float, t_block: float, t_review: float) -> str:
    if match_score >= t_block:
        return "BLOCK"
    if match_score >= t_review:
        return "REVIEW"
    return "CLEAR"

def static_verdict(match_score: float) -> str:
    if match_score >= STATIC_THRESHOLD:
        return "BLOCK"
    if match_score >= 50.0:
        return "REVIEW"
    return "CLEAR"


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 12_add_threshold_noise.py started ===")
    logger.info(f"  RNG seed        : {RNG_SEED}")
    logger.info(f"  sigma_block     : {SIGMA_BLOCK}")
    logger.info(f"  sigma_review    : {SIGMA_REVIEW}")
    logger.info(f"  outer clamps    : t_block in [{T_MIN_BLOCK}, {T_MAX}]  "
                f"t_review in [{T_MIN_REVIEW}, {T_MAX}]")
    logger.info(f"  ordering fix    : if t_review >= t_block → t_review = t_block - 1")

    # ── Load data ─────────────────────────────────────────────────────────────
    logger.info("Loading threshold_decisions.parquet …")
    td = pd.read_parquet(TD_PARQUET)
    logger.info(f"  {len(td)} rows loaded")

    logger.info("Loading screening_results.parquet (for match_score lookup) …")
    sr = pd.read_parquet(SR_PARQUET, columns=["screening_id", "match_score"])

    # Join match_score into td
    td = td.merge(sr, on="screening_id", how="left", suffixes=("", "_sr"))

    # ── Before stats ──────────────────────────────────────────────────────────
    logger.info("--- BEFORE noise ---")
    for col in ["dynamic_t_block", "dynamic_t_review"]:
        s = td[col]
        logger.info(f"  {col}: mean={s.mean():.3f}  std={s.std():.3f}  "
                    f"min={s.min():.3f}  max={s.max():.3f}")
    gap_before = td["dynamic_t_block"] - td["dynamic_t_review"]
    logger.info(f"  gap (t_block-t_review): mean={gap_before.mean():.3f}  "
                f"std={gap_before.std():.5f}")
    for v, c in td["dynamic_verdict"].value_counts().items():
        logger.info(f"  dynamic_verdict {v}: {c} ({c/len(td)*100:.1f}%)")
    logger.info(f"  verdicts_differ=1: {td['verdicts_differ'].sum()} "
                f"({td['verdicts_differ'].mean()*100:.1f}%)")

    # ── Apply noise ────────────────────────────────────────────────────────────
    rng = np.random.default_rng(RNG_SEED)
    n   = len(td)

    noise_block  = rng.normal(0, SIGMA_BLOCK,  size=n)
    noise_review = rng.normal(0, SIGMA_REVIEW, size=n)

    t_block_new  = np.clip(td["dynamic_t_block"].values  + noise_block,
                           T_MIN_BLOCK, T_MAX)
    t_review_new = np.clip(td["dynamic_t_review"].values + noise_review,
                           T_MIN_REVIEW, T_MAX)

    # Ordering fix: t_review must be strictly below t_block
    swap_mask = t_review_new >= t_block_new
    t_review_new[swap_mask] = t_block_new[swap_mask] - 1.0
    logger.info(f"  ordering fix applied to {swap_mask.sum()} rows")

    td["dynamic_t_block"]  = np.round(t_block_new,  4)
    td["dynamic_t_review"] = np.round(t_review_new, 4)

    # Recompute verdict and verdicts_differ
    td["dynamic_verdict"]  = [
        dynamic_verdict(ms, tb, tr)
        for ms, tb, tr in zip(td["match_score"], td["dynamic_t_block"], td["dynamic_t_review"])
    ]
    td["verdicts_differ"] = (td["dynamic_verdict"] != td["static_verdict"]).astype(int)

    # ── After stats ───────────────────────────────────────────────────────────
    logger.info("--- AFTER noise ---")
    for col in ["dynamic_t_block", "dynamic_t_review"]:
        s = td[col]
        logger.info(f"  {col}: mean={s.mean():.3f}  std={s.std():.3f}  "
                    f"min={s.min():.3f}  max={s.max():.3f}")
    gap_after = td["dynamic_t_block"] - td["dynamic_t_review"]
    logger.info(f"  gap (t_block-t_review): mean={gap_after.mean():.3f}  "
                f"std={gap_after.std():.3f}")
    for v, c in td["dynamic_verdict"].value_counts().items():
        logger.info(f"  dynamic_verdict {v}: {c} ({c/len(td)*100:.1f}%)")
    logger.info(f"  verdicts_differ=1: {td['verdicts_differ'].sum()} "
                f"({td['verdicts_differ'].mean()*100:.1f}%)")

    # ── Drop temp join column and write parquet ────────────────────────────────
    out_cols = ["decision_id", "transaction_id", "screening_id",
                "static_threshold", "static_verdict",
                "dynamic_t_block", "dynamic_t_review",
                "dynamic_verdict", "verdicts_differ"]
    td_out = td[out_cols].copy()

    logger.info(f"Writing {TD_PARQUET} …")
    td_out.to_parquet(TD_PARQUET, index=False)
    logger.info("  parquet written.")

    # ── Update SQLite ──────────────────────────────────────────────────────────
    logger.info(f"Updating SQLite at {DB_PATH} …")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")

    # Build update rows: (t_block, t_review, verdict, differ, decision_id)
    updates = list(zip(
        td_out["dynamic_t_block"].tolist(),
        td_out["dynamic_t_review"].tolist(),
        td_out["dynamic_verdict"].tolist(),
        td_out["verdicts_differ"].tolist(),
        td_out["decision_id"].tolist(),
    ))

    sql = """
        UPDATE threshold_decisions
        SET dynamic_t_block=?, dynamic_t_review=?, dynamic_verdict=?, verdicts_differ=?
        WHERE decision_id=?
    """
    CHUNK = 2000
    for i in range(0, len(updates), CHUNK):
        conn.executemany(sql, updates[i:i + CHUNK])
        conn.commit()
        logger.info(f"  Updated rows {i+1}–{min(i+CHUNK, len(updates))}")

    conn.close()
    logger.info("SQLite updated.")
    logger.info("=== 12_add_threshold_noise.py finished ===")


if __name__ == "__main__":
    main()
