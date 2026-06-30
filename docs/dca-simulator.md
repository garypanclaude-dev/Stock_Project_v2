# 高股息 ETF 定期定額模擬器 規格文件

> 版本：v1.0 (MVP)
> 最後更新：2026-07-01
> 對應前端 view：`#dividend-dca`
> 對應後端模組：`stock_fetcher/etf_*.py`

---

## 1. 目標與範圍

讓投資人在一個 view 內完成「**選 ETF → 看內涵 → 試算長期報酬**」的決策流程。

### MVP 範圍

| 編號 | 功能 | 來源 |
|---|---|---|
| 1 | ETF 基本資料（追蹤指數、規模、費用率、配息頻率、除息月份） | yfinance `.info` + `etf_config.py` |
| 2 | 歷史績效（含息 vs 不含息、年化、MDD、波動度、Sharpe） | yfinance `.history` |
| 3 | 配息歷史（每次金額、殖利率、月化配息、近一年月均） | yfinance `.dividends` |
| 4 | 持股（前 10 大、產業分布） | yfinance `.funds_data` |
| 6 | 定期定額模擬（DRIP / 領現金、含息對照 0050、月領預估） | 純計算（用 2+3 推） |

### MVP 不做

- 配息品質分數（穩定度 / 填息率 / 平準金）— 延後到 v1.1+
- 二代健保補充保費 / 股利所得稅扣除
- 壓力測試（2008 / 2022 情境）
- 退休反推（目標月領 → 所需投入）
- 使用者自訂任意 ETF 代號（僅清單內 22 檔）

---

## 2. ETF 清單（22 檔，5 組）

### A. 核心高股息（5 檔）

| 代號 | 名稱 | 配息 | 追蹤指數 | 費用率 |
|---|---|---|---|---|
| 0056 | 元大高股息 | 季配 | 臺灣高股息指數 | 0.46% |
| 00878 | 國泰永續高股息 | 季配 | MSCI 臺灣 ESG 永續高股息精選 30 | 0.51% |
| 00919 | 群益台灣精選高息 | 季配 | 臺灣精選高息指數 | 0.55% |
| 00713 | 元大台灣高息低波 | 季配 | 臺灣高息低波動指數 | 0.55% |
| 00915 | 凱基優選高股息 30 | 季配 | 臺灣多因子優選高股息 30 指數 | 0.40% |

### B. 月配息（5 檔）

| 代號 | 名稱 | 追蹤指數 | 費用率 |
|---|---|---|---|
| 00929 | 復華台灣科技優息 | 臺灣科技優息指數 | 0.60% |
| 00939 | 統一台灣高息動能 | 特選台灣高息動能指數 | 0.60% |
| 00940 | 元大台灣價值高息 | 臺灣價值高息指數 | 0.34% |
| 00943 | 兆豐台灣電子成長高息 | 特選臺灣電子高息成長指數 | 0.45% |
| 00946 | 群益台灣科技高息成長 | 臺灣科技高息成長指數 | 0.50% |

### C. 高息成長 / 因子型（3 檔）

| 代號 | 名稱 | 配息 | 追蹤指數 | 費用率 |
|---|---|---|---|---|
| 00731 | FH 富時高息低波 | 季配 | 富時臺灣高息低波指數 | 0.50% |
| 00701 | 國泰股利精選 30 | 半年配 | 臺灣指數公司低波動股利精選 30 | 0.34% |
| 00692 | 富邦公司治理 | 半年配 | 臺灣公司治理 100 指數 | 0.32% |

### D. 主動式 ETF（5 檔）

> ⚠️ 2025/06 起發行，歷史 < 1 年，5Y/3Y 績效自動隱藏；DCA 模擬至少需 6 個月。

| 代號 | 名稱 | 策略 | 費用率 |
|---|---|---|---|
| 00980A | 野村臺灣 SMART 主動式 | 多因子主動選股 | 0.99% |
| 00981A | 統一台灣高息成長主動式 | 高息 + 成長 | 0.99% |
| 00982A | 群益台灣優選主動式 | 主動精選 | 0.99% |
| 00984A | 安聯臺灣高息成長主動式 | 高息成長 | 1.20% |
| 00985A | 野村臺灣 50 主動式 | 50 指數增強 | 0.99% |

