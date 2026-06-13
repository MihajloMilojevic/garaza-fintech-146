"""
04_generate_transactions.py
===========================
Generates 200,000 synthetic transactions in 20 batches of 10,000 and inserts
them into the `transactions` table of sanctions_screening.db.

After all batches are complete, runs a velocity post-pass that computes:
  - velocity_30d_count
  - velocity_30d_amount
  - is_first_time_recipient

Progress is tracked in progress.json:
  - transactions_batches_done: list of completed batch indices
  - transactions_velocity_pass_complete: bool

Idempotent: skips batches already in transactions_batches_done.
"""

import csv
import json
import logging
import math
import os
import random
import sqlite3
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DB_PATH = os.path.join(PROJECT_DIR, "sanctions_screening.db")
PROGRESS_PATH = os.path.join(PROJECT_DIR, "progress.json")
LOG_PATH = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")
REF_DIR = os.path.join(PROJECT_DIR, "reference_data")

# ── Constants ─────────────────────────────────────────────────────────────────
TOTAL_TRANSACTIONS = 200_000
BATCH_SIZE = 10_000
NUM_BATCHES = TOTAL_TRANSACTIONS // BATCH_SIZE  # 20

DATE_START = datetime(2023, 1, 1)
DATE_END = datetime(2026, 6, 1)
DATE_RANGE_DAYS = (DATE_END - DATE_START).days

PAYMENT_RAIL_WEIGHTS = {
    "wire": 0.20,
    "ach": 0.40,
    "card": 0.25,
    "check": 0.10,
    "internal": 0.05,
}

CURRENCY_WEIGHTS = {
    "USD": 0.70,
    "EUR": 0.15,
    "GBP": 0.05,
    "CNY": 0.03,
    "CAD": 0.02,
    "CHF": 0.01,
    "AED": 0.01,
    "SGD": 0.01,
    "HKD": 0.01,
    "OTHER": 0.01,
}

OTHER_CURRENCIES = ["JPY", "KRW", "BRL", "MXN", "INR", "RUB", "TRY", "ZAR", "NGN", "THB"]

RECIPIENT_TYPE_WEIGHTS = {
    "account": 0.50,
    "external_individual": 0.35,
    "crypto_wallet": 0.15,
}

FALLBACK_DISTRIBUTIONS = {
    "wire":     {"mean": 45000, "std": 80000, "p5": 500,   "p95": 200000},
    "ach":      {"mean": 2500,  "std": 5000,  "p5": 50,    "p95": 15000},
    "card":     {"mean": 180,   "std": 350,   "p5": 5,     "p95": 800},
    "check":    {"mean": 3500,  "std": 8000,  "p5": 100,   "p95": 20000},
    "internal": {"mean": 10000, "std": 25000, "p5": 200,   "p95": 50000},
    "crypto":   {"mean": 8000,  "std": 20000, "p5": 100,   "p95": 50000},
}

VELOCITY_BATCH_SIZE = 1000

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("04_generate_transactions")
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

def load_rail_distributions(logger: logging.Logger) -> dict:
    """Load payment-rail amount distributions from aml_transactions_sample.csv."""
    path = os.path.join(REF_DIR, "aml_transactions_sample.csv")
    try:
        raw: dict = defaultdict(dict)
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rail = row["payment_rail"].strip().lower()
                stat = row["stat_name"].strip().lower()
                try:
                    val = float(row["value"])
                except (ValueError, KeyError):
                    continue
                raw[rail][stat] = val
        if not raw:
            raise ValueError("Empty distribution file")
        logger.info(f"Loaded rail distributions from {path}: {list(raw.keys())}")
        return dict(raw)
    except Exception as exc:
        logger.warning(f"Could not load rail distributions ({exc}); using fallback.")
        return {}


def build_lognormal_params(dist: dict) -> tuple:
    """
    Given a dist dict with keys mean/std/p5/p95, compute (mu, sigma) for lognormal
    so that the median is reasonable.  We calibrate using p5 and p95 if available.
    Returns (mu, sigma) for numpy-free sampling via math.exp(mu + sigma*gauss).
    """
    p5  = dist.get("p5",  dist.get("p_5",   dist.get("mean", 100) * 0.1))
    p95 = dist.get("p95", dist.get("p_95",  dist.get("mean", 100) * 4.0))
    # Avoid log(0)
    p5  = max(p5, 1.0)
    p95 = max(p95, p5 * 2)
    # For lognormal: p5 = exp(mu + z5*sigma), p95 = exp(mu + z95*sigma)
    # z5 = -1.6449, z95 = +1.6449
    z5  = -1.6449
    z95 =  1.6449
    sigma = (math.log(p95) - math.log(p5)) / (z95 - z5)
    mu    = (math.log(p5) + math.log(p95)) / 2.0
    return mu, sigma


