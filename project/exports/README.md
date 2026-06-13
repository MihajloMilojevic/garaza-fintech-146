# Sanctions Screening Synthetic Dataset

## Overview

Synthetic dataset for training and evaluating sanctions screening and AML models.
Generated: 2026-06-13

## Tables

| Table | Rows | File(s) |
|---|---|---|
| accounts | 20,000 | accounts.parquet |
| account_relationships | 13,088 | account_relationships.parquet |
| wallets | 3,379 | wallets.parquet |
| transactions | 199,387 | transactions.parquet |
| screening_results | 39,938 | screening_results.parquet |
| risk_scores | 20,000 | risk_scores.parquet |
| threshold_decisions | 39,938 | threshold_decisions.parquet |
| explanatory_logs | 3,378 | explanatory_logs.parquet |

## Column Descriptions (key tables)

### accounts
| Column | Description |
|---|---|
| account_id | Unique account identifier (ACC-XXXXXXXX) |
| account_type | individual / business |
| full_name | Synthetic name of account holder |
| country_residence | ISO-2 country of residence |
| country_incorporation | ISO-2 country of incorporation (business only) |
| kyc_completeness | 0.0–1.0 fraction of KYC fields completed |
| kyc_status | verified / pending / expired |
| is_pep | 1 if politically exposed person |
| sanctioned_entity_id | Linked sanctioned entity ID (if applicable) |
| name_match_type | exact / alias / fuzzy / null |
| activity_tier | high / medium / low |

### risk_scores
| Column | Description |
|---|---|
| risk_score_id | RSK-XXXXXXXX |
| account_id | Foreign key to accounts |
| geographic_risk | 0–100 geographic component |
| identity_kyc_risk | 0–100 KYC/identity component |
| pep_sanctions_risk | 0–100 sanctions/PEP component |
| behavioural_risk | 0–100 transaction behaviour component |
| relationship_network_risk | 0–100 network component |
| overall_risk_score | Weighted composite score (0–100) |
| risk_band | CRITICAL / HIGH / MEDIUM / LOW |
| override_applied | 1 if an analyst override was simulated |
| override_reason | Text reason for override or NULL |

### threshold_decisions
| Column | Description |
|---|---|
| decision_id | DEC-XXXXXXXX |
| screening_id | FK to screening_results |
| static_threshold | Fixed threshold (75.0) |
| static_verdict | BLOCK / REVIEW / CLEAR under static rule |
| dynamic_t_block | Risk-adjusted block threshold |
| dynamic_t_review | Risk-adjusted review threshold |
| dynamic_verdict | BLOCK / REVIEW / CLEAR under dynamic rule |
| verdicts_differ | 1 if the two verdicts disagree |

## Reference Data Sources

| Source | Status |
|---|---|
| sanctioned_entities | real |
| peps | real |
| matching_pairs | real |
| aml_shape | real |
| relationships | real_ftm |

## Risk Score Formula

```
overall_risk_score = (
    0.25 * geographic_risk +
    0.15 * identity_kyc_risk +
    0.30 * pep_sanctions_risk +
    0.20 * behavioural_risk +
    0.10 * relationship_network_risk
)
```
Capped at 100. Bands: CRITICAL ≥ 80, HIGH ≥ 60, MEDIUM ≥ 40, LOW < 40.

## Dynamic Threshold Formula

```
risk_adjustment  = (overall_risk_score - 50) * 0.3
dynamic_t_block  = clamp(75 - risk_adjustment, 40, 90)
dynamic_t_review = clamp(50 - risk_adjustment, 25, 65)
```
High-risk accounts get a lower (more sensitive) block threshold.

## Loading the Dataset

```python
from load_dataset import load_table

accounts = load_table('accounts')
risk_scores = load_table('risk_scores')
```

The `load_table` helper automatically handles split files via manifest.

### Manual load (single file)
```python
import pandas as pd
df = pd.read_parquet('accounts.parquet')
```
