// 頂部 Header 元件。
//
// 職責：股票代號輸入、分析按鈕、加入自選按鈕、LIVE/MOCK 切換、watchlist sidebar 開合。
//
// Header 不知道下游有哪些 view —— 只發事件、不直呼 view 函式：
//   'ticker:analyze'  payload={ symbol }     使用者按下「分析」或 Enter
//   'ticker:add'      payload={ symbol }     按下 + 把目前輸入加入自選
//   'mock:change'     payload={ isMock }     切換 MOCK toggle
//   'sidebar:toggle'                          開合 sidebar
//
// 對於「目前在 screener view 時 disable ticker 輸入」這種跨 view 行為，
// header 訂閱 stateStore 'currentView' 變化，自己決定 UI 狀態。
//
// 對外 API：mount(rootSelectors)；外部不需直接操作 header 內部元素。

import { eventBus } from '../core/event-bus.js';
import { stateStore } from '../services/state-store.js';
import { normalizeTicker } from '../services/ticker-utils.js';

const TICKER_DEPENDENT_VIEWS = new Set(['stock']);

export class Header {
  constructor() {
    this._el = {};
  }

  mount() {
    this._el = {
      tickerInput: document.getElementById('ticker-input'),
      analyzeBtn:  document.querySelector('[data-action="analyze"]'),
      addBtn:      document.querySelector('[data-action="add-to-watchlist"]'),
      sidebarBtn:  document.querySelector('[data-action="toggle-sidebar"]'),
      mockToggle:  document.querySelector('[data-action="toggle-mock"]'),
      mockTrack:   document.getElementById('toggle-track'),
      mockDot:     document.getElementById('toggle-dot'),
      mockBadge:   document.getElementById('mock-badge'),
    };

    this._el.tickerInput?.addEventListener('keydown', e => {
      if (e.key === 'Enter') this._emitAnalyze();
    });
    this._el.analyzeBtn?.addEventListener('click', () => this._emitAnalyze());
    this._el.addBtn?.addEventListener('click', () => this._emitAdd());
    this._el.sidebarBtn?.addEventListener('click', () => eventBus.emit('sidebar:toggle'));
    this._el.mockToggle?.addEventListener('click', () => this._toggleMock());

    stateStore.on('currentView', v => this._syncTickerEnabled(v));
    stateStore.on('isMock', () => this._syncMockUI());

    this._syncMockUI();
    this._syncTickerEnabled(stateStore.currentView);
  }

  setTicker(symbol) {
    if (!this._el.tickerInput) return;
    // 顯示原始（包含市場後綴），方便使用者複製
    this._el.tickerInput.value = symbol;
  }

  _emitAnalyze() {
    const raw = this._el.tickerInput?.value || '';
    const symbol = normalizeTicker(raw);
    if (!symbol) return;
    eventBus.emit('ticker:analyze', { symbol });
  }

  _emitAdd() {
    const raw = this._el.tickerInput?.value || '';
    const symbol = normalizeTicker(raw);
    if (!symbol) return;
    eventBus.emit('ticker:add', { symbol });
  }

  _toggleMock() {
    stateStore.set('isMock', !stateStore.isMock);
    eventBus.emit('mock:change', { isMock: stateStore.isMock });
  }

  _syncMockUI() {
    const m = stateStore.isMock;
    if (this._el.mockTrack) {
      this._el.mockTrack.className = `w-10 h-5 rounded-full transition-colors duration-200 ${m ? 'bg-amber-500' : 'bg-slate-600'}`;
    }
    if (this._el.mockDot) {
      this._el.mockDot.className = `absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${m ? 'translate-x-5' : 'translate-x-0'}`;
    }
    if (this._el.mockBadge) {
      this._el.mockBadge.className = `text-xs font-semibold px-2.5 py-1 rounded-full border ${m ? 'bg-amber-500/15 text-amber-400 border-amber-500/30' : 'bg-slate-700 text-slate-500 border-slate-600'}`;
      this._el.mockBadge.textContent = m ? 'MOCK' : 'LIVE';
    }
  }

  _syncTickerEnabled(view) {
    const tickerRelevant = view == null || TICKER_DEPENDENT_VIEWS.has(view);
    [this._el.tickerInput, this._el.analyzeBtn, this._el.addBtn].forEach(el => {
      if (!el) return;
      el.disabled = !tickerRelevant;
      el.classList.toggle('opacity-40', !tickerRelevant);
      el.classList.toggle('cursor-not-allowed', !tickerRelevant);
    });
  }
}
