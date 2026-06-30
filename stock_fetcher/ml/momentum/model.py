"""LightGBM binary classification model for breakout detection (momentum).

Label: Triple-Barrier Method
  Y=1 if intraday high reaches +UPPER_BARRIER_PCT% within MAX_HOLDING_DAYS (起漲)
  Y=0 if intraday low reaches LOWER_BARRIER_PCT% first, OR time barrier expires
Features: 21 維原始值（技術面 + 籌碼面 + 基本面）

Usage:
    from stock_fetcher.ml.momentum import train_model, predict_today
    result = train_model()      # Walk-forward training
    preds  = predict_today()    # Inference on latest data
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict

import numpy as np

from stock_fetcher import tw_db
from stock_fetcher.cancellation import ProgressReporter
from stock_fetcher.tw_market import (
    _compute_multi_day_factors,
    _compute_extended_factors,
    SCREENER_CONFIG,
)
from .config import (
    UPPER_BARRIER_PCT,
    LOWER_BARRIER_PCT,
    MAX_HOLDING_DAYS,
    BENCHMARK_SYMBOL,
    WARM_UP_DAYS,
    MIN_TRAIN_DAYS,
    MIN_VOLUME,
    TIER_THRESHOLDS,
    LGBM_PARAMS,
    MODEL_PATH,
    META_PATH,
    CALIBRATOR_PATH,
    ENABLE_CALIBRATION,
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
        "trust_net_5d_norm": stock.get("trust_net_5d_norm"),
        "foreign_net_5d_norm": stock.get("foreign_net_5d_norm"),
        "inst_volume_ratio": stock.get("inst_volume_ratio"),
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
            from stock_fetcher.indicators import stochastic_kd
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

    # 法人籌碼去量綱化：除以 5 日總成交量，保留方向性
    # 單位校正：institutional_trading 數值單位為「股」，daily_prices.volume 單位為「張」
    # 需把法人數據除以 1000 換算成張後才能與成交量同單位比較
    avg_vol = result.get("avg_vol_5d")
    if avg_vol and avg_vol > 0:
        total_vol_5d = avg_vol * 5
        fnet_lots = (result.get("foreign_net_5d") or 0) / 1000  # 股 → 張
        tnet_lots = (result.get("trust_net_5d") or 0) / 1000
        result["foreign_net_5d_norm"] = round(fnet_lots / total_vol_5d * 100, 4)
        result["trust_net_5d_norm"] = round(tnet_lots / total_vol_5d * 100, 4)
        # inst_volume_ratio：法人關注度（不分方向，衡量法人在量能中的參與度）
        result["inst_volume_ratio"] = round((abs(fnet_lots) + abs(tnet_lots)) / total_vol_5d * 100, 4)

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

def _compute_triple_barrier_label(
    sym: str,
    buy_idx: int,
    trading_dates: list[str],
    prices: dict,
) -> int | None:
    """Triple-Barrier label：往前掃描 MAX_HOLDING_DAYS 個交易日。

    Returns:
        1 if upper barrier hit first（intraday high reach +UPPER_BARRIER_PCT%）
        0 if lower barrier hit first OR time barrier expires
        None if insufficient data
    """
    if buy_idx >= len(trading_dates):
        return None

    buy_date = trading_dates[buy_idx]
    sym_prices = prices.get(sym, {})
    buy_data = sym_prices.get(buy_date)
    if not buy_data or not buy_data.get("open") or buy_data["open"] <= 0:
        return None

    buy_price = buy_data["open"]
    upper_price = buy_price * (1 + UPPER_BARRIER_PCT / 100)
    lower_price = buy_price * (1 + LOWER_BARRIER_PCT / 100)

    end_idx = min(buy_idx + MAX_HOLDING_DAYS, len(trading_dates))

    for i in range(buy_idx, end_idx):
        d = trading_dates[i]
        day_data = sym_prices.get(d)
        if not day_data:
            continue
        high = day_data.get("high")
        low = day_data.get("low")
        if high is None or low is None:
            continue

        # 若同日上下軌都被觸及，保守視為先觸下軌（避免高估）
        if low <= lower_price:
            return 0
        if high >= upper_price:
            return 1

    return 0


def _build_dataset(
    trading_dates: list[str],
    prices: dict,
    inst_data: dict,
    revenue_data: dict,
    shareholder_data: dict,
    reporter: ProgressReporter | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build feature matrix, label array (Triple-Barrier binary), and signal-date array."""
    reporter = reporter or ProgressReporter.noop()
    date_to_idx = {d: i for i, d in enumerate(trading_dates)}
    backtest_dates = trading_dates[WARM_UP_DAYS:]

    all_X: list[list[float]] = []
    all_y: list[int] = []
    sample_dates: list[str] = []

    logger.info("ML dataset: building from %d candidate dates …", len(backtest_dates))
    total_dates = len(backtest_dates)

    for i, signal_date in enumerate(backtest_dates):
        # 每個 signal_date 都 check cancel（單一 date 內含千級 symbol 迴圈，可能跑數秒）
        reporter.check_cancelled()
        if i % 5 == 0:
            reporter.update(
                (i / max(total_dates, 1)) * 100,
                f"建立樣本中 {i}/{total_dates} ({signal_date})",
            )
        signal_idx = date_to_idx[signal_date]
        buy_idx = signal_idx + 1
        if buy_idx + MAX_HOLDING_DAYS > len(trading_dates):
            break

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

            label = _compute_triple_barrier_label(sym, buy_idx, trading_dates, prices)
            if label is None:
                continue

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
    """Train a single LightGBM regression model."""
    import lightgbm as lgb

    params = {k: v for k, v in LGBM_PARAMS.items() if k != "n_estimators"}

    train_data = lgb.Dataset(
        X, label=y, feature_name=FEATURE_NAMES, free_raw_data=False,
    )
    return lgb.train(
        params,
        train_data,
        num_boost_round=LGBM_PARAMS["n_estimators"],
    )


