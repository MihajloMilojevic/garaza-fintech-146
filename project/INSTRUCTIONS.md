# Sanctions Screening Synthetic Dataset — Generation Instructions (v2)

> **Audience:** An AI coding agent (Claude Code, running locally with filesystem access).
> Possibly picked up in a fresh session with no memory of prior steps.
>
> **Purpose:** Generate a complete, relationally-consistent dataset that supports:
> 1. Training/evaluating a **customer risk score model** (0–100)
> 2. Generating **transaction-context features** for the dynamic threshold model
> 3. Producing **explanatory audit logs** (SHAP-style "why" narratives)
> 4. A **static-threshold vs dynamic-threshold** comparison ("show impact" deliverable)
>
> **Time budget: ~16 hours total**, including downloads, generation, and training a first
> XGBoost pass. Prioritize getting an end-to-end pipeline working over maximizing scale.
> If running short on time, cut scale (fewer accounts/transactions) before cutting
> pipeline steps (every step in Section 4 should produce *something*, even if small).
>
> **This document is self-contained.** If resuming mid-way, read Section 9 first.

---

## 0. Inputs you should already have on disk

The user is downloading these manually. Check `/data/raw/` (or wherever the user places
them — confirm the path at the start) for:

| File | Source | Approx size | Used for |
|---|---|---|---|
| `sanctions_targets.simple.csv` | opensanctions.org/datasets/sanctions → targets.simple.csv | ~63 MB | Primary sanctioned-entity reference list |
| `sanctions_entities.ftm.json` | opensanctions.org/datasets/sanctions → entities.ftm.json | ~327 MB | Relationship/ownership edges (Section 2.1b) |
| `peps_targets.simple.csv` | opensanctions.org/datasets/peps → targets.simple.csv | varies | PEP reference list |
| `matching_pairs.json` (or similar) | opensanctions.org/docs/opensource/pairs/ | varies | Calibrating fuzzy-match score distributions |
| `HI-Small_Trans.csv` | Kaggle ealtman2019/ibm-transactions-for-anti-money-laundering-aml | ~tens of MB | Real transaction shape (amounts, timing, accounts, laundering labels) |
| `HI-Small_Patterns.txt` | same Kaggle dataset | small | Which HI-Small transactions are laundering, and which pattern |

**If any file is missing**, fall back to the synthetic generator described inline at each
relevant step (marked **FALLBACK**) — do not block the whole pipeline on one missing file.
Log which fallbacks were used in `progress.json.notes`.

**First action:** write a small `inspect_inputs.py` that loads the first ~100 rows /
entities of each file present, prints columns/structure, and writes a short
`reference_data/input_inventory.md` summarizing what's actually available and its exact
schema (real-world files often differ slightly from docs). Do this BEFORE writing any
generation logic that assumes a schema.

---

## 1. Directory layout

```
/data/                              (or wherever inputs live — confirm with user)
  raw/                              <- user-provided downloads, read-only

project/
├── INSTRUCTIONS.md                 (this file)
├── progress.json
├── logs/generation_log.txt
├── reference_data/
│   ├── input_inventory.md
│   ├── country_risk.csv
│   ├── sanctioned_entities.csv     <- derived from sanctions_targets.simple.csv
│   ├── sanctioned_relationships.csv <- derived from entities.ftm.json
│   ├── peps.csv                    <- derived from peps_targets.simple.csv
│   ├── matching_pairs_summary.csv  <- derived from matching pairs
│   └── aml_transactions_sample.csv <- derived from HI-Small_Trans.csv
├── scripts/
│   ├── inspect_inputs.py
│   ├── 00_init_db.py
│   ├── 01_build_reference_data.py
│   ├── 02_generate_accounts.py
│   ├── 03_generate_relationships.py
│   ├── 04_generate_transactions.py
│   ├── 05_generate_screening_results.py
│   ├── 06_compute_risk_scores.py
│   ├── 07_compute_dynamic_thresholds.py
│   ├── 08_generate_explanatory_logs.py
│   ├── 09_comparison_report.py
│   └── 10_export.py
├── exports/                         <- final compressed parquet/csv, <100MB each
├── sanctions_screening.db
└── comparison_summary.md
```