def load_hour_distribution(logger: logging.Logger) -> list:
    """Return list of 24 weights (index = hour). Falls back to peaked distribution."""
    path = os.path.join(REF_DIR, "aml_hour_dist.csv")
    try:
        weights = [0.0] * 24
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                hour  = int(row["hour"])
                count = float(row["count"])
                if 0 <= hour < 24:
                    weights[hour] = count
        total = sum(weights)
        if total == 0:
            raise ValueError("All zero")
        weights = [w / total for w in weights]
        logger.info(f"Loaded hour distribution from {path}")
        return weights
    except Exception as exc:
        logger.warning(f"Could not load hour distribution ({exc}); using peaked fallback.")
        # Peak 9-17, low overnight
        base = [0.5] * 24
        for h in range(9, 18):
            base[h] = 3.0
        for h in range(18, 22):
            base[h] = 1.5
        t = sum(base)
        return [w / t for w in base]


def load_dow_distribution(logger: logging.Logger) -> list:
    """Return list of 7 weights (0=Mon … 6=Sun)."""
    path = os.path.join(REF_DIR, "aml_dow_dist.csv")
    try:
        weights = [0.0] * 7
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dow   = int(row["dow"])
                count = float(row["count"])
                if 0 <= dow < 7:
                    weights[dow] = count
        total = sum(weights)
        if total == 0:
            raise ValueError("All zero")
        weights = [w / total for w in weights]
        logger.info(f"Loaded dow distribution from {path}")
        return weights
    except Exception as exc:
        logger.warning(f"Could not load dow distribution ({exc}); using weekday-heavy fallback.")
        # Mon-Fri higher
        return [0.19, 0.19, 0.19, 0.19, 0.19, 0.025, 0.025]


def load_laundering_velocity(logger: logging.Logger) -> dict:
    path = os.path.join(REF_DIR, "aml_laundering_velocity.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Loaded laundering velocity data from {path}")
        return data
    except Exception as exc:
        logger.warning(f"Could not load laundering velocity ({exc}); using defaults.")
        return {
            "burst_min_txns": 3,
            "burst_max_txns": 10,
            "burst_window_days": 3,
            "burst_hour_weights": {str(h): 3.0 for h in range(2, 6)},
        }


# ── Weighted sampling helpers ─────────────────────────────────────────────────

def weighted_choice(choices: list, weights: list):
    """Pick one item from choices according to weights (unnormalised ok)."""
    total = sum(weights)
    r = random.random() * total
    cumul = 0.0
    for item, w in zip(choices, weights):
        cumul += w
        if r <= cumul:
            return item
    return choices[-1]


def build_cumulative(weights: list) -> list:
    """Return cumulative weight list for bisect-based sampling."""
    cumul = []
    total = 0.0
    for w in weights:
        total += w
        cumul.append(total)
    return cumul


def sample_from_cumulative(cumul: list, items: list):
    r = random.random() * cumul[-1]
    idx = bisect_left(cumul, r)
    return items[min(idx, len(items) - 1)]


def sample_lognormal(mu: float, sigma: float, cap: float = 10_000_000.0) -> float:
    val = math.exp(mu + sigma * random.gauss(0, 1))
    return min(max(val, 0.01), cap)