### E. 對照組（4 檔）

| 代號 | 名稱 | 角色 |
|---|---|---|
| 0050 | 元大台灣 50 | 大盤總報酬基準（DCA 模擬器強制對照） |
| 006208 | 富邦台 50 | 0050 低費用替代 |
| 00646 | 元大 S&P500 | 美股對照 |
| 00692\* | 富邦公司治理 | 已在 C 組 |

---

## 3. 資料庫設計（etf.db）

獨立 SQLite，位於 `data/etf.db`，與 `tw_market.db` 解耦。

### 3.1 為何獨立而非沿用 tw_market.db

- **領域邊界清楚**：ETF 元資料、配息、持股屬於「ETF 產品」領域，與既有的「個股市場日資料」職責不同
- **可獨立備份 / 重建**：ETF 資料來源以 yfinance 為主，重建成本低
- **減少 schema migration 影響面**：ETF schema MVP 階段仍可能調整，與既有 `tw_market.db` 隔離

### 3.2 Schema

```sql
-- 元資料快照（含 yfinance 抓得到的動態欄位 + config 寫死的靜態欄位合併）
CREATE TABLE etf_meta (
    symbol              TEXT PRIMARY KEY,        -- '0056.TW'
    name_zh             TEXT NOT NULL,           -- '元大高股息'
    name_en             TEXT,                    -- yfinance longName
    category            TEXT NOT NULL,           -- 'core' / 'monthly' / 'factor' / 'active' / 'benchmark'
    tracking_index      TEXT,                    -- config 寫死
    expense_ratio       REAL,                    -- config 寫死，yfinance 拿不到
    payout_frequency    INTEGER,                 -- 1=月 / 3=季 / 6=半年 / 12=年，可由 dividends 自動推
    is_active           INTEGER NOT NULL DEFAULT 0, -- 1=主動式 ETF
    fund_family         TEXT,                    -- yfinance fundFamily
    inception_date      TEXT,                    -- ISO date
    aum                 REAL,                    -- yfinance totalAssets
    nav_price           REAL,                    -- yfinance navPrice
    currency            TEXT DEFAULT 'TWD',
    updated_at          TEXT NOT NULL            -- ISO datetime
);

-- 日線價量（含 Adj Close 含息序列）
CREATE TABLE etf_price_daily (
    symbol      TEXT NOT NULL,
    date        TEXT NOT NULL,                   -- ISO date
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    adj_close   REAL,                            -- 用於含息報酬計算
    volume      INTEGER,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX idx_etf_price_symbol_date ON etf_price_daily(symbol, date);

-- 配息紀錄
CREATE TABLE etf_dividends (
    symbol          TEXT NOT NULL,
    ex_date         TEXT NOT NULL,               -- 除息日
    dividend        REAL NOT NULL,               -- 每股配息額
    PRIMARY KEY (symbol, ex_date)
);

-- 持股快照（覆寫式：每次抓只保留最新）
CREATE TABLE etf_holdings (
    symbol          TEXT NOT NULL,
    constituent     TEXT NOT NULL,               -- 成分股代號（如 '2330.TW'）
    name            TEXT,
    weight          REAL NOT NULL,               -- 0.0468 = 4.68%
    rank            INTEGER NOT NULL,            -- 1..N
    snapshot_at     TEXT NOT NULL,               -- 抓取時間
    PRIMARY KEY (symbol, constituent)
);

CREATE TABLE etf_sectors (
    symbol          TEXT NOT NULL,
    sector          TEXT NOT NULL,               -- 'technology' / 'financial_services' ...
    weight          REAL NOT NULL,
    snapshot_at     TEXT NOT NULL,
    PRIMARY KEY (symbol, sector)
);
```

### 3.3 資料更新策略

