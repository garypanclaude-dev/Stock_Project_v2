# 前端架構文件

> 版本：v1.0
> 最後更新：2026-06-30
> 涵蓋範圍：`frontend/` 目錄重構後的全新模組化架構

---

## 1. 設計目標

舊版前端是一個 1376 行的 `app.js` god file，所有邏輯（個股分析、潛力選股、自選股、ML、回測）混雜在同一個 scope 共用全域變數。隨著規劃中要新增「策略回測 / 產業熱度 / ETF 比較 / 高股息定期定額」四個新功能，再加東西進去會越來越難維護。

本架構的設計目標：

| 目標 | 解法 |
|---|---|
| **單一職責**：每個檔案只做一件事 | 拆成 core / services / components / views 四層 |
| **低耦合**：元件不需要知道下游 view 的存在 | 透過 `EventBus` pub/sub + 依賴注入 |
| **生命週期明確**：避免 chart instance / event listener 洩漏 | `View` 基底類強制 mount/activate/deactivate/unmount |
| **加新 view 成本接近零** | `router.register('id', new View())` 一行 |
| **可測試**：純函式 / 純資料層可在 Node 跑單元測試 | services 與 chart render 函式皆無 DOM 依賴或可注入 mock |
| **URL 可分享** | Hash router，每個 view 對應 `#view-id?params` |

---

## 2. 目錄結構

```
frontend/
├── index.html                    ← 89 行骨架（header + 頂層 tab bar + sidebar + view 容器）
├── style.css                     ← CSS（未動）
└── src/
    ├── main.js                   ← 唯一進入點：組裝、註冊、啟動
    │
    ├── core/                     ← 通用抽象，零業務知識
    │   ├── view.js               ← View 基底類（生命週期介面）
    │   ├── tab-controller.js     ← 通用 tab 切換器（同時驅動頂層 + 內層）
    │   ├── router.js             ← Hash router（URL ↔ view 同步）
    │   └── event-bus.js          ← Pub/sub 事件匯流排
    │
    ├── services/                 ← 純資料層，零 DOM 依賴
    │   ├── api-client.js         ← 統一 backend API 封裝
    │   ├── watchlist-store.js    ← 自選股 localStorage + 訂閱
    │   ├── state-store.js        ← 全域 app 狀態（mock / ticker / period / view）
    │   ├── ticker-utils.js       ← normalizeTicker、stripSuffix
    │   └── formatters.js         ← fmtCap、fmtVol、escHtml
    │
    ├── components/               ← 可重用 UI 元件
    │   ├── header.js             ← 頂部 header（ticker 輸入、mock 切換）
    │   ├── sidebar-watchlist.js  ← 自選股 sidebar
    │   └── charts/               ← 7 個圖表模組
    │       ├── chart-plugins.js          ← K 棒、型態標記、thinLabels
    │       ├── price-charts.js           ← 主圖 K 棒 + 成交量
    │       ├── indicator-charts.js       ← RSI / MACD / KD / OBV
    │       ├── fundamental-charts.js     ← 年營收 YoY / 股利歷史 / PE 河流
    │       ├── score-donut.js
    │       ├── comparison-chart.js       ← 同業 / 自選股相對表現
    │       └── backtest-rank-chart.js
    │
    └── views/                    ← 頂層 view（一個 view 一個檔）
        ├── stock-view.js                 ← 個股分析
        ├── stock-view-template.js        ← 對應 HTML 模板
        ├── placeholder-view.js           ← 通用施工中空殼
        └── screener/                     ← 潛力選股（含內層分頁）
            ├── screener-view.js          ← 容器，內部用 TabController
            ├── screener-view-template.js
            ├── screener-results-subview.js
            ├── backtest-subview.js
            └── ml-subview.js
```

---

## 3. 分層職責

採類洋蔥架構，依賴方向**單向由外向內**：`views → components → services → core`。

```
┌─────────────────────────────────────────────────────────┐
│  views/      個股分析、潛力選股、策略回測 …               │
│              ↓ 使用                                      │
├─────────────────────────────────────────────────────────┤
│  components/ header、sidebar、charts（render 函式）       │
│              ↓ 使用                                      │
├─────────────────────────────────────────────────────────┤
│  services/   api-client、stores、純函式                  │
│              ↓ 使用                                      │
├─────────────────────────────────────────────────────────┤
│  core/       View、TabController、Router、EventBus       │
└─────────────────────────────────────────────────────────┘
```