def _compute_precision_at_top_n(
    y_true: np.ndarray, y_pred: np.ndarray, n: int = 10,
) -> float | None:
    """預測機率前 N 名中，實際 label=1（觸頂）的比例 (%)。"""
    if len(y_true) < n:
        return None
    top_idx = np.argsort(y_pred)[-n:]
    hits = (y_true[top_idx] == 1).sum()
    return round(float(hits / n) * 100, 1)


def _calibration_diagnostics(
    y_true: np.ndarray, y_prob: np.ndarray, top_pct: float = 10.0,
) -> dict:
    """回傳 Brier score 與最高 X% 預測機率區段的可靠度（預測 vs 實際）。"""
    n = len(y_true)
    brier = float(np.mean((y_prob - y_true) ** 2)) if n > 0 else None

    top_n = max(1, int(n * top_pct / 100))
    top_idx = np.argsort(y_prob)[-top_n:]
    pred_avg = float(np.mean(y_prob[top_idx])) * 100 if top_n > 0 else None
    actual_rate = float(np.mean(y_true[top_idx])) * 100 if top_n > 0 else None

    return {
        "brier": round(brier, 4) if brier is not None else None,
        f"top{int(top_pct)}pct_predicted_avg": round(pred_avg, 1) if pred_avg is not None else None,
        f"top{int(top_pct)}pct_actual_rate": round(actual_rate, 1) if actual_rate is not None else None,
        f"top{int(top_pct)}pct_n": top_n,
    }


def _fit_calibrator(y_true: np.ndarray, y_prob: np.ndarray):
    """以 OOS 預測訓練 Isotonic Regression 校準器。"""
    from sklearn.isotonic import IsotonicRegression

    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(y_prob, y_true)
    return calibrator


