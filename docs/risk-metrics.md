# 風險指標系統 (Risk Metrics)

> 版本：1.2
> 最後更新：2026-06-10
> v1.1：新增「警示燈號」(B7 整合) — KD 高檔死叉 / OBV 看空背離 / 均線空頭排列
> v1.2：警示燈號加第 4 類「近期看空反轉型態」(B8 整合)

## 概述

本系統與「綜合投資評分」並列：
- **綜合投資評分** = 機會評估「這支股票值不值得買？」
- **風險指標** = 風險評估「買了之後最壞會虧多少、何時該停損？」

**設計原則**：
- 純函式計算，不依賴外部 API（連 Gemini 都不用），失敗風險極低
- 不納入綜合評分公式，避免「機會分」與「風險分」混為一談導致雙重懲罰
- 提供四種獨立的停損停利方法，使用者可交叉驗證

**包含四大內容**：
1. **歷史波動率 (HV, Historical Volatility)** — 衡量股價波動程度
2. **最大回撤 (MDD, Maximum Drawdown)** — 衡量最壞情境下的虧損上限
3. **停損停利建議** — 四種主流方法並列
4. **警示燈號 (v1.1)** — 從技術指標偵測風險訊號（不影響數字，僅標注）

---

## Part 1：歷史波動率 (HV)

### 計算公式

```
日對數報酬 r_i = ln(P_i / P_{i-1})
日波動率   σ_d = std(r) over the past N days
年化波動率 HV  = σ_d × √252 × 100%
```

> **為什麼用對數報酬而非簡單報酬？**
> 對數報酬具備時間可加性，且符合常用的幾何布朗運動假設，是金融計量的標準作法。

### 採用視窗

| 視窗 | 名稱 | 用途 |
|------|------|------|
| **20 日** | 短期波動率 | 反映近期市場情緒，主要顯示指標 |
| **60 日** | 中期波動率 | 比較長期穩定度，輔助參考 |

### 樣本充足性

`HV_MIN_SAMPLES = 20`。樣本不足時回傳 `None`，前端顯示「資料不足」。

| Period | 交易日 ≈ | 20日 HV | 60日 HV |
|--------|---------|---------|---------|
| 1M | ~21 | ✅ | ❌ 資料不足 |
| 3M | ~63 | ✅ | ✅ |
| 6M / 1Y / YTD | ≥126 | ✅ | ✅ |

### 等級對照

| HV 年化 | key | label | color | 適用操作 |
|---------|-----|-------|-------|---------|
| < 20% | `low` | 低波動 | `#22c55e` 綠 | 適合長線、價值投資、退休配置 |
| 20–40% | `medium` | 中波動 | `#f59e0b` 黃 | 一般操作區間，技術分析有效 |
| 40–60% | `high` | 高波動 | `#f97316` 橘 | 短線操作為主，需嚴設停損 |
| > 60% | `extreme` | 極高波動 | `#ef4444` 紅 | 投機區間，建議減碼或避開 |

### 投資視角解讀

**HV 不是越低越好**：低波動 = 穩定 = 也較難有暴利機會。HV 應與**個人風險承受度**配對：

- 退休族 / 保守投資 → 偏好 HV < 25% 的標的（如台積電 2330、台塑 1301）
- 一般成長股 → 25–45% 區間（多數科技股）
- 主題股 / 趨勢股 → 45% 以上（生技、AI 新創）

---

## Part 2：最大回撤 (MDD)

### 計算邏輯

```
peak_i = max(P_0 .. P_i)
drawdown_i = (P_i - peak_i) / peak_i
MDD = min(drawdown_0 .. drawdown_n)
```

### 回傳欄位

| 欄位 | 說明 |
|------|------|
| `mdd_pct` | 最大回撤百分比（負值） |
| `peak_date` / `peak_price` | 最高點日期與價格 |
| `trough_date` / `trough_price` | 最低點日期與價格 |
| `recovered` | 是否已回到前高（true/false） |
| `recovery_days` | 從低點回到前高所需交易日（未回復則 null） |
| `current_drawdown_pct` | 目前距離歷史高點的回撤 |

### 警戒線

`MDD_WARNING_THRESHOLD = -30.0`。超過此值（即 MDD < -30%）視為**值得重新評估持有理由**的警示，前端會以紅色顯示。

| MDD 區間 | 顏色 | 投資意義 |
|---------|------|---------|
| > -15% | 綠 `#22c55e` | 一般回檔範圍 |
| -15% ~ -30% | 黃 `#f59e0b` | 顯著修正，需注意趨勢是否改變 |
| < -30% | 紅 `#ef4444` | 嚴重套牢區，重新審視基本面 |

### 投資視角解讀

