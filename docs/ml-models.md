# ML 雙引擎模型規格 (Dual-Engine ML Models)

> 版本：1.0
> 最後更新：2026-06-30
> v1.0：首次建立。記錄動能型（momentum）與反轉型（reversal）雙引擎架構，含特徵清單、Triple-Barrier label 定義、訓練流程與檔案路徑。

## 概述

篩選器採用 **雙模型並行**架構，兩個模型各自訓練、各自推論，覆蓋不同的進場情境：

| 模型 | 模組 | 設計目標 | 適用情境 |
| --- | --- | --- | --- |
| **動能型 (momentum)** | `stock_fetcher/ml/momentum/` | 抓「已啟動、追勢」的標的 | 突破型、量增追擊 |
| **反轉型 (reversal)** | `stock_fetcher/ml/reversal/` | 抓「糾結爆量起漲」的標的 | 長期盤整 + 帶量突圍的早期啟動點 |

兩個模型共用同一套 Triple-Barrier label 定義與 LightGBM 超參數，**主要差異在特徵子集**。

---

## Triple-Barrier Label 定義

兩個模型目前共用此定義：

- 從買入日起向後掃描 `MAX_HOLDING_DAYS = 10` 個交易日
- intraday high 觸及 `+UPPER_BARRIER_PCT = +10%` → `Y = 1`（先觸頂 = 起漲成功）
- intraday low 觸及 `LOWER_BARRIER_PCT = -5%` → `Y = 0`（先觸底 = 失敗）
- 時間到期皆未觸及 → `Y = 0`（震盪）

> 反轉型後續可能調整為更寬鬆的觸發門檻（如 +15%/20 日），以對應「糾結爆發」的較大波段空間，調整時須同步更新本文件。

---

## 動能型模型 (Momentum)

### 特徵清單（共 20 項）

**技術面（連續值，14 項）**
- `bb_squeeze`：布林通道帶寬收斂率
- `volume_breakout`：放量突破強度
- `box_breakout`：箱型突破
- `squeeze_volume`：壓縮 + 放量複合訊號
- `avwap_dev`：錨定 VWAP 偏離率
- `near_breakout`：接近突破點
- `price_position`：價格在區間中的相對位置
- `tangled_ma`：均線糾結度
- `liquidity_sweep`：流動性掃蕩
- `obv_divergence`：OBV 背離
- `volume_contraction`：量縮持續度
- `k_value` / `d_value` / `k_minus_d`：KD 拆解為連續值

**籌碼面（去量綱化，5 項）**
- `trust_net_5d_norm`：投信 5 日淨買超 / 5 日總成交量 × 100%
- `foreign_net_5d_norm`：外資 5 日淨買超 / 5 日總成交量 × 100%
- `inst_volume_ratio`：法人成交占比
- `trust_streak`：投信連續買超日數
- `foreign_streak`：外資連續買超日數

**基本面（2 項）**
- `revenue_yoy`：營收年增率
- `revenue_mom`：營收月增率

### 模型檔案
- `data/ml_model.txt`
- `data/ml_model_meta.json`
- `data/ml_calibrator.pkl`（v7.3 起 `ENABLE_CALIBRATION = False`，不使用）

---

## 反轉型模型 (Reversal)

> **里程碑 3：差異化起漲型** — 反轉型不該與動能型用同一套特徵，否則兩個模型輸出高度相關，雙引擎失去意義。第一步先極致精簡，只保留與「糾結態」最直接相關的特徵；後續再加入糾結持續性、量縮持續性等專屬特徵。

### 特徵清單（共 2 項，里程碑 3 第一步）

| 特徵 | 含義 |
| --- | --- |
| `bb_squeeze` | 布林通道帶寬收斂率。值越小代表波動越壓抑、越接近爆發點 |
| `tangled_ma` | 均線糾結度。短/中/長期 MA 越貼近，代表盤整越久、力道蓄積越大 |

### 規劃中的反轉型專屬特徵
- `bb_squeeze_persistence`：BB 壓縮的連續天數（不只看當下，更看持續時間）
- `ma_tangle_days`：均線糾結持續天數
- 量縮持續性指標（區別於動能型的 `volume_contraction`，更強調長期低量）

### 模型檔案（與 momentum 區隔，避免互相覆蓋）
- `data/ml_reversal.txt`
- `data/ml_reversal_meta.json`
- `data/ml_reversal_calibrator.pkl`

---

## 共用超參數

### 訓練參數
- `WARM_UP_DAYS = 60`：暖機天數（與 backtest_config 一致；對齊 BB60 / MA60）
- `MIN_TRAIN_DAYS = 60`
- `MIN_VOLUME = 500` 張

### Walk-Forward Expanding
- `PURGE_GAP_DAYS = 10`：訓練/測試安全間隔（= `MAX_HOLDING_DAYS`，防 label 洩漏）
- `WF_FOLD_DAYS = 10`：每個測試 fold 的交易日數
- `WF_MIN_TRAIN_SAMPLES = 100`

### LightGBM 超參數
```python
{
    "objective": "binary",
    "metric": "auc",
    "is_unbalance": True,          # 起漲為稀有事件，自動處理類別不平衡
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
```

### 推論分級門檻
| Tier | 機率閾值 | 意義 |
| --- | --- | --- |
| high | ≥ 70% | 強力推薦 |
| medium | ≥ 50% | 中等推薦 |
| low | < 50% | 不推薦 |

---

## 變更管理規則

> 任何對下列項目的調整，都必須**同步更新本文件**並與程式碼變更**包含在同一個 commit**：
> - 特徵清單（新增、刪除、改名）
> - Triple-Barrier 參數（upper / lower / holding days）
> - LightGBM 超參數
> - Walk-Forward 設定
> - 推論分級門檻
> - 模型檔案路徑

文件需標註版本號與最後更新日期，並在版本註記中描述調整原因與預期影響。
