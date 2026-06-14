# Backend — Sanctions Screening API

FastAPI backend that wraps the AI screening model and serves data to the frontend dashboard.

---

## Running the server

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

- API base URL: `http://localhost:8000`
- Interactive docs (Swagger UI): `http://localhost:8000/docs`
- Alternative docs (ReDoc): `http://localhost:8000/redoc`

**Environment variables**

| Variable      | Default                        | Description                       |
|---------------|--------------------------------|-----------------------------------|
| `EXPORTS_DIR` | `../project/exports/`          | Path to the parquet data directory |
| `PORT`        | `8000`                         | Uvicorn port                      |

CORS is open (`allow_origins=["*"]`), so no proxy config is needed during frontend development.

---

## Architecture overview

On startup, the server reads all parquet files into memory and precomputes two joined views:

- **`accounts_enriched`** — accounts joined with risk scores and each account's latest account-level screening verdict. Used by `GET /accounts` and `GET /accounts/{id}`.
- **`screening_merged`** — screening results joined with threshold decisions. Used by `GET /screening` and `GET /screening/{id}`.

Endpoints that return a single account or screening call the AI model (`ai/model/predict.screen()`) live to produce the audit narrative, feature contributions, and class probabilities. This adds ~5–20 ms per call after the model warms up.

---

## Data model quick reference

**Verdicts** (always uppercase): `BLOCK` | `REVIEW` | `CLEAR`

**Risk bands** (always uppercase): `LOW` | `MEDIUM` | `HIGH` | `CRITICAL`

**Screening contexts**: `account` (one per account, run at onboarding) | `transaction` (run on individual payments)

**Threshold logic** (what the AI model does):
```
t_block  = clamp(75 − (overall_risk_score − 50) × 0.5,  40, 95)
t_review = clamp(50 − (overall_risk_score − 50) × 0.5,  20, 70)

match_score ≥ t_block              →  BLOCK  (automatic)
t_review ≤ match_score < t_block   →  REVIEW (human review)
match_score < t_review             →  CLEAR  (automatic pass)
```

High-risk accounts have lower thresholds (easier to trigger). Low-risk accounts have higher thresholds (harder to trigger). A static threshold of 65 ignores all of this.

---

## Endpoints

### `GET /dashboard/stats`

Aggregate statistics for the dashboard home view.

**No parameters.**

**Response `200 OK`:**

```json
{
  "verdict_distribution": {
    "BLOCK": 80,
    "REVIEW": 312,
    "CLEAR": 19608
  },
  "risk_band_counts": {
    "low": 19253,
    "medium": 508,
    "high": 38,
    "critical": 201
  },
  "verdicts_differ_count": 3266,
  "verdicts_differ_pct": 8.18,
  "total_accounts": 20000,
  "total_screening_events": 39938,
  "top_risk_accounts": [
    {
      "account_id": "ACC-014265",
      "full_name": "Hamilton Group",
      "overall_risk_score": 94.958,
      "risk_band": "CRITICAL",
      "latest_verdict": "CLEAR",
      "match_score": 14.66
    }
  ]
}
```

**Field notes:**
- `verdict_distribution` — counts from the account-level screening for each account (one per account, 20 000 total). These are the primary verdicts for the dashboard.
- `risk_band_counts` — keys are lowercase (`low`, `medium`, `high`, `critical`).
- `verdicts_differ_count` / `verdicts_differ_pct` — how many of the 39 938 total screening events (account + transaction) had the dynamic threshold verdict disagree with the XGBoost model's own argmax prediction. This is the "AI vs rules" divergence metric.
- `top_risk_accounts` — top 5 by `overall_risk_score`, descending. Always 5 entries.

---

### `GET /accounts`

Paginated, filterable list of accounts.

**Query parameters:**

| Parameter   | Type    | Default | Description |
|-------------|---------|---------|-------------|
| `page`      | integer | `1`     | 1-indexed page number |
| `limit`     | integer | `50`    | Results per page, max `200` |
| `risk_band` | string  | —       | Filter by risk band. Case-insensitive. Values: `low`, `medium`, `high`, `critical` |
| `verdict`   | string  | —       | Filter by latest account-level verdict. Case-insensitive. Values: `BLOCK`, `REVIEW`, `CLEAR` |
| `search`    | string  | —       | Partial case-insensitive match on `account_id` or `full_name` |

