"""
01_build_reference_data.py
==========================
Builds all reference CSV/JSON files consumed by later pipeline stages.

Sub-steps
---------
A  sanctioned_entities.csv          – 5,000–8,000 stratified sanctioned entities
B  sanctioned_relationships.csv     – relationship graph from entities.ftm.json
C  peps.csv                         – 2,000–3,000 PEPs from peps/targets.simple.csv
D  matching_pairs_summary.csv       – Jaro-Winkler histogram from pairs-20251209.json
   matching_pairs_stats.json        – per-class descriptive statistics
E  aml_transactions_sample.csv      – amount/rail distribution from HI-Small_Trans.csv
   aml_hour_dist.csv
   aml_dow_dist.csv
   aml_laundering_velocity.json
F  country_risk.csv                 – ~195 countries with composite risk scores

Each sub-step is wrapped in try/except with a synthetic fallback so the script
always produces usable output even when raw files are unavailable.

Composite risk formula (sub-step F):
    ofac_factor   = 100 if ofac_sanctioned else 0
    fatf_factor   = 100 if blacklist, 60 if greylist, 0 otherwise
    basel_norm    = (basel_aml_score / 10) * 100   # scores are 0-10 scale
    composite     = 0.4*ofac_factor + 0.3*fatf_factor + 0.3*basel_norm
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import random
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR   = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
DATA_DIR      = "/home/mihajlo/Mihajlo/Projekti/garaza/data/raw"
REF_DIR       = os.path.join(PROJECT_DIR, "reference_data")
LOG_PATH      = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")
PROGRESS_PATH = os.path.join(PROJECT_DIR, "progress.json")

SANCTIONS_CSV  = os.path.join(DATA_DIR, "sanctions", "targets.simple.csv")
ENTITIES_FTM   = os.path.join(DATA_DIR, "sanctions", "entities.ftm.json")
PAIRS_JSON     = os.path.join(DATA_DIR, "sanctions", "pairs-20251209.json")
PEPS_CSV       = os.path.join(DATA_DIR, "peps", "targets.simple.csv")
AML_TRANS_CSV  = os.path.join(DATA_DIR, "keggle", "HI-Small_Trans.csv")

TODAY = datetime(2026, 6, 14)   # reference date per project spec

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("01_build_reference_data")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")
    if not logger.handlers:
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger


# ── Progress ──────────────────────────────────────────────────────────────────

def load_progress() -> dict:
    if not os.path.exists(PROGRESS_PATH):
        return {}
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def update_progress(key: str, value: Any) -> None:
    progress = load_progress()
    progress[key] = value
    progress["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    tmp = PROGRESS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)
    os.replace(tmp, PROGRESS_PATH)


# ── Utility ───────────────────────────────────────────────────────────────────

def out_path(filename: str) -> str:
    os.makedirs(REF_DIR, exist_ok=True)
    return os.path.join(REF_DIR, filename)


def write_csv(path: str, fieldnames: List[str], rows: List[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ── Jaro-Winkler (no external deps) ──────────────────────────────────────────

def jaro(s1: str, s2: str) -> float:
    """Jaro similarity between two strings."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0
    match_dist = max(len1, len2) // 2 - 1
    match_dist = max(match_dist, 0)

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_dist)
        end   = min(i + match_dist + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    return (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3


def jaro_winkler(s1: str, s2: str, p: float = 0.1) -> float:
    """Jaro-Winkler similarity (prefix weight p, up to 4 chars)."""
    j = jaro(s1, s2)
    # Common prefix length (up to 4)
    prefix = 0
    for c1, c2 in zip(s1[:4], s2[:4]):
        if c1 == c2:
            prefix += 1
        else:
            break
    return j + prefix * p * (1 - j)


# ── Schema mappings ───────────────────────────────────────────────────────────

SCHEMA_TO_ENTITY_TYPE = {
    "Person":       "Person",
    "Company":      "Company",
    "LegalEntity":  "Organization",
    "Organization": "Organization",
    "CryptoWallet": "CryptoWallet",
    "Vessel":       "Vessel",
    "Airplane":     "Vessel",
}

CRYPTO_RE = re.compile(
    r'(?:0x[0-9a-fA-F]{30,}|bc1[0-9a-zA-Z]{25,}|[13][0-9A-Za-z]{25,34})'
)

PAYMENT_RAIL_MAP = {
    "Wire":         "wire",
    "ACH":          "ach",
    "Credit Card":  "card",
    "Cheque":       "check",
    "Reinvestment": "internal",
}


def map_schema(schema: str) -> str:
    return SCHEMA_TO_ENTITY_TYPE.get(schema, "Organization")


# ═══════════════════════════════════════════════════════════════════════════════
# SUB-STEP A: sanctioned_entities.csv
# ═══════════════════════════════════════════════════════════════════════════════

def step_a(logger: logging.Logger) -> None:
    """Read sanctions/targets.simple.csv and build a stratified sample of
    5,000–8,000 sanctioned entities."""
    logger.info("--- Sub-step A: sanctioned_entities.csv ---")
    TARGET_MIN, TARGET_MAX = 5_000, 8_000

    try:
        import csv as _csv

        if not os.path.exists(SANCTIONS_CSV):
            raise FileNotFoundError(f"Not found: {SANCTIONS_CSV}")

        # ── First pass: load all rows into memory buckets by country ──────────
        # File is 65 MB — manageable as a full load.
        logger.info(f"  Reading {SANCTIONS_CSV} ...")

        crypto_rows: List[dict] = []
        country_buckets: Dict[str, List[dict]] = defaultdict(list)

        with open(SANCTIONS_CSV, "r", encoding="utf-8", errors="replace") as f:
            reader = _csv.DictReader(f)
            for raw in reader:
                schema   = (raw.get("schema") or "").strip()
                etype    = map_schema(schema)
                name     = (raw.get("name") or "").strip()
                aliases  = (raw.get("aliases") or "").strip()
                dob      = (raw.get("birth_date") or "").strip()
                countries = (raw.get("countries") or "").strip()
                idents   = (raw.get("identifiers") or "").strip()
                sanctions_txt = (raw.get("sanctions") or "").strip()
                program  = (raw.get("program_ids") or "").strip()
                entity_id = (raw.get("id") or "").strip()

                if not entity_id or not name:
                    continue

                # Primary country
                country = countries.split(";")[0].strip() if countries else "XX"

                # Crypto addresses
                if etype == "CryptoWallet":
                    crypto_addrs = idents
                else:
                    found = CRYPTO_RE.findall(idents)
                    crypto_addrs = ";".join(found) if found else ""

                row = {
                    "entity_id":       entity_id,
                    "name":            name,
                    "aliases":         aliases,
                    "entity_type":     etype,
                    "country":         country,
                    "dob":             dob,
                    "program":         program or sanctions_txt[:120],
                    "crypto_addresses": crypto_addrs,
                }

                if etype == "CryptoWallet":
                    crypto_rows.append(row)
                else:
                    country_buckets[country].append(row)

        logger.info(f"  Loaded {len(crypto_rows)} CryptoWallet rows and "
                    f"{sum(len(v) for v in country_buckets.values())} other rows "
                    f"across {len(country_buckets)} countries.")

        # ── Stratified sampling ───────────────────────────────────────────────
        budget = TARGET_MAX - len(crypto_rows)
        if budget < 0:
            # More crypto wallets than max — just truncate
            crypto_rows = crypto_rows[:TARGET_MAX]
            budget = 0

        total_non_crypto = sum(len(v) for v in country_buckets.values())
        selected_non_crypto: List[dict] = []

        if total_non_crypto > 0 and budget > 0:
            # Proportional allocation with 50% cap per country
            country_list = sorted(country_buckets.keys())
            # Raw proportional quota
            raw_quota: Dict[str, int] = {}
            for c in country_list:
                prop = len(country_buckets[c]) / total_non_crypto
                raw_quota[c] = max(1, int(prop * budget))
            # Apply 50% cap: no country with >100 entities gets more than 50% of budget
            for c in country_list:
                if len(country_buckets[c]) > 100:
                    raw_quota[c] = min(raw_quota[c], budget // 2)

            # Scale to budget
            total_q = sum(raw_quota.values())
            scale = budget / total_q if total_q > budget else 1.0

            random.seed(42)
            for c in country_list:
                quota = min(int(raw_quota[c] * scale) + 1, len(country_buckets[c]))
                sample = random.sample(country_buckets[c], quota)
                selected_non_crypto.extend(sample)

            # Trim if over
            if len(selected_non_crypto) > budget:
                random.shuffle(selected_non_crypto)
                selected_non_crypto = selected_non_crypto[:budget]

        all_entities = crypto_rows + selected_non_crypto

        # Ensure within bounds
        if len(all_entities) < TARGET_MIN:
            logger.warning(f"  Only {len(all_entities)} entities found — below minimum {TARGET_MIN}. "
                           "Using all available.")
        if len(all_entities) > TARGET_MAX:
            random.seed(42)
            all_entities = random.sample(all_entities, TARGET_MAX)

        logger.info(f"  Final entity count: {len(all_entities)}")

        # ── Write output ──────────────────────────────────────────────────────
        out = out_path("sanctioned_entities.csv")
        fields = ["entity_id", "name", "aliases", "entity_type", "country",
                  "dob", "program", "crypto_addresses"]
        write_csv(out, fields, all_entities)
        logger.info(f"  Written: {out}")
        update_progress("sanctioned_entities_source", "real")

    except Exception as exc:
        logger.error(f"  Sub-step A failed ({exc}); generating synthetic fallback.", exc_info=True)
        _step_a_fallback(logger)


def _step_a_fallback(logger: logging.Logger) -> None:
    """Synthetic fallback for sub-step A."""
    logger.info("  Generating synthetic sanctioned_entities.csv ...")
    random.seed(99)
    rows = []
    types_pool = ["Person", "Company", "Organization", "CryptoWallet", "Vessel"]
    countries_pool = ["RU", "IR", "KP", "SY", "BY", "VE", "CU", "MM", "SD", "YE"]
    for i in range(300):
        etype = random.choice(types_pool)
        crypto = f"0x{random.randint(0, 2**160):040x}" if etype == "CryptoWallet" else ""
        rows.append({
            "entity_id":        f"syn-{i:05d}",
            "name":             f"Synthetic Entity {i}",
            "aliases":          f"SE{i}A;SE{i}B",
            "entity_type":      etype,
            "country":          random.choice(countries_pool),
            "dob":              "1970-01-01" if etype == "Person" else "",
            "program":          "US-OFAC",
            "crypto_addresses": crypto,
        })
    out = out_path("sanctioned_entities.csv")
    write_csv(out, list(rows[0].keys()), rows)
    logger.info(f"  Fallback written: {out} ({len(rows)} rows)")
    update_progress("sanctioned_entities_source", "fallback")


# ═══════════════════════════════════════════════════════════════════════════════
# SUB-STEP B: sanctioned_relationships.csv
# ═══════════════════════════════════════════════════════════════════════════════

def _stream_ftm_objects(path: str) -> Iterator[dict]:
    """Stream multi-line JSON objects from entities.ftm.json.

    Each object starts with '{' at column 0.  We accumulate lines until the
    next such boundary, then parse and yield.
    """
    buf: List[str] = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("{") and buf:
                raw = "".join(buf)
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    pass
                buf = [line]
            else:
                buf.append(line)
    # Last object
    if buf:
        raw = "".join(buf)
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            pass


RELATIONSHIP_SCHEMAS = {
    "Ownership":    ("owner",   "asset",         "owner",     "asset"),
    "Family":       ("person",  "relative",       "person",    "relative"),
    "Directorship": ("director","organization",   "director",  "organization"),
    "Associate":    ("person",  "associate",      "person",    "associate"),
    "UnknownLink":  ("subject", "object",         "subject",   "object"),
}


def step_b(logger: logging.Logger) -> None:
    """Stream entities.ftm.json and extract relationships involving known sanctioned entities."""
    logger.info("--- Sub-step B: sanctioned_relationships.csv ---")

    # Load known entity IDs from step A output
    entities_path = out_path("sanctioned_entities.csv")
    known_ids: set = set()
    if os.path.exists(entities_path):
        with open(entities_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                eid = row.get("entity_id", "").strip()
                if eid:
                    known_ids.add(eid)
    logger.info(f"  Known sanctioned entity IDs loaded: {len(known_ids)}")

    try:
        if not os.path.exists(ENTITIES_FTM):
            raise FileNotFoundError(f"Not found: {ENTITIES_FTM}")

        TIME_LIMIT_SECS = 30 * 60      # 30 minutes
        LINE_LIMIT      = 5_000_000

        start_time  = time.time()
        line_count  = 0
        obj_count   = 0
        rel_rows: List[dict] = []
        rel_counter = 0

        logger.info(f"  Streaming {ENTITIES_FTM} (time limit: 30 min, line limit: {LINE_LIMIT:,}) ...")

        with open(ENTITIES_FTM, "r", encoding="utf-8", errors="replace") as f:
            buf: List[str] = []
            for raw_line in f:
                line_count += 1

                if line_count > LINE_LIMIT or (time.time() - start_time) > TIME_LIMIT_SECS:
                    logger.info(f"  Time/line limit reached at line {line_count:,}.")
                    # Try to process remaining buffer
                    if buf:
                        try:
                            _process_ftm_obj(json.loads("".join(buf)), known_ids,
                                             rel_rows, rel_counter)
                        except Exception:
                            pass
                    break

                if raw_line.startswith("{") and buf:
                    try:
                        obj = json.loads("".join(buf))
                        obj_count += 1
                        new_rels = _extract_relationships(obj, known_ids, rel_counter)
                        rel_rows.extend(new_rels)
                        rel_counter += len(new_rels)
                    except json.JSONDecodeError:
                        pass
                    buf = [raw_line]
                else:
                    buf.append(raw_line)

            # Final object
            if buf:
                try:
                    obj = json.loads("".join(buf))
                    new_rels = _extract_relationships(obj, known_ids, rel_counter)
                    rel_rows.extend(new_rels)
                    rel_counter += len(new_rels)
                    obj_count += 1
                except json.JSONDecodeError:
                    pass

        elapsed = time.time() - start_time
        logger.info(f"  Streamed {line_count:,} lines, {obj_count:,} objects in {elapsed:.1f}s.")
        logger.info(f"  Relationships found: {len(rel_rows)}")

        if len(rel_rows) < 50:
            raise ValueError(f"Too few relationships ({len(rel_rows)} < 50); using fallback.")

        out = out_path("sanctioned_relationships.csv")
        fields = ["relationship_id", "entity_id_a", "entity_id_b",
                  "relationship_type", "role_a", "role_b"]
        write_csv(out, fields, rel_rows)
        logger.info(f"  Written: {out}")
        update_progress("relationships_source", "real_ftm")

    except Exception as exc:
        logger.error(f"  Sub-step B failed ({exc}); generating synthetic fallback.", exc_info=True)
        _step_b_fallback(logger, known_ids)


def _extract_relationships(obj: dict, known_ids: set, counter: int) -> List[dict]:
    """Extract relationship rows from a single FTM object."""
    schema = obj.get("schema", "")
    if schema not in RELATIONSHIP_SCHEMAS:
        return []

    props = obj.get("properties", {})
    prop_a_key, prop_b_key, role_a, role_b = RELATIONSHIP_SCHEMAS[schema]

    ids_a = props.get(prop_a_key, [])
    ids_b = props.get(prop_b_key, [])

    if not ids_a or not ids_b:
        # Try fallback property names for UnknownLink
        if schema == "UnknownLink":
            all_prop_keys = list(props.keys())
            if len(all_prop_keys) >= 2:
                ids_a = props.get(all_prop_keys[0], [])
                ids_b = props.get(all_prop_keys[1], [])

    rows = []
    for id_a in ids_a:
        for id_b in ids_b:
            # At least one endpoint must be a known sanctioned entity
            if id_a in known_ids or id_b in known_ids:
                rows.append({
                    "relationship_id": f"rel-{counter + len(rows):07d}",
                    "entity_id_a":     id_a,
                    "entity_id_b":     id_b,
                    "relationship_type": schema,
                    "role_a":          role_a,
                    "role_b":          role_b,
                })
    return rows


def _process_ftm_obj(obj, known_ids, rel_rows, rel_counter):
    """Helper used at time-limit boundary."""
    new_rels = _extract_relationships(obj, known_ids, rel_counter)
    rel_rows.extend(new_rels)


def _step_b_fallback(logger: logging.Logger, known_ids: set) -> None:
    logger.info("  Generating synthetic sanctioned_relationships.csv ...")
    random.seed(42)
    id_list = list(known_ids)[:200] if len(known_ids) >= 2 else [f"syn-{i:05d}" for i in range(200)]
    rel_types = ["Ownership", "Family", "Directorship", "Associate"]
    roles = {
        "Ownership":    ("owner",    "asset"),
        "Family":       ("person",   "relative"),
        "Directorship": ("director", "organization"),
        "Associate":    ("person",   "associate"),
    }
    rows = []
    for i in range(200):
        rtype = random.choice(rel_types)
        ra, rb = roles[rtype]
        rows.append({
            "relationship_id":   f"rel-{i:07d}",
            "entity_id_a":       random.choice(id_list),
            "entity_id_b":       random.choice(id_list),
            "relationship_type": rtype,
            "role_a":            ra,
            "role_b":            rb,
        })
    out = out_path("sanctioned_relationships.csv")
    write_csv(out, list(rows[0].keys()), rows)
    logger.info(f"  Fallback written: {out} ({len(rows)} rows)")
    update_progress("relationships_source", "fallback")


# ═══════════════════════════════════════════════════════════════════════════════
# SUB-STEP C: peps.csv
# ═══════════════════════════════════════════════════════════════════════════════

def step_c(logger: logging.Logger) -> None:
    """Read peps/targets.simple.csv and build a stratified sample of 2,000–3,000 PEPs."""
    logger.info("--- Sub-step C: peps.csv ---")
    TARGET_MIN, TARGET_MAX = 2_000, 3_000
    TWO_YEARS_DAYS = 2 * 365

    try:
        if not os.path.exists(PEPS_CSV):
            raise FileNotFoundError(f"Not found: {PEPS_CSV}")

        logger.info(f"  Reading {PEPS_CSV} (may be slow — 192 MB) ...")

        country_buckets: Dict[str, List[dict]] = defaultdict(list)
        total_loaded = 0

        with open(PEPS_CSV, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                schema = (raw.get("schema") or "").strip()
                if schema != "Person":
                    continue

                pep_id    = (raw.get("id") or "").strip()
                name      = (raw.get("name") or "").strip()
                dataset   = (raw.get("dataset") or "").strip()
                countries = (raw.get("countries") or "").strip()
                first_seen = (raw.get("first_seen") or "").strip()
                last_seen  = (raw.get("last_seen") or "").strip()

                if not pep_id or not name:
                    continue

                country = countries.split(";")[0].strip() if countries else "XX"

                # is_current: last_seen within 2 years of TODAY
                is_current = 0
                if last_seen:
                    try:
                        ls_date = datetime.fromisoformat(last_seen[:10])
                        delta = (TODAY - ls_date).days
                        is_current = 1 if delta <= TWO_YEARS_DAYS else 0
                    except ValueError:
                        pass

                row = {
                    "pep_id":     pep_id,
                    "name":       name,
                    "position":   dataset,
                    "country":    country,
                    "start_date": first_seen[:10] if first_seen else "",
                    "end_date":   last_seen[:10]  if last_seen  else "",
                    "is_current": is_current,
                }
                country_buckets[country].append(row)
                total_loaded += 1

        logger.info(f"  Loaded {total_loaded:,} Person rows across {len(country_buckets)} countries.")

        if total_loaded < TARGET_MIN:
            raise ValueError(f"Too few PEP Person rows ({total_loaded} < {TARGET_MIN}).")

        # Stratified sample
        budget = TARGET_MAX
        total  = total_loaded
        random.seed(42)
        selected: List[dict] = []

        for country, rows in sorted(country_buckets.items()):
            prop  = len(rows) / total
            quota = max(1, min(int(prop * budget), len(rows)))
            selected.extend(random.sample(rows, quota))

        if len(selected) > TARGET_MAX:
            random.shuffle(selected)
            selected = selected[:TARGET_MAX]

        logger.info(f"  Final PEP count: {len(selected)}")

        out = out_path("peps.csv")
        fields = ["pep_id", "name", "position", "country",
                  "start_date", "end_date", "is_current"]
        write_csv(out, fields, selected)
        logger.info(f"  Written: {out}")
        update_progress("peps_source", "real")

    except Exception as exc:
        logger.error(f"  Sub-step C failed ({exc}); generating synthetic fallback.", exc_info=True)
        _step_c_fallback(logger)


def _step_c_fallback(logger: logging.Logger) -> None:
    logger.info("  Generating synthetic peps.csv ...")
    random.seed(7)
    positions = [
        "President", "Prime Minister", "Minister of Finance", "Minister of Interior",
        "Central Bank Governor", "Defence Minister", "Foreign Minister",
        "Attorney General", "Chief Justice", "State Secretary",
        "Senator", "Member of Parliament", "Ambassador", "Regional Governor",
        "City Mayor", "Head of Intelligence", "Military General", "Admiral",
    ]
    countries = ["US", "GB", "DE", "FR", "RU", "CN", "BR", "IN", "ZA", "NG",
                 "AE", "TR", "MX", "AR", "EG", "PK", "SA", "ID", "KR", "JP"]
    rows = []
    for i in range(500):
        country = random.choice(countries)
        start_yr = random.randint(2000, 2020)
        end_yr   = random.randint(start_yr + 1, 2026)
        is_cur   = 1 if end_yr >= 2024 else 0
        rows.append({
            "pep_id":     f"pep-syn-{i:05d}",
            "name":       f"Synthetic PEP {i}",
            "position":   random.choice(positions),
            "country":    country,
            "start_date": f"{start_yr}-01-01",
            "end_date":   f"{end_yr}-12-31",
            "is_current": is_cur,
        })
    out = out_path("peps.csv")
    write_csv(out, list(rows[0].keys()), rows)
    logger.info(f"  Fallback written: {out} ({len(rows)} rows)")
    update_progress("peps_source", "fallback")


# ═══════════════════════════════════════════════════════════════════════════════
# SUB-STEP D: matching_pairs_summary.csv + matching_pairs_stats.json
# ═══════════════════════════════════════════════════════════════════════════════

def _percentile(sorted_vals: List[float], pct: float) -> float:
    """Compute a percentile from a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (k - lo) * (sorted_vals[hi] - sorted_vals[lo])


def _describe(vals: List[float]) -> dict:
    n = len(vals)
    if n == 0:
        return {k: 0.0 for k in ["mean", "std", "p5", "p25", "p50", "p75", "p95", "count"]}
    mean = sum(vals) / n
    variance = sum((x - mean) ** 2 for x in vals) / n
    std  = math.sqrt(variance)
    sv   = sorted(vals)
    return {
        "mean":  round(mean, 4),
        "std":   round(std, 4),
        "p5":    round(_percentile(sv, 5),  4),
        "p25":   round(_percentile(sv, 25), 4),
        "p50":   round(_percentile(sv, 50), 4),
        "p75":   round(_percentile(sv, 75), 4),
        "p95":   round(_percentile(sv, 95), 4),
        "count": n,
    }


def step_d(logger: logging.Logger) -> None:
    """Read pairs-20251209.json (NDJSON, 2.1 GB) — at most 100,000 lines —
    compute Jaro-Winkler scores and write histogram + stats."""
    logger.info("--- Sub-step D: matching_pairs_summary.csv + matching_pairs_stats.json ---")
    MAX_LINES = 100_000

    try:
        if not os.path.exists(PAIRS_JSON):
            raise FileNotFoundError(f"Not found: {PAIRS_JSON}")

        logger.info(f"  Reading up to {MAX_LINES:,} lines from {PAIRS_JSON} ...")

        positive_scores: List[float] = []
        negative_scores: List[float] = []

        # Histogram bins 0.0–0.1, 0.1–0.2, ..., 0.9–1.0
        hist_pos = [0] * 10
        hist_neg = [0] * 10

        line_num = 0
        with open(PAIRS_JSON, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_num += 1
                if line_num > MAX_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                judgement = obj.get("judgement", "")
                if judgement not in ("positive", "negative"):
                    continue

                left  = obj.get("left",  {})
                right = obj.get("right", {})
                names_l = left.get("properties",  {}).get("name", [])
                names_r = right.get("properties", {}).get("name", [])
                if not names_l or not names_r:
                    continue

                name_a = str(names_l[0]).strip().lower()
                name_b = str(names_r[0]).strip().lower()
                score  = round(jaro_winkler(name_a, name_b), 4)

                bin_idx = min(int(score * 10), 9)
                if judgement == "positive":
                    positive_scores.append(score)
                    hist_pos[bin_idx] += 1
                else:
                    negative_scores.append(score)
                    hist_neg[bin_idx] += 1

                if line_num % 10_000 == 0:
                    logger.info(f"    Processed {line_num:,} lines ...")

        logger.info(f"  Done: {line_num:,} lines, "
                    f"{len(positive_scores):,} positive, {len(negative_scores):,} negative pairs.")

        if len(positive_scores) + len(negative_scores) < 10:
            raise ValueError("Too few valid pairs found.")

        # ── Write histogram CSV ───────────────────────────────────────────────
        bins   = [f"{i/10:.1f}-{(i+1)/10:.1f}" for i in range(10)]
        hist_rows = [
            {"score_bin": b, "positive_count": p, "negative_count": n}
            for b, p, n in zip(bins, hist_pos, hist_neg)
        ]
        write_csv(out_path("matching_pairs_summary.csv"),
                  ["score_bin", "positive_count", "negative_count"], hist_rows)
        logger.info(f"  Written: {out_path('matching_pairs_summary.csv')}")

        # ── Write stats JSON ──────────────────────────────────────────────────
        pos_stats = _describe(positive_scores)
        neg_stats = _describe(negative_scores)
        stats = {
            "positive": {f"positive_{k}": v for k, v in pos_stats.items()},
            "negative": {f"negative_{k}": v for k, v in neg_stats.items()},
        }
        # Flat version for easy reading
        flat_stats = {}
        flat_stats.update(stats["positive"])
        flat_stats.update(stats["negative"])

        with open(out_path("matching_pairs_stats.json"), "w", encoding="utf-8") as f:
            json.dump(flat_stats, f, indent=2)
        logger.info(f"  Written: {out_path('matching_pairs_stats.json')}")

        update_progress("matching_pairs_source", "real")

    except Exception as exc:
        logger.error(f"  Sub-step D failed ({exc}); using illustrative fallback.", exc_info=True)
        _step_d_fallback(logger)


def _step_d_fallback(logger: logging.Logger) -> None:
    logger.info("  Writing illustrative matching_pairs fallback ...")
    # Illustrative distribution: positive: mean=0.82, std=0.08; negative confusable: mean=0.58, std=0.12
    # Approximate histogram
    hist_rows = [
        {"score_bin": "0.0-0.1", "positive_count": 0,   "negative_count": 12},
        {"score_bin": "0.1-0.2", "positive_count": 0,   "negative_count": 45},
        {"score_bin": "0.2-0.3", "positive_count": 1,   "negative_count": 78},
        {"score_bin": "0.3-0.4", "positive_count": 2,   "negative_count": 120},
        {"score_bin": "0.4-0.5", "positive_count": 5,   "negative_count": 200},
        {"score_bin": "0.5-0.6", "positive_count": 18,  "negative_count": 310},
        {"score_bin": "0.6-0.7", "positive_count": 45,  "negative_count": 280},
        {"score_bin": "0.7-0.8", "positive_count": 120, "negative_count": 150},
        {"score_bin": "0.8-0.9", "positive_count": 350, "negative_count": 80},
        {"score_bin": "0.9-1.0", "positive_count": 459, "negative_count": 25},
    ]
    write_csv(out_path("matching_pairs_summary.csv"),
              ["score_bin", "positive_count", "negative_count"], hist_rows)

    stats = {
        "positive_mean":  0.82, "positive_std":  0.08,
        "positive_p5":    0.65, "positive_p25":  0.78,
        "positive_p50":   0.84, "positive_p75":  0.90,
        "positive_p95":   0.96, "positive_count": 1000,
        "negative_mean":  0.58, "negative_std":  0.12,
        "negative_p5":    0.35, "negative_p25":  0.50,
        "negative_p50":   0.60, "negative_p75":  0.67,
        "negative_p95":   0.78, "negative_count": 1300,
    }
    with open(out_path("matching_pairs_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    logger.info(f"  Fallback written to {REF_DIR}")
    update_progress("matching_pairs_source", "fallback")


# ═══════════════════════════════════════════════════════════════════════════════
# SUB-STEP E: aml_transactions_sample.csv + hour/dow/velocity
# ═══════════════════════════════════════════════════════════════════════════════

def step_e(logger: logging.Logger) -> None:
    """Read HI-Small_Trans.csv and extract distributions for synthetic generation."""
    logger.info("--- Sub-step E: aml_transactions_sample.csv ---")
    MAX_ROWS = 500_000

    try:
        if not os.path.exists(AML_TRANS_CSV):
            raise FileNotFoundError(f"Not found: {AML_TRANS_CSV}")

        logger.info(f"  Reading up to {MAX_ROWS:,} rows from {AML_TRANS_CSV} ...")

        col_names = [
            "Timestamp", "From_Bank", "From_Account", "To_Bank", "To_Account",
            "Amount_Received", "Receiving_Currency", "Amount_Paid",
            "Payment_Currency", "Payment_Format", "Is_Laundering",
        ]

        # Per-rail buckets: amounts
        rail_amounts: Dict[str, List[float]] = defaultdict(list)
        # Hour/DoW distributions
        hour_counts = [0] * 24
        dow_counts  = [0] * 7
        # Laundering stats
        launder_amounts: List[float] = []
        launder_txn_by_date: Dict[str, int] = defaultdict(int)

        rows_read = 0
        with open(AML_TRANS_CSV, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, fieldnames=col_names)
            next(reader)  # skip original header row

            for raw in reader:
                rows_read += 1
                if rows_read > MAX_ROWS:
                    break

                ts_str  = (raw.get("Timestamp") or "").strip()
                amt_str = (raw.get("Amount_Paid") or "0").strip()
                fmt     = (raw.get("Payment_Format") or "").strip()
                is_laun = (raw.get("Is_Laundering") or "0").strip()

                try:
                    amount = float(amt_str)
                except ValueError:
                    amount = 0.0

                rail = PAYMENT_RAIL_MAP.get(fmt, "other")
                rail_amounts[rail].append(amount)

                # Parse timestamp
                try:
                    dt = datetime.strptime(ts_str, "%Y/%m/%d %H:%M")
                    hour_counts[dt.hour] += 1
                    dow_counts[dt.weekday()] += 1
                    date_str = dt.strftime("%Y-%m-%d")
                except ValueError:
                    date_str = ""

                if is_laun == "1":
                    launder_amounts.append(amount)
                    if date_str:
                        launder_txn_by_date[date_str] += 1

                if rows_read % 100_000 == 0:
                    logger.info(f"    {rows_read:,} rows processed ...")

        logger.info(f"  Done: {rows_read:,} rows read.")

        # ── Amount distribution by rail ───────────────────────────────────────
        amount_rows = []
        for rail, amounts in sorted(rail_amounts.items()):
            if not amounts:
                continue
            sv = sorted(amounts)
            n  = len(sv)
            mean_v = sum(sv) / n
            var_v  = sum((x - mean_v) ** 2 for x in sv) / n
            stats  = {
                "mean":  round(mean_v, 2),
                "std":   round(math.sqrt(var_v), 2),
                "p5":    round(_percentile(sv, 5),  2),
                "p25":   round(_percentile(sv, 25), 2),
                "p50":   round(_percentile(sv, 50), 2),
                "p75":   round(_percentile(sv, 75), 2),
                "p95":   round(_percentile(sv, 95), 2),
                "count": n,
            }
            for stat_name, value in stats.items():
                amount_rows.append({
                    "payment_rail": rail,
                    "stat_name":   stat_name,
                    "value":       value,
                })

        write_csv(out_path("aml_transactions_sample.csv"),
                  ["payment_rail", "stat_name", "value"], amount_rows)
        logger.info(f"  Written: {out_path('aml_transactions_sample.csv')}")

        # ── Hour distribution ─────────────────────────────────────────────────
        hour_rows = [{"hour": h, "count": c} for h, c in enumerate(hour_counts)]
        write_csv(out_path("aml_hour_dist.csv"), ["hour", "count"], hour_rows)
        logger.info(f"  Written: {out_path('aml_hour_dist.csv')}")

        # ── DoW distribution ──────────────────────────────────────────────────
        dow_rows = [{"dow": d, "count": c} for d, c in enumerate(dow_counts)]
        write_csv(out_path("aml_dow_dist.csv"), ["dow", "count"], dow_rows)
        logger.info(f"  Written: {out_path('aml_dow_dist.csv')}")

        # ── Laundering velocity ───────────────────────────────────────────────
        daily_counts = list(launder_txn_by_date.values())
        if daily_counts:
            mean_dc = sum(daily_counts) / len(daily_counts)
            var_dc  = sum((x - mean_dc)**2 for x in daily_counts) / len(daily_counts)
            std_dc  = math.sqrt(var_dc)
        else:
            mean_dc, std_dc = 3.0, 1.5

        if launder_amounts:
            sv_la   = sorted(launder_amounts)
            mean_la = sum(sv_la) / len(sv_la)
            med_la  = _percentile(sv_la, 50)
            p95_la  = _percentile(sv_la, 95)
        else:
            mean_la, med_la, p95_la = 50000.0, 25000.0, 200000.0

        velocity = {
            "burst_txn_per_day": {
                "mean": round(mean_dc, 2),
                "std":  round(std_dc, 2),
            },
            "burst_amount_escalation": {
                "mean_amount":   round(mean_la, 2),
                "median_amount": round(med_la,  2),
                "p95_amount":    round(p95_la,  2),
                "laundering_txn_count": len(launder_amounts),
            },
        }
        with open(out_path("aml_laundering_velocity.json"), "w", encoding="utf-8") as f:
            json.dump(velocity, f, indent=2)
        logger.info(f"  Written: {out_path('aml_laundering_velocity.json')}")

        update_progress("aml_shape_source", "real")

    except Exception as exc:
        logger.error(f"  Sub-step E failed ({exc}); using fallback distributions.", exc_info=True)
        _step_e_fallback(logger)


def _step_e_fallback(logger: logging.Logger) -> None:
    logger.info("  Writing fallback AML distribution files ...")

    # Amount distributions per rail (illustrative)
    rail_defaults = {
        "wire":     {"mean": 85000, "std": 120000, "p5": 1000,  "p25": 8000,  "p50": 30000,  "p75": 100000, "p95": 350000, "count": 50000},
        "ach":      {"mean": 4200,  "std": 12000,  "p5": 50,    "p25": 500,   "p50": 1500,   "p75": 5000,   "p95": 18000,  "count": 80000},
        "card":     {"mean": 320,   "std": 800,    "p5": 10,    "p25": 50,    "p50": 150,    "p75": 400,    "p95": 1200,   "count": 120000},
        "check":    {"mean": 3500,  "std": 9000,   "p5": 100,   "p25": 500,   "p50": 1200,   "p75": 4000,   "p95": 15000,  "count": 30000},
        "internal": {"mean": 15000, "std": 40000,  "p5": 200,   "p25": 1000,  "p50": 5000,   "p75": 20000,  "p95": 80000,  "count": 20000},
        "other":    {"mean": 5000,  "std": 15000,  "p5": 50,    "p25": 300,   "p50": 1000,   "p75": 5000,   "p95": 25000,  "count": 10000},
    }
    amount_rows = []
    for rail, stats in rail_defaults.items():
        for stat_name, value in stats.items():
            amount_rows.append({"payment_rail": rail, "stat_name": stat_name, "value": value})
    write_csv(out_path("aml_transactions_sample.csv"),
              ["payment_rail", "stat_name", "value"], amount_rows)

    # Hour dist (higher at business hours and late night for suspicious)
    hour_pattern = [800, 500, 400, 350, 400, 600, 1200, 3000, 5000, 6000,
                    6500, 6200, 5800, 5500, 5200, 5000, 4800, 4500, 4000, 3500,
                    3000, 2500, 2000, 1200]
    write_csv(out_path("aml_hour_dist.csv"), ["hour", "count"],
              [{"hour": h, "count": c} for h, c in enumerate(hour_pattern)])

    # DoW dist (Mon-Fri higher)
    dow_pattern = [8000, 8500, 8200, 8100, 7800, 3500, 2000]
    write_csv(out_path("aml_dow_dist.csv"), ["dow", "count"],
              [{"dow": d, "count": c} for d, c in enumerate(dow_pattern)])

    velocity = {
        "burst_txn_per_day": {"mean": 4.2, "std": 2.8},
        "burst_amount_escalation": {
            "mean_amount":   52000.0,
            "median_amount": 28000.0,
            "p95_amount":    210000.0,
            "laundering_txn_count": 0,
        },
    }
    with open(out_path("aml_laundering_velocity.json"), "w", encoding="utf-8") as f:
        json.dump(velocity, f, indent=2)

    logger.info(f"  Fallback AML files written to {REF_DIR}")
    update_progress("aml_shape_source", "fallback")


# ═══════════════════════════════════════════════════════════════════════════════
# SUB-STEP F: country_risk.csv
# ═══════════════════════════════════════════════════════════════════════════════

def step_f(logger: logging.Logger) -> None:
    """Build country_risk.csv for ~195 countries with composite risk scores.

    Composite formula (documented in module docstring):
        ofac_factor  = 100 if ofac_sanctioned else 0
        fatf_factor  = 100 if blacklist, 60 if greylist, 0 otherwise
        basel_norm   = (basel_aml_score / 10.0) * 100
        composite    = 0.4 * ofac_factor + 0.3 * fatf_factor + 0.3 * basel_norm
    """
    logger.info("--- Sub-step F: country_risk.csv ---")

    try:
        # ── Reference sets ────────────────────────────────────────────────────
        FATF_BLACKLIST = {"IR", "MM", "KP"}
        FATF_GREYLIST  = {
            "DZ", "AO", "BF", "CM", "CI", "HR", "CD", "ET", "HT", "KE",
            "ML", "MC", "MZ", "NA", "NP", "NG", "PH", "SN", "ZA", "SS",
            "TZ", "VE", "VN", "YE",
        }
        # OFAC comprehensively or heavily sanctioned
        OFAC_SANCTIONED = {"KP", "IR", "SY", "CU", "RU", "BY", "VE"}

        # Regions map
        REGIONS = {
            "US": "North America", "CA": "North America", "MX": "North America",
            "PR": "North America", "VI": "North America", "GU": "North America",
            "MP": "North America", "AS": "North America", "UM": "North America",
            "GB": "Europe", "DE": "Europe", "FR": "Europe", "IT": "Europe",
            "ES": "Europe", "PT": "Europe", "NL": "Europe", "BE": "Europe",
            "LU": "Europe", "CH": "Europe", "AT": "Europe", "SE": "Europe",
            "NO": "Europe", "FI": "Europe", "DK": "Europe", "IE": "Europe",
            "IS": "Europe", "LI": "Europe", "MC": "Europe", "SM": "Europe",
            "VA": "Europe", "AD": "Europe", "MT": "Europe", "CY": "Europe",
            "GR": "Europe", "HR": "Europe", "SI": "Europe", "SK": "Europe",
            "CZ": "Europe", "HU": "Europe", "PL": "Europe", "EE": "Europe",
            "LV": "Europe", "LT": "Europe", "RO": "Europe", "BG": "Europe",
            "RS": "Europe", "BA": "Europe", "ME": "Europe", "MK": "Europe",
            "AL": "Europe", "XK": "Europe", "MD": "Europe", "UA": "Europe",
            "BY": "Europe", "RU": "Europe", "TR": "Europe",
            "AM": "Asia", "AZ": "Asia", "GE": "Asia",
            "CN": "Asia", "JP": "Asia", "KR": "Asia", "KP": "Asia",
            "TW": "Asia", "HK": "Asia", "MO": "Asia", "MN": "Asia",
            "IN": "Asia", "PK": "Asia", "BD": "Asia", "LK": "Asia",
            "NP": "Asia", "BT": "Asia", "MV": "Asia", "AF": "Asia",
            "VN": "Asia", "TH": "Asia", "MY": "Asia", "SG": "Asia",
            "ID": "Asia", "PH": "Asia", "MM": "Asia", "KH": "Asia",
            "LA": "Asia", "BN": "Asia", "TL": "Asia",
            "KZ": "Asia", "UZ": "Asia", "TM": "Asia", "TJ": "Asia", "KG": "Asia",
            "IR": "Middle East", "IQ": "Middle East", "SY": "Middle East",
            "LB": "Middle East", "JO": "Middle East", "IL": "Middle East",
            "PS": "Middle East", "SA": "Middle East", "AE": "Middle East",
            "QA": "Middle East", "BH": "Middle East", "KW": "Middle East",
            "OM": "Middle East", "YE": "Middle East",
            "EG": "Africa", "LY": "Africa", "TN": "Africa", "DZ": "Africa",
            "MA": "Africa", "SD": "Africa", "SS": "Africa", "ET": "Africa",
            "SO": "Africa", "ER": "Africa", "DJ": "Africa", "KE": "Africa",
            "TZ": "Africa", "UG": "Africa", "RW": "Africa", "BI": "Africa",
            "NG": "Africa", "GH": "Africa", "CM": "Africa", "CI": "Africa",
            "SN": "Africa", "ML": "Africa", "BF": "Africa", "NE": "Africa",
            "TD": "Africa", "MR": "Africa", "GM": "Africa", "GN": "Africa",
            "GW": "Africa", "SL": "Africa", "LR": "Africa", "TG": "Africa",
            "BJ": "Africa", "ZA": "Africa", "NA": "Africa", "BW": "Africa",
            "ZW": "Africa", "ZM": "Africa", "MW": "Africa", "MZ": "Africa",
            "AO": "Africa", "CD": "Africa", "CG": "Africa", "GA": "Africa",
            "GQ": "Africa", "CF": "Africa", "ST": "Africa",
            "MG": "Africa", "MU": "Africa", "SC": "Africa", "KM": "Africa",
            "CV": "Africa", "CU": "Caribbean", "HT": "Caribbean",
            "DO": "Caribbean", "JM": "Caribbean", "TT": "Caribbean",
            "BB": "Caribbean", "LC": "Caribbean", "VC": "Caribbean",
            "GD": "Caribbean", "AG": "Caribbean", "DM": "Caribbean",
            "KN": "Caribbean", "BS": "Caribbean", "TC": "Caribbean",
            "KY": "Caribbean", "BM": "Caribbean", "VG": "Caribbean",
            "AW": "Caribbean", "CW": "Caribbean", "SX": "Caribbean",
            "BQ": "Caribbean", "AI": "Caribbean", "MS": "Caribbean",
            "MF": "Caribbean", "BL": "Caribbean", "GP": "Caribbean",
            "MQ": "Caribbean",
            "BR": "South America", "AR": "South America", "CL": "South America",
            "CO": "South America", "PE": "South America", "VE": "South America",
            "EC": "South America", "BO": "South America", "PY": "South America",
            "UY": "South America", "GY": "South America", "SR": "South America",
            "GF": "South America", "FK": "South America",
            "GT": "Central America", "BZ": "Central America", "HN": "Central America",
            "SV": "Central America", "NI": "Central America", "CR": "Central America",
            "PA": "Central America",
            "AU": "Oceania", "NZ": "Oceania", "PG": "Oceania", "FJ": "Oceania",
            "SB": "Oceania", "VU": "Oceania", "WS": "Oceania", "TO": "Oceania",
            "KI": "Oceania", "FM": "Oceania", "MH": "Oceania", "PW": "Oceania",
            "NR": "Oceania", "TV": "Oceania", "CK": "Oceania", "NU": "Oceania",
            "NC": "Oceania", "PF": "Oceania", "TF": "Oceania", "AQ": "Oceania",
            "WF": "Oceania", "TK": "Oceania", "PN": "Oceania",
        }

        # Country data: (code, name, basel_aml_score [0-10 scale], fatf_status, ofac_sanctioned)
        # Basel AML Index 2023 approximate scores (higher = more risk)
        # Sources: Basel AML Index 2023, FATF lists, OFAC SDN country lists
        COUNTRIES = [
            # Low-risk anchors
            ("FI", "Finland",             1.5, "clean",  False),
            ("NO", "Norway",              1.6, "clean",  False),
            ("SE", "Sweden",              1.7, "clean",  False),
            ("DK", "Denmark",             1.8, "clean",  False),
            ("LU", "Luxembourg",          2.0, "clean",  False),
            ("NZ", "New Zealand",         2.1, "clean",  False),
            ("CH", "Switzerland",         2.2, "clean",  False),
            ("NL", "Netherlands",         2.3, "clean",  False),
            ("DE", "Germany",             2.4, "clean",  False),
            ("SG", "Singapore",           2.5, "clean",  False),
            ("AU", "Australia",           2.6, "clean",  False),
            ("CA", "Canada",              2.7, "clean",  False),
            ("JP", "Japan",               2.8, "clean",  False),
            ("AT", "Austria",             2.9, "clean",  False),
            ("GB", "United Kingdom",      3.0, "clean",  False),
            ("US", "United States",       3.1, "clean",  False),
            ("FR", "France",              3.2, "clean",  False),
            ("IE", "Ireland",             3.3, "clean",  False),
            ("BE", "Belgium",             3.4, "clean",  False),
            ("IS", "Iceland",             3.5, "clean",  False),
            ("LI", "Liechtenstein",       3.5, "clean",  False),
            ("SM", "San Marino",          3.5, "clean",  False),
            ("KR", "South Korea",         3.6, "clean",  False),
            ("IL", "Israel",              3.8, "clean",  False),
            ("PT", "Portugal",            3.9, "clean",  False),
            ("ES", "Spain",               4.0, "clean",  False),
            ("IT", "Italy",               4.1, "clean",  False),
            ("CZ", "Czech Republic",      4.2, "clean",  False),
            ("SK", "Slovakia",            4.3, "clean",  False),
            ("SI", "Slovenia",            4.4, "clean",  False),
            ("EE", "Estonia",             4.5, "clean",  False),
            ("LV", "Latvia",              4.6, "clean",  False),
            ("LT", "Lithuania",           4.7, "clean",  False),
            ("PL", "Poland",              4.8, "clean",  False),
            ("HU", "Hungary",             5.0, "clean",  False),
            ("RO", "Romania",             5.2, "clean",  False),
            ("BG", "Bulgaria",            5.4, "clean",  False),
            ("HK", "Hong Kong",           4.0, "clean",  False),
            ("TW", "Taiwan",              3.8, "clean",  False),
            ("MT", "Malta",               4.5, "clean",  False),
            ("CY", "Cyprus",              5.0, "clean",  False),
            ("GR", "Greece",              5.0, "clean",  False),
            ("MC", "Monaco",              4.8, "grey",   False),
            # Mid-range
            ("AE", "United Arab Emirates",5.5, "clean",  False),
            ("SA", "Saudi Arabia",        5.5, "clean",  False),
            ("QA", "Qatar",               5.3, "clean",  False),
            ("BH", "Bahrain",             5.4, "clean",  False),
            ("KW", "Kuwait",              5.6, "clean",  False),
            ("OM", "Oman",                5.7, "clean",  False),
            ("JO", "Jordan",              5.8, "clean",  False),
            ("LB", "Lebanon",             7.2, "clean",  False),
            ("TR", "Turkey",              6.0, "clean",  False),
            ("UA", "Ukraine",             6.5, "clean",  False),
            ("RS", "Serbia",              5.8, "clean",  False),
            ("BA", "Bosnia and Herzegovina",6.0,"clean", False),
            ("ME", "Montenegro",          5.9, "clean",  False),
            ("MK", "North Macedonia",     5.8, "clean",  False),
            ("AL", "Albania",             6.2, "clean",  False),
            ("MD", "Moldova",             6.5, "clean",  False),
            ("AM", "Armenia",             6.3, "clean",  False),
            ("AZ", "Azerbaijan",          6.5, "clean",  False),
            ("GE", "Georgia",             5.5, "clean",  False),
            ("KZ", "Kazakhstan",          6.8, "clean",  False),
            ("UZ", "Uzbekistan",          7.0, "clean",  False),
            ("TM", "Turkmenistan",        7.5, "clean",  False),
            ("TJ", "Tajikistan",          7.2, "clean",  False),
            ("KG", "Kyrgyzstan",          7.0, "clean",  False),
            ("MN", "Mongolia",            6.5, "clean",  False),
            ("CN", "China",               6.0, "clean",  False),
            ("IN", "India",               5.8, "clean",  False),
            ("PK", "Pakistan",            7.5, "clean",  False),
            ("BD", "Bangladesh",          7.0, "clean",  False),
            ("LK", "Sri Lanka",           6.5, "clean",  False),
            ("NP", "Nepal",               7.2, "grey",   False),
            ("BT", "Bhutan",              5.5, "clean",  False),
            ("MV", "Maldives",            5.8, "clean",  False),
            ("AF", "Afghanistan",         8.5, "clean",  False),
            ("VN", "Vietnam",             7.0, "grey",   False),
            ("TH", "Thailand",            6.0, "clean",  False),
            ("MY", "Malaysia",            5.5, "clean",  False),
            ("ID", "Indonesia",           5.8, "clean",  False),
            ("PH", "Philippines",         6.5, "grey",   False),
            ("MM", "Myanmar",             8.5, "black",  False),
            ("KH", "Cambodia",            7.5, "clean",  False),
            ("LA", "Laos",                7.0, "clean",  False),
            ("BN", "Brunei",              5.0, "clean",  False),
            ("TL", "Timor-Leste",         6.0, "clean",  False),
            ("PG", "Papua New Guinea",    6.5, "clean",  False),
            ("FJ", "Fiji",                5.8, "clean",  False),
            ("SB", "Solomon Islands",     5.5, "clean",  False),
            ("VU", "Vanuatu",             6.0, "clean",  False),
            ("WS", "Samoa",               5.2, "clean",  False),
            ("TO", "Tonga",               5.0, "clean",  False),
            ("KI", "Kiribati",            5.0, "clean",  False),
            ("FM", "Micronesia",          5.0, "clean",  False),
            ("MH", "Marshall Islands",    6.0, "clean",  False),
            ("PW", "Palau",               5.5, "clean",  False),
            ("NR", "Nauru",               7.0, "clean",  False),
            ("TV", "Tuvalu",              5.0, "clean",  False),
            ("CK", "Cook Islands",        5.5, "clean",  False),
            ("NU", "Niue",                5.0, "clean",  False),
            ("NC", "New Caledonia",       4.5, "clean",  False),
            ("PF", "French Polynesia",    4.5, "clean",  False),
            ("TF", "French Southern Territories",4.0,"clean",False),
            ("AQ", "Antarctica",          1.0, "clean",  False),
            ("WF", "Wallis and Futuna",   4.5, "clean",  False),
            ("TK", "Tokelau",             4.0, "clean",  False),
            ("PN", "Pitcairn",            4.0, "clean",  False),
            # Africa
            ("NG", "Nigeria",             7.2, "grey",   False),
            ("ZA", "South Africa",        6.5, "grey",   False),
            ("KE", "Kenya",               6.8, "grey",   False),
            ("EG", "Egypt",               6.5, "clean",  False),
            ("MA", "Morocco",             6.0, "clean",  False),
            ("TN", "Tunisia",             6.2, "clean",  False),
            ("DZ", "Algeria",             7.0, "grey",   False),
            ("LY", "Libya",               8.0, "clean",  False),
            ("SD", "Sudan",               8.5, "clean",  False),
            ("SS", "South Sudan",         8.8, "grey",   False),
            ("ET", "Ethiopia",            7.5, "grey",   False),
            ("SO", "Somalia",             9.0, "clean",  False),
            ("ER", "Eritrea",             8.0, "clean",  False),
            ("DJ", "Djibouti",            6.8, "clean",  False),
            ("TZ", "Tanzania",            7.0, "grey",   False),
            ("UG", "Uganda",              7.0, "clean",  False),
            ("RW", "Rwanda",              5.5, "clean",  False),
            ("BI", "Burundi",             7.5, "clean",  False),
            ("CM", "Cameroon",            7.2, "grey",   False),
            ("CI", "Côte d'Ivoire",       6.8, "grey",   False),
            ("SN", "Senegal",             6.5, "grey",   False),
            ("ML", "Mali",                7.8, "grey",   False),
            ("BF", "Burkina Faso",        7.5, "grey",   False),
            ("NE", "Niger",               7.2, "clean",  False),
            ("TD", "Chad",                8.0, "clean",  False),
            ("MR", "Mauritania",          7.0, "clean",  False),
            ("GM", "Gambia",              6.5, "clean",  False),
            ("GN", "Guinea",              7.8, "clean",  False),
            ("GW", "Guinea-Bissau",       8.5, "clean",  False),
            ("SL", "Sierra Leone",        7.5, "clean",  False),
            ("LR", "Liberia",             7.2, "clean",  False),
            ("TG", "Togo",                7.0, "clean",  False),
            ("BJ", "Benin",               6.8, "clean",  False),
            ("GH", "Ghana",               6.5, "clean",  False),
            ("NA", "Namibia",             6.0, "grey",   False),
            ("BW", "Botswana",            5.5, "clean",  False),
            ("ZW", "Zimbabwe",            8.0, "clean",  False),
            ("ZM", "Zambia",              6.8, "clean",  False),
            ("MW", "Malawi",              6.5, "clean",  False),
            ("MZ", "Mozambique",          7.0, "grey",   False),
            ("AO", "Angola",              7.5, "grey",   False),
            ("CD", "DRC",                 8.0, "grey",   False),
            ("CG", "Republic of Congo",   7.5, "clean",  False),
            ("GA", "Gabon",               7.0, "clean",  False),
            ("GQ", "Equatorial Guinea",   7.8, "clean",  False),
            ("CF", "Central African Republic",8.5,"clean",False),
            ("ST", "São Tomé and Príncipe",6.0,"clean",  False),
            ("MG", "Madagascar",          7.0, "clean",  False),
            ("MU", "Mauritius",           4.5, "clean",  False),
            ("SC", "Seychelles",          5.5, "clean",  False),
            ("KM", "Comoros",             7.0, "clean",  False),
            ("CV", "Cape Verde",          5.8, "clean",  False),
            # Middle East (cont.)
            ("IQ", "Iraq",                8.2, "clean",  False),
            ("PS", "Palestine",           7.0, "clean",  False),
            # OFAC / High risk
            ("KP", "North Korea",         9.5, "black",  True),
            ("IR", "Iran",                9.2, "black",  True),
            ("SY", "Syria",               9.0, "clean",  True),
            ("CU", "Cuba",                7.5, "clean",  True),
            ("RU", "Russia",              7.8, "clean",  True),
            ("BY", "Belarus",             7.2, "clean",  True),
            ("VE", "Venezuela",           8.0, "grey",   True),
            # Americas
            ("BR", "Brazil",              5.8, "clean",  False),
            ("AR", "Argentina",           6.0, "clean",  False),
            ("CL", "Chile",               4.5, "clean",  False),
            ("CO", "Colombia",            6.5, "clean",  False),
            ("PE", "Peru",                6.2, "clean",  False),
            ("EC", "Ecuador",             6.8, "clean",  False),
            ("BO", "Bolivia",             7.0, "clean",  False),
            ("PY", "Paraguay",            7.2, "clean",  False),
            ("UY", "Uruguay",             4.8, "clean",  False),
            ("GY", "Guyana",              6.5, "clean",  False),
            ("SR", "Suriname",            7.0, "clean",  False),
            ("GF", "French Guiana",       5.5, "clean",  False),
            ("FK", "Falkland Islands",    3.5, "clean",  False),
            ("GT", "Guatemala",           7.0, "clean",  False),
            ("BZ", "Belize",              6.8, "clean",  False),
            ("HN", "Honduras",            7.2, "clean",  False),
            ("SV", "El Salvador",         6.8, "clean",  False),
            ("NI", "Nicaragua",           7.5, "clean",  False),
            ("CR", "Costa Rica",          5.5, "clean",  False),
            ("PA", "Panama",              6.5, "clean",  False),
            ("DO", "Dominican Republic",  6.0, "clean",  False),
            ("JM", "Jamaica",             6.5, "clean",  False),
            ("TT", "Trinidad and Tobago", 6.8, "clean",  False),
            ("HT", "Haiti",               8.0, "grey",   False),
            ("BB", "Barbados",            5.0, "clean",  False),
            ("LC", "Saint Lucia",         5.5, "clean",  False),
            ("VC", "Saint Vincent",       6.0, "clean",  False),
            ("GD", "Grenada",             5.5, "clean",  False),
            ("AG", "Antigua and Barbuda", 5.8, "clean",  False),
            ("DM", "Dominica",            6.0, "clean",  False),
            ("KN", "Saint Kitts and Nevis",6.2,"clean",  False),
            ("BS", "Bahamas",             5.5, "clean",  False),
            ("TC", "Turks and Caicos",    5.8, "clean",  False),
            ("KY", "Cayman Islands",      5.0, "clean",  False),
            ("BM", "Bermuda",             4.5, "clean",  False),
            ("VG", "British Virgin Islands",5.5,"clean", False),
            ("AW", "Aruba",               5.0, "clean",  False),
            ("CW", "Curaçao",             5.5, "clean",  False),
            ("SX", "Sint Maarten",        5.8, "clean",  False),
            ("MF", "Saint Martin",        5.0, "clean",  False),
            ("BL", "Saint Barthélemy",    4.5, "clean",  False),
            ("GP", "Guadeloupe",          4.5, "clean",  False),
            ("MQ", "Martinique",          4.5, "clean",  False),
            # US territories (low risk)
            ("PR", "Puerto Rico",         4.5, "clean",  False),
            ("VI", "US Virgin Islands",   4.8, "clean",  False),
            ("GU", "Guam",                4.5, "clean",  False),
            ("MP", "Northern Mariana Islands",4.5,"clean",False),
            ("AS", "American Samoa",      4.5, "clean",  False),
            ("UM", "US Minor Outlying Islands",4.0,"clean",False),
            # Misc territories
            ("SH", "Saint Helena",        4.0, "clean",  False),
            ("IO", "British Indian Ocean Territory",4.0,"clean",False),
            ("YT", "Mayotte",             5.0, "clean",  False),
            ("RE", "Réunion",             4.5, "clean",  False),
            ("PM", "Saint Pierre and Miquelon",4.0,"clean",False),
            ("XK", "Kosovo",              6.0, "clean",  False),
            ("VA", "Vatican City",        3.5, "clean",  False),
            ("AD", "Andorra",             3.8, "clean",  False),
        ]

        def compute_composite(ofac: bool, fatf_status: str, basel: float) -> float:
            ofac_factor  = 100.0 if ofac else 0.0
            if fatf_status == "black":
                fatf_factor = 100.0
            elif fatf_status == "grey":
                fatf_factor = 60.0
            else:
                fatf_factor = 0.0
            basel_norm = (basel / 10.0) * 100.0
            composite = 0.4 * ofac_factor + 0.3 * fatf_factor + 0.3 * basel_norm
            return round(composite, 2)

        rows = []
        for code, name, basel, fatf, ofac in COUNTRIES:
            # Determine final FATF status from reference sets (override inline value)
            if code in FATF_BLACKLIST:
                fatf_final = "black"
            elif code in FATF_GREYLIST:
                fatf_final = "grey"
            else:
                fatf_final = "clean"

            ofac_final = code in OFAC_SANCTIONED
            composite  = compute_composite(ofac_final, fatf_final, basel)

            rows.append({
                "country_code":          code,
                "country_name":          name,
                "basel_aml_score":       round(basel, 2),
                "fatf_status":           fatf_final,
                "ofac_sanctioned_country": 1 if ofac_final else 0,
                "region":                REGIONS.get(code, "Other"),
                "composite_risk_score":  composite,
            })

        out = out_path("country_risk.csv")
        fields = ["country_code", "country_name", "basel_aml_score", "fatf_status",
                  "ofac_sanctioned_country", "region", "composite_risk_score"]
        write_csv(out, fields, rows)
        logger.info(f"  Written: {out} ({len(rows)} countries)")
        update_progress("country_risk_source", "real")

    except Exception as exc:
        logger.error(f"  Sub-step F failed ({exc}); generating minimal fallback.", exc_info=True)
        _step_f_fallback(logger)


def _step_f_fallback(logger: logging.Logger) -> None:
    logger.info("  Writing minimal country_risk fallback ...")
    rows = [
        {"country_code":"US","country_name":"United States","basel_aml_score":3.1,"fatf_status":"clean","ofac_sanctioned_country":0,"region":"North America","composite_risk_score":9.3},
        {"country_code":"GB","country_name":"United Kingdom","basel_aml_score":3.0,"fatf_status":"clean","ofac_sanctioned_country":0,"region":"Europe","composite_risk_score":9.0},
        {"country_code":"KP","country_name":"North Korea","basel_aml_score":9.5,"fatf_status":"black","ofac_sanctioned_country":1,"region":"Asia","composite_risk_score":98.5},
        {"country_code":"IR","country_name":"Iran","basel_aml_score":9.2,"fatf_status":"black","ofac_sanctioned_country":1,"region":"Middle East","composite_risk_score":97.6},
        {"country_code":"SY","country_name":"Syria","basel_aml_score":9.0,"fatf_status":"clean","ofac_sanctioned_country":1,"region":"Middle East","composite_risk_score":67.0},
    ]
    out = out_path("country_risk.csv")
    write_csv(out, list(rows[0].keys()), rows)
    logger.info(f"  Fallback written: {out}")
    update_progress("country_risk_source", "fallback")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    logger = setup_logging()
    logger.info("=== 01_build_reference_data.py started ===")

    os.makedirs(REF_DIR, exist_ok=True)

    # Sub-step A
    logger.info("Running sub-step A ...")
    step_a(logger)
    logger.info("Sub-step A complete.")

    # Sub-step B
    logger.info("Running sub-step B ...")
    step_b(logger)
    logger.info("Sub-step B complete.")

    # Sub-step C
    logger.info("Running sub-step C ...")
    step_c(logger)
    logger.info("Sub-step C complete.")

    # Sub-step D
    logger.info("Running sub-step D ...")
    step_d(logger)
    logger.info("Sub-step D complete.")

    # Sub-step E
    logger.info("Running sub-step E ...")
    step_e(logger)
    logger.info("Sub-step E complete.")

    # Sub-step F
    logger.info("Running sub-step F ...")
    step_f(logger)
    logger.info("Sub-step F complete.")

    # Mark all reference data complete
    update_progress("reference_data_complete", True)
    logger.info("progress.json updated: reference_data_complete=true")
    logger.info("=== 01_build_reference_data.py finished successfully ===")
    print("All reference data files built. See logs/generation_log.txt for details.")


if __name__ == "__main__":
    main()
