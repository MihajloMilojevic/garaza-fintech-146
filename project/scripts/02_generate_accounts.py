"""
02_generate_accounts.py
=======================
Generate 20,000 synthetic accounts in 10 batches of 2,000 and insert them
into the `accounts` table of the SQLite database.

Idempotent: batches already listed in progress.json `accounts_batches_done`
are skipped.  Resume by re-running the script after a failure.

Usage:
    python 02_generate_accounts.py
"""

import csv
import json
import logging
import os
import random
import sqlite3
import string
import sys
import unicodedata
from datetime import datetime, date, timedelta, timezone
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR    = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DB_PATH        = os.path.join(PROJECT_DIR, "sanctions_screening.db")
PROGRESS_PATH  = os.path.join(PROJECT_DIR, "progress.json")
LOG_PATH       = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")
REF_DIR        = os.path.join(PROJECT_DIR, "reference_data")
SANCTIONED_CSV = os.path.join(REF_DIR, "sanctioned_entities.csv")
PEPS_CSV       = os.path.join(REF_DIR, "peps.csv")

# ── Constants ─────────────────────────────────────────────────────────────────
TOTAL_ACCOUNTS  = 20_000
BATCH_SIZE      = 2_000
NUM_BATCHES     = TOTAL_ACCOUNTS // BATCH_SIZE   # 10

SANCTIONED_PER_BATCH_MIN = 6
SANCTIONED_PER_BATCH_MAX = 10
PEP_PER_BATCH            = 10  # ~0.5 %

# ── Country weights ──────────────────────────────────────────────────────────
_HIGH_WEIGHT_COUNTRIES = [
    "US", "GB", "DE", "FR", "CH", "NL", "AE", "SG", "HK", "CA", "AU",
    "CN", "IN", "BR",
]
_MEDIUM_WEIGHT_COUNTRIES = [
    "IT", "ES", "SE", "NO", "DK", "FI", "PL", "CZ", "AT", "BE",
    "PT", "GR", "IL", "TR", "ZA", "NG", "KE", "EG", "MX", "AR",
    "CL", "CO", "PE", "VE", "PH", "ID", "MY", "TH", "VN", "PK",
    "BD", "LK", "UA", "RO", "HU", "BG", "HR", "RS", "SK", "SI",
    "LT", "LV", "EE", "MT", "CY", "LU", "IE", "NZ", "JP", "KR",
]
_SANCTIONED_COUNTRIES = ["RU", "IR", "KP", "SY", "BY"]
_OFFSHORE_COUNTRIES   = ["KY", "VG", "BZ", "PA", "LI"]

def _build_country_pool():
    pool, weights = [], []
    for c in _HIGH_WEIGHT_COUNTRIES:
        pool.append(c); weights.append(8)
    for c in _MEDIUM_WEIGHT_COUNTRIES:
        pool.append(c); weights.append(2)
    # Sanctioned countries: ~3 % overall → give them ~0.4 weight each (5×0.4 = 2)
    for c in _SANCTIONED_COUNTRIES:
        pool.append(c); weights.append(0.4)
    return pool, weights

COUNTRY_POOL, COUNTRY_WEIGHTS = _build_country_pool()

