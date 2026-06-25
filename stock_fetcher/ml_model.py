"""
LightGBM prediction model for stock screening.

Label: 未來 5 日報酬 > 0050 同期報酬 + 2% → 1，否則 0
Features: 14 因子原始值（非百分位），KD 拆解為 k/d/k-d 三個連續特徵 + near_breakout/price_position，共 19 維

Usage:
    from stock_fetcher.ml_model import train_model, predict_today
    result = train_model()      # Walk-forward training
    preds  = predict_today()    # Inference on latest data
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict

import numpy as np

from . import tw_db
from .tw_market import (
    _compute_multi_day_factors,
    _compute_extended_factors,
    SCREENER_CONFIG,
)
from .ml_config import (
    FORWARD_DAYS,
    EXCESS_RETURN_THRESHOLD,
    BENCHMARK_SYMBOL,
    WARM_UP_DAYS,
    MIN_TRAIN_DAYS,
    EXTREME_RETURN_CAP,
    MIN_VOLUME,
    LGBM_PARAMS,
    MODEL_PATH,
    META_PATH,
    FEATURE_NAMES,
    PURGE_GAP_DAYS,
    WF_FOLD_DAYS,
    WF_MIN_TRAIN_SAMPLES,
)

logger = logging.getLogger(__name__)


# ── Feature extraction ──────────────────────────────────────────────────────

def _extract_features(stock: dict) -> list[float | None]:
    """Extract raw feature values from an enriched stock dict."""
    k_val = stock.get("kd_value")
    d_val = stock.get("d_value")
    k_minus_d = (k_val - d_val) if k_val is not None and d_val is not None else None

    mapping = {
        "bb_squeeze": stock.get("bb_squeeze"),
        "volume_breakout": stock.get("volume_breakout"),
        "box_breakout": stock.get("box_breakout"),
        "squeeze_volume": stock.get("squeeze_volume"),
        "avwap_dev": stock.get("avwap_dev"),
        "near_breakout": stock.get("near_breakout"),
        "price_position": stock.get("price_position"),
        "tangled_ma": stock.get("tangled_ma"),
        "liquidity_sweep": stock.get("liquidity_sweep"),
        "obv_divergence": stock.get("obv_divergence"),
        "volume_contraction": stock.get("volume_contraction"),
        "k_value": k_val,
        "d_value": d_val,
        "k_minus_d": k_minus_d,
        "trust_net_5d": stock.get("trust_net_5d"),
        "inst_volume_ratio": stock.get("inst_volume_ratio"),
        "foreign_net_5d": stock.get("foreign_net_5d"),
        "trust_streak": stock.get("trust_streak"),
        "foreign_streak": stock.get("foreign_streak"),
        "revenue_yoy": stock.get("revenue_yoy"),
        "revenue_mom": stock.get("revenue_mom"),
    }
    return [mapping[f] for f in FEATURE_NAMES]


def _enrich_stock(
    symbol: str,
    history: list[dict],
    signal_date: str,
    *,
    inst_data: dict | None = None,
    revenue_data: dict | None = None,
    shareholder_data: dict | None = None,
) -> dict:
    """Compute all raw factors for a single stock (no percentile ranking)."""
    result = {"symbol": symbol}

    tech = _compute_multi_day_factors(symbol, history=history)
    result.update(tech)

    # KD cross produces kd_value (K), but we also need D
    if len(history) >= 2:
        hist_fwd = list(reversed(history))
        full_rows = [
            h for h in hist_fwd
            if all(h.get(k) is not None for k in ("open", "high", "low", "close", "volume"))
        ]
        if len(full_rows) >= 9:
            from .indicators import stochastic_kd
            kd = stochastic_kd(
                [r["high"] for r in full_rows],
                [r["low"] for r in full_rows],
                [r["close"] for r in full_rows],
            )
            result["d_value"] = kd["d"][-1] if kd["d"] and kd["d"][-1] is not None else None

    ext = _compute_extended_factors(
        symbol, signal_date,
        inst_data=inst_data,
        revenue_data=revenue_data,
        shareholder_data=shareholder_data,
    )
    result.update(ext)

    # inst_volume_ratio
    avg_vol = result.get("avg_vol_5d")
    fnet = abs(result.get("foreign_net_5d", 0) or 0)
    tnet = abs(result.get("trust_net_5d", 0) or 0)
    if avg_vol and avg_vol > 0:
        result["inst_volume_ratio"] = round((fnet + tnet) / (avg_vol * 5) * 100, 4)

    return result


# ── Data loading (same patterns as backtester) ──────────────────────────────

def _load_all_data():
    """Load prices, companies, and extended data into memory."""
    trading_dates = tw_db.get_trading_dates()

    raw = tw_db.get_all_daily_prices()
    prices: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in raw:
        sym = row.pop("symbol")
        dt = row.pop("date")
        prices[sym][dt] = row

    companies = tw_db.get_all_companies()

    inst_data: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in tw_db.get_all_institutional_trading():
        sym = row.pop("symbol")
        dt = row.pop("date")
        inst_data[sym][dt] = row

    revenue_data: dict[str, list[dict]] = defaultdict(list)
    for row in tw_db.get_all_monthly_revenue():
        sym = row.pop("symbol")
        revenue_data[sym].append(row)

    shareholder_data: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in tw_db.get_all_shareholder_concentration():
        sym = row.pop("symbol")
        dt = row.pop("date")
        shareholder_data[sym][dt] = row

    logger.info(
        "ML data loaded: %d dates, %d stocks, %d inst, %d rev, %d sh",
        len(trading_dates), len(prices),
        len(inst_data), len(revenue_data), len(shareholder_data),
    )
    return (
        trading_dates, dict(prices), companies,
        dict(inst_data), dict(revenue_data), dict(shareholder_data),
    )


def _get_history_before(
    prices: dict[str, dict[str, dict]],
    symbol: str,
    before_date: str,
    days: int = 200,
) -> list[dict]:
    """Return up to N days of history ending at before_date, newest first."""
    sym_prices = prices.get(symbol)
    if not sym_prices:
        return []
    filtered = [
        {"date": d, **p}
        for d, p in sym_prices.items()
        if d <= before_date
    ]
    return list(reversed(filtered[-days:]))


# ── Training ────────────────────────────────────────────────────────────────

def _build_dataset(
    trading_dates: list[str],
    prices: dict,
    inst_data: dict,
    revenue_data: dict,
    shareholder_data: dict,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build feature matrix, label array, and signal-date array from historical data."""
    date_to_idx = {d: i for i, d in enumerate(trading_dates)}
    backtest_dates = trading_dates[WARM_UP_DAYS:]

    all_X: list[list[float]] = []
    all_y: list[int] = []
    sample_dates: list[str] = []

    logger.info("ML dataset: building from %d candidate dates …", len(backtest_dates))

    for signal_date in backtest_dates:
        signal_idx = date_to_idx[signal_date]
        buy_idx = signal_idx + 1
        if buy_idx >= len(trading_dates):
            break
        target_idx = buy_idx + FORWARD_DAYS
        if target_idx >= len(trading_dates):
            break

        buy_date = trading_dates[buy_idx]
        target_date = trading_dates[target_idx]

        bench_buy = prices.get(BENCHMARK_SYMBOL, {}).get(buy_date)
        bench_target = prices.get(BENCHMARK_SYMBOL, {}).get(target_date)
        if not bench_buy or not bench_target:
            continue
        if not bench_buy.get("open") or bench_buy["open"] <= 0:
            continue
        if not bench_target.get("close"):
            continue
        bench_return = (bench_target["close"] / bench_buy["open"] - 1) * 100

        for sym, date_prices in prices.items():
            if sym == BENCHMARK_SYMBOL:
                continue
            if signal_date not in date_prices:
                continue

            row = date_prices[signal_date]
            if (row.get("volume") or 0) < MIN_VOLUME:
                continue

            history = _get_history_before(prices, sym, signal_date, 200)
            if len(history) < 60:
                continue

            hist_fwd = list(reversed(history))
            closes = [h["close"] for h in hist_fwd if h.get("close") is not None]
            if len(closes) >= 200:
                ma200 = sum(closes[-200:]) / 200
                if row.get("close", 0) < ma200:
                    continue

            buy_data = (
                date_prices.get(buy_date)
                if buy_date in date_prices
                else prices.get(sym, {}).get(buy_date)
            )
            target_data = prices.get(sym, {}).get(target_date)
            if not buy_data or not buy_data.get("open") or buy_data["open"] <= 0:
                continue
            if not target_data or not target_data.get("close"):
                continue

            stock_return = (target_data["close"] / buy_data["open"] - 1) * 100
            if abs(stock_return) > EXTREME_RETURN_CAP:
                continue

            label = 1 if stock_return > bench_return + EXCESS_RETURN_THRESHOLD else 0

            enriched = _enrich_stock(
                sym, history, signal_date,
                inst_data=inst_data, revenue_data=revenue_data,
                shareholder_data=shareholder_data,
            )
            features = _extract_features(enriched)
            all_X.append(features)
            all_y.append(label)
            sample_dates.append(signal_date)

        if len(sample_dates) % 5000 == 0 and len(sample_dates) > 0:
            logger.info("ML dataset: %d samples collected so far …", len(sample_dates))

    X = np.array(all_X, dtype=np.float64) if all_X else np.empty((0, len(FEATURE_NAMES)))
    y = np.array(all_y, dtype=np.int32) if all_y else np.empty(0, dtype=np.int32)
    dates = np.array(sample_dates)

    return X, y, dates


