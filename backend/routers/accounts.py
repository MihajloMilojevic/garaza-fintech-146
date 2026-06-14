import math
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from ai.model.predict import screen as run_screen
import data.loader as dl
from data.loader import clean

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _account_row_summary(row) -> dict:
    return {
        "account_id":         row["account_id"],
        "full_name":          row.get("full_name"),
        "account_type":       row.get("account_type"),
        "kyc_status":         row.get("kyc_status"),
        "account_status":     row.get("account_status"),
        "overall_risk_score": row.get("overall_risk_score"),
        "risk_band":          row.get("risk_band"),
        "latest_verdict":     row.get("latest_verdict"),
        "latest_match_score": row.get("latest_match_score"),
        "created_at":         row.get("created_at"),
    }


def _build_features(acct_row, scr_row=None) -> dict:
    """Assemble the feature dict required by screen() from an accounts_enriched row."""
    features = {
        "account_type":               acct_row.get("account_type", "individual"),
        "kyc_completeness":           float(acct_row.get("kyc_completeness") or 0.5),
        "kyc_status":                 acct_row.get("kyc_status", "complete"),
        "is_pep":                     int(acct_row.get("is_pep") or 0),
        "has_complex_ownership":      int(acct_row.get("has_complex_ownership") or 0),
        "shell_company_flag":         int(acct_row.get("shell_company_flag") or 0),
        "activity_tier":              acct_row.get("activity_tier", "low"),
        "account_status":             acct_row.get("account_status", "active"),
        "match_score":                float(acct_row.get("latest_match_score") or 0.0),
        "shares_address_with_sanctioned": 0,
        "pep_exposure_score":         0.0,
        "country_risk_score":         float(acct_row.get("geographic_risk") or 0.0),
        "geographic_risk":            float(acct_row.get("geographic_risk") or 0.0),
        "identity_kyc_risk":          float(acct_row.get("identity_kyc_risk") or 0.0),
        "pep_sanctions_risk":         float(acct_row.get("pep_sanctions_risk") or 0.0),
        "behavioural_risk":           float(acct_row.get("behavioural_risk") or 0.0),
        "relationship_network_risk":  float(acct_row.get("relationship_network_risk") or 0.0),
        "overall_risk_score":         float(acct_row.get("overall_risk_score") or 0.0),
        "override_applied":           int(acct_row.get("override_applied") or 0),
    }
    if scr_row is not None:
        features["shares_address_with_sanctioned"] = int(scr_row.get("shares_address_with_sanctioned") or 0)
        features["pep_exposure_score"]  = float(scr_row.get("pep_exposure_score") or 0.0)
        features["country_risk_score"]  = float(scr_row.get("country_risk_score") or 0.0)
        features["match_score"]         = float(scr_row.get("match_score") or 0.0)
    return features


