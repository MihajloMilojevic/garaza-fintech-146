# Sanctions Screening Dataset — Comparison Summary

_Generated at: 2026-06-13T23:54:17_

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
Verdicts differ: **3,266** (8.2%)

### Confusion Matrix (static_verdict → dynamic_verdict)

| Static \ Dynamic | BLOCK | REVIEW | CLEAR |
|---|---|---|---|
| BLOCK | 2798 | 1194 | 72 |
| REVIEW | 8 | 773 | 1961 |
| CLEAR | 0 | 31 | 33101 |

### Classification Metrics (positive class = BLOCK)

| Metric | Static | Dynamic |
|---|---|---|
| Precision | 0.4338 | 0.6283 |
| Recall    | 1.0000  | 1.0000  |
| F1        | 0.6051   | 0.7717   |
| TP        | 1,763 | 1,763 |
| FP        | 2,301 | 1,043 |
| FN        | 0 | 0 |
| TN        | 35,874 | 37,132 |

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
| static_precision        | 0.4338 |
| static_recall           | 1.0000 |
| static_f1               | 0.6051 |
| dynamic_precision       | 0.6283 |
| dynamic_recall          | 1.0000 |
| dynamic_f1              | 0.7717 |
| verdicts_differ_count   | 3,266 |
| verdicts_differ_pct     | 8.18% |
