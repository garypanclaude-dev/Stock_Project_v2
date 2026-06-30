// 應用程式進入點。
//
// 唯一一個帶有 side effects 的檔案：建立所有依賴、組裝、啟動 router。
// 其他模組（core/services/components/views）皆 stateless 或 self-contained。

import { TabController } from './core/tab-controller.js';
import { Router } from './core/router.js';
import { eventBus } from './core/event-bus.js';

import { stateStore } from './services/state-store.js';
import { ApiClient } from './services/api-client.js';
import { JobStore } from './services/job-store.js';
import { WatchlistStore } from './services/watchlist-store.js';

import { Header } from './components/header.js';
import { SidebarWatchlist } from './components/sidebar-watchlist.js';

import { StockView } from './views/stock-view.js';
import { ScreenerView } from './views/screener/screener-view.js';
import { DividendDcaView } from './views/dividend-dca/dividend-dca-view.js';
import { PlaceholderView } from './views/placeholder-view.js';

// ── 依賴注入 ─────────────────────────────────────────────────────────
const apiClient = new ApiClient(() => stateStore.isMock);
const jobStore = new JobStore(apiClient);
const watchlistStore = new WatchlistStore();

// ── Components ─────────────────────────────────────────────────────
const header = new Header();
const sidebar = new SidebarWatchlist({ watchlistStore, apiClient });

// ── Views ──────────────────────────────────────────────────────────
const views = {
  'stock':              new StockView({ apiClient, watchlistStore }),
  'screener':           new ScreenerView({ apiClient, jobStore }),
  'strategy-backtest':  new PlaceholderView({ title: '策略回測', description: '輸入買賣訊號規則，回測歷史報酬與風險指標。' }),
  'sector-heatmap':     new PlaceholderView({ title: '產業熱度',  description: '各產業 / 主題類股的資金流向、漲跌幅熱力圖。' }),
  'etf-compare':        new PlaceholderView({ title: 'ETF 比較',  description: '同類 ETF 績效、費用率、追蹤誤差、持股重疊度比較。' }),
  'dividend-dca':       new DividendDcaView({ apiClient }),
};

const VIEW_TITLES = {
  'stock': '個股分析',
  'screener': '潛力選股',
  'strategy-backtest': '策略回測',
  'sector-heatmap': '產業熱度',
  'etf-compare': 'ETF 比較',
  'dividend-dca': '高股息定期定額',
};

// ── TabController + Router ─────────────────────────────────────────
function bootstrap() {
  const container = document.getElementById('view-container');
  const tabController = new TabController({
    container,
    onChange: (from, to) => {
      stateStore.set('currentView', to);
      eventBus.emit('view:change', { from, to });
      syncTopTabs(to);
    },
  });
  for (const [id, view] of Object.entries(views)) {
    tabController.register(id, view);
  }

  const router = new Router({ defaultView: 'stock' });
  router.bind(tabController);

  // 頂層 tab 點擊：以 router 切換（會同步 URL）
  document.getElementById('top-tabs')?.addEventListener('click', e => {
    const btn = e.target.closest('[data-view]');
    if (btn) router.navigate(btn.dataset.view);
  });

  // 跨 view 導航：sub-view 廣播 'navigate' → router 切換頂層 view
  eventBus.on('navigate', ({ view, params }) => {
    if (view === 'stock' && params?.ticker) {
      stateStore.set('currentTicker', params.ticker);
      header.setTicker(params.ticker);
    }
    router.navigate(view, params || {});
  });

  // Header 廣播分析事件 → 切到 stock view 並用該 symbol 重抓
  eventBus.on('ticker:analyze', ({ symbol }) => {
    if (stateStore.currentView !== 'stock') router.navigate('stock');
    // stock view 自己訂閱了 'ticker:analyze'，這裡不必再呼叫
  });

  // Header / sidebar 共享：把目前 ticker 同步顯示到輸入框
  stateStore.on('currentTicker', sym => header.setTicker(sym));

  header.mount();
  sidebar.mount();
  router.start();
}

function syncTopTabs(activeId) {
  document.querySelectorAll('#top-tabs [data-view]').forEach(btn => {
    const active = btn.dataset.view === activeId;
    btn.classList.toggle('bg-slate-700', active);
    btn.classList.toggle('text-white', active);
    btn.classList.toggle('text-slate-400', !active);
  });
  const title = VIEW_TITLES[activeId];
  if (title) document.title = `${title} · StockInsights`;
}

document.addEventListener('DOMContentLoaded', bootstrap);
