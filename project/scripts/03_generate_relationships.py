"""
03_generate_relationships.py
============================
Generate account relationships (account_relationships table) and crypto
wallets (wallets table) for the accounts already in the database.

Must be run AFTER 02_generate_accounts.py.

Idempotent: skips if both `relationships_complete` AND `wallets_complete`
are true in progress.json.

Usage:
    python 03_generate_relationships.py
"""

import csv
import json
import logging
import os
import random
import sqlite3
import string
import sys
from datetime import datetime, timezone
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR     = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DB_PATH         = os.path.join(PROJECT_DIR, "sanctions_screening.db")
PROGRESS_PATH   = os.path.join(PROJECT_DIR, "progress.json")
LOG_PATH        = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")
REF_DIR         = os.path.join(PROJECT_DIR, "reference_data")
SANCTIONED_CSV  = os.path.join(REF_DIR, "sanctioned_entities.csv")
SANC_REL_CSV    = os.path.join(REF_DIR, "sanctioned_relationships.csv")

# ── Constants ─────────────────────────────────────────────────────────────────
BASE58_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Wallet probability by risk tier
WALLET_PROB_NORMAL   = 0.15
WALLET_PROB_HIGH     = 0.40   # sanctioned / PEP / CRITICAL risk-band

# Relationship type → (role_a, role_b)
REL_ROLES = {
    "ownership":    ("owner",    "asset"),
    "family":       ("person",   "relative"),
    "directorship": ("director", "organization"),
    "associate":    ("person",   "associate"),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("03_generate_relationships")
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
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_faker():
    try:
        from faker import Faker
        return Faker("en_US")
    except ImportError:
        raise RuntimeError("faker package not installed.  Run: pip install faker")


# ── Address generators ────────────────────────────────────────────────────────

def gen_eth_address(rng: random.Random) -> str:
    """Return a synthetic Ethereum address: 0x + 40 hex chars."""
    return "0x" + "".join(rng.choices(string.hexdigits[:16], k=40))


def gen_btc_address(rng: random.Random) -> str:
    """Return a synthetic P2PKH Bitcoin address: '1' + 33 base58 chars."""
    return "1" + "".join(rng.choices(BASE58_CHARS, k=33))


def gen_bech32_address(rng: random.Random) -> str:
    """Return a synthetic Bech32 Bitcoin address: 'bc1q' + 38 lowercase hex chars."""
    return "bc1q" + "".join(rng.choices("0123456789abcdef", k=38))


def generate_synthetic_address(rng: random.Random) -> tuple[str, str]:
    """Return (address, chain)."""
    roll = rng.random()
    if roll < 0.60:
        return gen_eth_address(rng), "Ethereum"
    elif roll < 0.85:
        return gen_btc_address(rng), "Bitcoin"
    else:
        return gen_bech32_address(rng), "Bitcoin"


# ── Relationship builder ──────────────────────────────────────────────────────

def _make_rel(rel_n: int,
              account_id: str,
              rel_type: str,
              related_name: str,
              related_is_pep: int,
              related_is_sanctioned: int,
              related_sanctioned_entity_id: Optional[str],
              source: str) -> dict:
    role_a, role_b = REL_ROLES[rel_type]
    return {
        "relationship_id":              f"REL-{rel_n:07d}",
        "account_id":                   account_id,
        "related_entity_name":          related_name,
        "relationship_type":            rel_type,
        "role_a":                       role_a,
        "role_b":                       role_b,
        "related_is_pep":               related_is_pep,
        "related_is_sanctioned":        related_is_sanctioned,
        "related_sanctioned_entity_id": related_sanctioned_entity_id,
        "source":                       source,
    }


def choose_rel_type(account_type: str, rng: random.Random) -> str:
    if account_type == "business":
        return rng.choices(
            ["ownership", "directorship", "associate", "family"],
            weights=[40, 35, 20, 5],
        )[0]
    else:
        return rng.choices(
            ["family", "associate", "ownership"],
            weights=[50, 35, 15],
        )[0]


def _ftm_rels_for_entity(entity_id: str,
                          ftm_index: dict[str, list[dict]]) -> list[dict]:
    """Return FTM relationship rows matching entity_id on either side."""
    return ftm_index.get(entity_id, [])


def build_relationships(accounts: list[dict],
                        sanctioned_entities: list[dict],
                        ftm_rels: list[dict],
                        relationships_source: Optional[str],
                        faker,
                        rng: random.Random) -> list[dict]:
    """
    Build all account_relationships rows.

    Returns a flat list of relationship dicts.
    """
    # Index FTM relationships by entity_id (both sides)
    ftm_index: dict[str, list[dict]] = {}
    for row in ftm_rels:
        for key in ("entity_id_a", "entity_id_b"):
            eid = row.get(key)
            if eid:
                ftm_index.setdefault(eid, []).append(row)

    # Index sanctioned entities by entity_id for quick lookup
    sanc_by_id: dict[str, dict] = {
        e["entity_id"]: e for e in sanctioned_entities if e.get("entity_id")
    }

    all_rels: list[dict] = []
    rel_counter = 1

    for acct in accounts:
        acid        = acct["account_id"]
        acct_type   = acct.get("account_type", "individual")
        sanc_eid    = acct.get("sanctioned_entity_id")
        is_pep      = int(acct.get("is_pep", 0))
        has_complex = int(acct.get("has_complex_ownership", 0))
        risk_band   = acct.get("initial_risk_band", "LOW")

        # ── 1. Sanctioned / PEP accounts ──────────────────────────────────────
        if sanc_eid or is_pep:
            # FTM real edges
            if relationships_source == "real_ftm" and sanc_eid:
                for ftm_row in _ftm_rels_for_entity(sanc_eid, ftm_index):
                    # Determine the "other side" entity name
                    if ftm_row.get("entity_id_a") == sanc_eid:
                        other_name = ftm_row.get("name_b") or ftm_row.get("entity_id_b", "Unknown")
                        other_eid  = ftm_row.get("entity_id_b")
                    else:
                        other_name = ftm_row.get("name_a") or ftm_row.get("entity_id_a", "Unknown")
                        other_eid  = ftm_row.get("entity_id_a")

                    rel_type = ftm_row.get("relationship_type", "associate")
                    if rel_type not in REL_ROLES:
                        rel_type = "associate"

                    other_is_sanc = int(other_eid in sanc_by_id) if other_eid else 0
                    all_rels.append(_make_rel(
                        rel_counter, acid, rel_type, other_name,
                        0, other_is_sanc,
                        other_eid if other_is_sanc else None,
                        "real_ftm",
                    ))
                    rel_counter += 1

            # 0-3 additional synthetic relationships
            for _ in range(rng.randint(0, 3)):
                rel_type    = choose_rel_type(acct_type, rng)
                related_name = faker.name() if rel_type != "ownership" else faker.company()
                all_rels.append(_make_rel(
                    rel_counter, acid, rel_type, related_name,
                    0, 0, None, "synthetic",
                ))
                rel_counter += 1

        # ── 2. Business with complex ownership ────────────────────────────────
        elif has_complex and acct_type == "business":
            n_rels = rng.randint(2, 5)
            for _ in range(n_rels):
                rel_type = choose_rel_type(acct_type, rng)

                # ~20 % chance the related entity is sanctioned
                if rng.random() < 0.20 and sanctioned_entities:
                    sanc_entity = rng.choice(sanctioned_entities)
                    related_name = sanc_entity.get("name", faker.company())
                    related_sanc_eid = sanc_entity.get("entity_id")
                    all_rels.append(_make_rel(
                        rel_counter, acid, rel_type, related_name,
                        0, 1, related_sanc_eid, "synthetic",
                    ))
                else:
                    related_name = faker.name() if rel_type in ("family", "associate") else faker.company()
                    all_rels.append(_make_rel(
                        rel_counter, acid, rel_type, related_name,
                        0, 0, None, "synthetic",
                    ))
                rel_counter += 1

        # ── 3. ~5 % of ordinary accounts: indirect exposure ───────────────────
        elif rng.random() < 0.05:
            for _ in range(rng.randint(1, 3)):
                rel_type     = choose_rel_type(acct_type, rng)
                related_name = faker.name() if acct_type == "individual" else faker.company()
                all_rels.append(_make_rel(
                    rel_counter, acid, rel_type, related_name,
                    0, 0, None, "synthetic",
                ))
                rel_counter += 1

        # ── 4. Remaining accounts: 30 % get 1-2 benign relationships ──────────
        elif rng.random() < 0.30:
            for _ in range(rng.randint(1, 2)):
                rel_type     = choose_rel_type(acct_type, rng)
                related_name = faker.name() if rel_type in ("family", "associate") else faker.company()
                all_rels.append(_make_rel(
                    rel_counter, acid, rel_type, related_name,
                    0, 0, None, "synthetic",
                ))
                rel_counter += 1

        # else: no relationships (70 % of ordinary accounts)

    return all_rels


# ── Wallet builder ────────────────────────────────────────────────────────────

def _parse_crypto_addresses(raw: str) -> list[str]:
    """
    Parse the crypto_addresses field from sanctioned_entities.csv.
    Addresses may be semicolon-separated.
    """
    if not raw:
        return []
    return [a.strip() for a in raw.split(";") if a.strip()]


def _chain_from_address(addr: str) -> str:
    if addr.startswith("0x"):
        return "Ethereum"
    elif addr.startswith("bc1"):
        return "Bitcoin"
    elif addr.startswith("1") or addr.startswith("3"):
        return "Bitcoin"
    return "Unknown"


def build_wallets(accounts: list[dict],
                  sanctioned_entities: list[dict],
                  rng: random.Random) -> list[dict]:
    """
    Build all wallets rows.

    Returns a flat list of wallet dicts.
    """
    # Index sanctioned entities by entity_id
    sanc_by_id: dict[str, dict] = {
        e["entity_id"]: e for e in sanctioned_entities if e.get("entity_id")
    }

    all_wallets: list[dict] = []
    wallet_counter = 1

    for acct in accounts:
        acid      = acct["account_id"]
        sanc_eid  = acct.get("sanctioned_entity_id")
        is_pep    = int(acct.get("is_pep", 0))
        risk_band = acct.get("initial_risk_band", "LOW")

        is_high_risk = bool(sanc_eid or is_pep or risk_band in ("HIGH", "CRITICAL"))
        wallet_prob  = WALLET_PROB_HIGH if is_high_risk else WALLET_PROB_NORMAL

        if rng.random() >= wallet_prob:
            continue  # no wallet for this account

        # ── Sanctioned account: try to use real crypto_addresses ──────────────
        if sanc_eid and sanc_eid in sanc_by_id:
            entity  = sanc_by_id[sanc_eid]
            addrs   = _parse_crypto_addresses(entity.get("crypto_addresses", ""))

            if addrs:
                for addr in addrs:
                    chain = _chain_from_address(addr)
                    all_wallets.append({
                        "wallet_id":             f"WLT-{wallet_counter:07d}",
                        "account_id":            acid,
                        "wallet_address":        addr,
                        "chain":                 chain,
                        "is_sanctioned":         1,
                        "sanctioned_entity_id":  sanc_eid,
                        "hops_to_sanctioned":    0,
                    })
                    wallet_counter += 1
                continue  # done for this sanctioned account

        # ── Generate a synthetic address ──────────────────────────────────────
        addr, chain = generate_synthetic_address(rng)

        if is_high_risk:
            hops = rng.randint(1, 3)
        else:
            hops = None  # clean accounts: NULL

        all_wallets.append({
            "wallet_id":             f"WLT-{wallet_counter:07d}",
            "account_id":            acid,
            "wallet_address":        addr,
            "chain":                 chain,
            "is_sanctioned":         0,
            "sanctioned_entity_id":  None,
            "hops_to_sanctioned":    hops,
        })
        wallet_counter += 1

    return all_wallets


# ── DB insertion ──────────────────────────────────────────────────────────────

REL_INSERT_SQL = """
INSERT OR IGNORE INTO account_relationships (
    relationship_id, account_id, related_entity_name,
    relationship_type,
    related_is_pep, related_is_sanctioned,
    related_sanctioned_entity_id, source
) VALUES (
    :relationship_id, :account_id, :related_entity_name,
    :relationship_type,
    :related_is_pep, :related_is_sanctioned,
    :related_sanctioned_entity_id, :source
)
"""

WALLET_INSERT_SQL = """
INSERT OR IGNORE INTO wallets (
    wallet_id, account_id, wallet_address,
    chain, is_sanctioned,
    sanctioned_entity_id, hops_to_sanctioned
) VALUES (
    :wallet_id, :account_id, :wallet_address,
    :chain, :is_sanctioned,
    :sanctioned_entity_id, :hops_to_sanctioned
)
"""

# Chunk size for executemany to avoid excessively large transactions
CHUNK_SIZE = 5_000


def insert_in_chunks(conn: sqlite3.Connection,
                     sql: str,
                     rows: list[dict],
                     logger: logging.Logger,
                     label: str) -> int:
    total = 0
    cur   = conn.cursor()
    for i in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[i:i + CHUNK_SIZE]
        cur.executemany(sql, chunk)
        conn.commit()
        total += cur.rowcount
        logger.info(f"  {label}: inserted chunk [{i}:{i + len(chunk)}] ({cur.rowcount} rows)")
    return total


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 03_generate_relationships.py started ===")

    # ── Check progress ────────────────────────────────────────────────────────
    progress = load_progress()
    rel_done    = progress.get("relationships_complete", False)
    wallet_done = progress.get("wallets_complete", False)

    if rel_done and wallet_done:
        logger.info("relationships_complete and wallets_complete are both true — nothing to do.")
        print("Relationships and wallets already generated. Exiting.")
        return

    relationships_source = progress.get("relationships_source")   # e.g. "real_ftm" or None

    # ── Load reference data ───────────────────────────────────────────────────
    logger.info("Loading reference data …")
    sanctioned_entities = read_csv(SANCTIONED_CSV)
    ftm_rels            = read_csv(SANC_REL_CSV) if relationships_source == "real_ftm" else []
    logger.info(f"  sanctioned_entities: {len(sanctioned_entities)} rows")
    logger.info(f"  sanctioned_relationships (FTM): {len(ftm_rels)} rows")

    # ── Load accounts from DB ─────────────────────────────────────────────────
    logger.info(f"Loading accounts from database: {DB_PATH} …")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row

    cur = conn.cursor()
    cur.execute("""
        SELECT account_id, account_type, sanctioned_entity_id,
               is_pep, has_complex_ownership, initial_risk_band
        FROM accounts
    """)
    accounts = [dict(row) for row in cur.fetchall()]
    conn.row_factory = None
    logger.info(f"  {len(accounts)} accounts loaded.")

    if not accounts:
        logger.error("No accounts found in the database. Run 02_generate_accounts.py first.")
        conn.close()
        sys.exit(1)

    # ── Faker ─────────────────────────────────────────────────────────────────
    faker = load_faker()

    # ── RNG ───────────────────────────────────────────────────────────────────
    rng = random.Random()

    # ── Relationships ─────────────────────────────────────────────────────────
    if not rel_done:
        logger.info("Building account relationships …")
        rels = build_relationships(
            accounts, sanctioned_entities, ftm_rels,
            relationships_source, faker, rng,
        )
        logger.info(f"  {len(rels)} relationship rows to insert.")

        inserted_rels = insert_in_chunks(conn, REL_INSERT_SQL, rels, logger, "account_relationships")
        logger.info(f"  Total inserted: {inserted_rels} rows.")

        progress["relationships_complete"] = True
        save_progress(progress)
        logger.info("progress.json updated: relationships_complete=true")
    else:
        logger.info("Relationships already complete — skipping.")

    # ── Wallets ───────────────────────────────────────────────────────────────
    if not wallet_done:
        logger.info("Building wallets …")
        wallets = build_wallets(accounts, sanctioned_entities, rng)
        logger.info(f"  {len(wallets)} wallet rows to insert.")

        inserted_wallets = insert_in_chunks(conn, WALLET_INSERT_SQL, wallets, logger, "wallets")
        logger.info(f"  Total inserted: {inserted_wallets} rows.")

        progress["wallets_complete"] = True
        save_progress(progress)
        logger.info("progress.json updated: wallets_complete=true")
    else:
        logger.info("Wallets already complete — skipping.")

    conn.close()
    logger.info("Database connection closed.")
    logger.info("=== 03_generate_relationships.py finished successfully ===")
    print("Done. Relationships and wallets written to database.")


if __name__ == "__main__":
    main()