def train_model(*, reporter: ProgressReporter | None = None) -> dict:
    """Train LightGBM binary classifier with Walk-Forward Expanding + Purge Gap.

    1. Build dataset with Triple-Barrier labels.
    2. Walk-Forward Expanding: expanding train window, purge gap, fixed test fold.
    3. Collect OOS predictions → OOS AUC + Precision@Top10.
    4. Train final production model on all data.
    5. Save model + metadata.
    """
    from sklearn.metrics import roc_auc_score

    reporter = reporter or ProgressReporter.noop()
    reporter.update(0, "載入資料 …")
    logger.info("ML train: loading data …")
    (
        trading_dates, prices, companies,
        inst_data, revenue_data, shareholder_data,
    ) = _load_all_data()

    backtest_dates = trading_dates[WARM_UP_DAYS:]

    # 建資料集佔 5~50%
    X, y, dates_arr = _build_dataset(
        trading_dates, prices, inst_data, revenue_data, shareholder_data,
        reporter=reporter.section(0.05, 0.50),
    )

    if len(y) < WF_MIN_TRAIN_SAMPLES:
        return {"error": f"樣本不足：僅收集到 {len(y)} 筆（至少需要 {WF_MIN_TRAIN_SAMPLES} 筆）"}

    pos_rate = float(y.mean()) * 100
    logger.info(
        "ML train: %d samples, positive rate %.1f%%, %d features",
        len(y), pos_rate, X.shape[1],
    )

    # ── Walk-Forward Expanding ────────────────────────────────────────────
    unique_dates = sorted(set(dates_arr))
    n_dates = len(unique_dates)

    oos_preds = np.full(len(y), np.nan)
    fold_results = []
    fold_aucs = []

    cursor = MIN_TRAIN_DAYS
    fold_num = 0
    # 估算總 fold 數，給進度條用
    est_total_folds = max(1, (n_dates - MIN_TRAIN_DAYS - PURGE_GAP_DAYS) // max(WF_FOLD_DAYS, 1))

    while cursor + PURGE_GAP_DAYS < n_dates:
        reporter.update(
            50 + (fold_num / est_total_folds) * 40,
            f"Walk-Forward 第 {fold_num + 1}/{est_total_folds} 折 …",
        )
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
            round(float(roc_auc_score(y_test, preds)), 4)
            if len(set(y_test)) > 1 else None
        )
        fold_prec = _compute_precision_at_top_n(y_test, preds)
        fold_num += 1

        if fold_auc is not None:
            fold_aucs.append(fold_auc)

        fold_results.append({
            "fold": fold_num,
            "train_end": train_cutoff,
            "test_start": unique_dates[test_start_idx],
            "test_end": unique_dates[test_end_idx - 1],
            "train_samples": int(len(train_idx)),
            "test_samples": int(len(test_idx)),
            "test_pos_rate": round(float(y_test.mean()) * 100, 1),
            "auc": fold_auc,
            "precision_top10": fold_prec,
        })

        logger.info(
            "ML fold %d: train=%d test=%d AUC=%s P@10=%s [%s → %s]",
            fold_num, len(train_idx), len(test_idx),
            f"{fold_auc:.4f}" if fold_auc is not None else "N/A",
            f"{fold_prec:.1f}%" if fold_prec is not None else "N/A",
            unique_dates[test_start_idx], unique_dates[test_end_idx - 1],
        )

        cursor = test_end_idx

    # ── OOS 綜合指標 ─────────────────────────────────────────────────────
    oos_mask = ~np.isnan(oos_preds)
    oos_auc = None
    oos_precision_top10 = None

    if oos_mask.sum() > 0 and len(set(y[oos_mask])) > 1:
        oos_auc = round(float(roc_auc_score(y[oos_mask], oos_preds[oos_mask])), 4)
        oos_precision_top10 = _compute_precision_at_top_n(y[oos_mask], oos_preds[oos_mask])

    logger.info(
        "ML walk-forward: %d folds, OOS samples=%d, AUC=%s, P@10=%s",
        len(fold_results), int(oos_mask.sum()),
        f"{oos_auc:.4f}" if oos_auc is not None else "N/A",
        f"{oos_precision_top10:.1f}%" if oos_precision_top10 is not None else "N/A",
    )

    # ── Probability Calibration（Isotonic Regression on OOS preds） ───────
    calibration_info = {"enabled": False}
    calibrator = None
    if ENABLE_CALIBRATION and oos_mask.sum() >= 50 and len(set(y[oos_mask])) > 1:
        import joblib

        y_oos = y[oos_mask].astype(np.float64)
        p_oos = oos_preds[oos_mask]

        before = _calibration_diagnostics(y_oos, p_oos)
        calibrator = _fit_calibrator(y_oos, p_oos)
        p_oos_cal = calibrator.predict(p_oos)
        after = _calibration_diagnostics(y_oos, p_oos_cal)

        os.makedirs(os.path.dirname(CALIBRATOR_PATH), exist_ok=True)
        joblib.dump(calibrator, CALIBRATOR_PATH)

        calibration_info = {
            "enabled": True,
            "method": "isotonic",
            "fit_samples": int(oos_mask.sum()),
            "before": before,
            "after": after,
        }
        logger.info(
            "ML calibration: Brier %.4f → %.4f, Top10%% predicted %.1f%% / actual %.1f%%",
            before["brier"], after["brier"],
            after["top10pct_predicted_avg"], after["top10pct_actual_rate"],
        )

    # ── Final production model: train on ALL data ─────────────────────────
    reporter.update(92, "訓練最終模型 …")
    final_model = _train_lgbm(X, y)
    reporter.update(98, "儲存模型 …")

    y_pred_all = final_model.predict(X)
    insample_auc = (
        round(float(roc_auc_score(y, y_pred_all)), 4)
        if len(set(y)) > 1 else None
    )

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

    meta = {
        "trained_at": trading_dates[-1] if trading_dates else "",
        "model_type": "classification_triple_barrier",
        "train_period": {
            "start": backtest_dates[0] if backtest_dates else "",
            "end": backtest_dates[-1] if backtest_dates else "",
        },
        "total_samples": len(y),
        "positive_samples": int(y.sum()),
        "positive_rate": round(pos_rate, 1),
        "metrics": {
            "insample_auc": insample_auc,
            "oos_auc": oos_auc,
            "oos_precision_top10": oos_precision_top10,
        },
        "walk_forward": {
            "n_folds": len(fold_results),
            "purge_gap_days": PURGE_GAP_DAYS,
            "fold_days": WF_FOLD_DAYS,
            "min_train_samples": WF_MIN_TRAIN_SAMPLES,
            "oos_samples": int(oos_mask.sum()),
            "folds": fold_results,
        },
        "triple_barrier": {
            "upper_pct": UPPER_BARRIER_PCT,
            "lower_pct": LOWER_BARRIER_PCT,
            "max_holding_days": MAX_HOLDING_DAYS,
        },
        "feature_importance": feature_importance,
        "feature_names": FEATURE_NAMES,
        "tier_thresholds": TIER_THRESHOLDS,
        "calibration": calibration_info,
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info(
        "ML train complete: %d samples, pos_rate=%.1f%%, OOS AUC=%s, P@10=%s, saved to %s",
        len(y), pos_rate,
        f"{oos_auc:.4f}" if oos_auc is not None else "N/A",
        f"{oos_precision_top10:.1f}%" if oos_precision_top10 is not None else "N/A",
        MODEL_PATH,
    )

    return {
        "status": "ok",
        "total_samples": len(y),
        "positive_samples": int(y.sum()),
        "positive_rate": round(pos_rate, 1),
        "metrics": {
            "insample_auc": insample_auc,
            "oos_auc": oos_auc,
            "oos_precision_top10": oos_precision_top10,
        },
        "walk_forward": {
            "n_folds": len(fold_results),
            "folds": fold_results,
        },
        "feature_importance": feature_importance,
        "train_period": meta["train_period"],
        "calibration": calibration_info,
    }


# ── Prediction ──────────────────────────────────────────────────────────────

def _assign_tier(probability_pct: float) -> str:
    """Assign recommendation tier based on breakout probability (%)."""
    if probability_pct >= TIER_THRESHOLDS["high"]:
        return "high"
    if probability_pct >= TIER_THRESHOLDS["medium"]:
        return "medium"
    return "low"


def predict_today(*, reporter: ProgressReporter | None = None) -> dict:
    """Run inference on the latest snapshot using the trained model.

    Returns dict with ranked predictions (symbol, name, breakout_probability, tier, ...).
    """
    import lightgbm as lgb

    reporter = reporter or ProgressReporter.noop()
    reporter.update(0, "載入模型 …")

    if not os.path.exists(MODEL_PATH):
        return {"error": "模型尚未訓練，請先點擊「重新訓練」"}

    model = lgb.Booster(model_file=MODEL_PATH)

    meta = {}
    if os.path.exists(META_PATH):
        with open(META_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)

    calibrator = None
    if ENABLE_CALIBRATION and os.path.exists(CALIBRATOR_PATH):
        import joblib
        calibrator = joblib.load(CALIBRATOR_PATH)
        logger.info("ML predict: calibrator loaded from %s", CALIBRATOR_PATH)

    reporter.update(10, "載入資料 …")
    (
        trading_dates, prices, companies,
        inst_data, revenue_data, shareholder_data,
    ) = _load_all_data()

    if not trading_dates:
        return {"error": "無交易日資料"}

    latest_date = trading_dates[-1]
    logger.info("ML predict: running inference on %s", latest_date)
    reporter.update(30, f"對 {latest_date} 推論中 …")

    # ── Phase 1: 抽特徵（不預測） ──────────────────────────────────────────
    feature_rows: list[list[float | None]] = []
    meta_rows: list[dict] = []
    total_syms = len(prices)
    processed = 0

    for sym, date_prices in prices.items():
        processed += 1
        # 每 10 個 symbol check 一次 cancel，讓 worker 在使用者按取消後能快速釋放
        if processed % 10 == 0:
            reporter.check_cancelled()
        if processed % 50 == 0:
            reporter.update(
                30 + (processed / max(total_syms, 1)) * 60,
                f"抽特徵 {processed}/{total_syms}",
            )
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

        enriched = _enrich_stock(
            sym, history, latest_date,
            inst_data=inst_data, revenue_data=revenue_data,
            shareholder_data=shareholder_data,
        )
        feature_rows.append(_extract_features(enriched))
        company = companies.get(sym, {})
        meta_rows.append({
            "symbol": sym,
            "name": company.get("name", ""),
            "close": row.get("close", 0),
            "change_pct": row.get("change_pct", 0),
            "volume": row.get("volume", 0),
        })

    # ── Phase 2: 一次性批次推論 ────────────────────────────────────────────
    reporter.update(92, "批次推論中 …")
    predictions: list[dict] = []
    if feature_rows:
        X_all = np.array(feature_rows, dtype=np.float64)
        raw_probs = model.predict(X_all)
        if calibrator is not None:
            raw_probs = calibrator.predict(raw_probs)

        for row_meta, raw_prob in zip(meta_rows, raw_probs):
            prob_pct = float(raw_prob) * 100
            predictions.append({
                **row_meta,
                "breakout_probability": round(prob_pct, 1),
                "tier": _assign_tier(prob_pct),
            })

    reporter.update(98, "排序結果 …")
    predictions.sort(key=lambda x: x["breakout_probability"], reverse=True)

    return {
        "status": "ok",
        "signal_date": latest_date,
        "total_stocks": len(predictions),
        "top_picks": predictions[:30],
        "model_info": {
            "model_type": "classification_triple_barrier",
            "train_period": meta.get("train_period", {}),
            "total_samples": meta.get("total_samples", 0),
            "positive_rate": meta.get("positive_rate", 0),
            "metrics": meta.get("metrics", {}),
            "feature_importance": meta.get("feature_importance", []),
            "tier_thresholds": TIER_THRESHOLDS,
            "triple_barrier": meta.get("triple_barrier", {}),
            "calibration": meta.get("calibration", {}),
            "calibrated": calibrator is not None,
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
        "model_type": meta.get("model_type", "unknown"),
        "train_period": meta.get("train_period", {}),
        "total_samples": meta.get("total_samples", 0),
        "positive_rate": meta.get("positive_rate", 0),
        "metrics": meta.get("metrics", {}),
        "feature_importance": meta.get("feature_importance", []),
        "tier_thresholds": meta.get("tier_thresholds", {}),
        "triple_barrier": meta.get("triple_barrier", {}),
        "calibration": meta.get("calibration", {}),
    }
