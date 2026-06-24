# P1-5 同業比較、自選股比較、潛力股篩選

> 版本：7.0
> 最後更新：2026-06-23
> v3.3：潛力股篩選 B7 整合 — 8 → 10 因子，新增 KD、OBV；ma_trend 升級為 4 態（含糾結判定）
> v3.4：潛力股篩選 B8 整合 — 10 → 11 因子，新增 K 線型態因子
> v3.5：潛力股篩選 B9 整合 — 11 → 13 因子，新增殖利率穩定度 + PE 60 日歷史分位
> v3.6：修正對照表 — 綜合評分技術面更新為 6 指標（含 KD/OBV）、量能欄位更正
> v4.0：新增歷史回測功能 — 前瞻報酬率分析；DB 擴充至 250 個交易日
> v5.0：**篩選器全面改版 B11** — 13 因子 → 10 因子。IC 分析確認舊因子為反向指標，新設計以籌碼面+基本面+技術面三維均衡取代。新增 3 張 DB 表（institutional_trading / monthly_revenue / shareholder_concentration）。每日更新整合。
> v6.0：**篩選器 v5 因子擴充** — 10 因子 → 16 因子。新增 MA200 前置過濾、BB squeeze、成交量突破、箱型突破、Anchored VWAP、Liquidity Sweep、法人吃貨比、外資/投信連買天數。移除 revenue_acceleration（資料不足）及 ma_convergence（與 BB squeeze 重疊）。權重重分配：技術面 40% / 籌碼面 40% / 基本面 20%。
> v7.0：**篩選器經理人實戰調校** — 16 因子 → 15 因子。KD 從絕對值評分改為黃金交叉偵測（kd_cross）。新增均線糾結因子（tangled_ma）。移除 pe_percentile，以 revenue_mom 取代。投信權重調高（主動型基金主力）、外資調低（避免權值股干擾）。權重重分配：技術面 50% / 籌碼面 35% / 基本面 15%。

## 概述

本功能包含三個互相關聯的比較維度：

1. **同業比較**：查看個股時自動帶出同產業競爭對手，橫向比較指標 + 相對走勢圖（含大盤）
2. **自選股比較**：Watchlist 內所有股票 + 大盤指數放在同一張圖比較
3. **潛力股篩選**：從全台灣上市櫃 ~1,970 支股票中，用 **15 因子**（技術面 50% + 籌碼面 35% + 基本面 15%）百分位排名選出 Top 20
4. **歷史回測**：以過去 1 年資料驗證篩選器信號品質（前瞻報酬率分析）

---

## 四套評分系統的差異與適用場景

本專案中有四個地方涉及「評分」或「比較」，各自的設計目的、評分方式、資料來源不同：

### 功能定位

| | 潛力股篩選 | 綜合投資評分 |
|---|---|---|
| **角色** | **選股池** — 從全市場篩選短線/波段候選標的 | **個股評估** — 深入分析特定股票是否適合進場 |
| **操作流程** | 先用篩選器從 ~1,970 支中找出 Top 20 | 再對感興趣的個股做綜合評分，決定是否交易 |
| **時間定位** | 短線至波段（1-20 日） | 短線至波段（依技術面訊號進出） |

> **使用順序**：篩選器 → 找到候選 → 綜合評分 → 決定是否進場

### 對照表