| 層 | 可以依賴 | 不可依賴 |
|---|---|---|
| `core/` | （無） | 任何業務 |
| `services/` | `core/` | DOM、`components/`、`views/` |
| `components/` | `core/`、`services/` | `views/` |
| `views/` | `core/`、`services/`、`components/` | 其他 `views/`（要溝通走 event-bus） |

---

## 4. 核心抽象（core/）

### 4.1 View 基底類

所有頂層 view 與內層 sub-view 都繼承自 `View`，必須實作以下生命週期：

```js
class MyView extends View {
  constructor(deps) { super(); /* 依賴注入，不碰 DOM */ }
  mount(container)  {        // 第一次進入：建立 DOM、Chart、訂閱事件
    super.mount(container);
  }
  activate(params)  {        // 每次切回來：刷新資料
    super.activate(params);
  }
  deactivate()      {        // 切走時：暫停、隱藏（DOM 保留以加速回返）
    super.deactivate();
  }
  unmount()         {        // 真正銷毀：destroy charts、unsubscribe
    super.unmount();
  }
}
```

**為何強制這套介面？** 過去 chart instance 與 setInterval 會跟著 view 切走而洩漏。Lifecycle 標準化後，記憶體管理變成 view 自己的責任，遺漏會在 code review 時馬上看出來。

### 4.2 TabController

零業務知識的通用 tab 切換器，**同時驅動頂層 view 列與內層 sub-tab**。

```js
const ctrl = new TabController({
  container: viewContainer,
  onChange: (from, to) => { /* 同步 URL、發事件 */ },
});
ctrl.register('stock',    new StockView(...));
ctrl.register('screener', new ScreenerView(...));
await ctrl.switchTo('screener');     // lazy mount + activate
```

關鍵特性：
- **Lazy mount**：view 第一次被 switch 到時才建立 DOM
- **自動釋放**：切走前先呼叫 `from.deactivate()`
- **重入安全**：重複 `switchTo(currentId)` 只觸發 `activate`，不會 re-mount
- **panel 自動建立**：在 container 內為每個 view 建一個子 div 並切換 `.hidden`

### 4.3 Router

Hash router，URL 格式 `#view-id?key=value&...`。

```js
router.bind(tabController);
router.start();                  // 讀取目前 URL，切到對應 view
router.navigate('screener');     // 程式觸發切換（會更新 URL）
```

**為何用 hash 而非 history API？** 此專案前端由 FastAPI StaticFiles 服務，沒有 SPA fallback 路由；用 history API 重新整理會 404。Hash 對伺服器透明、實作極簡，未來要升級只需換掉本檔。

### 4.4 EventBus

極簡 pub/sub，讓 components 不直接耦合 views：

```js
eventBus.on('ticker:analyze', ({ symbol }) => { ... });
eventBus.emit('ticker:analyze', { symbol: '2330.TW' });
```

#### 標準事件清單

| 事件名 | Payload | 發出者 | 訂閱者 |
|---|---|---|---|
| `ticker:analyze` | `{ symbol }` | header / sidebar | StockView、main |
| `ticker:add`     | `{ symbol }` | header | StockView |
| `mock:change`    | `{ isMock }` | header | StockView、ScreenerView |
| `sidebar:toggle` | （無） | header | SidebarWatchlist |
| `view:change`    | `{ from, to }` | main（TabController.onChange） | components |
| `navigate`       | `{ view, params }` | sub-views | main |

---

## 5. 資料層（services/）

### 5.1 ApiClient

集中所有 backend endpoint 呼叫；mock 旗標透過 callback 注入，與全域狀態解耦：

```js
const api = new ApiClient(() => stateStore.isMock);
const data = await api.getStockInsights('AAPL', '3M');
```

未來要加 retry、abort signal、response cache，都只改這一檔。

### 5.2 WatchlistStore / StateStore

採 store + 訂閱模式取代散落的全域變數：

```js
stateStore.set('isMock', false);
stateStore.on('currentView', (newView, oldView) => { ... });

watchlistStore.add('2330');
watchlistStore.onChange(({ tickers, quotes }) => { ... });
```

### 5.3 純函式

`ticker-utils`、`formatters` 是純函式模組，可在 Node 跑單元測試（已驗證）：

```bash
node --input-type=module -e "import {normalizeTicker} from './src/services/ticker-utils.js'; console.assert(normalizeTicker('2330') === '2330.TW')"
```

---

## 6. 元件層（components/）

### 6.1 Header / Sidebar 行為

兩者皆**只發事件、不直呼 view**。例如 Header 的「分析」按鈕：

```js
this._el.analyzeBtn.addEventListener('click', () => {
  eventBus.emit('ticker:analyze', { symbol: normalizeTicker(this._el.tickerInput.value) });
});
```