# ── Fake name generators (no faker dependency assumed) ────────────────────────
# Minimal deterministic generators to avoid Faker dependency requirement uncertainty.

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "William", "Barbara", "David", "Elizabeth", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Hiroshi", "Yuki", "Ahmed", "Fatima",
    "Mohammed", "Aisha", "Wei", "Lin", "Carlos", "Maria", "Andrei", "Olga",
    "Pierre", "Sophie", "Hans", "Ingrid", "Kwame", "Amara", "Raj", "Priya",
    "Ali", "Zara", "Igor", "Natasha", "Luca", "Giulia", "Mateus", "Isabela",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Wilson", "Anderson", "Taylor", "Thomas", "Jackson", "White", "Harris", "Martin",
    "Thompson", "Young", "Allen", "Sanchez", "Lee", "Perez", "Walker", "Hall",
    "Yamamoto", "Tanaka", "Al-Rashid", "Hassan", "Zhang", "Wang", "Popescu", "Ionescu",
    "Dubois", "Laurent", "Mueller", "Schmidt", "Mensah", "Osei", "Sharma", "Patel",
    "Khan", "Malik", "Petrov", "Volkov", "Rossi", "Ferrari", "Silva", "Santos",
]

COMPANY_SUFFIXES = [
    "Ltd", "LLC", "Inc", "Corp", "Group", "Holdings", "Partners", "Enterprises",
    "Solutions", "Capital", "Ventures", "International", "Global", "Associates",
]

COMPANY_WORDS = [
    "Alpha", "Beta", "Apex", "Prime", "Eagle", "Sterling", "Pacific", "Atlantic",
    "North", "South", "Eastern", "Western", "Summit", "Horizon", "Pinnacle", "Dynamic",
    "Advanced", "United", "Global", "National", "Strategic", "Integrated", "Premier",
]


def random_person_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def random_company_name() -> str:
    return f"{random.choice(COMPANY_WORDS)} {random.choice(COMPANY_WORDS)} {random.choice(COMPANY_SUFFIXES)}"


def random_external_name() -> str:
    if random.random() < 0.6:
        return random_person_name()
    return random_company_name()


CHAINS = ["BTC", "ETH", "USDT_TRC20", "XRP", "LTC", "BNB", "SOL"]
HEX_CHARS = "0123456789abcdef"


def random_wallet_address(chain: str = "ETH") -> str:
    if chain == "BTC":
        return "1" + "".join(random.choices("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz", k=33))
    elif chain in ("ETH", "BNB"):
        return "0x" + "".join(random.choices(HEX_CHARS, k=40))
    elif chain == "XRP":
        return "r" + "".join(random.choices("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz", k=33))
    else:
        return "0x" + "".join(random.choices(HEX_CHARS, k=40))


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def sample_timestamp(hour_weights: list, dow_weights: list,
                     force_hour: int = None, force_date: datetime = None) -> datetime:
    """Generate a random timestamp within DATE_START … DATE_END."""
    if force_date is not None:
        base = force_date
    else:
        # Sample a day-of-week consistent date
        days_offset = random.randint(0, DATE_RANGE_DAYS - 1)
        base = DATE_START + timedelta(days=days_offset)
        # Optionally re-weight by dow
        # (We already pick uniformly from calendar days; if dow_weights provided, accept/reject)
        # For simplicity, just use the random day as-is (close enough).

    hour = force_hour if force_hour is not None else sample_from_cumulative(
        build_cumulative(hour_weights), list(range(24))
    )
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return base.replace(hour=hour, minute=minute, second=second)


def format_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ── DB helpers ────────────────────────────────────────────────────────────────

def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-65536;")  # 64 MB
    conn.row_factory = sqlite3.Row
    return conn


def fetch_accounts(conn: sqlite3.Connection) -> list:
    cur = conn.execute(
        "SELECT account_id, full_name, country_residence, created_at, "
        "activity_tier, is_pep, sanctioned_entity_id, account_status "
        "FROM accounts"
    )
    return cur.fetchall()


def fetch_wallets(conn: sqlite3.Connection) -> list:
    cur = conn.execute("SELECT wallet_id, wallet_address, chain FROM wallets LIMIT 50000")
    return cur.fetchall()


def fetch_all_account_ids(conn: sqlite3.Connection) -> list:
    cur = conn.execute("SELECT account_id FROM accounts")
    return [row[0] for row in cur.fetchall()]


# ── Sender selection ──────────────────────────────────────────────────────────

def build_sender_pool(accounts: list) -> tuple:
    """
    Return (sender_ids, cumulative_weights) for weighted sampling.
    active accounts only; high-tier and sanctioned/PEP weighted higher.
    """
    tier_weight = {"high": 5.0, "medium": 2.0, "low": 1.0}
    ids, weights = [], []
    for acc in accounts:
        if acc["account_status"] != "active":
            continue
        w = tier_weight.get(acc["activity_tier"], 1.0)
        # Sanctioned or PEP gets 3x multiplier
        if acc["sanctioned_entity_id"] or acc["is_pep"]:
            w *= 3.0
        ids.append(acc["account_id"])
        weights.append(w)
    cumul = build_cumulative(weights)
    return ids, cumul