| | 綜合投資評分 | 同業比較 | 自選股比較 | 潛力股篩選 |
|---|---|---|---|---|
| **解決什麼問題** | 這支股票現在適合進場嗎？ | 跟同產業比是強是弱？ | 我的持股哪支最好？ | 全市場哪支最值得關注？ |
| **比較對象** | 單一股票 vs 絕對標準 | 同產業 3-4 支 | Watchlist 全部 | 全台 ~1,970 支 |
| **評分方式** | 絕對閾值（P/E<15=75 分） | 簡化基本面分數 | 簡化基本面分數 | 相對百分位排名 |
| **技術面** | ✅ RSI, MACD, 均線, 布林, KD, OBV | ❌ | ❌ | ✅ BB squeeze, 量突破, 箱型突破, 量能擠壓, AVWAP, 均線糾結, KD 交叉, Liquidity Sweep |
| **基本面** | ✅ P/E, ROE, 營收, Margin, 殖利率 | ✅ P/E, ROE, Margin, 殖利率 | ✅ 同左 | ✅ 營收年增率, 營收月增率 |
| **籌碼面** | ❌ | ❌ | ❌ | ✅ 投信/外資淨買超, 法人吃貨比, 投信/外資連買天數, 大戶持股 |
| **風險** | ✅ Beta | ✅ Beta | ✅ Beta | ❌（已移除低波動因子） |
| **AI 情緒** | ✅ Gemini 分析 | ❌ | ❌ | ❌ |
| **資料來源** | yfinance + Gemini | yfinance | yfinance | **SQLite（250 個交易日 TWSE/TPEX 歷史）** |
| **規格文件** | `docs/composite-score.md` | 本文件 | 本文件 | 本文件 |

### 為什麼不統一？

1. **資料來源不同**：潛力股篩選用 TWSE/TPEX 官方 API（批次快速），個股分析用 yfinance（細節多）。兩套 API 回傳的欄位不同，無法用同一套閾值。

2. **使用場景不同**：
   - 看單一股票時：「P/E 32 是高還是低？」→ 用**絕對閾值**有意義
   - 從 1,970 支中篩選時：「誰的 P/E 最低？」→ 用**百分位排名**才公平
   - 跟同業比時：「P/E 33 在科技股中算貴嗎？」→ 用**橫向比較**最直觀

3. **效能限制**：對 1,970 支股票全部計算 RSI/MACD 需要 yfinance 逐支抓歷史，耗時數小時，不實際。

---

## 功能 A：同業比較

### 同業匹配邏輯（三層 fallback）

```
Step 1: 查硬編碼映射表 PEER_MAP（stock_fetcher/peers.py）
        → 命中？回傳（如 AAPL → [MSFT, GOOGL, META]）
        → 注意：僅美股有硬編碼，台股一律走 Step 2

Step 2: 查 SQLite companies 表的 industry 欄位（台股限定）
        → 從 daily_prices 找同 industry 的股票
        → 按最新成交量排序，取前 3 名（排除自己）
        → 例：廣達(2382) = 電腦及週邊設備業 → [仁寶(2324), 宏碁(2353), 英業達(2356)]

Step 3: 都沒命中（如冷門外股）
        → 回傳空陣列，前端只顯示該股 + 大盤指數
```

### 硬編碼映射表（僅美股）

```
# 美股（沒有產業分類資料源，需手動維護）
AAPL  → [MSFT, GOOGL, META]       # 科技巨頭
TSLA  → [F, GM, RIVN]             # 車廠
NVDA  → [AMD, INTC, AVGO]         # 半導體
AMZN  → [MSFT, GOOGL, AAPL]       # 科技平台
```

> **設計變更（v3.2）**：台股的硬編碼項目（2330、2454、2881 等共 6 組）已移除。
> 既然 TWSE/TPEX 產業分類能自動覆蓋所有 ~1,970 支台股，硬編碼是重複的程式碼。
> 移除後台股 100% 透過 Step 2 處理，行為一致、無需手動維護。

### 比較指標

| 指標 | 來源 | 比較用途 |
|------|------|---------|
| **基本面分數** | `scoring.py::_score_fundamental` | 快速判斷誰的基本面最好 |
| P/E (TTM) | yfinance info | 估值比較 |
| ROE | yfinance info | 獲利效率 |
| Profit Margin | yfinance info | 成本控制 |
| 市值 (Market Cap) | yfinance info | 規模量級 |
| 區間報酬率 | kline 首尾價差 | 股價表現 |
| 殖利率 | yfinance info | 配息能力 |
| Beta | yfinance info | 波動風險 |

### 基本面分數計算（同業/自選股共用）

同業比較和自選股比較中的「評分」欄位，使用 `scoring.py` 的基本面子分數計算：