哪個 view 接收、要不要切 view，是 main / StockView 的事，Header 不需知道。

### 6.2 跨 view 行為的解法

「在非個股 view 時 disable ticker 輸入」這種跨 view 行為，Header 訂閱 `stateStore.currentView` 自己決定，不需要每個 view 知道 Header 存在：

```js
stateStore.on('currentView', v => this._syncTickerEnabled(v));
```

### 6.3 Chart 函式約定

`components/charts/` 內每個函式皆為純函式：

```js
export function renderRSI(canvas, klines, indicators) {
  if (!indicators?.rsi) return null;   // 無資料回傳 null
  return new Chart(canvas.getContext('2d'), { ... });  // 回傳 Chart instance
}
```

**呼叫端持有 instance 並負責 destroy**。Chart 函式自己不管理生命週期。

---

## 7. 視圖層（views/）

### 7.1 一個 view 的完整骨架

```js
import { View } from '../core/view.js';
import { eventBus } from '../core/event-bus.js';
import { stateStore } from '../services/state-store.js';

export class MyView extends View {
  constructor({ apiClient }) {
    super();
    this._api = apiClient;
    this._charts = {};
    this._unsubs = [];
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = MY_TEMPLATE;
    this._cacheBindings(container);
    this._unsubs.push(eventBus.on('mock:change', () => this.activate()));
  }

  async activate(params = {}) {
    super.activate(params);
    const data = await this._api.getSomething();
    this._render(data);
  }

  unmount() {
    this._unsubs.forEach(u => u());
    Object.values(this._charts).forEach(c => c?.destroy());
    super.unmount();
  }
}
```

### 7.2 模板與 DOM 綁定約定

HTML 模板抽到 `*-view-template.js`，避免 view 邏輯被一大塊字串淹沒。

**禁止使用 `id="..."` + `document.getElementById`**，因為若同一個 view 在頁面上有兩份（未來可能的需求）會 id 衝突。改用 `data-bind="key"`：

```html
<canvas data-bind="rsi-chart"></canvas>
```

```js
container.querySelectorAll('[data-bind]').forEach(el => {
  this._el[el.dataset.bind] = el;
});
this._el['rsi-chart'];   // 取用
```

同理：互動元素用 `data-action` 取代 inline `onclick`：

```html
<button data-action="refresh">重新整理</button>
```

### 7.3 內層 sub-view（以 ScreenerView 為例）

潛力選股的三個內層分頁（篩選結果 / 回測 / ML）每一個也是 `View` 子類，由 ScreenerView 內部建立的 **TabController instance** 驅動 —— 與頂層 TabController 是同一份程式碼，驗證抽象的可重用性：

```js
// screener-view.js
this._subTab = new TabController({ container: this._el['sub-container'] });
this._subTab.register('results',  new ScreenerResultsSubView({ ... }));
this._subTab.register('backtest', new BacktestSubView({ ... }));
this._subTab.register('ml',       new MLSubView({ ... }));
```

---

## 8. 進入點：main.js

唯一帶 side effects 的檔案，順序：

1. 建立 services（`apiClient`、`watchlistStore`）
2. 建立 components（`header`、`sidebar`）
3. 建立 views（六個）
4. 建立 `TabController`、註冊所有 view
5. 建立 `Router`、bind、start
6. 訂閱跨 view 事件（`navigate`、`ticker:analyze`）

---

## 9. 加一個新 view 的流程

以「策略回測」實作為例（目前是 PlaceholderView）：

### Step 1：建立 view class

```
src/views/strategy-backtest/
  ├── strategy-backtest-view.js
  └── strategy-backtest-view-template.js
```

```js
// strategy-backtest-view.js
import { View } from '../../core/view.js';

export class StrategyBacktestView extends View {
  constructor({ apiClient }) { super(); this._api = apiClient; }
  mount(container) { super.mount(container); container.innerHTML = TEMPLATE; }
  async activate(params) { super.activate(params); /* fetch + render */ }
  unmount() { /* destroy charts */ super.unmount(); }
}
```

### Step 2：替換 main.js 的 placeholder

```diff
- 'strategy-backtest': new PlaceholderView({ title: '策略回測', ... }),
+ 'strategy-backtest': new StrategyBacktestView({ apiClient }),
```

### Step 3：完成。

不需動 `index.html`（top-tabs 按鈕已存在）、不需動 router（已註冊）、不需動其他 view。URL `#strategy-backtest` 立即可用。

### 加 backend endpoint

若需要新 API，去 `services/api-client.js` 加一個 method：

