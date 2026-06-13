"""
09_comparison_report.py
========================
Generate comparison_summary.md and comparison_summary.json in the project root.

Sections:
  1. Dataset summary (table row counts, verdict distribution, progress sources)
  2. Static vs dynamic threshold comparison (verdicts_differ, confusion matrix, P/R/F1)
  3. Risk score distribution (by band, mean/std overall and by account_type)
  4. Key metrics table

Idempotent: skips if progress.json has comparison_summary_complete=true.
"""

import json
import logging
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_DIR   = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DB_PATH       = os.path.join(PROJECT_DIR, "sanctions_screening.db")
PROGRESS_PATH = os.path.join(PROJECT_DIR, "progress.json")
LOG_PATH      = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")
MD_OUT        = os.path.join(PROJECT_DIR, "comparison_summary.md")
JSON_OUT      = os.path.join(PROJECT_DIR, "comparison_summary.json")

TABLES = [
    "accounts",
    "account_relationships",
    "wallets",
    "transactions",
    "screening_results",
    "risk_scores",
    "threshold_decisions",
    "explanatory_logs",
]

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("09_comparison_report")
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


# ── DB helpers ────────────────────────────────────────────────────────────────

def table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0


def fetch_one(conn: sqlite3.Connection, query: str, params=()) -> tuple | None:
    try:
        return conn.execute(query, params).fetchone()
    except sqlite3.OperationalError:
        return None


def fetch_all(conn: sqlite3.Connection, query: str, params=()) -> list[tuple]:
    try:
        return conn.execute(query, params).fetchall()
    except sqlite3.OperationalError:
        return []


# ── Statistics helpers ────────────────────────────────────────────────────────

def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    prec = safe_div(tp, tp + fp)
    rec  = safe_div(tp, tp + fn)
    f1   = safe_div(2 * prec * rec, prec + rec)
    return prec, rec, f1


def std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


# ── Section builders ──────────────────────────────────────────────────────────

def build_dataset_summary(conn: sqlite3.Connection,
                           progress: dict) -> tuple[dict, list[str]]:
    row_counts = {t: table_count(conn, t) for t in TABLES}

    # Verdict distribution
    verdict_rows = fetch_all(conn,
        "SELECT verdict_ground_truth, COUNT(*) FROM screening_results "
        "GROUP BY verdict_ground_truth")
    verdict_dist = {row[0]: row[1] for row in verdict_rows}
    total_sr = sum(verdict_dist.values())

    sources = {
        "sanctioned_entities": progress.get("sanctioned_entities_source", "unknown"),
        "peps":                progress.get("peps_source", "unknown"),
        "matching_pairs":      progress.get("matching_pairs_source", "unknown"),
        "aml_shape":           progress.get("aml_shape_source", "unknown"),
        "relationships":       progress.get("relationships_source", "unknown"),
    }

    data = {
        "row_counts":    row_counts,
        "verdict_dist":  verdict_dist,
        "total_sr":      total_sr,
        "sources":       sources,
    }

    lines = [
        "## 1. Dataset Summary",
        "",
        "### Table Row Counts",
        "",
        "| Table | Row Count |",
        "|---|---|",
    ]
    for t in TABLES:
        lines.append(f"| {t} | {row_counts[t]:,} |")

    lines += [
        "",
        "### Screening Result Verdict Distribution",
        "",
        "| Verdict | Count | % |",
        "|---|---|---|",
    ]
    for v, c in sorted(verdict_dist.items()):
        pct = safe_div(c, total_sr) * 100
        lines.append(f"| {v} | {c:,} | {pct:.1f}% |")

    lines += [
        "",
        "### Reference Data Sources",
        "",
        "| Source | Value |",
        "|---|---|",
    ]
    for k, v in sources.items():
        lines.append(f"| {k} | {v or 'unknown'} |")

    return data, lines


