"""
ML model configuration constants.

All tuneable hyperparameters for the LightGBM prediction model.
"""

# ── Label 定義 ──────────────────────────────────────────────────────────────
FORWARD_DAYS = 5                    # 預測未來 N 個交易日的報酬
EXCESS_RETURN_THRESHOLD = 2.0       # 超額報酬門檻 (%)：stock_return > bench_return + threshold → label=1
BENCHMARK_SYMBOL = "0050.TW"

# ── 訓練參數 ──────────────────────────────────────────────────────────────
WARM_UP_DAYS = 120                  # 篩選器暖機天數（與 backtest_config 一致）
MIN_TRAIN_DAYS = 60                 # 最少訓練天數
EXTREME_RETURN_CAP = 30.0           # 排除 |return| > 30% 的極端值（除權息/異常交易）
MIN_VOLUME = 500                    # 最低成交量門檻（張）

# ── LightGBM 超參數 ──────────────────────────────────────────────────────
LGBM_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "verbosity": -1,
    "n_estimators": 300,
    "learning_rate": 0.05,
    "max_depth": 5,
    "num_leaves": 31,
    "min_child_samples": 50,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
}

# ── 模型儲存路徑 ──────────────────────────────────────────────────────────
import os
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODEL_PATH = os.path.join(MODEL_DIR, "ml_model.txt")
META_PATH = os.path.join(MODEL_DIR, "ml_model_meta.json")

# ── 特徵清單（原始值，非百分位） ──────────────────────────────────────────
FEATURE_NAMES = [
    # 技術面 — 連續值
    "bb_squeeze",
    "volume_breakout",
    "box_breakout",
    "squeeze_volume",
    "avwap_dev",
    "breakout",
    "tangled_ma",
    "liquidity_sweep",
    # 技術面 — KD 拆解為連續值
    "k_value",
    "d_value",
    "k_minus_d",
    # 籌碼面
    "trust_net_5d",
    "inst_volume_ratio",
    "foreign_net_5d",
    "trust_streak",
    "large_holder_change",
    "foreign_streak",
    # 基本面
    "revenue_yoy",
    "revenue_mom",
]
