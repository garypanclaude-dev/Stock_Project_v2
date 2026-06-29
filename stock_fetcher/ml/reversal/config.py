"""Reversal (起漲) 模型參數.

里程碑 2 暫時完整複製 momentum 設定，僅模型檔路徑改名以避免兩個模型互相覆蓋。
後續里程碑會調整 Triple-Barrier、特徵子集、超參數等。
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

# ── 模型儲存路徑（與 momentum 區隔，避免互相覆蓋） ──────────────────────
# 此檔位於 stock_fetcher/ml/reversal/config.py，需上溯三層到 repo root
import os
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
MODEL_DIR = os.path.join(_REPO_ROOT, "data")
MODEL_PATH = os.path.join(MODEL_DIR, "ml_reversal.txt")
META_PATH = os.path.join(MODEL_DIR, "ml_reversal_meta.json")
CALIBRATOR_PATH = os.path.join(MODEL_DIR, "ml_reversal_calibrator.pkl")

# ── 機率校準 ──────────────────────────────────────────────────────────────
ENABLE_CALIBRATION = False

# ── 特徵清單 ─────────────────────────────────────────────────────────────
# 里程碑 3 第一步：差異化起漲型，只保留兩個與「糾結態」最直接相關的特徵
#   bb_squeeze : 布林通道帶寬收斂率（越小代表波動越壓抑、越接近爆發點）
#   tangled_ma : 均線糾結度（短中長期 MA 越貼近，代表盤整越久、力道蓄積越大）
# 後續會再加入：bb_squeeze_persistence、ma_tangle_days、量縮持續性等專屬特徵
FEATURE_NAMES = [
    "bb_squeeze",
    "tangled_ma",
]
