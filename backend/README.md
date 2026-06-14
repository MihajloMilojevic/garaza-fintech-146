# Backend — Sanctions Screening API

REST API layer that wraps the AI screening model and serves data to the frontend dashboard.

---

## Purpose

The backend sits between the AI model and the frontend. It:

- Loads account, risk score, transaction, and screening result data from the parquet exports in `project/exports/`
- Exposes that data over a REST API with filtering and pagination
- Calls `ai/model/predict.py`'s `screen()` function to run live screening decisions
- Returns threshold explanations, audit narratives, and risk component breakdowns

---

## Recommended Tech Stack

**FastAPI (Python)** — strongly recommended over Node.js for this project.

The AI model is pure Python (XGBoost + NumPy). Wrapping it in FastAPI means you import it directly:

```python
from ai.model.predict import screen
```

No subprocess spawning, no stdin/stdout serialisation, no IPC overhead. The model is in-process. FastAPI also gives you automatic OpenAPI docs at `/docs` for free, which is useful when building the frontend.

If you prefer Node.js, you would have to shell out to Python for every screening call, which adds latency and complexity. Stick with FastAPI.

---

## Project Layout (suggested)

```
backend/
├── main.py            # FastAPI app entrypoint
├── routers/
│   ├── screen.py      # POST /screen, GET /thresholds/explain/{account_id}
│   ├── accounts.py    # GET /accounts, GET /accounts/{id}, GET /accounts/{id}/transactions
│   ├── screening.py   # GET /screening, GET /screening/{id}
│   └── dashboard.py   # GET /dashboard/stats
├── data/
│   └── loader.py      # load parquet files into memory / DuckDB
└── requirements.txt
```

---

## Integrating the AI Model

The model lives at `ai/model/predict.py` relative to the repo root. From inside `backend/`, add the repo root to `sys.path` so the import resolves:

```python
import sys
from pathlib import Path

# Add repo root so `ai.model.predict` is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.model.predict import screen
```

The `screen()` function is thread-safe after the first call (models are loaded once into module globals). You can call it from async FastAPI endpoints via `asyncio.run_in_executor` if you want to keep the event loop unblocked, but for a demo a direct call is fine.

### Input shape

```python
result = screen({
    # Account identity
    "account_type":               "individual",  # "individual" | "business"
    "kyc_completeness":           0.85,           # 0.0–1.0
    "kyc_status":                 "complete",     # complete | partial | pending | expired
    "is_pep":                     0,              # 0 | 1
    "has_complex_ownership":      0,
    "shell_company_flag":         0,
    "activity_tier":              "medium",       # low | medium | high
    "account_status":             "active",       # active | suspended | closed
    # Screening event
    "match_score":                72.5,           # 0–100 from name-matching engine
    "shares_address_with_sanctioned": 0,
    "pep_exposure_score":         0.0,
    "country_risk_score":         35.0,
    # Pre-computed risk components (or 0 to let model estimate)
    "geographic_risk":            35.0,
    "identity_kyc_risk":          15.0,
    "pep_sanctions_risk":         55.0,
    "behavioural_risk":           20.0,
    "relationship_network_risk":  5.0,
    "overall_risk_score":         30.0,
    "override_applied":           0,
})
```

### Output shape

```python
{
    "verdict":             "REVIEW",     # BLOCK | REVIEW | CLEAR
    "t_block":             80.0,         # block threshold for this account
    "t_review":            55.0,         # review threshold for this account
    "match_score":         72.5,
    "overall_risk_score":  30.0,
    "block_probability":   0.312,        # P(BLOCK) from binary XGBoost model
    "class_probabilities": {"BLOCK": 0.312, "CLEAR": 0.481, "REVIEW": 0.207},
    "risk_components": {
        "geographic_risk":           35.0,
        "identity_kyc_risk":         15.0,
        "pep_sanctions_risk":        55.0,
        "behavioural_risk":          20.0,
        "relationship_network_risk":  5.0,
    },
    "feature_contributions": [
        {"feature": "match_score", "importance": 0.312, "value": 72.5, "contribution_pct": 22.6},
        ...
    ],
    "audit_narrative":  "Verdict: REVIEW. The account's overall risk score of 30.0/100 raised the block threshold ...",
    "audit_factors":    ["match score = 72.5 ...", "pep sanctions risk = 55.0 ..."],
}
```

