# garaza-fintech-146

Sanctions screening demo application — AI model, backend API, and frontend dashboard.

The system takes a name-match score from a screening engine and produces a **BLOCK / REVIEW / CLEAR** verdict using per-account dynamic thresholds driven by a five-component risk score. Everything is explained: each decision comes with an audit narrative, risk component breakdown, and the exact threshold values and formula that produced it.

---

## Repository layout

```
.
├── ai/                        ← Model documentation, trained models, inference module
│   ├── README.md              ← Comprehensive model docs (start here for AI context)
│   └── model/
│       ├── predict.py         ← Inference entry-point  →  screen(features) → verdict
│       ├── model_binary.ubj   ← XGBoost binary classifier (BLOCK vs not-BLOCK)
│       ├── model_multiclass.ubj ← XGBoost multiclass (BLOCK / REVIEW / CLEAR)
│       ├── model_metadata.json  ← Feature schema, threshold formulas, output contract
│       ├── xgb_results.json   ← Training metrics + feature importances
│       └── xgb_report.md      ← Human-readable training report
│
├── backend/
│   └── README.md              ← API spec, integration guide, endpoint reference
│
├── frontend/
│   └── README.md              ← Frontend guide (read this if you're building the UI)
│
└── project/                   ← Data generation pipeline (reproducible from raw inputs)
    ├── INSTRUCTIONS.md        ← Full pipeline spec
    ├── scripts/               ← 12 numbered generation scripts (00–11)
    ├── reference_data/        ← Derived CSVs from real OpenSanctions + IBM AML data
    ├── exports/               ← Parquet tables (loaded by backend)
    ├── progress.json          ← Checkpoint state
    ├── comparison_summary.md  ← Static vs dynamic threshold comparison report
    └── logs/
```

---

## The three sections

### AI — `ai/`

The core of the demo. An XGBoost-based screening model that computes **two dynamic thresholds per account** and uses them to produce a three-zone verdict.

**Decision logic:**

```
t_block  = clamp(75 − (overall_risk_score − 50) × 0.5,  40, 95)
t_review = clamp(50 − (overall_risk_score − 50) × 0.5,  20, 70)

match_score ≥ t_block            →  BLOCK   (automatic)
t_review ≤ match_score < t_block →  REVIEW  (human analyst)
match_score < t_review           →  CLEAR   (automatic pass)
```

A low-risk account (risk score = 10) gets `t_block = 95` — its name match must be near-perfect to trigger anything. A high-risk account (risk score = 90) gets `t_block = 55` — it triggers easily and has a wide review band. A static threshold at 65 ignores all of this, producing 2,301 false positives vs 1,043 for the dynamic model.

Every decision includes an audit narrative, risk component scores, and feature contributions. See [`ai/README.md`](ai/README.md) for the full model documentation.

**Quickstart:**

```python
from ai.model.predict import screen

result = screen({
    "account_type": "individual",
    "kyc_completeness": 0.95,
    "kyc_status": "complete",
    "is_pep": 0,
    "has_complex_ownership": 0,
    "shell_company_flag": 0,
    "activity_tier": "low",
    "account_status": "active",
    "match_score": 68.0,             # from screening system
    "shares_address_with_sanctioned": 0,
    "pep_exposure_score": 0.0,
    "country_risk_score": 12.0,
    "geographic_risk": 12.0,
    "identity_kyc_risk": 5.0,
    "pep_sanctions_risk": 8.0,
    "behavioural_risk": 8.0,
    "relationship_network_risk": 2.0,
    "overall_risk_score": 8.5,
    "override_applied": 0,
})

# result["verdict"]          → "CLEAR"
# result["t_block"]          → 95.0
# result["t_review"]         → 70.0
# result["block_probability"] → 0.0000
# result["audit_narrative"]  → "Verdict: CLEAR. The account's overall risk score of 8.5/100
#                               raised the block threshold to 95.0 ..."
```

---

### Backend — `backend/`

REST API that wraps the model and serves the dataset to the frontend. See [`backend/README.md`](backend/README.md) for the full endpoint spec.

Key endpoints:

