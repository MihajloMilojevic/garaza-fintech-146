import math
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from ai.model.predict import screen as run_screen
import data.loader as dl
from data.loader import clean

router = APIRouter()


@router.get("/screening")
def list_screening(
    verdict: Optional[str] = None,
    context: Optional[str] = None,
    min_match_score: Optional[float] = None,
    verdicts_differ: Optional[bool] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    if dl.screening_merged is None or dl.transactions_df is None:
        raise HTTPException(503, "Data not loaded")

    df = dl.screening_merged.copy()

    # Only transaction-context screenings (account-only screenings excluded)
    df = df[df["screening_context"] == "transaction"]

    if verdict:
        df = df[df["dynamic_verdict"] == verdict.upper()]
    if context:
        df = df[df["screening_context"] == context]
    if min_match_score is not None:
        df = df[df["match_score"] >= min_match_score]
    if verdicts_differ is not None:
        df = df[df["verdicts_differ"] == (1 if verdicts_differ else 0)]

    # Attach transaction timestamp where available
    tx_ts = dl.transactions_df[["transaction_id", "timestamp"]].rename(columns={"timestamp": "tx_timestamp"})
    df = df.merge(tx_ts, on="transaction_id", how="left")

    total = len(df)
    page_df = df.iloc[(page - 1) * limit : page * limit]

    results = []
    for _, r in page_df.iterrows():
        tx_ts = r.get("tx_timestamp")
        if tx_ts and not (isinstance(tx_ts, float) and math.isnan(tx_ts)):
            screened_at = tx_ts
        elif dl.accounts_enriched is not None:
            acct_rows = dl.accounts_enriched[dl.accounts_enriched["account_id"] == r["account_id"]]
            screened_at = acct_rows.iloc[0]["computed_at"] if not acct_rows.empty else None
        else:
            screened_at = None

        results.append({
            "screening_id":   r.get("screening_id"),
            "account_id":     r.get("account_id"),
            "verdict":        r.get("dynamic_verdict"),
            "match_score":    r.get("match_score"),
            "context":        r.get("screening_context"),
            "t_block":        r.get("dynamic_t_block"),
            "t_review":       r.get("dynamic_t_review"),
            "verdicts_differ": bool(r.get("verdicts_differ")),
            "screened_at":    screened_at,
        })

    return clean({
        "total": total,
        "page": page,
        "limit": limit,
        "results": results,
    })


@router.get("/screening/{screening_id}")
def get_screening(screening_id: str):
    if dl.screening_merged is None:
        raise HTTPException(503, "Data not loaded")

    rows = dl.screening_merged[dl.screening_merged["screening_id"] == screening_id]
    if rows.empty:
        raise HTTPException(404, f"Screening {screening_id} not found")

    scr = rows.iloc[0]
    account_id = scr["account_id"]

    # Account + risk scores
    acct_rows = dl.accounts_enriched[dl.accounts_enriched["account_id"] == account_id]
    if acct_rows.empty:
        raise HTTPException(404, f"Account {account_id} not found")
    acct = acct_rows.iloc[0]

    # Transaction details
    transaction_id = scr.get("transaction_id")
    transaction = None
    screened_at = acct.get("computed_at")
    if transaction_id and dl.transactions_df is not None:
        import math as _math
        if not (isinstance(transaction_id, float) and _math.isnan(transaction_id)):
            tx_rows = dl.transactions_df[dl.transactions_df["transaction_id"] == transaction_id]
            if not tx_rows.empty:
                tx = tx_rows.iloc[0]
                screened_at = tx.get("timestamp")
                transaction = {
                    "transaction_id":        tx.get("transaction_id"),
                    "amount":                float(tx.get("amount") or 0),
                    "currency":              tx.get("currency"),
                    "payment_rail":          tx.get("payment_rail"),
                    "recipient_name":        tx.get("recipient_name"),
                    "recipient_type":        tx.get("recipient_type"),
                    "recipient_country":     tx.get("recipient_country"),
                    "recipient_account_id":  tx.get("recipient_account_id"),
                    "recipient_wallet_id":   tx.get("recipient_wallet_id"),
                    "is_first_time_recipient": int(tx.get("is_first_time_recipient") or 0),
                    "velocity_30d_count":    int(tx.get("velocity_30d_count") or 0),
                    "velocity_30d_amount":   float(tx.get("velocity_30d_amount") or 0),
                    "sender_account_age_days": int(tx.get("sender_account_age_days") or 0),
                    "timestamp":             tx.get("timestamp"),
                }

    # Build feature dict and call screen()
    features = {
        "account_type":               acct.get("account_type", "individual"),
        "kyc_completeness":           float(acct.get("kyc_completeness") or 0.5),
        "kyc_status":                 acct.get("kyc_status", "complete"),
        "is_pep":                     int(acct.get("is_pep") or 0),
        "has_complex_ownership":      int(acct.get("has_complex_ownership") or 0),
        "shell_company_flag":         int(acct.get("shell_company_flag") or 0),
        "activity_tier":              acct.get("activity_tier", "low"),
        "account_status":             acct.get("account_status", "active"),
        "match_score":                float(scr.get("match_score") or 0.0),
        "shares_address_with_sanctioned": int(scr.get("shares_address_with_sanctioned") or 0),
        "pep_exposure_score":         float(scr.get("pep_exposure_score") or 0.0),
        "country_risk_score":         float(scr.get("country_risk_score") or 0.0),
        "geographic_risk":            float(acct.get("geographic_risk") or 0.0),
        "identity_kyc_risk":          float(acct.get("identity_kyc_risk") or 0.0),
        "pep_sanctions_risk":         float(acct.get("pep_sanctions_risk") or 0.0),
        "behavioural_risk":           float(acct.get("behavioural_risk") or 0.0),
        "relationship_network_risk":  float(acct.get("relationship_network_risk") or 0.0),
        "overall_risk_score":         float(acct.get("overall_risk_score") or 0.0),
        "override_applied":           int(acct.get("override_applied") or 0),
    }

    model_result = run_screen(features)
    t_block  = model_result["t_block"]
    t_review = model_result["t_review"]
    risk     = features["overall_risk_score"]
    adj      = (risk - 50.0) * 0.5
    t_block_raw  = 75.0 - adj
    t_review_raw = 50.0 - adj

    sender = {
        "account_id":        account_id,
        "full_name":         acct.get("full_name"),
        "country_residence": acct.get("country_residence"),
        "account_type":      acct.get("account_type"),
        "kyc_status":        acct.get("kyc_status"),
        "is_pep":            int(acct.get("is_pep") or 0),
        "risk_band":         acct.get("risk_band"),
        "overall_risk_score": float(acct.get("overall_risk_score") or 0),
    }

    return clean({
        "screening_id":  screening_id,
        "account_id":    account_id,
        "verdict":       model_result["verdict"],
        "match_score":   model_result["match_score"],
        "context":       scr.get("screening_context"),
        "screened_at":   screened_at,
        "transaction":   transaction,
        "sender":        sender,
        "threshold_decision": {
            "t_block":   t_block,
            "t_review":  t_review,
            "match_score": model_result["match_score"],
            "verdict":   model_result["verdict"],
            "formula": {
                "overall_risk_score": risk,
                "adjustment":        f"({risk} - 50.0) * 0.5 = {adj:.2f}",
                "t_block_raw":       f"75.0 - {adj:.2f} = {t_block_raw:.4f} -> clamped to {t_block}",
                "t_review_raw":      f"50.0 - {adj:.2f} = {t_review_raw:.4f} -> clamped to {t_review}",
            },
        },
        "audit_narrative":       model_result["audit_narrative"],
        "audit_factors":         model_result["audit_factors"],
        "risk_components":       model_result["risk_components"],
        "class_probabilities":   model_result["class_probabilities"],
        "block_probability":     model_result["block_probability"],
        "feature_contributions": model_result["feature_contributions"],
    })
