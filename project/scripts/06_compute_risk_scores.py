"""
06_compute_risk_scores.py
=========================
Compute a composite risk score for every account and insert into `risk_scores`.

Five component scores (each 0-100):
  - geographic_risk
  - identity_kyc_risk
  - pep_sanctions_risk
  - behavioural_risk
  - relationship_network_risk

Overall: weighted sum (0.25/0.15/0.30/0.20/0.10), capped at 100.

Idempotent: skips if progress.json has risk_scores_complete=true.
"""

import csv
import json
import logging
import math
import os
import random
import sqlite3
import sys
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_DIR    = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DB_PATH        = os.path.join(PROJECT_DIR, "sanctions_screening.db")
PROGRESS_PATH  = os.path.join(PROJECT_DIR, "progress.json")
LOG_PATH       = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")
REF_DIR        = os.path.join(PROJECT_DIR, "reference_data")
COUNTRY_RISK_CSV = os.path.join(REF_DIR, "country_risk.csv")

# ── Constants ─────────────────────────────────────────────────────────────────
OFFSHORE_COUNTRIES = {"BVI", "VG", "KY", "PA", "BZ", "LI"}

COMPONENT_WEIGHTS = {
    "geographic_risk":           0.25,
    "identity_kyc_risk":         0.15,
    "pep_sanctions_risk":        0.30,
    "behavioural_risk":          0.20,
    "relationship_network_risk": 0.10,
}

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("06_compute_risk_scores")
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


# ── Reference data ────────────────────────────────────────────────────────────

def load_country_risk(path: str) -> dict:
    """Return {country_code: composite_risk_score} from country_risk.csv.

    Falls back to a hard-coded table of common codes if the CSV is missing.
    """
    fallback = {
        "RU": 85, "IR": 90, "KP": 95, "SY": 90, "BY": 80,
        "CN": 55, "AE": 45, "NG": 65, "VE": 70, "PK": 65,
        "UA": 60, "IQ": 75, "LY": 75, "SD": 80, "MM": 70,
        "ZW": 70, "CU": 75, "HT": 65, "AF": 85, "YE": 80,
        "US": 10, "GB": 10, "DE": 10, "FR": 12, "CH": 8,
        "NL": 10, "CA": 10, "AU": 10, "JP": 10, "KR": 12,
        "SG": 12, "HK": 15, "IN": 30, "BR": 35, "MX": 40,
        "KY": 40, "VG": 42, "BVI": 42, "BZ": 38, "PA": 38,
        "LI": 35,
    }
    if not os.path.exists(path):
        return fallback
    result = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = (row.get("country_code") or row.get("code") or "").strip().upper()
                score_raw = (row.get("composite_risk_score") or
                             row.get("risk_score") or
                             row.get("score") or "0")
                try:
                    score = float(score_raw)
                except ValueError:
                    score = 0.0
                if code:
                    result[code] = score
    except Exception:
        return fallback
    if not result:
        return fallback
    return result


# ── Component score functions ─────────────────────────────────────────────────

def compute_geographic_risk(account: dict, country_risk: dict) -> float:
    """Score based on country of residence and incorporation."""
    res_country = (account.get("country_residence") or "").upper()
    inc_country = (account.get("country_incorporation") or "").upper()

    base = country_risk.get(res_country, 20.0)

    # Secondary: if different incorporation country adds half its risk
    if inc_country and inc_country != res_country:
        inc_risk = country_risk.get(inc_country, 20.0)
        base = base + 0.5 * inc_risk

    # Offshore tax haven boost
    if inc_country in OFFSHORE_COUNTRIES and inc_country != res_country:
        base += 20.0

    return min(100.0, base)


def compute_identity_kyc_risk(account: dict) -> float:
    """Score based on KYC completeness and status."""
    kyc_completeness = account.get("kyc_completeness") or 0.0
    kyc_status = (account.get("kyc_status") or "").lower()
    account_type = (account.get("account_type") or "").lower()

    score = 100.0 - (kyc_completeness * 100.0)

    if kyc_status == "expired":
        score += 30.0
    elif kyc_status == "pending":
        score += 20.0

    if account_type == "business" and kyc_completeness < 0.7:
        score += 15.0

    return min(100.0, score)


