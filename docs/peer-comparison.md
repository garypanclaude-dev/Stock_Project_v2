# P1-5 同業比較、自選股比較、潛力股篩選

> 版本：1.0
> 最後更新：2026-06-05

## 概述

本功能包含三個互相關聯的比較維度：

1. **同業比較**：查看個股時自動帶出同產業競爭對手，橫向比較指標 + 相對走勢圖（含大盤）
2. **自選股比較**：Watchlist 內所有股票 + 大盤指數放在同一張圖比較
3. **潛力股篩選**：從全台灣上市櫃 ~2,500 支股票中，用多因子模型篩選 Top 20

---

## 功能 A：同業比較

### 同業映射表

維護一份主要股票的 peers mapping：

```
AAPL → [MSFT, GOOGL, META]         # 科技巨頭
TSLA → [F, GM, RIVN]               # 車廠
NVDA → [AMD, INTC, AVGO]           # 半導體
2330.TW → [2454.TW, 3711.TW, 2303.TW]  # 台灣半導體
```

未命中的股票：從 yfinance 的 `sector` 欄位找同 sector 的知名股票。

### 比較指標

| 指標 | 來源 |
|------|------|
| P/E (TTM) | fundamentals.valuation |
| ROE | fundamentals.profitability |
| Profit Margin | fundamentals.profitability |
| 市值 (Market Cap) | latest_quote |
| 1M / 3M 漲跌幅 | kline 計算 |
| 殖利率 | fundamentals.dividend |
| Beta | fundamentals.summary |

### 相對走勢圖

- 起點標準化為 100%（第一天收盤價 = 100）
- 同業前三名 + 大盤指數（美股 SPY、台股 0050.TW）
- 使用 Chart.js 折線圖，不同顏色區分

### API

```
GET /api/peer-comparison?ticker=AAPL&period=3M&mock=true

Response:
{
  "symbol": "AAPL",
  "peers": ["MSFT", "GOOGL", "META"],
  "index": "SPY",
  "comparison_table": [
    { "symbol": "AAPL", "pe": 33.2, "roe": 157, "margin": 26.3, "mcap": 4.4e12, "return_1m": 5.2, "return_3m": 12.1, "yield": 0.49, "beta": 1.24, "is_target": true },
    { "symbol": "MSFT", ... },
    ...
  ],
  "relative_performance": {
    "labels": ["03-01", "03-02", ...],
    "series": {
      "AAPL": [100, 101.2, 103.5, ...],
      "MSFT": [100, 100.8, 102.1, ...],
      "GOOGL": [100, 99.5, 101.2, ...],
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
| 股票來源 | 自動帶出同產業 peers | 使用者的 Watchlist |
| 數量 | 3-4 支 + 大盤 | Watchlist 全部 + 大盤 |
| 大盤選擇 | 依主要市場（SPY/0050.TW） | 依 Watchlist 組成自動判斷 |

### API

```
GET /api/watchlist-comparison?tickers=AAPL,TSLA,NVDA&period=3M&mock=true

Response:
{
  "tickers": ["AAPL", "TSLA", "NVDA"],
  "index": "SPY",
  "comparison_table": [ ... ],  // 同上格式
  "relative_performance": { ... }  // 同上格式
}
```

---

## 功能 C：潛力股篩選

### 資料來源

| API | URL | 回傳內容 |
|-----|-----|---------|
| TWSE 每日收盤 | `https://www.twse.com.tw/exchangeReport/MI_INDEX` | 全上市股票收盤價、漲跌、成交量 |
| TWSE 本益比 | `https://www.twse.com.tw/exchangeReport/BWIBBU_d` | P/E、殖利率、P/B |
| TPEX 每日收盤 | `https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php` | 全上櫃股票收盤價 |
| TPEX 本益比 | `https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/pera_result.php` | P/E、殖利率、P/B |

### 前置篩選（排除不適合的股票）

- 排除日均成交量 < 500 張
- 排除特別股、ETF、權證
- 排除近 5 日無交易紀錄

### 多因子評分模型

| 因子 | 權重 | 計算方式 |
|------|------|---------|
| 動能 (Momentum) | 30% | 近 1 月漲幅排名百分位 |
| 價值 (Value) | 20% | P/E 百分位（越低越好，反轉計算） |
| 品質 (Quality) | 25% | 殖利率排名百分位 |
| 規模溢酬 (Size) | 10% | 市值百分位 |
| 波動 (Volatility) | 15% | 近 1 月振幅排名（越低越好） |

> 每個因子都轉換為 0-100 的百分位排名後加權合成。

### 資料新鮮度檢查

```python
def is_stale(snapshot_date: str) -> bool:
    """
    判斷快照是否過期：
    - 交易日 14:00 後：快照日期必須是今天
    - 交易日 14:00 前：快照日期必須是上一個交易日
    - 週末/假日：快照日期必須是最近的交易日
    """
```

### 儲存策略

- 檔案路徑：`data/tw_market_snapshot.json`
- 格式：`{ "date": "2026-06-04", "updated_at": "...", "stocks": [...] }`
- 啟動時載入記憶體，背景更新不阻塞請求

### API

```
GET /api/stock-screener?mock=true

Response:
{
  "last_updated": "2026-06-04T14:30:00",
  "total_stocks": 2487,
  "top_picks": [
    {
      "rank": 1,
      "symbol": "2330.TW",
      "name": "台積電",
      "score": 87,
      "close": 2380,
      "change_pct": 1.2,
      "pe": 32.3,
      "yield": 1.02,
      "volume": 45678,
      "factors": { "momentum": 92, "value": 45, "quality": 95, "size": 99, "volatility": 78 }
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

## 預計改動檔案

```
新增：
  docs/peer-comparison.md              ← 本文件
  stock_fetcher/peers.py               ← 同業映射 + 比較資料
  stock_fetcher/tw_market.py           ← TWSE/TPEX 抓取 + 篩選引擎
  data/                                ← 快照目錄（程式自動產生）

修改：
  stock_fetcher/__init__.py            ← 匯出新模組
  app.py                               ← 三個新 endpoint
  mock_data.py                         ← 三個功能的 mock 資料
  frontend/index.html                  ← 比較 UI + 篩選 UI
```
