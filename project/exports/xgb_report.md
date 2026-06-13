# XGBoost Training Results

_Generated at: 2026-06-14T01:42:50.343051_

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
| ROC-AUC | 1.0000 | ±0.0000 |
| F1 (BLOCK) | 1.0000 | ±0.0000 |

### In-Sample Metrics

| Metric | Value |
|---|---|
| ROC-AUC | 1.0000 |
| Precision (BLOCK) | 1.0000 |
| Recall (BLOCK) | 1.0000 |
| F1 (BLOCK) | 1.0000 |

### Confusion Matrix (in-sample)

| | Pred not-BLOCK | Pred BLOCK |
|---|---|---|
| True not-BLOCK | 19,953 | 0 |
| True BLOCK     | 0 | 47 |

### Top 15 Feature Importances

| Rank | Feature | Importance |
|---|---|---|
| 1 | `hops_to_sanctioned` | 0.5474 |
| 2 | `name_match_type_enc` | 0.2910 |
| 3 | `pep_sanctions_risk` | 0.1539 |
| 4 | `dynamic_verdict_enc` | 0.0076 |
| 5 | `identity_kyc_risk` | 0.0002 |
| 6 | `account_type_enc` | 0.0000 |
| 7 | `kyc_completeness` | 0.0000 |
| 8 | `kyc_status_enc` | 0.0000 |
| 9 | `is_pep` | 0.0000 |
| 10 | `has_complex_ownership` | 0.0000 |
| 11 | `shell_company_flag` | 0.0000 |
| 12 | `activity_tier_enc` | 0.0000 |
| 13 | `account_status_enc` | 0.0000 |
| 14 | `match_score` | 0.0000 |
| 15 | `shares_address_with_sanctioned` | 0.0000 |

---

## 2. Multiclass Model — BLOCK / REVIEW / CLEAR

### Cross-Validation (5-fold, macro-F1)

| Metric | Mean | Std |
|---|---|---|
| Macro F1 | 0.9998 | ±0.0004 |

### Confusion Matrix (in-sample)

| | Pred BLOCK | Pred CLEAR | Pred REVIEW |
|---|---|---|---|
| True BLOCK | 47 | 0 | 0 |
| True CLEAR | 0 | 19047 | 0 |
| True REVIEW | 0 | 0 | 906 |

### Top 15 Feature Importances

| Rank | Feature | Importance |
|---|---|---|
| 1 | `dynamic_t_block` | 0.2467 |
| 2 | `overall_risk_score` | 0.2215 |
| 3 | `name_match_type_enc` | 0.1636 |
| 4 | `dynamic_t_review` | 0.1568 |
| 5 | `kyc_completeness` | 0.0356 |
| 6 | `country_risk_score` | 0.0315 |
| 7 | `geographic_risk` | 0.0230 |
| 8 | `static_verdict_enc` | 0.0222 |
| 9 | `match_score` | 0.0198 |
| 10 | `hops_to_sanctioned` | 0.0167 |
| 11 | `verdicts_differ` | 0.0155 |
| 12 | `identity_kyc_risk` | 0.0133 |
| 13 | `pep_sanctions_risk` | 0.0119 |
| 14 | `has_complex_ownership` | 0.0062 |
| 15 | `relationship_network_risk` | 0.0040 |

---

## 3. Learnability Verdict

CV ROC-AUC = **1.0000** (threshold ≥ 0.85)

**✓ DATASET IS LEARNABLE**

---

## 4. Model Files

| File | Description |
|---|---|
| `exports/model_binary.ubj` | Binary XGBoost (BLOCK vs not-BLOCK) |
| `exports/model_multiclass.ubj` | Multiclass XGBoost (BLOCK/REVIEW/CLEAR) |
| `exports/xgb_results.json` | Full metrics + importances |