def _train_lgbm(X: np.ndarray, y: np.ndarray) -> "lgb.Booster":
    """Train a single LightGBM model on the given data."""
    import lightgbm as lgb

    pos_count = y.sum()
    neg_count = len(y) - pos_count
    spw = neg_count / pos_count if pos_count > 0 else 1.0

    params = dict(LGBM_PARAMS)
    params["scale_pos_weight"] = round(spw, 2)

    train_data = lgb.Dataset(
        X, label=y, feature_name=FEATURE_NAMES, free_raw_data=False,
    )
    return lgb.train(
        {k: v for k, v in params.items() if k != "n_estimators"},
        train_data,
        num_boost_round=params["n_estimators"],
    )


def train_model() -> dict:
    """Train LightGBM with Walk-Forward Expanding + Purge Gap.

    1. Build full dataset (features + labels) from historical data.
    2. Walk-Forward Expanding: expanding training window, purge gap, fixed test fold.
    3. Collect OOS predictions across all folds → OOS AUC.
    4. Train final production model on all data.
    5. Save model + metadata.

    Returns dict with training stats, OOS AUC, per-fold results, feature importance.
    """
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score

    logger.info("ML train: loading data …")
    (
        trading_dates, prices, companies,
        inst_data, revenue_data, shareholder_data,
    ) = _load_all_data()

    backtest_dates = trading_dates[WARM_UP_DAYS:]

    X, y, dates_arr = _build_dataset(
        trading_dates, prices, inst_data, revenue_data, shareholder_data,
    )

    if len(y) < WF_MIN_TRAIN_SAMPLES:
        return {"error": f"樣本不足：僅收集到 {len(y)} 筆（至少需要 {WF_MIN_TRAIN_SAMPLES} 筆）"}

    logger.info(
        "ML train: %d samples, positive rate %.1f%%, %d features",
        len(y), y.mean() * 100, X.shape[1],
    )

    # ── Walk-Forward Expanding ────────────────────────────────────────────
    unique_dates = sorted(set(dates_arr))
    n_dates = len(unique_dates)

    oos_preds = np.full(len(y), np.nan)
    fold_results = []

    cursor = MIN_TRAIN_DAYS
    fold_num = 0

    while cursor + PURGE_GAP_DAYS < n_dates:
        train_cutoff = unique_dates[cursor - 1]

        test_start_idx = cursor + PURGE_GAP_DAYS
        test_end_idx = min(test_start_idx + WF_FOLD_DAYS, n_dates)

        if test_start_idx >= n_dates:
            break

        test_dates_set = set(unique_dates[test_start_idx:test_end_idx])

        train_mask = dates_arr <= train_cutoff
        test_mask = np.array([d in test_dates_set for d in dates_arr])

        train_idx = np.where(train_mask)[0]
        test_idx = np.where(test_mask)[0]

        if len(train_idx) < WF_MIN_TRAIN_SAMPLES or len(test_idx) == 0:
            cursor = test_end_idx
            continue

        model = _train_lgbm(X[train_idx], y[train_idx])
        preds = model.predict(X[test_idx])
        oos_preds[test_idx] = preds

        y_test = y[test_idx]
        fold_auc = (
            round(roc_auc_score(y_test, preds), 4)
            if len(set(y_test)) > 1
            else None
        )
        fold_num += 1

        fold_results.append({
            "fold": fold_num,
            "train_end": train_cutoff,
            "test_start": unique_dates[test_start_idx],
            "test_end": unique_dates[test_end_idx - 1],
            "train_samples": int(len(train_idx)),
            "test_samples": int(len(test_idx)),
            "test_pos_rate": round(float(y_test.mean()) * 100, 1),
            "auc": fold_auc,
        })

        logger.info(
            "ML fold %d: train=%d test=%d AUC=%s [%s → %s]",
            fold_num, len(train_idx), len(test_idx),
            f"{fold_auc:.4f}" if fold_auc is not None else "N/A",
            unique_dates[test_start_idx], unique_dates[test_end_idx - 1],
        )

        cursor = test_end_idx

    # OOS AUC（所有 fold 的預測合併計算）
    oos_mask = ~np.isnan(oos_preds)
    oos_auc = None
    if oos_mask.sum() > 0 and len(set(y[oos_mask])) > 1:
        oos_auc = round(float(roc_auc_score(y[oos_mask], oos_preds[oos_mask])), 4)

    logger.info(
        "ML walk-forward: %d folds, OOS samples=%d, OOS AUC=%s",
        len(fold_results), int(oos_mask.sum()),
        f"{oos_auc:.4f}" if oos_auc is not None else "N/A",
    )

    # ── Final production model: train on ALL data ─────────────────────────
    final_model = _train_lgbm(X, y)

    y_pred_all = final_model.predict(X)
    insample_auc = round(float(roc_auc_score(y, y_pred_all)), 4)

    importance = final_model.feature_importance(importance_type="gain")
    importance_pct = (importance / importance.sum() * 100).round(1)
    feature_importance = sorted(
        zip(FEATURE_NAMES, importance_pct.tolist()),
        key=lambda x: x[1],
        reverse=True,
    )

    # ── Save ──────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    final_model.save_model(MODEL_PATH)

    pos_count = int(y.sum())
    meta = {
        "trained_at": trading_dates[-1] if trading_dates else "",
        "train_period": {
            "start": backtest_dates[0] if backtest_dates else "",
            "end": backtest_dates[-1] if backtest_dates else "",
        },
        "total_samples": len(y),
        "positive_samples": pos_count,
        "positive_rate": round(float(y.mean()) * 100, 1),
        "auc_insample": insample_auc,
        "auc_oos": oos_auc,
        "walk_forward": {
            "n_folds": len(fold_results),
            "purge_gap_days": PURGE_GAP_DAYS,
            "fold_days": WF_FOLD_DAYS,
            "min_train_samples": WF_MIN_TRAIN_SAMPLES,
            "oos_samples": int(oos_mask.sum()),
            "folds": fold_results,
        },
        "scale_pos_weight": round(
            (len(y) - pos_count) / pos_count if pos_count > 0 else 1.0, 2,
        ),
        "feature_importance": feature_importance,
        "feature_names": FEATURE_NAMES,
        "forward_days": FORWARD_DAYS,
        "excess_threshold": EXCESS_RETURN_THRESHOLD,
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info(
        "ML train complete: %d samples, OOS AUC=%s, IS AUC=%.4f, %d folds, saved to %s",
        len(y), f"{oos_auc:.4f}" if oos_auc is not None else "N/A",
        insample_auc, len(fold_results), MODEL_PATH,
    )

    return {
        "status": "ok",
        "total_samples": len(y),
        "positive_samples": pos_count,
        "positive_rate": round(float(y.mean()) * 100, 1),
        "auc_insample": insample_auc,
        "auc_oos": oos_auc,
        "walk_forward": {
            "n_folds": len(fold_results),
            "folds": fold_results,
        },
        "feature_importance": feature_importance,
        "train_period": meta["train_period"],
    }


# ── Prediction ──────────────────────────────────────────────────────────────

def predict_today() -> dict:
    """Run inference on the latest snapshot using the trained model.

    Returns dict with ranked predictions (symbol, name, probability, close, change_pct).
    """
    import lightgbm as lgb

    if not os.path.exists(MODEL_PATH):
        return {"error": "模型尚未訓練，請先點擊「重新訓練」"}

    model = lgb.Booster(model_file=MODEL_PATH)

    meta = {}
    if os.path.exists(META_PATH):
        with open(META_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)

    # Load latest data
    (
        trading_dates, prices, companies,
        inst_data, revenue_data, shareholder_data,
    ) = _load_all_data()

    if not trading_dates:
        return {"error": "無交易日資料"}

    latest_date = trading_dates[-1]
    logger.info("ML predict: running inference on %s", latest_date)

    predictions = []

    for sym, date_prices in prices.items():
        if sym == BENCHMARK_SYMBOL:
            continue
        if latest_date not in date_prices:
            continue

        row = date_prices[latest_date]
        if (row.get("volume") or 0) < MIN_VOLUME:
            continue

        history = _get_history_before(prices, sym, latest_date, 200)
        if len(history) < 60:
            continue

        # MA200 filter
        hist_fwd = list(reversed(history))
        closes = [h["close"] for h in hist_fwd if h.get("close") is not None]
        if len(closes) >= 200:
            ma200 = sum(closes[-200:]) / 200
            if row.get("close", 0) < ma200:
                continue

        enriched = _enrich_stock(
            sym, history, latest_date,
            inst_data=inst_data, revenue_data=revenue_data,
            shareholder_data=shareholder_data,
        )
        features = _extract_features(enriched)

        X = np.array([features], dtype=np.float64)
        prob = model.predict(X)[0]

        company = companies.get(sym, {})
        predictions.append({
            "symbol": sym,
            "name": company.get("name", ""),
            "probability": round(float(prob) * 100, 1),
            "close": row.get("close", 0),
            "change_pct": row.get("change_pct", 0),
            "volume": row.get("volume", 0),
        })

    predictions.sort(key=lambda x: x["probability"], reverse=True)

    return {
        "status": "ok",
        "signal_date": latest_date,
        "total_stocks": len(predictions),
        "top_picks": predictions[:30],
        "model_info": {
            "train_period": meta.get("train_period", {}),
            "total_samples": meta.get("total_samples", 0),
            "positive_rate": meta.get("positive_rate", 0),
            "auc_insample": meta.get("auc_insample", 0),
            "feature_importance": meta.get("feature_importance", []),
        },
    }


def get_model_status() -> dict:
    """Check if a trained model exists and return its metadata."""
    if not os.path.exists(MODEL_PATH):
        return {"trained": False}

    meta = {}
    if os.path.exists(META_PATH):
        with open(META_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)

    return {
        "trained": True,
        "train_period": meta.get("train_period", {}),
        "total_samples": meta.get("total_samples", 0),
        "positive_rate": meta.get("positive_rate", 0),
        "auc_insample": meta.get("auc_insample", 0),
        "feature_importance": meta.get("feature_importance", []),
    }
