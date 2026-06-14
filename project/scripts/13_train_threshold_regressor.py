"""
13_train_threshold_regressor.py
================================
Train two XGBoost regressors — one for dynamic_t_block, one for dynamic_t_review
— on the noisy threshold labels produced by script 12.

Why two separate models instead of XGBoost multi-output (>= 2.0)?
  - More portable: works with XGBoost 1.x and 2.x alike.
  - Feature importances are per-target, giving cleaner audit narrative for each.
  - No API instability risk from a recently-added experimental feature.
  - Downside: slightly more params; negligible at this scale.

Feature set
-----------
Account-level features (all rows):
  overall_risk_score, geographic_risk, identity_kyc_risk, pep_sanctions_risk,
  behavioural_risk, relationship_network_risk, kyc_completeness, kyc_status_enc,
  account_type_enc, is_pep, has_complex_ownership, shell_company_flag,
  activity_tier_enc, account_status_enc, shares_address_with_sanctioned,
  pep_exposure_score, country_risk_score, override_applied

Transaction-level features (filled with 0 for account-context rows):
  amount_log, payment_rail_enc, is_first_time_recipient, velocity_30d_count,
  velocity_30d_amount_log, hour_of_day, day_of_week, has_transaction

  `amount_log`           = log1p(amount) — reduces skew from large wire transfers
  `velocity_30d_amount_log` = log1p(velocity_30d_amount) — same reason
  `has_transaction`      = 1 if this screening has a linked transaction, 0 otherwise

Excluded features (same exclusions as old classifiers):
  hops_to_sanctioned, name_match_type_enc — label-proxy / leakage risk
  dynamic_verdict, verdicts_differ — derived from targets
  match_score — not a threshold-driver, it's the score compared TO the threshold

Targets:
  dynamic_t_block   (noisy, σ=4.0)
  dynamic_t_review  (noisy, σ=3.5)

CV: 5-fold, reporting MAE / RMSE / R² for each target.

Outputs
-------
  ai/model/model_threshold_regressor_block.ubj
  ai/model/model_threshold_regressor_review.ubj
  ai/model/model_metadata.json   (updated with regressor section)
"""

import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import xgboost as xgb

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_DIR  = "/home/mihajlo/Mihajlo/Projekti/garaza/project"
EXPORTS_DIR  = os.path.join(PROJECT_DIR, "exports")
MODEL_DIR    = "/home/mihajlo/Mihajlo/Projekti/garaza/ai/model"
LOG_PATH     = os.path.join(PROJECT_DIR, "logs", "generation_log.txt")

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("13_train_threshold_regressor")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


# ── Encoders ──────────────────────────────────────────────────────────────────

KYC_STATUS_ENC      = {"complete": 0, "partial": 1, "pending": 2, "expired": 3}
ACTIVITY_ENC        = {"low": 0, "medium": 1, "high": 2}
ACCOUNT_STATUS_ENC  = {"active": 0, "suspended": 1, "closed": 2}
ACCOUNT_TYPE_ENC    = {"individual": 0, "business": 1}
PAYMENT_RAIL_ENC    = {"ach": 0, "card": 1, "check": 2, "crypto": 3,
                       "internal": 4, "wire": 5}

FEATURE_ORDER_REG = [
    # account-level
    "account_type_enc",
    "kyc_completeness",
    "kyc_status_enc",
    "is_pep",
    "has_complex_ownership",
    "shell_company_flag",
    "activity_tier_enc",
    "account_status_enc",
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
    # transaction-level
    "has_transaction",
    "amount_log",
    "payment_rail_enc",
    "is_first_time_recipient",
    "velocity_30d_count",
    "velocity_30d_amount_log",
    "hour_of_day",
    "day_of_week",
]


# ── Data assembly ─────────────────────────────────────────────────────────────

