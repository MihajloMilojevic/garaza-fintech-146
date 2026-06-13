# garaza-fintech-146

Synthetic dataset and end-to-end pipeline for **sanctions screening**, **customer risk scoring**, and **dynamic threshold modelling** in a fintech/compliance context.

Built as a self-contained code + data deliverable: every pipeline step is reproducible from the scripts in `project/scripts/` given the original raw inputs (OpenSanctions exports + IBM AML dataset).

---

## What this is

A relationally-consistent synthetic dataset designed to support:

1. **Customer risk score model** — five-component weighted score (geographic, KYC, PEP/sanctions, behavioural, network)
2. **Dynamic threshold model** — per-account block/review thresholds that adapt to risk context, compared against a static baseline
3. **Explainability audit logs** — SHAP-style narrative logs for high-risk decisions
4. **Static vs dynamic threshold comparison** — quantified impact of risk-adaptive thresholds

All reference data was sourced from real public datasets (OpenSanctions, IBM AML) — no synthetic fallbacks were triggered.

---

## Dataset at a glance

| Table | Rows | Description |
|---|---|---|
| `accounts` | 20,000 | Synthetic customer accounts (75 sanctioned, 100 PEP-injected) |
| `account_relationships` | 13,088 | Ownership, family, directorship edges (1,499 real FTM edges) |
| `wallets` | 3,379 | Crypto wallet addresses (real sanctioned addresses where available) |
| `transactions` | 199,387 | Payments with AML-derived amount/timing distributions |
| `screening_results` | 39,938 | Account + transaction-level screening verdicts |
| `risk_scores` | 20,000 | Five-component risk scores per account |
| `threshold_decisions` | 39,938 | Static vs dynamic threshold comparison per screening event |
| `explanatory_logs` | 3,378 | Narrative explanations for high-risk accounts and divergent decisions |

### Screening verdict distribution (account-level)

| Verdict | Count | % |
|---|---|---|
| BLOCK | 47 | 0.23% |
| REVIEW | 906 | 4.53% |
| CLEAR | 19,047 | 95.24% |

Account-level BLOCK rate: **0.23%** — within the realistic 0.2–0.5% target range.

### Risk band distribution

| Band | Count |
|---|---|
| CRITICAL | 201 |
| HIGH | 38 |
| MEDIUM | 508 |
| LOW | 19,253 |

---

## Reference data sources

All sourced from real public data:

| Source | Details |
|---|---|
| Sanctioned entities | 8,000 entities from [OpenSanctions](https://opensanctions.org) `targets.simple.csv` (2,463 CryptoWallet) |
| FTM relationships | 1,499 edges extracted from `entities.ftm.json` (Ownership, Family, Directorship) |
| PEPs | 3,000 persons sampled from 754,598 in OpenSanctions PEP dataset |
| Fuzzy-match calibration | Jaro-Winkler distributions from 85,144 positive / 11,820 negative pairs |
| AML transaction shapes | Amount, hour-of-day, day-of-week distributions from 500k IBM HI-Small rows |
| Country risk | Curated 226-country list (FATF grey/black, OFAC sanctioned, Basel AML proxy scores) |

---

## Static vs dynamic threshold comparison

The dynamic threshold lowers the block threshold for high-risk accounts and raises it for low-risk ones, reducing false positives without sacrificing recall.

| Metric | Static (75/50) | Dynamic (risk-adjusted) |
|---|---|---|
| Precision | 0.566 | **0.630** |
| Recall | 1.000 | 1.000 |
| F1 | 0.723 | **0.773** |
| False positives | 1,350 | **1,034** |

Verdicts differ in **1,639 of 39,938 decisions (4.1%)**.

---

## XGBoost first pass

Trained on account-level screening results (20,000 rows) using risk score components + threshold features as inputs and `verdict_ground_truth` as label.

| Model | CV metric | Score |
|---|---|---|
| Binary (BLOCK vs not-BLOCK) | ROC-AUC (5-fold) | **1.0000 ± 0.0000** |
| Binary | F1-BLOCK (5-fold) | **1.0000 ± 0.0000** |
| Multiclass (BLOCK/REVIEW/CLEAR) | Macro-F1 (5-fold) | **0.9998 ± 0.0004** |

**Learnability: PASS.** Perfect CV scores are expected for a synthetic dataset where labels are derived deterministically from the features — they confirm no contradictions or label bugs. For a realistic evaluation, introduce label noise or hold out accounts screened under a different ruleset.

Top features (binary model): `hops_to_sanctioned` (0.547), `name_match_type_enc` (0.291), `pep_sanctions_risk` (0.154).

---

## Repository layout

```
.
├── project/
│   ├── INSTRUCTIONS.md             # Full pipeline spec
│   ├── progress.json               # Checkpoint state (all steps complete)
│   ├── comparison_summary.md       # Static vs dynamic report
│   ├── comparison_summary.json
│   ├── scripts/
│   │   ├── inspect_inputs.py       # Schema inspection (run first)
│   │   ├── 00_init_db.py           # Create SQLite schema
│   │   ├── 01_build_reference_data.py
│   │   ├── 02_generate_accounts.py
│   │   ├── 03_generate_relationships.py
│   │   ├── 04_generate_transactions.py
│   │   ├── 05_generate_screening_results.py
│   │   ├── 06_compute_risk_scores.py
│   │   ├── 07_compute_dynamic_thresholds.py
│   │   ├── 08_generate_explanatory_logs.py
│   │   ├── 09_comparison_report.py
│   │   ├── 10_export.py
│   │   └── 11_train_xgboost.py
│   ├── reference_data/             # Derived CSVs/JSONs (committed)
│   └── exports/                    # Parquet tables + models (committed)
│       ├── accounts.parquet
│       ├── transactions.parquet
│       ├── screening_results.parquet
│       ├── risk_scores.parquet
│       ├── threshold_decisions.parquet
│       ├── account_relationships.parquet
│       ├── wallets.parquet
│       ├── explanatory_logs.parquet
│       ├── model_binary.ubj        # XGBoost binary classifier
│       ├── model_multiclass.ubj    # XGBoost multiclass classifier
│       ├── xgb_results.json
│       ├── xgb_report.md
│       └── load_dataset.py         # Helper to load parquet tables
└── README.md
```

Not committed (listed in `.gitignore`): `data/raw/` (raw inputs, ~3GB), `*.db` (SQLite working file), `__pycache__/`.

---

## Loading the data

```python
import sys
sys.path.insert(0, "project/exports")
from load_dataset import load_table

accounts     = load_table("accounts")
transactions = load_table("transactions")
screening    = load_table("screening_results")
risk_scores  = load_table("risk_scores")
thresholds   = load_table("threshold_decisions")
```

Or directly with pandas/pyarrow:

```python
import pandas as pd

df = pd.read_parquet("project/exports/accounts.parquet")
```

---

## Reproducing from scratch

```bash
pip install pandas numpy faker pyarrow ijson ujson xgboost scikit-learn

# 1. Inspect raw input schemas
python project/scripts/inspect_inputs.py

# 2. Build reference data from raw inputs
python project/scripts/01_build_reference_data.py

# 3. Initialize DB schema
python project/scripts/00_init_db.py

# 4–10. Generate dataset (batched, resumable via progress.json)
python project/scripts/02_generate_accounts.py
python project/scripts/03_generate_relationships.py
python project/scripts/04_generate_transactions.py
python project/scripts/05_generate_screening_results.py
python project/scripts/06_compute_risk_scores.py
python project/scripts/07_compute_dynamic_thresholds.py
python project/scripts/08_generate_explanatory_logs.py

# 11. Reports + export
python project/scripts/09_comparison_report.py
python project/scripts/10_export.py

# 12. XGBoost first pass
python project/scripts/11_train_xgboost.py
```

Each script is idempotent — completed batches are skipped based on `progress.json`. See `project/INSTRUCTIONS.md` for the full spec.

---

## Risk score formula

```
overall_risk_score = (
    0.25 × geographic_risk       +
    0.15 × identity_kyc_risk     +
    0.30 × pep_sanctions_risk    +
    0.20 × behavioural_risk      +
    0.10 × relationship_network_risk
)
```

## Dynamic threshold formula

```
risk_adjustment   = (overall_risk_score − 50) × 0.3   # range −15 to +15
dynamic_t_block  = clamp(75 − risk_adjustment, 40, 90)
dynamic_t_review = clamp(50 − risk_adjustment, 25, 65)
```

High-risk accounts get a lower block threshold (more sensitive); low-risk accounts get a higher one (fewer false positives).