# ── Country helpers ───────────────────────────────────────────────────────────

def load_country_list(conn: sqlite3.Connection) -> list:
    try:
        cur = conn.execute("SELECT DISTINCT country_residence FROM accounts WHERE country_residence IS NOT NULL")
        countries = [row[0] for row in cur.fetchall()]
        return countries if countries else ["US", "GB", "DE", "FR", "CN", "IN", "BR", "SG", "AE", "RU"]
    except Exception:
        return ["US", "GB", "DE", "FR", "CN", "IN", "BR", "SG", "AE", "RU"]


def sample_recipient_country(sender_country: str, all_countries: list) -> str:
    """70% same-region proxy: 70% chance return sender's country, 30% random."""
    if random.random() < 0.70:
        return sender_country or random.choice(all_countries)
    return random.choice(all_countries)


# ── Rail / amount samplers ────────────────────────────────────────────────────

def build_rail_sampler(rail_dists: dict) -> dict:
    """
    Merge reference distributions with fallback, build lognormal params per rail.
    Returns {rail: (mu, sigma)}.
    """
    params = {}
    for rail, fallback in FALLBACK_DISTRIBUTIONS.items():
        ref = rail_dists.get(rail, {})
        dist = {
            "mean": ref.get("mean", fallback["mean"]),
            "std":  ref.get("std",  fallback["std"]),
            "p5":   ref.get("p5",   ref.get("p_5",   fallback["p5"])),
            "p95":  ref.get("p95",  ref.get("p_95",  fallback["p95"])),
        }
        params[rail] = build_lognormal_params(dist)
    return params


def sample_payment_rail(is_high_amount_sender: bool, recipient_type: str) -> str:
    if recipient_type == "crypto_wallet":
        return random.choice(["wire", "crypto"])
    if is_high_amount_sender:
        # More wire/ach
        return weighted_choice(
            ["wire", "ach", "card", "check", "internal"],
            [0.35, 0.40, 0.10, 0.10, 0.05]
        )
    return weighted_choice(
        list(PAYMENT_RAIL_WEIGHTS.keys()),
        list(PAYMENT_RAIL_WEIGHTS.values())
    )


def sample_currency() -> str:
    c = weighted_choice(list(CURRENCY_WEIGHTS.keys()), list(CURRENCY_WEIGHTS.values()))
    if c == "OTHER":
        return random.choice(OTHER_CURRENCIES)
    return c


# ── Burst pattern generator ───────────────────────────────────────────────────

def make_burst_transactions(
    sender_id: str,
    sender_row: dict,
    n_burst: int,
    base_date: datetime,
    window_days: int,
    rail_params: dict,
    all_account_ids: list,
    all_countries: list,
    wallets: list,
    global_txn_counter: list,  # mutable [int]
    hour_weights_night: list,
) -> list:
    """Generate a cluster of high-risk burst transactions."""
    rows = []
    base_amount = None
    for i in range(n_burst):
        global_txn_counter[0] += 1
        n = global_txn_counter[0]
        txn_id = f"TXN-{n:08d}"

        # Escalating amounts
        rail = random.choice(["wire", "ach", "crypto"])
        mu, sigma = rail_params.get(rail, rail_params.get("wire", (math.log(10000), 0.8)))
        amount = sample_lognormal(mu, sigma)
        if base_amount is None:
            base_amount = amount
        else:
            # Escalate by 10-50%
            amount = base_amount * (1.0 + random.uniform(0.1, 0.5)) * (i + 1)
            amount = min(amount, 10_000_000.0)

        # Unusual hours (2-5 AM more common)
        hour = sample_from_cumulative(build_cumulative(hour_weights_night), list(range(24)))

        offset_days = random.randint(0, window_days - 1)
        ts_dt = base_date + timedelta(days=offset_days)
        ts_dt = ts_dt.replace(
            hour=hour,
            minute=random.randint(0, 59),
            second=random.randint(0, 59)
        )
        ts_str = format_ts(ts_dt)

        recipient_type = weighted_choice(
            ["account", "external_individual", "crypto_wallet"],
            [0.20, 0.30, 0.50]  # more crypto for burst
        )
        recipient_account_id = None
        recipient_name = None
        recipient_wallet_id = None
        # Force different countries for burst
        recipient_country = random.choice(all_countries)

        if recipient_type == "account":
            recipient_account_id = random.choice(all_account_ids)
            recipient_name = None
        elif recipient_type == "external_individual":
            recipient_name = random_external_name()
        else:
            if wallets:
                w = random.choice(wallets)
                recipient_wallet_id = w["wallet_id"]
            else:
                recipient_wallet_id = random_wallet_address(random.choice(CHAINS))

        sender_country = sender_row["country_residence"] or "US"
        try:
            created_at = datetime.fromisoformat(sender_row["created_at"][:19])
        except Exception:
            created_at = DATE_START
        age_days = (ts_dt - created_at).days

        rows.append((
            txn_id, sender_id, recipient_account_id, recipient_type,
            recipient_name, recipient_country, recipient_wallet_id,
            round(amount, 2), sample_currency(), rail,
            ts_str, 0, max(age_days, 0), 0, 0.0,
            ts_dt.hour, ts_dt.weekday(), "aml_derived"
        ))
    return rows


