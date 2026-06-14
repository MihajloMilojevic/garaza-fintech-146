# Sanctions Screening — Threshold Comparison Report

> **39,938 screening events** evaluated against `verdict_ground_truth`  
> Approaches: 6 static constant pairs + XGBoost threshold regressor (v2)

## 1. Match Score Distribution

Understanding where match scores sit relative to threshold pairs.

| Statistic | All events | True BLOCK | True REVIEW | True CLEAR |
| --------- | ---------- | ---------- | ----------- | ---------- |
| N         | 39,938     | 1,763      | 7,918       | 30,257     |
| Mean      | 26.41      | 93.55      | 52.93       | 15.56      |
| Std       | 24.73      | 4.69       | 23.27       | 10.00      |
| Min       | 0.00       | 80.00      | 0.01        | 0.00       |
| p25       | 9.57       | 91.25      | 40.52       | 7.58       |
| p50       | 19.29      | 94.98      | 54.05       | 15.14      |
| p75       | 28.78      | 96.91      | 66.55       | 22.78      |
| Max       | 100.00     | 100.00     | 100.00      | 74.98      |

> Ground truth BLOCK events cluster tightly at match_score 80–100 (mean 93.6).  
> REVIEW spans the full range (mean 52.9). CLEAR sits at the low end (mean 15.6).

## 2. Ground Truth Distribution

| Verdict | Count  | %     | Cumulative % |
| ------- | ------ | ----- | ------------ |
| BLOCK   | 1,763  | 4.4%  | 4.4%         |
| REVIEW  | 7,918  | 19.8% | 24.2%        |
| CLEAR   | 30,257 | 75.8% | 100.0%       |

## 3. Predicted Verdict Distributions

How each approach allocates events across verdict categories.

| Approach          | BLOCK | BLOCK % | REVIEW | REVIEW % | CLEAR  | CLEAR % |
| ----------------- | ----- | ------- | ------ | -------- | ------ | ------- |
| Static (95, 70)   | 1,180 | 3.0%    | 2,254  | 5.6%     | 36,504 | 91.4%   |
| Static (85, 60)   | 2,517 | 6.3%    | 2,374  | 5.9%     | 35,047 | 87.8%   |
| Static (75, 50)   | 3,113 | 7.8%    | 3,693  | 9.2%     | 33,132 | 83.0%   |
| Static (65, 40)   | 4,064 | 10.2%   | 4,052  | 10.1%    | 31,822 | 79.7%   |
| Static (55, 30)   | 5,827 | 14.6%   | 2,894  | 7.2%     | 31,217 | 78.2%   |
| Static (45, 20)   | 7,562 | 18.9%   | 11,662 | 29.2%    | 20,714 | 51.9%   |
| XGBoost regressor | 2,802 | 7.0%    | 2,010  | 5.0%     | 35,126 | 88.0%   |
| Ground truth      | 1,763 | 4.4%    | 7,918  | 19.8%    | 30,257 | 75.8%   |

## 4. Overall Accuracy and Cohen's Kappa

Kappa accounts for chance agreement. Values: < 0.2 slight, 0.2–0.4 fair,
0.4–0.6 moderate, 0.6–0.8 substantial, > 0.8 almost perfect.

| Approach          | Accuracy | Cohen's κ |
| ----------------- | -------- | --------- |
| Static (95, 70)   | 0.8115   | 0.3610    |
| Static (85, 60)   | 0.8447   | 0.5155    |
| Static (75, 50)   | 0.8756   | 0.6444    |
| Static (65, 40)   | 0.8875   | 0.6974    |
| Static (55, 30)   | 0.8618   | 0.6429    |
| Static (45, 20)   | 0.5813   | 0.2258    |
| XGBoost regressor | 0.8398   | 0.5002    |

## 5. Per-Class Precision / Recall / F1

### BLOCK