```js
runStrategyBacktest(config) { return this._post('/api/strategy-backtest', config); }
```

---

## 10. 加一個 chart 的流程

1. 在 `components/charts/` 加一個檔，export 一個 `renderXxx(canvas, ...)` 函式回傳 Chart instance
2. 在 view 的 `_render` 方法呼叫：
   ```js
   this._destroyChart('myChart');
   this._charts.myChart = renderXxx(this._el['my-chart'], data);
   ```
3. 在 `unmount` 確認 `_destroyAllCharts()` 會清掉它（已自動處理）

---

## 11. Mock / LIVE 切換的資料流

```
User 點 toggle
   ↓
header._toggleMock()
   ↓
stateStore.set('isMock', !isMock)            ← 狀態變更
   ↓
eventBus.emit('mock:change', { isMock })     ← 廣播事件
   ↓ ┌─────────────────────────────────┐
     │ StockView 訂閱 → 立即重抓        │
     │ ScreenerView 訂閱 → 失效所有     │
     │   sub-view，當前 sub 立即 reload │
     │ Sidebar 訂閱 → 重抓 batch-quotes │
     └─────────────────────────────────┘
```

`api-client` 透過 `() => stateStore.isMock` 取得當前旗標，所以後續每個 API 呼叫都帶 `mock=false`。

---

## 12. URL 路由清單

| Hash | View |
|---|---|
| `#stock` 或 `#stock?ticker=AAPL` | 個股分析 |
| `#screener` | 潛力選股（預設子分頁：篩選結果） |
| `#screener?subtab=backtest` | 潛力選股 → 回測分析 |
| `#screener?subtab=ml` | 潛力選股 → ML 選股 |
| `#strategy-backtest` | 策略回測（placeholder） |
| `#sector-heatmap` | 產業熱度（placeholder） |
| `#etf-compare` | ETF 比較（placeholder） |
| `#dividend-dca` | 高股息定期定額（placeholder） |

未知或空 hash 一律導向 `#stock`。

---

## 13. 編碼慣例

- **語言**：繁體中文註解 + 英文識別字
- **檔名**：kebab-case（`stock-view.js`）
- **Class 名**：PascalCase（`StockView`）
- **私有方法**：底線前綴（`_render`）
- **常數**：UPPER_SNAKE_CASE（`STOCK_VIEW_TEMPLATE`）
- **DOM 綁定**：用 `data-bind` 與 `data-action`，**禁止** `id="..."` 與 inline `onclick`（既存 `#wl-sidebar` 等是過渡期保留，未來重構時改掉）
- **註解原則**：依 CLAUDE.md，只寫「為什麼這樣做」，不寫「這段程式碼在做什麼」

---

## 14. 測試策略

| 層 | 測試方式 |
|---|---|
| `services/` 純函式 | Node 單元測試（已驗證 `normalizeTicker`、`fmtCap`、`escHtml`、`WatchlistStore`） |
| `components/charts/*` | 在實際 view 中視覺驗收（chart.js 渲染） |
| `views/` | 開瀏覽器手動測試 MOCK + LIVE 兩種模式 |
| 整合 | preview tools 自動操作（click、screenshot、console error 檢查） |

### Smoke test 指令

```bash
cd frontend
# Service 層
node --input-type=module -e "import('./src/services/ticker-utils.js').then(m => console.log(m.normalizeTicker('2330')))"

# Module 載入
node --input-type=module -e "import('./src/main.js').then(() => console.log('main loaded'))"
```

---

## 15. 未來擴充方向

| 規劃功能 | 對應 view | 狀態 |
|---|---|---|
| 策略回測 | `strategy-backtest` | placeholder，待實作 |
| 產業熱度 | `sector-heatmap` | placeholder，待實作 |
| ETF 比較 | `etf-compare` | placeholder，待實作 |
| 高股息定期定額預期回報 | `dividend-dca` | placeholder，待實作 |

實作時遵循「[加一個新 view 的流程](#9-加一個新-view-的流程)」即可。

### 升級路徑

- **TypeScript**：所有檔案皆為 ES Module，加 `tsconfig.json` 後改副檔名即可漸進式遷移
- **打包工具**：目前用瀏覽器原生 ES Module，若日後檔案數增加導致初始載入慢，可加 esbuild / vite，**view 與 component 程式碼不需變動**
- **history API**：若改用後端 SPA fallback，只需替換 `core/router.js`，其他層不動
- **狀態管理升級**：`state-store.js` 是極簡 pub/sub，若狀態膨脹可換成 Zustand / Redux 而不影響呼叫端 API（保留 `get/set/on` 介面即可）