def _threshold_formula(risk: float) -> dict:
    adj          = (risk - 50.0) * 0.5
    t_block_raw  = 75.0 - adj
    t_review_raw = 50.0 - adj
    t_block      = float(max(40.0, min(95.0, t_block_raw)))
    t_review     = float(max(20.0, min(70.0, t_review_raw)))

    direction    = "above-average" if risk > 50 else "below-average"
    effect       = "lowered, making it easier to trigger BLOCK or REVIEW" if risk > 50 else "raised, making it harder to trigger BLOCK or REVIEW"
    contrast_risk = 20.0 if risk > 50 else 80.0
    ca = (contrast_risk - 50.0) * 0.5
    cb = round(float(max(40.0, min(95.0, 75.0 - ca))), 1)
    cr = round(float(max(20.0, min(70.0, 50.0 - ca))), 1)
    interpretation = (
        f"This account has {direction} risk ({round(risk, 2)} {'>' if risk > 50 else '<'} 50). "
        f"Dynamic thresholds are {effect}. "
        f"A {'lower' if risk > 50 else 'higher'}-risk account with score {contrast_risk:.0f} "
        f"would have t_block={cb} and t_review={cr}."
    )

    return {
        "dynamic_t_block":      round(t_block, 4),
        "dynamic_t_review":     round(t_review, 4),
        "static_threshold":     65.0,
        "baseline_t_block":     75.0,
        "baseline_t_review":    50.0,
        "adjustment_factor":    0.5,
        "risk_deviation":       f"{round(risk, 4)} - 50.0 = {round(risk - 50.0, 4)}",
        "adjustment":           f"{round(risk - 50.0, 4)} × 0.5 = {round(adj, 4)}",
        "t_block_unclamped":    f"75.0 - ({round(adj, 4)}) = {round(t_block_raw, 4)}",
        "t_block_clamp_range":  "[40.0, 95.0]",
        "t_block_final":        round(t_block, 4),
        "t_review_unclamped":   f"50.0 - ({round(adj, 4)}) = {round(t_review_raw, 4)}",
        "t_review_clamp_range": "[20.0, 70.0]",
        "t_review_final":       round(t_review, 4),
        "static_vs_dynamic": (
            f"Static threshold is fixed at 65.0 for all accounts. "
            f"Dynamic threshold for this account: t_block={round(t_block, 2)}, t_review={round(t_review, 2)}. "
            f"{'Dynamic is stricter (lower t_block) than static.' if t_block < 65.0 else 'Dynamic is more lenient (higher t_block) than static, reducing false positives for this low-risk account.'}"
        ),
        "interpretation": interpretation,
        "decision_zones": {
            "BLOCK":  f"match_score ≥ {round(t_block, 4)}",
            "REVIEW": f"{round(t_review, 4)} ≤ match_score < {round(t_block, 4)}",
            "CLEAR":  f"match_score < {round(t_review, 4)}",
        },
    }


def _is_nan(v) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# GET /accounts
# ---------------------------------------------------------------------------

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
    page_df = df.iloc[(page - 1) * limit : page * limit]

    return clean({
        "total": total,
        "page": page,
        "limit": limit,
        "accounts": [_account_row_summary(r) for _, r in page_df.iterrows()],
    })


# ---------------------------------------------------------------------------
# GET /accounts/{account_id}
# ---------------------------------------------------------------------------

@router.get("/accounts/{account_id}")
def get_account(account_id: str):
    if dl.accounts_enriched is None or dl.screening_merged is None:
        raise HTTPException(503, "Data not loaded")

    rows = dl.accounts_enriched[dl.accounts_enriched["account_id"] == account_id]
    if rows.empty:
        raise HTTPException(404, f"Account {account_id} not found")
    row = rows.iloc[0]

    scr_rows = dl.screening_merged[
        (dl.screening_merged["account_id"] == account_id)
        & (dl.screening_merged["screening_context"] == "account")
    ]
    scr_row = scr_rows.iloc[0] if not scr_rows.empty else None

    features = _build_features(row, scr_row)
    model_result = run_screen(features)

    t_block  = model_result["t_block"]
    t_review = model_result["t_review"]
    ms       = model_result["match_score"]

    if ms >= t_block:
        zone_desc = f"match_score {ms} ≥ t_block {t_block} → BLOCK"
    elif ms >= t_review:
        zone_desc = f"match_score {ms} is between t_review {t_review} and t_block {t_block} → REVIEW"
    else:
        zone_desc = f"match_score {ms} < t_review {t_review} → CLEAR"

    latest_screening = None
    if scr_row is not None:
        latest_screening = {
            "screening_id": scr_row.get("screening_id"),
            "verdict":      scr_row.get("dynamic_verdict"),
            "match_score":  scr_row.get("match_score"),
            "context":      scr_row.get("screening_context"),
            "screened_at":  row.get("computed_at"),
        }

    return clean({
        "account": {
            "account_id":            row.get("account_id"),
            "full_name":             row.get("full_name"),
            "account_type":          row.get("account_type"),
            "kyc_completeness":      row.get("kyc_completeness"),
            "kyc_status":            row.get("kyc_status"),
            "is_pep":                row.get("is_pep"),
            "has_complex_ownership": row.get("has_complex_ownership"),
            "shell_company_flag":    row.get("shell_company_flag"),
            "activity_tier":         row.get("activity_tier"),
            "account_status":        row.get("account_status"),
            "country_residence":     row.get("country_residence"),
            "created_at":            row.get("created_at"),
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
            "t_block":     t_block,
            "t_review":    t_review,
            "match_score": ms,
            "verdict":     model_result["verdict"],
            "zone":        zone_desc,
        },
        "audit": {
            "verdict":               model_result["verdict"],
            "block_probability":     model_result["block_probability"],
            "class_probabilities":   model_result["class_probabilities"],
            "audit_narrative":       model_result["audit_narrative"],
            "audit_factors":         model_result["audit_factors"],
            "feature_contributions": model_result["feature_contributions"],
            "risk_components":       model_result["risk_components"],
        },
    })