# ── Main transaction row generator ────────────────────────────────────────────

def generate_batch(
    batch_idx: int,
    batch_size: int,
    start_n: int,
    sender_ids: list,
    sender_cumul: list,
    account_map: dict,
    all_account_ids: list,
    all_countries: list,
    wallets: list,
    rail_params: dict,
    hour_weights: list,
    dow_weights: list,
    hour_weights_night: list,
    velocity_data: dict,
    shape_source: str,
    logger: logging.Logger,
) -> list:
    """Generate batch_size transaction rows. Returns list of tuples."""
    rows = []
    n = start_n

    burst_sender_ids = set()
    # Pre-determine burst senders for this batch (~5% of unique senders selected)
    for acc_id, acc in account_map.items():
        if acc["sanctioned_entity_id"] or acc["is_pep"] or acc["activity_tier"] == "high":
            if random.random() < 0.05:
                burst_sender_ids.add(acc_id)

    burst_rows_buffer = []

    while len(rows) + len(burst_rows_buffer) < batch_size:
        n += 1
        txn_id = f"TXN-{n:08d}"

        sender_id = sample_from_cumulative(sender_cumul, sender_ids)
        sender_row = account_map.get(sender_id, {})

        sender_country = sender_row.get("country_residence") or "US"
        is_high = sender_row.get("activity_tier") == "high"
        is_risky = bool(sender_row.get("sanctioned_entity_id") or sender_row.get("is_pep"))

        # Burst pattern injection
        if sender_id in burst_sender_ids and random.random() < 0.3:
            burst_n_txns = random.randint(
                velocity_data.get("burst_min_txns", 3),
                velocity_data.get("burst_max_txns", 10)
            )
            burst_window = velocity_data.get("burst_window_days", 3)
            offset_days = random.randint(0, DATE_RANGE_DAYS - burst_window - 1)
            base_date = DATE_START + timedelta(days=offset_days)
            counter = [n]  # mutable reference
            burst = make_burst_transactions(
                sender_id, sender_row, burst_n_txns, base_date, burst_window,
                rail_params, all_account_ids, all_countries, wallets,
                counter, hour_weights_night
            )
            n = counter[0]
            burst_rows_buffer.extend(burst)
            burst_sender_ids.discard(sender_id)  # don't burst again this batch
            continue

        # Normal transaction
        recipient_type = weighted_choice(
            list(RECIPIENT_TYPE_WEIGHTS.keys()),
            list(RECIPIENT_TYPE_WEIGHTS.values())
        )

        recipient_account_id = None
        recipient_name = None
        recipient_wallet_id = None

        if recipient_type == "account":
            recipient_account_id = random.choice(all_account_ids)
            # Try to get name from account map
            rec_acc = account_map.get(recipient_account_id)
            recipient_name = rec_acc["full_name"] if rec_acc else None
        elif recipient_type == "external_individual":
            recipient_name = random_external_name()
        else:  # crypto_wallet
            if wallets and random.random() < 0.7:
                w = random.choice(wallets)
                recipient_wallet_id = w["wallet_id"]
            else:
                recipient_wallet_id = random_wallet_address(random.choice(CHAINS))

        recipient_country = sample_recipient_country(sender_country, all_countries)

        rail = sample_payment_rail(is_high, recipient_type)
        mu, sigma = rail_params.get(rail, rail_params.get("wire", (math.log(10000), 0.8)))
        amount = sample_lognormal(mu, sigma)

        currency = sample_currency()

        ts_dt = sample_timestamp(hour_weights, dow_weights)
        ts_str = format_ts(ts_dt)

        try:
            created_at = datetime.fromisoformat(sender_row["created_at"][:19])
        except Exception:
            created_at = DATE_START
        age_days = max((ts_dt - created_at).days, 0)

        used_aml = shape_source == "aml_derived"

        rows.append((
            txn_id, sender_id, recipient_account_id, recipient_type,
            recipient_name, recipient_country, recipient_wallet_id,
            round(amount, 2), currency, rail,
            ts_str, 0, age_days, 0, 0.0,
            ts_dt.hour, ts_dt.weekday(),
            "aml_derived" if used_aml else "synthetic"
        ))

    # Drain burst buffer (may overshoot slightly; trimmed outside)
    rows.extend(burst_rows_buffer)
    return rows[:batch_size]