# ── Faker locales pool ────────────────────────────────────────────────────────
FAKER_LOCALES = [
    "en_US", "en_GB", "de_DE", "fr_FR", "ru_RU",
    "zh_CN", "ar_EG", "es_ES", "pt_BR", "tr_TR",
    "uk_UA", "fa_IR", "ko_KR", "ja_JP",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("02_generate_accounts")
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


def read_csv(path: str) -> list[dict]:
    """Read a CSV file and return a list of row dicts."""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def random_date(start: date, end: date, rng: random.Random) -> date:
    delta = (end - start).days
    return start + timedelta(days=rng.randint(0, delta))


def random_datetime(start: datetime, end: datetime, rng: random.Random) -> datetime:
    delta_secs = int((end - start).total_seconds())
    return start + timedelta(seconds=rng.randint(0, delta_secs))


# ── Name perturbation ─────────────────────────────────────────────────────────

def _transliterate_char(ch: str) -> str:
    """Replace a Latin char with a visually-similar Cyrillic/other char, or vice-versa."""
    _MAP = {
        "a": "а", "e": "е", "o": "о", "p": "р", "c": "с",
        "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C",
    }
    return _MAP.get(ch, ch)


def perturb_name(name: str, entity_type: str, match_type: str,
                 aliases_str: str, rng: random.Random) -> str:
    """
    Return a perturbed version of *name* according to *match_type*.

    match_type:
        'exact'          → return name unchanged
        'alias'          → pick a random alias from aliases_str, else perturb
        'fuzzy_near_miss'→ apply 1-2 random perturbations
    """
    if match_type == "exact":
        return name

    if match_type == "alias":
        aliases = [a.strip() for a in (aliases_str or "").split(";") if a.strip()]
        if aliases:
            return rng.choice(aliases)
        # Fall through to fuzzy if no aliases

    # ── fuzzy_near_miss perturbations ────────────────────────────────────────
    parts = name.split()
    result = name

    perturbations = [
        "swap_name_order",
        "transliterate_char",
        "insert_char",
        "delete_char",
        "double_letter",
        "swap_adjacent",
        "add_middle_initial",
        "abbreviate_first",
    ]

    chosen = rng.sample(perturbations, k=rng.randint(1, 2))

    for p in chosen:
        words = result.split()
        if not words:
            break

        if p == "swap_name_order" and len(words) >= 2:
            words = words[-1:] + words[:-1]
            result = " ".join(words)

        elif p == "transliterate_char":
            idx = rng.randint(0, len(result) - 1)
            ch = result[idx]
            new_ch = _transliterate_char(ch)
            result = result[:idx] + new_ch + result[idx + 1:]

        elif p == "insert_char":
            idx = rng.randint(1, len(result))
            ch = rng.choice(string.ascii_lowercase)
            result = result[:idx] + ch + result[idx:]

        elif p == "delete_char" and len(result) > 2:
            idx = rng.randint(0, len(result) - 1)
            result = result[:idx] + result[idx + 1:]

        elif p == "double_letter":
            alpha_idxs = [i for i, c in enumerate(result) if c.isalpha()]
            if alpha_idxs:
                idx = rng.choice(alpha_idxs)
                result = result[:idx] + result[idx] + result[idx:]

        elif p == "swap_adjacent" and len(result) >= 2:
            idx = rng.randint(0, len(result) - 2)
            lst = list(result)
            lst[idx], lst[idx + 1] = lst[idx + 1], lst[idx]
            result = "".join(lst)

        elif p == "add_middle_initial" and len(words) >= 2:
            initial = rng.choice(string.ascii_uppercase) + "."
            insert_pos = rng.randint(1, len(words) - 1)
            words.insert(insert_pos, initial)
            result = " ".join(words)

        elif p == "abbreviate_first":
            words = result.split()
            if words and len(words[0]) > 1:
                words[0] = words[0][0] + "."
                result = " ".join(words)

    return result


# ── Account field generators ──────────────────────────────────────────────────

def _kyc_fields(is_risk: bool, rng: random.Random) -> tuple[float, str]:
    """Return (kyc_completeness, kyc_status)."""
    if is_risk:
        completeness = rng.uniform(0.1, 0.9)
        # Skew toward lower values as a red flag
        if rng.random() < 0.4:
            completeness = rng.uniform(0.1, 0.5)
    else:
        if rng.random() < 0.10:   # ~10 % incomplete
            completeness = rng.uniform(0.3, 0.7)
        else:
            completeness = rng.uniform(0.7, 1.0)

    if completeness > 0.8:
        status = "complete" if rng.random() < 0.9 else "partial"
    elif completeness >= 0.5:
        status = "partial"
    else:
        status = "pending" if rng.random() < 0.6 else "expired"

    return round(completeness, 4), status


def _activity_tier(is_risk: bool, rng: random.Random) -> str:
    if is_risk:
        return rng.choices(["low", "medium", "high"], weights=[20, 50, 30])[0]
    return rng.choices(["low", "medium", "high"], weights=[60, 30, 10])[0]


def _risk_band(is_sanctioned: bool, is_pep: bool,
               country: Optional[str], rng: random.Random) -> str:
    if is_sanctioned:
        return "CRITICAL"
    high_risk_country = country in _SANCTIONED_COUNTRIES
    if is_pep or high_risk_country:
        return rng.choices(["HIGH", "MEDIUM"], weights=[60, 40])[0]
    return rng.choices(["LOW", "MEDIUM", "HIGH"], weights=[65, 30, 5])[0]


def _account_status(rng: random.Random) -> str:
    return rng.choices(["active", "suspended", "closed"], weights=[85, 8, 7])[0]


# ── Faker pool ────────────────────────────────────────────────────────────────

def build_faker_pool() -> list:
    """Build a list of Faker instances, one per locale."""
    try:
        from faker import Faker
    except ImportError:
        raise RuntimeError("faker package not installed.  Run: pip install faker")
    return [Faker(loc) for loc in FAKER_LOCALES]


# ── Main account builder ──────────────────────────────────────────────────────

def build_clean_account(account_id: str,
                         faker_pool: list,
                         rng: random.Random) -> dict:
    acct_type = rng.choices(["individual", "business"], weights=[70, 30])[0]
    fk = rng.choice(faker_pool)

    full_name = fk.name() if acct_type == "individual" else fk.company()

    country = rng.choices(COUNTRY_POOL, weights=COUNTRY_WEIGHTS)[0]
    nationality = country if rng.random() < 0.80 else rng.choices(COUNTRY_POOL, weights=COUNTRY_WEIGHTS)[0]

    country_incorp = None
    if acct_type == "business":
        if rng.random() < 0.15:  # offshore
            country_incorp = rng.choice(_OFFSHORE_COUNTRIES)
        else:
            country_incorp = country

    dob = None
    if acct_type == "individual":
        dob = random_date(date(1940, 1, 1), date(2000, 12, 31), rng).isoformat()

    created_at = random_datetime(
        datetime(2015, 1, 1), datetime(2026, 1, 1), rng
    ).strftime("%Y-%m-%d %H:%M:%S")

    has_complex = int(rng.random() < (0.15 if acct_type == "business" else 0.02))
    shell_flag  = int(has_complex and rng.random() < (5/15))

    kyc_comp, kyc_stat = _kyc_fields(is_risk=False, rng=rng)

    # 2 % coincidental fuzzy near-miss for clean accounts
    name_match = rng.choices(["none", "fuzzy_near_miss"], weights=[98, 2])[0]

    return {
        "account_id":            account_id,
        "account_type":          acct_type,
        "full_name":             full_name,
        "country_residence":     country,
        "country_incorporation": country_incorp,
        "date_of_birth":         dob,
        "nationality":           nationality,
        "created_at":            created_at,
        "kyc_completeness":      kyc_comp,
        "kyc_status":            kyc_stat,
        "is_pep":                0,
        "pep_id":                None,
        "has_complex_ownership": has_complex,
        "shell_company_flag":    shell_flag,
        "sanctioned_entity_id":  None,
        "name_match_type":       name_match,
        "account_status":        _account_status(rng),
        "activity_tier":         _activity_tier(is_risk=False, rng=rng),
        "initial_risk_band":     _risk_band(False, False, country, rng),
    }


def build_sanctioned_account(account_id: str,
                              entity: dict,
                              faker_pool: list,
                              rng: random.Random) -> dict:
    entity_type  = entity.get("entity_type", "individual").lower()
    acct_type    = "business" if entity_type in ("organization", "company", "legalentity") else "individual"

    match_type = rng.choices(
        ["exact", "alias", "fuzzy_near_miss"], weights=[40, 20, 40]
    )[0]
    full_name = perturb_name(
        entity.get("name", "Unknown"),
        entity_type,
        match_type,
        entity.get("aliases", ""),
        rng,
    )

    country = entity.get("country") or rng.choices(COUNTRY_POOL, weights=COUNTRY_WEIGHTS)[0]
    nationality = country if rng.random() < 0.80 else rng.choices(COUNTRY_POOL, weights=COUNTRY_WEIGHTS)[0]

    country_incorp = None
    if acct_type == "business":
        country_incorp = country if rng.random() < 0.70 else rng.choice(_OFFSHORE_COUNTRIES)

    dob = entity.get("dob") or None
    if acct_type == "individual" and not dob:
        dob = random_date(date(1940, 1, 1), date(2000, 12, 31), rng).isoformat()

    created_at = random_datetime(
        datetime(2015, 1, 1), datetime(2026, 1, 1), rng
    ).strftime("%Y-%m-%d %H:%M:%S")

    has_complex = int(rng.random() < (0.30 if acct_type == "business" else 0.05))
    shell_flag  = int(has_complex and rng.random() < 0.5)

    kyc_comp, kyc_stat = _kyc_fields(is_risk=True, rng=rng)

    return {
        "account_id":            account_id,
        "account_type":          acct_type,
        "full_name":             full_name,
        "country_residence":     country,
        "country_incorporation": country_incorp,
        "date_of_birth":         dob,
        "nationality":           nationality,
        "created_at":            created_at,
        "kyc_completeness":      kyc_comp,
        "kyc_status":            kyc_stat,
        "is_pep":                0,
        "pep_id":                None,
        "has_complex_ownership": has_complex,
        "shell_company_flag":    shell_flag,
        "sanctioned_entity_id":  entity.get("entity_id"),
        "name_match_type":       match_type,
        "account_status":        _account_status(rng),
        "activity_tier":         _activity_tier(is_risk=True, rng=rng),
        "initial_risk_band":     "CRITICAL",
    }


def build_pep_account(account_id: str,
                       pep: dict,
                       faker_pool: list,
                       rng: random.Random) -> dict:
    full_name   = pep.get("name", rng.choice(faker_pool).name())
    country     = pep.get("country") or rng.choices(COUNTRY_POOL, weights=COUNTRY_WEIGHTS)[0]
    nationality = country if rng.random() < 0.80 else rng.choices(COUNTRY_POOL, weights=COUNTRY_WEIGHTS)[0]

    created_at = random_datetime(
        datetime(2015, 1, 1), datetime(2026, 1, 1), rng
    ).strftime("%Y-%m-%d %H:%M:%S")

    has_complex = int(rng.random() < 0.10)
    shell_flag  = int(has_complex and rng.random() < 0.3)

    kyc_comp, kyc_stat = _kyc_fields(is_risk=True, rng=rng)
    dob = random_date(date(1940, 1, 1), date(2000, 12, 31), rng).isoformat()

    return {
        "account_id":            account_id,
        "account_type":          "individual",
        "full_name":             full_name,
        "country_residence":     country,
        "country_incorporation": None,
        "date_of_birth":         dob,
        "nationality":           nationality,
        "created_at":            created_at,
        "kyc_completeness":      kyc_comp,
        "kyc_status":            kyc_stat,
        "is_pep":                1,
        "pep_id":                pep.get("pep_id"),
        "has_complex_ownership": has_complex,
        "shell_company_flag":    shell_flag,
        "sanctioned_entity_id":  None,
        "name_match_type":       "none",
        "account_status":        _account_status(rng),
        "activity_tier":         _activity_tier(is_risk=True, rng=rng),
        "initial_risk_band":     _risk_band(False, True, country, rng),
    }


# ── Batch generation ──────────────────────────────────────────────────────────

def generate_batch(batch_idx: int,
                   start_n: int,
                   sanctioned_entities: list[dict],
                   peps: list[dict],
                   faker_pool: list,
                   rng: random.Random) -> list[dict]:
    """
    Generate one batch of BATCH_SIZE accounts.

    start_n: the 1-based counter for the first account in this batch.
    Returns a list of account dicts.
    """
    n_sanctioned = rng.randint(SANCTIONED_PER_BATCH_MIN, SANCTIONED_PER_BATCH_MAX)
    n_pep        = PEP_PER_BATCH
    n_clean      = BATCH_SIZE - n_sanctioned - n_pep

    # Shuffle slot types so they're spread across the batch
    slot_types = (["sanctioned"] * n_sanctioned +
                  ["pep"]        * n_pep        +
                  ["clean"]      * n_clean)
    rng.shuffle(slot_types)

    accounts = []
    for i, slot in enumerate(slot_types):
        n    = start_n + i
        acid = f"ACC-{n:06d}"

        if slot == "sanctioned" and sanctioned_entities:
            entity  = rng.choice(sanctioned_entities)
            account = build_sanctioned_account(acid, entity, faker_pool, rng)
        elif slot == "pep" and peps:
            pep     = rng.choice(peps)
            account = build_pep_account(acid, pep, faker_pool, rng)
        else:
            account = build_clean_account(acid, faker_pool, rng)

        accounts.append(account)

    return accounts


INSERT_SQL = """
INSERT OR IGNORE INTO accounts (
    account_id, account_type, full_name,
    country_residence, country_incorporation,
    date_of_birth, nationality, created_at,
    kyc_completeness, kyc_status,
    is_pep, pep_id,
    has_complex_ownership, shell_company_flag,
    sanctioned_entity_id, name_match_type,
    account_status, activity_tier, initial_risk_band
) VALUES (
    :account_id, :account_type, :full_name,
    :country_residence, :country_incorporation,
    :date_of_birth, :nationality, :created_at,
    :kyc_completeness, :kyc_status,
    :is_pep, :pep_id,
    :has_complex_ownership, :shell_company_flag,
    :sanctioned_entity_id, :name_match_type,
    :account_status, :activity_tier, :initial_risk_band
)
"""


def insert_batch(conn: sqlite3.Connection, accounts: list[dict]) -> int:
    cur = conn.cursor()
    cur.executemany(INSERT_SQL, accounts)
    conn.commit()
    return cur.rowcount   # rows affected (≥0)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 02_generate_accounts.py started ===")

    # ── Load progress ─────────────────────────────────────────────────────────
    progress = load_progress()
    done_batches    = set(progress.get("accounts_batches_done", []))
    accounts_so_far = progress.get("accounts_generated", 0)

    remaining = [i for i in range(NUM_BATCHES) if i not in done_batches]
    if not remaining:
        logger.info("All batches already complete — nothing to do.")
        print("All account batches already generated. Exiting.")
        return

    logger.info(f"Batches to generate: {remaining}")
    logger.info(f"Accounts already generated: {accounts_so_far}")

    # ── Load reference data ───────────────────────────────────────────────────
    logger.info("Loading reference data …")
    sanctioned_entities = read_csv(SANCTIONED_CSV)
    peps                = read_csv(PEPS_CSV)
    logger.info(f"  sanctioned_entities: {len(sanctioned_entities)} rows")
    logger.info(f"  peps: {len(peps)} rows")

    if not sanctioned_entities:
        logger.warning("sanctioned_entities.csv is empty or missing — sanctioned slots will fall back to clean.")
    if not peps:
        logger.warning("peps.csv is empty or missing — PEP slots will fall back to clean.")

    # ── Build Faker pool ──────────────────────────────────────────────────────
    logger.info("Building Faker locale pool …")
    faker_pool = build_faker_pool()
    logger.info(f"  {len(faker_pool)} Faker locales loaded.")

    # ── RNG (seeded per script run for reproducibility of individual batches) ─
    rng = random.Random()   # unseeded → fully random; seed with int for reproducibility

    # ── Open DB ───────────────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    try:
        for batch_idx in remaining:
            # Determine starting account number for this batch.
            # We compute it from the *ordered* position: batch_idx * BATCH_SIZE + 1,
            # so IDs are always deterministic regardless of resume order.
            start_n = batch_idx * BATCH_SIZE + 1

            logger.info(
                f"Generating batch {batch_idx} "
                f"(accounts ACC-{start_n:06d} … ACC-{start_n + BATCH_SIZE - 1:06d}) …"
            )

            accounts = generate_batch(
                batch_idx, start_n,
                sanctioned_entities, peps,
                faker_pool, rng,
            )

            inserted = insert_batch(conn, accounts)
            logger.info(f"  Batch {batch_idx}: {len(accounts)} generated, {inserted} rows inserted.")

            # ── Update progress ───────────────────────────────────────────────
            done_batches.add(batch_idx)
            accounts_so_far += len(accounts)

            progress["accounts_batches_done"] = sorted(done_batches)
            progress["accounts_generated"]    = accounts_so_far
            save_progress(progress)

            logger.info(
                f"  Progress saved: {accounts_so_far}/{TOTAL_ACCOUNTS} accounts, "
                f"batches done: {sorted(done_batches)}"
            )

    except Exception as exc:
        logger.error(f"Fatal error: {exc}", exc_info=True)
        conn.close()
        sys.exit(1)

    conn.close()
    logger.info("Database connection closed.")
    logger.info("=== 02_generate_accounts.py finished successfully ===")
    print(f"Done. {accounts_so_far} accounts written to database.")


if __name__ == "__main__":
    main()