---

## Data Sources

All data lives in `project/exports/` as parquet files. Load them at startup:

```python
import duckdb

con = duckdb.connect()
con.execute("CREATE VIEW accounts AS SELECT * FROM read_parquet('project/exports/accounts.parquet')")
con.execute("CREATE VIEW risk_scores AS SELECT * FROM read_parquet('project/exports/risk_scores.parquet')")
con.execute("CREATE VIEW transactions AS SELECT * FROM read_parquet('project/exports/transactions.parquet')")
con.execute("CREATE VIEW screening_results AS SELECT * FROM read_parquet('project/exports/screening_results.parquet')")
```

DuckDB queries return Arrow/pandas results you can serialise directly to JSON. Alternatively load into pandas DataFrames and filter in Python — fine for a demo dataset.

---

## API Endpoints

### POST /screen

Run a live screening decision through the AI model.

**Request body** (`application/json`):

```json
{
  "account_type": "individual",
  "kyc_completeness": 0.85,
  "kyc_status": "complete",
  "is_pep": 0,
  "has_complex_ownership": 0,
  "shell_company_flag": 0,
  "activity_tier": "medium",
  "account_status": "active",
  "match_score": 72.5,
  "shares_address_with_sanctioned": 0,
  "pep_exposure_score": 0.0,
  "country_risk_score": 35.0,
  "geographic_risk": 35.0,
  "identity_kyc_risk": 15.0,
  "pep_sanctions_risk": 55.0,
  "behavioural_risk": 20.0,
  "relationship_network_risk": 5.0,
  "overall_risk_score": 30.0,
  "override_applied": 0
}
```

**Response** `200 OK`:

```json
{
  "verdict": "REVIEW",
  "t_block": 85.0,
  "t_review": 60.0,
  "match_score": 72.5,
  "overall_risk_score": 30.0,
  "block_probability": 0.2341,
  "class_probabilities": {
    "BLOCK": 0.2341,
    "CLEAR": 0.5102,
    "REVIEW": 0.2557
  },
  "risk_components": {
    "geographic_risk": 35.0,
    "identity_kyc_risk": 15.0,
    "pep_sanctions_risk": 55.0,
    "behavioural_risk": 20.0,
    "relationship_network_risk": 5.0
  },
  "feature_contributions": [
    {"feature": "match_score", "importance": 0.312, "value": 72.5, "contribution_pct": 22.6},
    {"feature": "pep_sanctions_risk", "importance": 0.198, "value": 55.0, "contribution_pct": 10.9},
    {"feature": "overall_risk_score", "importance": 0.143, "value": 30.0, "contribution_pct": 4.3}
  ],
  "audit_narrative": "Verdict: REVIEW. The account's overall risk score of 30.0/100 raised the block threshold from the static baseline of 75.0 to 85.0 and the review threshold to 60.0, reflecting a low-risk profile. The screening system produced a match score of 72.5/100. match score 72.5 is between review threshold 60.0 and block threshold 85.0 → routed to human analyst.",
  "audit_factors": [
    "match score = 72.5 (importance 0.312, contribution 22.6%)",
    "pep sanctions risk = 55.0 (importance 0.198, contribution 10.9%)",
    "overall risk score = 30.0 (importance 0.143, contribution 4.3%)"
  ]
}
```

---

### GET /accounts

List accounts with pagination and optional filters.

**Query parameters**:

| Parameter   | Type    | Default | Description                                     |
|-------------|---------|---------|------------------------------------------------|
| `page`      | integer | 1       | Page number (1-indexed)                         |
| `limit`     | integer | 50      | Results per page (max 200)                      |
| `risk_band` | string  | —       | Filter by risk band: `low`, `medium`, `high`, `critical` |
| `verdict`   | string  | —       | Filter by latest screening verdict: `BLOCK`, `REVIEW`, `CLEAR` |
| `search`    | string  | —       | Partial match on account name or ID             |

**Response** `200 OK`:

```json
{
  "total": 1240,
  "page": 1,
  "limit": 50,
  "accounts": [
    {
      "account_id": "ACC-00042",
      "account_type": "business",
      "kyc_status": "complete",
      "account_status": "active",
      "overall_risk_score": 78.4,
      "risk_band": "high",
      "latest_verdict": "REVIEW",
      "created_at": "2024-03-15"
    }
  ]
}
```

