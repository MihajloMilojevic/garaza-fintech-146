"""
00_init_db.py
=============
Creates the SQLite database schema for the sanctions screening dataset pipeline.

Idempotent: skips if progress.json already has schema_complete=true.
Logs to logs/generation_log.txt and updates progress.json on completion.
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR   = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DB_PATH       = os.path.join(PROJECT_DIR, "sanctions_screening.db")
PROGRESS_PATH = os.path.join(PROJECT_DIR, "progress.json")
LOG_PATH      = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")

# ── DDL ──────────────────────────────────────────────────────────────────────
DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS accounts (
        account_id               TEXT PRIMARY KEY,
        account_type             TEXT,
        full_name                TEXT,
        country_residence        TEXT,
        country_incorporation    TEXT,
        date_of_birth            TEXT,
        nationality              TEXT,
        created_at               TEXT,
        kyc_completeness         REAL,
        kyc_status               TEXT,
        is_pep                   INTEGER,
        pep_id                   TEXT,
        has_complex_ownership    INTEGER,
        shell_company_flag       INTEGER,
        sanctioned_entity_id     TEXT,
        name_match_type          TEXT,
        account_status           TEXT,
        activity_tier            TEXT,
        initial_risk_band        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_relationships (
        relationship_id             TEXT PRIMARY KEY,
        account_id                  TEXT,
        related_entity_name         TEXT,
        relationship_type           TEXT,
        related_is_pep              INTEGER,
        related_is_sanctioned       INTEGER,
        related_sanctioned_entity_id TEXT,
        source                      TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wallets (
        wallet_id              TEXT PRIMARY KEY,
        account_id             TEXT,
        wallet_address         TEXT,
        chain                  TEXT,
        is_sanctioned          INTEGER,
        sanctioned_entity_id   TEXT,
        hops_to_sanctioned     INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        transaction_id           TEXT PRIMARY KEY,
        sender_account_id        TEXT,
        recipient_account_id     TEXT,
        recipient_type           TEXT,
        recipient_name           TEXT,
        recipient_country        TEXT,
        recipient_wallet_id      TEXT,
        amount                   REAL,
        currency                 TEXT,
        payment_rail             TEXT,
        timestamp                TEXT,
        is_first_time_recipient  INTEGER,
        sender_account_age_days  INTEGER,
        velocity_30d_count       INTEGER,
        velocity_30d_amount      REAL,
        hour_of_day              INTEGER,
        day_of_week              INTEGER,
        shape_source             TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS screening_results (
        screening_id                    TEXT PRIMARY KEY,
        transaction_id                  TEXT,
        account_id                      TEXT,
        screening_context               TEXT,
        matched_entity_id               TEXT,
        match_score                     REAL,
        match_field                     TEXT,
        fuzzy_match_type                TEXT,
        hops_to_sanctioned              INTEGER,
        shares_address_with_sanctioned  INTEGER,
        pep_exposure_score              REAL,
        country_risk_score              REAL,
        verdict_ground_truth            TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_scores (
        risk_score_id              TEXT PRIMARY KEY,
        account_id                 TEXT,
        computed_at                TEXT,
        geographic_risk            REAL,
        identity_kyc_risk          REAL,
        pep_sanctions_risk         REAL,
        behavioural_risk           REAL,
        relationship_network_risk  REAL,
        overall_risk_score         REAL,
        risk_band                  TEXT,
        override_applied           INTEGER,
        override_reason            TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS threshold_decisions (
        decision_id       TEXT PRIMARY KEY,
        transaction_id    TEXT,
        screening_id      TEXT,
        static_threshold  REAL,
        static_verdict    TEXT,
        dynamic_t_block   REAL,
        dynamic_t_review  REAL,
        dynamic_verdict   TEXT,
        verdicts_differ   INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS explanatory_logs (
        log_id           TEXT PRIMARY KEY,
        related_table    TEXT,
        related_id       TEXT,
        narrative        TEXT,
        top_factors_json TEXT
    )
    """,
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """Configure logging to both file and stdout."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("00_init_db")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")
    # File handler (append)
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    # Stdout handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def load_progress() -> dict:
    """Load progress.json; return empty dict if missing or corrupt."""
    if not os.path.exists(PROGRESS_PATH):
        return {}
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def update_progress(key: str, value) -> None:
    """Atomically read-modify-write progress.json."""
    progress = load_progress()
    progress[key] = value
    progress["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    tmp_path = PROGRESS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)
    os.replace(tmp_path, PROGRESS_PATH)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 00_init_db.py started ===")

    # Check progress
    progress = load_progress()
    if progress.get("schema_complete") is True:
        logger.info("schema_complete=true in progress.json — nothing to do, exiting.")
        print("Schema already initialised. Delete progress.json or set schema_complete=false to re-run.")
        return

    # Ensure DB directory exists
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)

    logger.info(f"Creating/opening database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        cursor = conn.cursor()
        table_names = [
            "accounts",
            "account_relationships",
            "wallets",
            "transactions",
            "screening_results",
            "risk_scores",
            "threshold_decisions",
            "explanatory_logs",
        ]

        for i, (ddl, tname) in enumerate(zip(DDL_STATEMENTS, table_names), start=1):
            logger.info(f"  [{i}/{len(DDL_STATEMENTS)}] Creating table: {tname}")
            cursor.execute(ddl)
            conn.commit()
            logger.info(f"    OK — {tname}")

        # Verify all tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        existing = {row[0] for row in cursor.fetchall()}
        missing = set(table_names) - existing
        if missing:
            raise RuntimeError(f"Tables missing after creation: {missing}")

        logger.info(f"All {len(table_names)} tables confirmed in database.")

    except Exception as exc:
        logger.error(f"Fatal error during schema creation: {exc}", exc_info=True)
        conn.close()
        sys.exit(1)

    conn.close()
    logger.info("Database connection closed.")

    # Mark complete
    update_progress("schema_complete", True)
    logger.info("progress.json updated: schema_complete=true")
    logger.info("=== 00_init_db.py finished successfully ===")
    print("Done. Database schema created successfully.")


if __name__ == "__main__":
    main()