```python
score = _score_fundamental(fundamentals)
# 包含：P/E (25%) + ROE (20%) + 營收趨勢 (25%) + Margin (15%) + 殖利率 (15%)
```

> 注意：這裡不計算技術面和情緒面分數，因為比較表中沒有足夠的資料（RSI/MACD/催化劑）。
> 這是一個「簡化版」分數，只反映基本面強弱，與綜合投資評分中的「基本面子維度」一致。

### 相對走勢圖

- 起點標準化為 100%（第一天收盤價 = 100）
- 同業 + 大盤指數（美股 SPY、台股 0050.TW）
- 使用 Chart.js 折線圖，大盤用虛線區分

### 大盤指數選擇邏輯

| 股票市場 | 大盤指數 |
|---------|---------|
| `.TW` 台灣 | 0050.TW（元大台灣50 ETF） |
| `.SS` 上海 | 000300.SS（滬深300） |
| `.SZ` 深圳 | 000300.SS（滬深300） |
| 其他（美股等） | SPY（S&P 500 ETF） |

### API

```
GET /api/peer-comparison?ticker=AAPL&period=3M&mock=true

Response:
{
  "symbol": "AAPL",
  "peers": ["MSFT", "GOOGL", "META"],
  "index": "SPY",
  "comparison_table": [
    {
      "symbol": "AAPL",
      "score": 64,
      "pe": 33.2, "roe": 157, "margin": 26.3,
      "mcap": 4.4e12, "return_period": 12.1,
      "yield": 0.49, "beta": 1.24,
      "is_target": true, "is_index": false
    },
    ...
  ],
  "relative_performance": {
    "labels": ["03-01", "03-02", ...],
    "series": {
      "AAPL": [100, 101.2, 103.5, ...],
      "MSFT": [100, 100.8, 102.1, ...],
      "SPY": [100, 100.3, 100.8, ...]
    }
  }
}
```

---

## 功能 B：自選股比較

### 與同業比較的差異

| | 同業比較 | 自選股比較 |
|---|---------|----------|
| 股票來源 | 自動匹配同產業 peers | 使用者的 Watchlist |
| 數量 | 3-4 支 + 大盤 | Watchlist 全部 + 大盤 |
| 大盤選擇 | 依目標股票市場 | 依 Watchlist 多數股票市場 |
| 評分欄位 | ✅ 基本面分數 | ✅ 基本面分數 |
| 用途 | 跟同業比是否領先 | 自選股之間誰最強 |

### API

```
GET /api/watchlist-comparison?tickers=AAPL,TSLA,NVDA&period=3M&mock=true

Response: （格式同同業比較）
```

---

## 功能 C：潛力股篩選

### 資料儲存架構

**從 v3.0 開始改用 SQLite 累積歷史資料**（取代原本的單日 JSON 快照）。

```
data/tw_market.db
├── companies                 (1,979 筆：TWSE 1,090 + TPEX 889)
│   └── symbol, name, industry, market, updated_at
├── daily_prices              (~490,000 筆，250 個交易日 × ~1,970 支)
│   └── symbol, date, open, high, low, close, change_pct, volume, pe, pb, yield_pct
├── institutional_trading     (v5.0 新增：法人進出)
│   └── symbol, date, foreign_net, trust_net, dealer_net, total_net
├── monthly_revenue           (v5.0 新增：月營收)
│   └── symbol, year_month, revenue, revenue_yoy, revenue_mom
└── shareholder_concentration (v5.0 新增：TDCC 集保大戶持股)
    └── symbol, date, large_holder_pct, total_holders
```

**為什麼換成 SQLite？**
- 單日資料無法計算多日技術指標（如 5d/20d 動能、MA5/MA20、量能比）
- SQL 查詢效率高，可用索引加速 peer lookup 和 screener ranking
- 單一檔案管理方便，內建 Python 不需額外服務

### 資料來源

