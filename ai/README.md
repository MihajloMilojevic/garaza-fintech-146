# Sanctions Screening AI — Model Documentation

> **Version:** 1.0.0  
> **Trained:** 2026-06-14  
> **Model files:** `model/model_binary.ubj`, `model/model_multiclass.ubj`  
> **Inference entry-point:** `model/predict.py` → `screen()`

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Two-Threshold Decision Logic](#2-two-threshold-decision-logic)
3. [Five-Component Risk Score](#3-five-component-risk-score)
4. [Model Architecture](#4-model-architecture)
5. [Training Data](#5-training-data)
6. [Reference Data Sources](#6-reference-data-sources)
7. [Model Performance](#7-model-performance)
8. [Feature Importance](#8-feature-importance)
9. [Data Schema](#9-data-schema)
10. [Production Data Provenance](#10-production-data-provenance)
11. [Interpretability and Audit Output](#11-interpretability-and-audit-output)
12. [How to Use the Model](#12-how-to-use-the-model)
13. [Files in This Directory](#13-files-in-this-directory)

---

## 1. System Overview

This is a **two-threshold dynamic sanctions screening model** that sits downstream of a name-matching engine. It does two things:

1. **Computes per-account dynamic thresholds** (`t_block` and `t_review`) derived from a five-component risk score. Accounts that are inherently riskier have lower thresholds (easier to trigger), while low-risk accounts require a near-perfect name match before any action is taken.

2. **Applies those thresholds to the name-match score** produced by the screening system to emit a three-way verdict: `BLOCK`, `REVIEW`, or `CLEAR`.

The model is implemented as two XGBoost classifiers trained on 20,000 synthetic accounts. The classifiers confirm and quantify the threshold-based decision with calibrated probabilities used for audit and confidence scoring, but the **primary decision path is the deterministic threshold formula**, not the classifier output. This design keeps the decision rule transparent and auditable.

The system replaces a static, one-size-fits-all threshold (e.g. 65/100) that cannot distinguish between a verified low-risk retail customer and a high-risk business with complex offshore ownership. The dynamic approach reduced false positives from 2,301 (static) to 1,043 (dynamic) on the training population.

---

## 2. Two-Threshold Decision Logic

This is the most important section. Read it carefully before integrating.

### How the thresholds are calculated

Two thresholds are computed per account at screening time, using the account's `overall_risk_score` (0–100):

```
risk_adjustment = (overall_risk_score − 50) × 0.5

t_block  = clamp(75 − risk_adjustment,  40, 95)
t_review = clamp(50 − risk_adjustment,  20, 70)
```

Both thresholds are derived from the **same risk adjustment factor**. When `overall_risk_score` is above 50 (elevated risk), both thresholds decrease — it becomes easier for a name match to trigger a BLOCK or REVIEW. When `overall_risk_score` is below 50 (low risk), both thresholds increase — a weaker match is less likely to trigger any action.

The clamp bounds prevent extreme scores from producing absurd thresholds:
- `t_block` is always between 40 and 95.
- `t_review` is always between 20 and 70.

### Decision zones

Once the thresholds are computed, the `match_score` from the screening system (0–100, produced by the name-matching engine using Jaro-Winkler or equivalent string similarity) is compared against them:

| Condition | Verdict | Meaning |
|---|---|---|
| `match_score >= t_block` | **BLOCK** | Automatic block — no human review required |
| `t_review <= match_score < t_block` | **REVIEW** | Routed to a human analyst |
| `match_score < t_review` | **CLEAR** | Automatic pass — no action taken |

### Concrete examples

| `overall_risk_score` | `t_block` | `t_review` | Practical effect |
|---|---|---|---|
| 10 | 95.0 | 70.0 | Very low-risk: match must be near-perfect (≥ 95/100) to auto-block; review band starts at 70 |
| 50 | 75.0 | 50.0 | Neutral account: identical to the static baseline (block at 75, review at 50) |
| 90 | 55.0 | 30.0 | High-risk: a 55/100 fuzzy match triggers an automatic block; review band starts at 30 |

### Comparison with a static threshold

A static threshold at 65/100 fires unconditionally regardless of account risk context. On the 20,000-account synthetic dataset:

| Approach | False Positives | Notes |
|---|---|---|
| Static threshold at 65 | 2,301 | Cannot distinguish risky vs. safe accounts |
| Dynamic two-threshold | 1,043 | Adjusts per account — 55% fewer false positives |

The key insight is that a 68/100 name match for a fully verified, low-risk domestic retail customer is almost certainly a coincidental match and should pass automatically. The same score for a high-risk offshore shell company with complex ownership should trigger immediate human review.

---

## 3. Five-Component Risk Score

The `overall_risk_score` (0–100) that drives threshold calculation is a weighted sum of five components:

```
overall_risk_score =
    0.25 × geographic_risk
  + 0.15 × identity_kyc_risk
  + 0.30 × pep_sanctions_risk
  + 0.20 × behavioural_risk
  + 0.10 × relationship_network_risk
```

All component scores are on a 0–100 scale.

### Component definitions

#### `geographic_risk` (weight 0.25)

Reflects the sanctions and AML risk of the countries associated with the account.

- **Inputs:** `country_residence`, `country_incorporation`
- **Scoring:** Composite country risk score drawn from `country_risk.csv` (see [Reference Data Sources](#6-reference-data-sources)), which encodes FATF grey/black list membership, OFAC comprehensive sanctions designation, and Basel AML Index proxy scores for 226 countries.
- **Penalty:** Accounts with offshore incorporation in a different (and higher-risk) jurisdiction from their residence receive an additional penalty.
- **Effect:** A UK resident with UK incorporation has a low geographic risk. A British Virgin Islands shell company with a Cyprus-resident director has a high geographic risk.

#### `identity_kyc_risk` (weight 0.15)

Reflects the quality and completeness of the account's Know Your Customer (KYC) record.

- **Scoring:** Primarily the inverse of `kyc_completeness` (0.0–1.0 completeness → higher incompleteness → higher risk). Additional status penalties are applied:
  - `expired` KYC: highest penalty (documentation is out of date)
  - `pending` KYC: elevated penalty (identity not yet confirmed)
  - `partial` KYC: moderate penalty
  - `complete` KYC: base risk only from incompleteness fraction
- **Effect:** An account with 95% KYC completeness and `complete` status has minimal identity risk. An account with 30% completeness and `expired` status has high identity risk.

#### `pep_sanctions_risk` (weight 0.30, highest weight)

Reflects direct exposure to sanctions lists and Politically Exposed Person (PEP) databases. This is the most heavily weighted component because it is the most direct signal of sanctions exposure.

- **Name match type scoring:**
  - `exact` match against a sanctioned entity → score in the range 95–100
  - `alias` match → 85–95
  - `fuzzy_near_miss` match → 60–85
  - `none` (no match) → 0–10 (residual PEP-driven risk may remain)
- **PEP status:** Accounts with `is_pep = 1` receive elevated base scores regardless of name match type.
- **Effect:** This single component dominates the binary classifier (importance 0.838), meaning the BLOCK/not-BLOCK decision is almost entirely determined by how closely the account name matches a sanctioned entity.

#### `behavioural_risk` (weight 0.20)

Reflects anomalous transaction patterns associated with AML typologies.

- **Signals:**
  - Transaction velocity over 30 days (`velocity_30d_count`, `velocity_30d_amount`)
  - Large individual amounts above expected thresholds
  - Night-hour transaction pattern (transactions concentrated in overnight hours)
  - Round-amount pattern (amounts divisible by 1,000 or 10,000, often indicative of structuring)
  - Multi-currency usage across multiple payment rails
- **Effect:** A retail account with two transactions per month, all small domestic transfers, has very low behavioural risk. A business account with 200 transactions in 30 days, round amounts in multiple currencies, concentrated late at night, has high behavioural risk.

#### `relationship_network_risk` (weight 0.10)

Reflects risk introduced by the account's documented relationships with sanctioned entities, PEPs, or high-risk recipients.

- **Signals:**
  - Direct relationships with sanctioned entities (from `account_relationships` table)
  - Direct PEP relationships
  - Concentration of transaction recipients in high-risk countries
  - Blockchain wallet hops to sanctioned addresses (from `wallets` table)
- **Effect:** An account that has a documented directorship relationship with a sanctioned entity's beneficial owner has high network risk, even if its own name does not match any list.

---

## 4. Model Architecture

The system uses two XGBoost classifiers trained on the same feature set and training data. They serve complementary purposes.

### Binary classifier (`model_binary.ubj`)

- **Objective:** `binary:logistic`
- **Task:** Discriminate BLOCK from not-BLOCK (CLEAR + REVIEW pooled as negative class).
- **Class imbalance handling:** `scale_pos_weight = 424.5` (ratio of negative to positive examples in training data).
- **Output used for:** `block_probability` field — a calibrated P(BLOCK) value used for audit confidence scoring. High `block_probability` alongside a REVIEW threshold verdict suggests the case is borderline and should be escalated.

### Multiclass classifier (`model_multiclass.ubj`)

- **Objective:** `multi:softprob`
- **Classes:** `BLOCK`, `CLEAR`, `REVIEW` (alphabetical order, matching XGBoost's internal ordering)
- **Output used for:** `class_probabilities` field — a probability distribution over all three verdicts. The multiclass model is the preferred source for final decision output in audit logs.

### Decision flow

```
Input features (19)
        │
        ▼
_compute_thresholds(overall_risk_score)
        │
        ├── t_block  = clamp(75 − adj, 40, 95)
        └── t_review = clamp(50 − adj, 20, 70)
                │
                ▼
     _apply_thresholds(match_score, t_block, t_review)
                │
                ├── PRIMARY VERDICT (deterministic)
                │
                ▼
     Binary model  →  block_probability (P(BLOCK))
     Multiclass model → class_probabilities {BLOCK, CLEAR, REVIEW}
                │
                ▼
     _feature_contributions() → top-10 importance-weighted contributions
                │
                ▼
     _build_narrative() → audit_narrative + audit_factors
                │
                ▼
     screen() output dict
```

The verdict returned to the caller is always determined by the **threshold formula**, not by the classifier's argmax. The classifiers provide confidence calibration and support the audit trail.

---

## 5. Training Data

### Dataset summary

| Label | Count | Percentage |
|---|---|---|
| CLEAR | 19,047 | 95.23% |
| REVIEW | 906 | 4.53% |
| BLOCK | 47 | 0.23% |
| **Total** | **20,000** | |

The dataset consists of **20,000 synthetic accounts**. The synthetic population was constructed to be realistic and representative:
- **75 accounts** are directly sanctioned entities (exact or alias name matches against OpenSanctions targets).
- **100 accounts** are PEP-injected (persons from the OpenSanctions PEP dataset, inserted as account holders with elevated risk scores).
- The remaining accounts are clean, with realistic but non-sanctioned profiles.

Labels (`BLOCK`, `REVIEW`, `CLEAR`) were assigned using the same two-threshold dynamic decision logic described in [Section 2](#2-two-threshold-decision-logic), applied at the account-level screening stage. This means the model is trained to reproduce the threshold logic from raw features, not to predict an externally labelled outcome — which is why the in-sample and cross-validation metrics are extremely high.

### Training methodology

- **Feature set:** 19 features (see [Section 9](#9-data-schema) for the full feature list).
- **Excluded features (label-proxy):** The following features were excluded from training to prevent data leakage, as they directly encode the screening outcome and would be unavailable or contaminated in production:
  - `hops_to_sanctioned` (blockchain analytics field, encodes proximity to sanctioned wallets which correlates directly with the label)
  - `name_match_type_enc` (encodes whether the name matched exactly/alias/fuzzy — too closely correlated with `pep_sanctions_risk` and the label)
  - Threshold verdict fields from `threshold_decisions` table (these are the labels themselves)
- **Validation:** 5-fold stratified cross-validation, stratified on the three-class label to ensure BLOCK cases (47 total) appear in every fold.
- **Class imbalance:** Binary model uses `scale_pos_weight`; multiclass model uses XGBoost's default softprob with the skewed distribution as-is (the model learns the prior).

---

## 6. Reference Data Sources

The synthetic training data was calibrated against six real-world reference datasets to ensure realistic score distributions and entity coverage.

### `sanctioned_entities.csv`

- **Source:** OpenSanctions `targets.simple.csv` (public domain)
- **Size used:** 8,000 entities, stratified by country of origin
- **Crypto wallet coverage:** All 2,463 `CryptoWallet` entities were retained (not sampled), since crypto-related sanctions are a primary use case.
- **Usage:** Populates the sanctioned entity reference list that the name-matching engine screens against. Directly drives `name_match_type` and `match_score` distributions.

### `sanctioned_relationships.csv`

- **Source:** OpenSanctions `entities.ftm.json` (FollowTheMoney format)
- **Size used:** 1,499 real relationship edges, covering `Ownership`, `Family`, and `Directorship` schemas
- **Usage:** Populates `account_relationships` for the 75 directly sanctioned accounts. These are real documented relationships from the OpenSanctions graph, not fabricated ones. This calibrates the `relationship_network_risk` component.

### `peps.csv`

- **Source:** OpenSanctions PEP (Politically Exposed Persons) dataset
- **Size used:** 3,000 persons sampled from 754,598 total PEP records
- **Usage:** 100 sampled PEPs are injected as account holders. Their names, nationalities, and PEP status directly drive `pep_sanctions_risk` and `is_pep` fields.

### `matching_pairs_summary.csv`

- **Source:** Jaro-Winkler similarity distributions computed from OpenSanctions `pairs-20251209.json`
- **Pair counts:** 85,144 positive pairs (same entity, different name representations) and 11,820 negative pairs (different entities)
- **Usage:** Calibrates the `match_score` distributions for each `name_match_type` bucket (`exact`, `alias`, `fuzzy_near_miss`, `none`). Without this calibration, synthetic match scores would not reflect real string similarity distributions for names in the OpenSanctions corpus.

### `aml_transactions_sample.csv`

- **Source:** IBM HI-Small AML synthetic transaction dataset (public release)
- **Size used:** 500,000 transactions used for distribution sampling
- **Usage:** Calibrates `behavioural_risk` signal distributions: transaction amounts, hour-of-day patterns, day-of-week patterns, burst patterns. The IBM dataset contains labelled money-laundering patterns that ground the behavioural risk features in realistic AML typologies.

### `country_risk.csv`

- **Coverage:** 226 countries
- **Sources:** FATF grey list and black list (2025), OFAC comprehensive sanctions country designations, Basel AML Index proxy scores
- **Usage:** Provides the `country_risk_score` composite for each country. Used to compute `geographic_risk` for accounts based on their residence and incorporation countries.

---

## 7. Model Performance

All metrics below were computed on the 20,000-account training population. No held-out test set was used for the final models; cross-validation is the primary estimate of generalisation performance.

### Binary model — BLOCK vs not-BLOCK

#### Cross-validation (5-fold stratified)

| Metric | Mean | Std |
|---|---|---|
| ROC-AUC | 0.9999 | ±0.0001 |
| F1 (BLOCK class) | 0.9610 | ±0.0372 |

#### In-sample metrics

| Metric | Value |
|---|---|
| ROC-AUC | 1.0000 |
| Precision (BLOCK) | 0.9216 |
| Recall (BLOCK) | 1.0000 |
| F1 (BLOCK) | 0.9592 |

#### In-sample confusion matrix

| | Predicted not-BLOCK | Predicted BLOCK |
|---|---|---|
| True not-BLOCK | 19,949 | 4 |
| True BLOCK | 0 | 47 |

All 47 BLOCK cases are correctly recalled. The 4 false positives are REVIEW or CLEAR accounts classified as BLOCK by the binary model — these would not result in erroneous blocks since the primary decision is determined by the threshold formula, not the model's argmax.

### Multiclass model — BLOCK / REVIEW / CLEAR

#### Cross-validation (5-fold stratified)

| Metric | Mean | Std |
|---|---|---|
| Macro F1 | 0.9964 | ±0.0066 |

#### In-sample confusion matrix

| | Predicted BLOCK | Predicted CLEAR | Predicted REVIEW |
|---|---|---|---|
| True BLOCK | 47 | 0 | 0 |
| True CLEAR | 0 | 19,047 | 0 |
| True REVIEW | 0 | 0 | 906 |

The multiclass model achieves perfect in-sample separation across all three classes.

### Interpretation of these metrics

The extremely high performance metrics are expected given the training setup: the labels themselves were generated by the same threshold logic that the model is trained to reproduce, using features that strongly encode the outcome (`pep_sanctions_risk` encodes name match type, which directly determines BLOCK verdicts). These metrics should not be interpreted as evidence of generalisation to real-world data. See [Section 11](#11-interpretability-and-audit-output) for what is still needed before production deployment.

---

## 8. Feature Importance

### Binary model (BLOCK vs not-BLOCK) — top 15 features

| Rank | Feature | Importance |
|---|---|---|
| 1 | `pep_sanctions_risk` | 0.8382 |
| 2 | `match_score` | 0.1231 |
| 3 | `overall_risk_score` | 0.0251 |
| 4 | `override_applied` | 0.0060 |
| 5 | `account_type_enc` | 0.0027 |
| 6 | `relationship_network_risk` | 0.0012 |
| 7 | `account_status_enc` | 0.0012 |
| 8 | `geographic_risk` | 0.0006 |
| 9 | `pep_exposure_score` | 0.0005 |
| 10 | `kyc_status_enc` | 0.0003 |
| 11 | `behavioural_risk` | 0.0003 |
| 12 | `activity_tier_enc` | 0.0003 |
| 13 | `kyc_completeness` | 0.0002 |
| 14 | `identity_kyc_risk` | 0.0002 |
| 15 | `country_risk_score` | 0.0001 |

The binary model is almost entirely determined by two features: `pep_sanctions_risk` (0.838) and `match_score` (0.123). This is expected — the BLOCK class requires a direct name match against a sanctioned entity, which is encoded in `pep_sanctions_risk`. Features with zero importance in the binary model (`is_pep`, `has_complex_ownership`, `shell_company_flag`, `shares_address_with_sanctioned`) are unused for the BLOCK/not-BLOCK decision but may be meaningful for the REVIEW/CLEAR distinction.

### Multiclass model (BLOCK / REVIEW / CLEAR) — top 15 features

| Rank | Feature | Importance |
|---|---|---|
| 1 | `overall_risk_score` | 0.4175 |
| 2 | `pep_sanctions_risk` | 0.1525 |
| 3 | `country_risk_score` | 0.0791 |
| 4 | `match_score` | 0.0651 |
| 5 | `override_applied` | 0.0573 |
| 6 | `kyc_completeness` | 0.0515 |
| 7 | `is_pep` | 0.0389 |
| 8 | `identity_kyc_risk` | 0.0334 |
| 9 | `relationship_network_risk` | 0.0247 |
| 10 | `geographic_risk` | 0.0223 |
| 11 | `behavioural_risk` | 0.0127 |
| 12 | `has_complex_ownership` | 0.0114 |
| 13 | `pep_exposure_score` | 0.0087 |
| 14 | `activity_tier_enc` | 0.0087 |
| 15 | `account_status_enc` | 0.0078 |

The multiclass model distributes importance more broadly, because distinguishing REVIEW from CLEAR requires subtler signals. `overall_risk_score` (0.4175) is the dominant feature — it directly drives where accounts fall within the REVIEW band. The shift from `pep_sanctions_risk`-dominated (binary) to `overall_risk_score`-dominated (multiclass) reflects that REVIEW vs CLEAR is fundamentally a risk-score question, not a name-match question.

---

## 9. Data Schema

All tables exist in the SQLite database and as Parquet exports. The schema below documents every column.

### `accounts`

The central entity table. One row per customer account.

| Column | Type | Description |
|---|---|---|
| `account_id` | string (PK) | Unique account identifier |
| `account_type` | enum | `individual` or `business` |
| `full_name` | string | Account holder name (input to name-matching engine) |
| `country_residence` | string | ISO country code of residence |
| `country_incorporation` | string | ISO country code of incorporation (businesses) |
| `date_of_birth` | date | For individuals |
| `nationality` | string | ISO country code |
| `created_at` | datetime | Account creation timestamp |
| `kyc_completeness` | float [0.0–1.0] | Fraction of KYC fields completed |
| `kyc_status` | enum | `complete`, `partial`, `pending`, `expired` |
| `is_pep` | int [0/1] | Politically Exposed Person flag |
| `pep_id` | string (nullable) | Reference to PEP database entry |
| `has_complex_ownership` | int [0/1] | Multi-layer or unclear ownership structure |
| `shell_company_flag` | int [0/1] | Identified as a shell company |
| `sanctioned_entity_id` | string (nullable) | Reference to matched entity in `sanctioned_entities.csv` |
| `name_match_type` | enum | `none`, `exact`, `alias`, `fuzzy_near_miss` |
| `account_status` | enum | `active`, `suspended`, `closed` |
| `activity_tier` | enum | `low`, `medium`, `high` — expected transaction volume |
| `initial_risk_band` | enum | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` — assigned at onboarding |

### `account_relationships`

Documents connections between accounts and other persons or entities.

| Column | Type | Description |
|---|---|---|
| `relationship_id` | string (PK) | |
| `account_id` | string (FK → accounts) | |
| `related_entity_name` | string | Name of the related person or entity |
| `relationship_type` | enum | `ownership`, `family`, `associate`, `directorship` |
| `related_is_pep` | int [0/1] | Whether the related entity is a PEP |
| `related_is_sanctioned` | int [0/1] | Whether the related entity is sanctioned |
| `related_sanctioned_entity_id` | string (nullable) | Reference to sanctioned entity |
| `source` | enum | `real_ftm` (from FollowTheMoney graph) or `synthetic` |

### `wallets`

Crypto wallet addresses associated with accounts.

| Column | Type | Description |
|---|---|---|
| `wallet_id` | string (PK) | |
| `account_id` | string (FK → accounts) | |
| `wallet_address` | string | On-chain address |
| `chain` | enum | `Ethereum` or `Bitcoin` |
| `is_sanctioned` | int [0/1] | Wallet is on OFAC SDN or equivalent |
| `sanctioned_entity_id` | string (nullable) | Reference to sanctioned entity |
| `hops_to_sanctioned` | int | Blockchain distance to nearest sanctioned address (0 = direct) |

### `transactions`

Individual payment events. One row per transaction.

| Column | Type | Description |
|---|---|---|
| `transaction_id` | string (PK) | |
| `sender_account_id` | string (FK → accounts) | |
| `recipient_account_id` | string (FK → accounts, nullable) | Null for external recipients |
| `recipient_type` | enum | `account`, `external_individual`, `crypto_wallet` |
| `recipient_name` | string | Name of recipient (used in transaction-level screening) |
| `recipient_country` | string | ISO country code |
| `recipient_wallet_id` | string (FK → wallets, nullable) | |
| `amount` | float | Transaction amount |
| `currency` | string | ISO 4217 currency code |
| `payment_rail` | enum | `wire`, `ach`, `card`, `check`, `internal`, `crypto` |
| `timestamp` | datetime | |
| `is_first_time_recipient` | int [0/1] | First transaction to this recipient |
| `sender_account_age_days` | int | Age of the sender's account at transaction time |
| `velocity_30d_count` | int | Number of transactions by sender in last 30 days |
| `velocity_30d_amount` | float | Total amount sent by sender in last 30 days |
| `hour_of_day` | int [0–23] | Local hour of transaction |
| `day_of_week` | int [0–6] | Day of week (0 = Monday) |
| `shape_source` | enum | `aml_derived` (distributions from IBM AML dataset) or `synthetic` |

### `screening_results`

Output of the name-matching engine. One row per screening event.

| Column | Type | Description |
|---|---|---|
| `screening_id` | string (PK) | |
| `transaction_id` | string (FK → transactions, nullable) | Null for account-level screenings |
| `account_id` | string (FK → accounts) | |
| `screening_context` | enum | `account` or `transaction` |
| `matched_entity_id` | string | Matched entity in the sanctions/PEP list |
| `match_score` | float [0–100] | String similarity score from the matching engine |
| `match_field` | string | Which field matched (e.g. `full_name`, `alias`) |
| `fuzzy_match_type` | string | Algorithm used (e.g. Jaro-Winkler, token-set-ratio) |
| `hops_to_sanctioned` | int | Blockchain hops (for crypto screening) |
| `shares_address_with_sanctioned` | int [0/1] | Registered address overlap |
| `pep_exposure_score` | float [0–100] | Composite PEP exposure score |
| `country_risk_score` | float [0–100] | Composite country risk score |
| `verdict_ground_truth` | enum | `BLOCK`, `REVIEW`, `CLEAR` — the training label |

### `risk_scores`

Computed risk scores for each account. One row per account (latest computation).

| Column | Type | Description |
|---|---|---|
| `risk_score_id` | string (PK) | |
| `account_id` | string (FK → accounts) | |
| `computed_at` | datetime | When this risk score was computed |
| `geographic_risk` | float [0–100] | See Section 3 |
| `identity_kyc_risk` | float [0–100] | See Section 3 |
| `pep_sanctions_risk` | float [0–100] | See Section 3 |
| `behavioural_risk` | float [0–100] | See Section 3 |
| `relationship_network_risk` | float [0–100] | See Section 3 |
| `overall_risk_score` | float [0–100] | Weighted sum — see Section 3 formula |
| `risk_band` | enum | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `override_applied` | int [0/1] | Whether a manual analyst override was applied |
| `override_reason` | string (nullable) | Free-text reason for override |

### `threshold_decisions`

One row per screening event, recording the threshold comparison result.

| Column | Type | Description |
|---|---|---|
| `decision_id` | string (PK) | |
| `transaction_id` | string (FK → transactions, nullable) | |
| `screening_id` | string (FK → screening_results) | |
| `static_threshold` | float | The fixed threshold used for comparison (e.g. 65.0) |
| `static_verdict` | enum | `BLOCK`, `REVIEW`, `CLEAR` using the static threshold |
| `dynamic_t_block` | float | Computed `t_block` for this account |
| `dynamic_t_review` | float | Computed `t_review` for this account |
| `dynamic_verdict` | enum | `BLOCK`, `REVIEW`, `CLEAR` using dynamic thresholds |
| `verdicts_differ` | int [0/1] | 1 if static and dynamic verdicts disagree |

### `explanatory_logs`

Stores human-readable narratives and structured factor lists for audit trail purposes.

| Column | Type | Description |
|---|---|---|
| `log_id` | string (PK) | |
| `related_table` | string | `risk_scores` or `threshold_decisions` |
| `related_id` | string | FK to the related row in the referenced table |
| `narrative` | text | Full human-readable explanation of the decision |
| `top_factors_json` | text | JSON array of factor strings (top contributing features) |

### Entity-relationship summary

```
accounts
  ├── account_relationships  (one-to-many)
  ├── wallets                (one-to-many)
  ├── transactions           (one-to-many, as sender)
  ├── screening_results      (one-to-many)
  └── risk_scores            (one-to-one)

screening_results
  └── threshold_decisions    (one-to-one)

risk_scores
  └── explanatory_logs       (one-to-many, via related_table/related_id)

threshold_decisions
  └── explanatory_logs       (one-to-many, via related_table/related_id)
```

---

## 10. Production Data Provenance

This section explains where each table's data would come from in a real production deployment. The synthetic dataset was designed to mirror these real sources.

### `accounts`

In production, this table is populated from the **core banking system** or **KYC onboarding platform** (CRM, identity verification provider such as Onfido, Jumio, or Socure). The `kyc_completeness` and `kyc_status` fields come from the AML compliance team's document verification workflow. `is_pep` and `pep_id` are populated from a commercial PEP database subscription (Dow Jones Risk & Compliance, LexisNexis WorldCompliance, Refinitiv World-Check, or equivalent) queried at onboarding and on periodic refresh. `shell_company_flag` and `has_complex_ownership` come from UBO (Ultimate Beneficial Owner) registry queries or corporate registry API providers (e.g. Companies House API in the UK, SEC EDGAR, national UBO registries required under AMLD5/6 in the EU).

### `account_relationships`

In production, populated from **UBO declarations** submitted by business customers at onboarding, enriched by **corporate registry data** (OpenCorporates, Bureau van Dijk Orbis, FactSet Entity) and **graph enrichment providers**. The `real_ftm` source rows in the synthetic dataset correspond to relationships that would come from the OpenSanctions relationship graph (FollowTheMoney format) or a commercial equivalent. In a production system, this graph would be refreshed daily as new sanctions designations and relationship data are published.

### `wallets`

In production, crypto wallet addresses are declared by customers during onboarding (increasingly required by Travel Rule regulations under FATF Recommendation 16). The `is_sanctioned`, `sanctioned_entity_id`, and `hops_to_sanctioned` fields are populated by **blockchain analytics providers** (Chainalysis, Elliptic, TRM Labs) queried in real-time or batch. These providers maintain continuously updated graphs of on-chain address clusters and their relationships to sanctioned entities.

### `transactions`

In production, populated from the **core banking transaction ledger** or **payment processor** (SWIFT for wire transfers, ACH network for US domestic transfers, card schemes for card payments, internal ledger for intra-bank transfers). The velocity fields (`velocity_30d_count`, `velocity_30d_amount`) are computed in near-real-time by a **streaming data pipeline** — typically Apache Kafka for event ingestion plus Apache Flink or Spark Streaming for windowed aggregation — and written back to the transaction record at the time of payment authorisation.

### `screening_results`

In production, populated by the **name-matching engine** run against the screening/PEP lists. Providers include Refinitiv World-Check One API, ComplyAdvantage, Dow Jones Watchlist, or an in-house fuzzy matching service. The `match_score` field is the string similarity score returned by the matching engine (Jaro-Winkler, token-based similarity such as token-set-ratio, or phonetic similarity such as Soundex/Metaphone), scaled to 0–100. Every payment event and every onboarding event triggers a screening run. `pep_exposure_score` and `country_risk_score` are computed by the risk scoring engine (which produces `risk_scores`) and denormalised here for query convenience.

### `risk_scores`

In production, computed by **this model** at three trigger points:
1. **Account onboarding** — initial risk score before first transaction.
2. **Periodic refresh** — daily or weekly batch recomputation for all accounts, incorporating updated country risk lists, new relationship disclosures, and updated KYC status.
3. **Event-triggered re-scoring** — immediately after a significant event: a new transaction alert, a change in KYC status, a new relationship disclosure, a new sanctions list publication, or a match against a PEP database.

The `override_applied` and `override_reason` fields are set by a human analyst who manually adjusts a risk score after reviewing a case. Overrides are logged and subject to four-eyes review in regulated institutions.

### `threshold_decisions`

In production, computed by **this model's `screen()` function** at every screening event, in real-time. The row is written to the database as an immutable audit record immediately after the decision is taken. In a regulated institution, this record cannot be deleted or altered — it forms part of the regulatory audit trail. For institutions subject to SWIFT gpi or SEPA Instant, the threshold decision must be taken within milliseconds of the payment instruction arriving.

### `explanatory_logs`

In production, generated by **this model's `predict.py` output** and stored as part of the mandatory regulatory audit trail. Regulators including the FCA (UK), FinCEN (US), EBA (EU), and MAS (Singapore) require that AML model decisions be explainable: a compliance officer must be able to explain to a regulator exactly why a specific account was blocked or cleared on a specific date, citing the specific factors that drove the decision. The `narrative` field and `top_factors_json` field serve this requirement.

---

## 11. Interpretability and Audit Output

### What audit output is currently produced

Every call to `screen()` returns an `audit_narrative` (a free-text paragraph) and `audit_factors` (a list of factor sentences). These are also stored in `explanatory_logs` via the backend integration.

Example `audit_narrative` for a high-risk BLOCK case:
```
Verdict: BLOCK. The account's overall risk score of 85.0/100 lowered the block threshold
from the static baseline of 75.0 to 55.0 and the review threshold to 30.0, reflecting a
high-risk profile. The screening system produced a match score of 96.0/100.
match score 96.0 ≥ block threshold 55.0 → automatic block.
```

Example `audit_factors`:
```
• pep sanctions risk = 97.0 (importance 0.838, contribution 81.4%)
• match score = 96.0 (importance 0.123, contribution 11.8%)
• overall risk score = 85.0 (importance 0.025, contribution 2.1%)
• Account shares a registered address with a known sanctioned entity.
```

The `threshold_decisions` table additionally records both the static and dynamic thresholds side-by-side, and a `verdicts_differ` flag, which provides a direct comparison for model monitoring and regulatory challenge scenarios.

### What `predict.py` returns

The `screen()` function returns a dictionary with the following fields:

| Field | Type | Description |
|---|---|---|
| `verdict` | str | `"BLOCK"`, `"REVIEW"`, or `"CLEAR"` — the primary decision |
| `t_block` | float | Computed block threshold for this account |
| `t_review` | float | Computed review threshold for this account |
| `match_score` | float | Echo of the input match score |
| `overall_risk_score` | float | Echo of the input overall risk score |
| `block_probability` | float | P(BLOCK) from the binary XGBoost classifier [0.0–1.0] |
| `class_probabilities` | dict | `{BLOCK: float, CLEAR: float, REVIEW: float}` from multiclass model |
| `risk_components` | dict | The five component scores (geographic, identity_kyc, pep_sanctions, behavioural, relationship_network) |
| `feature_contributions` | list | Top-10 features with importance, raw value, and contribution percentage |
| `audit_narrative` | str | Human-readable paragraph explaining the decision |
| `audit_factors` | list[str] | Individual factor sentences suitable for display in a case management UI |

### Feature contributions — what they are and what they are not

The `feature_contributions` list in the output uses an **importance-weighted approximation**, not true SHAP values. Specifically, each feature's contribution is calculated as:

```
contribution_pct = feature_importance × (feature_value / feature_max) × 100
```

where `feature_importance` is the XGBoost feature importance score (fraction of splits using that feature) and `feature_value / feature_max` is the feature value normalised to [0, 1] using hard-coded expected maxima.

This is a fast proxy that is suitable for generating readable audit narratives and identifying the dominant factors in a given decision. However, it has important limitations:
- It does not capture interaction effects between features.
- It does not reflect the direction of the contribution (whether the feature pushes towards BLOCK or CLEAR).
- It is not additive in the way SHAP values are (SHAP values sum to the model output minus the expected output).

**To get true SHAP values:**
```python
import shap
import xgboost as xgb

model = xgb.XGBClassifier()
model.load_model("model/model_binary.ubj")

explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X)  # X is a numpy array of shape (n_samples, 19)
```

SHAP `TreeExplainer` is exact for tree-based models and adds no approximation error. For production audit use, SHAP values should replace the current importance-weighted proxy.

### What regulators typically require for AML model explainability

Regulatory guidance from the FCA (Dear CEO Letters, ML guidance), FinCEN (2021 AML priorities), EBA (EBA/GL/2021/05 on internal governance), and FATF (FATF Guidance on AI) consistently requires:

1. **Decision-level explainability**: For each blocked or reviewed transaction, the institution must be able to explain which specific factors led to that outcome, in a form a compliance officer can articulate to a regulator.
2. **Model documentation**: A documented description of how the model works, what data it was trained on, what its performance metrics are, and what its limitations are. This document addresses that requirement.
3. **Model validation**: Independent validation of the model by a party not involved in development, including backtesting against real cases, stress testing, and sensitivity analysis.
4. **Audit trail**: An immutable log of every decision, the inputs used, and the reasoning, retained for at least 5 years (FCA) or as required by local AML record-keeping obligations.
5. **Model risk governance**: A model risk management framework covering model approval, change management, periodic review, and decommissioning. BCBS 239 and SR 11-7 (Fed guidance on model risk) are the standard references.

### What is still missing for full production audit readiness

The current system is a functional prototype. The following gaps must be addressed before regulated production deployment:

1. **True SHAP values in the audit output**: Replace the importance-weighted proxy in `feature_contributions` with `shap.TreeExplainer` output. SHAP values are directional, additive, and theoretically grounded — they satisfy regulatory expectations for explainability far better than importance proxies.

2. **Model card**: A standardised model card (following the Mitchell et al. 2019 format, or the FS regulatory variant) documenting intended use, out-of-scope use, evaluation data, ethical considerations, and caveats. This document is a step toward that, but a formal model card is a separate, shorter artefact typically reviewed by a model risk committee.

3. **Backtesting against real cases**: The model was trained on synthetic data. Before production deployment, it must be backtested against real historical screening decisions from the institution's own case management system to verify that the threshold logic and risk scores produce verdicts consistent with expert analyst judgement. The synthetic dataset cannot substitute for this.

4. **Model drift monitoring**: Once in production, the model's input distributions (match score distributions, risk score distributions, country risk composition) will shift over time as the sanctions lists evolve, customer behaviour changes, and the institution's portfolio mix changes. A monitoring pipeline is needed to detect distribution shift (using statistical tests such as PSI — Population Stability Index — or KS tests on feature distributions) and model performance drift (tracking BLOCK and REVIEW rates over time against analyst disposition outcomes).

5. **Independent model validation**: Regulatory expectation (SR 11-7, EBA guidelines) requires that models used in AML decisions be independently validated by a team or function separate from the development team. The validation report must cover conceptual soundness, data quality, outcome testing, and sensitivity analysis.

6. **Threshold governance**: The two-threshold formula and its parameters (75, 50, 0.5, clamp bounds) were chosen analytically. A production system requires a documented, committee-approved process for selecting and revising these parameters, with evidence of backtesting across the institution's portfolio.

---

## 12. How to Use the Model

### Installation

The inference module requires Python 3.9+ and XGBoost:

```bash
pip install xgboost numpy
```

### Calling `screen()`

Import from `ai.model.predict` (adjust the import path to match your project layout):

```python
from ai.model.predict import screen

result = screen({
    # Account identity fields
    "account_type": "individual",       # "individual" or "business"
    "kyc_completeness": 0.85,           # 0.0 to 1.0
    "kyc_status": "complete",           # "complete" | "partial" | "pending" | "expired"
    "is_pep": 0,                        # 0 or 1
    "has_complex_ownership": 0,         # 0 or 1
    "shell_company_flag": 0,            # 0 or 1
    "activity_tier": "medium",          # "low" | "medium" | "high"
    "account_status": "active",         # "active" | "suspended" | "closed"

    # Screening system output
    "match_score": 72.5,                # 0.0 to 100.0 — from the name-matching engine
    "shares_address_with_sanctioned": 0,
    "pep_exposure_score": 0.0,          # 0.0 to 100.0
    "country_risk_score": 35.0,         # 0.0 to 100.0

    # Risk components (pre-computed by the risk scoring engine)
    "geographic_risk": 35.0,
    "identity_kyc_risk": 15.0,
    "pep_sanctions_risk": 55.0,
    "behavioural_risk": 20.0,
    "relationship_network_risk": 5.0,
    "overall_risk_score": 30.0,         # Weighted sum — ALSO drives threshold calculation
    "override_applied": 0,              # 0 or 1
})

# Primary fields used for routing
print(result["verdict"])          # "REVIEW"
print(result["t_block"])          # 85.0
print(result["t_review"])         # 65.0
print(result["audit_narrative"])  # Human-readable explanation
```

### Output structure

```python
{
    "verdict": "REVIEW",                  # "BLOCK" | "REVIEW" | "CLEAR"
    "t_block": 85.0,                      # Block threshold for this account
    "t_review": 65.0,                     # Review threshold for this account
    "match_score": 72.5,                  # Echo of input
    "overall_risk_score": 30.0,           # Echo of input
    "block_probability": 0.0021,          # P(BLOCK) from binary classifier
    "class_probabilities": {
        "BLOCK": 0.0021,
        "CLEAR": 0.1834,
        "REVIEW": 0.8145,
    },
    "risk_components": {
        "geographic_risk": 35.0,
        "identity_kyc_risk": 15.0,
        "pep_sanctions_risk": 55.0,
        "behavioural_risk": 20.0,
        "relationship_network_risk": 5.0,
    },
    "feature_contributions": [
        {
            "feature": "pep_sanctions_risk",
            "importance": 0.8382,
            "value": 55.0,
            "contribution_pct": 46.1,
        },
        # ... up to 10 features, sorted by contribution_pct descending
    ],
    "audit_narrative": "Verdict: REVIEW. The account's overall risk score of 30.0/100 raised ...",
    "audit_factors": [
        "pep sanctions risk = 55.0 (importance 0.838, contribution 46.1%)",
        "match score = 72.5 (importance 0.123, contribution 8.9%)",
        "overall risk score = 30.0 (importance 0.025, contribution 0.7%)",
    ],
}
```

### Three example cases

The following three cases are included in the `predict.py` CLI test (`python -m ai.model.predict` or `python ai/model/predict.py`):

---

#### Case 1: High-risk sanctioned business — BLOCK

```python
{
    "account_type": "business",
    "kyc_completeness": 0.3,
    "kyc_status": "expired",
    "is_pep": 0,
    "has_complex_ownership": 1,
    "shell_company_flag": 1,
    "activity_tier": "high",
    "account_status": "active",
    "match_score": 96.0,
    "shares_address_with_sanctioned": 1,
    "pep_exposure_score": 0.0,
    "country_risk_score": 85.0,
    "geographic_risk": 85.0,
    "identity_kyc_risk": 70.0,
    "pep_sanctions_risk": 97.0,
    "behavioural_risk": 60.0,
    "relationship_network_risk": 75.0,
    "overall_risk_score": 85.0,
    "override_applied": 0,
}
```

**Expected result:**
- `overall_risk_score` = 85.0 → `t_block` = clamp(75 − (85−50)×0.5, 40, 95) = clamp(57.5, 40, 95) = **57.5**
- `t_review` = clamp(50 − 17.5, 20, 70) = **32.5**
- `match_score` = 96.0 ≥ 57.5 → **BLOCK**

---

#### Case 2: Low-risk individual with coincidental name match — CLEAR

```python
{
    "account_type": "individual",
    "kyc_completeness": 0.95,
    "kyc_status": "complete",
    "is_pep": 0,
    "has_complex_ownership": 0,
    "shell_company_flag": 0,
    "activity_tier": "low",
    "account_status": "active",
    "match_score": 68.0,
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
}
```

**Expected result:**
- `overall_risk_score` = 8.5 → `t_block` = clamp(75 − (8.5−50)×0.5, 40, 95) = clamp(75 + 20.75, 40, 95) = **95.0** (clamped)
- `t_review` = clamp(50 + 20.75, 20, 70) = **70.0** (clamped)
- `match_score` = 68.0 < 70.0 → **CLEAR**

A static threshold at 65 would have returned REVIEW for this account. The dynamic threshold correctly identifies it as a coincidental match.

---

#### Case 3: PEP account with medium match score — REVIEW

```python
{
    "account_type": "individual",
    "kyc_completeness": 0.7,
    "kyc_status": "partial",
    "is_pep": 1,
    "has_complex_ownership": 0,
    "shell_company_flag": 0,
    "activity_tier": "medium",
    "account_status": "active",
    "match_score": 55.0,
    "shares_address_with_sanctioned": 0,
    "pep_exposure_score": 80.0,
    "country_risk_score": 45.0,
    "geographic_risk": 45.0,
    "identity_kyc_risk": 30.0,
    "pep_sanctions_risk": 75.0,
    "behavioural_risk": 25.0,
    "relationship_network_risk": 30.0,
    "overall_risk_score": 52.0,
    "override_applied": 0,
}
```

**Expected result:**
- `overall_risk_score` = 52.0 → `t_block` = clamp(75 − (52−50)×0.5, 40, 95) = clamp(74.0, 40, 95) = **74.0**
- `t_review` = clamp(50 − 1.0, 20, 70) = **49.0**
- `match_score` = 55.0 ≥ 49.0 and < 74.0 → **REVIEW**

This PEP account has an elevated overall risk score but not enough of a name match to auto-block. The verdict REVIEW correctly routes the case to a human analyst who can assess whether the 55/100 fuzzy match against the sanctions list is credible.

---

## 13. Files in This Directory

```
ai/
├── README.md                   ← This document
└── model/
    ├── model_binary.ubj        ← XGBoost binary classifier (BLOCK vs not-BLOCK)
    │                             Trained with binary:logistic, scale_pos_weight=424.5
    │                             CV ROC-AUC: 0.9999 ± 0.0001
    │
    ├── model_multiclass.ubj    ← XGBoost multiclass classifier (BLOCK / REVIEW / CLEAR)
    │                             Trained with multi:softprob, 3 classes
    │                             CV macro-F1: 0.9964 ± 0.0066
    │
    ├── model_metadata.json     ← Feature schema, threshold formulas, output schema,
    │                             feature importances for both models
    │
    ├── predict.py              ← Inference module — import and call screen()
    │                             Self-contained; loads both models on first call
    │
    ├── xgb_report.md           ← Full training report with confusion matrices
    │                             and complete feature importance rankings
    │
    └── xgb_results.json        ← Machine-readable training metrics, importances,
                                  and label distribution (generated by training script)
```

### Quick reference: model files

| File | Format | Description |
|---|---|---|
| `model_binary.ubj` | XGBoost UBJ (Universal Binary JSON) | Binary BLOCK/not-BLOCK classifier |
| `model_multiclass.ubj` | XGBoost UBJ | Three-class BLOCK/REVIEW/CLEAR classifier |
| `model_metadata.json` | JSON | Feature order, encoding specs, threshold formulas, importance scores |
| `predict.py` | Python 3.9+ | `screen()` function — the single entry point for all inference |

The `.ubj` format is XGBoost's native binary format. Load with:
```python
import xgboost as xgb
model = xgb.XGBClassifier()
model.load_model("model/model_binary.ubj")
```
