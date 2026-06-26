"""
ML model configuration constants.

All tuneable hyperparameters for the LightGBM prediction model.
"""

# ── Label 定義：Triple-Barrier Method ─────────────────────────────────────
# 從買入日起，往前掃描 MAX_HOLDING_DAYS 個交易日
#   intraday high 觸及 +UPPER_BARRIER_PCT % → Y=1（先觸頂 = 起漲）
#   intraday low  觸及  LOWER_BARRIER_PCT % → Y=0（先觸底 = 失敗）
#   時間到期皆未觸及 → Y=0（震盪）
UPPER_BARRIER_PCT = 10.0            # 上軌（賺錢波段觸發點）
LOWER_BARRIER_PCT = -5.0            # 下軌（停損觸發點）
MAX_HOLDING_DAYS = 10               # 時間軌（最長持有天數）
BENCHMARK_SYMBOL = "0050.TW"        # 仍保留作為其他用途（不參與 label）

# ── 訓練參數 ──────────────────────────────────────────────────────────────
WARM_UP_DAYS = 60                   # 篩選器暖機天數（與 backtest_config 一致；BB60/MA60 對齊）
MIN_TRAIN_DAYS = 60                 # 最少訓練交易日數
MIN_VOLUME = 500                    # 最低成交量門檻（張）

# ── 推論分級門檻（機率） ─────────────────────────────────────────────────
TIER_THRESHOLDS = {
    "high": 70.0,                   # 預測起漲機率 ≥ 70% → 強力推薦
    "medium": 50.0,                 # 預測起漲機率 ≥ 50% → 中等推薦
}

# ── Walk-Forward Expanding 參數 ──────────────────────────────────────────
PURGE_GAP_DAYS = 10                 # 訓練/測試安全間隔（= MAX_HOLDING_DAYS，防止 label 洩漏）
WF_FOLD_DAYS = 10                   # 每個測試 fold 的交易日數
WF_MIN_TRAIN_SAMPLES = 100          # 每個 fold 最少訓練樣本數

# ── LightGBM 超參數 ──────────────────────────────────────────────────────
LGBM_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "is_unbalance": True,           # 自動處理類別不平衡（起漲為稀有事件）
    "verbosity": -1,
    "n_estimators": 300,
    "learning_rate": 0.03,
    "max_depth": 4,
    "num_leaves": 15,
    "min_child_samples": 100,
    "subsample": 0.7,
    "colsample_bytree": 0.7,
    "reg_alpha": 0.5,
    "reg_lambda": 3.0,
}

# ── 模型儲存路徑 ──────────────────────────────────────────────────────────
import os
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODEL_PATH = os.path.join(MODEL_DIR, "ml_model.txt")
META_PATH = os.path.join(MODEL_DIR, "ml_model_meta.json")
CALIBRATOR_PATH = os.path.join(MODEL_DIR, "ml_calibrator.pkl")

# ── 機率校準 ──────────────────────────────────────────────────────────────
# is_unbalance=True 會系統性拉高預測機率，使用 Isotonic Regression 校正
# 校準器以 walk-forward OOS 預測為訓練資料
ENABLE_CALIBRATION = True

# ── 特徵清單（原始值，非百分位） ──────────────────────────────────────────
FEATURE_NAMES = [
    # 技術面 — 連續值
    "bb_squeeze",
    "volume_breakout",
    "box_breakout",
    "squeeze_volume",
    "avwap_dev",
    "near_breakout",
    "price_position",
    "tangled_ma",
    "close_to_ma200_ratio",
    "liquidity_sweep",
    "obv_divergence",
    "volume_contraction",
    # 技術面 — KD 拆解為連續值
    "k_value",
    "d_value",
    "k_minus_d",
    # 籌碼面（法人買超已正規化 = 5日淨買超 / 5日總成交量 × 100%）
    "trust_net_5d_norm",
    "foreign_net_5d_norm",
    "inst_volume_ratio",
    "trust_streak",
    "foreign_streak",
    # 基本面
    "revenue_yoy",
    "revenue_mom",
]