def build_threshold_comparison(conn: sqlite3.Connection) -> tuple[dict, list[str]]:
    # Join threshold_decisions with screening_results for ground truth
    rows = fetch_all(conn, """
        SELECT td.static_verdict, td.dynamic_verdict, td.verdicts_differ,
               sr.verdict_ground_truth
        FROM threshold_decisions td
        JOIN screening_results sr ON td.screening_id = sr.screening_id
    """)

    if not rows:
        return {}, ["## 2. Static vs Dynamic Threshold Comparison", "", "_No data._"]

    total = len(rows)
    differ_count = sum(1 for r in rows if r[2] == 1)

    # Confusion matrix counts: positive class = BLOCK
    # Ground truth positive: verdict_ground_truth == 'BLOCK'
    def classify(pred: str, truth: str) -> str:
        pos_pred  = pred == "BLOCK"
        pos_truth = truth == "BLOCK"
        if pos_pred and pos_truth:
            return "TP"
        if pos_pred and not pos_truth:
            return "FP"
        if not pos_pred and pos_truth:
            return "FN"
        return "TN"

    stat_counts = {"TP": 0, "FP": 0, "FN": 0, "TN": 0}
    dyn_counts  = {"TP": 0, "FP": 0, "FN": 0, "TN": 0}
    confusion = {}  # (static_verdict, dynamic_verdict) → count

    for stat_v, dyn_v, _, truth in rows:
        truth = truth or "CLEAR"
        stat_counts[classify(stat_v, truth)] += 1
        dyn_counts[classify(dyn_v, truth)]   += 1
        key = (stat_v, dyn_v)
        confusion[key] = confusion.get(key, 0) + 1

    stat_prec, stat_rec, stat_f1 = precision_recall_f1(
        stat_counts["TP"], stat_counts["FP"], stat_counts["FN"])
    dyn_prec, dyn_rec, dyn_f1 = precision_recall_f1(
        dyn_counts["TP"], dyn_counts["FP"], dyn_counts["FN"])

    data = {
        "total_decisions":      total,
        "verdicts_differ_count": differ_count,
        "verdicts_differ_pct":  round(safe_div(differ_count, total) * 100, 2),
        "confusion_matrix":     {f"{k[0]}_static_{k[1]}_dynamic": v
                                 for k, v in confusion.items()},
        "static_tp":  stat_counts["TP"],
        "static_fp":  stat_counts["FP"],
        "static_fn":  stat_counts["FN"],
        "static_tn":  stat_counts["TN"],
        "static_precision": round(stat_prec, 4),
        "static_recall":    round(stat_rec, 4),
        "static_f1":        round(stat_f1, 4),
        "dynamic_tp":  dyn_counts["TP"],
        "dynamic_fp":  dyn_counts["FP"],
        "dynamic_fn":  dyn_counts["FN"],
        "dynamic_tn":  dyn_counts["TN"],
        "dynamic_precision": round(dyn_prec, 4),
        "dynamic_recall":    round(dyn_rec, 4),
        "dynamic_f1":        round(dyn_f1, 4),
    }

    lines = [
        "## 2. Static vs Dynamic Threshold Comparison",
        "",
        f"Total decisions evaluated: **{total:,}**",
        f"Verdicts differ: **{differ_count:,}** ({safe_div(differ_count, total)*100:.1f}%)",
        "",
        "### Confusion Matrix (static_verdict → dynamic_verdict)",
        "",
        "| Static \\ Dynamic | BLOCK | REVIEW | CLEAR |",
        "|---|---|---|---|",
    ]
    for sv in ["BLOCK", "REVIEW", "CLEAR"]:
        cells = [str(confusion.get((sv, dv), 0)) for dv in ["BLOCK", "REVIEW", "CLEAR"]]
        lines.append(f"| {sv} | {' | '.join(cells)} |")

    lines += [
        "",
        "### Classification Metrics (positive class = BLOCK)",
        "",
        "| Metric | Static | Dynamic |",
        "|---|---|---|",
        f"| Precision | {stat_prec:.4f} | {dyn_prec:.4f} |",
        f"| Recall    | {stat_rec:.4f}  | {dyn_rec:.4f}  |",
        f"| F1        | {stat_f1:.4f}   | {dyn_f1:.4f}   |",
        f"| TP        | {stat_counts['TP']:,} | {dyn_counts['TP']:,} |",
        f"| FP        | {stat_counts['FP']:,} | {dyn_counts['FP']:,} |",
        f"| FN        | {stat_counts['FN']:,} | {dyn_counts['FN']:,} |",
        f"| TN        | {stat_counts['TN']:,} | {dyn_counts['TN']:,} |",
    ]
    return data, lines


