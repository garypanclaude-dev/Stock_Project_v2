"""Backward-compat shim.

實作已搬至 ``stock_fetcher.ml.momentum.config``。本檔僅為向後相容，
讓既有 ``from stock_fetcher.ml_config import ...`` 的呼叫不需修改。

里程碑 4（UI 雙引擎）完成後本檔將被移除，屆時請改用：
    from stock_fetcher.ml.momentum.config import ...
"""
from stock_fetcher.ml.momentum.config import *  # noqa: F401,F403
from stock_fetcher.ml.momentum.config import (  # noqa: F401  re-export explicit for IDEs
    UPPER_BARRIER_PCT,
    LOWER_BARRIER_PCT,
    MAX_HOLDING_DAYS,
    BENCHMARK_SYMBOL,
    WARM_UP_DAYS,
    MIN_TRAIN_DAYS,
    MIN_VOLUME,
    TIER_THRESHOLDS,
    PURGE_GAP_DAYS,
    WF_FOLD_DAYS,
    WF_MIN_TRAIN_SAMPLES,
    LGBM_PARAMS,
    MODEL_DIR,
    MODEL_PATH,
    META_PATH,
    CALIBRATOR_PATH,
    ENABLE_CALIBRATION,
    FEATURE_NAMES,
)