| 表 | 觸發時機 | TTL |
|---|---|---|
| `etf_meta` | 啟動初始化 + 每次 detail 請求若 `updated_at` > 24h | 24h |
| `etf_price_daily` | detail 請求若最新一筆 < 今天 | 即時補 |
| `etf_dividends` | detail 請求若最新一筆 < 今天 | 即時補 |
| `etf_holdings` / `etf_sectors` | detail 請求若 `snapshot_at` > 7 天 | 7 天 |

入庫策略：**lazy load + 增量更新**。啟動時不主動抓全部，第一個使用者要看哪檔就抓哪檔，後續用快取。

### 3.4 未來擴充欄位（不影響 MVP）

```sql
-- v1.1：配息品質
ALTER TABLE etf_meta ADD COLUMN quality_score REAL;
ALTER TABLE etf_dividends ADD COLUMN fill_days INTEGER;     -- 填息天數
ALTER TABLE etf_dividends ADD COLUMN levelizer_pct REAL;    -- 平準金佔比
ALTER TABLE etf_dividends ADD COLUMN income_pct REAL;       -- 股利所得佔比
ALTER TABLE etf_dividends ADD COLUMN capgain_pct REAL;      -- 資本利得佔比
```

---

## 4. 核心計算公式

### 4.1 月化配息

```
months_per_payout = payout_frequency               # 1 / 3 / 6 / 12
monthly_dividend_per_share = latest_dividend / months_per_payout
```

`payout_frequency` 取得順序：
1. 先讀 `etf_config.py` 的靜態設定
2. 若無，從 `etf_dividends` 最近 4 筆日期間隔自動推：

```python
def detect_payout_frequency(ex_dates: list[date]) -> int:
    if len(ex_dates) < 2:
        return 12
    gaps = [(b - a).days for a, b in zip(ex_dates, ex_dates[1:])]
    avg = sum(gaps) / len(gaps)
    if avg < 45:  return 1
    if avg < 120: return 3
    if avg < 200: return 6
    return 12
```

### 4.2 近一年月均配息

```
total_div_12m = sum(dividends where ex_date >= today - 365 days)
avg_monthly_div_12m = total_div_12m / 12
```

### 4.3 兩個一起顯示

| 欄位 | 公式 | 用途 |
|---|---|---|
| `monthly_dividend_latest` | `latest_div / payout_frequency` | 主指標：最近一期推算月領 |
| `monthly_dividend_avg_12m` | `近 12 個月總配息 / 12` | 副指標：對照基準 |
| `latest_vs_avg_pct` | `(latest - avg) / avg × 100` | 警示：本期增配 / 減配幅度 |

### 4.4 歷史報酬指標

```
# 含息報酬（用 adj_close）
total_return = adj_close[-1] / adj_close[0] - 1

# 年化 CAGR
years = (date[-1] - date[0]).days / 365.25
cagr = (1 + total_return) ** (1/years) - 1

# 最大回撤 MDD
rolling_max = adj_close.cummax()
drawdown = (adj_close - rolling_max) / rolling_max
mdd = drawdown.min()

# 波動度（年化）
daily_returns = adj_close.pct_change().dropna()
volatility = daily_returns.std() * sqrt(252)

# Sharpe（無風險利率假設 1.5%）
sharpe = (cagr - 0.015) / volatility
```

### 4.5 DCA + DRIP 模擬

**輸入：**
- `monthly_amount`：每月投入金額
- `start_date` / `end_date`
- `drip`：True = 股息再投入 / False = 領現金
- `benchmark`：對照標的（預設 `0050.TW`）

**演算法：**