| API | 用途 | 頻率 | 涵蓋 |
|-----|------|------|------|
| TWSE MI_INDEX | 上市股票每日收盤、成交量 | 每日 | ~1,090 支 |
| TWSE BWIBBU_d | 上市股票 P/E、殖利率、P/B | 每日 | ~1,090 支 |
| TPEX otc_quotes | 上櫃股票每日收盤 | 每日 | ~880 支 |
| TPEX peratio | 上櫃股票 P/E、殖利率、P/B | 每日 | ~880 支 |
| TWSE openapi t187ap03_L | 上市公司產業分類 | 偶爾 | 1,090 公司 |
| TPEX openapi mopsfin_t187ap03_O | 上櫃公司產業分類 | 偶爾 | 889 公司 |
| **TWSE T86** (v5.0) | 上市三大法人買賣超 | 每日 | ~1,090 支 |
| **TPEX 3itrade** (v5.0) | 上櫃三大法人買賣超 | 每日 | ~880 支 |
| **TWSE/TPEX opendata 營收** (v5.0) | 月營收（當期） | 每月 | ~1,960 支 |
| **TDCC opendata 1-5** (v5.0) | 集保戶股權分散表 | 每週五 | ~2,946 支 |

> **註**：兩個市場合計約 1,970 支股票，已涵蓋台股主要交易標的。
> 興櫃股票（約 300 支）目前不在範圍內。
> 月營收僅能取得最新期資料（MOPS 歷史查詢受 WAF 封鎖），需透過每月累積建立歷史。

### 前置篩選（排除不適合的股票）

- 排除日均成交量 < 500 張（流動性不足）
- 排除代號非 4 碼純數字（特別股、ETF、權證）
- 排除收盤價為 0 或無成交紀錄
- **排除收盤價 < MA200**（長期處於空頭趨勢的股票）。歷史不足 200 日者不排除。

### 15 因子評分模型（v7.0）

> **改版背景**：v7.0 以經理人實戰操盤邏輯調校因子與權重。核心策略定位為「捕捉波動壓縮後帶量突破的起漲股」。KD 從絕對值評分改為黃金交叉偵測（轉折初速），新增均線糾結因子（籌碼沉澱訊號）。移除 pe_percentile（非必要干擾），以 revenue_mom 取代（營收雙增催化劑）。投信權重調高（中小型波段主力），外資調低（避免權值股干擾）。權重調整為技術面 50% / 籌碼面 35% / 基本面 15%。

| 維度 | 因子 | 權重 | 計算方式 | 排名方向 | 設計理由 |
|------|------|------|---------|---------|---------|
| **技術面 50%** | bb_squeeze | 8% | 布林帶寬在 120 日內的百分位 | 越低越好（反轉） | 波動壓縮是起漲的前戲 |
| | volume_breakout | 8% | today_vol / avg_vol_20d | 越大越好 | 帶量突破才是真突破，防範假突破 |
| | box_breakout | 7% | close ≥ 60d_high 時 100/range%，否則 0 | 越大越好 | 帶量出箱型，最容易發動長波段 |
| | squeeze_volume | 6% | max(0, (σ20d-σ5d)/σ20d) × 量比 | 越大越好 | 窒息量後首條補量紅棒的起漲訊號 |
| | avwap_dev | 5% | (close - AVWAP) / AVWAP × 100，錨定 60 日 swing low | 越高越好 | 站穩主力平均成本線之上，建立持股信心 |
| | breakout | 5% | (收盤 - 20 日最高) / 20 日最高 × 100 | 越高越好 | 確保短線動能已經全面啟動 |
| | tangled_ma | 5% | MA5/10/20/60 spread = (max-min)/mean | 越低越好（反轉） | 均線糾結 = 籌碼沉澱、無獲利了結賣壓 |
| | kd_cross | 4% | K(9,3,3) 黃金交叉：K 上穿 D 且 K<50 高分 | 越高越好 | 低點附近的黃金交叉，定位在轉折初速 |
| | liquidity_sweep | 2% | low < 5d_min_low 且 close 收回時的回升幅度 | 越大越好 | 洗盤後直接 V 轉拉出的個股加分 |
| **籌碼面 35%** | trust_net_5d | 10% | 近 5 日投信淨買超張數加總 | 越多越好 | 投信認養（主動型基金拉抬）是中小型波段主力 |
| | inst_volume_ratio | 6% | (\|外資5d\|+\|投信5d\|) / (avg_vol_5d×5) × 100 | 越大越好 | 法人控盤而非散戶當沖跟風 |
| | foreign_net_5d | 5% | 近 5 日外資淨買超張數加總 | 越多越好 | 外資為輔助，避免權值股干擾波段篩選 |
| | trust_streak | 5% | 投信連續淨買天數（負值=連賣） | 越大越好 | 連買 3~5 天以上代表經理人建倉決心 |
| | large_holder_change | 5% | 最近一週 vs 前一週大戶持股比例差 | 越大越好 | 集保資料有遞延性，當參考加分項 |
| | foreign_streak | 4% | 外資連續淨買天數（負值=連賣） | 越大越好 | 外資連買往往代表波段鎖股 |
| **基本面 15%** | revenue_yoy | 10% | 最新月營收年增率 (%) | 越高越好 | 確保有實質業績支撐，非單純投機題材 |
| | revenue_mom | 5% | 最新月營收月增率 (%) | 越高越好 | 營收雙增（YoY+MoM）是起漲最強催化劑 |

