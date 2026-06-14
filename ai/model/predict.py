"""
predict.py — Inference module for the sanctions screening threshold model (v2).

WHAT CHANGED IN v2
------------------
`compute_thresholds()` now runs two XGBoost **regressors** that predict the
(t_block, t_review) pair directly, rather than deriving them from a hard-coded
arithmetic formula. The models were trained on noisy threshold labels (σ_block=4.0,
σ_review=3.5 Gaussian noise added to the original formula outputs) so the regression
target is non-trivial: the model must learn the full feature→threshold mapping from
data, not just reproduce arithmetic.

The two v1 classifiers (model_binary.ubj, model_multiclass.ubj) are loaded for
backward-compatible `block_probability` and `class_probabilities` fields but are
DEPRECATED and will be removed in v3.

Usage (from backend, unchanged call signature)
----------------------------------------------
    from ai.model.predict import screen

    result = screen({
        "account_type": "individual",
        "kyc_completeness": 0.85,
        "kyc_status": "complete",
        "is_pep": 0,
        "has_complex_ownership": 0,
        "shell_company_flag": 0,
        "activity_tier": "medium",
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
        "override_applied": 0,
        # Optional transaction-context keys (improves threshold prediction):
        # "amount": 15000.0,
        # "payment_rail": "wire",
        # "is_first_time_recipient": 1,
        # "velocity_30d_count": 3,
        # "velocity_30d_amount": 45000.0,
        # "hour_of_day": 2,
        # "day_of_week": 6,
    })

    # result["verdict"]         → "REVIEW"
    # result["t_block"]         → 84.3  (alias of min_block)
    # result["t_review"]        → 59.1  (alias of min_review)
    # result["min_block"]       → 84.3  (predicted by XGBoost regressor)
    # result["min_review"]      → 59.1  (predicted by XGBoost regressor)
    # result["threshold_reasons"] → ["overall_risk_score raised threshold by …", …]

Decision zones
--------------
  BLOCK   match_score ≥ t_block            → automatic block
  REVIEW  t_review ≤ match_score < t_block → routed to human analyst
  CLEAR   match_score < t_review           → automatic pass

Post-prediction clamps (v2)
----------------------------
  t_block  = clip(predicted_t_block,  10.0, 95.0)
  t_review = clip(predicted_t_review,  5.0, 95.0)
  if t_review >= t_block: t_review = t_block - 1.0   (ordering safety)
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

# ── Model loading ─────────────────────────────────────────────────────────────

_MODEL_DIR   = Path(__file__).resolve().parent
_meta: dict | None = None

# v2 regressors
_block_model  = None
_review_model = None

# v1 classifiers (deprecated, kept for block_probability / class_probabilities)
_bin_model    = None
_multi_model  = None


def _load_models():
    global _meta, _block_model, _review_model, _bin_model, _multi_model
    if _block_model is not None:
        return

    import xgboost as xgb

    meta_path = _MODEL_DIR / "model_metadata.json"
    _meta = json.loads(meta_path.read_text())

    # v2 regressors
    _block_model  = xgb.XGBRegressor()
    _review_model = xgb.XGBRegressor()
    _block_model.load_model(str(_MODEL_DIR / "model_threshold_regressor_block.ubj"))
    _review_model.load_model(str(_MODEL_DIR / "model_threshold_regressor_review.ubj"))

    # v1 classifiers (deprecated)
    _bin_model   = xgb.XGBClassifier()
    _multi_model = xgb.XGBClassifier()
    _bin_model.load_model(str(_MODEL_DIR / "model_binary.ubj"))
    _multi_model.load_model(str(_MODEL_DIR / "model_multiclass.ubj"))


# ── Encoders ──────────────────────────────────────────────────────────────────

_KYC_STATUS_ENC     = {"complete": 0, "partial": 1, "pending": 2, "expired": 3}
_ACTIVITY_ENC       = {"low": 0, "medium": 1, "high": 2}
_ACCOUNT_STATUS_ENC = {"active": 0, "suspended": 1, "closed": 2}
_PAYMENT_RAIL_ENC   = {"ach": 0, "card": 1, "check": 2, "crypto": 3,
                       "internal": 4, "wire": 5}

# ── Feature order for v1 classifiers (unchanged) ─────────────────────────────

FEATURE_ORDER_CLF = [
    "account_type_enc", "kyc_completeness", "kyc_status_enc",
    "is_pep", "has_complex_ownership", "shell_company_flag",
    "activity_tier_enc", "account_status_enc", "match_score",
    "shares_address_with_sanctioned", "pep_exposure_score", "country_risk_score",
    "geographic_risk", "identity_kyc_risk", "pep_sanctions_risk",
    "behavioural_risk", "relationship_network_risk", "overall_risk_score",
    "override_applied",
]

# ── Feature order for v2 regressors ──────────────────────────────────────────

FEATURE_ORDER_REG = [
    # account-level
    "account_type_enc", "kyc_completeness", "kyc_status_enc",
    "is_pep", "has_complex_ownership", "shell_company_flag",
    "activity_tier_enc", "account_status_enc",
    "shares_address_with_sanctioned", "pep_exposure_score", "country_risk_score",
    "geographic_risk", "identity_kyc_risk", "pep_sanctions_risk",
    "behavioural_risk", "relationship_network_risk", "overall_risk_score",
    "override_applied",
    # transaction-level (0 / False when no transaction context)
    "has_transaction", "amount_log", "payment_rail_enc",
    "is_first_time_recipient", "velocity_30d_count", "velocity_30d_amount_log",
    "hour_of_day", "day_of_week",
]

_CLASS_NAMES = ["BLOCK", "CLEAR", "REVIEW"]   # alphabetical — matches v1 training


# ── Feature encoding ──────────────────────────────────────────────────────────

def _encode_common(raw: dict) -> dict:
    """Shared encoded fields used by both clf and reg feature vectors."""
    return {
        "account_type_enc":               1 if raw.get("account_type") == "business" else 0,
        "kyc_completeness":               float(raw.get("kyc_completeness", 0.5)),
        "kyc_status_enc":                 _KYC_STATUS_ENC.get(raw.get("kyc_status", "complete"), 0),
        "is_pep":                         int(raw.get("is_pep", 0)),
        "has_complex_ownership":          int(raw.get("has_complex_ownership", 0)),
        "shell_company_flag":             int(raw.get("shell_company_flag", 0)),
        "activity_tier_enc":              _ACTIVITY_ENC.get(raw.get("activity_tier", "low"), 0),
        "account_status_enc":             _ACCOUNT_STATUS_ENC.get(raw.get("account_status", "active"), 0),
        "shares_address_with_sanctioned": int(raw.get("shares_address_with_sanctioned", 0)),
        "pep_exposure_score":             float(raw.get("pep_exposure_score", 0.0)),
        "country_risk_score":             float(raw.get("country_risk_score", 25.0)),
        "geographic_risk":                float(raw.get("geographic_risk", 25.0)),
        "identity_kyc_risk":              float(raw.get("identity_kyc_risk", 20.0)),
        "pep_sanctions_risk":             float(raw.get("pep_sanctions_risk", 5.0)),
        "behavioural_risk":               float(raw.get("behavioural_risk", 10.0)),
        "relationship_network_risk":      float(raw.get("relationship_network_risk", 5.0)),
        "overall_risk_score":             float(raw.get("overall_risk_score", 20.0)),
        "override_applied":               int(raw.get("override_applied", 0)),
    }


def _encode_clf(raw: dict) -> np.ndarray:
    """Feature vector for v1 classifiers (19 features, includes match_score)."""
    enc = _encode_common(raw)
    enc["match_score"] = float(raw.get("match_score", 0.0))
    return np.array([[enc[f] for f in FEATURE_ORDER_CLF]], dtype=np.float32)


def _encode_reg(raw: dict) -> np.ndarray:
    """Feature vector for v2 regressors (26 features, includes tx context)."""
    enc = _encode_common(raw)
    amount = raw.get("amount")
    has_tx = amount is not None and not (isinstance(amount, float) and math.isnan(amount))
    enc["has_transaction"]        = 1 if has_tx else 0
    enc["amount_log"]             = float(np.log1p(amount if has_tx else 0.0))
    enc["payment_rail_enc"]       = _PAYMENT_RAIL_ENC.get(raw.get("payment_rail", ""), -1)
    enc["is_first_time_recipient"]= int(raw.get("is_first_time_recipient", 0))
    enc["velocity_30d_count"]     = float(raw.get("velocity_30d_count", 0))
    v30a = raw.get("velocity_30d_amount", 0.0) or 0.0
    enc["velocity_30d_amount_log"]= float(np.log1p(v30a))
    enc["hour_of_day"]            = int(raw.get("hour_of_day", 12))
    enc["day_of_week"]            = int(raw.get("day_of_week", 0))
    return np.array([[enc[f] for f in FEATURE_ORDER_REG]], dtype=np.float32)


# ── Threshold logic (v2) ──────────────────────────────────────────────────────

_T_BLOCK_CLAMP  = (10.0, 95.0)
_T_REVIEW_CLAMP = ( 5.0, 95.0)
_BASELINE_BLOCK  = 75.0   # what formula gives at risk=50
_BASELINE_REVIEW = 50.0


def compute_thresholds(context: dict) -> dict:
    """
    Predict (min_block, min_review) using the XGBoost threshold regressors.

    Parameters
    ----------
    context : dict
        Same keys as `screen()` raw input. Transaction-level keys (amount,
        payment_rail, is_first_time_recipient, velocity_30d_count,
        velocity_30d_amount, hour_of_day, day_of_week) are optional; when absent,
        the model treats this as an account-context screening.

    Returns
    -------
    dict with keys:
        min_block  float  — predicted block threshold (match_score must reach this)
        min_review float  — predicted review threshold
        reasons    list[str] — importance-weighted contribution explanations
    """
    _load_models()

    x = _encode_reg(context)
    raw_block  = float(_block_model.predict(x)[0])
    raw_review = float(_review_model.predict(x)[0])

    # Clamp to outer safety bounds
    t_block  = float(np.clip(raw_block,  *_T_BLOCK_CLAMP))
    t_review = float(np.clip(raw_review, *_T_REVIEW_CLAMP))

    # Ordering: t_review must be strictly below t_block
    if t_review >= t_block:
        t_review = t_block - 1.0

    # Build threshold reasons from feature importances
    reasons = _threshold_reasons(context, x, t_block, t_review)

    return {
        "min_block":  round(t_block,  4),
        "min_review": round(t_review, 4),
        "reasons":    reasons,
    }


def _threshold_reasons(
    raw: dict,
    x: np.ndarray,
    t_block: float,
    t_review: float,
) -> list[str]:
    """
    Build human-readable reasons for the predicted thresholds.
    Uses importance-weighted contribution as a proxy for SHAP.
    (Not true SHAP — a fast approximation suitable for audit narrative.)
    """
    fi_block  = _meta["threshold_regressor"]["feature_importances_block"]
    fi_review = _meta["threshold_regressor"]["feature_importances_review"]

    _max = {
        "account_type_enc": 1, "kyc_completeness": 1, "kyc_status_enc": 3,
        "is_pep": 1, "has_complex_ownership": 1, "shell_company_flag": 1,
        "activity_tier_enc": 2, "account_status_enc": 2,
        "shares_address_with_sanctioned": 1, "pep_exposure_score": 100,
        "country_risk_score": 100, "geographic_risk": 100,
        "identity_kyc_risk": 100, "pep_sanctions_risk": 100,
        "behavioural_risk": 100, "relationship_network_risk": 100,
        "overall_risk_score": 100, "override_applied": 1,
        "has_transaction": 1, "amount_log": 14,   # log1p(1.2M) ≈ 14
        "payment_rail_enc": 5, "is_first_time_recipient": 1,
        "velocity_30d_count": 50, "velocity_30d_amount_log": 14,
        "hour_of_day": 23, "day_of_week": 6,
    }

    vals = {f: float(x[0, i]) for i, f in enumerate(FEATURE_ORDER_REG)}

    def top_contribs(fi: dict, n: int = 3) -> list[tuple[str, float, float]]:
        items = []
        for feat, imp in fi.items():
            if feat not in vals:
                continue
            norm = vals[feat] / _max.get(feat, 100)
            items.append((feat, imp, round(imp * norm * 100, 1)))
        items.sort(key=lambda t: -t[2])
        return items[:n]

    block_dir  = "lowered" if t_block  < _BASELINE_BLOCK  else "raised"
    review_dir = "lowered" if t_review < _BASELINE_REVIEW else "raised"

    block_top  = top_contribs(fi_block)
    review_top = top_contribs(fi_review)

    def fmt(feat: str, val: float, pct: float) -> str:
        name = feat.replace("_enc", "").replace("_", " ")
        return f"{name}={val:.2f} ({pct:.1f}%)"

    block_parts  = ", ".join(fmt(f, vals[f], pct) for f, _, pct in block_top)
    review_parts = ", ".join(fmt(f, vals[f], pct) for f, _, pct in review_top)

    reasons = [
        f"Block threshold {block_dir} to {t_block:.1f} (baseline {_BASELINE_BLOCK:.0f}); "
        f"primary drivers: {block_parts}",
        f"Review threshold {review_dir} to {t_review:.1f} (baseline {_BASELINE_REVIEW:.0f}); "
        f"primary drivers: {review_parts}",
    ]

    # Flag-specific plain-language additions
    if raw.get("is_pep"):
        reasons.append("Account is flagged as a Politically Exposed Person (PEP).")
    if raw.get("override_applied"):
        reasons.append("A manual analyst override has been applied to this account's risk score.")
    if raw.get("shares_address_with_sanctioned"):
        reasons.append("Account shares a registered address with a known sanctioned entity.")
    if raw.get("is_first_time_recipient"):
        reasons.append("Transaction is to a first-time recipient — elevated novelty signal.")
    if raw.get("amount") and raw["amount"] > 50_000:
        reasons.append(f"Transaction amount ${raw['amount']:,.0f} exceeds $50k high-value threshold.")

    return reasons


def _apply_thresholds(match_score: float, t_block: float, t_review: float) -> str:
    if match_score >= t_block:
        return "BLOCK"
    if match_score >= t_review:
        return "REVIEW"
    return "CLEAR"


# ── Feature contributions (v1 classifier importances, kept for audit panel) ──

def _feature_contributions(
    feature_vec: np.ndarray,
    importances: dict[str, float],
    feature_order: list[str],
) -> list[dict]:
    """
    Approximate per-feature contribution as importance × |normalised value|.
    Not SHAP — a fast proxy suitable for audit narratives.
    """
    vals = {f: float(feature_vec[0, i]) for i, f in enumerate(feature_order)}
    _max = {
        "account_type_enc": 1, "kyc_completeness": 1, "kyc_status_enc": 3,
        "is_pep": 1, "has_complex_ownership": 1, "shell_company_flag": 1,
        "activity_tier_enc": 2, "account_status_enc": 2,
        "match_score": 100, "shares_address_with_sanctioned": 1,
        "pep_exposure_score": 100, "country_risk_score": 100,
        "geographic_risk": 100, "identity_kyc_risk": 100,
        "pep_sanctions_risk": 100, "behavioural_risk": 100,
        "relationship_network_risk": 100, "overall_risk_score": 100,
        "override_applied": 1,
    }
    contribs = []
    for feat, imp in importances.items():
        if feat not in vals:
            continue
        norm_val = vals[feat] / _max.get(feat, 100)
        contribs.append({
            "feature":          feat,
            "importance":       round(imp, 4),
            "value":            round(vals[feat], 2),
            "contribution_pct": round(imp * norm_val * 100, 2),
        })
    contribs.sort(key=lambda x: -x["contribution_pct"])
    return contribs[:10]


# ── Audit narrative ───────────────────────────────────────────────────────────

def _build_narrative(
    raw: dict,
    verdict: str,
    match_score: float,
    t_block: float,
    t_review: float,
    overall_risk: float,
    top_contribs: list[dict],
    threshold_reasons: list[str],
) -> tuple[str, list[str]]:
    zone_desc = {
        "BLOCK":  f"match score {match_score:.1f} >= block threshold {t_block:.1f} -- automatic block",
        "REVIEW": f"match score {match_score:.1f} is between review threshold {t_review:.1f} and block threshold {t_block:.1f} -- routed to human analyst",
        "CLEAR":  f"match score {match_score:.1f} < review threshold {t_review:.1f} -- automatic pass",
    }
    adj_desc = "lowered" if overall_risk > 50 else "raised"
    risk_dir  = "high" if overall_risk > 50 else "low"

    narrative = (
        f"Verdict: {verdict}. "
        f"The XGBoost threshold model predicted block threshold {t_block:.1f} and "
        f"review threshold {t_review:.1f} for this account (overall risk "
        f"{overall_risk:.1f}/100 - {risk_dir} risk, thresholds {adj_desc} relative "
        f"to the 75/50 neutral baseline). "
        f"The screening system produced a match score of {match_score:.1f}/100. "
        f"{zone_desc[verdict]}."
    )

    factors = []
    for c in top_contribs[:3]:
        feat = c["feature"].replace("_", " ")
        factors.append(
            f"{feat} = {c['value']:.1f} (importance {c['importance']:.3f}, "
            f"contribution {c['contribution_pct']:.1f}%)"
        )
    # Add threshold reasons as additional factors (first two: block + review summary)
    factors.extend(threshold_reasons[:2])

    if raw.get("is_pep"):
        factors.append("Account is flagged as a Politically Exposed Person (PEP).")
    if raw.get("override_applied"):
        factors.append("A manual analyst override has been applied to this account's risk score.")
    if raw.get("shares_address_with_sanctioned"):
        factors.append("Account shares a registered address with a known sanctioned entity.")

    return narrative, factors


# ── Public API ────────────────────────────────────────────────────────────────

def screen(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Run the full screening decision pipeline for one account/transaction event.

    Parameters
    ----------
    raw : dict
        Feature dict — see module docstring for expected keys.

    Returns
    -------
    dict with keys:
        verdict              str
        t_block              float  (alias of min_block)
        t_review             float  (alias of min_review)
        min_block            float  — predicted by XGBoost regressor
        min_review           float  — predicted by XGBoost regressor
        match_score          float
        overall_risk_score   float
        block_probability    float  — P(BLOCK) from deprecated v1 binary model
        class_probabilities  dict
        risk_components      dict
        feature_contributions list
        threshold_reasons    list[str]
        audit_narrative      str
        audit_factors        list[str]
    """
    _load_models()

    overall_risk = float(raw.get("overall_risk_score", 20.0))
    match_score  = float(raw.get("match_score", 0.0))

    # 1. Threshold prediction via v2 regressors
    thresh = compute_thresholds(raw)
    t_block  = thresh["min_block"]
    t_review = thresh["min_review"]
    threshold_reasons = thresh["reasons"]

    # 2. Threshold-based verdict
    verdict = _apply_thresholds(match_score, t_block, t_review)

    # 3. v1 classifier probabilities (deprecated — kept for audit panel)
    x_clf = _encode_clf(raw)
    bin_prob        = float(_bin_model.predict_proba(x_clf)[0, 1])
    multi_probs_arr = _multi_model.predict_proba(x_clf)[0]
    class_probs     = {cls: round(float(p), 4)
                       for cls, p in zip(_CLASS_NAMES, multi_probs_arr)}

    # 4. Feature contributions (using v1 binary importances for audit display)
    fi = _meta["feature_importances_binary"]
    contributions = _feature_contributions(x_clf, fi, FEATURE_ORDER_CLF)

    # 5. Audit narrative
    narrative, factors = _build_narrative(
        raw, verdict, match_score, t_block, t_review,
        overall_risk, contributions, threshold_reasons,
    )

    return {
        "verdict":              verdict,
        "t_block":              round(t_block, 4),   # alias
        "t_review":             round(t_review, 4),  # alias
        "min_block":            round(t_block, 4),
        "min_review":           round(t_review, 4),
        "match_score":          round(match_score, 4),
        "overall_risk_score":   round(overall_risk, 4),
        "block_probability":    round(bin_prob, 4),
        "class_probabilities":  class_probs,
        "risk_components": {
            "geographic_risk":           float(raw.get("geographic_risk", 0)),
            "identity_kyc_risk":         float(raw.get("identity_kyc_risk", 0)),
            "pep_sanctions_risk":        float(raw.get("pep_sanctions_risk", 0)),
            "behavioural_risk":          float(raw.get("behavioural_risk", 0)),
            "relationship_network_risk": float(raw.get("relationship_network_risk", 0)),
        },
        "feature_contributions":  contributions,
        "threshold_reasons":      threshold_reasons,
        "audit_narrative":        narrative,
        "audit_factors":          factors,
    }


