"""
14_comparison_report.py
========================
Produce THRESHOLD_V2.md comparing:

  a) Static threshold baselines (50, 55, 60, 65, 70, 75, 80)
  b) Old deterministic formula: t_block = clamp(75-(risk-50)*0.5, 40, 95)
  c) New XGBoost threshold regressor (compute_thresholds from predict.py)

  All compared against verdict_ground_truth from screening_results.

Outputs: ai/THRESHOLD_V2.md
"""

import json
import os
import sys
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score, f1_score

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_DIR = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
EXPORTS_DIR = os.path.join(PROJECT_DIR, "exports")
AI_DIR      = "/home/mihajlo/Mihajlo/Projekti/garaza/ai"

sys.path.insert(0, "/home/mihajlo/Mihajlo/Projekti/garaza")

# ── Load data ─────────────────────────────────────────────────────────────────

def load_data():
    td  = pd.read_parquet(os.path.join(EXPORTS_DIR, "threshold_decisions.parquet"))
    sr  = pd.read_parquet(os.path.join(EXPORTS_DIR, "screening_results.parquet"))
    rs  = pd.read_parquet(os.path.join(EXPORTS_DIR, "risk_scores.parquet"))
    acc = pd.read_parquet(os.path.join(EXPORTS_DIR, "accounts.parquet"))
    tx  = pd.read_parquet(os.path.join(EXPORTS_DIR, "transactions.parquet"))

    # Join everything into one analysis frame
    df = td.merge(
        sr[["screening_id", "account_id", "transaction_id", "match_score",
            "verdict_ground_truth", "shares_address_with_sanctioned",
            "pep_exposure_score", "country_risk_score"]],
        on="screening_id", how="left", suffixes=("_td", "")
    )
    if "transaction_id_td" in df.columns:
        df["transaction_id"] = df["transaction_id"].fillna(df["transaction_id_td"])
        df.drop(columns=["transaction_id_td"], inplace=True)

    df = df.merge(
        rs[["account_id", "overall_risk_score", "geographic_risk", "identity_kyc_risk",
            "pep_sanctions_risk", "behavioural_risk", "relationship_network_risk",
            "override_applied"]],
        on="account_id", how="left"
    )
    df = df.merge(
        acc[["account_id", "account_type", "kyc_completeness", "kyc_status",
             "is_pep", "has_complex_ownership", "shell_company_flag",
             "activity_tier", "account_status"]],
        on="account_id", how="left"
    )
    df = df.merge(
        tx[["transaction_id", "amount", "payment_rail", "is_first_time_recipient",
            "velocity_30d_count", "velocity_30d_amount", "hour_of_day", "day_of_week"]],
        on="transaction_id", how="left"
    )
    return df


# ── Verdict helpers ────────────────────────────────────────────────────────────

def apply_threshold(match_score: float, t_block: float, t_review: float) -> str:
    if match_score >= t_block:
        return "BLOCK"
    if match_score >= t_review:
        return "REVIEW"
    return "CLEAR"

def static_verdict(match_score: float, threshold: float) -> str:
    if match_score >= threshold:
        return "BLOCK"
    if match_score >= 50.0:
        return "REVIEW"
    return "CLEAR"

def old_formula_thresholds(risk: float):
    adj = (risk - 50.0) * 0.5
    t_block  = float(np.clip(75.0 - adj, 40.0, 95.0))
    t_review = float(np.clip(50.0 - adj, 20.0, 70.0))
    return t_block, t_review


# ── Metrics helpers ────────────────────────────────────────────────────────────

def verdict_dist(verdicts) -> dict:
    d = {"BLOCK": 0, "REVIEW": 0, "CLEAR": 0}
    for v in verdicts:
        if v in d:
            d[v] += 1
    total = sum(d.values())
    pct   = {k: f"{v/total*100:.1f}%" if total else "0%" for k, v in d.items()}
    return {"counts": d, "pct": pct, "total": total}

