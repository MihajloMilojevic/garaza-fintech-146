"""
05_generate_screening_results.py
=================================
Generates screening results for every account (account-level) and for
high-risk transactions (transaction-level), inserting rows into the
`screening_results` table of sanctions_screening.db.

Progress tracking:
  - Sets screening_results_complete=true in progress.json when done.

Idempotent: checks progress.json before running.
"""

import csv
import json
import logging
import math
import os
import random
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_DIR = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DB_PATH = os.path.join(PROJECT_DIR, "sanctions_screening.db")
PROGRESS_PATH = os.path.join(PROJECT_DIR, "progress.json")
LOG_PATH = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")
REF_DIR = os.path.join(PROJECT_DIR, "reference_data")

# ── Constants ─────────────────────────────────────────────────────────────────
INSERT_BATCH = 2000
HIGH_RISK_COUNTRY_THRESHOLD = 65.0
TXN_SCREENING_SAMPLE_RATE = 0.10  # ~10% of transactions

MATCH_FIELDS = ["name", "alias", "identifier", "address"]
FUZZY_MATCH_TYPES = ["exact", "alias", "transliteration", "nickname", "abbreviation", "none"]

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("05_generate_screening_results")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
    )
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


def save_progress(progress: dict) -> None:
    progress["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    tmp = PROGRESS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)
    os.replace(tmp, PROGRESS_PATH)


def update_progress_key(key: str, value) -> None:
    p = load_progress()
    p[key] = value
    save_progress(p)


# ── Reference data loaders ────────────────────────────────────────────────────

def load_matching_pairs_stats(logger: logging.Logger) -> dict:
    """Load matching_pairs_stats.json — positive/negative JW distributions."""
    path = os.path.join(REF_DIR, "matching_pairs_stats.json")
    defaults = {
        "positive_mean_jw": 0.92,
        "positive_std_jw":  0.06,
        "positive_p5":      0.80,
        "positive_p95":     0.99,
        "negative_mean_jw": 0.62,
        "negative_std_jw":  0.10,
        "negative_p5":      0.45,
        "negative_p95":     0.78,
    }
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults for any missing keys
        for k, v in defaults.items():
            data.setdefault(k, v)
        logger.info(f"Loaded matching pairs stats from {path}")
        return data
    except Exception as exc:
        logger.warning(f"Could not load matching_pairs_stats.json ({exc}); using defaults.")
        return defaults


def load_country_risk(logger: logging.Logger) -> dict:
    """Return {country_code: composite_risk_score}."""
    path = os.path.join(REF_DIR, "country_risk.csv")
    risk_map: dict = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code  = (row.get("country_code") or "").strip().upper()
                score_str = (row.get("composite_risk_score") or "0").strip()
                try:
                    score = float(score_str)
                except ValueError:
                    score = 0.0
                if code:
                    risk_map[code] = score
        logger.info(f"Loaded country risk for {len(risk_map)} countries from {path}.")
    except Exception as exc:
        logger.warning(f"Could not load country_risk.csv ({exc}); country risk will default to 0.")
    return risk_map


def load_sanctioned_entities(logger: logging.Logger) -> dict:
    """Return {entity_id: row_dict} from sanctioned_entities.csv."""
    path = os.path.join(REF_DIR, "sanctioned_entities.csv")
    entities: dict = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                eid = (row.get("entity_id") or "").strip()
                if eid:
                    entities[eid] = dict(row)
        logger.info(f"Loaded {len(entities):,} sanctioned entities from {path}.")
    except Exception as exc:
        logger.warning(f"Could not load sanctioned_entities.csv ({exc}).")
    return entities


# ── DB helpers ────────────────────────────────────────────────────────────────

def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-65536;")
    conn.row_factory = sqlite3.Row
    return conn


def fetch_accounts(conn: sqlite3.Connection) -> list:
    cur = conn.execute(
        "SELECT account_id, full_name, country_residence, activity_tier, "
        "       is_pep, sanctioned_entity_id, name_match_type, account_status, "
        "       initial_risk_band "
        "FROM accounts"
    )
    return [dict(r) for r in cur.fetchall()]


def fetch_transactions_for_screening(conn: sqlite3.Connection) -> list:
    """
    Return all transactions sorted by timestamp.
    We screen ~10% of them: those where sender has sanctions flag OR
    recipient_country is high-risk.  The caller does the filtering after
    loading account risk info.
    """
    cur = conn.execute(
        "SELECT transaction_id, sender_account_id, recipient_account_id, "
        "       recipient_country, timestamp, amount "
        "FROM transactions "
        "ORDER BY timestamp"
    )
    return [dict(r) for r in cur.fetchall()]


# ── Score sampling helpers ────────────────────────────────────────────────────

def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def sample_score_near(mean: float, std: float, lo: float, hi: float) -> float:
    """Sample from Normal(mean, std) clamped to [lo, hi]."""
    val = random.gauss(mean, std)
    return round(clamp(val, lo, hi), 4)


def jw_to_score(jw: float) -> float:
    """Scale Jaro-Winkler similarity (0-1) to a 0-100 match score."""
    return round(jw * 100.0, 2)


def sample_positive_score(stats: dict) -> float:
    """Sample a match score representing a TRUE positive (sanctioned match)."""
    mean = stats.get("positive_mean_jw", 0.92)
    std  = stats.get("positive_std_jw", 0.06)
    p5   = stats.get("positive_p5", 0.80)
    p95  = stats.get("positive_p95", 0.99)
    val  = clamp(random.gauss(mean, std), p5, p95)
    return jw_to_score(val)


def sample_negative_confusable_score(stats: dict) -> float:
    """Sample a match score for a clean account that looks superficially similar (false positive)."""
    mean = stats.get("negative_mean_jw", 0.62)
    std  = stats.get("negative_std_jw", 0.10)
    # Only use the 50-75 sub-range (confusable but not high-confidence)
    val  = clamp(random.gauss(mean, std), 0.50, 0.75)
    return jw_to_score(val)


def sample_noise_score() -> float:
    """Low match score for truly unmatched accounts."""
    return round(random.uniform(0.0, 30.0), 2)


def sample_pep_score(is_pep: bool, has_pep_relation: bool) -> float:
    if is_pep:
        return round(random.uniform(90.0, 100.0), 2)
    if has_pep_relation:
        return round(random.uniform(40.0, 70.0), 2)
    return round(random.uniform(0.0, 10.0), 2)


def get_country_risk(country_code: str, risk_map: dict) -> float:
    if not country_code:
        return 0.0
    return risk_map.get(country_code.strip().upper(), 0.0)


# ── Hops-to-sanctioned helpers ────────────────────────────────────────────────

def determine_hops(
    account: dict,
    sanctioned_entity_id: str,
    relationship_hop_map: dict,
) -> int | None:
    """
    Return hops_to_sanctioned:
      - 0 if directly sanctioned
      - 1-2 if in relationship_hop_map
      - 3 if distant
      - None if truly clean
    """
    acc_id = account["account_id"]
    if sanctioned_entity_id:
        return 0
    hops = relationship_hop_map.get(acc_id)
    if hops is not None:
        return hops
    # For PEP accounts, slight chance of 2-3 hops
    if account.get("is_pep"):
        return random.choice([1, 2, 2, 3])
    return None


# ── relationship hop map builder ──────────────────────────────────────────────

def build_relationship_hop_map(conn: sqlite3.Connection, logger: logging.Logger) -> dict:
    """
    Build {account_id: min_hops} from account_relationships where
    related_is_sanctioned=1.
    """
    hop_map: dict = {}
    try:
        cur = conn.execute(
            "SELECT account_id, related_is_sanctioned, related_is_pep "
            "FROM account_relationships"
        )
        for row in cur.fetchall():
            acc_id = row[0]
            if row[1]:  # related_is_sanctioned
                existing = hop_map.get(acc_id)
                hop_map[acc_id] = min(existing, 1) if existing is not None else 1
        logger.info(f"Built relationship hop map: {len(hop_map):,} accounts with sanctions links.")
    except Exception as exc:
        logger.warning(f"Could not build relationship hop map ({exc}).")
    return hop_map


# ── Verdict determination ─────────────────────────────────────────────────────

def determine_verdict(
    name_match_type: str,
    match_score: float,
    is_pep: bool,
    country_risk_score: float,
    hops_to_sanctioned: int | None,
) -> str:
    """
    Ground-truth verdict:
      BLOCK  — directly sanctioned (exact/alias match)
      REVIEW — fuzzy near-miss sanctioned, PEP, high country risk, close hops
      CLEAR  — clean
    """
    if name_match_type in ("exact", "alias"):
        return "BLOCK"
    if name_match_type == "fuzzy_near_miss" and match_score >= 75.0:
        return "REVIEW"
    if is_pep:
        return "REVIEW"
    if country_risk_score > HIGH_RISK_COUNTRY_THRESHOLD:
        return "REVIEW"
    if hops_to_sanctioned is not None and hops_to_sanctioned <= 2:
        return "REVIEW"
    return "CLEAR"


# ── match_field / fuzzy_match_type selectors ──────────────────────────────────

def choose_match_field(name_match_type: str) -> str:
    if name_match_type in ("exact", "fuzzy_near_miss"):
        return "name"
    if name_match_type == "alias":
        return "alias"
    return random.choice(MATCH_FIELDS)


def choose_fuzzy_match_type(name_match_type: str) -> str:
    if name_match_type == "exact":
        return "exact"
    if name_match_type == "alias":
        return "alias"
    if name_match_type == "fuzzy_near_miss":
        return random.choice(["transliteration", "nickname", "abbreviation"])
    return "none"


# ── Screening result builders ─────────────────────────────────────────────────

def build_account_screening_result(
    scr_n: int,
    account: dict,
    stats: dict,
    country_risk_map: dict,
    relationship_hop_map: dict,
    entities: dict,
) -> dict:
    """Build one screening_results row for an account-level screen."""
    acc_id          = account["account_id"]
    name_match_type = account.get("name_match_type") or "none"
    sanctioned_id   = account.get("sanctioned_entity_id")
    is_pep          = bool(account.get("is_pep"))
    country_code    = (account.get("country_residence") or "").strip().upper()

    # matched_entity_id
    matched_entity_id = None
    if sanctioned_id:
        matched_entity_id = sanctioned_id
    elif name_match_type == "fuzzy_near_miss" and not sanctioned_id:
        # Find a plausible entity to "almost match"
        if entities:
            matched_entity_id = random.choice(list(entities.keys()))

    # match_score
    if name_match_type == "exact":
        match_score = sample_score_near(97.5, 1.5, 95.0, 100.0)
    elif name_match_type == "alias":
        match_score = sample_score_near(90.0, 3.0, 85.0, 95.0)
    elif name_match_type == "fuzzy_near_miss":
        if sanctioned_id:
            # True positive
            match_score = sample_positive_score(stats)
        else:
            # False positive / clean with near-miss name
            match_score = sample_negative_confusable_score(stats)
    else:
        match_score = sample_noise_score()
        matched_entity_id = None  # don't assign an entity for noise

    # match_field / fuzzy_match_type
    match_field      = choose_match_field(name_match_type)
    fuzzy_match_type = choose_fuzzy_match_type(name_match_type)

    # hops_to_sanctioned
    hops = determine_hops(account, sanctioned_id, relationship_hop_map)

    # shares_address_with_sanctioned: ~5% of high-risk
    is_high_risk_acc = bool(sanctioned_id or is_pep or
                            account.get("activity_tier") == "high" or
                            account.get("initial_risk_band") in ("high", "very_high"))
    shares_address = 1 if (is_high_risk_acc and random.random() < 0.05) else 0

    # pep_exposure_score
    has_pep_relation = False  # simplified; relationship map doesn't track PEP here
    pep_exposure = sample_pep_score(is_pep, has_pep_relation)

    # country_risk_score
    country_risk = get_country_risk(country_code, country_risk_map)

    # verdict
    verdict = determine_verdict(
        name_match_type, match_score, is_pep, country_risk, hops
    )

    return {
        "screening_id":                 f"SCR-{scr_n:08d}",
        "transaction_id":               None,
        "account_id":                   acc_id,
        "screening_context":            "account",
        "matched_entity_id":            matched_entity_id,
        "match_score":                  match_score,
        "match_field":                  match_field,
        "fuzzy_match_type":             fuzzy_match_type,
        "hops_to_sanctioned":           hops,
        "shares_address_with_sanctioned": shares_address,
        "pep_exposure_score":           pep_exposure,
        "country_risk_score":           round(country_risk, 4),
        "verdict_ground_truth":         verdict,
    }


def build_transaction_screening_result(
    scr_n: int,
    txn: dict,
    sender_account: dict,
    stats: dict,
    country_risk_map: dict,
    relationship_hop_map: dict,
) -> dict:
    """Build one screening_results row for a transaction-level screen."""
    acc_id          = sender_account["account_id"]
    name_match_type = sender_account.get("name_match_type") or "none"
    sanctioned_id   = sender_account.get("sanctioned_entity_id")
    is_pep          = bool(sender_account.get("is_pep"))

    sender_country   = (sender_account.get("country_residence") or "").strip().upper()
    recipient_country = (txn.get("recipient_country") or "").strip().upper()

    sender_risk   = get_country_risk(sender_country, country_risk_map)
    recipient_risk = get_country_risk(recipient_country, country_risk_map)
    country_risk  = max(sender_risk, recipient_risk)

    # matched_entity_id
    matched_entity_id = sanctioned_id  # may be None

    # match_score (transaction-level: slightly noisier)
    if name_match_type == "exact":
        match_score = sample_score_near(96.0, 2.0, 90.0, 100.0)
    elif name_match_type == "alias":
        match_score = sample_score_near(88.0, 4.0, 80.0, 95.0)
    elif name_match_type == "fuzzy_near_miss" and sanctioned_id:
        match_score = sample_positive_score(stats)
    elif country_risk > HIGH_RISK_COUNTRY_THRESHOLD:
        # Country-risk triggered — score reflects country exposure not name match
        match_score = sample_score_near(55.0, 12.0, 30.0, 75.0)
        matched_entity_id = None
    else:
        match_score = sample_noise_score()
        matched_entity_id = None

    match_field      = choose_match_field(name_match_type)
    fuzzy_match_type = choose_fuzzy_match_type(name_match_type)

    hops = determine_hops(sender_account, sanctioned_id, relationship_hop_map)

    is_high_risk_acc = bool(sanctioned_id or is_pep)
    shares_address = 1 if (is_high_risk_acc and random.random() < 0.05) else 0

    pep_exposure = sample_pep_score(is_pep, False)

    verdict = determine_verdict(
        name_match_type, match_score, is_pep, country_risk, hops
    )

    return {
        "screening_id":                 f"SCR-{scr_n:08d}",
        "transaction_id":               txn["transaction_id"],
        "account_id":                   acc_id,
        "screening_context":            "transaction",
        "matched_entity_id":            matched_entity_id,
        "match_score":                  match_score,
        "match_field":                  match_field,
        "fuzzy_match_type":             fuzzy_match_type,
        "hops_to_sanctioned":           hops,
        "shares_address_with_sanctioned": shares_address,
        "pep_exposure_score":           pep_exposure,
        "country_risk_score":           round(country_risk, 4),
        "verdict_ground_truth":         verdict,
    }


# ── DB insert helper ──────────────────────────────────────────────────────────

INSERT_SQL = """
    INSERT OR IGNORE INTO screening_results (
        screening_id, transaction_id, account_id, screening_context,
        matched_entity_id, match_score, match_field, fuzzy_match_type,
        hops_to_sanctioned, shares_address_with_sanctioned,
        pep_exposure_score, country_risk_score, verdict_ground_truth
    ) VALUES (
        :screening_id, :transaction_id, :account_id, :screening_context,
        :matched_entity_id, :match_score, :match_field, :fuzzy_match_type,
        :hops_to_sanctioned, :shares_address_with_sanctioned,
        :pep_exposure_score, :country_risk_score, :verdict_ground_truth
    )
"""


def flush_rows(conn: sqlite3.Connection, rows: list, logger: logging.Logger) -> None:
    if rows:
        conn.executemany(INSERT_SQL, rows)
        conn.commit()


# ── Ground truth distribution reporter ───────────────────────────────────────

def report_distribution(
    counts: dict,
    total: int,
    logger: logging.Logger,
) -> None:
    block  = counts.get("BLOCK", 0)
    review = counts.get("REVIEW", 0)
    clear  = counts.get("CLEAR", 0)

    block_rate  = block  / total * 100 if total else 0
    review_rate = review / total * 100 if total else 0
    clear_rate  = clear  / total * 100 if total else 0
    positive_rate = block / total if total else 0

    msg_lines = [
        "=== Ground truth distribution ===",
        f"  Total screening results : {total:,}",
        f"  BLOCK                   : {block:,}  ({block_rate:.3f}%)",
        f"  REVIEW                  : {review:,}  ({review_rate:.2f}%)",
        f"  CLEAR                   : {clear:,}  ({clear_rate:.2f}%)",
        f"  Positive rate (BLOCK)   : {positive_rate:.4%}",
    ]

    if not (0.002 <= positive_rate <= 0.005):
        msg_lines.append(
            f"  WARNING: Positive rate {positive_rate:.4%} is outside target range 0.20%-0.50%"
        )
    else:
        msg_lines.append("  OK: Positive rate within target range (0.20%-0.50%)")

    msg = "\n".join(msg_lines)
    logger.info(msg)
    print(msg)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 05_generate_screening_results.py started ===")

    progress = load_progress()
    if progress.get("screening_results_complete"):
        logger.info("screening_results_complete=true — nothing to do.")
        print("Screening results already generated. Set screening_results_complete=false to re-run.")
        return

    # ── Load reference data ────────────────────────────────────────────────────
    stats           = load_matching_pairs_stats(logger)
    country_risk_map = load_country_risk(logger)
    entities        = load_sanctioned_entities(logger)

    # ── Load DB data ───────────────────────────────────────────────────────────
    conn = open_db()

    accounts = fetch_accounts(conn)
    if not accounts:
        logger.error("No accounts found in DB. Run account generation scripts first.")
        conn.close()
        sys.exit(1)
    logger.info(f"Loaded {len(accounts):,} accounts.")

    account_map: dict = {acc["account_id"]: acc for acc in accounts}

    relationship_hop_map = build_relationship_hop_map(conn, logger)

    transactions = fetch_transactions_for_screening(conn)
    logger.info(f"Loaded {len(transactions):,} transactions.")

    # ── Account-level screening ────────────────────────────────────────────────
    logger.info("Generating account-level screening results ...")
    scr_counter = 0
    verdict_counts: dict = defaultdict(int)
    batch_rows: list = []

    for account in accounts:
        scr_counter += 1
        result = build_account_screening_result(
            scr_n=scr_counter,
            account=account,
            stats=stats,
            country_risk_map=country_risk_map,
            relationship_hop_map=relationship_hop_map,
            entities=entities,
        )
        verdict_counts[result["verdict_ground_truth"]] += 1
        batch_rows.append(result)

        if len(batch_rows) >= INSERT_BATCH:
            flush_rows(conn, batch_rows, logger)
            batch_rows.clear()
            logger.debug(f"  Flushed account screening at SCR-{scr_counter:08d}")

    flush_rows(conn, batch_rows, logger)
    batch_rows.clear()
    logger.info(f"Account screening complete: {scr_counter:,} results inserted.")

    # ── Transaction-level screening ────────────────────────────────────────────
    logger.info("Selecting high-risk transactions for screening ...")

    # Build set of sender account IDs that are sanctioned
    sanctioned_sender_ids: set = {
        acc["account_id"]
        for acc in accounts
        if acc.get("sanctioned_entity_id")
    }

    # Filter: sender sanctioned OR recipient country high-risk
    candidate_txns = [
        txn for txn in transactions
        if txn["sender_account_id"] in sanctioned_sender_ids
        or get_country_risk(
            (txn.get("recipient_country") or "").strip().upper(), country_risk_map
        ) > HIGH_RISK_COUNTRY_THRESHOLD
    ]

    # If still too many, sample down to ~10% of all transactions
    target_txn_count = int(len(transactions) * TXN_SCREENING_SAMPLE_RATE)
    if len(candidate_txns) > target_txn_count:
        candidate_txns = random.sample(candidate_txns, target_txn_count)
    elif len(candidate_txns) < target_txn_count // 2:
        # Supplement with random transactions if not enough candidates
        remaining = [t for t in transactions if t not in candidate_txns]
        supplement_n = min(target_txn_count - len(candidate_txns), len(remaining))
        if supplement_n > 0:
            candidate_txns.extend(random.sample(remaining, supplement_n))

    logger.info(f"Selected {len(candidate_txns):,} transactions for screening.")

    for txn in candidate_txns:
        sender_account = account_map.get(txn["sender_account_id"])
        if not sender_account:
            continue
        scr_counter += 1
        result = build_transaction_screening_result(
            scr_n=scr_counter,
            txn=txn,
            sender_account=sender_account,
            stats=stats,
            country_risk_map=country_risk_map,
            relationship_hop_map=relationship_hop_map,
        )
        verdict_counts[result["verdict_ground_truth"]] += 1
        batch_rows.append(result)

        if len(batch_rows) >= INSERT_BATCH:
            flush_rows(conn, batch_rows, logger)
            batch_rows.clear()
            logger.debug(f"  Flushed transaction screening at SCR-{scr_counter:08d}")

    flush_rows(conn, batch_rows, logger)
    batch_rows.clear()
    logger.info(f"Transaction screening complete. Total screening results: {scr_counter:,}.")

    # ── Report ────────────────────────────────────────────────────────────────
    total_scr = sum(verdict_counts.values())
    report_distribution(dict(verdict_counts), total_scr, logger)

    # ── Finalise ──────────────────────────────────────────────────────────────
    conn.close()
    update_progress_key("screening_results_complete", True)
    logger.info("progress.json updated: screening_results_complete=true")
    logger.info("=== 05_generate_screening_results.py finished ===")
    print("Done. Screening results generated.")


if __name__ == "__main__":
    main()
