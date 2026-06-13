#!/usr/bin/env python3
"""
11_train_xgboost.py — First XGBoost pass on the sanctions screening dataset.

Trains two models:
  1. Binary classifier: BLOCK vs (REVIEW | CLEAR)  — positive class = BLOCK
  2. Multiclass classifier: BLOCK / REVIEW / CLEAR

Uses account-level screening results joined with risk_score + threshold features.
Validates dataset is learnable and reports feature importances.

Outputs:
  exports/model_binary.ubj       — binary XGBoost model
  exports/model_multiclass.ubj   — multiclass XGBoost model
  exports/xgb_results.json       — metrics + feature importances
  exports/xgb_report.md          — human-readable summary
"""

import json
import sqlite3
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore")

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH     = PROJECT_DIR / "sanctions_screening.db"
EXPORTS     = PROJECT_DIR / "exports"
EXPORTS.mkdir(exist_ok=True)

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_PATH = PROJECT_DIR / "logs" / "generation_log.txt"

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    line = f"{ts} [INFO] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

# ── Load and join data ────────────────────────────────────────────────────────
log("=== 11_train_xgboost.py started ===")
log("Loading data from database …")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Account-level screening only (20 000 rows — clean label assignment)
query = """
SELECT
    -- identity
    a.account_id,
    a.account_type,
    a.kyc_completeness,
    CASE a.kyc_status
        WHEN 'complete' THEN 0
        WHEN 'partial'  THEN 1
        WHEN 'pending'  THEN 2
        WHEN 'expired'  THEN 3
        ELSE 2
    END                             AS kyc_status_enc,
    a.is_pep,
    a.has_complex_ownership,
    a.shell_company_flag,
    CASE a.name_match_type
        WHEN 'none'           THEN 0
        WHEN 'fuzzy_near_miss' THEN 1
        WHEN 'alias'          THEN 2
        WHEN 'exact'          THEN 3
        ELSE 0
    END                             AS name_match_type_enc,
    CASE a.activity_tier
        WHEN 'low'    THEN 0
        WHEN 'medium' THEN 1
        WHEN 'high'   THEN 2
        ELSE 0
    END                             AS activity_tier_enc,
    CASE a.account_status
        WHEN 'active'    THEN 0
        WHEN 'suspended' THEN 1
        WHEN 'closed'    THEN 2
        ELSE 0
    END                             AS account_status_enc,

    -- screening features
    s.match_score,
    COALESCE(s.hops_to_sanctioned, 9)        AS hops_to_sanctioned,
    s.shares_address_with_sanctioned,
    s.pep_exposure_score,
    s.country_risk_score,

    -- risk score components
    r.geographic_risk,
    r.identity_kyc_risk,
    r.pep_sanctions_risk,
    r.behavioural_risk,
    r.relationship_network_risk,
    r.overall_risk_score,
    r.override_applied,

    -- threshold features
    t.static_threshold,
    t.dynamic_t_block,
    t.dynamic_t_review,
    CASE t.static_verdict
        WHEN 'CLEAR'  THEN 0
        WHEN 'REVIEW' THEN 1
        WHEN 'BLOCK'  THEN 2
        ELSE 0
    END                             AS static_verdict_enc,
    CASE t.dynamic_verdict
        WHEN 'CLEAR'  THEN 0
        WHEN 'REVIEW' THEN 1
        WHEN 'BLOCK'  THEN 2
        ELSE 0
    END                             AS dynamic_verdict_enc,
    t.verdicts_differ,

    -- label
    s.verdict_ground_truth

FROM screening_results s
JOIN accounts          a ON a.account_id   = s.account_id
JOIN risk_scores       r ON r.account_id   = s.account_id
JOIN threshold_decisions t ON t.screening_id = s.screening_id
WHERE s.screening_context = 'account'
"""

df = pd.read_sql_query(query, conn)
conn.close()

log(f"Loaded {len(df):,} rows.")
log(f"Label distribution:\n{df['verdict_ground_truth'].value_counts().to_string()}")

# ── Feature matrix ────────────────────────────────────────────────────────────
FEATURE_COLS = [
    "account_type_enc",
    "kyc_completeness",
    "kyc_status_enc",
    "is_pep",
    "has_complex_ownership",
    "shell_company_flag",
    "name_match_type_enc",
    "activity_tier_enc",
    "account_status_enc",
    "match_score",
    "hops_to_sanctioned",
    "shares_address_with_sanctioned",
    "pep_exposure_score",
    "country_risk_score",
    "geographic_risk",
    "identity_kyc_risk",
    "pep_sanctions_risk",
    "behavioural_risk",
    "relationship_network_risk",
    "overall_risk_score",
    "override_applied",
    "static_threshold",
    "dynamic_t_block",
    "dynamic_t_review",
    "static_verdict_enc",
    "dynamic_verdict_enc",
    "verdicts_differ",
]