```python
shares = 0
total_invested = 0
total_cash_div = 0
cashflows = []   # for XIRR

monthly_dates = closes.groupby([year, month]).head(1).index   # 每月第一個交易日

for each trading day:
    # 1) 配息日：先入帳
    if 當天有配息:
        cash_div = shares × dividend_per_share
        if drip:
            shares += cash_div / close_price       # 再投入
        else:
            total_cash_div += cash_div
            cashflows.append((date, +cash_div))

    # 2) 每月買進日：投入
    if 今天是該月第一個交易日:
        shares += monthly_amount / close_price
        total_invested += monthly_amount
        cashflows.append((date, -monthly_amount))

# 期末
market_value = shares × last_close
cashflows.append((last_date, +market_value))

xirr = solve_irr(cashflows)
cagr = (final_total_value / total_invested) ** (1/years) - 1
```

**對照標的同步跑一次**，呈現在同一張圖上。

### 4.6 退休現金流預估

```
estimated_annual_dividend = shares × (avg_monthly_div_12m × 12)
estimated_monthly_income = estimated_annual_dividend / 12
```

DCA 模擬器右側即時顯示「目前持股 X，每月可領 ≈ $N」。

---

## 5. Backend API 規格

### 5.1 `GET /api/etf/list`

回傳 22 檔 ETF 摘要，前端列表頁用。

**Response:**

```json
{
  "etfs": [
    {
      "symbol": "0056.TW",
      "name_zh": "元大高股息",
      "category": "core",
      "is_active": false,
      "payout_frequency": 3,
      "expense_ratio": 0.0046,
      "aum": 682852024320,
      "nav_price": 51.75,
      "yield": 0.0717,
      "monthly_dividend_latest": 0.357,
      "monthly_dividend_avg_12m": 0.320,
      "latest_vs_avg_pct": 11.6,
      "total_return_5y": 0.85,
      "as_of": "2026-07-01"
    },
    ...
  ]
}
```

### 5.2 `GET /api/etf/{symbol}/detail`

**Response:**

```json
{
  "meta": { /* 同 list 但更完整 */
    "symbol": "0056.TW", "name_zh": "...", "tracking_index": "...",
    "inception_date": "2007-12-13", "fund_family": "Yuanta...", ...
  },
  "performance": {
    "as_of": "2026-07-01",
    "return_1y_pct": 8.2,
    "return_3y_pct": 12.5,
    "return_5y_pct": 11.8,
    "return_since_inception_pct": 6.4,
    "mdd_pct": -23.5,
    "volatility_pct": 15.2,
    "sharpe": 0.65,
    "price_history": [{"date":"2021-07-01","close":36.5,"adj_close":28.4}, ...],
    "benchmark_history": [{"date":"...", "adj_close":...}, ...]
  },
  "dividends": {
    "monthly_dividend_latest": 0.357,
    "monthly_dividend_avg_12m": 0.320,
    "latest_vs_avg_pct": 11.6,
    "payout_frequency": 3,
    "history": [
      {"ex_date":"2026-04-23", "dividend":1.07, "yield_at_ex":0.020},
      ...
    ]
  },
  "holdings": {
    "snapshot_at": "2026-07-01",
    "top": [
      {"symbol":"2891.TW","name":"中信金","weight":0.0468,"rank":1},
      ...
    ],
    "sectors": [
      {"sector":"technology","weight":0.5576},
      ...
    ]
  }
}
```

### 5.3 `POST /api/etf/dca-simulate`

**Request:**

```json
{
  "symbol": "0056.TW",
  "monthly_amount": 10000,
  "start_date": "2021-01-01",
  "end_date": "2026-06-30",
  "drip": true,
  "benchmark": "0050.TW"
}
```

**Response:**

```json
{
  "target": {
    "symbol": "0056.TW",
    "total_invested": 660000,
    "shares": 26031.32,
    "last_price": 51.80,
    "market_value": 1348422,
    "cash_dividends_received": 0,
    "total_value": 1348422,
    "total_return_pct": 104.31,
    "cagr_pct": 14.2,
    "xirr_pct": 26.19,
    "timeline": [
      {"date":"2021-01-04","invested":10000,"market_value":10050,"shares":275.5}, ...
    ],
    "estimated_monthly_income_now": 8330
  },
  "benchmark": { /* 同結構，symbol = "0050.TW" */ }
}
```

---

## 6. UI 設計

