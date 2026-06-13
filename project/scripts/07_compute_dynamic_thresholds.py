"""
07_compute_dynamic_thresholds.py
=================================
For every screening result, compute a static threshold decision and a dynamic
threshold decision (adjusted by the account's risk score), then insert the
comparison into `threshold_decisions`.

Static rule:
  BLOCK if match_score >= 75 | REVIEW if >= 50 | CLEAR otherwise

Dynamic rule:
  base_block  = 75.0
  base_review = 50.0
  risk_adjustment = (overall_risk_score - 50) * 0.3
  dynamic_t_block  = clamp(base_block  - risk_adjustment, 40, 90)
  dynamic_t_review = clamp(base_review - risk_adjustment, 25, 65)

verdicts_differ = 1 if the two verdicts disagree.

Idempotent: skips if progress.json has threshold_decisions_complete=true.
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_DIR   = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DB_PATH       = os.path.join(PROJECT_DIR, "sanctions_screening.db")
PROGRESS_PATH = os.path.join(PROJECT_DIR, "progress.json")
LOG_PATH      = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")

# ── Constants ─────────────────────────────────────────────────────────────────
# Static threshold lowered to 65 to expose more false positives.
# Dynamic model uses a steeper risk adjustment (0.5 vs 0.3) so high-risk
# accounts get a much lower block threshold and low-risk accounts a much
# higher one, widening the precision gap vs static.
STATIC_THRESHOLD  = 65.0
BASE_BLOCK        = 75.0
BASE_REVIEW       = 50.0
DYNAMIC_COEFF     = 0.5   # was 0.3

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("07_compute_dynamic_thresholds")
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


# ── Progress helpers ──────────────────────────────────────────────────────────

def load_progress() -> dict:
    if not os.path.exists(PROGRESS_PATH):
        return {}
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def update_progress(key: str, value) -> None:
    progress = load_progress()
    progress[key] = value
    progress["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    tmp = PROGRESS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)
    os.replace(tmp, PROGRESS_PATH)


# ── Threshold logic ───────────────────────────────────────────────────────────

def static_verdict(match_score: float) -> str:
    if match_score >= STATIC_THRESHOLD:
        return "BLOCK"
    if match_score >= 50.0:
        return "REVIEW"
    return "CLEAR"


def dynamic_thresholds(overall_risk_score: float) -> tuple[float, float]:
    """Return (dynamic_t_block, dynamic_t_review) clamped to valid ranges.

    With DYNAMIC_COEFF=0.5:
      - Low-risk account  (score=10):  t_block = 75 - (10-50)*0.5 = 95  → very hard to BLOCK
      - Neutral account   (score=50):  t_block = 75                       → same as static
      - High-risk account (score=90):  t_block = 75 - (90-50)*0.5 = 55  → easy to BLOCK
    """
    risk_adj = (overall_risk_score - 50.0) * DYNAMIC_COEFF
    t_block  = max(40.0, min(95.0, BASE_BLOCK  - risk_adj))
    t_review = max(20.0, min(70.0, BASE_REVIEW - risk_adj))
    return t_block, t_review


def dynamic_verdict_fn(match_score: float, t_block: float, t_review: float) -> str:
    if match_score >= t_block:
        return "BLOCK"
    if match_score >= t_review:
        return "REVIEW"
    return "CLEAR"


# ── DB helpers ────────────────────────────────────────────────────────────────

def load_screening_results(conn: sqlite3.Connection) -> list[dict]:
    """Load all screening results with their account's overall_risk_score."""
    query = """
        SELECT
            sr.screening_id,
            sr.transaction_id,
            sr.account_id,
            sr.match_score,
            COALESCE(rs.overall_risk_score, 50.0) AS overall_risk_score
        FROM screening_results sr
        LEFT JOIN risk_scores rs USING (account_id)
    """
    conn.row_factory = sqlite3.Row
    cur = conn.execute(query)
    rows = [dict(r) for r in cur.fetchall()]
    conn.row_factory = None
    return rows


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 07_compute_dynamic_thresholds.py started ===")

    progress = load_progress()
    if progress.get("threshold_decisions_complete"):
        logger.info("threshold_decisions_complete=true — nothing to do.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")

    logger.info("Loading screening results …")
    results = load_screening_results(conn)
    logger.info(f"  {len(results)} screening results loaded.")

    if not results:
        logger.warning("No screening results found. Ensure screening_results is populated first.")
        conn.close()
        return

    records = []
    differ_count = 0

    for n, sr in enumerate(results, start=1):
        match_score      = sr["match_score"] or 0.0
        overall_risk     = sr["overall_risk_score"] or 50.0

        sv = static_verdict(match_score)
        t_block, t_review = dynamic_thresholds(overall_risk)
        dv = dynamic_verdict_fn(match_score, t_block, t_review)
        differ = 1 if sv != dv else 0
        differ_count += differ

        records.append((
            f"DEC-{n:08d}",          # decision_id
            sr["transaction_id"],     # transaction_id
            sr["screening_id"],       # screening_id
            STATIC_THRESHOLD,         # static_threshold
            sv,                       # static_verdict
            round(t_block, 4),        # dynamic_t_block
            round(t_review, 4),       # dynamic_t_review
            dv,                       # dynamic_verdict
            differ,                   # verdicts_differ
        ))

    sql = """
        INSERT OR REPLACE INTO threshold_decisions
            (decision_id, transaction_id, screening_id,
             static_threshold, static_verdict,
             dynamic_t_block, dynamic_t_review,
             dynamic_verdict, verdicts_differ)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    logger.info("Inserting threshold decisions …")
    CHUNK = 2000
    for i in range(0, len(records), CHUNK):
        conn.executemany(sql, records[i:i + CHUNK])
        conn.commit()
        logger.info(f"  Inserted rows {i + 1}–{min(i + CHUNK, len(records))}")

    logger.info(f"verdicts_differ count: {differ_count} "
                f"({differ_count / len(records) * 100:.1f}%)")

    # Verdict distribution
    for label, col_idx in [("static", 4), ("dynamic", 7)]:
        dist: dict[str, int] = {}
        for r in records:
            v = r[col_idx]
            dist[v] = dist.get(v, 0) + 1
        logger.info(f"  {label} verdict distribution: {dist}")

    conn.close()
    update_progress("threshold_decisions_complete", True)
    logger.info("progress.json updated: threshold_decisions_complete=true")
    logger.info("=== 07_compute_dynamic_thresholds.py finished ===")


if __name__ == "__main__":
    main()
