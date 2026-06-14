from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from ai.model.predict import screen as run_screen
import data.loader as dl
from data.loader import clean

router = APIRouter()


def _account_row_summary(row) -> dict:
    return {
        "account_id":        row["account_id"],
        "full_name":         row.get("full_name"),
        "account_type":      row.get("account_type"),
        "kyc_status":        row.get("kyc_status"),
        "account_status":    row.get("account_status"),
        "overall_risk_score": row.get("overall_risk_score"),
        "risk_band":         row.get("risk_band"),
        "latest_verdict":    row.get("latest_verdict"),
        "latest_match_score": row.get("latest_match_score"),
        "created_at":        row.get("created_at"),
    }


@router.get("/accounts")
def list_accounts(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    risk_band: Optional[str] = None,
    verdict: Optional[str] = None,
    search: Optional[str] = None,
):
    if dl.accounts_enriched is None:
        raise HTTPException(503, "Data not loaded")

    df = dl.accounts_enriched

    if risk_band:
        df = df[df["risk_band"] == risk_band.upper()]
    if verdict:
        df = df[df["latest_verdict"] == verdict.upper()]
    if search:
        s = search.lower()
        mask = (
            df["account_id"].str.lower().str.contains(s, na=False)
            | df["full_name"].str.lower().str.contains(s, na=False)
        )
        df = df[mask]

    total = len(df)
    start = (page - 1) * limit
    page_df = df.iloc[start : start + limit]

    return clean({
        "total": total,
        "page": page,
        "limit": limit,
        "accounts": [_account_row_summary(r) for _, r in page_df.iterrows()],
    })


