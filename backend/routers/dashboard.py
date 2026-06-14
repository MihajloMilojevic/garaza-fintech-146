from fastapi import APIRouter, HTTPException

import data.loader as dl
from data.loader import clean

router = APIRouter()


@router.get("/dashboard/stats")
def dashboard_stats():
    if dl.accounts_enriched is None or dl.screening_merged is None:
        raise HTTPException(503, "Data not loaded")

    ae = dl.accounts_enriched
    sm = dl.screening_merged

    # Verdict distribution — from all account-level screenings
    acct_sm = sm[sm["screening_context"] == "account"]
    verdict_dist = acct_sm["dynamic_verdict"].value_counts().to_dict()
    verdict_distribution = {
        "BLOCK":  int(verdict_dist.get("BLOCK", 0)),
        "REVIEW": int(verdict_dist.get("REVIEW", 0)),
        "CLEAR":  int(verdict_dist.get("CLEAR", 0)),
    }

    # Risk band distribution — from risk_scores (one per account)
    risk_band_counts = {}
    for band in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
        risk_band_counts[band.lower()] = int((ae["risk_band"] == band).sum())

    # Verdicts differ % — across all screening events
    total_events = len(sm)
    differ_count = int(sm["verdicts_differ"].sum())
    verdicts_differ_pct = round(differ_count / total_events * 100, 2) if total_events else 0.0

    # Top 5 highest-risk accounts
    top5 = ae.nlargest(5, "overall_risk_score")[
        ["account_id", "full_name", "overall_risk_score", "risk_band", "latest_verdict", "latest_match_score"]
    ]
    top_risk_accounts = [
        {
            "account_id":        r["account_id"],
            "full_name":         r.get("full_name"),
            "overall_risk_score": r["overall_risk_score"],
            "risk_band":         r["risk_band"],
            "latest_verdict":    r.get("latest_verdict"),
            "match_score":       r.get("latest_match_score"),
        }
        for _, r in top5.iterrows()
    ]

    return clean({
        "verdict_distribution":    verdict_distribution,
        "risk_band_counts":        risk_band_counts,
        "verdicts_differ_count":   differ_count,
        "verdicts_differ_pct":     verdicts_differ_pct,
        "total_accounts":          int(len(ae)),
        "total_screening_events":  total_events,
        "top_risk_accounts":       top_risk_accounts,
    })