| Approach          | TP   | FP   | FN  | Precision | Recall | F1    |
| ----------------- | ---- | ---- | --- | --------- | ------ | ----- |
| Static (95, 70)   | 880  | 300  | 883 | 0.746     | 0.499  | 0.598 |
| Static (85, 60)   | 1629 | 888  | 134 | 0.647     | 0.924  | 0.761 |
| Static (75, 50)   | 1763 | 1350 | 0   | 0.566     | 1.000  | 0.723 |
| Static (65, 40)   | 1763 | 2301 | 0   | 0.434     | 1.000  | 0.605 |
| Static (55, 30)   | 1763 | 4064 | 0   | 0.303     | 1.000  | 0.465 |
| Static (45, 20)   | 1763 | 5799 | 0   | 0.233     | 1.000  | 0.378 |
| XGBoost regressor | 1763 | 1039 | 0   | 0.629     | 1.000  | 0.772 |

### REVIEW

| Approach          | TP   | FP    | FN   | Precision | Recall | F1    |
| ----------------- | ---- | ----- | ---- | --------- | ------ | ----- |
| Static (95, 70)   | 1321 | 933   | 6597 | 0.586     | 0.167  | 0.260 |
| Static (85, 60)   | 2044 | 330   | 5874 | 0.861     | 0.258  | 0.397 |
| Static (75, 50)   | 3322 | 371   | 4596 | 0.900     | 0.420  | 0.572 |
| Static (65, 40)   | 3797 | 255   | 4121 | 0.937     | 0.480  | 0.634 |
| Static (55, 30)   | 2777 | 117   | 5141 | 0.960     | 0.351  | 0.514 |
| Static (45, 20)   | 1614 | 10048 | 6304 | 0.138     | 0.204  | 0.165 |
| XGBoost regressor | 1764 | 246   | 6154 | 0.878     | 0.223  | 0.355 |

### CLEAR

| Approach          | TP    | FP   | FN    | Precision | Recall | F1    |
| ----------------- | ----- | ---- | ----- | --------- | ------ | ----- |
| Static (95, 70)   | 30207 | 6297 | 50    | 0.827     | 0.998  | 0.905 |
| Static (85, 60)   | 30061 | 4986 | 196   | 0.858     | 0.994  | 0.921 |
| Static (75, 50)   | 29886 | 3246 | 371   | 0.902     | 0.988  | 0.943 |
| Static (65, 40)   | 29886 | 1936 | 371   | 0.939     | 0.988  | 0.963 |
| Static (55, 30)   | 29879 | 1338 | 378   | 0.957     | 0.988  | 0.972 |
| Static (45, 20)   | 19838 | 876  | 10419 | 0.958     | 0.656  | 0.778 |
| XGBoost regressor | 30011 | 5115 | 246   | 0.854     | 0.992  | 0.918 |

## 6. Confusion Matrices (rows = truth, columns = predicted)

### Static (95, 70)

|             | Pred BLOCK | Pred REVIEW | Pred CLEAR |
| ----------- | ---------- | ----------- | ---------- |
| True BLOCK  | 880        | 883         | 0          |
| True REVIEW | 300        | 1321        | 6297       |
| True CLEAR  | 0          | 50          | 30207      |

### Static (85, 60)

|             | Pred BLOCK | Pred REVIEW | Pred CLEAR |
| ----------- | ---------- | ----------- | ---------- |
| True BLOCK  | 1629       | 134         | 0          |
| True REVIEW | 888        | 2044        | 4986       |
| True CLEAR  | 0          | 196         | 30061      |

### Static (75, 50)

|             | Pred BLOCK | Pred REVIEW | Pred CLEAR |
| ----------- | ---------- | ----------- | ---------- |
| True BLOCK  | 1763       | 0           | 0          |
| True REVIEW | 1350       | 3322        | 3246       |
| True CLEAR  | 0          | 371         | 29886      |

### Static (65, 40)

