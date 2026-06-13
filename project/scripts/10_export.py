"""
10_export.py
============
Export all tables to compressed Parquet files in project/exports/.

For each table:
  - Read from SQLite
  - Write to exports/{table}.parquet (zstd compression)
  - If the resulting file > 90 MB, split into parts by row range and write
    exports/{table}_manifest.json

Also writes:
  - exports/load_dataset.py  — helper loader
  - exports/README.md        — dataset documentation

Idempotent: skips if progress.json has export_complete=true.
Requires: pandas, pyarrow
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_DIR   = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DB_PATH       = os.path.join(PROJECT_DIR, "sanctions_screening.db")
PROGRESS_PATH = os.path.join(PROJECT_DIR, "progress.json")
LOG_PATH      = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")
EXPORTS_DIR   = os.path.join(PROJECT_DIR, "exports")
GARAZA_DIR    = "/home/mihajlo/Mihajlo/Projekti/garaza"

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

MAX_FILE_BYTES = 90 * 1024 * 1024   # 90 MB split threshold

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("10_export")
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


# ── Export helpers ────────────────────────────────────────────────────────────

def export_table(table: str, conn: sqlite3.Connection,
                 exports_dir: Path, logger: logging.Logger) -> dict:
    """
    Read `table` from SQLite, write to Parquet.
    Returns metadata dict: {table, total_rows, parts, file_sizes}.
    """
    import pandas as pd

    logger.info(f"  Reading table: {table}")
    df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    total_rows = len(df)
    logger.info(f"    {total_rows:,} rows, {len(df.columns)} columns")

    base_path = exports_dir / f"{table}.parquet"

    # Write initial file
    df.to_parquet(str(base_path), engine="pyarrow",
                  compression="zstd", index=False)
    file_size = base_path.stat().st_size
    logger.info(f"    Written {file_size / 1024 / 1024:.1f} MB → {base_path.name}")

    if file_size <= MAX_FILE_BYTES:
        return {
            "table":      table,
            "total_rows": total_rows,
            "parts":      [f"{table}.parquet"],
            "file_sizes": [file_size],
            "split":      False,
        }

    # Split needed: remove the combined file, write parts
    logger.info(f"    File exceeds 90 MB — splitting …")
    base_path.unlink()

    # Estimate how many parts are needed
    n_parts = max(2, math.ceil(file_size / MAX_FILE_BYTES))
    rows_per_part = math.ceil(total_rows / n_parts)

    part_names  = []
    row_ranges  = []
    file_sizes  = []

    for part_idx in range(n_parts):
        start = part_idx * rows_per_part
        end   = min(start + rows_per_part, total_rows)
        if start >= total_rows:
            break
        chunk     = df.iloc[start:end]
        part_name = f"{table}_part{part_idx + 1}.parquet"
        part_path = exports_dir / part_name
        chunk.to_parquet(str(part_path), engine="pyarrow",
                         compression="zstd", index=False)
        sz = part_path.stat().st_size
        part_names.append(part_name)
        row_ranges.append([start, end])
        file_sizes.append(sz)
        logger.info(f"    Part {part_idx + 1}: rows {start:,}–{end:,}, "
                    f"{sz / 1024 / 1024:.1f} MB → {part_name}")

    # Write manifest
    manifest = {
        "parts":      part_names,
        "total_rows": total_rows,
        "row_ranges": row_ranges,
    }
    manifest_path = exports_dir / f"{table}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info(f"    Manifest written: {manifest_path.name}")

    return {
        "table":      table,
        "total_rows": total_rows,
        "parts":      part_names,
        "file_sizes": file_sizes,
        "split":      True,
    }


# ── load_dataset.py helper ────────────────────────────────────────────────────

LOAD_DATASET_PY = '''\
import pandas as pd
import pyarrow.parquet as pq
import json
from pathlib import Path


def load_table(table_name, exports_dir="."):
    exports_dir = Path(exports_dir)
    manifest = exports_dir / f"{table_name}_manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text())
        return pd.concat(
            [pd.read_parquet(exports_dir / p) for p in m["parts"]],
            ignore_index=True,
        )
    return pd.read_parquet(exports_dir / f"{table_name}.parquet")
'''


# ── README.md ─────────────────────────────────────────────────────────────────

def build_readme(table_meta: list[dict], progress: dict) -> str:
    sources = {
        "sanctioned_entities": progress.get("sanctioned_entities_source", "unknown"),
        "peps":                progress.get("peps_source", "unknown"),
        "matching_pairs":      progress.get("matching_pairs_source", "unknown"),
        "aml_shape":           progress.get("aml_shape_source", "unknown"),
        "relationships":       progress.get("relationships_source", "unknown"),
    }

    lines = [
        "# Sanctions Screening Synthetic Dataset",
        "",
        "## Overview",
        "",
        "Synthetic dataset for training and evaluating sanctions screening and AML models.",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        "## Tables",
        "",
        "| Table | Rows | File(s) |",
        "|---|---|---|",
    ]
    for m in table_meta:
        files = ", ".join(m["parts"])
        lines.append(f"| {m['table']} | {m['total_rows']:,} | {files} |")

    lines += [
        "",
        "## Column Descriptions (key tables)",
        "",
        "### accounts",
        "| Column | Description |",
        "|---|---|",
        "| account_id | Unique account identifier (ACC-XXXXXXXX) |",
        "| account_type | individual / business |",
        "| full_name | Synthetic name of account holder |",
        "| country_residence | ISO-2 country of residence |",
        "| country_incorporation | ISO-2 country of incorporation (business only) |",
        "| kyc_completeness | 0.0–1.0 fraction of KYC fields completed |",
        "| kyc_status | verified / pending / expired |",
        "| is_pep | 1 if politically exposed person |",
        "| sanctioned_entity_id | Linked sanctioned entity ID (if applicable) |",
        "| name_match_type | exact / alias / fuzzy / null |",
        "| activity_tier | high / medium / low |",
        "",
        "### risk_scores",
        "| Column | Description |",
        "|---|---|",
        "| risk_score_id | RSK-XXXXXXXX |",
        "| account_id | Foreign key to accounts |",
        "| geographic_risk | 0–100 geographic component |",
        "| identity_kyc_risk | 0–100 KYC/identity component |",
        "| pep_sanctions_risk | 0–100 sanctions/PEP component |",
        "| behavioural_risk | 0–100 transaction behaviour component |",
        "| relationship_network_risk | 0–100 network component |",
        "| overall_risk_score | Weighted composite score (0–100) |",
        "| risk_band | CRITICAL / HIGH / MEDIUM / LOW |",
        "| override_applied | 1 if an analyst override was simulated |",
        "| override_reason | Text reason for override or NULL |",
        "",
        "### threshold_decisions",
        "| Column | Description |",
        "|---|---|",
        "| decision_id | DEC-XXXXXXXX |",
        "| screening_id | FK to screening_results |",
        "| static_threshold | Fixed threshold (75.0) |",
        "| static_verdict | BLOCK / REVIEW / CLEAR under static rule |",
        "| dynamic_t_block | Risk-adjusted block threshold |",
        "| dynamic_t_review | Risk-adjusted review threshold |",
        "| dynamic_verdict | BLOCK / REVIEW / CLEAR under dynamic rule |",
        "| verdicts_differ | 1 if the two verdicts disagree |",
        "",
        "## Reference Data Sources",
        "",
        "| Source | Status |",
        "|---|---|",
    ]
    for k, v in sources.items():
        lines.append(f"| {k} | {v or 'unknown'} |")

    lines += [
        "",
        "## Risk Score Formula",
        "",
        "```",
        "overall_risk_score = (",
        "    0.25 * geographic_risk +",
        "    0.15 * identity_kyc_risk +",
        "    0.30 * pep_sanctions_risk +",
        "    0.20 * behavioural_risk +",
        "    0.10 * relationship_network_risk",
        ")",
        "```",
        "Capped at 100. Bands: CRITICAL ≥ 80, HIGH ≥ 60, MEDIUM ≥ 40, LOW < 40.",
        "",
        "## Dynamic Threshold Formula",
        "",
        "```",
        "risk_adjustment  = (overall_risk_score - 50) * 0.3",
        "dynamic_t_block  = clamp(75 - risk_adjustment, 40, 90)",
        "dynamic_t_review = clamp(50 - risk_adjustment, 25, 65)",
        "```",
        "High-risk accounts get a lower (more sensitive) block threshold.",
        "",
        "## Loading the Dataset",
        "",
        "```python",
        "from load_dataset import load_table",
        "",
        "accounts = load_table('accounts')",
        "risk_scores = load_table('risk_scores')",
        "```",
        "",
        "The `load_table` helper automatically handles split files via manifest.",
        "",
        "### Manual load (single file)",
        "```python",
        "import pandas as pd",
        "df = pd.read_parquet('accounts.parquet')",
        "```",
    ]
    return "\n".join(lines) + "\n"


# ── .gitignore / .gitattributes ───────────────────────────────────────────────

GITIGNORE_CONTENT = """\
data/raw/
*.db
__pycache__/
*.pyc
"""

GITATTRIBUTES_CONTENT = """\
exports/*.parquet filter=lfs diff=lfs merge=lfs -text
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 10_export.py started ===")

    progress = load_progress()
    if progress.get("export_complete"):
        logger.info("export_complete=true — nothing to do.")
        return

    try:
        import math
        import pandas as pd
        import pyarrow
    except ImportError as exc:
        logger.error(f"Missing dependency: {exc}. Install with: pip install pandas pyarrow")
        sys.exit(1)

    # Bring math into module scope for use inside export_table
    import math as _math
    globals()["math"] = _math

    exports_dir = Path(EXPORTS_DIR)
    exports_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")

    table_meta = []
    for table in TABLES:
        logger.info(f"Exporting: {table}")
        meta = export_table(table, conn, exports_dir, logger)
        table_meta.append(meta)

    conn.close()

    # ── Write load_dataset.py ──────────────────────────────────────────────
    load_py_path = exports_dir / "load_dataset.py"
    load_py_path.write_text(LOAD_DATASET_PY, encoding="utf-8")
    logger.info(f"Written: {load_py_path}")

    # ── Write README.md ────────────────────────────────────────────────────
    readme_content = build_readme(table_meta, progress)
    readme_path = exports_dir / "README.md"
    readme_path.write_text(readme_content, encoding="utf-8")
    logger.info(f"Written: {readme_path}")

    # ── Write .gitignore ───────────────────────────────────────────────────
    gitignore_path = Path(GARAZA_DIR) / ".gitignore"
    gitignore_path.write_text(GITIGNORE_CONTENT, encoding="utf-8")
    logger.info(f"Written: {gitignore_path}")

    # ── Write .gitattributes ───────────────────────────────────────────────
    gitattributes_path = Path(GARAZA_DIR) / ".gitattributes"
    gitattributes_path.write_text(GITATTRIBUTES_CONTENT, encoding="utf-8")
    logger.info(f"Written: {gitattributes_path}")

    # ── Summary ────────────────────────────────────────────────────────────
    logger.info("Export summary:")
    total_rows_all = 0
    for m in table_meta:
        split_note = f" (split into {len(m['parts'])} parts)" if m["split"] else ""
        logger.info(f"  {m['table']}: {m['total_rows']:,} rows{split_note}")
        total_rows_all += m["total_rows"]
    logger.info(f"  Total rows across all tables: {total_rows_all:,}")

    update_progress("export_complete", True)
    logger.info("progress.json updated: export_complete=true")
    logger.info("=== 10_export.py finished ===")


if __name__ == "__main__":
    main()
