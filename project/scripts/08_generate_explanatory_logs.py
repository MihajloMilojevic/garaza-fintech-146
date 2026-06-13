"""
08_generate_explanatory_logs.py
================================
Generate narrative explanations for:
  1. All CRITICAL/HIGH risk-score accounts
  2. All threshold_decisions where verdicts_differ=1
  3. Top 1000 screening_results by match_score
  4. A random sample of 500 low-risk accounts (contrast/explainability)

Insert rows into `explanatory_logs`.

Idempotent: skips if progress.json has explanatory_logs_complete=true.
"""

import json
import logging
import os
import random
import sqlite3
import sys
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_DIR   = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DB_PATH       = os.path.join(PROJECT_DIR, "sanctions_screening.db")
PROGRESS_PATH = os.path.join(PROJECT_DIR, "progress.json")
LOG_PATH      = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")

STATIC_THRESHOLD = 75.0

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("08_generate_explanatory_logs")
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


# ── Narrative builders ────────────────────────────────────────────────────────

COMPONENT_WEIGHTS = {
    "geographic_risk":           0.25,
    "identity_kyc_risk":         0.15,
    "pep_sanctions_risk":        0.30,
    "behavioural_risk":          0.20,
    "relationship_network_risk": 0.10,
}

COMPONENT_LABELS = {
    "geographic_risk":           "Geographic risk",
    "identity_kyc_risk":         "Identity/KYC risk",
    "pep_sanctions_risk":        "PEP/Sanctions risk",
    "behavioural_risk":          "Behavioural risk",
    "relationship_network_risk": "Relationship network risk",
}


def top_factors(rs: dict, n: int = 3) -> list[dict]:
    """Return top-n risk components sorted by weighted contribution."""
    components = [
        ("geographic_risk",           rs.get("geographic_risk", 0.0)),
        ("identity_kyc_risk",         rs.get("identity_kyc_risk", 0.0)),
        ("pep_sanctions_risk",        rs.get("pep_sanctions_risk", 0.0)),
        ("behavioural_risk",          rs.get("behavioural_risk", 0.0)),
        ("relationship_network_risk", rs.get("relationship_network_risk", 0.0)),
    ]
    components.sort(key=lambda x: x[1] * COMPONENT_WEIGHTS[x[0]], reverse=True)
    return [
        {"name": name, "score": round(score, 1), "weight": COMPONENT_WEIGHTS[name]}
        for name, score in components[:n]
    ]


def top_factors_json(rs: dict) -> str:
    return json.dumps({"factors": top_factors(rs, 3)})


def extra_context_for_risk(rs: dict, acct: dict, pep_map: dict,
                            txn_stats: dict) -> str:
    """Build a short extra-context sentence for the risk narrative."""
    account_id = rs.get("account_id", "")
    name_match = (acct.get("name_match_type") or "").lower()

    if name_match in ("exact", "alias"):
        return "The account is linked to a sanctioned entity via a direct name match."

    if name_match in ("fuzzy", "near_miss", "fuzzy_near_miss"):
        return "A fuzzy name match against a sanctioned entity was detected."

    pep_id = acct.get("pep_id") or ""
    if pep_id and pep_id in pep_map:
        position = pep_map[pep_id].get("position", "unknown position")
        return f"PEP status detected (position: {position})."

    stats = txn_stats.get(account_id)
    if stats:
        v = stats.get("velocity_30d_count", 0)
        amt = stats.get("max_amount", 0.0)
        if v > 10 or amt > 50_000:
            return (f"High transaction velocity "
                    f"(30d: {v} txns, ${amt:,.0f} max single amount).")

    return "No single dominant risk driver identified; risk is composite."


def build_risk_narrative(rs: dict, acct: dict, pep_map: dict,
                          txn_stats: dict) -> str:
    account_id = rs.get("account_id", "?")
    score      = rs.get("overall_risk_score", 0.0)
    band       = rs.get("risk_band", "?")
    factors    = top_factors(rs, 2)
    f1_name    = COMPONENT_LABELS.get(factors[0]["name"], factors[0]["name"]) if factors else "N/A"
    f1_score   = factors[0]["score"] if factors else 0.0
    f2_name    = COMPONENT_LABELS.get(factors[1]["name"], factors[1]["name"]) if len(factors) > 1 else "N/A"
    f2_score   = factors[1]["score"] if len(factors) > 1 else 0.0
    extra      = extra_context_for_risk(rs, acct, pep_map, txn_stats)

    return (
        f"Account {account_id} received an overall risk score of {score:.0f}/100 ({band}). "
        f"Primary drivers: {f1_name} ({f1_score:.0f}/100), {f2_name} ({f2_score:.0f}/100). "
        f"{extra}"
    )