整個流程內聚於 `#dividend-dca` view，內含三個 sub-view，照 `ScreenerView` 模式以內層 `TabController` 驅動。

### 6.1 URL 路由

| Hash | 子分頁 |
|---|---|
| `#dividend-dca` | 列表（預設） |
| `#dividend-dca?subtab=detail&symbol=00878.TW` | 詳情 |
| `#dividend-dca?subtab=simulator&symbol=00878.TW` | DCA 模擬器 |

### 6.2 Sub 1：ETF 列表（EtfListSubView）

```
[全部] [核心高股息] [月配] [因子型] [主動式] [對照組]      ← 內層 tab

┌──────┬────────────┬─────┬───────┬──────┬──────┬────┐
│ 代號 │ 名稱        │殖利率│月化配息│ 規模 │ 5Y含息│ 動 │  ← 排序
├──────┼────────────┼─────┼───────┼──────┼──────┼────┤
│ 0056 │ 元大高股息  │ 7.2%│ $0.36 │6,800億│ +85% │    │
│00878 │ 國泰永續..  │ 6.1%│ $0.55 │5,800億│ +95% │    │
│00940 │ 元大價值..  │10.2%│ $0.08▼│  800億│  —   │    │
│00982A│ 第一金太極..│  —  │   —   │   —   │  —   │ ⚡ │  ← 主動式標記
└──────┴────────────┴─────┴───────┴──────┴──────┴────┘

點某列 → navigate('dividend-dca', {subtab:'detail', symbol:'0056.TW'})
```

- 預設排序：規模降冪
- 主動式 ETF 用 ⚡ icon 標記
- 殖利率 > 10% 用紅字 + ⚠️
- 月化配息旁 ▲▼ 表示對近一年月均的變化方向

### 6.3 Sub 2：ETF 詳情（EtfDetailSubView）

單頁滾動 + sticky 錨點 tab：

```
┌─────────────────────────────────────────────────────┐
│ 0056 元大高股息              [← 回列表] [模擬定期定額→]│
│ NAV $51.75   殖利率 7.2%   AUM 6,800億               │
│ [概覽] [績效] [配息] [持股]                            │
└─────────────────────────────────────────────────────┘

▼ 概覽
   追蹤指數 / 配息頻率 / 除息月份 / 成立日 / 費用率 / 發行商

▼ 績效
   [折線圖] 含息 vs 不含息累積報酬 + 0050 灰底對照
   摘要：1Y/3Y/5Y/成立至今 含息年化、MDD、波動度、Sharpe

▼ 配息
   ┌─ 最近一期配息推算 ───────────────────┐
   │ 每股月化配息  $0.357                  │  ← MVP 重點
   │ 最新一期 $1.07（2026-04-23，季配）/3 │
   │ 近一年月均 $0.320  ▲ 比近一年高 11.6% │
   └─────────────────────────────────────┘
   [柱狀圖] 每次配息額（X=除息日，Y=金額）
   [表格] 近 12 次：除息日 / 金額 / 當期殖利率

▼ 持股
   [圓餅圖] 產業分布
   [長條圖] 前 10 大持股 + 權重
   集中度：Top10 佔比 / Top1 佔比
```

主動式 ETF 因歷史短，績效區自動隱藏 3Y/5Y，僅顯示「成立至今」。

### 6.4 Sub 3：DCA 模擬器（DcaSimulatorSubView）

