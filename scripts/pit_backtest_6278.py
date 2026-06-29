"""Point-in-time backtest: train as of 2026-04-10, check if 6278.TW is picked.

Skips walk-forward (single train on all eligible data prior to test date) for speed.
"""
from __future__ import annotations

import json
import logging
import os
import numpy as np

from stock_fetcher.ml.momentum.model import (
    _load_all_data, _build_dataset, _enrich_stock, _extract_features,
    _get_history_before, _assign_tier,
)
from stock_fetcher.ml.momentum.config import (
    FEATURE_NAMES, WARM_UP_DAYS, MAX_HOLDING_DAYS, BENCHMARK_SYMBOL,
    MIN_VOLUME, LGBM_PARAMS,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

TEST_DATE = "2026-04-10"
TARGET_SYMBOL = "6278.TW"


def main():
    import lightgbm as lgb

    logger.info("Loading data ...")
    (trading_dates, prices, companies, inst_data, revenue_data, shareholder_data) = _load_all_data()

    if TEST_DATE not in trading_dates:
        raise SystemExit(f"{TEST_DATE} not a trading day in DB")

    test_idx = trading_dates.index(TEST_DATE)
    logger.info(f"Test date {TEST_DATE} at idx {test_idx}/{len(trading_dates)}")

    # Truncate to data <= test date
    truncated_dates = trading_dates[: test_idx + 1]
    # Purge: training samples must complete label before test buy day (test_idx + 1)
    # Sample at signal_idx i has label window [i+1, i+MAX_HOLDING_DAYS]
    # Require i + MAX_HOLDING_DAYS < test_idx + 1  =>  i <= test_idx - MAX_HOLDING_DAYS
    # We rely on len(truncated_dates) = test_idx + 1, so signal_idx up to
    # test_idx - MAX_HOLDING_DAYS is OK. To force this, drop last MAX_HOLDING_DAYS
    # days from truncated_dates so _build_dataset stops there.
    train_dates = truncated_dates[: -MAX_HOLDING_DAYS]
    logger.info(f"Train dates: {train_dates[0]} ~ {train_dates[-1]} ({len(train_dates)} days)")

    logger.info("Building training dataset ...")
    X, y, dates_arr = _build_dataset(
        train_dates, prices, inst_data, revenue_data, shareholder_data,
    )
    pos_rate = y.mean() * 100 if len(y) else 0
    logger.info(f"Train samples: {len(y):,}  positive_rate: {pos_rate:.2f}%")

    logger.info("Training LightGBM ...")
    train_set = lgb.Dataset(X, label=y, feature_name=FEATURE_NAMES, free_raw_data=False)
    model = lgb.train(LGBM_PARAMS, train_set)

    # Inference for TEST_DATE
    logger.info(f"Running inference for signal_date = {TEST_DATE} ...")
    predictions = []
    target_features = None

    # For inference, we need history up to and including TEST_DATE
    # Use the original full trading_dates context but cap history fetch by TEST_DATE
    for sym, dp in prices.items():
        if sym == BENCHMARK_SYMBOL or TEST_DATE not in dp:
            continue
        row = dp[TEST_DATE]
        if (row.get("volume") or 0) < MIN_VOLUME:
            continue

        # History prior to and including TEST_DATE
        hist = _get_history_before(prices, sym, TEST_DATE, 200)
        if len(hist) < 60:
            continue

        enriched = _enrich_stock(
            sym, hist, TEST_DATE,
            inst_data=inst_data, revenue_data=revenue_data,
            shareholder_data=shareholder_data,
        )
        feats = _extract_features(enriched)
        X_pred = np.array([feats], dtype=np.float64)
        prob = float(model.predict(X_pred)[0]) * 100

        company = companies.get(sym, {})
        predictions.append({
            "symbol": sym,
            "name": company.get("name", ""),
            "prob": prob,
            "close": row.get("close", 0),
            "change_pct": row.get("change_pct", 0),
            "ma200": enriched.get("ma200"),
            "bb_sq": enriched.get("bb_squeeze"),
            "vol_brk": enriched.get("volume_breakout"),
            "box_brk": enriched.get("box_breakout"),
            "tangled": enriched.get("tangled_ma"),
            "kd_cross": enriched.get("kd_cross"),
            "trust_streak": enriched.get("trust_streak"),
        })

        if sym == TARGET_SYMBOL:
            target_features = enriched

    predictions.sort(key=lambda x: -x["prob"])
    logger.info(f"Total predictions: {len(predictions)}")

    print()
    print("=" * 90)
    print(f"TOP 30 PICKS on {TEST_DATE} (point-in-time model)")
    print("=" * 90)
    print(f'{"#":>3} {"sym":10} {"prob":>6} {"close":>8} {"Δ%":>6} {"bb_sq":>6} {"vol_brk":>7} {"box_brk":>7} {"tangled":>8} {"kd":>4} name')
    for i, p in enumerate(predictions[:30], 1):
        marker = " ← TARGET" if p["symbol"] == TARGET_SYMBOL else ""
        bb = f'{p["bb_sq"]:.0f}' if p["bb_sq"] is not None else "-"
        vb = f'{p["vol_brk"]:.2f}' if p["vol_brk"] is not None else "-"
        bk = f'{p["box_brk"]:.1f}' if p["box_brk"] is not None else "-"
        tg = f'{p["tangled"]:.4f}' if p["tangled"] is not None else "-"
        kd = f'{p["kd_cross"]:.0f}' if p["kd_cross"] is not None else "-"
        print(f'{i:>3} {p["symbol"]:10} {p["prob"]:>5.1f}% {p["close"]:>8.2f} {p["change_pct"]:>+5.1f}% {bb:>6} {vb:>7} {bk:>7} {tg:>8} {kd:>4} {p["name"]}{marker}')

    # Find target rank
    target_rank = next((i for i, p in enumerate(predictions, 1) if p["symbol"] == TARGET_SYMBOL), None)
    print()
    print("=" * 90)
    if target_rank:
        target_pred = next(p for p in predictions if p["symbol"] == TARGET_SYMBOL)
        print(f'TARGET 6278.TW (台表科)')
        print(f'  Rank:        {target_rank} / {len(predictions)}')
        print(f'  Probability: {target_pred["prob"]:.2f}%')
        print(f'  Close 4/10:  {target_pred["close"]:.2f}  (Δ {target_pred["change_pct"]:+.1f}%)')
        print(f'  Top decile?  {"YES" if target_rank <= len(predictions) * 0.1 else "NO"}')
        print(f'  Top 30?      {"YES" if target_rank <= 30 else "NO"}')
        print(f'  Top 10?      {"YES" if target_rank <= 10 else "NO"}')
        print()
        print(f'Feature snapshot for 6278.TW:')
        for fn in FEATURE_NAMES:
            v = target_features.get(fn) if target_features else None
            v_str = f"{v:.4f}" if isinstance(v, (int, float)) else str(v)
            print(f'  {fn:25s} = {v_str}')
    else:
        print(f"TARGET {TARGET_SYMBOL} NOT FOUND in predictions (insufficient history or other filter)")

    # Compute ground-truth label for 6278 at signal=4/10
    print()
    print("=" * 90)
    print("Actual outcome (forward 10 days from 2026-04-13 open):")
    buy_idx = test_idx + 1
    if buy_idx < len(trading_dates):
        buy_date = trading_dates[buy_idx]
        buy_data = prices[TARGET_SYMBOL].get(buy_date)
        if buy_data and buy_data.get("open"):
            buy_price = buy_data["open"]
            upper = buy_price * 1.10
            lower = buy_price * 0.95
            print(f'  Buy date: {buy_date}  open: {buy_price:.2f}')
            print(f'  Upper barrier (+10%): {upper:.2f}')
            print(f'  Lower barrier (-5%):  {lower:.2f}')
            for i in range(buy_idx, min(buy_idx + MAX_HOLDING_DAYS, len(trading_dates))):
                d = trading_dates[i]
                dd = prices[TARGET_SYMBOL].get(d)
                if not dd: continue
                h, l = dd.get("high"), dd.get("low")
                hit_u = " [HIT]" if h and h >= upper else ""
                hit_l = " [HIT]" if l and l <= lower else ""
                print(f'    {d}  H={h:>6.1f} L={l:>6.1f}  upper{hit_u}  lower{hit_l}')
                if h and h >= upper:
                    print(f'  >>> LABEL = 1 (upper barrier hit first on {d})')
                    break
                if l and l <= lower:
                    print(f'  >>> LABEL = 0 (lower barrier hit first on {d})')
                    break
            else:
                print(f'  >>> LABEL = 0 (time barrier expired, neither hit)')


if __name__ == "__main__":
    main()