def build_threshold_narrative(td: dict, sr_risk: float) -> str:
    dyn_t_block  = td.get("dynamic_t_block", 75.0)
    match_score  = td.get("match_score", 0.0)
    dyn_verdict  = td.get("dynamic_verdict", "?")
    stat_verdict = td.get("static_verdict", "?")
    sensitivity  = "more sensitive" if dyn_t_block < STATIC_THRESHOLD else "less sensitive"

    return (
        f"The dynamic threshold model set a block threshold of {dyn_t_block:.1f} "
        f"(vs static {STATIC_THRESHOLD:.1f}) for this screening event, reflecting "
        f"account risk score of {sr_risk:.0f}. "
        f"The match score of {match_score:.1f} resulted in a {dyn_verdict} decision "
        f"under the dynamic model vs {stat_verdict} under static rules. "
        f"This represents a {sensitivity} posture."
    )


def build_screening_narrative(sr: dict) -> str:
    acct_name   = sr.get("account_full_name") or sr.get("account_id", "?")
    entity_id   = sr.get("matched_entity_id") or "UNKNOWN"
    entity_name = sr.get("entity_name") or entity_id
    score       = sr.get("match_score", 0.0)
    field       = sr.get("match_field") or "name"
    verdict     = sr.get("verdict_ground_truth") or "?"

    return (
        f"Name match detected against {entity_id}: '{acct_name}' vs sanctioned "
        f"entity '{entity_name}'. "
        f"Match score: {score:.1f}/100 ({field}). "
        f"Ground truth: {verdict}."
    )


# ── DB loaders ────────────────────────────────────────────────────────────────