# account_type: individual=0, business=1
df["account_type_enc"] = (df["account_type"] == "business").astype(int)

# Fill any NULLs
df[FEATURE_COLS] = df[FEATURE_COLS].fillna(0)

X = df[FEATURE_COLS].values
y_raw = df["verdict_ground_truth"].values

# ── Binary label (BLOCK = 1, else = 0) ───────────────────────────────────────
y_bin = (y_raw == "BLOCK").astype(int)

# ── Multiclass label ──────────────────────────────────────────────────────────
le = LabelEncoder()
y_multi = le.fit_transform(y_raw)   # BLOCK=0, CLEAR=1, REVIEW=2  (alphabetical)
class_names = list(le.classes_)
log(f"Multiclass encoding: {dict(zip(class_names, le.transform(class_names)))}")

# ── Scale weights for imbalanced classes ──────────────────────────────────────
block_count  = (y_bin == 1).sum()
other_count  = (y_bin == 0).sum()
scale_pos    = other_count / max(block_count, 1)
log(f"Binary: {block_count} BLOCK, {other_count} non-BLOCK. scale_pos_weight={scale_pos:.1f}")

# ── Shared XGBoost hyperparameters ───────────────────────────────────────────
COMMON_PARAMS = dict(
    n_estimators     = 200,
    max_depth        = 5,
    learning_rate    = 0.1,
    subsample        = 0.8,
    colsample_bytree = 0.8,
    min_child_weight = 3,
    gamma            = 0.1,
    reg_alpha        = 0.1,
    reg_lambda       = 1.0,
    random_state     = 42,
    n_jobs           = -1,
    eval_metric      = "logloss",
)

# ── 5-fold CV helper ──────────────────────────────────────────────────────────
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

def cv_metrics_binary(model, X, y):
    aucs = cross_val_score(model, X, y, cv=cv, scoring="roc_auc")
    f1s  = cross_val_score(model, X, y, cv=cv, scoring="f1")
    return {
        "roc_auc_mean": float(aucs.mean()),
        "roc_auc_std":  float(aucs.std()),
        "f1_mean":      float(f1s.mean()),
        "f1_std":       float(f1s.std()),
    }

# ── 1. Binary model ───────────────────────────────────────────────────────────
log("Training binary model (BLOCK vs not-BLOCK) …")

bin_model = xgb.XGBClassifier(
    objective        = "binary:logistic",
    scale_pos_weight = scale_pos,
    **COMMON_PARAMS,
)
bin_model.fit(X, y_bin)

# In-sample (sanity) + CV
y_pred_bin  = bin_model.predict(X)
y_prob_bin  = bin_model.predict_proba(X)[:, 1]

log("Binary — in-sample classification report:")
report_bin = classification_report(y_bin, y_pred_bin, target_names=["not-BLOCK", "BLOCK"])
print(report_bin)

auc_insample = roc_auc_score(y_bin, y_prob_bin)
log(f"Binary — in-sample ROC-AUC: {auc_insample:.4f}")

log("Binary — running 5-fold CV …")
cv_bin = cv_metrics_binary(
    xgb.XGBClassifier(objective="binary:logistic", scale_pos_weight=scale_pos, **COMMON_PARAMS),
    X, y_bin
)
log(f"Binary — CV ROC-AUC: {cv_bin['roc_auc_mean']:.4f} ± {cv_bin['roc_auc_std']:.4f}")
log(f"Binary — CV F1:      {cv_bin['f1_mean']:.4f} ± {cv_bin['f1_std']:.4f}")

# Feature importances (binary)
fi_bin = dict(zip(FEATURE_COLS, bin_model.feature_importances_.tolist()))
fi_bin_sorted = sorted(fi_bin.items(), key=lambda x: -x[1])
log("Binary — top 10 features by importance:")
for feat, imp in fi_bin_sorted[:10]:
    log(f"  {feat:<35} {imp:.4f}")

# Save binary model
bin_model_path = EXPORTS / "model_binary.ubj"
bin_model.save_model(str(bin_model_path))
log(f"Binary model saved → {bin_model_path}")