---

### GET /accounts/{account_id}

Full account detail: account row + risk score row + latest screening result + threshold breakdown.

**Path parameter**: `account_id` — string account identifier.

**Response** `200 OK`:

```json
{
  "account": {
    "account_id": "ACC-00042",
    "account_type": "business",
    "kyc_completeness": 0.72,
    "kyc_status": "partial",
    "is_pep": 0,
    "has_complex_ownership": 1,
    "shell_company_flag": 0,
    "activity_tier": "high",
    "account_status": "active",
    "shares_address_with_sanctioned": 0
  },
  "risk_score": {
    "overall_risk_score": 78.4,
    "risk_band": "high",
    "geographic_risk": 65.0,
    "identity_kyc_risk": 40.0,
    "pep_sanctions_risk": 20.0,
    "behavioural_risk": 55.0,
    "relationship_network_risk": 30.0,
    "scored_at": "2025-06-10T14:23:00Z"
  },
  "latest_screening": {
    "screening_id": "SCR-00891",
    "verdict": "REVIEW",
    "match_score": 61.2,
    "context": "transaction",
    "screened_at": "2025-06-13T09:11:00Z"
  },
  "threshold_decision": {
    "t_block": 63.8,
    "t_review": 38.8,
    "match_score": 61.2,
    "verdict": "REVIEW",
    "zone": "match_score 61.2 is between t_review 38.8 and t_block 63.8"
  }
}
```

---

### GET /accounts/{account_id}/transactions

Transactions for an account, with rolling velocity fields.

**Query parameters**:

| Parameter | Type    | Default | Description                  |
|-----------|---------|---------|------------------------------|
| `page`    | integer | 1       |                              |
| `limit`   | integer | 50      |                              |
| `from`    | string  | —       | ISO date filter start        |
| `to`      | string  | —       | ISO date filter end          |

**Response** `200 OK`:

```json
{
  "account_id": "ACC-00042",
  "total": 87,
  "transactions": [
    {
      "transaction_id": "TXN-004291",
      "amount": 14500.00,
      "currency": "EUR",
      "transaction_type": "wire_transfer",
      "counterparty_country": "AE",
      "timestamp": "2025-06-12T16:44:00Z",
      "tx_count_7d": 12,
      "tx_amount_7d": 87600.0,
      "tx_count_30d": 34,
      "tx_amount_30d": 210400.0
    }
  ]
}
```

---

### GET /screening

List screening results with filters.

**Query parameters**:

| Parameter        | Type    | Default | Description                                      |
|------------------|---------|---------|--------------------------------------------------|
| `verdict`        | string  | —       | `BLOCK`, `REVIEW`, or `CLEAR`                    |
| `context`        | string  | —       | `onboarding`, `transaction`, `periodic_review`   |
| `min_match_score`| float   | —       | Only return results with match_score ≥ this value |
| `verdicts_differ`| boolean | —       | If true, return only results where threshold verdict differs from model classification |
| `page`           | integer | 1       |                                                  |
| `limit`          | integer | 50      |                                                  |

**Response** `200 OK`:

```json
{
  "total": 312,
  "page": 1,
  "limit": 50,
  "results": [
    {
      "screening_id": "SCR-00891",
      "account_id": "ACC-00042",
      "verdict": "REVIEW",
      "match_score": 61.2,
      "context": "transaction",
      "t_block": 63.8,
      "t_review": 38.8,
      "screened_at": "2025-06-13T09:11:00Z"
    }
  ]
}
```

---

### GET /screening/{screening_id}

Full screening result, including threshold decision and the complete audit trail.

**Response** `200 OK`:

