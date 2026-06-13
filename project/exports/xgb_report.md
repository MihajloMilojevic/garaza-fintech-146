# XGBoost Training Results

_Generated at: 2026-06-14T01:54:26.607363_

## Dataset

| Label | Count | % |
|---|---|---|
| CLEAR | 19,047 | 95.2% |
| REVIEW | 906 | 4.5% |
| BLOCK | 47 | 0.2% |

Total samples: **20,000** (account-level screening results only)

---

## 1. Binary Model — BLOCK vs not-BLOCK

> Positive class = BLOCK. `scale_pos_weight = 424.5` to handle class imbalance.

### Cross-Validation (5-fold, stratified)

| Metric | Mean | Std |
|---|---|---|
| ROC-AUC | 0.9999 | ±0.0001 |
| F1 (BLOCK) | 0.9610 | ±0.0372 |

### In-Sample Metrics

| Metric | Value |
|---|---|
| ROC-AUC | 1.0000 |
| Precision (BLOCK) | 0.9216 |
| Recall (BLOCK) | 1.0000 |
| F1 (BLOCK) | 0.9592 |

### Confusion Matrix (in-sample)

| | Pred not-BLOCK | Pred BLOCK |
|---|---|---|
| True not-BLOCK | 19,949 | 4 |
| True BLOCK     | 0 | 47 |

### Top 15 Feature Importances

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

---

## 2. Multiclass Model — BLOCK / REVIEW / CLEAR

### Cross-Validation (5-fold, macro-F1)

| Metric | Mean | Std |
|---|---|---|
| Macro F1 | 0.9964 | ±0.0066 |

### Confusion Matrix (in-sample)

| | Pred BLOCK | Pred CLEAR | Pred REVIEW |
|---|---|---|---|
| True BLOCK | 47 | 0 | 0 |
| True CLEAR | 0 | 19047 | 0 |
| True REVIEW | 0 | 0 | 906 |

### Top 15 Feature Importances

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

---

## 3. Learnability Verdict

CV ROC-AUC = **0.9999** (threshold ≥ 0.9)

**✓ DATASET IS LEARNABLE**

---

## 4. Model Files

| File | Description |
|---|---|
| `exports/model_binary.ubj` | Binary XGBoost (BLOCK vs not-BLOCK) |
| `exports/model_multiclass.ubj` | Multiclass XGBoost (BLOCK/REVIEW/CLEAR) |
| `exports/xgb_results.json` | Full metrics + importances |