def build_dataset(logger) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    logger.info("Loading parquet files …")
    td  = pd.read_parquet(os.path.join(EXPORTS_DIR, "threshold_decisions.parquet"))
    sr  = pd.read_parquet(os.path.join(EXPORTS_DIR, "screening_results.parquet"))
    rs  = pd.read_parquet(os.path.join(EXPORTS_DIR, "risk_scores.parquet"))
    acc = pd.read_parquet(os.path.join(EXPORTS_DIR, "accounts.parquet"))
    tx  = pd.read_parquet(os.path.join(EXPORTS_DIR, "transactions.parquet"))
    logger.info(f"  td:{len(td)}  sr:{len(sr)}  rs:{len(rs)}  "
                f"acc:{len(acc)}  tx:{len(tx)}")

    # Join td → sr to get account_id, transaction_id, country_risk_score, etc.
    df = td.merge(
        sr[["screening_id", "account_id", "transaction_id",
            "shares_address_with_sanctioned", "pep_exposure_score",
            "country_risk_score"]],
        on="screening_id", how="left", suffixes=("_td", "")
    )
    # Resolve transaction_id (td has it as NaN for account-level rows,
    # sr has it too; use the one from sr)
    if "transaction_id_td" in df.columns:
        df["transaction_id"] = df["transaction_id"].fillna(df["transaction_id_td"])
        df.drop(columns=["transaction_id_td"], inplace=True)

    # Join risk scores
    df = df.merge(
        rs[["account_id", "overall_risk_score", "geographic_risk", "identity_kyc_risk",
            "pep_sanctions_risk", "behavioural_risk", "relationship_network_risk",
            "override_applied"]],
        on="account_id", how="left"
    )

    # Join account attributes
    df = df.merge(
        acc[["account_id", "account_type", "kyc_completeness", "kyc_status",
             "is_pep", "has_complex_ownership", "shell_company_flag",
             "activity_tier", "account_status"]],
        on="account_id", how="left"
    )

    # Join transaction features (left join — account-context rows get NaN)
    df = df.merge(
        tx[["transaction_id", "amount", "payment_rail", "is_first_time_recipient",
            "velocity_30d_count", "velocity_30d_amount", "hour_of_day", "day_of_week"]],
        on="transaction_id", how="left"
    )

    logger.info(f"  Merged dataset: {len(df)} rows, {df.shape[1]} columns")

    # ── Encode categoricals ────────────────────────────────────────────────────
    df["account_type_enc"]   = df["account_type"].map(ACCOUNT_TYPE_ENC).fillna(0).astype(int)
    df["kyc_status_enc"]     = df["kyc_status"].map(KYC_STATUS_ENC).fillna(0).astype(int)
    df["activity_tier_enc"]  = df["activity_tier"].map(ACTIVITY_ENC).fillna(0).astype(int)
    df["account_status_enc"] = df["account_status"].map(ACCOUNT_STATUS_ENC).fillna(0).astype(int)

    # ── Transaction features ───────────────────────────────────────────────────
    df["has_transaction"]      = df["amount"].notna().astype(int)
    df["amount_log"]           = np.log1p(df["amount"].fillna(0))
    df["payment_rail_enc"]     = df["payment_rail"].map(PAYMENT_RAIL_ENC).fillna(-1).astype(int)
    df["is_first_time_recipient"] = df["is_first_time_recipient"].fillna(0).astype(int)
    df["velocity_30d_count"]   = df["velocity_30d_count"].fillna(0).astype(float)
    df["velocity_30d_amount_log"] = np.log1p(df["velocity_30d_amount"].fillna(0))
    df["hour_of_day"]          = df["hour_of_day"].fillna(12).astype(int)
    df["day_of_week"]          = df["day_of_week"].fillna(0).astype(int)

    # ── Fill remaining NaN in numeric account features ─────────────────────────
    for col in ["overall_risk_score", "geographic_risk", "identity_kyc_risk",
                "pep_sanctions_risk", "behavioural_risk", "relationship_network_risk"]:
        df[col] = df[col].fillna(50.0)
    df["kyc_completeness"]            = df["kyc_completeness"].fillna(0.5)
    df["shares_address_with_sanctioned"] = df["shares_address_with_sanctioned"].fillna(0)
    df["pep_exposure_score"]          = df["pep_exposure_score"].fillna(0)
    df["country_risk_score"]          = df["country_risk_score"].fillna(25.0)
    df["is_pep"]                      = df["is_pep"].fillna(0).astype(int)
    df["has_complex_ownership"]       = df["has_complex_ownership"].fillna(0).astype(int)
    df["shell_company_flag"]          = df["shell_company_flag"].fillna(0).astype(int)
    df["override_applied"]            = df["override_applied"].fillna(0).astype(int)

    X = df[FEATURE_ORDER_REG].astype(np.float32)
    y_block  = df["dynamic_t_block"].astype(np.float32)
    y_review = df["dynamic_t_review"].astype(np.float32)

    logger.info(f"  Feature matrix shape: {X.shape}")
    logger.info(f"  NaN in X: {X.isna().sum().sum()}")
    return X, y_block, y_review


