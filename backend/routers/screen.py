from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from ai.model.predict import screen as run_screen
import data.loader as dl
from data.loader import clean

router = APIRouter()


class ScreenRequest(BaseModel):
    account_type: str = "individual"
    kyc_completeness: float = Field(0.8, ge=0.0, le=1.0)
    kyc_status: str = "complete"
    is_pep: int = Field(0, ge=0, le=1)
    has_complex_ownership: int = Field(0, ge=0, le=1)
    shell_company_flag: int = Field(0, ge=0, le=1)
    activity_tier: str = "low"
    account_status: str = "active"
    match_score: float = Field(..., ge=0.0, le=100.0)
    shares_address_with_sanctioned: int = Field(0, ge=0, le=1)
    pep_exposure_score: float = 0.0
    country_risk_score: float = 0.0
    geographic_risk: float = 0.0
    identity_kyc_risk: float = 0.0
    pep_sanctions_risk: float = 0.0
    behavioural_risk: float = 0.0
    relationship_network_risk: float = 0.0
    overall_risk_score: float = Field(20.0, ge=0.0, le=100.0)
    override_applied: int = Field(0, ge=0, le=1)


@router.post("/screen")
def screen_endpoint(body: ScreenRequest):
    result = run_screen(body.model_dump())
    return clean(result)


@router.get("/thresholds/explain/{account_id}")
def explain_thresholds(account_id: str):
    if dl.accounts_enriched is None:
        raise HTTPException(503, "Data not loaded")

    row = dl.accounts_enriched[dl.accounts_enriched["account_id"] == account_id]
    if row.empty:
        raise HTTPException(404, f"Account {account_id} not found")

    risk = float(row.iloc[0]["overall_risk_score"])
    adj = (risk - 50.0) * 0.5
    t_block_raw  = 75.0 - adj
    t_review_raw = 50.0 - adj
    t_block  = float(max(40.0, min(95.0, t_block_raw)))
    t_review = float(max(20.0, min(70.0, t_review_raw)))

    # Interpretation sentence
    direction = "above-average" if risk > 50 else "below-average"
    effect = "lowered, making it easier to trigger BLOCK or REVIEW" if risk > 50 else "raised, making it harder to trigger BLOCK or REVIEW"
    contrast_risk = 20.0 if risk > 50 else 80.0
    contrast_adj  = (contrast_risk - 50.0) * 0.5
    contrast_block  = round(float(max(40.0, min(95.0, 75.0 - contrast_adj))), 1)
    contrast_review = round(float(max(20.0, min(70.0, 50.0 - contrast_adj))), 1)
    interpretation = (
        f"This account has {direction} risk ({risk} {'>' if risk > 50 else '<'} 50). "
        f"Thresholds are {effect}. "
        f"A {'lower' if risk > 50 else 'higher'}-risk account with score {contrast_risk:.0f} "
        f"would have t_block={contrast_block} and t_review={contrast_review}."
    )

    return clean({
        "account_id": account_id,
        "overall_risk_score": risk,
        "t_block": round(t_block, 4),
        "t_review": round(t_review, 4),
        "formula": {
            "baseline_t_block": 75.0,
            "baseline_t_review": 50.0,
            "adjustment_factor": 0.5,
            "risk_deviation": f"{risk} - 50.0 = {risk - 50.0:.1f}",
            "adjustment": f"{risk - 50.0:.1f} × 0.5 = {adj:.2f}",
            "t_block_unclamped": f"75.0 - {adj:.2f} = {t_block_raw:.4f}",
            "t_block_clamp_range": "[40.0, 95.0]",
            "t_block_final": round(t_block, 4),
            "t_review_unclamped": f"50.0 - {adj:.2f} = {t_review_raw:.4f}",
            "t_review_clamp_range": "[20.0, 70.0]",
            "t_review_final": round(t_review, 4),
            "interpretation": interpretation,
        },
        "decision_zones": {
            "BLOCK":  f"match_score ≥ {round(t_block, 4)}",
            "REVIEW": f"{round(t_review, 4)} ≤ match_score < {round(t_block, 4)}",
            "CLEAR":  f"match_score < {round(t_review, 4)}",
        },
    })