| Method | Path | Description |
|---|---|---|
| `POST` | `/screen` | Run a live screening decision — returns verdict, thresholds, probabilities, audit |
| `GET` | `/accounts` | List accounts with risk_band / verdict filters |
| `GET` | `/accounts/{id}` | Account detail: risk score + latest screening + threshold decision |
| `GET` | `/accounts/{id}/transactions` | Transaction history with velocity data |
| `GET` | `/screening/{id}` | Full screening result + threshold decision + explanatory log |
| `GET` | `/dashboard/stats` | Aggregate stats for dashboard summary view |
| `GET` | `/thresholds/explain/{id}` | Formula breakdown showing exactly why t_block and t_review are what they are |

Recommended stack: **FastAPI** (Python) — keeps model import in-process, no IPC overhead.

---

### Frontend — `frontend/`

Demo dashboard. See [`frontend/README.md`](frontend/README.md) for the full guide (written for the frontend developer joining the project).

Key views to build:

- **Dashboard** — verdict distribution, risk band counts, divergence rate (static vs dynamic)
- **Account Explorer** — searchable/filterable account table
- **Account Detail** — threshold visualisation (coloured zones, match_score marker, t_review and t_block boundary lines), risk component breakdown, audit panel
- **Live Screener** — form that calls `POST /screen` and renders the decision in real time
- **Screening Queue** — REVIEW-verdict accounts for simulated human review

The **threshold visualisation** is the key UI component: a 0–100 horizontal bar with green (CLEAR), amber (REVIEW), and red (BLOCK) zones that shifts per account, making the dynamic nature immediately visible.

---

## Dataset

Generated by the pipeline in `project/`. All reference data sourced from real public datasets — no synthetic fallbacks.

| Table | Rows | Description |
|---|---|---|
| `accounts` | 20,000 | Synthetic customers (75 sanctioned, 100 PEP-injected) |
| `account_relationships` | 13,088 | Ownership/family/directorship edges (1,499 real FTM) |
| `wallets` | 3,379 | Crypto addresses (real sanctioned addresses where available) |
| `transactions` | 199,387 | Payments with AML-derived distributions |
| `screening_results` | 39,938 | Account + transaction-level verdicts |
| `risk_scores` | 20,000 | Five-component risk scores |
| `threshold_decisions` | 39,938 | Static vs dynamic comparison per event |
| `explanatory_logs` | 3,378 | Audit narratives for high-risk and divergent decisions |

Load any table:

```python
import pandas as pd
df = pd.read_parquet("project/exports/accounts.parquet")
```

---

## Model performance

| Model | Metric | Score |
|---|---|---|
| Binary (BLOCK vs not-BLOCK) | CV ROC-AUC (5-fold) | 0.9999 ± 0.0001 |
| Binary | CV F1-BLOCK (5-fold) | 0.961 ± 0.037 |
| Multiclass (BLOCK/REVIEW/CLEAR) | CV macro-F1 (5-fold) | 0.9964 ± 0.0066 |

Static vs dynamic threshold comparison (on 39,938 screening events):

| | Static (threshold=65) | Dynamic (risk-adjusted) |
|---|---|---|
| Precision | 0.434 | **0.628** |
| Recall | 1.000 | 1.000 |
| F1 | 0.605 | **0.772** |
| False positives | 2,301 | **1,043** |
| Verdicts differ | — | 3,266 events (8.2%) |

---

## Dependencies

```bash
pip install pandas numpy faker pyarrow ijson ujson xgboost scikit-learn
```

For data generation pipeline only (not needed to run the model):
`faker ijson ujson` are pipeline-only.

---

## Reproducing the dataset

```bash
# 1. Inspect raw input schemas
python project/scripts/inspect_inputs.py

# 2–11. Build reference data, schema, accounts, relationships,
#        transactions, screening, risk scores, thresholds, logs, export
python project/scripts/01_build_reference_data.py
python project/scripts/00_init_db.py
python project/scripts/02_generate_accounts.py
python project/scripts/03_generate_relationships.py
python project/scripts/04_generate_transactions.py
python project/scripts/05_generate_screening_results.py
python project/scripts/06_compute_risk_scores.py
python project/scripts/07_compute_dynamic_thresholds.py
python project/scripts/08_generate_explanatory_logs.py
python project/scripts/09_comparison_report.py
python project/scripts/10_export.py

# 12. Train XGBoost
python project/scripts/11_train_xgboost.py
```

Each script is idempotent — completed batches are skipped via `project/progress.json`. Raw input files (~3 GB) are not committed; see `project/INSTRUCTIONS.md` for download links.