# ── 2. Multiclass model ───────────────────────────────────────────────────────
log("Training multiclass model (BLOCK / REVIEW / CLEAR) …")

# Class weights: BLOCK is rare, weight it higher
class_counts = np.bincount(y_multi)
sample_weight = np.where(
    y_raw == "BLOCK",  10.0,
    np.where(y_raw == "REVIEW", 2.0, 1.0)
)

multi_model = xgb.XGBClassifier(
    objective    = "multi:softprob",
    num_class    = len(class_names),
    **{k: v for k, v in COMMON_PARAMS.items() if k != "eval_metric"},
    eval_metric  = "mlogloss",
)
multi_model.fit(X, y_multi, sample_weight=sample_weight)

y_pred_multi = multi_model.predict(X)

log("Multiclass — in-sample classification report:")
report_multi = classification_report(
    y_multi, y_pred_multi, target_names=class_names
)
print(report_multi)

# Macro-average F1 via CV
log("Multiclass — running 5-fold CV (macro-F1) …")
# Manual CV to pass sample_weight through fit_params
cv_multi_f1_scores = []
for train_idx, val_idx in cv.split(X, y_multi):
    _m = xgb.XGBClassifier(
        objective   = "multi:softprob",
        num_class   = len(class_names),
        **{k: v for k, v in COMMON_PARAMS.items() if k != "eval_metric"},
        eval_metric = "mlogloss",
    )
    _m.fit(X[train_idx], y_multi[train_idx], sample_weight=sample_weight[train_idx])
    _pred = _m.predict(X[val_idx])
    cv_multi_f1_scores.append(f1_score(y_multi[val_idx], _pred, average="macro"))
cv_multi_f1 = np.array(cv_multi_f1_scores)
log(f"Multiclass — CV macro-F1: {cv_multi_f1.mean():.4f} ± {cv_multi_f1.std():.4f}")

# Feature importances (multiclass)
fi_multi = dict(zip(FEATURE_COLS, multi_model.feature_importances_.tolist()))
fi_multi_sorted = sorted(fi_multi.items(), key=lambda x: -x[1])
log("Multiclass — top 10 features by importance:")
for feat, imp in fi_multi_sorted[:10]:
    log(f"  {feat:<35} {imp:.4f}")

# Save multiclass model
multi_model_path = EXPORTS / "model_multiclass.ubj"
multi_model.save_model(str(multi_model_path))
log(f"Multiclass model saved → {multi_model_path}")

# ── 3. Confusion matrices ─────────────────────────────────────────────────────
cm_bin   = confusion_matrix(y_bin, y_pred_bin).tolist()
cm_multi = confusion_matrix(y_multi, y_pred_multi).tolist()

# ── 4. Learnability check ─────────────────────────────────────────────────────
# A learnable dataset should have CV ROC-AUC >> 0.5 and CV F1 >> baseline
LEARNABLE_AUC_THRESHOLD = 0.85
is_learnable = cv_bin["roc_auc_mean"] >= LEARNABLE_AUC_THRESHOLD
log(f"Learnability check: CV ROC-AUC={cv_bin['roc_auc_mean']:.4f} "
    f"(threshold={LEARNABLE_AUC_THRESHOLD}) → {'PASS' if is_learnable else 'BORDERLINE'}")

# ── 5. Save results JSON ──────────────────────────────────────────────────────
results = {
    "generated_at": datetime.now().isoformat(),
    "n_samples": int(len(df)),
    "label_distribution": df["verdict_ground_truth"].value_counts().to_dict(),
    "binary_model": {
        "insample_roc_auc": float(auc_insample),
        "insample_precision_block": float(precision_score(y_bin, y_pred_bin)),
        "insample_recall_block":    float(recall_score(y_bin, y_pred_bin)),
        "insample_f1_block":        float(f1_score(y_bin, y_pred_bin)),
        "cv_roc_auc_mean": cv_bin["roc_auc_mean"],
        "cv_roc_auc_std":  cv_bin["roc_auc_std"],
        "cv_f1_mean":      cv_bin["f1_mean"],
        "cv_f1_std":       cv_bin["f1_std"],
        "confusion_matrix": cm_bin,
        "feature_importances": fi_bin_sorted[:20],
        "model_path": str(bin_model_path),
    },
    "multiclass_model": {
        "cv_macro_f1_mean": float(cv_multi_f1.mean()),
        "cv_macro_f1_std":  float(cv_multi_f1.std()),
        "class_names": class_names,
        "confusion_matrix": cm_multi,
        "feature_importances": fi_multi_sorted[:20],
        "model_path": str(multi_model_path),
    },
    "learnability": {
        "is_learnable": is_learnable,
        "threshold_used": LEARNABLE_AUC_THRESHOLD,
    },
    "features_used": FEATURE_COLS,
}