# ── Velocity post-pass ────────────────────────────────────────────────────────

def run_velocity_pass(conn: sqlite3.Connection, logger: logging.Logger) -> None:
    """
    For every sender:
      1. Sort their transactions by timestamp.
      2. For each txn, count/sum transactions by that sender in the preceding 30 days.
      3. Mark is_first_time_recipient=1 if this is the first send to this recipient.
    Updates are written in batches of VELOCITY_BATCH_SIZE.
    """
    logger.info("Starting velocity post-pass...")

    # Load all transactions (id, sender, recipient_account_id, recipient_name,
    #                         recipient_wallet_id, timestamp, amount)
    cur = conn.execute(
        "SELECT transaction_id, sender_account_id, recipient_account_id, "
        "       recipient_name, recipient_wallet_id, timestamp, amount "
        "FROM transactions ORDER BY sender_account_id, timestamp"
    )
    rows = cur.fetchall()
    logger.info(f"Loaded {len(rows):,} transactions for velocity pass.")

    # Group by sender
    by_sender: dict = defaultdict(list)
    for row in rows:
        by_sender[row[1]].append(row)

    updates: list = []
    total_processed = 0

    for sender_id, txn_list in by_sender.items():
        # Sort by timestamp string (ISO8601 sorts lexicographically)
        txn_list.sort(key=lambda r: r[5])

        seen_recipients: set = set()
        n = len(txn_list)
        timestamps = [r[5] for r in txn_list]
        amounts    = [r[6] for r in txn_list]

        for i, row in enumerate(txn_list):
            txn_id = row[0]
            ts_str = row[5]

            try:
                ts = datetime.fromisoformat(ts_str)
            except Exception:
                ts = DATE_START

            cutoff = (ts - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")

            # Find the window start index via bisect
            lo = bisect_left(timestamps, cutoff)
            # Count/sum from lo to i (exclusive)
            window_count  = i - lo
            window_amount = sum(amounts[lo:i])

            # First-time recipient key
            rec_key = (
                row[2] or "",   # recipient_account_id
                row[3] or "",   # recipient_name
                row[4] or "",   # recipient_wallet_id
            )
            is_first = 1 if rec_key not in seen_recipients else 0
            seen_recipients.add(rec_key)

            updates.append((window_count, window_amount, is_first, txn_id))
            total_processed += 1

        # Flush in batches
        if len(updates) >= VELOCITY_BATCH_SIZE:
            conn.executemany(
                "UPDATE transactions SET velocity_30d_count=?, velocity_30d_amount=?, "
                "is_first_time_recipient=? WHERE transaction_id=?",
                updates
            )
            conn.commit()
            updates.clear()

    # Final flush
    if updates:
        conn.executemany(
            "UPDATE transactions SET velocity_30d_count=?, velocity_30d_amount=?, "
            "is_first_time_recipient=? WHERE transaction_id=?",
            updates
        )
        conn.commit()

    logger.info(f"Velocity pass complete. Updated {total_processed:,} rows.")


# ── Night-hour weights ────────────────────────────────────────────────────────

def build_night_hour_weights() -> list:
    """Weights biased toward 2-5 AM for burst/suspicious transactions."""
    weights = [0.3] * 24
    for h in range(2, 6):
        weights[h] = 3.0
    for h in range(22, 24):
        weights[h] = 1.5
    t = sum(weights)
    return [w / t for w in weights]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 04_generate_transactions.py started ===")

    progress = load_progress()

    # ── Load reference data ────────────────────────────────────────────────────
    rail_dists_raw = load_rail_distributions(logger)
    rail_params = build_rail_sampler(rail_dists_raw)
    shape_source = "aml_derived" if rail_dists_raw else "synthetic"

    hour_weights      = load_hour_distribution(logger)
    dow_weights       = load_dow_distribution(logger)
    hour_weights_night = build_night_hour_weights()
    velocity_data     = load_laundering_velocity(logger)

    # ── Load DB data ───────────────────────────────────────────────────────────
    conn = open_db()

    accounts = fetch_accounts(conn)
    if not accounts:
        logger.error("No accounts found in DB. Run account generation scripts first.")
        conn.close()
        sys.exit(1)
    logger.info(f"Loaded {len(accounts):,} accounts.")

    account_map: dict = {acc["account_id"]: dict(acc) for acc in accounts}
    all_account_ids  = [acc["account_id"] for acc in accounts]
    all_countries    = load_country_list(conn)
    wallets          = fetch_wallets(conn)
    logger.info(f"Loaded {len(wallets):,} wallets, {len(all_countries)} distinct countries.")

    sender_ids, sender_cumul = build_sender_pool(accounts)
    logger.info(f"Sender pool size: {len(sender_ids):,} active accounts.")

    # ── Batch generation ───────────────────────────────────────────────────────
    batches_done: list = progress.get("transactions_batches_done", [])
    if not isinstance(batches_done, list):
        batches_done = []

    INSERT_SQL = """
        INSERT OR IGNORE INTO transactions (
            transaction_id, sender_account_id, recipient_account_id,
            recipient_type, recipient_name, recipient_country, recipient_wallet_id,
            amount, currency, payment_rail, timestamp,
            is_first_time_recipient, sender_account_age_days,
            velocity_30d_count, velocity_30d_amount,
            hour_of_day, day_of_week, shape_source
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """

    for batch_idx in range(NUM_BATCHES):
        if batch_idx in batches_done:
            logger.info(f"Batch {batch_idx} already done — skipping.")
            continue

        start_n = batch_idx * BATCH_SIZE
        logger.info(f"Generating batch {batch_idx} (TXN #{start_n+1:,} … #{start_n+BATCH_SIZE:,}) ...")

        rows = generate_batch(
            batch_idx=batch_idx,
            batch_size=BATCH_SIZE,
            start_n=start_n,
            sender_ids=sender_ids,
            sender_cumul=sender_cumul,
            account_map=account_map,
            all_account_ids=all_account_ids,
            all_countries=all_countries,
            wallets=wallets,
            rail_params=rail_params,
            hour_weights=hour_weights,
            dow_weights=dow_weights,
            hour_weights_night=hour_weights_night,
            velocity_data=velocity_data,
            shape_source=shape_source,
            logger=logger,
        )

        conn.executemany(INSERT_SQL, rows)
        conn.commit()

        batches_done.append(batch_idx)
        p = load_progress()
        p["transactions_batches_done"] = batches_done
        p["transactions_generated"] = (batch_idx + 1) * BATCH_SIZE
        save_progress(p)
        logger.info(f"  Batch {batch_idx} inserted {len(rows):,} rows. Total done: {(batch_idx+1)*BATCH_SIZE:,}.")

    logger.info(f"All {NUM_BATCHES} batches complete.")

    # ── Velocity post-pass ────────────────────────────────────────────────────
    if not progress.get("transactions_velocity_pass_complete"):
        run_velocity_pass(conn, logger)
        update_progress_key("transactions_velocity_pass_complete", True)
        logger.info("progress.json updated: transactions_velocity_pass_complete=true")
    else:
        logger.info("Velocity pass already complete — skipping.")

    conn.close()
    logger.info("=== 04_generate_transactions.py finished ===")
    print("Done. Transactions generated and velocity pass complete.")


if __name__ == "__main__":
    main()