**Response `200 OK`:**

```json
{
  "total": 20000,
  "page": 1,
  "limit": 50,
  "accounts": [
    {
      "account_id": "ACC-000001",
      "full_name": "María Luisa Isern Hernández",
      "account_type": "individual",
      "kyc_status": "complete",
      "account_status": "active",
      "overall_risk_score": 20.777,
      "risk_band": "LOW",
      "latest_verdict": "CLEAR",
      "latest_match_score": 11.68,
      "created_at": "2024-05-19 02:04:54"
    }
  ]
}
```

**Field notes:**
- `total` reflects the count after filters are applied, not the full 20 000.
- `risk_band` in the response is always uppercase (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`). The `risk_band` query parameter is case-insensitive.
- `latest_verdict` is from the account-level screening (context = `account`). Every account has exactly one.
- `latest_match_score` is the name match score (0–100) from that same account-level screening.
- `full_name` can contain Unicode (Arabic, Cyrillic, Chinese, etc.) — handle this in your rendering.

**Example filtered requests:**
```
GET /accounts?risk_band=critical&verdict=BLOCK&limit=10
GET /accounts?search=hamilton&limit=5
GET /accounts?page=3&limit=100
```

---

### `GET /accounts/{account_id}`

Full account detail: account info, risk score breakdown, latest screening, threshold decision, and live AI audit output.

**Path parameter:** `account_id` — e.g. `ACC-000054`

**Response `200 OK`:**

```json
{
  "account": {
    "account_id": "ACC-000054",
    "full_name": "Кравченко Марина Олександріна",
    "account_type": "individual",
    "kyc_completeness": 0.8493,
    "kyc_status": "complete",
    "is_pep": 0,
    "has_complex_ownership": 0,
    "shell_company_flag": 0,
    "activity_tier": "medium",
    "account_status": "suspended",
    "country_residence": "ua",
    "created_at": "2021-03-07 09:58:16"
  },
  "risk_score": {
    "overall_risk_score": 40.7085,
    "risk_band": "MEDIUM",
    "geographic_risk": 19.5,
    "identity_kyc_risk": 15.07,
    "pep_sanctions_risk": 98.2048,
    "behavioural_risk": 20.0,
    "relationship_network_risk": 1.1155,
    "scored_at": "2026-06-13T23:31:07"
  },
  "latest_screening": {
    "screening_id": "SCR-00000054",
    "verdict": "BLOCK",
    "match_score": 95.9666,
    "context": "account",
    "screened_at": "2026-06-13T23:31:07"
  },
  "threshold_decision": {
    "t_block": 79.6457,
    "t_review": 54.6457,
    "match_score": 95.9666,
    "verdict": "BLOCK",
    "zone": "match_score 95.9666 ≥ t_block 79.6457 → BLOCK"
  },
  "audit": {
    "verdict": "BLOCK",
    "block_probability": 0.9985,
    "class_probabilities": {
      "BLOCK": 0.9967,
      "CLEAR": 0.0017,
      "REVIEW": 0.0016
    },
    "audit_narrative": "Verdict: BLOCK. The account's overall risk score of 40.7/100 raised the block threshold from the static baseline of 75.0 to 79.6 and the review threshold to 54.6, reflecting a low-risk profile. The screening system produced a match score of 96.0/100. match score 96.0 ≥ block threshold 79.6 → automatic block.",
    "audit_factors": [
      "pep sanctions risk = 98.2 (importance 0.838, contribution 82.3%)",
      "match score = 96.0 (importance 0.123, contribution 11.8%)",
      "overall risk score = 40.7 (importance 0.025, contribution 1.0%)"
    ],
    "feature_contributions": [
      {
        "feature": "pep_sanctions_risk",
        "importance": 0.838,
        "value": 98.2,
        "contribution_pct": 82.3
      },
      {
        "feature": "match_score",
        "importance": 0.123,
        "value": 95.97,
        "contribution_pct": 11.8
      },
      {
        "feature": "overall_risk_score",
        "importance": 0.025,
        "value": 40.71,
        "contribution_pct": 1.02
      },
      {
        "feature": "override_applied",
        "importance": 0.006,
        "value": 0.0,
        "contribution_pct": 0.0
      }
    ],
    "risk_components": {
      "geographic_risk": 19.5,
      "identity_kyc_risk": 15.07,
      "pep_sanctions_risk": 98.2048,
      "behavioural_risk": 20.0,
      "relationship_network_risk": 1.1155
    }
  }
}
```

**Section breakdown:**

`account` — Basic account record.
- `account_type`: `"individual"` or `"business"`
- `kyc_completeness`: float 0.0–1.0
- `kyc_status`: `"complete"` | `"partial"` | `"pending"` | `"expired"`
- `is_pep`: `0` or `1`
- `has_complex_ownership`: `0` or `1`
- `shell_company_flag`: `0` or `1`
- `activity_tier`: `"low"` | `"medium"` | `"high"`
- `account_status`: `"active"` | `"suspended"` | `"closed"`

`risk_score` — Five-component risk breakdown. Components are weighted and combined into `overall_risk_score` (0–100):
```
overall = 0.25×geographic + 0.15×identity_kyc + 0.30×pep_sanctions + 0.20×behavioural + 0.10×relationship_network
```

`latest_screening` — The account-level screening event (the one run at onboarding/periodic review). `screened_at` is the risk score computation timestamp.

`threshold_decision` — The two thresholds calculated for this account and where the match score landed:
- `t_block`: score at or above which the account is automatically blocked
- `t_review`: score at or above which (but below `t_block`) the account is routed to human review
- `zone`: human-readable string describing the decision

`audit` — Live output from the AI model:
- `verdict`: the authoritative decision (`BLOCK` | `REVIEW` | `CLEAR`)
- `block_probability`: P(BLOCK) from the binary XGBoost classifier (0.0–1.0)
- `class_probabilities`: probabilities for all three classes from the multiclass model. Sum to approximately 1.0. Useful for showing how borderline a decision is.
- `audit_narrative`: plain-English paragraph explaining the decision. Display as body text.
- `audit_factors`: bullet points listing the top features that drove the decision.
- `feature_contributions`: ranked list of features by influence. `importance` is the XGBoost feature importance weight; `contribution_pct` is importance × normalised feature value, as a percentage of the total.
- `risk_components`: the five raw risk scores (same as `risk_score` section, repeated here for convenience).

**Errors:**
- `404` — account not found

---

### `GET /accounts/{account_id}/transactions`

Transactions sent by this account, sorted newest-first.

**Path parameter:** `account_id`

**Query parameters:**

| Parameter | Type    | Default | Description |
|-----------|---------|---------|-------------|
| `page`    | integer | `1`     | |
| `limit`   | integer | `50`    | Max `200` |
| `from`    | string  | —       | ISO datetime filter start (e.g. `2025-01-01T00:00:00`) |
| `to`      | string  | —       | ISO datetime filter end |

**Response `200 OK`:**

```json
{
  "account_id": "ACC-011291",
  "total": 122,
  "page": 1,
  "limit": 2,
  "transactions": [
    {
      "transaction_id": "TXN-00161244",
      "amount": 160.96,
      "currency": "GBP",
      "payment_rail": "crypto",
      "recipient_type": "crypto_wallet",
      "recipient_name": null,
      "recipient_country": "HR",
      "timestamp": "2026-05-22T00:18:34",
      "velocity_30d_count": 2,
      "velocity_30d_amount": 712559.76,
      "is_first_time_recipient": 1
    },
    {
      "transaction_id": "TXN-00143414",
      "amount": 712533.96,
      "currency": "GBP",
      "payment_rail": "wire",
      "recipient_type": "account",
      "recipient_name": "حسين هوشیار",
      "recipient_country": "XX",
      "timestamp": "2026-05-14T02:28:00",
      "velocity_30d_count": 1,
      "velocity_30d_amount": 25.8,
      "is_first_time_recipient": 1
    }
  ]
}
```

**Field notes:**
- `payment_rail`: `"wire"` | `"ach"` | `"crypto"` | `"card"` | `"internal"`
- `recipient_type`: `"account"` | `"crypto_wallet"` | `"external"`
- `recipient_name`: can be `null` for crypto wallet recipients
- `recipient_country`: ISO 3166-1 alpha-2 country code. `"XX"` = unknown/offshore.
- `velocity_30d_count` / `velocity_30d_amount`: rolling 30-day transaction count and total amount for this sender at the time of each transaction.
- `is_first_time_recipient`: `0` or `1` — whether this sender has ever sent to this recipient before.
- Some accounts have zero transactions — `total` will be `0` and `transactions` will be `[]`. This is normal for accounts that only had onboarding screenings.

**Errors:**
- `404` is not thrown for unknown account IDs; you'll get `total: 0` instead.

---

### `GET /screening`

List screening events with filters. Returns both account-level and transaction-level screenings (39 938 total).

**Query parameters:**

| Parameter         | Type    | Default | Description |
|-------------------|---------|---------|-------------|
| `page`            | integer | `1`     | |
| `limit`           | integer | `50`    | Max `200` |
| `verdict`         | string  | —       | `BLOCK`, `REVIEW`, or `CLEAR` (case-insensitive) |
| `context`         | string  | —       | `account` or `transaction` |
| `min_match_score` | float   | —       | Only return results where `match_score ≥` this value |
| `verdicts_differ` | boolean | —       | `true` = only return events where the threshold verdict differs from the model's argmax prediction |

**Response `200 OK`:**

```json
{
  "total": 1998,
  "page": 1,
  "limit": 1,
  "results": [
    {
      "screening_id": "SCR-00000029",
      "account_id": "ACC-000029",
      "verdict": "REVIEW",
      "match_score": 58.82,
      "context": "account",
      "t_block": 79.5872,
      "t_review": 54.5872,
      "verdicts_differ": false,
      "screened_at": "2026-06-13T23:31:07"
    }
  ]
}
```

**Field notes:**
- `verdict` is the dynamic threshold verdict (not the ground truth label).
- `verdicts_differ: true` means the threshold rule and the XGBoost model's argmax disagreed. These are the most interesting cases — the model was uncertain.
- `screened_at`: ISO datetime string. For transaction-level screenings, this is the transaction timestamp. For account-level screenings, this is the risk-score computation timestamp.

**Common use cases:**
```
GET /screening?verdict=REVIEW                        — screening queue (1 998 events)
GET /screening?context=transaction&verdict=BLOCK     — blocked transactions
GET /screening?verdicts_differ=true                  — cases where AI and rules disagree
GET /screening?min_match_score=80&verdict=CLEAR      — high match scores that cleared
```

---

### `GET /screening/{screening_id}`

Full screening detail with live AI audit output.

**Path parameter:** `screening_id` — e.g. `SCR-00000029`

**Response `200 OK`:**

```json
{
  "screening_id": "SCR-00000029",
  "account_id": "ACC-000029",
  "verdict": "REVIEW",
  "match_score": 58.82,
  "context": "account",
  "screened_at": "2026-06-13T23:31:07",
  "threshold_decision": {
    "t_block": 79.5872,
    "t_review": 54.5872,
    "match_score": 58.82,
    "verdict": "REVIEW",
    "formula": {
      "overall_risk_score": 40.8257,
      "adjustment": "(40.8257 - 50.0) × 0.5 = -4.59",
      "t_block_raw": "75.0 - -4.59 = 79.5872 → clamped to 79.5872",
      "t_review_raw": "50.0 - -4.59 = 54.5872 → clamped to 54.5872"
    }
  },
  "audit_narrative": "Verdict: REVIEW. The account's overall risk score of 40.8/100 raised the block threshold from the static baseline of 75.0 to 79.6 and the review threshold to 54.6, reflecting a low-risk profile. The screening system produced a match score of 58.8/100. match score 58.8 is between review threshold 54.6 and block threshold 79.6 → routed to human analyst.",
  "audit_factors": [
    "pep sanctions risk = 75.2 (importance 0.838, contribution 63.0%)",
    "match score = 58.8 (importance 0.123, contribution 7.2%)",
    "overall risk score = 40.8 (importance 0.025, contribution 1.0%)"
  ],
  "risk_components": {
    "geographic_risk": 14.4,
    "identity_kyc_risk": 18.09,
    "pep_sanctions_risk": 75.2283,
    "behavioural_risk": 58.8629,
    "relationship_network_risk": 1.7114
  },
  "class_probabilities": {
    "BLOCK": 0.0001,
    "CLEAR": 0.9984,
    "REVIEW": 0.0015
  },
  "block_probability": 0.0,
  "feature_contributions": [
    {
      "feature": "pep_sanctions_risk",
      "importance": 0.838,
      "value": 75.23,
      "contribution_pct": 63.04
    },
    {
      "feature": "match_score",
      "importance": 0.123,
      "value": 58.82,
      "contribution_pct": 7.23
    },
    {
      "feature": "overall_risk_score",
      "importance": 0.025,
      "value": 40.83,
      "contribution_pct": 1.02
    },
    {
      "feature": "override_applied",
      "importance": 0.006,
      "value": 0.0,
      "contribution_pct": 0.0
    }
  ]
}
```

**Field notes:**
- `threshold_decision.formula` — step-by-step strings showing the maths behind `t_block` and `t_review`. These are strings, not numbers, because they're display text. Use them to populate the "how was this calculated" tooltip in the UI.
- `class_probabilities` — from the multiclass XGBoost model. These can disagree with the verdict (which comes from the threshold rule, not argmax). Example: the verdict is `REVIEW` but `class_probabilities.CLEAR = 0.9984` — the model thinks it's likely CLEAR, but the threshold rule puts it in the REVIEW zone.
- `block_probability` — from a separate binary XGBoost classifier (BLOCK vs not-BLOCK). Can differ slightly from `class_probabilities.BLOCK`.

**Errors:**
- `404` — screening ID not found

---

### `POST /screen`

Run a live screening decision through the AI model. This is the core endpoint for the Live Screener page.

**Request body** (`application/json`):

All fields are optional except `match_score`. Defaults are used for missing fields.

```json
{
  "account_type": "individual",
  "kyc_completeness": 0.85,
  "kyc_status": "complete",
  "is_pep": 0,
  "has_complex_ownership": 0,
  "shell_company_flag": 0,
  "activity_tier": "low",
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

**Field constraints:**

| Field | Type | Range | Notes |
|-------|------|-------|-------|
| `match_score` | float | 0–100 | **Required.** Score from name-matching engine. |
| `overall_risk_score` | float | 0–100 | Drives the thresholds. Default: `20.0`. |
| `kyc_completeness` | float | 0.0–1.0 | Default: `0.8`. |
| `is_pep` | int | 0 or 1 | Default: `0`. |
| `has_complex_ownership` | int | 0 or 1 | Default: `0`. |
| `shell_company_flag` | int | 0 or 1 | Default: `0`. |
| `shares_address_with_sanctioned` | int | 0 or 1 | Default: `0`. |
| `override_applied` | int | 0 or 1 | Default: `0`. |
| `account_type` | string | `individual` \| `business` | Default: `individual`. |
| `kyc_status` | string | `complete` \| `partial` \| `pending` \| `expired` | Default: `complete`. |
| `activity_tier` | string | `low` \| `medium` \| `high` | Default: `low`. |
| `account_status` | string | `active` \| `suspended` \| `closed` | Default: `active`. |

**Response `200 OK` — BLOCK example** (`overall_risk_score=78`, `match_score=91`):

```json
{
  "verdict": "BLOCK",
  "t_block": 61.0,
  "t_review": 36.0,
  "match_score": 91.0,
  "overall_risk_score": 78.0,
  "block_probability": 0.9987,
  "class_probabilities": {
    "BLOCK": 0.2683,
    "CLEAR": 0.0041,
    "REVIEW": 0.7276
  },
  "risk_components": {
    "geographic_risk": 75.0,
    "identity_kyc_risk": 30.0,
    "pep_sanctions_risk": 90.0,
    "behavioural_risk": 60.0,
    "relationship_network_risk": 25.0
  },
  "feature_contributions": [
    { "feature": "pep_sanctions_risk", "importance": 0.838, "value": 90.0, "contribution_pct": 75.42 },
    { "feature": "match_score", "importance": 0.123, "value": 91.0, "contribution_pct": 11.19 },
    { "feature": "overall_risk_score", "importance": 0.025, "value": 78.0, "contribution_pct": 1.95 },
    { "feature": "override_applied", "importance": 0.006, "value": 0.0, "contribution_pct": 0.0 }
  ],
  "audit_narrative": "Verdict: BLOCK. The account's overall risk score of 78.0/100 lowered the block threshold from the static baseline of 75.0 to 61.0 and the review threshold to 36.0, reflecting a high-risk profile. The screening system produced a match score of 91.0/100. match score 91.0 ≥ block threshold 61.0 → automatic block.",
  "audit_factors": [
    "pep sanctions risk = 90.0 (importance 0.838, contribution 75.4%)",
    "match score = 91.0 (importance 0.123, contribution 11.2%)",
    "overall risk score = 78.0 (importance 0.025, contribution 1.9%)",
    "Account is flagged as a Politically Exposed Person (PEP)."
  ]
}
```

**Response `200 OK` — CLEAR example** (`overall_risk_score=8.5`, `match_score=22`):

```json
{
  "verdict": "CLEAR",
  "t_block": 95.0,
  "t_review": 70.0,
  "match_score": 22.0,
  "overall_risk_score": 8.5,
  "block_probability": 0.0,
  "class_probabilities": {
    "BLOCK": 0.0,
    "CLEAR": 1.0,
    "REVIEW": 0.0
  },
  "risk_components": {
    "geographic_risk": 12.0,
    "identity_kyc_risk": 5.0,
    "pep_sanctions_risk": 8.0,
    "behavioural_risk": 8.0,
    "relationship_network_risk": 2.0
  },
  "feature_contributions": [
    { "feature": "pep_sanctions_risk", "importance": 0.838, "value": 8.0, "contribution_pct": 6.7 },
    { "feature": "match_score", "importance": 0.123, "value": 22.0, "contribution_pct": 2.71 },
    { "feature": "overall_risk_score", "importance": 0.025, "value": 8.5, "contribution_pct": 0.21 },
    { "feature": "override_applied", "importance": 0.006, "value": 0.0, "contribution_pct": 0.0 }
  ],
  "audit_narrative": "Verdict: CLEAR. The account's overall risk score of 8.5/100 raised the block threshold from the static baseline of 75.0 to 95.0 and the review threshold to 70.0, reflecting a low-risk profile. The screening system produced a match score of 22.0/100. match score 22.0 < review threshold 70.0 → automatic pass.",
  "audit_factors": [
    "pep sanctions risk = 8.0 (importance 0.838, contribution 6.7%)",
    "match score = 22.0 (importance 0.123, contribution 2.7%)",
    "overall risk score = 8.5 (importance 0.025, contribution 0.2%)"
  ]
}
```

**Field notes:**
- The model's first call takes ~1–2 seconds (model loading). All subsequent calls are fast (~5–20 ms). Show a loading spinner.
- `t_block` and `t_review` are derived purely from `overall_risk_score` — they shift the zones left (high risk) or right (low risk) on the 0–100 bar.
- For the Live Screener slider demo: debounce the `POST /screen` call by ~300ms. Dragging the `match_score` slider will visibly flip the verdict as it crosses `t_review` and `t_block`.
- `audit_factors` will include additional plain-English flags for notable features (e.g. `"Account is flagged as a Politically Exposed Person (PEP)."`) — render these as bullet points.

**Errors:**
- `422` — validation error (e.g. `match_score` out of range or missing)

---

### `GET /thresholds/explain/{account_id}`

Returns the step-by-step threshold formula for a specific account. Use this to populate the "why is t_block = X?" tooltip or expandable section in the UI.

**Path parameter:** `account_id`

**Response `200 OK`:**

```json
{
  "account_id": "ACC-000054",
  "overall_risk_score": 40.7085,
  "t_block": 79.6457,
  "t_review": 54.6457,
  "formula": {
    "baseline_t_block": 75.0,
    "baseline_t_review": 50.0,
    "adjustment_factor": 0.5,
    "risk_deviation": "40.7085 - 50.0 = -9.3",
    "adjustment": "-9.3 × 0.5 = -4.65",
    "t_block_unclamped": "75.0 - -4.65 = 79.6457",
    "t_block_clamp_range": "[40.0, 95.0]",
    "t_block_final": 79.6457,
    "t_review_unclamped": "50.0 - -4.65 = 54.6457",
    "t_review_clamp_range": "[20.0, 70.0]",
    "t_review_final": 54.6457,
    "interpretation": "This account has below-average risk (40.7085 < 50). Thresholds are raised, making it harder to trigger BLOCK or REVIEW. A higher-risk account with score 80 would have t_block=60.0 and t_review=35.0."
  },
  "decision_zones": {
    "BLOCK": "match_score ≥ 79.6457",
    "REVIEW": "54.6457 ≤ match_score < 79.6457",
    "CLEAR": "match_score < 54.6457"
  }
}
```

**Field notes:**
- `formula` values are human-readable strings (e.g. `"40.7085 - 50.0 = -9.3"`). They are display strings, not numbers.
- `formula.t_block_final` and `formula.t_review_final` are the same numbers as the top-level `t_block` / `t_review`.
- `formula.interpretation` is a plain-English sentence comparing this account to a contrasting hypothetical. Display it directly.
- `decision_zones` provides the three verdict boundaries as strings, ready for display.

**Errors:**
- `404` — account not found
- `503` — data not loaded (server still starting up)

---

## Error responses

All errors return a JSON body:

```json
{ "detail": "Account ACC-XXXXX not found" }
```

| Status | When |
|--------|------|
| `404`  | Account ID or screening ID not found |
| `422`  | Request body validation failure (wrong type, out-of-range value, missing required field) |
| `503`  | Data not loaded — server is still starting up; retry after a second |
| `500`  | Unexpected server error — check server logs |

---

## Quick reference — pages to endpoints

| Page | Endpoint(s) |
|------|-------------|
| Dashboard home | `GET /dashboard/stats` |
| Account Explorer | `GET /accounts` (with filters and pagination) |
| Account Detail | `GET /accounts/{id}` · `GET /accounts/{id}/transactions` · `GET /thresholds/explain/{id}` |
| Screening Queue | `GET /screening?verdict=REVIEW` |
| Screening Detail | `GET /screening/{id}` |
| Live Screener | `POST /screen` |

---

## Implementation notes for the AI agent building the frontend

**Base URL:** Configure as an environment variable, e.g.:

```ts
const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
```

**CORS:** Already open — no proxy needed in dev.

**The threshold visualisation** — the key component for every page that shows a screening result. Build a horizontal 0–100 bar split at `t_review` and `t_block`:

```
|←—— CLEAR (green) ——→|←— REVIEW (amber) —→|←— BLOCK (red) —→|
0                   t_review             t_block              100
                                   ●  ← match_score
```

All three values come from the same response object. Zone widths as percentages:
```
green width  = t_review / 100 * 100%
amber width  = (t_block - t_review) / 100 * 100%
red width    = (100 - t_block) / 100 * 100%
dot position = match_score / 100 * 100%
```

**The audit panel** — appears on Account Detail, Screening Detail, and Live Screener result. Render:
1. Verdict badge (coloured chip): green = CLEAR, amber = REVIEW, red = BLOCK
2. `audit_narrative` as a body-text paragraph
3. `audit_factors` as an unordered list
4. `class_probabilities` as three small badges or a mini bar: BLOCK (red), REVIEW (amber), CLEAR (green)
5. `feature_contributions` top 3–5 as a table or mini bar chart

**Loading states:** The first `POST /screen` call takes ~1–2 seconds. Show a spinner. All subsequent calls are fast.

**Unicode:** `full_name` and `recipient_name` can contain Arabic, Cyrillic, Chinese, and other scripts. Make sure your font stack handles it.

**Null fields:** `recipient_name` can be `null` for crypto wallet transactions. `country_residence` and other string fields are never `null` but can be empty strings or ISO codes like `"XX"` (unknown country).