> **計分方式**：`Score = Σ (百分位排名_i × 權重_i)`，分數範圍 0-100，取 Top 20。
>
> **百分位排名**：每個因子都轉換為 0-100 cross-sectional 百分位。例如 trust_net_5d 排名 88 = 該股投信買超金額超過 88% 的股票。
>
> **kd_cross 為絕對評分**：K<30 且黃金交叉 → 100 分；K<50 且交叉 → 80 分；K≥50 且交叉 → 50 分；無交叉 → 0 分。再做百分位排名。

### IC 驗證結果

> v7.0 新增因子（kd_cross, tangled_ma, revenue_mom）的 IC 尚需實際回測驗證。以下為既有因子的參考值。

| 因子 | 5D Mean IC | 20D Mean IC | 訊號強度 |
|------|-----------|------------|---------|
| revenue_yoy | +0.076 | +0.107 | ★★★ 極強 |
| squeeze_volume | +0.003 | +0.003 | 邊緣 |

### 資料可用性注意事項

| 因子 | 資料來源 | 限制 |
|------|---------|------|
| foreign_net_5d / trust_net_5d | TWSE T86 + TPEX 3itrade | 需 5 個交易日的法人資料 |
| foreign_streak / trust_streak | 同上 | 需 20 個交易日歷史以計算連續天數 |
| inst_volume_ratio | 法人資料 + daily_prices | 需法人資料 + 5 日成交量 |
| large_holder_change | TDCC opendata 1-5 | 每週五公布，需至少 2 週資料 |
| revenue_yoy / revenue_mom | TWSE/TPEX opendata | 僅能取得最新期，需每月累積 |
| bb_squeeze | daily_prices 表 | 需 20 日以上收盤價（理想 120 日） |
| box_breakout / avwap_dev | daily_prices 表 | 需 60 日 OHLCV |
| tangled_ma | daily_prices 表 | 需 60 日收盤價以計算 MA60 |
| kd_cross | daily_prices 表 | 需 9 日以上 OHLC |
| MA200 前置過濾 | daily_prices 表 | 需 200 日收盤價，不足者不排除 |

### kd_cross 因子細節

KD(9,3,3) 黃金交叉偵測：前一期 K < D 且本期 K ≥ D 為交叉成立。依交叉時 K 值位置給予絕對評分後做百分位排名：

| 條件 | 絕對分數 |
|------|---------|
| 黃金交叉且 K < 30 | 100（超賣區交叉，最強轉折） |
| 黃金交叉且 K < 50 | 80（低位交叉） |
| 黃金交叉且 K ≥ 50 | 50（高位交叉，參考性較低） |
| 無黃金交叉 | 0 |

### 與綜合投資評分的差異