def compute_pep_sanctions_risk(account: dict, pep_map: dict,
                                rel_flags: dict, rng: random.Random) -> float:
    """Score based on sanctions matches, PEP links, and related-party flags."""
    name_match_type = (account.get("name_match_type") or "").lower()
    account_id = account.get("account_id", "")

    # Direct sanction exact/alias match
    if name_match_type in ("exact", "alias"):
        return rng.uniform(95.0, 100.0)

    # Fuzzy / near-miss sanction
    if name_match_type in ("fuzzy", "near_miss", "fuzzy_near_miss"):
        return rng.uniform(60.0, 85.0)

    # PEP linkage
    pep_id = account.get("pep_id") or ""
    if pep_id and pep_id in pep_map:
        is_current = pep_map[pep_id].get("is_current", False)
        if is_current:
            return rng.uniform(70.0, 85.0)
        else:
            return rng.uniform(40.0, 60.0)
    elif account.get("is_pep"):
        # PEP flag set but no pep record found — treat as historical
        return rng.uniform(40.0, 60.0)

    # Related-entity risk
    flags = rel_flags.get(account_id, {})
    if flags.get("related_is_sanctioned"):
        return rng.uniform(40.0, 60.0)
    if flags.get("related_is_pep"):
        return rng.uniform(20.0, 40.0)

    # No connection: small noise
    return rng.uniform(0.0, 10.0)


def compute_behavioural_risk(account: dict, txn_stats: dict,
                              rng: random.Random) -> float:
    """Score based on transaction behaviour; falls back to activity_tier."""
    account_id = account.get("account_id", "")
    stats = txn_stats.get(account_id)

    if stats is None:
        # No transactions — use activity_tier proxy
        tier = (account.get("activity_tier") or "low").lower()
        tier_map = {"high": 40.0, "medium": 20.0, "low": 5.0}
        return tier_map.get(tier, 10.0)

    score = 0.0

    # Velocity (30-day count)
    velocity = stats.get("velocity_30d_count", 0)
    score += min(50.0, math.log(velocity + 1) * 10.0)

    # Large single transaction
    if stats.get("max_amount", 0) > 100_000:
        score += 20.0

    # Night-hour transactions (00:00–05:59)
    total_txns = stats.get("total_count", 1)
    night_txns = stats.get("night_count", 0)
    if total_txns > 0 and night_txns / total_txns > 0.20:
        score += 15.0

    # Multiple currencies
    if stats.get("currency_count", 1) > 1:
        score += 10.0

    # Round-number amounts (divisible by 1000) > 30%
    round_txns = stats.get("round_count", 0)
    if total_txns > 0 and round_txns / total_txns > 0.30:
        score += 10.0

    return min(100.0, score)


def compute_relationship_network_risk(account: dict, rel_flags: dict,
                                       sanctioned_countries_count: dict,
                                       rng: random.Random) -> float:
    """Score based on direct sanctioned/PEP relationships and recipient geography."""
    account_id = account.get("account_id", "")
    flags = rel_flags.get(account_id, {})

    score = 0.0

    if flags.get("related_is_sanctioned"):
        score = rng.uniform(70.0, 90.0)
    elif flags.get("related_is_pep"):
        score = rng.uniform(30.0, 50.0)

    # High unique recipients in sanctioned countries
    if sanctioned_countries_count.get(account_id, 0) >= 3:
        score += 20.0

    if score == 0.0:
        score = rng.uniform(0.0, 10.0)

    return min(100.0, score)


def compute_overall(geo: float, kyc: float, pep: float,
                    beh: float, rel: float) -> float:
    return min(100.0, (
        COMPONENT_WEIGHTS["geographic_risk"]           * geo +
        COMPONENT_WEIGHTS["identity_kyc_risk"]         * kyc +
        COMPONENT_WEIGHTS["pep_sanctions_risk"]        * pep +
        COMPONENT_WEIGHTS["behavioural_risk"]          * beh +
        COMPONENT_WEIGHTS["relationship_network_risk"] * rel
    ))


def risk_band(score: float) -> str:
    if score >= 80.0:
        return "CRITICAL"
    if score >= 60.0:
        return "HIGH"
    if score >= 40.0:
        return "MEDIUM"
    return "LOW"