def build_risk_distribution(conn: sqlite3.Connection) -> tuple[dict, list[str]]:
    band_rows = fetch_all(conn,
        "SELECT risk_band, COUNT(*) FROM risk_scores GROUP BY risk_band")
    band_counts = {r[0]: r[1] for r in band_rows}

    # Overall mean/std
    score_rows = fetch_all(conn, "SELECT overall_risk_score FROM risk_scores")
    all_scores = [r[0] for r in score_rows if r[0] is not None]
    overall_mean = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0
    overall_std  = round(std(all_scores), 4) if all_scores else 0.0

    # By account_type
    type_rows = fetch_all(conn, """
        SELECT a.account_type, rs.overall_risk_score
        FROM risk_scores rs
        JOIN accounts a ON rs.account_id = a.account_id
    """)
    type_scores: dict[str, list] = {}
    for atype, score in type_rows:
        if score is not None:
            type_scores.setdefault(atype or "unknown", []).append(score)

    type_stats = {}
    for atype, scores in type_scores.items():
        type_stats[atype] = {
            "count": len(scores),
            "mean": round(sum(scores) / len(scores), 4),
            "std":  round(std(scores), 4),
        }

    data = {
        "band_counts":   band_counts,
        "overall_mean":  overall_mean,
        "overall_std":   overall_std,
        "by_account_type": type_stats,
    }

    lines = [
        "## 3. Risk Score Distribution",
        "",
        "### Count by Risk Band",
        "",
        "| Band | Count |",
        "|---|---|",
    ]
    for band in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        lines.append(f"| {band} | {band_counts.get(band, 0):,} |")

    lines += [
        "",
        f"Overall risk score — mean: **{overall_mean}**, std: **{overall_std}**",
        "",
        "### Mean ± Std by Account Type",
        "",
        "| Account Type | Count | Mean | Std |",
        "|---|---|---|---|",
    ]
    for atype, stats in sorted(type_stats.items()):
        lines.append(f"| {atype} | {stats['count']:,} | {stats['mean']} | {stats['std']} |")

    return data, lines


def build_key_metrics(threshold_data: dict) -> tuple[dict, list[str]]:
    metrics = {
        "static_precision":       threshold_data.get("static_precision", 0.0),
        "static_recall":          threshold_data.get("static_recall", 0.0),
        "static_f1":              threshold_data.get("static_f1", 0.0),
        "dynamic_precision":      threshold_data.get("dynamic_precision", 0.0),
        "dynamic_recall":         threshold_data.get("dynamic_recall", 0.0),
        "dynamic_f1":             threshold_data.get("dynamic_f1", 0.0),
        "verdicts_differ_count":  threshold_data.get("verdicts_differ_count", 0),
        "verdicts_differ_pct":    threshold_data.get("verdicts_differ_pct", 0.0),
    }
    lines = [
        "## 4. Key Metrics Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| static_precision        | {metrics['static_precision']:.4f} |",
        f"| static_recall           | {metrics['static_recall']:.4f} |",
        f"| static_f1               | {metrics['static_f1']:.4f} |",
        f"| dynamic_precision       | {metrics['dynamic_precision']:.4f} |",
        f"| dynamic_recall          | {metrics['dynamic_recall']:.4f} |",
        f"| dynamic_f1              | {metrics['dynamic_f1']:.4f} |",
        f"| verdicts_differ_count   | {metrics['verdicts_differ_count']:,} |",
        f"| verdicts_differ_pct     | {metrics['verdicts_differ_pct']:.2f}% |",
    ]
    return metrics, lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 09_comparison_report.py started ===")

    progress = load_progress()
    if progress.get("comparison_summary_complete"):
        logger.info("comparison_summary_complete=true — nothing to do.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    logger.info("Building dataset summary …")
    ds_data, ds_lines = build_dataset_summary(conn, progress)

    logger.info("Building threshold comparison …")
    th_data, th_lines = build_threshold_comparison(conn)

    logger.info("Building risk score distribution …")
    rk_data, rk_lines = build_risk_distribution(conn)

    logger.info("Building key metrics …")
    km_data, km_lines = build_key_metrics(th_data)

    conn.close()

    # ── Markdown output ───────────────────────────────────────────────────────
    header = [
        "# Sanctions Screening Dataset — Comparison Summary",
        "",
        f"_Generated at: {generated_at}_",
        "",
    ]
    all_lines = header + ds_lines + [""] + th_lines + [""] + rk_lines + [""] + km_lines
    md_content = "\n".join(all_lines) + "\n"

    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write(md_content)
    logger.info(f"Markdown report written to: {MD_OUT}")

    # ── JSON output ───────────────────────────────────────────────────────────
    json_data = {
        "generated_at":       generated_at,
        "dataset_summary":    ds_data,
        "threshold_comparison": th_data,
        "risk_distribution":  rk_data,
        "key_metrics":        km_data,
    }
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2)
    logger.info(f"JSON report written to: {JSON_OUT}")

    update_progress("comparison_summary_complete", True)
    logger.info("progress.json updated: comparison_summary_complete=true")
    logger.info("=== 09_comparison_report.py finished ===")


if __name__ == "__main__":
    main()