| | 綜合投資評分 | 潛力股篩選 |
|---|---|---|
| **評分方式** | 絕對閾值 | 百分位排名 |
| **例子** | P/E < 15 → 75 分（不管別人） | 投信淨買超排名前 10% → 90 分（跟全市場比） |
| **技術面** | RSI, MACD, 均線, 布林, KD, OBV | BB squeeze, 量突破, 箱型突破, 量能擠壓, AVWAP, 突破, 均線糾結, KD 交叉, Liquidity Sweep |
| **基本面** | P/E, ROE, 營收趨勢, Margin, 殖利率 | 營收年增率, 營收月增率 |
| **籌碼面** | ❌ | ✅ 投信/外資淨買超, 法人吃貨比, 投信/外資連買天數, 大戶持股 |
| **前置過濾** | ❌ | ✅ MA200 年線過濾（排除長期空頭） |
| **適用場景** | 評估個股是否適合進場交易 | 從全市場篩選短線/波段候選標的 |

### API

```
GET /api/stock-screener?mock=true

Response:
{
  "last_updated": "2026-06-17T00:00:00",
  "total_stocks": 1973,
  "top_picks": [
    {
      "rank": 1,
      "symbol": "8131.TW",
      "name": "福懋科",
      "score": 74,
      "close": 54.60,
      "change_pct": 1.30,
      "pe": 12.8,
      "yield_pct": 4.1,
      "volume": 2345,
      "factors": {
        "bb_squeeze":           72,
        "volume_breakout":      65,
        "box_breakout":         88,
        "squeeze_volume":       81,
        "avwap_dev":            55,
        "breakout":             99,
        "tangled_ma":           68,
        "kd_cross":             80,
        "liquidity_sweep":      0,
        "trust_net_5d":         66,
        "inst_volume_ratio":    73,
        "foreign_net_5d":       88,
        "trust_streak":         45,
        "large_holder_change":  94,
        "foreign_streak":       60,
        "revenue_yoy":          78,
        "revenue_mom":          62
      }
    },
    ...
  ]
}
```

### 前端呈現

- Top 20 排名表格，含排名、代號、名稱、評分、收盤價、漲跌幅、P/E、殖利率
- 點擊任一行可直接切換到該股的完整分析頁面
- 底部免責聲明：「以上僅為量化篩選結果，不構成投資建議，投資決策請自行評估風險。」

---

## 功能 D：歷史回測（v4.0 新增）

### 目的

驗證篩選器的實際選股效果：**如果過去一年每天都照 Top 5 操作，到底賺不賺錢？**

與 B2（事件回顧）不同：B2 是「特定事件後股價怎麼走」，歷史回測是「篩選器整體策略的績效驗證」。

### 模擬邏輯

```
每個交易日 D（有持倉 slot 空出時）：
  1. 用「截至 D 日」的歷史資料跑 10 因子篩選器 → 取 Top 5
  2. D+1 以開盤價買入（等權重分配）
  3. 每支持股獨立判定出場：
     a. 停利：當日 High ≥ 買入價 × 1.03 → 以買入價 × 1.03 結算
     b. 停損：當日 Low  ≤ 買入價 × 0.95 → 以買入價 × 0.95 結算
     c. 同日觸發兩者 → 停損優先（保守假設）
     d. 持有滿 5 日 → 以第 5 日收盤價強制出場
  4. 空出的 slot → 用最新篩選結果補位（排除仍在持倉的股票）
  5. 追蹤每日組合淨值 + 對照基準（0050.TW buy-and-hold）
```

### 出場參數

| 參數 | 值 | 設計理由 |
|------|-----|---------|
| 停利 | +3% | 短線操作，落袋為安 |
| 停損 | -5% | 給足夠空間避免被日內波動震出，風報比 1:1.67 |
| 最長持有 | 5 交易日 | 與篩選器短線定位一致 |
| 持倉數 | 5 | 集中持股提高精準度，Top 5 品質較 Top 20 更高 |
| 基準 | 0050.TW | 台股大盤 ETF，同期 buy-and-hold |

> 所有參數可在 `stock_fetcher/backtest_config.py` 調整。