- MDD 對應的是**真實心理壓力**。理論上分數 80 的好股票若 MDD -40%，多數人會在最低點賣出。
- 與 HV 互相驗證：HV 低但 MDD 大 → 可能是長期溫水煮青蛙的衰退
- 與 Recovery Days 一起看：MDD -25% 但 30 天就回復 = 短暫修正；MDD -25% 且 200 天未回復 = 趨勢改變

---

## Part 3：停損停利建議（四法對照）

### 為什麼提供四種方法？

每種方法背後的哲學不同，**並列對照可以交叉驗證**。當四個方法算出的停損價落在接近區間（例如 ±2%），代表這個價位特別具參考意義。

### 方法 1：ATR 法（量化派標準）

```
ATR(14) = Wilder-smoothed True Range over 14 days
True Range = max(high - low, |high - prev_close|, |low - prev_close|)

停損 = current - stop_mult × ATR
停利 = current + target_mult × ATR
```

**三種風險偏好**（從 `risk_config.ATR_PROFILES`）：

| Profile | stop_mult | target_mult | R:R | 適合 |
|---------|-----------|-------------|-----|------|
| `conservative` 保守 | 2.0 | 3.0 | 1 : 1.5 | 短線、低風險容忍、震盪市 |
| `standard` 標準 | 2.5 | 5.0 | 1 : 2.0 | 中線、一般操作 |
| `aggressive` 積極 | 3.0 | 6.0 | 1 : 2.0 | 長線、趨勢明確、高容忍 |

**優點**：自動適應股票波動特性，波動大的股票停損自動拉寬，避免被噪音掃出場。
**缺點**：對突發新聞事件造成的暴漲跌反應較慢。

### 方法 2：固定百分比法

```
停損 = current × (1 - 8%) = current × 0.92
停利 = current × (1 + 15%) = current × 1.15
```

設定值來自 `risk_config.FIXED_PCT`。R:R = 1 : 1.875。

**優點**：直覺、容易執行、心理界線明確。
**缺點**：不考慮個股波動。對台積電可能太鬆，對小型股可能太緊。
**適合**：剛開始學投資、偏好簡單規則的人。

### 方法 3：布林通道法

```
停損 = Bollinger 下軌（最新值）
停利 = Bollinger 上軌（最新值）
```

直接重用 `indicators.bollinger` 的計算結果，不另外計算。

**特殊處理**：當前價已突破上軌時，停利改為 `current + (上軌 - 下軌)` 以維持 R:R 意義（避免停利價低於當前價的怪現象）。

**優點**：基於統計分布（2σ 涵蓋 95% 機率），有理論基礎。
**缺點**：通道隨時在動，停損點不是固定的，需頻繁調整。
**適合**：震盪盤、技術分析派、波段操作。

### 方法 4：波段支撐壓力法

```
停損 = 近 60 個交易日的最低點 (swing low)
停利 = 近 60 個交易日的最高點 (swing high)
```

設定值來自 `risk_config.SWING_LOOKBACK = 60`。

**優點**：尊重市場結構，過往低點往往是心理防線（跌破代表趨勢轉空）。
**缺點**：需要近期有明顯波段，盤整盤效果差；停損點可能離當前價很遠。
**適合**：趨勢明確的股票、看圖派、波段交易。

## Part 4：警示燈號 (v1.1 新增)

### 設計理念

警示燈號**不影響任何數字**（HV、MDD、停損停利價都不變），純粹是從技術指標自動偵測「值得提醒的風險訊號」，以紅 / 橘色 banner 顯示在風險卡頂部。

**為什麼分開？** 風險指標的核心數字（HV、MDD）反映「歷史已發生的事實」，警示則是「當前需要注意的潛在訊號」。性質不同，分開呈現避免使用者把警示當作數字判讀。

### 四類警示

| 警示 type | 觸發條件 | 嚴重度 | 顏色 |
|---------|---------|-------|------|
| `kd_death_cross` | K 線在 **K > 70** 的高檔由上向下穿越 D 線 | warn | 🟠 橘 |
| `obv_bearish_divergence` | 近 10 日股價上漲但 OBV 下跌（量價背離） | warn | 🟠 橘 |
| `ma_bearish_alignment` | MA5 < MA10 < MA20 < MA60 且 收盤 < MA5 | danger | 🔴 紅 |
| `bearish_pattern` (v1.2) | 近 5 日 K 線出現流星 / 夜星 / 看空吞噬 | warn | 🟠 橘 |

### 設定（`risk_config.py`）

```python
WARN_KD_DEATH_CROSS_THRESHOLD = 70    # K 在 >70 才視為「高檔」死叉
WARN_OBV_DIVERGENCE_LOOKBACK = 10     # 比對 10 日斜率
WARN_BEARISH_PATTERN_LOOKBACK = 5     # 近 5 日看空型態觸發警示 (v1.2)
```