# ── CV evaluation ──────────────────────────────────────────────────────────────

def cv_metrics(X, y, model_params, n_splits=5, seed=42, logger=None):
    kf     = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    maes, rmses, r2s = [], [], []

    for fold, (tr, va) in enumerate(kf.split(X), 1):
        m = xgb.XGBRegressor(**model_params)
        m.fit(X.iloc[tr], y.iloc[tr], verbose=False)
        preds = m.predict(X.iloc[va])
        mae   = mean_absolute_error(y.iloc[va], preds)
        rmse  = mean_squared_error(y.iloc[va], preds) ** 0.5
        r2    = r2_score(y.iloc[va], preds)
        maes.append(mae); rmses.append(rmse); r2s.append(r2)
        if logger:
            logger.info(f"    fold {fold}: MAE={mae:.3f}  RMSE={rmse:.3f}  R²={r2:.4f}")

    return {
        "mae":  float(np.mean(maes)),
        "rmse": float(np.mean(rmses)),
        "r2":   float(np.mean(r2s)),
        "mae_std":  float(np.std(maes)),
        "rmse_std": float(np.std(rmses)),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    logger = setup_logging()
    logger.info("=== 13_train_threshold_regressor.py started ===")
    logger.info(f"  XGBoost version: {xgb.__version__}")
    logger.info(f"  Two separate XGBRegressors (block + review)")

    X, y_block, y_review = build_dataset(logger)

    model_params = dict(
        n_estimators      = 400,
        max_depth         = 5,
        learning_rate     = 0.05,
        subsample         = 0.8,
        colsample_bytree  = 0.8,
        min_child_weight  = 5,
        reg_alpha         = 0.1,
        reg_lambda        = 1.0,
        random_state      = 42,
        n_jobs            = -1,
        tree_method       = "hist",
    )
    logger.info(f"  Model params: {model_params}")

    # ── 5-fold CV ─────────────────────────────────────────────────────────────
    logger.info("--- CV for t_block ---")
    block_cv = cv_metrics(X, y_block, model_params, logger=logger)
    logger.info(f"  MEAN  MAE={block_cv['mae']:.3f} ± {block_cv['mae_std']:.3f}  "
                f"RMSE={block_cv['rmse']:.3f} ± {block_cv['rmse_std']:.3f}  "
                f"R²={block_cv['r2']:.4f}")

    logger.info("--- CV for t_review ---")
    review_cv = cv_metrics(X, y_review, model_params, logger=logger)
    logger.info(f"  MEAN  MAE={review_cv['mae']:.3f} ± {review_cv['mae_std']:.3f}  "
                f"RMSE={review_cv['rmse']:.3f} ± {review_cv['rmse_std']:.3f}  "
                f"R²={review_cv['r2']:.4f}")

    # ── Final full-data models ─────────────────────────────────────────────────
    logger.info("Training final models on full dataset …")
    block_model  = xgb.XGBRegressor(**model_params)
    review_model = xgb.XGBRegressor(**model_params)
    block_model.fit(X, y_block, verbose=False)
    review_model.fit(X, y_review, verbose=False)
    logger.info("  Training complete.")

    # ── Feature importances ────────────────────────────────────────────────────
    fi_block  = dict(zip(FEATURE_ORDER_REG,
                         block_model.feature_importances_.tolist()))
    fi_review = dict(zip(FEATURE_ORDER_REG,
                         review_model.feature_importances_.tolist()))

    # Sort and log top features
    fi_block_sorted  = sorted(fi_block.items(),  key=lambda x: -x[1])
    fi_review_sorted = sorted(fi_review.items(), key=lambda x: -x[1])

    logger.info("--- Feature importances (t_block) ---")
    for feat, imp in fi_block_sorted[:10]:
        logger.info(f"  {feat:<35s}: {imp:.4f}")

    logger.info("--- Feature importances (t_review) ---")
    for feat, imp in fi_review_sorted[:10]:
        logger.info(f"  {feat:<35s}: {imp:.4f}")

    # ── Save models ────────────────────────────────────────────────────────────
    block_path  = os.path.join(MODEL_DIR, "model_threshold_regressor_block.ubj")
    review_path = os.path.join(MODEL_DIR, "model_threshold_regressor_review.ubj")
    block_model.save_model(block_path)
    review_model.save_model(review_path)
    logger.info(f"  Saved: {block_path}")
    logger.info(f"  Saved: {review_path}")

    # ── Update model_metadata.json ─────────────────────────────────────────────
    meta_path = os.path.join(MODEL_DIR, "model_metadata.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    meta["version"] = "2.0.0"
    meta["trained_at"] = datetime.now().strftime("%Y-%m-%d")
    meta["description"] = (
        "v2: Two XGBoost regressors predict (t_block, t_review) directly. "
        "The v1 classifiers (model_binary.ubj, model_multiclass.ubj) are retained "
        "but DEPRECATED — not used in compute_thresholds() as of v2."
    )

    meta["threshold_regressor"] = {
        "files": {
            "block":  "model_threshold_regressor_block.ubj",
            "review": "model_threshold_regressor_review.ubj",
        },
        "approach": "Two separate XGBRegressors, one per target",
        "noise_labels": {
            "seed": 42,
            "sigma_block": 4.0,
            "sigma_review": 3.5,
            "clamp_block": [10.0, 95.0],
            "clamp_review": [5.0, 95.0],
            "note": "Applied in script 12_add_threshold_noise.py — labels are noisy "
                    "to make the regression target non-trivial",
        },
        "post_predict_clamps": {
            "t_block":  [10.0, 95.0],
            "t_review": [5.0,  95.0],
            "ordering": "t_review forced < t_block if needed",
        },
        "cv_5fold": {
            "t_block": {
                "mae":  round(block_cv["mae"], 4),
                "rmse": round(block_cv["rmse"], 4),
                "r2":   round(block_cv["r2"], 4),
            },
            "t_review": {
                "mae":  round(review_cv["mae"], 4),
                "rmse": round(review_cv["rmse"], 4),
                "r2":   round(review_cv["r2"], 4),
            },
        },
        "feature_order": FEATURE_ORDER_REG,
        "feature_importances_block":  {k: round(v, 4) for k, v in fi_block_sorted},
        "feature_importances_review": {k: round(v, 4) for k, v in fi_review_sorted},
        "model_params": model_params,
    }

    meta["models"]["binary"]["status"]     = "DEPRECATED as of v2 — kept for reference"
    meta["models"]["multiclass"]["status"] = "DEPRECATED as of v2 — kept for reference"

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    logger.info(f"  Updated model_metadata.json (v2)")

    logger.info("=== 13_train_threshold_regressor.py finished ===")
    logger.info(f"  t_block  CV: MAE={block_cv['mae']:.3f}  "
                f"RMSE={block_cv['rmse']:.3f}  R²={block_cv['r2']:.4f}")
    logger.info(f"  t_review CV: MAE={review_cv['mae']:.3f}  "
                f"RMSE={review_cv['rmse']:.3f}  R²={review_cv['r2']:.4f}")


if __name__ == "__main__":
    main()