# ---------------------------------------------------------------------------
# GET /accounts/{account_id}/transactions
# ---------------------------------------------------------------------------

@router.get("/accounts/{account_id}/transactions")
def get_transactions(
    account_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    if dl.transactions_df is None or dl.accounts_enriched is None:
        raise HTTPException(503, "Data not loaded")

    # ---- Account & risk ----
    acct_rows = dl.accounts_enriched[dl.accounts_enriched["account_id"] == account_id]
    if acct_rows.empty:
        raise HTTPException(404, f"Account {account_id} not found")
    acct = acct_rows.iloc[0]

    scr_rows = dl.screening_merged[
        (dl.screening_merged["account_id"] == account_id)
        & (dl.screening_merged["screening_context"] == "account")
    ] if dl.screening_merged is not None else None
    scr_row = scr_rows.iloc[0] if (scr_rows is not None and not scr_rows.empty) else None

    # ---- Model output ----
    features     = _build_features(acct, scr_row)
    model_result = run_screen(features)
    risk         = float(acct.get("overall_risk_score") or 0.0)
    threshold_fm = _threshold_formula(risk)

    # ---- All transactions for this account ----
    all_tx = dl.transactions_df[dl.transactions_df["sender_account_id"] == account_id].copy()

    if from_date:
        all_tx = all_tx[all_tx["timestamp"] >= from_date]
    if to_date:
        all_tx = all_tx[all_tx["timestamp"] <= to_date]

    all_tx = all_tx.sort_values("timestamp", ascending=False)
    total = len(all_tx)

    # ---- Summary statistics ----
    blocked_ids = set()
    review_ids  = set()
    clear_ids   = set()
    if dl.screening_by_tx:
        for tid in all_tx["transaction_id"]:
            s = dl.screening_by_tx.get(tid)
            if s:
                v = s.get("dynamic_verdict")
                if v == "BLOCK":   blocked_ids.add(tid)
                elif v == "REVIEW": review_ids.add(tid)
                elif v == "CLEAR":  clear_ids.add(tid)

    rail_counts = all_tx["payment_rail"].value_counts().to_dict()
    ccy_counts  = all_tx["currency"].value_counts().to_dict()
    amounts     = all_tx["amount"].dropna()

    summary = {
        "total_transactions":    total,
        "total_sent_amount":     round(float(amounts.sum()), 2) if len(amounts) else 0.0,
        "avg_transaction_amount": round(float(amounts.mean()), 2) if len(amounts) else 0.0,
        "max_transaction_amount": round(float(amounts.max()), 2) if len(amounts) else 0.0,
        "unique_recipients":     int(
            all_tx["recipient_account_id"].nunique()
            + all_tx["recipient_wallet_id"].nunique()
            + all_tx[all_tx["recipient_type"] == "external_individual"]["recipient_name"].nunique()
        ),
        "date_range": {
            "first": all_tx["timestamp"].min() if total else None,
            "last":  all_tx["timestamp"].max() if total else None,
        },
        "payment_rails":         {k: int(v) for k, v in rail_counts.items()},
        "currencies":            {k: int(v) for k, v in ccy_counts.items()},
        "screening_verdicts": {
            "BLOCK":   len(blocked_ids),
            "REVIEW":  len(review_ids),
            "CLEAR":   len(clear_ids),
            "unscreened": total - len(blocked_ids) - len(review_ids) - len(clear_ids),
        },
    }

    # ---- Transaction graph ----
    # Build a node for each unique recipient and an edge aggregating all tx to them.
    # Nodes: "source" (this account) + one node per unique recipient.
    # Edges: one per unique recipient.

    risk_lookup = {}  # account_id -> (overall_risk_score, risk_band, full_name, latest_verdict)
    if dl.accounts_enriched is not None:
        for _, r in dl.accounts_enriched[
            ["account_id", "overall_risk_score", "risk_band", "full_name", "latest_verdict"]
        ].iterrows():
            risk_lookup[r["account_id"]] = {
                "overall_risk_score": r.get("overall_risk_score"),
                "risk_band":          r.get("risk_band"),
                "full_name":          r.get("full_name"),
                "latest_verdict":     r.get("latest_verdict"),
            }

    wallet_lookup = {}  # wallet_id OR wallet_address -> wallet row dict
    if dl.wallets_df is not None:
        for _, w in dl.wallets_df.iterrows():
            wd = w.to_dict()
            wallet_lookup[w["wallet_id"]]      = wd
            wallet_lookup[w["wallet_address"]] = wd

    # Aggregation: key -> {"tx_count", "total_amount", "amounts", "currencies", "rails",
    #                       "first_ts", "last_ts", "node_type", "node_meta"}
    edge_agg: dict = defaultdict(lambda: {
        "tx_count": 0, "total_amount": 0.0, "amounts": [],
        "currencies": defaultdict(int), "rails": defaultdict(int),
        "first_ts": None, "last_ts": None,
        "node_type": None, "node_meta": {},
    })

    for _, tx in all_tx.iterrows():
        rtype = tx.get("recipient_type")
        amt   = tx.get("amount")
        ts    = tx.get("timestamp")
        ccy   = tx.get("currency", "")
        rail  = tx.get("payment_rail", "")

        if rtype == "account" and not _is_nan(tx.get("recipient_account_id")):
            key = ("account", tx["recipient_account_id"])
            meta = risk_lookup.get(tx["recipient_account_id"], {})
            edge_agg[key]["node_type"] = "account"
            edge_agg[key]["node_meta"] = meta

        elif rtype == "crypto_wallet" and not _is_nan(tx.get("recipient_wallet_id")):
            key = ("wallet", tx["recipient_wallet_id"])
            w = wallet_lookup.get(tx["recipient_wallet_id"], {})
            edge_agg[key]["node_type"] = "wallet"
            edge_agg[key]["node_meta"] = w

        else:
            # external individual — key on recipient_name; fall back to "unknown"
            rname = tx.get("recipient_name") or "unknown"
            key = ("external", rname)
            edge_agg[key]["node_type"] = "external"
            edge_agg[key]["node_meta"] = {
                "recipient_name":    rname,
                "recipient_country": tx.get("recipient_country"),
            }

        agg = edge_agg[key]
        agg["tx_count"]      += 1
        agg["total_amount"]  += float(amt) if amt and not _is_nan(amt) else 0.0
        if amt and not _is_nan(amt):
            agg["amounts"].append(float(amt))
        agg["currencies"][ccy] += 1
        agg["rails"][rail]     += 1
        if ts:
            agg["first_ts"] = ts if agg["first_ts"] is None else min(agg["first_ts"], ts)
            agg["last_ts"]  = ts if agg["last_ts"]  is None else max(agg["last_ts"],  ts)

    # Source node
    source_node = {
        "id":               account_id,
        "type":             "source",
        "label":            acct.get("full_name") or account_id,
        "account_type":     acct.get("account_type"),
        "overall_risk_score": acct.get("overall_risk_score"),
        "risk_band":        acct.get("risk_band"),
        "latest_verdict":   acct.get("latest_verdict"),
        "kyc_status":       acct.get("kyc_status"),
        "is_pep":           int(acct.get("is_pep") or 0),
        "country_residence": acct.get("country_residence"),
    }

    nodes = [source_node]
    edges = []

    for (ntype, nid), agg in edge_agg.items():
        avg_amt  = round(agg["total_amount"] / agg["tx_count"], 2) if agg["tx_count"] else 0.0
        total_amt = round(agg["total_amount"], 2)
        meta     = agg["node_meta"]

        if ntype == "account":
            node = {
                "id":                 nid,
                "type":               "account",
                "label":              meta.get("full_name") or nid,
                "overall_risk_score": meta.get("overall_risk_score"),
                "risk_band":          meta.get("risk_band"),
                "latest_verdict":     meta.get("latest_verdict"),
                "transaction_count":  agg["tx_count"],
                "total_amount":       total_amt,
                "avg_amount":         avg_amt,
                "currencies":         dict(agg["currencies"]),
                "payment_rails":      dict(agg["rails"]),
                "first_transaction":  agg["first_ts"],
                "last_transaction":   agg["last_ts"],
            }

        elif ntype == "wallet":
            node = {
                "id":               nid,
                "type":             "wallet",
                "label":            meta.get("wallet_address") or nid,
                "chain":            meta.get("chain"),
                "is_sanctioned":    bool(meta.get("is_sanctioned")),
                "sanctioned_entity_id": meta.get("sanctioned_entity_id") if meta.get("sanctioned_entity_id") else None,
                "owner_account_id": meta.get("account_id"),
                "transaction_count": agg["tx_count"],
                "total_amount":     total_amt,
                "avg_amount":       avg_amt,
                "currencies":       dict(agg["currencies"]),
                "payment_rails":    dict(agg["rails"]),
                "first_transaction": agg["first_ts"],
                "last_transaction":  agg["last_ts"],
            }

        else:  # external
            node = {
                "id":               f"ext:{nid}",
                "type":             "external",
                "label":            meta.get("recipient_name") or nid,
                "country":          meta.get("recipient_country"),
                "transaction_count": agg["tx_count"],
                "total_amount":     total_amt,
                "avg_amount":       avg_amt,
                "currencies":       dict(agg["currencies"]),
                "payment_rails":    dict(agg["rails"]),
                "first_transaction": agg["first_ts"],
                "last_transaction":  agg["last_ts"],
            }

        nodes.append(node)

        to_id = nid if ntype != "external" else f"ext:{nid}"
        edges.append({
            "from":              account_id,
            "to":                to_id,
            "recipient_type":    ntype,
            "transaction_count": agg["tx_count"],
            "total_amount":      total_amt,
            "avg_amount":        avg_amt,
            "currencies":        dict(agg["currencies"]),
            "payment_rails":     dict(agg["rails"]),
            "first_transaction": agg["first_ts"],
            "last_transaction":  agg["last_ts"],
        })

    # Sort edges by transaction_count descending
    edges.sort(key=lambda e: e["transaction_count"], reverse=True)

    transaction_graph = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }

    # ---- Known relationships (ownership / family / associate / directorship) ----
    relationships = []
    if dl.relationships_df is not None:
        rel_rows = dl.relationships_df[dl.relationships_df["account_id"] == account_id]
        for _, r in rel_rows.iterrows():
            relationships.append({
                "relationship_id":        r.get("relationship_id"),
                "related_entity_name":    r.get("related_entity_name"),
                "relationship_type":      r.get("relationship_type"),
                "related_is_pep":         bool(r.get("related_is_pep")),
                "related_is_sanctioned":  bool(r.get("related_is_sanctioned")),
                "sanctioned_entity_id":   r.get("related_sanctioned_entity_id") if r.get("related_is_sanctioned") else None,
                "source":                 r.get("source"),
            })

    # ---- Paginated transactions with per-tx screening ----
    page_tx = all_tx.iloc[(page - 1) * limit : page * limit]
    transactions = []
    for _, tx in page_tx.iterrows():
        tid = tx.get("transaction_id")
        scr = dl.screening_by_tx.get(tid) if dl.screening_by_tx else None

        # Resolve recipient identity for this specific transaction
        rtype = tx.get("recipient_type")
        recipient_risk_score = None
        recipient_risk_band  = None
        recipient_full_name  = None
        recipient_is_sanctioned = None

        if rtype == "account" and not _is_nan(tx.get("recipient_account_id")):
            rinfo = risk_lookup.get(tx["recipient_account_id"], {})
            recipient_risk_score = rinfo.get("overall_risk_score")
            recipient_risk_band  = rinfo.get("risk_band")
            recipient_full_name  = rinfo.get("full_name")

        elif rtype == "crypto_wallet" and not _is_nan(tx.get("recipient_wallet_id")):
            winfo = wallet_lookup.get(tx["recipient_wallet_id"], {})
            recipient_is_sanctioned = bool(winfo.get("is_sanctioned"))

        tx_dict = {
            "transaction_id":          tid,
            "amount":                  tx.get("amount"),
            "currency":                tx.get("currency"),
            "payment_rail":            tx.get("payment_rail"),
            "recipient_type":          rtype,
            "recipient_account_id":    tx.get("recipient_account_id") if not _is_nan(tx.get("recipient_account_id")) else None,
            "recipient_wallet_id":     tx.get("recipient_wallet_id") if not _is_nan(tx.get("recipient_wallet_id")) else None,
            "recipient_name":          tx.get("recipient_name") if tx.get("recipient_name") else None,
            "recipient_country":       tx.get("recipient_country"),
            "recipient_full_name":     recipient_full_name,
            "recipient_risk_score":    recipient_risk_score,
            "recipient_risk_band":     recipient_risk_band,
            "recipient_is_sanctioned": recipient_is_sanctioned,
            "timestamp":               tx.get("timestamp"),
            "velocity_30d_count":      tx.get("velocity_30d_count"),
            "velocity_30d_amount":     tx.get("velocity_30d_amount"),
            "is_first_time_recipient": int(tx.get("is_first_time_recipient") or 0),
            "hour_of_day":             tx.get("hour_of_day"),
            "day_of_week":             tx.get("day_of_week"),
            "screening": {
                "screening_id":    scr.get("screening_id") if scr else None,
                "match_score":     scr.get("match_score") if scr else None,
                "dynamic_verdict": scr.get("dynamic_verdict") if scr else None,
                "dynamic_t_block": scr.get("dynamic_t_block") if scr else None,
                "dynamic_t_review": scr.get("dynamic_t_review") if scr else None,
                "static_verdict":  scr.get("static_verdict") if scr else None,
                "static_threshold": scr.get("static_threshold") if scr else None,
                "verdicts_differ": bool(scr.get("verdicts_differ")) if scr else None,
            } if scr else None,
        }
        transactions.append(tx_dict)

    return clean({
        "account_id": account_id,

        "account": {
            "account_id":            acct.get("account_id"),
            "full_name":             acct.get("full_name"),
            "account_type":          acct.get("account_type"),
            "kyc_completeness":      acct.get("kyc_completeness"),
            "kyc_status":            acct.get("kyc_status"),
            "is_pep":                int(acct.get("is_pep") or 0),
            "has_complex_ownership": int(acct.get("has_complex_ownership") or 0),
            "shell_company_flag":    int(acct.get("shell_company_flag") or 0),
            "activity_tier":         acct.get("activity_tier"),
            "account_status":        acct.get("account_status"),
            "country_residence":     acct.get("country_residence"),
            "created_at":            acct.get("created_at"),
        },

        "risk_score": {
            "overall_risk_score":        acct.get("overall_risk_score"),
            "risk_band":                 acct.get("risk_band"),
            "geographic_risk":           acct.get("geographic_risk"),
            "identity_kyc_risk":         acct.get("identity_kyc_risk"),
            "pep_sanctions_risk":        acct.get("pep_sanctions_risk"),
            "behavioural_risk":          acct.get("behavioural_risk"),
            "relationship_network_risk": acct.get("relationship_network_risk"),
            "scored_at":                 acct.get("computed_at"),
            "risk_formula": "overall = 0.25×geographic + 0.15×identity_kyc + 0.30×pep_sanctions + 0.20×behavioural + 0.10×relationship_network",
        },

        "model_output": {
            "verdict":               model_result["verdict"],
            "block_probability":     model_result["block_probability"],
            "class_probabilities":   model_result["class_probabilities"],
            "audit_narrative":       model_result["audit_narrative"],
            "audit_factors":         model_result["audit_factors"],
            "feature_contributions": model_result["feature_contributions"],
            "risk_components":       model_result["risk_components"],
        },

        "threshold_explanation": threshold_fm,

        "relationships": relationships,
        "relationship_count": len(relationships),

        "summary": summary,

        "transaction_graph": transaction_graph,

        "transactions": transactions,
        "total": total,
        "page": page,
        "limit": limit,
    })
