# Sanctions Screening Dataset — Comparison Summary

_Generated at: 2026-06-13T23:31:26_

## 1. Dataset Summary

### Table Row Counts

| Table | Row Count |
|---|---|
| accounts | 20,000 |
| account_relationships | 13,088 |
| wallets | 3,379 |
| transactions | 199,387 |
| screening_results | 39,938 |
| risk_scores | 20,000 |
| threshold_decisions | 39,938 |
| explanatory_logs | 3,378 |

### Screening Result Verdict Distribution

| Verdict | Count | % |
|---|---|---|
| BLOCK | 1,763 | 4.4% |
| CLEAR | 30,257 | 75.8% |
| REVIEW | 7,918 | 19.8% |

### Reference Data Sources

| Source | Value |
|---|---|
| sanctioned_entities | real |
| peps | real |
| matching_pairs | real |
| aml_shape | real |
| relationships | real_ftm |

## 2. Static vs Dynamic Threshold Comparison

Total decisions evaluated: **39,938**
Verdicts differ: **1,639** (4.1%)

### Confusion Matrix (static_verdict → dynamic_verdict)

| Static \ Dynamic | BLOCK | REVIEW | CLEAR |
|---|---|---|---|
| BLOCK | 2783 | 330 | 0 |
| REVIEW | 14 | 2397 | 1282 |
| CLEAR | 0 | 13 | 33119 |

### Classification Metrics (positive class = BLOCK)

| Metric | Static | Dynamic |
|---|---|---|
| Precision | 0.5663 | 0.6303 |
| Recall    | 1.0000  | 1.0000  |
| F1        | 0.7231   | 0.7732   |
| TP        | 1,763 | 1,763 |
| FP        | 1,350 | 1,034 |
| FN        | 0 | 0 |
| TN        | 36,825 | 37,141 |

## 3. Risk Score Distribution

### Count by Risk Band

| Band | Count |
|---|---|
| CRITICAL | 201 |
| HIGH | 38 |
| MEDIUM | 508 |
| LOW | 19,253 |

Overall risk score — mean: **19.0415**, std: **10.3284**

### Mean ± Std by Account Type

| Account Type | Count | Mean | Std |
|---|---|---|---|
| business | 5,820 | 22.2033 | 15.1089 |
| individual | 14,180 | 17.7437 | 7.1408 |

## 4. Key Metrics Summary

| Metric | Value |
|---|---|
| static_precision        | 0.5663 |
| static_recall           | 1.0000 |
| static_f1               | 0.7231 |
| dynamic_precision       | 0.6303 |
| dynamic_recall          | 1.0000 |
| dynamic_f1              | 0.7732 |
| verdicts_differ_count   | 1,639 |
| verdicts_differ_pct     | 4.10% |
