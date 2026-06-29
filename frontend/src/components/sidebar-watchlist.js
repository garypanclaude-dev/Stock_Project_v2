// 自選股 sidebar 元件。
//
// 訂閱 WatchlistStore 變化自動重繪；按下單一條目時透過 event-bus 廣播
// 'ticker:analyze'，由個股 view 訂閱處理。Component 不直呼 view 函式。

import { eventBus } from '../core/event-bus.js';
import { stateStore } from '../services/state-store.js';
import { stripSuffix } from '../services/ticker-utils.js';

export class SidebarWatchlist {
  constructor({ watchlistStore, apiClient }) {
    this._store = watchlistStore;
    this._api = apiClient;
    this._el = {};
    this._open = true;
  }

  async mount() {
    this._el = {
      sidebar:   document.getElementById('wl-sidebar'),
      list:      document.getElementById('wl-list'),
      addInput:  document.getElementById('wl-add-input'),
      addBtn:    document.querySelector('[data-action="wl-add"]'),
      refreshBtn:document.querySelector('[data-action="wl-refresh"]'),
      refreshIcon:document.getElementById('wl-refresh-icon'),
    };

    this._el.addBtn?.addEventListener('click', () => this._handleAdd());
    this._el.addInput?.addEventListener('keydown', e => { if (e.key === 'Enter') this._handleAdd(); });
    this._el.refreshBtn?.addEventListener('click', () => this.refresh());

    eventBus.on('sidebar:toggle', () => this._toggle());
    eventBus.on('mock:change', () => this.refresh());
    this._store.onChange(() => this._render());

    stateStore.on('currentTicker', () => this._render());

    this._render();
    await this.refresh();
  }

  async refresh() {
    const tickers = this._store.list();
    if (!tickers.length) { this._render(); return; }
    this._el.refreshIcon?.classList.add('spin');
    try {
      const data = await this._api.getBatchQuotes(tickers);
      this._store.setQuotes(data.quotes || []);
    } catch (err) {
      console.warn('Watchlist refresh failed:', err);
    } finally {
      this._el.refreshIcon?.classList.remove('spin');
    }
  }

  _handleAdd() {
    const raw = this._el.addInput?.value?.trim() || '';
    if (!raw) return;
    if (this._store.add(raw)) {
      this._el.addInput.value = '';
      this.refresh();
    }
  }

  _toggle() {
    this._open = !this._open;
    this._el.sidebar?.classList.toggle('collapsed', !this._open);
  }

  _render() {
    if (!this._el.list) return;
    const tickers = this._store.list();
    const quotes = this._store.quotes();
    const current = stateStore.currentTicker;

    if (!tickers.length) {
      this._el.list.innerHTML = '<div class="px-3 py-6 text-center text-xs text-slate-500">尚未加入自選股<br>使用 + 按鈕新增</div>';
      return;
    }

    this._el.list.innerHTML = tickers.map(ticker => {
      const q = quotes[ticker];
      const active = ticker === current ? ' active' : '';
      const price = q ? `$${q.current_price.toFixed(2)}` : '–';
      const change = q ? `${q.change >= 0 ? '+' : ''}${q.change.toFixed(2)}` : '';
      const pct = q ? `${q.change_pct >= 0 ? '+' : ''}${q.change_pct.toFixed(2)}%` : '';
      const color = q ? (q.change >= 0 ? 'text-green-400' : 'text-red-400') : 'text-slate-500';
      const displayTicker = stripSuffix(ticker);
      return `
        <div class="wl-row flex items-center px-3 py-2.5 cursor-pointer${active}"
             data-ticker="${ticker}">
          <div class="flex-1 min-w-0">
            <div class="text-sm font-bold text-slate-200 truncate">${displayTicker}</div>
            <div class="text-xs ${color} tabular-nums">${change} (${pct})</div>
          </div>
          <div class="text-right shrink-0 mr-2">
            <div class="text-sm font-semibold text-slate-100 tabular-nums">${price}</div>
          </div>
          <button data-remove="${ticker}" class="p-0.5 rounded hover:bg-red-500/20 transition" title="移除">
            <svg class="w-3.5 h-3.5 text-slate-600 hover:text-red-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>`;
    }).join('');

    // Event delegation：避免每個 row inline onclick，與 HTML 解耦
    this._el.list.querySelectorAll('[data-ticker]').forEach(row => {
      row.addEventListener('click', e => {
        const removeBtn = e.target.closest('[data-remove]');
        if (removeBtn) {
          e.stopPropagation();
          this._store.remove(removeBtn.dataset.remove);
          return;
        }
        eventBus.emit('ticker:analyze', { symbol: row.dataset.ticker });
      });
    });
  }
}
