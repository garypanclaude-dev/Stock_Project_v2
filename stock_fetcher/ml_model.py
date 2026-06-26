"""Backward-compat shim.

實作已搬至 ``stock_fetcher.ml.momentum.model``。本檔僅為向後相容，
讓既有 ``from stock_fetcher.ml_model import ...`` 的呼叫不需修改。

里程碑 4（UI 雙引擎）完成後本檔將被移除，屆時請改用：
    from stock_fetcher.ml.momentum import train_model, predict_today, get_model_status
"""
from stock_fetcher.ml.momentum.model import (  # noqa: F401
    # Public API
    train_model,
    predict_today,
    get_model_status,
    # Private helpers used by scripts/pit_backtest_6278.py
    _load_all_data,
    _build_dataset,
    _enrich_stock,
    _extract_features,
    _get_history_before,
    _assign_tier,
    _compute_triple_barrier_label,
    _train_lgbm,
    _compute_precision_at_top_n,
)