```
┌────────────────────────────────────────────────────────┐
│ 定期定額模擬 — 0056 元大高股息       [切換 ETF →]       │
├──────────────────┬─────────────────────────────────────┤
│ 【輸入】          │ 【輸出】                              │
│                  │                                       │
│ 每月投入          │ ┌─ 結果摘要 ──────────────────┐    │
│ [-----●------]   │ │ 累積投入: 240 萬              │    │
│ $10,000          │ │ 期末市值: 528 萬 🟢            │    │
│                  │ │ 累積領息: $0 (DRIP)           │    │
│ 投入期間 (年)    │ │ 含息年化: 9.8%                │    │
│ [---●--------]   │ │ XIRR:    14.2%                │    │
│ 5               │ │ 同期 0050: 685 萬 (年化 12.1%) │    │
│                  │ └────────────────────────────────┘    │
│ 股息處理         │                                       │
│ ◉ 再投入 (DRIP)  │ [折線圖]                              │
│ ○ 領現金         │ ──── 累積投入本金（基線）              │
│                  │ ──── 0056 含息市值（粗）              │
│ 起始日           │ ---- 0050 含息市值（虛線對照）        │
│ [2021-01-01]    │                                       │
│                  │ ┌─ 退休現金流預估 ──────────┐       │
│ [重新計算]       │ │ 目前持有 26,031 股            │       │
│                  │ │ 每月可領 ≈ $8,330            │       │
│                  │ │ 年領 ≈ $99,960               │       │
│                  │ └──────────────────────────────┘     │
└──────────────────┴─────────────────────────────────────┘
```

- 滑桿 / radio 變動後 debounce 300ms 自動重算
- 對照組固定 0050；MVP 不開放使用者自選對照
- 主動式 ETF 若歷史 < 1 年，顯示警告「資料不足以做長期模擬」

---

## 7. 資料來源對應表

| 欄位 | 來源 | 備註 |
|---|---|---|
| symbol, name_zh, category, is_active | `etf_config.py` | 人工維護 |
| tracking_index, expense_ratio | `etf_config.py` | yfinance 拿不到 |
| name_en, fund_family, inception_date, aum, nav_price, currency, yield | yfinance `.info` | 寫入 `etf_meta` |
| payout_frequency | `etf_config.py` 優先，fallback 自動推 | |
| 日線價量、Adj Close | yfinance `.history(auto_adjust=False)` | 寫入 `etf_price_daily` |
| 配息歷史 | yfinance `.dividends` | 寫入 `etf_dividends` |
| 前 10 持股 | yfinance `.funds_data.top_holdings` | 寫入 `etf_holdings` |
| 產業分布 | yfinance `.funds_data.sector_weightings` | 寫入 `etf_sectors` |
| 績效指標、月化配息、DCA 模擬結果 | 後端計算 | 不入庫，每次算 |

---

## 8. 檔案異動清單

### 新增

```
data/etf.db                                          (執行時自動建立)
stock_fetcher/etf_db.py                              (schema + 連線)
stock_fetcher/etf_config.py                          (22 檔元資料)
stock_fetcher/etf_service.py                         (業務邏輯)
frontend/src/views/dividend-dca/
    ├── dividend-dca-view.js                         (容器)
    ├── dividend-dca-view-template.js
    ├── etf-list-subview.js
    ├── etf-detail-subview.js
    └── dca-simulator-subview.js
frontend/src/components/charts/
    ├── etf-dividend-chart.js                        (配息柱狀)
    ├── etf-dca-chart.js                             (DCA 對照折線)
    └── etf-holdings-chart.js                        (產業圓餅 + 持股長條)
```

### 修改

```
app.py                                  新增 3 個 endpoint
frontend/src/services/api-client.js     新增 3 個 method
frontend/src/main.js                    替換 dividend-dca placeholder
```

---

## 9. 實作順序

1. `etf_db.py` + `etf_config.py`（無外部依賴，可獨立測試）
2. `etf_service.py`（依賴 yfinance + etf_db）
3. `app.py` 加 endpoint（依賴 service）
4. 後端 LIVE 模式驗證（curl 三個 endpoint，確認資料正確）
5. 前端 view + sub-views + charts
6. 前端 LIVE 整合測試

---

## 10. 後續版本路線圖

| 版本 | 內容 |
|---|---|
| v1.1 | 配息品質分數（穩定度 + 填息率，先不含平準金） |
| v1.2 | 平準金資料接入（爬發行商月報）→ 完整品質分數 |
| v2.0 | 壓力測試、退休反推、二代健保 / 股利稅試算 |
| v2.1 | 開放使用者自訂任意 ETF 代號 |