---

## 2. Reference data (Section A — do once)

### 2.1a Sanctioned entities — from `sanctions_targets.simple.csv`

This CSV (per OpenSanctions docs) has columns roughly: `id, schema, name, aliases,
birth_date, countries, addresses, identifiers, sanctions, phones, emails, dataset,
first_seen, last_seen, ...` — **confirm exact columns via `inspect_inputs.py`**, names
vary by export version.

Filter/transform to `reference_data/sanctioned_entities.csv` with columns:
- `entity_id`, `name`, `aliases` (pipe-separated), `entity_type` (map `schema` →
  Person/Company/Organization/CryptoWallet — CryptoWallet schema entities have wallet
  addresses in `identifiers` or a dedicated column), `country` (first/primary from
  `countries`), `dob` (from `birth_date`, persons only), `program` (from `sanctions` or
  `dataset`), `crypto_addresses` (pipe-separated, where applicable)

**Sampling:** the full file likely has tens of thousands of entities. For our purposes,
sample down to **5,000–8,000 entities**, but ensure the sample includes:
- ALL entities with `entity_type == CryptoWallet` (likely a small subset — keep all)
- A diverse spread of countries (don't just take the first N rows — stratify by country)
- A spread of `entity_type` (don't drop Companies/Organizations in favor of only Persons)

### 2.1b Relationship edges — from `sanctions_entities.ftm.json`

This is the FollowTheMoney graph. FTM entities include relationship schemas (Ownership,
Family, Associate, Directorship, etc.) with `properties` pointing to other entity IDs
via fields like `owner`/`asset`, `person`/`relative`, etc.

**This file is 327MB — do not load it fully into memory at once.** It's likely
newline-delimited JSON (one entity per line) or a JSON array — check in
`inspect_inputs.py`. Stream it line-by-line (or with `ijson` for array-format JSON).

Extract: for each relationship-type entity where BOTH endpoints resolve to an entity ID
present in your `sanctioned_entities.csv` sample (or where at least one endpoint is in
the sample and the other is a generic Person/Company — useful for the "indirect
exposure" cases), write a row to `reference_data/sanctioned_relationships.csv`:

`relationship_id, entity_id_a, entity_id_b, relationship_type (ownership/family/
associate/directorship), role_a, role_b`

**Time-box this step to ~30-45 minutes of wall-clock processing.** If streaming 327MB is
too slow, take a random sample of the file (e.g. every Nth line) rather than the full
thing — we need *enough* real relationship edges to seed `account_relationships`
realistically, not all of them. **FALLBACK** if this file is unusable/missing/too slow:
generate relationships synthetically as originally planned (random pairing of accounts
with plausible relationship types).

### 2.1c PEPs — from `peps_targets.simple.csv`

Same extraction pattern as 2.1a. Output `reference_data/peps.csv`:
`pep_id, name, position, country, start_date, end_date, is_current`

Sample to **2,000–3,000** if the source file is large, stratified by country.

**FALLBACK** if missing: synthetic generation as in v1 instructions (name + position
title + country combos).

### 2.1d Matching pairs — calibration data

From whatever format the matching pairs download is in, extract pairs of (name_a,
name_b, label=match/non-match) if available. Compute summary statistics:
- Distribution of string similarity (e.g. Jaro-Winkler) scores for TRUE matches
- Distribution for FALSE matches

Write `reference_data/matching_pairs_summary.csv` with these distributions (e.g.
histogram bins). **Use these distributions in Section 4.5 (screening_results) to
calibrate `match_score` for fuzzy_near_miss accounts** — instead of guessing a 45-75
range, sample from the real distribution of similarity scores for actual confusable
name pairs. This is the highest-value use of this file — it's what makes the "hard
band" realistic.

**FALLBACK** if missing/unusable: use the illustrative 45-75 range from v1 instructions,
note it in progress.json.

### 2.1e AML transaction shape — from `HI-Small_Trans.csv` + `HI-Small_Patterns.txt`

Inspect columns (typical AMLSim/IBM-AML schema: `Timestamp, From Bank, From Account,
To Bank, To Account, Amount Received, Receiving Currency, Amount Paid, Payment
Currency, Payment Format, Is Laundering`).

Don't use this dataset's accounts/identities directly (they're not relevant to
sanctions). Instead, extract **statistical distributions** to drive our synthetic
transaction generation:
- Amount distribution (overall, and conditional on `Payment Format` — wire/card/ACH/etc.)
- Hour-of-day / day-of-week distribution from `Timestamp`
- For accounts flagged in `Is Laundering` / `HI-Small_Patterns.txt`: their
  velocity/burst patterns (transactions per day, amount escalation) — use this to shape
  the behavioural-risk-triggering transaction sequences for our injected
  sanctioned/high-risk accounts (Section 4.4)
- `Payment Format` → map to our `payment_rail` categories (wire→wire, ACH→ach,
  Credit Card→card, etc.)

Write `reference_data/aml_transactions_sample.csv` as a compact summary (binned
distributions as CSV, e.g. `amount_bin, count, payment_format` — not a copy of the raw
file) — keep this small (<5MB).

### 2.2 Country risk — manual/curated (unchanged from v1)

Build `reference_data/country_risk.csv` covering ~195 countries:
`country_code, country_name, basel_aml_score (0-10), fatf_status (clean/grey/black),
ofac_sanctioned_country (bool), region, composite_risk_score (0-100)`

Use FATF grey/black list anchors (web search current FATF lists if time allows — cheap,
one search), OFAC comprehensively-sanctioned countries (North Korea, Iran, Syria, Cuba,
Russia, Belarus, Venezuela), and Basel-AML-style low-risk anchors (Switzerland, Nordics,
Singapore, Luxembourg, NZ). Mid-range everything else 25-55. Document the composite
formula in the script's docstring.

### `01_build_reference_data.py`

One script, does all of 2.1a-e + 2.2. Each sub-step wrapped in try/except, clear
success/fallback logging. Re-runnable (overwrites reference_data/ outputs, which are
all small).

**Checkpoint:** `reference_data_complete: true`, plus per-source flags:
`sanctioned_entities_source` ("real"|"fallback"), `relationships_source`, `peps_source`,
`matching_pairs_source`, `aml_shape_source` — each "real" or "fallback".

---

## 3. Database schema (`00_init_db.py`)

**Identical to v1 Section 3** — no changes to the schema itself. Reproducing here for
completeness (this is the contract every later script writes against):

### `accounts`
```sql
account_id TEXT PRIMARY KEY,
account_type TEXT,                  -- 'individual' | 'business'
full_name TEXT,
country_residence TEXT,
country_incorporation TEXT,
date_of_birth TEXT,
nationality TEXT,
created_at TEXT,
kyc_completeness REAL,
kyc_status TEXT,
is_pep INTEGER,
pep_id TEXT,
has_complex_ownership INTEGER,
shell_company_flag INTEGER,
sanctioned_entity_id TEXT,
name_match_type TEXT,               -- 'none'|'exact'|'alias'|'fuzzy_near_miss'
account_status TEXT,
activity_tier TEXT,                 -- 'low'|'medium'|'high' -- NEW vs v1, see 4.2
initial_risk_band TEXT
```

### `account_relationships`
```sql
relationship_id TEXT PRIMARY KEY,
account_id TEXT,
related_entity_name TEXT,
relationship_type TEXT,
related_is_pep INTEGER,
related_is_sanctioned INTEGER,
related_sanctioned_entity_id TEXT,
source TEXT                         -- 'real_ftm' | 'synthetic' -- NEW: provenance
```

### `wallets`
```sql
wallet_id TEXT PRIMARY KEY,
account_id TEXT,
wallet_address TEXT,
chain TEXT,
is_sanctioned INTEGER,
sanctioned_entity_id TEXT,
hops_to_sanctioned INTEGER
```

### `transactions`
```sql
transaction_id TEXT PRIMARY KEY,
sender_account_id TEXT,
recipient_account_id TEXT,
recipient_type TEXT,
recipient_name TEXT,
recipient_country TEXT,
recipient_wallet_id TEXT,
amount REAL,
currency TEXT,
payment_rail TEXT,
timestamp TEXT,
is_first_time_recipient INTEGER,
sender_account_age_days INTEGER,
velocity_30d_count INTEGER,
velocity_30d_amount REAL,
hour_of_day INTEGER,
day_of_week INTEGER,
shape_source TEXT                   -- 'aml_derived' | 'synthetic' -- NEW: provenance
```

### `screening_results`
```sql
screening_id TEXT PRIMARY KEY,
transaction_id TEXT,
account_id TEXT,
screening_context TEXT,
matched_entity_id TEXT,
match_score REAL,
match_field TEXT,
fuzzy_match_type TEXT,
hops_to_sanctioned INTEGER,
shares_address_with_sanctioned INTEGER,
pep_exposure_score REAL,
country_risk_score REAL,
verdict_ground_truth TEXT
```

### `risk_scores`
```sql
risk_score_id TEXT PRIMARY KEY,
account_id TEXT,
computed_at TEXT,
geographic_risk REAL,
identity_kyc_risk REAL,
pep_sanctions_risk REAL,
behavioural_risk REAL,
relationship_network_risk REAL,
overall_risk_score REAL,
risk_band TEXT,
override_applied INTEGER,
override_reason TEXT
```

### `threshold_decisions`
```sql
decision_id TEXT PRIMARY KEY,
transaction_id TEXT,
screening_id TEXT,
static_threshold REAL,
static_verdict TEXT,
dynamic_t_block REAL,
dynamic_t_review REAL,
dynamic_verdict TEXT,
verdicts_differ INTEGER
```

### `explanatory_logs`
```sql
log_id TEXT PRIMARY KEY,
related_table TEXT,
related_id TEXT,
narrative TEXT,
top_factors_json TEXT
```

Use `CREATE TABLE IF NOT EXISTS` throughout.

---

## 4. Generation order and logic

### Scale (adjusted for 16-hour budget)

- **20,000 accounts** (down from 50k — still gives 60-100 injected true positives at
  0.3-0.5%, which is sufficient for a first model)
- **200,000 transactions** (down from 500k)
- Batch sizes: 2,000 accounts/batch (10 batches), 10,000 transactions/batch (20 batches)

If the pipeline runs faster than expected and time remains, scale UP by re-running
generation scripts with higher targets in `progress.json` (they should support this —
treat target counts as config, not hardcoded).

### `02_generate_accounts.py`

Same logic as v1 Section 4 (`01_generate_accounts.py`), with one change: assign
`activity_tier` (`low`/`medium`/`high`, roughly 60/30/10 split) at creation time — this
drives transaction volume per account in step 4.

Sanctions true-positive injection: ~0.3-0.5% (60-100 accounts at 20k scale), using the
real `sanctioned_entities.csv` sample. Name perturbation for `fuzzy_near_miss` (~40% of
injected): transliteration swaps, common misspellings, name-order swaps — write a small
reusable `perturb_name(name, country)` function, since this same logic will be useful
for generating the "coincidental partial match" false-positive seeds in step 5.

PEP injection (~0.5%) using real `peps.csv`.

### `03_generate_relationships.py`

- If `relationships_source == "real_ftm"`: for sanctioned/PEP-injected accounts, look up
  whether their underlying real entity has edges in `sanctioned_relationships.csv` and
  materialize those as `account_relationships` rows with `source='real_ftm'`. For the
  ~5% of ordinary business accounts that should get an indirect-exposure relationship,
  also draw from real edges where available.
- Fill remaining relationship slots (most accounts) with `source='synthetic'` as in v1.
- Wallets: same as v1, using real `crypto_addresses` from `sanctioned_entities.csv`
  where available for directly-sanctioned wallets.

### `04_generate_transactions.py`

- Use `aml_transactions_sample.csv` distributions for: amount sampling (per
  payment_rail), hour-of-day/day-of-week sampling, and burst/velocity shaping for
  high-risk accounts. Set `shape_source='aml_derived'` for transactions generated this
  way. If using pure fallback distributions for some accounts, mark
  `shape_source='synthetic'`.
- Otherwise identical structure to v1: sender selection weighted by `activity_tier`,
  recipient_type split (50/35/15), `is_first_time_recipient` and velocity fields
  computed in a post-pass after all batches (same chronological-ordering constraint as
  v1).
- 200,000 transactions / 20 batches = 10,000/batch.

**Checkpoint:** `transactions_velocity_pass_complete: true`.

### `05_generate_screening_results.py`

Same as v1, with the calibration upgrade: for `fuzzy_near_miss` accounts, sample
`match_score` from the real TRUE-match similarity distribution in
`matching_pairs_summary.csv` (mapped to a 0-100 scale) rather than a flat 45-75 range.
For coincidental partial matches (false-positive seeds, ~1-2% of clean accounts), sample
from the real FALSE-match (but non-trivial similarity) distribution.

### `06_compute_risk_scores.py` / `07_compute_dynamic_thresholds.py` / `08_generate_explanatory_logs.py`

Unchanged from v1 (`05`/`06`/`07` there). Formulas as specified in v1 — reproduce them
in this codebase's script docstrings.

### `09_comparison_report.py`

Unchanged from v1 `08`. Output `comparison_summary.md` + `.json`.

### `10_export.py` — export and sharing strategy

This step changes meaningfully from v1 given the sharing constraint (no GitHub LFS/Drive
assumed available, 100MB/file practical limit):

1. Export each table to **Parquet with zstd compression** (`pyarrow`, `compression='zstd'`)
   — parquet+zstd on tabular data this size should comfortably stay under 100MB per
   table even at 200k transaction rows. Check actual sizes after export.
2. If any single exported file exceeds ~90MB (leave headroom under GitHub's 100MB
   limit), split it: e.g. `transactions_part1.parquet`, `transactions_part2.parquet`,
   by row-range, plus a tiny `transactions_manifest.json` listing parts and row counts.
   Write a 10-line `load_dataset.py` helper that transparently concatenates parts when
   loading any table — this is the "merge script."
3. Keep `sanctions_screening.db` (SQLite) too if it fits reasonably, but it's the
   "working" artifact, not necessarily what gets shared — parquet parts are the
   portable/shareable deliverable.
4. Write a top-level `README.md` in `exports/` describing: table list, row counts, which
   sources were "real" vs "fallback" (from `progress.json`), the formulas used (risk
   score weights, threshold formula), and how to load (`load_dataset.py`).
5. Final output location: everything the user needs to commit goes in `exports/` +
   `reference_data/` (small) + `scripts/` + `comparison_summary.md` + this
   INSTRUCTIONS.md. The `sanctions_screening.db` and `/data/raw/` inputs do NOT need to
   be committed (raw inputs are large and reproducible from the download links; the DB
   is reproducible from scripts + reference_data).

**If git is being used:** add a `.gitattributes` recommending Git LFS for any file >50MB
as a courtesy even if not required, and add `/data/raw/` and `*.db` to `.gitignore`.

---

## 5. Libraries / setup

```bash
pip install pandas numpy faker pyarrow ijson ujson
```

- `ijson` for streaming the large FTM JSON (2.1b) without loading 327MB into memory
- `faker` with multiple locales for name diversity
- `pyarrow` with zstd for compressed parquet export

---

## 6. Style notes for realism (unchanged from v1)

- Don't make injected sanctioned/PEP accounts uniformly high-risk on every dimension.
- Don't make clean accounts uniformly low-risk — inject some high behavioural/geographic
  risk with no sanctions connection (true negatives in the REVIEW band).
- Vary `created_at` for real spread in `sender_account_age_days`.
- Log running counts of `verdict_ground_truth` to sanity-check positive rate stays in
  the 0.2-0.5% range.

---

## 7. Progress tracking & recovery (`progress.json`)

```json
{
  "input_inventory_complete": false,
  "reference_data_complete": false,
  "sanctioned_entities_source": null,
  "relationships_source": null,
  "peps_source": null,
  "matching_pairs_source": null,
  "aml_shape_source": null,
  "schema_complete": false,
  "accounts_target": 20000,
  "accounts_generated": 0,
  "accounts_batches_done": [],
  "relationships_complete": false,
  "wallets_complete": false,
  "transactions_target": 200000,
  "transactions_generated": 0,
  "transactions_batches_done": [],
  "transactions_velocity_pass_complete": false,
  "screening_results_complete": false,
  "risk_scores_complete": false,
  "threshold_decisions_complete": false,
  "explanatory_logs_complete": false,
  "comparison_summary_complete": false,
  "export_complete": false,
  "last_updated": "<ISO timestamp>",
  "notes": []
}
```

Same rules as v1 Section 7: every script loads this first, skips completed work, updates
after each batch, logs to `logs/generation_log.txt`, prints progress to stdout.

---

## 8. Suggested execution order / todo list

1. `pip install` deps
2. Create directory structure, confirm `/data/raw/` contents match Section 0 table
3. `inspect_inputs.py` → `input_inventory.md` (do this before anything else — schemas
   may differ from assumptions above)
4. `01_build_reference_data.py` → reference CSVs (time-box 2.1b to 30-45 min)
5. `00_init_db.py` → schema
6. `02_generate_accounts.py` (10 batches × 2,000)
7. `03_generate_relationships.py`
8. `04_generate_transactions.py` (20 batches × 10,000) + velocity post-pass
9. `05_generate_screening_results.py`
10. `06_compute_risk_scores.py`
11. `07_compute_dynamic_thresholds.py`
12. `08_generate_explanatory_logs.py`
13. `09_comparison_report.py`
14. `10_export.py`
15. (If time remains) train a first XGBoost pass on `risk_scores` + `threshold_decisions`
    features using `screening_results.verdict_ground_truth` as the label — even a rough
    first model is valuable to validate the dataset is learnable. Not required for the
    dataset deliverable itself but worth attempting if hours remain.

Print a one-paragraph summary after each numbered step (row counts, key distributions,
real-vs-fallback sources used).

---

## 9. Resuming work after interruption

1. `cat progress.json` and `tail -50 logs/generation_log.txt`
2. Find the first incomplete step in Section 8's order.
3. Re-run that script — batches/steps already marked done are skipped.
4. If a script crashed mid-batch: each generation script should use deterministic IDs
   (e.g. `ACC-{:06d}`, `TXN-{:08d}`) and `INSERT OR IGNORE`, so re-running a batch is
   always safe even if it partially completed.
5. Given the 16-hour budget, if you're past hour ~12 and still on data generation
   (steps 1-9), consider cutting `transactions_target` down further (e.g. to 100,000)
   rather than risk not finishing export/comparison-report — those two are the
   user-visible deliverables.

---

## 10. Open items to flag back to the user

Record in `progress.json.notes` and mention in the final summary:
- Which reference sources ended up "real" vs "fallback"
- Any schema surprises found in `inspect_inputs.py` that required deviating from this doc
- Final scale actually achieved (accounts/transactions) if reduced from targets
- Any exported file that still exceeds 90MB despite splitting, and why