### 警示模板（API 回傳格式）

```json
{
  "type": "kd_death_cross",
  "severity": "warn",
  "label": "KD 高檔死亡交叉",
  "description": "K 線在高檔（>70）由上向下穿越 D 線，短期回調機率提高。",
  "color": "#f97316"
}
```

API 回傳的 `risk.warnings` 是這種物件的陣列，沒觸發則為空陣列 `[]`。

### 使用建議

| 看到警示 | 怎麼做 |
|---------|--------|
| KD 高檔死叉 | 短線：考慮減碼或設更緊的停損；長線：搭配其他指標確認 |
| OBV 看空背離 | 注意上漲是否為「無量上攻」，背離常是大跌前兆 |
| 均線空頭排列 | 趨勢已轉空，應停損停利規則務必嚴格執行，避免攤平 |

---

### 風報比（R:R Ratio）

```
風報比 = 報酬金額 / 風險金額 = (停利 - 當前價) / (當前價 - 停損)
```

| R:R | 顏色 | 投資意義 |
|-----|------|---------|
| ≥ 2.0 | 綠 | 划算，潛在獲利是潛在虧損的 2 倍以上 |
| 1.0–2.0 | 黃 | 一般，可接受但不算優秀 |
| < 1.0 | 紅 | 不划算，潛在獲利低於潛在虧損 |

**鐵則**：長期勝率 50% 的策略，只要 R:R ≥ 1.5 就能獲利。寧可放棄低 R:R 的訊號。

---

## 策略速查（白話版）

### 看到風險指標卡，腦袋裡的決策樹

```
1. 先看 HV 等級
   ├─ 低波動 → 適合長期持有，可放鬆停損
   ├─ 中波動 → 標準操作
   └─ 高/極高波動 → 嚴設停損，部位減半

2. 再看 MDD
   ├─ < -15% → 一般，繼續看
   ├─ -15% ~ -30% → 注意，是否仍處於回檔？
   └─ < -30% → 警示！重新評估基本面

3. 看四法停損停利對照
   ├─ 四個停損價聚集（差距 < 3%） → 此價位是強支撐
   ├─ 四個停損價分散 → 市場結構不清楚，謹慎
   └─ R:R 平均 < 1.5 → 此時進場 CP 值低，等待回檔
```

### 常見情境

**情境 A：穩健派想進場大型權值股**
- 看 HV 是否 < 30%
- 看 MDD 是否已從低點回復（recovered = true）
- 用 ATR 標準法 / 固定百分比法的停損價作參考
- 避開 R:R < 1.5 的進場時機

**情境 B：短線想追動能股**
- HV 高沒關係，但要看 ATR
- 停損用 **ATR 保守法**（2x），避免被掃出場
- 停利用 **波段壓力位**，目標明確

**情境 C：手上股票套牢想救援**
- 看 `current_drawdown_pct`，距離高點多少
- 看 MDD 的 `recovered`：如果歷史上類似 MDD 都有回復，可能還有機會
- 若 MDD < -30% 且 200+ 天未回復，考慮認輸換股

### 常見誤區

| 誤區 | 正解 |
|------|------|
| 「HV 高 = 不能買」 | 短線交易者反而需要高 HV 才有波動空間 |
| 「停損設 -8% 是鐵則」 | 對波動大的股票太緊，會被掃出場 |
| 「MDD 大代表爛公司」 | 2020 年好公司 MDD 都 -40%，看回復能力更重要 |
| 「四法選一個就好」 | 並列對照才能驗證價位的可信度 |

---

## API 規格

### 整合位置

風險指標已內嵌於 `/api/stock-insights` 回應，作為新欄位 `risk`。

### 回應格式

```json
{
  "symbol": "AAPL",
  "period": "3M",
  "score": { ... },
  "indicators": { ... },
  "risk": {
    "volatility": {
      "hv_20d": 28.45,
      "hv_60d": 32.10,
      "level": {
        "key": "medium",
        "label": "中波動",
        "color": "#f59e0b"
      }
    },
    "drawdown": {
      "mdd_pct": -23.45,
      "peak_date": "2026-01-15",
      "trough_date": "2026-03-08",
      "peak_price": 195.32,
      "trough_price": 149.50,
      "recovered": false,
      "recovery_days": null,
      "current_drawdown_pct": -5.20
    },
    "suggestions": {
      "current_price": 312.50,
      "atr_14": 6.8421,
      "methods": {
        "atr_standard": {
          "label": "ATR (標準)",
          "stop_loss": 295.40,
          "take_profit": 346.70,
          "risk_pct": -5.47,
          "reward_pct": 10.94,
          "rr_ratio": 2.0
        },
        "atr_conservative": { ... },
        "atr_aggressive": { ... },
        "fixed_pct": {
          "label": "固定百分比",
          "stop_loss": 287.50,
          "take_profit": 359.38,
          "risk_pct": -8.0,
          "reward_pct": 15.0,
          "rr_ratio": 1.87
        },
        "bollinger": {
          "label": "布林通道",
          "stop_loss": 298.60,
          "take_profit": 325.40,
          "risk_pct": -4.45,
          "reward_pct": 4.13,
          "rr_ratio": 0.93
        },
        "swing": {
          "label": "波段支撐壓力",
          "stop_loss": 292.10,
          "take_profit": 328.50,
          "risk_pct": -6.53,
          "reward_pct": 5.12,
          "rr_ratio": 0.78
        }
      }
    }
  }
}
```