```json
{
  "screening_id": "SCR-00891",
  "account_id": "ACC-00042",
  "verdict": "REVIEW",
  "match_score": 61.2,
  "context": "transaction",
  "screened_at": "2025-06-13T09:11:00Z",
  "threshold_decision": {
    "t_block": 63.8,
    "t_review": 38.8,
    "match_score": 61.2,
    "verdict": "REVIEW",
    "formula": {
      "overall_risk_score": 78.4,
      "adjustment": "(78.4 - 50.0) × 0.5 = 14.2",
      "t_block_raw": "75.0 - 14.2 = 60.8 → clamped to 63.8",
      "t_review_raw": "50.0 - 14.2 = 35.8 → clamped to 38.8"
    }
  },
  "audit_narrative": "Verdict: REVIEW. The account's overall risk score of 78.4/100 ...",
  "audit_factors": [
    "behavioural risk = 55.0 (importance 0.198, contribution 10.9%)",
    "match score = 61.2 (importance 0.312, contribution 19.1%)"
  ],
  "risk_components": {
    "geographic_risk": 65.0,
    "identity_kyc_risk": 40.0,
    "pep_sanctions_risk": 20.0,
    "behavioural_risk": 55.0,
    "relationship_network_risk": 30.0
  },
  "class_probabilities": {
    "BLOCK": 0.1812,
    "CLEAR": 0.3901,
    "REVIEW": 0.4287
  },
  "block_probability": 0.1812,
  "feature_contributions": [
    {"feature": "match_score", "importance": 0.312, "value": 61.2, "contribution_pct": 19.1},
    {"feature": "behavioural_risk", "importance": 0.198, "value": 55.0, "contribution_pct": 10.9}
  ]
}
```

---

### GET /dashboard/stats

Aggregate statistics for the dashboard home page.

**Response** `200 OK`:

```json
{
  "verdict_distribution": {
    "BLOCK": 87,
    "REVIEW": 312,
    "CLEAR": 841
  },
  "risk_band_counts": {
    "low": 520,
    "medium": 410,
    "high": 240,
    "critical": 70
  },
  "verdicts_differ_pct": 4.2,
  "total_accounts": 1240,
  "total_screening_results": 1240,
  "top_risk_accounts": [
    {
      "account_id": "ACC-00099",
      "overall_risk_score": 96.2,
      "risk_band": "critical",
      "latest_verdict": "BLOCK",
      "match_score": 98.0
    }
  ]
}
```

`verdicts_differ_pct` is the percentage of screening results where the threshold-based verdict (`BLOCK`/`REVIEW`/`CLEAR`) differs from the multiclass model's argmax prediction. This is an interesting metric for the demo — it shows cases where the rule-based threshold and the model disagree.

---

### GET /thresholds/explain/{account_id}

Returns the two dynamic thresholds for an account, with a step-by-step formula breakdown showing exactly why t_block and t_review are what they are for this account.

**Response** `200 OK`:

```json
{
  "account_id": "ACC-00042",
  "overall_risk_score": 78.4,
  "t_block": 63.8,
  "t_review": 38.8,
  "formula": {
    "baseline_t_block": 75.0,
    "baseline_t_review": 50.0,
    "adjustment_factor": 0.5,
    "risk_deviation": "78.4 - 50.0 = 28.4",
    "adjustment": "28.4 × 0.5 = 14.2",
    "t_block_unclamped": "75.0 - 14.2 = 60.8",
    "t_block_clamp_range": "[40.0, 95.0]",
    "t_block_final": 63.8,
    "t_review_unclamped": "50.0 - 14.2 = 35.8",
    "t_review_clamp_range": "[20.0, 70.0]",
    "t_review_final": 38.8,
    "interpretation": "This account has above-average risk (78.4 > 50). Thresholds are lowered, making it easier to trigger BLOCK or REVIEW. A lower-risk account with score 20 would have t_block=87.5 and t_review=65.0."
  },
  "decision_zones": {
    "BLOCK":  "match_score ≥ 63.8",
    "REVIEW": "38.8 ≤ match_score < 63.8",
    "CLEAR":  "match_score < 38.8"
  }
}
```

---

## Environment Setup

### Requirements

```
fastapi
uvicorn[standard]
duckdb
pandas
pyarrow
xgboost
numpy
```

Install:

```bash
pip install -r requirements.txt
```

### Running locally

```bash
cd backend
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Auto-generated docs at `http://localhost:8000/docs`.

### Environment variables

| Variable            | Default                   | Description                              |
|---------------------|---------------------------|------------------------------------------|
| `EXPORTS_DIR`       | `../project/exports/`     | Path to parquet export directory         |
| `PORT`              | `8000`                    | Port for uvicorn                         |

---

## Notes

- The model loads on first call and stays in memory. Cold start adds ~1–2 seconds; subsequent calls are fast.
- All parquet files are read-only for this demo — no database writes needed.
- CORS: enable `fastapi.middleware.cors.CORSMiddleware` to allow the frontend dev server (typically `http://localhost:5173`) to call the API.