def flagged_metrics(truth, predicted, pos_label="BLOCK"):
    """Precision / recall / F1 for a single class vs rest."""
    t = [1 if v == pos_label else 0 for v in truth]
    p = [1 if v == pos_label else 0 for v in predicted]
    tp = sum(a == 1 and b == 1 for a, b in zip(t, p))
    fp = sum(a == 0 and b == 1 for a, b in zip(t, p))
    fn = sum(a == 1 and b == 0 for a, b in zip(t, p))
    tn = sum(a == 0 and b == 0 for a, b in zip(t, p))
    prec   = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1     = 2 * prec * recall / (prec + recall) if (prec + recall) else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "precision": round(prec, 3), "recall": round(recall, 3), "f1": round(f1, 3)}

def flagged_any_metrics(truth, predicted):
    """BLOCK or REVIEW vs CLEAR."""
    t = [1 if v in ("BLOCK", "REVIEW") else 0 for v in truth]
    p = [1 if v in ("BLOCK", "REVIEW") else 0 for v in predicted]
    tp = sum(a == 1 and b == 1 for a, b in zip(t, p))
    fp = sum(a == 0 and b == 1 for a, b in zip(t, p))
    fn = sum(a == 1 and b == 0 for a, b in zip(t, p))
    prec   = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1     = 2 * prec * recall / (prec + recall) if (prec + recall) else 0.0
    return {"TP": tp, "FP": fp, "FN": fn,
            "precision": round(prec, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


# ── Regressor prediction over the full dataset ─────────────────────────────────

def predict_regressor(df: pd.DataFrame):
    """Run compute_thresholds row-by-row and return lists of (t_block, t_review, verdict)."""
    from ai.model.predict import compute_thresholds

    t_blocks, t_reviews, verdicts = [], [], []
    for _, row in df.iterrows():
        ctx = {
            "account_type":               row.get("account_type", "individual"),
            "kyc_completeness":           row.get("kyc_completeness", 0.5) or 0.5,
            "kyc_status":                 row.get("kyc_status", "complete"),
            "is_pep":                     int(row.get("is_pep", 0) or 0),
            "has_complex_ownership":      int(row.get("has_complex_ownership", 0) or 0),
            "shell_company_flag":         int(row.get("shell_company_flag", 0) or 0),
            "activity_tier":              row.get("activity_tier", "low"),
            "account_status":             row.get("account_status", "active"),
            "shares_address_with_sanctioned": int(row.get("shares_address_with_sanctioned", 0) or 0),
            "pep_exposure_score":         float(row.get("pep_exposure_score", 0) or 0),
            "country_risk_score":         float(row.get("country_risk_score", 25) or 25),
            "geographic_risk":            float(row.get("geographic_risk", 25) or 25),
            "identity_kyc_risk":          float(row.get("identity_kyc_risk", 20) or 20),
            "pep_sanctions_risk":         float(row.get("pep_sanctions_risk", 5) or 5),
            "behavioural_risk":           float(row.get("behavioural_risk", 10) or 10),
            "relationship_network_risk":  float(row.get("relationship_network_risk", 5) or 5),
            "overall_risk_score":         float(row.get("overall_risk_score", 20) or 20),
            "override_applied":           int(row.get("override_applied", 0) or 0),
        }
        # Add transaction context if available
        amt = row.get("amount")
        if amt is not None and not (isinstance(amt, float) and math.isnan(amt)):
            ctx["amount"]                  = float(amt)
            ctx["payment_rail"]            = row.get("payment_rail", "")
            ctx["is_first_time_recipient"] = int(row.get("is_first_time_recipient", 0) or 0)
            ctx["velocity_30d_count"]      = float(row.get("velocity_30d_count", 0) or 0)
            ctx["velocity_30d_amount"]     = float(row.get("velocity_30d_amount", 0) or 0)
            ctx["hour_of_day"]             = int(row.get("hour_of_day", 12) or 12)
            ctx["day_of_week"]             = int(row.get("day_of_week", 0) or 0)

        th = compute_thresholds(ctx)
        tb = th["min_block"]
        tr = th["min_review"]
        ms = float(row["match_score"])
        v  = apply_threshold(ms, tb, tr)
        t_blocks.append(tb)
        t_reviews.append(tr)
        verdicts.append(v)

    return t_blocks, t_reviews, verdicts


# ── Markdown helpers ───────────────────────────────────────────────────────────

def md_table(headers: list, rows: list) -> str:
    widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
              for i, h in enumerate(headers)]
    sep  = "| " + " | ".join("-" * w for w in widths) + " |"
    head = "| " + " | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)) + " |"
    body = "\n".join(
        "| " + " | ".join(str(r[i]).ljust(widths[i]) for i in range(len(headers))) + " |"
        for r in rows
    )
    return head + "\n" + sep + "\n" + body


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("Loading data …")
    df = load_data()
    print(f"  {len(df)} rows loaded")

    truth = df["verdict_ground_truth"].tolist()
    match_scores = df["match_score"].tolist()

    # ── Ground truth distribution ──────────────────────────────────────────────
    gt_dist = verdict_dist(truth)

    # ── a) Static threshold baselines ─────────────────────────────────────────
    static_thresholds = [50, 55, 60, 65, 70, 75, 80]
    static_results = {}
    for st in static_thresholds:
        preds = [static_verdict(ms, st) for ms in match_scores]
        static_results[st] = {
            "dist":       verdict_dist(preds),
            "block_m":    flagged_metrics(truth, preds, "BLOCK"),
            "review_m":   flagged_metrics(truth, preds, "REVIEW"),
            "flagged_m":  flagged_any_metrics(truth, preds),
            "preds":      preds,
        }

    # ── b) Old formula ────────────────────────────────────────────────────────
    print("Running old formula …")
    old_preds = []
    for _, row in df.iterrows():
        risk = float(row.get("overall_risk_score", 50) or 50)
        tb, tr = old_formula_thresholds(risk)
        ms = float(row["match_score"])
        old_preds.append(apply_threshold(ms, tb, tr))
    old_dist    = verdict_dist(old_preds)
    old_block_m = flagged_metrics(truth, old_preds, "BLOCK")
    old_flag_m  = flagged_any_metrics(truth, old_preds)

    # ── c) XGBoost regressor ──────────────────────────────────────────────────
    print("Running XGBoost regressor (this may take a minute) …")
    reg_t_blocks, reg_t_reviews, reg_preds = predict_regressor(df)
    reg_dist    = verdict_dist(reg_preds)
    reg_block_m = flagged_metrics(truth, reg_preds, "BLOCK")
    reg_flag_m  = flagged_any_metrics(truth, reg_preds)

    # Regressor accuracy vs noisy labels
    noisy_t_blocks  = df["dynamic_t_block"].values
    noisy_t_reviews = df["dynamic_t_review"].values
    reg_mae_block   = float(np.mean(np.abs(np.array(reg_t_blocks) - noisy_t_blocks)))
    reg_rmse_block  = float(np.sqrt(np.mean((np.array(reg_t_blocks) - noisy_t_blocks) ** 2)))
    reg_mae_review  = float(np.mean(np.abs(np.array(reg_t_reviews) - noisy_t_reviews)))
    reg_rmse_review = float(np.sqrt(np.mean((np.array(reg_t_reviews) - noisy_t_reviews) ** 2)))

    # ── Load model metadata for CV stats ──────────────────────────────────────
    meta_path = "/home/mihajlo/Mihajlo/Projekti/garaza/ai/model/model_metadata.json"
    with open(meta_path) as f:
        meta = json.load(f)
    cv = meta["threshold_regressor"]["cv_5fold"]
    fi_block  = meta["threshold_regressor"]["feature_importances_block"]
    fi_review = meta["threshold_regressor"]["feature_importances_review"]

    # ── 3 example screen() outputs ─────────────────────────────────────────────
    from ai.model.predict import screen
    examples = [
        {
            "_label": "High-risk sanctioned business (BLOCK expected)",
            "account_type": "business", "kyc_completeness": 0.3, "kyc_status": "expired",
            "is_pep": 0, "has_complex_ownership": 1, "shell_company_flag": 1,
            "activity_tier": "high", "account_status": "active",
            "match_score": 96.0, "shares_address_with_sanctioned": 1,
            "pep_exposure_score": 0.0, "country_risk_score": 85.0,
            "geographic_risk": 85.0, "identity_kyc_risk": 70.0, "pep_sanctions_risk": 97.0,
            "behavioural_risk": 60.0, "relationship_network_risk": 75.0,
            "overall_risk_score": 85.0, "override_applied": 0,
        },
        {
            "_label": "Low-risk individual with coincidental name match (CLEAR expected)",
            "account_type": "individual", "kyc_completeness": 0.95, "kyc_status": "complete",
            "is_pep": 0, "has_complex_ownership": 0, "shell_company_flag": 0,
            "activity_tier": "low", "account_status": "active",
            "match_score": 68.0, "shares_address_with_sanctioned": 0,
            "pep_exposure_score": 0.0, "country_risk_score": 12.0,
            "geographic_risk": 12.0, "identity_kyc_risk": 5.0, "pep_sanctions_risk": 8.0,
            "behavioural_risk": 8.0, "relationship_network_risk": 2.0,
            "overall_risk_score": 8.5, "override_applied": 0,
        },
        {
            "_label": "PEP account, medium risk, high-value late-night wire (REVIEW expected)",
            "account_type": "individual", "kyc_completeness": 0.7, "kyc_status": "partial",
            "is_pep": 1, "has_complex_ownership": 0, "shell_company_flag": 0,
            "activity_tier": "medium", "account_status": "active",
            "match_score": 55.0, "shares_address_with_sanctioned": 0,
            "pep_exposure_score": 80.0, "country_risk_score": 45.0,
            "geographic_risk": 45.0, "identity_kyc_risk": 30.0, "pep_sanctions_risk": 75.0,
            "behavioural_risk": 25.0, "relationship_network_risk": 30.0,
            "overall_risk_score": 52.0, "override_applied": 0,
            "amount": 85000.0, "payment_rail": "wire",
            "is_first_time_recipient": 1, "velocity_30d_count": 1,
            "velocity_30d_amount": 85000.0, "hour_of_day": 2, "day_of_week": 6,
        },
    ]
    ex_results = []
    for ex in examples:
        label = ex.pop("_label")
        r = screen(ex)
        ex_results.append((label, ex, r))

    # ── Build Markdown ─────────────────────────────────────────────────────────
    print("Writing THRESHOLD_V2.md …")
    lines = []
    A = lines.append

    A("# Threshold Model v2 — Design, Evaluation & Comparison Report")
    A("")
    A("> Generated by `project/scripts/14_comparison_report.py`  ")
    A(f"> Dataset: {len(df):,} screening events  ")
    A(f"> Ground truth source: `screening_results.verdict_ground_truth`")
    A("")

    # ── 1. Noise parameters ────────────────────────────────────────────────────
    A("## 1. Step 1 — Label Noise Parameters")
    A("")
    A("The original `dynamic_t_block` / `dynamic_t_review` values were generated by")
    A("a deterministic formula: **t_block = clamp(75 − (risk−50)×0.5, 40, 95)** and")
    A("**t_review = t_block − 25** (constant gap of 25 points). The v1 XGBoost classifiers")
    A("were trained to reproduce this formula's *output* (verdict class), so they were")
    A("circular — the model just re-derived arithmetic.")
    A("")
    A("To make the regression target non-trivial, independent Gaussian noise was added")
    A("in `scripts/12_add_threshold_noise.py`:")
    A("")
    A("| Parameter | Value | Rationale |")
    A("|-----------|-------|-----------|")
    A("| RNG seed | 42 | Fixed for reproducibility |")
    A("| σ(t_block) | **4.0 points** | ≈ 56% of the natural σ of t_block (~7.2), adding meaningful variance without swamping the risk-score trend |")
    A("| σ(t_review) | **3.5 points** | Slightly smaller so block and review targets carry independent information |")
    A("| Outer clamp | t_block ∈ [10, 95], t_review ∈ [5, 95] | Prevents nonsensical values; no tight inner clamps |")
    A("| Ordering fix | if t_review ≥ t_block → t_review = t_block − 1 | Safety only; triggered 0 times on this dataset |")
    A("")
    A("**Before vs after noise:**")
    A("")
    A("| Metric | t_block (before) | t_block (after) | t_review (before) | t_review (after) |")
    A("|--------|-----------------|-----------------|-------------------|------------------|")
    after_tb = pd.Series(df["dynamic_t_block"])
    after_tr = pd.Series(df["dynamic_t_review"])
    A(f"| Mean | 88.154 | {after_tb.mean():.3f} | 63.154 | {after_tr.mean():.3f} |")
    A(f"| Std  | 7.172  | {after_tb.std():.3f}  | 7.172  | {after_tr.std():.3f}  |")
    A(f"| Min  | 52.521 | {after_tb.min():.3f}  | 27.521 | {after_tr.min():.3f}  |")
    A(f"| Max  | 95.000 | {after_tb.max():.3f}  | 70.000 | {after_tr.max():.3f}  |")
    gap_after = after_tb - after_tr
    A(f"| Gap (t_block − t_review) std | 0.00002 (constant) | **{gap_after.std():.3f}** | — | — |")
    A("")

    # ── 2. Regressor model ─────────────────────────────────────────────────────
    A("## 2. Step 2 — XGBoost Threshold Regressor")
    A("")
    A("Two separate `XGBRegressor` models (one per target) trained in")
    A("`scripts/13_train_threshold_regressor.py`.")
    A("")
    A("**Why two separate models instead of XGBoost multi-output?**  ")
    A("Portability (XGBoost 1.x and 2.x), separate per-target feature importances")
    A("for cleaner audit narrative, and no API instability from a recently-added")
    A("experimental feature.")
    A("")
    A("**Feature set (26 features):**")
    A("")
    A("*Account-level (18):* overall_risk_score, geographic_risk, identity_kyc_risk,")
    A("pep_sanctions_risk, behavioural_risk, relationship_network_risk, kyc_completeness,")
    A("kyc_status_enc, account_type_enc, is_pep, has_complex_ownership, shell_company_flag,")
    A("activity_tier_enc, account_status_enc, shares_address_with_sanctioned,")
    A("pep_exposure_score, country_risk_score, override_applied")
    A("")
    A("*Transaction-level (8, zero-filled for account-context rows):* has_transaction,")
    A("amount_log, payment_rail_enc, is_first_time_recipient, velocity_30d_count,")
    A("velocity_30d_amount_log, hour_of_day, day_of_week")
    A("")
    A("*Excluded:* hops_to_sanctioned, name_match_type_enc (label-proxy / leakage risk),")
    A("match_score (compared to the threshold, not a driver of it), dynamic_verdict,")
    A("verdicts_differ (derived from targets).")
    A("")
    A("### 5-Fold CV Performance")
    A("")
    A("| Target | MAE | RMSE | R² |")
    A("|--------|-----|------|-----|")
    A(f"| t_block  | {cv['t_block']['mae']:.3f} | {cv['t_block']['rmse']:.3f} | {cv['t_block']['r2']:.4f} |")
    A(f"| t_review | {cv['t_review']['mae']:.3f} | {cv['t_review']['rmse']:.3f} | {cv['t_review']['r2']:.4f} |")
    A("")
    A("The ~0.80 R² indicates the models have captured the risk-score-driven threshold")
    A("trend. The residual ~20% variance is the intentional noise from Step 1 — the")
    A("regression target is designed to be non-trivially recoverable from the features.")
    A("")
    A("### Feature Importances")
    A("")
    A("**t_block model (top 10):**")
    A("")
    A("| Feature | Importance |")
    A("|---------|------------|")
    for feat, imp in list(fi_block.items())[:10]:
        A(f"| {feat} | {imp:.4f} |")
    A("")
    A("**t_review model (top 10):**")
    A("")
    A("| Feature | Importance |")
    A("|---------|------------|")
    for feat, imp in list(fi_review.items())[:10]:
        A(f"| {feat} | {imp:.4f} |")
    A("")

    # ── 3. compute_thresholds() ────────────────────────────────────────────────
    A("## 3. Step 3 — `compute_thresholds()` / `screen()` Changes")
    A("")
    A("### compute_thresholds(context) → dict")
    A("")
    A("```python")
    A("thresh = compute_thresholds(context)")
    A("# thresh[\"min_block\"]  — predicted block threshold")
    A("# thresh[\"min_review\"] — predicted review threshold")
    A("# thresh[\"reasons\"]    — list[str] importance-weighted explanations")
    A("```")
    A("")
    A("**Algorithm:**")
    A("1. Encode `context` dict into 26-feature float32 vector")
    A("2. Run `block_model.predict(x)` → raw_block")
    A("3. Run `review_model.predict(x)` → raw_review")
    A("4. Apply outer clamps: t_block = clip(raw_block, 10, 95); t_review = clip(raw_review, 5, 95)")
    A("5. Ordering safety: if t_review ≥ t_block → t_review = t_block − 1")
    A("6. Build `reasons` from importance-weighted contribution proxy (not SHAP)")
    A("")
    A("**Post-prediction clamps:**")
    A("")
    A("| Threshold | Min | Max | Notes |")
    A("|-----------|-----|-----|-------|")
    A("| t_block   | 10  | 95  | Outer safety only — no tight inner clamp |")
    A("| t_review  | 5   | 95  | Outer safety only — gap to t_block varies freely |")
    A("")
    A("The gap between t_block and t_review is now **variable** (std ≈ 5 points in the")
    A("training data, mean ≈ 25) rather than the rigid constant 25 of the v1 formula.")
    A("")
    A("### screen() changes")
    A("")
    A("- Now calls `compute_thresholds()` for threshold prediction (replaces the hardcoded formula)")
    A("- Returns two new fields: `min_block` / `min_review` (same values as `t_block` / `t_review`")
    A("  which are kept as aliases for backward compatibility)")
    A("- Returns `threshold_reasons: list[str]` — new field surfacing the threshold explanation")
    A("- `audit_factors` now includes the top-2 threshold reason strings")
    A("- v1 classifiers still loaded and used for `block_probability` / `class_probabilities`")
    A("  (marked DEPRECATED in model_metadata.json)")
    A("")

    # ── 4. Comparison tables ───────────────────────────────────────────────────
    A("## 4. Step 4 — Threshold Approach Comparison")
    A("")
    A("### d) Ground Truth Distribution")
    A("")
    A(f"Total screening events: **{gt_dist['total']:,}**")
    A("")
    A("| Verdict | Count | % |")
    A("|---------|-------|---|")
    for v in ["BLOCK", "REVIEW", "CLEAR"]:
        A(f"| {v} | {gt_dist['counts'][v]:,} | {gt_dist['pct'][v]} |")
    A("")

    A("### a) Static Threshold Baselines")
    A("")
    A("Format: BLOCK / REVIEW / CLEAR counts. Below-threshold becomes REVIEW (≥50) or CLEAR (<50).")
    A("")
    rows = []
    for st in static_thresholds:
        r  = static_results[st]
        d  = r["dist"]["counts"]
        bm = r["block_m"]
        fm = r["flagged_m"]
        rows.append([
            f"t={st}", d["BLOCK"], d["REVIEW"], d["CLEAR"],
            bm["precision"], bm["recall"], bm["f1"],
            bm["FP"], bm["FN"],
            fm["precision"], fm["recall"], fm["f1"],
        ])
    A(md_table(
        ["Threshold", "BLOCK", "REVIEW", "CLEAR",
         "BLOCK-prec", "BLOCK-rec", "BLOCK-F1", "BLOCK-FP", "BLOCK-FN",
         "FLAG-prec", "FLAG-rec", "FLAG-F1"],
        rows
    ))
    A("")

    A("### b) Old Account-Level Formula (v1)")
    A("")
    A("t_block = clamp(75 − (risk−50)×0.5, 40, 95)   t_review = t_block − 25")
    A("")
    od = old_dist["counts"]
    A(f"| BLOCK | REVIEW | CLEAR |")
    A(f"|-------|--------|-------|")
    A(f"| {od['BLOCK']:,} | {od['REVIEW']:,} | {od['CLEAR']:,} |")
    A("")
    A("| Metric | BLOCK | Flagged (BLOCK or REVIEW) |")
    A("|--------|-------|--------------------------|")
    A(f"| Precision | {old_block_m['precision']} | {old_flag_m['precision']} |")
    A(f"| Recall    | {old_block_m['recall']}    | {old_flag_m['recall']}    |")
    A(f"| F1        | {old_block_m['f1']}        | {old_flag_m['f1']}        |")
    A(f"| FP        | {old_block_m['FP']}        | {old_flag_m['FP']}        |")
    A(f"| FN        | {old_block_m['FN']}        | {old_flag_m['FN']}        |")
    A("")

    A("### c) XGBoost Threshold Regressor (v2)")
    A("")
    A("Thresholds predicted by `compute_thresholds()`. Verdict applied via `match_score` vs")
    A("predicted `(min_block, min_review)`.")
    A("")
    rd = reg_dist["counts"]
    A(f"| BLOCK | REVIEW | CLEAR |")
    A(f"|-------|--------|-------|")
    A(f"| {rd['BLOCK']:,} | {rd['REVIEW']:,} | {rd['CLEAR']:,} |")
    A("")
    A("| Metric | BLOCK | Flagged (BLOCK or REVIEW) |")
    A("|--------|-------|--------------------------|")
    A(f"| Precision | {reg_block_m['precision']} | {reg_flag_m['precision']} |")
    A(f"| Recall    | {reg_block_m['recall']}    | {reg_flag_m['recall']}    |")
    A(f"| F1        | {reg_block_m['f1']}        | {reg_flag_m['f1']}        |")
    A(f"| FP        | {reg_block_m['FP']}        | {reg_flag_m['FP']}        |")
    A(f"| FN        | {reg_block_m['FN']}        | {reg_flag_m['FN']}        |")
    A("")
    A("**Label-fit metrics** (predicted thresholds vs noisy training labels):")
    A("")
    A("| Target | MAE | RMSE |")
    A("|--------|-----|------|")
    A(f"| t_block  | {reg_mae_block:.3f} | {reg_rmse_block:.3f} |")
    A(f"| t_review | {reg_mae_review:.3f} | {reg_rmse_review:.3f} |")
    A("")
    A("> These are train-set (in-sample) label-fit metrics. CV MAE/RMSE above are")
    A("> the held-out estimates of generalisation error.")
    A("")

    # ── 5. Example outputs ─────────────────────────────────────────────────────
    A("## 5. Example `screen()` / `compute_thresholds()` Outputs")
    A("")
    for i, (label, ctx, r) in enumerate(ex_results, 1):
        A(f"### Case {i}: {label}")
        A("")
        A("```")
        A(f"min_review  : {r['min_review']:.2f}")
        A(f"min_block   : {r['min_block']:.2f}")
        A(f"match_score : {r['match_score']:.1f}")
        A(f"verdict     : {r['verdict']}")
        A("")
        A("threshold_reasons:")
        for reason in r["threshold_reasons"]:
            A(f"  • {reason}")
        A("```")
        A("")
        A(f"**Narrative:** {r['audit_narrative']}")
        A("")

    # ── 6. What this model is and isn't ───────────────────────────────────────
    A("## 6. What This Model Is and Isn't")
    A("")
    A("This v2 threshold model is a **learned approximation of a noisy version of")
    A("the original deterministic formula**, trained on synthetic data. It is designed")
    A("for use in the **Phase-0 / shadow-mode** described in the original proposal:")
    A("")
    A("**What it is:**")
    A("- A working XGBoost regression architecture that predicts `(t_block, t_review)`")
    A("  as a continuous pair rather than deriving them from a single formula")
    A("- A demonstration that the threshold prediction task is non-trivial when labels")
    A("  have realistic variance (R² ≈ 0.80, not 1.00)")
    A("- Ready for retraining on real analyst feedback without architectural change —")
    A("  just swap in real `(match_score, decided_threshold)` labels as they accumulate")
    A("- A richer feature set than the v1 formula (transaction amount, payment rail,")
    A("  velocity, first-time recipient, time-of-day) that would be genuinely predictive")
    A("  once trained on real human-annotated thresholds")
    A("")
    A("**What it isn't:**")
    A("- Trained on real analyst decisions — it learned a noisy version of the formula,")
    A("  not human judgment")
    A("- A SHAP-based explainer — `threshold_reasons` uses importance-weighted")
    A("  contribution as a fast proxy; for true SHAP use `shap.TreeExplainer`")
    A("- A replacement for compliance policy — thresholds should be audited against")
    A("  regulatory requirements before production use")
    A("")
    A("**Retraining path:** As real threshold decisions accumulate (analyst overrides,")
    A("regulatory feedback, case outcomes), replace `dynamic_t_block` / `dynamic_t_review`")
    A("labels with those real values and re-run `scripts/13_train_threshold_regressor.py`.")
    A("No architectural change required.")
    A("")

    out_path = os.path.join(AI_DIR, "THRESHOLD_V2.md")
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