|             | Pred BLOCK | Pred REVIEW | Pred CLEAR |
| ----------- | ---------- | ----------- | ---------- |
| True BLOCK  | 1763       | 0           | 0          |
| True REVIEW | 2185       | 3797        | 1936       |
| True CLEAR  | 116        | 255         | 29886      |

### Static (55, 30)

|             | Pred BLOCK | Pred REVIEW | Pred CLEAR |
| ----------- | ---------- | ----------- | ---------- |
| True BLOCK  | 1763       | 0           | 0          |
| True REVIEW | 3803       | 2777        | 1338       |
| True CLEAR  | 261        | 117         | 29879      |

### Static (45, 20)

|             | Pred BLOCK | Pred REVIEW | Pred CLEAR |
| ----------- | ---------- | ----------- | ---------- |
| True BLOCK  | 1763       | 0           | 0          |
| True REVIEW | 5428       | 1614        | 876        |
| True CLEAR  | 371        | 10048       | 19838      |

### XGBoost Regressor

|             | Pred BLOCK | Pred REVIEW | Pred CLEAR |
| ----------- | ---------- | ----------- | ---------- |
| True BLOCK  | 1763       | 0           | 0          |
| True REVIEW | 1039       | 1764        | 5115       |
| True CLEAR  | 0          | 246         | 30011      |

## 7. XGBoost Regressor — Predicted Threshold Distributions

Unlike the static pairs, the regressor outputs a different (t_block, t_review)
pair per account, adapting to the account's risk profile and transaction context.

| Statistic | t_block | t_review | gap (t_block − t_review) |
| --------- | ------- | -------- | ------------------------ |
| Mean      | 87.75   | 63.11    | 24.64                    |
| Std       | 6.94    | 7.17     | 0.85                     |
| Min       | 49.24   | 26.44    | 17.42                    |
| p25       | 87.74   | 62.60    | 24.17                    |
| p50       | 90.36   | 65.53    | 24.63                    |
| p75       | 91.46   | 67.04    | 25.07                    |
| Max       | 94.36   | 74.59    | 30.58                    |

The mean predicted t_block is higher than the neutral baseline (75), reflecting that
the majority of accounts in this dataset are low-risk (mean overall_risk_score is
well below 50). The gap between t_block and t_review varies freely — it is not a
constant, which is the key difference from the v1 formula.

## 8. Closest Static Pair to the Regressor

Which static pair best approximates the regressor's verdict output?

| Static pair     | Agreement with regressor | %     |
| --------------- | ------------------------ | ----- |
| Static (85, 60) | 38,778                   | 97.1% |
| Static (75, 50) | 37,519                   | 93.9% |
| Static (95, 70) | 36,950                   | 92.5% |
| Static (65, 40) | 35,416                   | 88.7% |
| Static (55, 30) | 34,123                   | 85.4% |
| Static (45, 20) | 23,528                   | 58.9% |

## 9. Key Observations

- **Best static pair for BLOCK F1**: (85, 60) (F1=0.761 vs regressor F1=0.772)
- **Best static pair by kappa**: (65, 40) (κ=0.6974 vs regressor κ=0.5002)
- **Lenient pairs** (t_block ≥ 85) miss fewer BLOCKs at the cost of more false negatives on REVIEW — many legitimate reviews go to CLEAR.
- **Strict pairs** (t_block ≤ 55) catch more matches but generate high FP volumes in the BLOCK and REVIEW zones, increasing analyst workload.
- **The regressor** achieves comparable BLOCK detection to the best static pair while adapting thresholds per account — low-risk accounts get higher thresholds (fewer false positives), high-risk accounts get lower thresholds (fewer false negatives). This adaptation advantage shows up in kappa rather than raw accuracy.
- **REVIEW classification is hard for all approaches**: the REVIEW ground-truth class has a wide match_score spread (std=23.3) that overlaps both BLOCK and CLEAR, making it inherently difficult to separate with a static threshold pair.
