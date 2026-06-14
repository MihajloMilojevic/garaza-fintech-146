"""
Loads all parquet exports into memory at startup and precomputes merged views.
All routers import from this module — do not import parquet files elsewhere.
"""

import os
import math
import pandas as pd
from pathlib import Path

# Configurable via env var; default is relative to the backend/ directory
EXPORTS_DIR = Path(os.environ.get("EXPORTS_DIR", str(Path(__file__).resolve().parent.parent.parent / "project" / "exports")))

# Raw tables
accounts_df: pd.DataFrame | None = None
risk_scores_df: pd.DataFrame | None = None
screening_df: pd.DataFrame | None = None
threshold_df: pd.DataFrame | None = None
transactions_df: pd.DataFrame | None = None
relationships_df: pd.DataFrame | None = None
wallets_df: pd.DataFrame | None = None
logs_df: pd.DataFrame | None = None

# Precomputed views
accounts_enriched: pd.DataFrame | None = None   # accounts + risk_scores + latest account-level verdict
screening_merged: pd.DataFrame | None = None    # screening_results + threshold_decisions
screening_by_tx: dict = {}                      # transaction_id -> screening_merged row dict


def load_all() -> None:
    global accounts_df, risk_scores_df, screening_df, threshold_df
    global transactions_df, relationships_df, wallets_df, logs_df
    global accounts_enriched, screening_merged, screening_by_tx

    accounts_df       = pd.read_parquet(EXPORTS_DIR / "accounts.parquet")
    risk_scores_df    = pd.read_parquet(EXPORTS_DIR / "risk_scores.parquet")
    screening_df      = pd.read_parquet(EXPORTS_DIR / "screening_results.parquet")
    threshold_df      = pd.read_parquet(EXPORTS_DIR / "threshold_decisions.parquet")
    transactions_df   = pd.read_parquet(EXPORTS_DIR / "transactions.parquet")
    relationships_df  = pd.read_parquet(EXPORTS_DIR / "account_relationships.parquet")
    wallets_df        = pd.read_parquet(EXPORTS_DIR / "wallets.parquet")
    logs_df           = pd.read_parquet(EXPORTS_DIR / "explanatory_logs.parquet")

    # --- screening_merged: join screening_results + threshold_decisions ---
    screening_merged = pd.merge(
        screening_df,
        threshold_df[[
            "screening_id", "static_threshold", "static_verdict",
            "dynamic_t_block", "dynamic_t_review", "dynamic_verdict", "verdicts_differ",
        ]],
        on="screening_id",
        how="left",
    )

    # --- screening_by_tx: fast lookup of transaction-level screenings by transaction_id ---
    tx_screenings = screening_merged[
        screening_merged["screening_context"] == "transaction"
    ].copy()
    tx_screenings = tx_screenings[tx_screenings["transaction_id"].notna()]
    screening_by_tx = {
        row["transaction_id"]: row.to_dict()
        for _, row in tx_screenings.iterrows()
    }

    # --- accounts_enriched: accounts + risk_scores + account-level verdict ---
    acct_screenings = (
        screening_merged[screening_merged["screening_context"] == "account"]
        [["account_id", "screening_id", "match_score", "dynamic_verdict", "dynamic_t_block", "dynamic_t_review"]]
        .rename(columns={
            "screening_id":    "latest_screening_id",
            "match_score":     "latest_match_score",
            "dynamic_verdict": "latest_verdict",
            "dynamic_t_block": "latest_t_block",
            "dynamic_t_review": "latest_t_review",
        })
    )

    accounts_enriched = (
        accounts_df
        .merge(
            risk_scores_df[[
                "account_id", "overall_risk_score", "risk_band",
                "geographic_risk", "identity_kyc_risk", "pep_sanctions_risk",
                "behavioural_risk", "relationship_network_risk",
                "override_applied", "computed_at",
            ]],
            on="account_id",
            how="left",
        )
        .merge(acct_screenings, on="account_id", how="left")
    )


def clean(obj):
    """Recursively replace NaN/inf with None and coerce numpy scalars to Python natives."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def row_to_dict(row: pd.Series) -> dict:
    return clean(row.where(pd.notnull(row), None).to_dict())