@router.get("/accounts/{account_id}")
def get_account(account_id: str):
    if dl.accounts_enriched is None or dl.screening_merged is None:
        raise HTTPException(503, "Data not loaded")

    rows = dl.accounts_enriched[dl.accounts_enriched["account_id"] == account_id]
    if rows.empty:
        raise HTTPException(404, f"Account {account_id} not found")
    row = rows.iloc[0]

    # Build feature dict for live screen() call
    features = {
        "account_type":               row.get("account_type", "individual"),
        "kyc_completeness":           float(row.get("kyc_completeness") or 0.5),
        "kyc_status":                 row.get("kyc_status", "complete"),
        "is_pep":                     int(row.get("is_pep") or 0),
        "has_complex_ownership":      int(row.get("has_complex_ownership") or 0),
        "shell_company_flag":         int(row.get("shell_company_flag") or 0),
        "activity_tier":              row.get("activity_tier", "low"),
        "account_status":             row.get("account_status", "active"),
        "match_score":                float(row.get("latest_match_score") or 0.0),
        "shares_address_with_sanctioned": 0,
        "pep_exposure_score":         0.0,
        "country_risk_score":         float(row.get("geographic_risk") or 0.0),
        "geographic_risk":            float(row.get("geographic_risk") or 0.0),
        "identity_kyc_risk":          float(row.get("identity_kyc_risk") or 0.0),
        "pep_sanctions_risk":         float(row.get("pep_sanctions_risk") or 0.0),
        "behavioural_risk":           float(row.get("behavioural_risk") or 0.0),
        "relationship_network_risk":  float(row.get("relationship_network_risk") or 0.0),
        "overall_risk_score":         float(row.get("overall_risk_score") or 0.0),
        "override_applied":           int(row.get("override_applied") or 0),
    }

    # Enrich features from the account-level screening row if available
    scr_rows = dl.screening_merged[
        (dl.screening_merged["account_id"] == account_id)
        & (dl.screening_merged["screening_context"] == "account")
    ]
    if not scr_rows.empty:
        scr = scr_rows.iloc[0]
        features["shares_address_with_sanctioned"] = int(scr.get("shares_address_with_sanctioned") or 0)
        features["pep_exposure_score"]  = float(scr.get("pep_exposure_score") or 0.0)
        features["country_risk_score"]  = float(scr.get("country_risk_score") or 0.0)
        features["match_score"]         = float(scr.get("match_score") or 0.0)

    model_result = run_screen(features)

    # Latest account-level screening
    latest_screening = None
    if not scr_rows.empty:
        s = scr_rows.iloc[0]
        latest_screening = {
            "screening_id":   s.get("screening_id"),
            "verdict":        s.get("dynamic_verdict"),
            "match_score":    s.get("match_score"),
            "context":        s.get("screening_context"),
            "screened_at":    row.get("computed_at"),
        }

    t_block  = model_result["t_block"]
    t_review = model_result["t_review"]
    ms       = model_result["match_score"]
    if ms >= t_block:
        zone_desc = f"match_score {ms} ≥ t_block {t_block} → BLOCK"
    elif ms >= t_review:
        zone_desc = f"match_score {ms} is between t_review {t_review} and t_block {t_block} → REVIEW"
    else:
        zone_desc = f"match_score {ms} < t_review {t_review} → CLEAR"

    return clean({
        "account": {
            "account_id":               row.get("account_id"),
            "full_name":                row.get("full_name"),
            "account_type":             row.get("account_type"),
            "kyc_completeness":         row.get("kyc_completeness"),
            "kyc_status":               row.get("kyc_status"),
            "is_pep":                   row.get("is_pep"),
            "has_complex_ownership":    row.get("has_complex_ownership"),
            "shell_company_flag":       row.get("shell_company_flag"),
            "activity_tier":            row.get("activity_tier"),
            "account_status":           row.get("account_status"),
            "country_residence":        row.get("country_residence"),
            "created_at":               row.get("created_at"),
        },
        "risk_score": {
            "overall_risk_score":       row.get("overall_risk_score"),
            "risk_band":                row.get("risk_band"),
            "geographic_risk":          row.get("geographic_risk"),
            "identity_kyc_risk":        row.get("identity_kyc_risk"),
            "pep_sanctions_risk":       row.get("pep_sanctions_risk"),
            "behavioural_risk":         row.get("behavioural_risk"),
            "relationship_network_risk": row.get("relationship_network_risk"),
            "scored_at":                row.get("computed_at"),
        },
        "latest_screening": latest_screening,
        "threshold_decision": {
            "t_block":      t_block,
            "t_review":     t_review,
            "match_score":  ms,
            "verdict":      model_result["verdict"],
            "zone":         zone_desc,
        },
        "audit": {
            "verdict":              model_result["verdict"],
            "block_probability":    model_result["block_probability"],
            "class_probabilities":  model_result["class_probabilities"],
            "audit_narrative":      model_result["audit_narrative"],
            "audit_factors":        model_result["audit_factors"],
            "feature_contributions": model_result["feature_contributions"],
            "risk_components":      model_result["risk_components"],
        },
    })


@router.get("/accounts/{account_id}/transactions")
def get_transactions(
    account_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    if dl.transactions_df is None:
        raise HTTPException(503, "Data not loaded")

    # Accounts appear as senders
    df = dl.transactions_df[dl.transactions_df["sender_account_id"] == account_id].copy()

    if from_date:
        df = df[df["timestamp"] >= from_date]
    if to_date:
        df = df[df["timestamp"] <= to_date]

    df = df.sort_values("timestamp", ascending=False)
    total = len(df)
    page_df = df.iloc[(page - 1) * limit : page * limit]

    txns = []
    for _, r in page_df.iterrows():
        txns.append({
            "transaction_id":       r.get("transaction_id"),
            "amount":               r.get("amount"),
            "currency":             r.get("currency"),
            "payment_rail":         r.get("payment_rail"),
            "recipient_type":       r.get("recipient_type"),
            "recipient_name":       r.get("recipient_name"),
            "recipient_country":    r.get("recipient_country"),
            "timestamp":            r.get("timestamp"),
            "velocity_30d_count":   r.get("velocity_30d_count"),
            "velocity_30d_amount":  r.get("velocity_30d_amount"),
            "is_first_time_recipient": r.get("is_first_time_recipient"),
        })

    return clean({
        "account_id": account_id,
        "total": total,
        "page": page,
        "limit": limit,
        "transactions": txns,
    })
