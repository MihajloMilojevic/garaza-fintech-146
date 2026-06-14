"""
predict.py — Inference module for the sanctions screening risk/threshold model.

Usage (from backend):

    from ai.model.predict import screen

    result = screen({
        "account_type": "individual",          # or "business"
        "kyc_completeness": 0.85,
        "kyc_status": "complete",              # complete | partial | pending | expired
        "is_pep": 0,
        "has_complex_ownership": 0,
        "shell_company_flag": 0,
        "activity_tier": "medium",             # low | medium | high
        "account_status": "active",            # active | suspended | closed
        "match_score": 72.5,                   # 0-100 from screening system
        "shares_address_with_sanctioned": 0,
        "pep_exposure_score": 0.0,
        "country_risk_score": 35.0,
        # Risk components (pre-computed by risk scoring engine, or pass 0 to
        # let this module estimate them from the above fields)
        "geographic_risk": 35.0,
        "identity_kyc_risk": 15.0,
        "pep_sanctions_risk": 55.0,
        "behavioural_risk": 20.0,
        "relationship_network_risk": 5.0,
        "overall_risk_score": 30.0,
        "override_applied": 0,
    })

    # result["verdict"]         → "REVIEW"
    # result["t_block"]         → 85.0  (match_score must reach this to auto-BLOCK)
    # result["t_review"]        → 60.0  (match_score must reach this to route to human)
    # result["audit_narrative"] → "Account received REVIEW verdict ..."

Decision zones
--------------
  BLOCK   match_score ≥ t_block            → automatic block
  REVIEW  t_review ≤ match_score < t_block → routed to human analyst
  CLEAR   match_score < t_review           → automatic pass

Both thresholds are per-account and adjust with overall_risk_score:
  t_block  = clamp(75 − (risk − 50) × 0.5,  40, 95)
  t_review = clamp(50 − (risk − 50) × 0.5,  20, 70)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np

# ── Model loading ─────────────────────────────────────────────────────────────

_MODEL_DIR = Path(__file__).resolve().parent
_meta: dict | None = None
_bin_model = None
_multi_model = None


def _load_models():
    global _meta, _bin_model, _multi_model
    if _bin_model is not None:
        return

    import xgboost as xgb

    meta_path = _MODEL_DIR / "model_metadata.json"
    _meta = json.loads(meta_path.read_text())

    _bin_model = xgb.XGBClassifier()
    _bin_model.load_model(str(_MODEL_DIR / "model_binary.ubj"))

    _multi_model = xgb.XGBClassifier()
    _multi_model.load_model(str(_MODEL_DIR / "model_multiclass.ubj"))


# ── Feature encoding ──────────────────────────────────────────────────────────

_KYC_STATUS_ENC   = {"complete": 0, "partial": 1, "pending": 2, "expired": 3}
_ACTIVITY_ENC     = {"low": 0, "medium": 1, "high": 2}
_ACCOUNT_STATUS_ENC = {"active": 0, "suspended": 1, "closed": 2}
_CLASS_NAMES      = ["BLOCK", "CLEAR", "REVIEW"]   # alphabetical — matches training

FEATURE_ORDER = [
    "account_type_enc",
    "kyc_completeness",
    "kyc_status_enc",
    "is_pep",
    "has_complex_ownership",
    "shell_company_flag",
    "activity_tier_enc",
    "account_status_enc",
    "match_score",
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
]


def _encode(raw: dict) -> np.ndarray:
    """Convert a raw input dict to the feature vector expected by the models."""
    encoded = {
        "account_type_enc":              1 if raw.get("account_type") == "business" else 0,
        "kyc_completeness":              float(raw.get("kyc_completeness", 0.5)),
        "kyc_status_enc":                _KYC_STATUS_ENC.get(raw.get("kyc_status", "complete"), 0),
        "is_pep":                        int(raw.get("is_pep", 0)),
        "has_complex_ownership":         int(raw.get("has_complex_ownership", 0)),
        "shell_company_flag":            int(raw.get("shell_company_flag", 0)),
        "activity_tier_enc":             _ACTIVITY_ENC.get(raw.get("activity_tier", "low"), 0),
        "account_status_enc":            _ACCOUNT_STATUS_ENC.get(raw.get("account_status", "active"), 0),
        "match_score":                   float(raw.get("match_score", 0.0)),
        "shares_address_with_sanctioned":int(raw.get("shares_address_with_sanctioned", 0)),
        "pep_exposure_score":            float(raw.get("pep_exposure_score", 0.0)),
        "country_risk_score":            float(raw.get("country_risk_score", 25.0)),
        "geographic_risk":               float(raw.get("geographic_risk", 25.0)),
        "identity_kyc_risk":             float(raw.get("identity_kyc_risk", 20.0)),
        "pep_sanctions_risk":            float(raw.get("pep_sanctions_risk", 5.0)),
        "behavioural_risk":              float(raw.get("behavioural_risk", 10.0)),
        "relationship_network_risk":     float(raw.get("relationship_network_risk", 5.0)),
        "overall_risk_score":            float(raw.get("overall_risk_score", 20.0)),
        "override_applied":              int(raw.get("override_applied", 0)),
    }
    return np.array([[encoded[f] for f in FEATURE_ORDER]], dtype=np.float32)


# ── Threshold logic ───────────────────────────────────────────────────────────

def _compute_thresholds(overall_risk_score: float) -> tuple[float, float]:
    """
    Returns (t_block, t_review) for the given account risk score.

    Decision zones:
      match_score >= t_block            → BLOCK  (automatic)
      t_review <= match_score < t_block → REVIEW (human analyst)
      match_score < t_review            → CLEAR  (automatic pass)
    """
    adj     = (overall_risk_score - 50.0) * 0.5
    t_block  = float(np.clip(75.0 - adj, 40.0, 95.0))
    t_review = float(np.clip(50.0 - adj, 20.0, 70.0))
    return t_block, t_review


def _apply_thresholds(match_score: float, t_block: float, t_review: float) -> str:
    if match_score >= t_block:
        return "BLOCK"
    if match_score >= t_review:
        return "REVIEW"
    return "CLEAR"


# ── Feature contributions (importance-weighted) ───────────────────────────────

def _feature_contributions(
    feature_vec: np.ndarray,
    importances: dict[str, float],
) -> list[dict]:
    """
    Approximate per-feature contribution as importance × |normalised value|.
    Not SHAP — a fast proxy suitable for audit narratives.
    For true SHAP: `pip install shap` and call shap.TreeExplainer(model).
    """
    vals = {f: float(feature_vec[0, i]) for i, f in enumerate(FEATURE_ORDER)}
    # Normalise to [0,1] per feature using rough expected max values
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
) -> tuple[str, list[str]]:
    """Build a human-readable audit narrative and a list of factor sentences."""

    zone_desc = {
        "BLOCK":  f"match score {match_score:.1f} ≥ block threshold {t_block:.1f} → automatic block",
        "REVIEW": f"match score {match_score:.1f} is between review threshold {t_review:.1f} and block threshold {t_block:.1f} → routed to human analyst",
        "CLEAR":  f"match score {match_score:.1f} < review threshold {t_review:.1f} → automatic pass",
    }

    adj_desc = "lowered" if overall_risk > 50 else "raised"
    risk_dir = "high" if overall_risk > 50 else "low"

    narrative = (
        f"Verdict: {verdict}. "
        f"The account's overall risk score of {overall_risk:.1f}/100 {adj_desc} the block threshold "
        f"from the static baseline of 75.0 to {t_block:.1f} and the review threshold to {t_review:.1f}, "
        f"reflecting a {risk_dir}-risk profile. "
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
        verdict              str   — "BLOCK" | "REVIEW" | "CLEAR"
        t_block              float — block threshold for this account
        t_review             float — review threshold for this account
        match_score          float — echo of input
        overall_risk_score   float — echo of input
        block_probability    float — P(BLOCK) from binary model
        class_probabilities  dict  — {BLOCK, CLEAR, REVIEW: float}
        risk_components      dict  — five component scores
        feature_contributions list — top-10 feature contributions
        audit_narrative      str   — human-readable explanation
        audit_factors        list  — individual factor sentences
    """
    _load_models()

    overall_risk = float(raw.get("overall_risk_score", 20.0))
    match_score  = float(raw.get("match_score", 0.0))

    # 1. Dynamic thresholds
    t_block, t_review = _compute_thresholds(overall_risk)

    # 2. Threshold-based verdict (primary decision path)
    verdict = _apply_thresholds(match_score, t_block, t_review)

    # 3. Model probabilities (for confidence / audit)
    x = _encode(raw)

    bin_prob  = float(_bin_model.predict_proba(x)[0, 1])   # P(BLOCK)

    multi_probs_arr = _multi_model.predict_proba(x)[0]
    class_probs = {cls: round(float(p), 4) for cls, p in zip(_CLASS_NAMES, multi_probs_arr)}

    # 4. Feature contributions
    fi = _meta["feature_importances_binary"]
    contributions = _feature_contributions(x, fi)

    # 5. Audit narrative
    narrative, factors = _build_narrative(
        raw, verdict, match_score, t_block, t_review, overall_risk, contributions
    )

    return {
        "verdict":             verdict,
        "t_block":             round(t_block, 4),
        "t_review":            round(t_review, 4),
        "match_score":         round(match_score, 4),
        "overall_risk_score":  round(overall_risk, 4),
        "block_probability":   round(bin_prob, 4),
        "class_probabilities": class_probs,
        "risk_components": {
            "geographic_risk":           float(raw.get("geographic_risk", 0)),
            "identity_kyc_risk":         float(raw.get("identity_kyc_risk", 0)),
            "pep_sanctions_risk":        float(raw.get("pep_sanctions_risk", 0)),
            "behavioural_risk":          float(raw.get("behavioural_risk", 0)),
            "relationship_network_risk": float(raw.get("relationship_network_risk", 0)),
        },
        "feature_contributions": contributions,
        "audit_narrative":     narrative,
        "audit_factors":       factors,
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
            "_label": "PEP account — medium risk",
            "account_type": "individual", "kyc_completeness": 0.7, "kyc_status": "partial",
            "is_pep": 1, "has_complex_ownership": 0, "shell_company_flag": 0,
            "activity_tier": "medium", "account_status": "active",
            "match_score": 55.0, "shares_address_with_sanctioned": 0,
            "pep_exposure_score": 80.0, "country_risk_score": 45.0,
            "geographic_risk": 45.0, "identity_kyc_risk": 30.0, "pep_sanctions_risk": 75.0,
            "behavioural_risk": 25.0, "relationship_network_risk": 30.0,
            "overall_risk_score": 52.0, "override_applied": 0,
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
        print(f"  t_review:       {result['t_review']:.1f}   (below = CLEAR)")
        print(f"  t_block:        {result['t_block']:.1f}   (above = BLOCK)")
        print(f"  Risk score:     {result['overall_risk_score']:.1f}/100")
        print(f"  P(BLOCK):       {result['block_probability']:.4f}")
        print(f"  Class probs:    {result['class_probabilities']}")
        print(f"\n  Narrative:")
        print(f"    {result['audit_narrative']}")
        print(f"\n  Top factors:")
        for f in result["audit_factors"]:
            print(f"    • {f}")