def fetch_rows(conn: sqlite3.Connection, query: str, params=()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.row_factory = None
    return rows


def load_high_critical_risk_scores(conn: sqlite3.Connection) -> list[dict]:
    return fetch_rows(conn,
        "SELECT * FROM risk_scores WHERE risk_band IN ('CRITICAL', 'HIGH')")


def load_low_risk_sample(conn: sqlite3.Connection, n: int,
                          rng: random.Random) -> list[dict]:
    rows = fetch_rows(conn,
        "SELECT * FROM risk_scores WHERE risk_band = 'LOW'")
    return rng.sample(rows, min(n, len(rows)))


def load_differing_threshold_decisions(conn: sqlite3.Connection) -> list[dict]:
    return fetch_rows(conn,
        """
        SELECT td.*, sr.match_score, sr.account_id
        FROM threshold_decisions td
        JOIN screening_results sr ON td.screening_id = sr.screening_id
        WHERE td.verdicts_differ = 1
        """)


def load_top_screening_results(conn: sqlite3.Connection, n: int) -> list[dict]:
    return fetch_rows(conn,
        f"""
        SELECT sr.*,
               a.full_name AS account_full_name,
               rs.overall_risk_score
        FROM screening_results sr
        LEFT JOIN accounts a ON sr.account_id = a.account_id
        LEFT JOIN risk_scores rs ON sr.account_id = rs.account_id
        ORDER BY sr.match_score DESC
        LIMIT {n}
        """)


def load_accounts_map(conn: sqlite3.Connection) -> dict:
    rows = fetch_rows(conn, "SELECT * FROM accounts")
    return {r["account_id"]: r for r in rows}


def load_pep_map(conn: sqlite3.Connection) -> dict:
    try:
        rows = fetch_rows(conn, "SELECT pep_id, is_current, position FROM peps")
        return {r["pep_id"]: r for r in rows}
    except sqlite3.OperationalError:
        return {}


def load_txn_stats(conn: sqlite3.Connection) -> dict:
    try:
        rows = fetch_rows(conn, """
            SELECT sender_account_id,
                   COUNT(*)              AS total_count,
                   MAX(velocity_30d_count) AS velocity_30d_count,
                   MAX(amount)           AS max_amount
            FROM transactions
            GROUP BY sender_account_id
        """)
        return {r["sender_account_id"]: r for r in rows}
    except sqlite3.OperationalError:
        return {}


def load_risk_score_map(conn: sqlite3.Connection) -> dict:
    rows = fetch_rows(conn, "SELECT * FROM risk_scores")
    return {r["account_id"]: r for r in rows}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 08_generate_explanatory_logs.py started ===")

    progress = load_progress()
    if progress.get("explanatory_logs_complete"):
        logger.info("explanatory_logs_complete=true — nothing to do.")
        return

    rng = random.Random(99)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")

    logger.info("Loading auxiliary data …")
    acct_map       = load_accounts_map(conn)
    pep_map        = load_pep_map(conn)
    txn_stats      = load_txn_stats(conn)
    risk_score_map = load_risk_score_map(conn)

    log_rows: list[tuple] = []
    log_counter = 0

    def emit(related_table: str, related_id: str,
             narrative: str, top_factors_str: str | None) -> None:
        nonlocal log_counter
        log_counter += 1
        log_rows.append((
            f"LOG-{log_counter:08d}",
            related_table,
            related_id,
            narrative,
            top_factors_str,
        ))

    # ── 1. CRITICAL / HIGH risk scores ───────────────────────────────────────
    logger.info("Generating narratives for CRITICAL/HIGH risk accounts …")
    high_crit = load_high_critical_risk_scores(conn)
    logger.info(f"  Found {len(high_crit)} CRITICAL/HIGH records.")
    for rs in high_crit:
        acct    = acct_map.get(rs["account_id"], {})
        narr    = build_risk_narrative(rs, acct, pep_map, txn_stats)
        tf_json = top_factors_json(rs)
        emit("risk_scores", rs["risk_score_id"], narr, tf_json)

    # ── 2. LOW risk accounts (sample of 500) ─────────────────────────────────
    logger.info("Generating narratives for low-risk account sample …")
    low_sample = load_low_risk_sample(conn, 500, rng)
    logger.info(f"  Sampled {len(low_sample)} LOW-risk records.")
    for rs in low_sample:
        acct    = acct_map.get(rs["account_id"], {})
        narr    = build_risk_narrative(rs, acct, pep_map, txn_stats)
        tf_json = top_factors_json(rs)
        emit("risk_scores", rs["risk_score_id"], narr, tf_json)

    # ── 3. Differing threshold decisions ──────────────────────────────────────
    logger.info("Generating narratives for differing threshold decisions …")
    diff_tds = load_differing_threshold_decisions(conn)
    logger.info(f"  Found {len(diff_tds)} differing decisions.")
    for td in diff_tds:
        account_id   = td.get("account_id")
        rs           = risk_score_map.get(account_id, {})
        overall_risk = rs.get("overall_risk_score", 50.0)
        narr         = build_threshold_narrative(td, overall_risk)
        tf_json      = top_factors_json(rs) if rs else None
        emit("threshold_decisions", td["decision_id"], narr, tf_json)

    # ── 4. Top 1000 screening results by match score ──────────────────────────
    logger.info("Generating narratives for top-1000 screening results …")
    top_sr = load_top_screening_results(conn, 1000)
    logger.info(f"  Loaded {len(top_sr)} top screening results.")
    for sr in top_sr:
        narr    = build_screening_narrative(sr)
        account_id = sr.get("account_id")
        rs      = risk_score_map.get(account_id, {})
        tf_json = top_factors_json(rs) if rs else None
        emit("screening_results", sr["screening_id"], narr, tf_json)

    logger.info(f"Total log entries to insert: {len(log_rows)}")

    sql = """
        INSERT OR REPLACE INTO explanatory_logs
            (log_id, related_table, related_id, narrative, top_factors_json)
        VALUES (?, ?, ?, ?, ?)
    """
    CHUNK = 500
    for i in range(0, len(log_rows), CHUNK):
        conn.executemany(sql, log_rows[i:i + CHUNK])
        conn.commit()
        logger.info(f"  Inserted rows {i + 1}–{min(i + CHUNK, len(log_rows))}")

    conn.close()
    update_progress("explanatory_logs_complete", True)
    logger.info("progress.json updated: explanatory_logs_complete=true")
    logger.info("=== 08_generate_explanatory_logs.py finished ===")


if __name__ == "__main__":
    main()