### 樣本不足時的回傳

- `hv_60d` 樣本不足 → `null`
- 全部不足（kline < 2）→ 所有數值 null、methods = `{}`
- 部分方法不可用（如布林尚未 warm-up）→ 該方法回傳 stop/target 為 null

前端負責處理 null 顯示為「資料不足」或「–」。

---

## 設定檔 (`stock_fetcher/risk_config.py`)

所有可調參數集中於此，避免 hard-code：

```python
# Historical Volatility
HV_WINDOWS = (20, 60)
TRADING_DAYS_PER_YEAR = 252
HV_MIN_SAMPLES = 20
HV_LEVELS = [
    (20.0,   "low",     "低波動",   "#22c55e"),
    (40.0,   "medium",  "中波動",   "#f59e0b"),
    (60.0,   "high",    "高波動",   "#f97316"),
    (9999.0, "extreme", "極高波動", "#ef4444"),
]

# Maximum Drawdown
MDD_WARNING_THRESHOLD = -30.0

# ATR
ATR_PERIOD = 14

# Stop-loss / Take-profit
ATR_PROFILES = {
    "conservative": {"stop_mult": 2.0, "target_mult": 3.0, "label": "保守"},
    "standard":     {"stop_mult": 2.5, "target_mult": 5.0, "label": "標準"},
    "aggressive":   {"stop_mult": 3.0, "target_mult": 6.0, "label": "積極"},
}
FIXED_PCT = {"stop_pct": 0.08, "target_pct": 0.15}
SWING_LOOKBACK = 60
```

### 調整建議

若日後想微調參數，建議**先測試一支股票的回測表現再全面套用**：

| 想調的事 | 改哪裡 |
|---------|--------|
| ATR 法停損太緊 | 提高 `ATR_PROFILES[*].stop_mult` |
| 固定百分比不符合台股偏好 | 改 `FIXED_PCT.stop_pct`（台股短線常用 7%，當沖用 3%） |
| 波段法看太遠 | 降低 `SWING_LOOKBACK`（例如改 30） |
| HV 等級閾值不符合台股 | 改 `HV_LEVELS` 各上界 |

---

## 預計改動檔案（v1.0 實作）

```
新增：
  stock_fetcher/risk.py            ← 純函式計算
  stock_fetcher/risk_config.py     ← 閾值與權重設定
  docs/risk-metrics.md             ← 本文件

修改：
  stock_fetcher/__init__.py        ← 匯出 compute_risk_metrics
  app.py                           ← /api/stock-insights 加入 risk 欄位
  mock_data.py                     ← Mock 回應加入 risk 欄位
  frontend/index.html              ← 新增「風險指標卡」UI 與 renderRisk()

不動：
  stock_fetcher/scoring.py         ← 風險不納入評分公式
  stock_fetcher/indicators.py      ← 技術指標保持單一職責
  docs/composite-score.md          ← 評分邏輯沒變
  docs/peer-comparison.md          ← 比較邏輯沒變
```

---

## 未來擴展（暫不實作）

| 想法 | 是否做 | 理由 |
|------|--------|------|
| Sharpe / Sortino Ratio | ❌ | 需無風險利率假設，對個股意義有限，做投資組合分析時再加 |
| 歷史 HV 趨勢圖（sparkline） | ⏸ 待評估 | 視 v1.0 上線後的使用者回饋 |
| Trailing Stop（移動停損） | ❌ | 需動態調整邏輯，現有四法已涵蓋主流需求 |
| 整合到綜合評分 | ❌ | 「機會」與「風險」分開呈現更清晰 |
| 整合到 `strategies.md` 速查手冊 | 🔜 | 未來建立 strategies.md 時統一收錄，本文件保留作工程參考 |

---

## 免責聲明

> 以上僅為量化分析參考，不構成投資建議，投資決策請自行評估風險。
> 風險指標與停損停利建議基於歷史數據與規則模型，無法預測未來市場走勢。
> 停損停利為機械式提示，實際操作應結合個人風險承受度、資金規模、操作週期綜合判斷。