### 避免前視偏差（Look-Ahead Bias）

回測的最大風險是不小心用到「未來資料」，導致績效虛高。本系統的防範：

| 項目 | 做法 |
|------|------|
| 篩選時間點 | 呼叫 `get_history_before(symbol, target_date, days=65)` 取「截至 target_date」的資料，絕不使用之後的資料 |
| 買入時間點 | 篩選日 D 選出 Top 5，D+1 開盤價買入（非 D 日收盤價） |
| 出場判定 | 用 D+1 起的 OHLC 判定，不使用篩選當天的價格 |

### 輸出格式

#### 1. 交易明細表（trades）

| 欄位 | 說明 |
|------|------|
| entry_date | 買入日期 |
| exit_date | 賣出日期 |
| symbol | 股票代號 |
| name | 股票名稱 |
| entry_price | 買入價（開盤價） |
| exit_price | 賣出價 |
| return_pct | 報酬率 (%) |
| exit_reason | `take_profit` / `stop_loss` / `max_hold` |
| hold_days | 持有天數 |

#### 2. 統計摘要（summary）

| 指標 | 說明 |
|------|------|
| total_return | 總報酬率 (%) |
| annualized_return | 年化報酬率 (%) |
| benchmark_return | 同期 0050.TW 報酬率 (%) |
| total_trades | 總交易次數 |
| win_rate | 勝率 (%) |
| avg_win | 平均獲利 (%) |
| avg_loss | 平均虧損 (%) |
| profit_factor | 獲利因子（總獲利 / 總虧損） |
| max_drawdown | 最大回撤 (%) |
| sharpe_ratio | Sharpe Ratio（年化，假設無風險利率 1.5%） |
| avg_hold_days | 平均持有天數 |

#### 3. 權益曲線（daily_equity）

每日一筆：`{date, equity, benchmark}`

- equity：組合淨值（起始 = 1,000,000）
- benchmark：0050.TW 同起始日 buy-and-hold 淨值
- 用 Chart.js 繪製雙線圖

### API

```
GET /api/stock-screener/backtest?mock=true

Response:
{
  "period": {"start": "2025-07-01", "end": "2026-06-09"},
  "config": {
    "top_n": 5,
    "take_profit": 0.03,
    "stop_loss": -0.05,
    "max_hold_days": 5,
    "initial_capital": 1000000
  },
  "summary": {
    "total_return": 12.35,
    "annualized_return": 12.85,
    "benchmark_return": 8.21,
    "total_trades": 186,
    "win_rate": 58.6,
    "avg_win": 2.87,
    "avg_loss": -3.42,
    "profit_factor": 1.45,
    "max_drawdown": -8.72,
    "sharpe_ratio": 1.23,
    "avg_hold_days": 3.1
  },
  "daily_equity": [
    {"date": "2025-07-01", "equity": 1000000, "benchmark": 1000000},
    ...
  ],
  "trades": [
    {
      "entry_date": "2025-07-02",
      "exit_date": "2025-07-04",
      "symbol": "2330.TW",
      "name": "台積電",
      "entry_price": 985.0,
      "exit_price": 1014.55,
      "return_pct": 3.0,
      "exit_reason": "take_profit",
      "hold_days": 2
    },
    ...
  ]
}
```

### 限制與注意事項

1. **交易成本未計入**：未扣手續費（買 0.1425%）、證交稅（賣 0.3%）。實際報酬約需再扣 0.4-0.5% / 每筆。
2. **流動性假設**：假設 Top 5 都能以開盤價成交，實際可能有滑價。已用前置篩選（日均量 ≥ 500 張）降低此風險。
3. **生存者偏差**：DB 只有目前仍在交易的股票，已下市股票不在回測範圍。
4. **同日停利停損**：以停損優先是保守假設，實際走勢可能先觸停利再跌破停損，或反之。日線層級無法區分日內先後順序。

---

## 資料管理（v3.0 新增）

### 工具一：`scripts/update_tw_history.py`

CLI 工具，負責維護 SQLite 中的 TW 市場歷史資料。**v5.0 起每次執行會同時更新法人買賣超、月營收、TDCC 集保資料。**