# ── CLI quick-test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    examples = [
        {
            "_label": "High-risk sanctioned account",
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
            "_label": "Low-risk account with coincidental name match",
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
            "_label": "PEP account — medium risk, high-value wire",
            "account_type": "individual", "kyc_completeness": 0.7, "kyc_status": "partial",
            "is_pep": 1, "has_complex_ownership": 0, "shell_company_flag": 0,
            "activity_tier": "medium", "account_status": "active",
            "match_score": 55.0, "shares_address_with_sanctioned": 0,
            "pep_exposure_score": 80.0, "country_risk_score": 45.0,
            "geographic_risk": 45.0, "identity_kyc_risk": 30.0, "pep_sanctions_risk": 75.0,
            "behavioural_risk": 25.0, "relationship_network_risk": 30.0,
            "overall_risk_score": 52.0, "override_applied": 0,
            # Transaction context
            "amount": 85000.0, "payment_rail": "wire",
            "is_first_time_recipient": 1, "velocity_30d_count": 1,
            "velocity_30d_amount": 85000.0, "hour_of_day": 2, "day_of_week": 6,
        },
    ]

    for ex in examples:
        label = ex.pop("_label")
        result = screen(ex)
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")
        print(f"  Verdict:        {result['verdict']}")
        print(f"  Match score:    {result['match_score']:.1f}")
        print(f"  min_review:     {result['min_review']:.2f}  (below = CLEAR)")
        print(f"  min_block:      {result['min_block']:.2f}   (above = BLOCK)")
        print(f"  Risk score:     {result['overall_risk_score']:.1f}/100")
        print(f"  P(BLOCK):       {result['block_probability']:.4f}")
        print(f"\n  Threshold reasons:")
        for r in result["threshold_reasons"]:
            print(f"    • {r}")
        print(f"\n  Narrative:")
        print(f"    {result['audit_narrative']}")
        print(f"\n  Top factors:")
        for f in result["audit_factors"][:4]:
            print(f"    • {f}")