# ── DB helpers ────────────────────────────────────────────────────────────────

def load_accounts(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM accounts")
    rows = [dict(r) for r in cur.fetchall()]
    conn.row_factory = None
    return rows


def load_pep_map(conn: sqlite3.Connection) -> dict:
    """Return {pep_id: {is_current, position}} from reference_data/peps.csv."""
    import csv
    from pathlib import Path
    peps_csv = Path(REF_DIR) / "peps.csv"
    if not peps_csv.exists():
        return {}
    result = {}
    with open(peps_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            result[row["pep_id"]] = {
                "is_current": row.get("is_current", "0") in ("1", "True", "true"),
                "position": row.get("position", ""),
            }
    return result


def load_rel_flags(conn: sqlite3.Connection) -> dict:
    """Return {account_id: {related_is_sanctioned, related_is_pep}} (OR-aggregated)."""
    try:
        cur = conn.execute(
            "SELECT account_id, MAX(related_is_sanctioned), MAX(related_is_pep) "
            "FROM account_relationships GROUP BY account_id"
        )
        return {row[0]: {"related_is_sanctioned": bool(row[1]),
                          "related_is_pep": bool(row[2])}
                for row in cur.fetchall()}
    except sqlite3.OperationalError:
        return {}


def load_txn_stats(conn: sqlite3.Connection) -> dict:
    """Aggregate transaction stats per sender account."""
    try:
        cur = conn.execute("""
            SELECT
                sender_account_id,
                COUNT(*)                                         AS total_count,
                MAX(velocity_30d_count)                          AS velocity_30d_count,
                MAX(amount)                                      AS max_amount,
                SUM(CASE WHEN hour_of_day BETWEEN 0 AND 5
                         THEN 1 ELSE 0 END)                     AS night_count,
                COUNT(DISTINCT currency)                         AS currency_count,
                SUM(CASE WHEN CAST(amount AS INTEGER) % 1000 = 0
                         THEN 1 ELSE 0 END)                     AS round_count
            FROM transactions
            GROUP BY sender_account_id
        """)
        result = {}
        for row in cur.fetchall():
            result[row[0]] = {
                "total_count":       row[1],
                "velocity_30d_count": row[2] or 0,
                "max_amount":        row[3] or 0.0,
                "night_count":       row[4] or 0,
                "currency_count":    row[5] or 1,
                "round_count":       row[6] or 0,
            }
        return result
    except sqlite3.OperationalError:
        return {}


def load_sanctioned_countries_count(conn: sqlite3.Connection) -> dict:
    """Count unique sanctioned-country recipients per sender (rough heuristic)."""
    sanctioned = {"RU", "IR", "KP", "SY", "BY", "CU", "VE", "SD", "LY", "MM"}
    try:
        cur = conn.execute(
            "SELECT sender_account_id, recipient_country FROM transactions"
        )
        counts: dict[str, set] = {}
        for sender, country in cur.fetchall():
            if country and country.upper() in sanctioned:
                counts.setdefault(sender, set()).add(country.upper())
        return {k: len(v) for k, v in counts.items()}
    except sqlite3.OperationalError:
        return {}


# ── Override simulation ───────────────────────────────────────────────────────

def apply_overrides(records: list[dict], rng: random.Random) -> None:
    """Mutate ~2 % of records to simulate analyst overrides."""
    sanctioned_low = [r for r in records
                      if r["risk_band"] == "LOW" and
                      (r.get("_name_match_type") in ("exact", "alias") or
                       r.get("_related_is_sanctioned"))]
    high_clean = [r for r in records
                  if r["risk_band"] == "HIGH" and
                  not r.get("_name_match_type") and
                  not r.get("_related_is_sanctioned")]

    # Override sanctioned-but-low → CRITICAL
    n_sanc = max(1, int(len(records) * 0.01))
    for rec in rng.sample(sanctioned_low, min(n_sanc, len(sanctioned_low))):
        rec["overall_risk_score"] = rng.uniform(80.0, 95.0)
        rec["risk_band"] = "CRITICAL"
        rec["override_applied"] = 1
        rec["override_reason"] = "Sanctions match confirmed"

    # Override high-risk clean → MEDIUM
    n_clean = max(1, int(len(records) * 0.01))
    for rec in rng.sample(high_clean, min(n_clean, len(high_clean))):
        rec["overall_risk_score"] = rng.uniform(40.0, 59.0)
        rec["risk_band"] = "MEDIUM"
        rec["override_applied"] = 1
        rec["override_reason"] = "KYC verified, legitimate"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 06_compute_risk_scores.py started ===")

    progress = load_progress()
    if progress.get("risk_scores_complete"):
        logger.info("risk_scores_complete=true — nothing to do.")
        return

    rng = random.Random(42)

    # Load reference data
    country_risk = load_country_risk(COUNTRY_RISK_CSV)
    logger.info(f"Loaded country risk scores for {len(country_risk)} countries.")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")

    logger.info("Loading accounts …")
    accounts = load_accounts(conn)
    logger.info(f"  {len(accounts)} accounts loaded.")

    logger.info("Loading auxiliary data …")
    pep_map                  = load_pep_map(conn)
    rel_flags                = load_rel_flags(conn)
    txn_stats                = load_txn_stats(conn)
    sanctioned_ctry_count    = load_sanctioned_countries_count(conn)
    logger.info(f"  PEP records: {len(pep_map)}, "
                f"accounts with relationships: {len(rel_flags)}, "
                f"accounts with transactions: {len(txn_stats)}")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    records = []
    for n, acct in enumerate(accounts, start=1):
        acct_id = acct["account_id"]

        geo  = compute_geographic_risk(acct, country_risk)
        kyc  = compute_identity_kyc_risk(acct)
        pep  = compute_pep_sanctions_risk(acct, pep_map, rel_flags, rng)
        beh  = compute_behavioural_risk(acct, txn_stats, rng)
        relr = compute_relationship_network_risk(acct, rel_flags,
                                                  sanctioned_ctry_count, rng)
        overall = compute_overall(geo, kyc, pep, beh, relr)
        band    = risk_band(overall)

        rec = {
            "risk_score_id":             f"RSK-{n:08d}",
            "account_id":                acct_id,
            "computed_at":               now_str,
            "geographic_risk":           round(geo, 4),
            "identity_kyc_risk":         round(kyc, 4),
            "pep_sanctions_risk":        round(pep, 4),
            "behavioural_risk":          round(beh, 4),
            "relationship_network_risk": round(relr, 4),
            "overall_risk_score":        round(overall, 4),
            "risk_band":                 band,
            "override_applied":          0,
            "override_reason":           None,
            # Internal fields for override logic (stripped before insert)
            "_name_match_type":          acct.get("name_match_type"),
            "_related_is_sanctioned":    rel_flags.get(acct_id, {}).get("related_is_sanctioned", False),
        }
        records.append(rec)

    logger.info(f"Computed {len(records)} risk scores. Applying overrides …")
    apply_overrides(records, rng)

    # Strip internal fields
    insert_keys = [k for k in records[0] if not k.startswith("_")]
    rows = [[r[k] for k in insert_keys] for r in records]

    placeholders = ", ".join(["?"] * len(insert_keys))
    sql = (f"INSERT OR REPLACE INTO risk_scores "
           f"({', '.join(insert_keys)}) VALUES ({placeholders})")

    logger.info("Inserting into risk_scores …")
    CHUNK = 1000
    for i in range(0, len(rows), CHUNK):
        conn.executemany(sql, rows[i:i + CHUNK])
        conn.commit()
        logger.info(f"  Inserted rows {i + 1}–{min(i + CHUNK, len(rows))}")

    overridden = sum(1 for r in records if r["override_applied"])
    logger.info(f"Override applied: {overridden} accounts.")

    band_counts = {}
    for r in records:
        band_counts[r["risk_band"]] = band_counts.get(r["risk_band"], 0) + 1
    logger.info(f"Band distribution: {band_counts}")

    conn.close()
    update_progress("risk_scores_complete", True)
    logger.info("progress.json updated: risk_scores_complete=true")
    logger.info("=== 06_compute_risk_scores.py finished ===")


if __name__ == "__main__":
    main()