### 使用模式

| 模式 | 指令 | 用途 |
|------|------|------|
| **預設增量** | `python scripts/update_tw_history.py` | 找 DB 最新日期 → 抓到今天，含擴充資料 |
| **完整檢查** | `python scripts/update_tw_history.py --full-check` | 比對最近 250 天的交易日，補齊任何位置的漏洞 |
| **首次建構** | `python scripts/update_tw_history.py --backfill 250` | 回填最近 250 個交易日（DB 空時自動觸發） |
| **單一日期** | `python scripts/update_tw_history.py --date 2026-06-03` | 補抓特定日期 |
| **日期範圍** | `python scripts/update_tw_history.py --from 2026-05-01 --to 2026-05-31` | 補抓指定範圍 |
| **預覽模式** | `python scripts/update_tw_history.py --dry-run` | 顯示會抓哪些日期，不實際執行 |
| **跳過公司更新** | `python scripts/update_tw_history.py --skip-companies` | 只更新價格，不重抓產業分類 |
| **跳過擴充資料** | `python scripts/update_tw_history.py --skip-extended` | 只更新價格，跳過法人/營收/TDCC |

### 工具二：`scripts/backfill_new_data.py`（v5.0 新增）

專門回填法人買賣超和 TDCC 集保歷史資料，用於首次建構 v5.0 資料。

| 模式 | 指令 | 用途 |
|------|------|------|
| **全部回填** | `python scripts/backfill_new_data.py` | 法人 + TDCC 全部回填 |
| **僅法人** | `python scripts/backfill_new_data.py --inst-only` | 只回填法人進出 |
| **僅 TDCC** | `python scripts/backfill_new_data.py --tdcc-only` | 只回填集保資料 |
| **預覽** | `python scripts/backfill_new_data.py --dry-run` | 顯示計畫，不執行 |

### 自動化處理

- **週末/假日**：自動跳過（API 回傳空資料則判定為非交易日）
- **盤中執行**：當天還沒收盤的話跳過今天
- **API 暫時失敗**：記錄失敗日期、繼續抓下一天，最後報告
- **錯誤日重抓**：使用者可手動 `--date YYYY-MM-DD` 補單日

### 效能

| 場景 | API 呼叫次數 | 預估時間（含 0.5s 延遲） |
|------|-----------|----------------------|
| 首次建構（250 天） | 250 × 4 價格 + 2 公司 | 約 15-20 分鐘 |
| 首次回填擴充資料 | ~236 法人 + ~51 TDCC + 1 營收 | 約 5-8 分鐘 |
| 日常增量（1 天） | 4 價格 + 2 法人 + 1 營收 + 1 TDCC | < 10 秒 |
| 補一週漏洞（5 天） | 20 價格 + 10 法人 | 約 20 秒 |
| 完整檢查（無漏洞） | 0 次（只查 DB） | < 1 秒 |

> 每日抓取：4 價格 API + 2 法人 API（TWSE T86 + TPEX 3itrade）+ 1 營收 API + 1 TDCC API（週五）
> 公司分類 2 個 API：TWSE openapi + TPEX openapi（通常只在第一次跑時抓）

### 建議排程

| 場景 | 建議 |
|------|------|
| 開發/個人使用 | 每天手動跑一次 `python scripts/update_tw_history.py` |
| Windows 排程 | 用 Task Scheduler 設每天 14:30 自動執行 |
| Linux/雲端 | 用 cron `30 14 * * 1-5 python /path/to/update_tw_history.py` |

### 資料生命週期

- **保留期間**：最近 250 個交易日（約 1 年）
- 需要 1 年歷史以支援回測功能（歷史篩選 + 模擬交易）
- **清理工具**：可用 `tw_db.prune_older_than()` 手動清理舊資料

---

## 免責聲明

> 以上僅為量化篩選與分析結果，不構成投資建議，投資決策請自行評估風險。
> 評分系統基於歷史數據與規則模型，無法預測未來市場走勢。