results_path = EXPORTS / "xgb_results.json"
results_path.write_text(json.dumps(results, indent=2))
log(f"Results saved → {results_path}")

# ── 6. Markdown report ────────────────────────────────────────────────────────
def fmt_cm_bin(cm):
    tn, fp, fn, tp = cm[0][0], cm[0][1], cm[1][0], cm[1][1]
    return (
        f"| | Pred not-BLOCK | Pred BLOCK |\n"
        f"|---|---|---|\n"
        f"| True not-BLOCK | {tn:,} | {fp:,} |\n"
        f"| True BLOCK     | {fn:,} | {tp:,} |"
    )

def fmt_cm_multi(cm, names):
    header = "| | " + " | ".join(f"Pred {n}" for n in names) + " |"
    sep    = "|---|" + "|".join("---" for _ in names) + "|"
    rows   = "\n".join(
        f"| True {names[i]} | " + " | ".join(str(v) for v in row) + " |"
        for i, row in enumerate(cm)
    )
    return "\n".join([header, sep, rows])

fi_bin_md   = "\n".join(
    f"| {i+1} | `{f}` | {v:.4f} |" for i, (f, v) in enumerate(fi_bin_sorted[:15])
)
fi_multi_md = "\n".join(
    f"| {i+1} | `{f}` | {v:.4f} |" for i, (f, v) in enumerate(fi_multi_sorted[:15])
)

md = f"""# XGBoost Training Results

_Generated at: {results['generated_at']}_

## Dataset

| Label | Count | % |
|---|---|---|
""" + "\n".join(
    f"| {k} | {v:,} | {100*v/len(df):.1f}% |"
    for k, v in results["label_distribution"].items()
) + f"""

Total samples: **{len(df):,}** (account-level screening results only)

---

## 1. Binary Model — BLOCK vs not-BLOCK

> Positive class = BLOCK. `scale_pos_weight = {scale_pos:.1f}` to handle class imbalance.

### Cross-Validation (5-fold, stratified)

| Metric | Mean | Std |
|---|---|---|
| ROC-AUC | {cv_bin['roc_auc_mean']:.4f} | ±{cv_bin['roc_auc_std']:.4f} |
| F1 (BLOCK) | {cv_bin['f1_mean']:.4f} | ±{cv_bin['f1_std']:.4f} |

### In-Sample Metrics

| Metric | Value |
|---|---|
| ROC-AUC | {auc_insample:.4f} |
| Precision (BLOCK) | {results['binary_model']['insample_precision_block']:.4f} |
| Recall (BLOCK) | {results['binary_model']['insample_recall_block']:.4f} |
| F1 (BLOCK) | {results['binary_model']['insample_f1_block']:.4f} |

### Confusion Matrix (in-sample)

{fmt_cm_bin(cm_bin)}

### Top 15 Feature Importances

| Rank | Feature | Importance |
|---|---|---|
{fi_bin_md}

---

## 2. Multiclass Model — BLOCK / REVIEW / CLEAR

### Cross-Validation (5-fold, macro-F1)

| Metric | Mean | Std |
|---|---|---|
| Macro F1 | {cv_multi_f1.mean():.4f} | ±{cv_multi_f1.std():.4f} |

### Confusion Matrix (in-sample)

{fmt_cm_multi(cm_multi, class_names)}

### Top 15 Feature Importances

| Rank | Feature | Importance |
|---|---|---|
{fi_multi_md}

---

## 3. Learnability Verdict

CV ROC-AUC = **{cv_bin['roc_auc_mean']:.4f}** (threshold ≥ {LEARNABLE_AUC_THRESHOLD})

**{'✓ DATASET IS LEARNABLE' if is_learnable else '⚠ BORDERLINE — review feature engineering'}**

---

## 4. Model Files

| File | Description |
|---|---|
| `exports/model_binary.ubj` | Binary XGBoost (BLOCK vs not-BLOCK) |
| `exports/model_multiclass.ubj` | Multiclass XGBoost (BLOCK/REVIEW/CLEAR) |
| `exports/xgb_results.json` | Full metrics + importances |
"""

md_path = EXPORTS / "xgb_report.md"
md_path.write_text(md)
log(f"Markdown report saved → {md_path}")

log("=== 11_train_xgboost.py finished ===")
