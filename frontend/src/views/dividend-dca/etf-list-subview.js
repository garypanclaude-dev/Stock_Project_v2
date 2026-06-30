// 內層 sub-view：ETF 列表。
//
// 22 檔 ETF 表格，分組 tab 篩選、可點列導向詳情頁。

import { View } from '../../core/view.js';
import { eventBus } from '../../core/event-bus.js';
import { stripSuffix } from '../../services/ticker-utils.js';
import { escHtml } from '../../services/formatters.js';

const CATEGORY_LABELS = {
  all:        '全部',
  core:       '核心高股息',
  monthly:    '月配息',
  factor:     '因子型',
  active:     '主動式',
  benchmark:  '對照組',
};

const FREQ_LABEL = { 1: '月配', 3: '季配', 6: '半年配', 12: '年配', 2: '半年配' };

export class EtfListSubView extends View {
  constructor({ apiClient, parent }) {
    super();
    this._api = apiClient;
    this._parent = parent;
    this._loaded = false;
    this._data = null;
    this._activeCategory = 'all';
    this._sortKey = 'aum';
    this._sortDesc = true;
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = `
      <div class="space-y-3">
        <div data-bind="cat-tabs" class="flex flex-wrap gap-1 text-xs"></div>
        <div data-bind="table" class="overflow-x-auto"></div>
      </div>`;
    this._el = {
      catTabs: container.querySelector('[data-bind="cat-tabs"]'),
      table:   container.querySelector('[data-bind="table"]'),
    };
    this._renderCategoryTabs();

    this._el.catTabs.addEventListener('click', e => {
      const btn = e.target.closest('[data-cat]');
      if (!btn) return;
      this._activeCategory = btn.dataset.cat;
      this._renderCategoryTabs();
      this._renderTable();
    });

    this._el.table.addEventListener('click', e => {
      const row = e.target.closest('[data-symbol]');
      if (row) {
        eventBus.emit('navigate', {
          view: 'dividend-dca',
          params: { subtab: 'detail', symbol: row.dataset.symbol },
        });
        return;
      }
      const th = e.target.closest('[data-sort]');
      if (th) {
        const key = th.dataset.sort;
        if (key === this._sortKey) this._sortDesc = !this._sortDesc;
        else { this._sortKey = key; this._sortDesc = true; }
        this._renderTable();
      }
    });
  }

  async activate() {
    super.activate();
    if (!this._loaded) await this.reload();
  }

  invalidate() { this._loaded = false; }

  async reload() {
    this._el.table.innerHTML = '<div class="text-slate-500 text-sm text-center py-10">載入 ETF 列表中（首次需同步 yfinance，約 30–60 秒）…</div>';
    this._parent.setStatus('載入中…');
    try {
      const data = await this._api.getEtfList({ signal: this.signal() });
      this._data = data.etfs || [];
      this._loaded = true;
      this._parent.setStatus(`共 ${this._data.length} 檔 ETF`);
      this._renderTable();
    } catch (err) {
      if (err.name === 'AbortError') return;
      this._el.table.innerHTML = `<div class="text-red-400 text-sm text-center py-6">載入失敗：${escHtml(err.message)}</div>`;
      this._parent.setStatus('載入失敗');
    }
  }

  _renderCategoryTabs() {
    this._el.catTabs.innerHTML = Object.entries(CATEGORY_LABELS).map(([k, label]) => {
      const active = k === this._activeCategory;
      const cls = active
        ? 'bg-slate-700 text-slate-200'
        : 'bg-slate-900 text-slate-500 hover:text-slate-300';
      return `<button data-cat="${k}" class="px-3 py-1 rounded-md transition font-medium ${cls}">${label}</button>`;
    }).join('');
  }

  _renderTable() {
    if (!this._data) return;
    let rows = this._activeCategory === 'all'
      ? [...this._data]
      : this._data.filter(e => e.category === this._activeCategory);

    rows.sort((a, b) => {
      const av = a[this._sortKey], bv = b[this._sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return this._sortDesc ? bv - av : av - bv;
    });

    if (!rows.length) {
      this._el.table.innerHTML = '<div class="text-slate-500 text-sm text-center py-6">此分類無 ETF</div>';
      return;
    }

    const sortIcon = key =>
      key === this._sortKey ? (this._sortDesc ? ' ↓' : ' ↑') : '';

    this._el.table.innerHTML = `
      <table class="w-full text-xs">
        <thead><tr class="text-slate-500 border-b border-slate-700">
          <th class="py-2 px-2 text-left font-medium">代號</th>
          <th class="py-2 px-2 text-left font-medium">名稱</th>
          <th class="py-2 px-2 text-left font-medium">分類</th>
          <th class="py-2 px-2 text-right font-medium">配息</th>
          <th class="py-2 px-2 text-right font-medium cursor-pointer hover:text-slate-300" data-sort="yield_rate">殖利率${sortIcon('yield_rate')}</th>
          <th class="py-2 px-2 text-right font-medium cursor-pointer hover:text-slate-300" data-sort="monthly_dividend_latest">月化配息${sortIcon('monthly_dividend_latest')}</th>
          <th class="py-2 px-2 text-right font-medium cursor-pointer hover:text-slate-300" data-sort="aum">規模${sortIcon('aum')}</th>
          <th class="py-2 px-2 text-right font-medium cursor-pointer hover:text-slate-300" data-sort="expense_ratio">費用率${sortIcon('expense_ratio')}</th>
          <th class="py-2 px-2 text-right font-medium cursor-pointer hover:text-slate-300" data-sort="return_5y_pct">5Y 含息${sortIcon('return_5y_pct')}</th>
        </tr></thead>
        <tbody>${rows.map(r => this._renderRow(r)).join('')}</tbody>
      </table>`;
  }

  _renderRow(r) {
    const sym = stripSuffix(r.symbol);
    const yieldVal = r.yield_rate != null ? (r.yield_rate * 100).toFixed(2) : null;
    const yieldColor = yieldVal != null && parseFloat(yieldVal) >= 10
      ? 'text-red-400' : yieldVal != null && parseFloat(yieldVal) >= 8 ? 'text-amber-400' : 'text-slate-200';
    const yieldWarn = yieldVal != null && parseFloat(yieldVal) >= 10 ? ' ⚠️' : '';

    const monthlyDiv = r.monthly_dividend_latest != null
      ? `$${r.monthly_dividend_latest.toFixed(2)}` : '–';
    const delta = r.latest_vs_avg_pct;
    const arrow = delta == null ? ''
      : delta > 3 ? '<span class="text-green-400 ml-1">▲</span>'
      : delta < -3 ? '<span class="text-red-400 ml-1">▼</span>' : '';

    const aum = r.aum
      ? r.aum >= 1e11 ? `${(r.aum / 1e11).toFixed(1)} 千億`
        : r.aum >= 1e8 ? `${(r.aum / 1e8).toFixed(0)} 億` : `$${r.aum.toLocaleString()}`
      : '–';

    const fee = r.expense_ratio != null ? (r.expense_ratio * 100).toFixed(2) + '%' : '–';
    const ret5y = r.return_5y_pct != null
      ? `<span class="${r.return_5y_pct >= 0 ? 'text-green-400' : 'text-red-400'}">${r.return_5y_pct >= 0 ? '+' : ''}${r.return_5y_pct.toFixed(1)}%</span>`
      : '<span class="text-slate-600">—</span>';

    const activeTag = r.is_active
      ? '<span class="ml-1 px-1.5 py-0.5 text-[10px] rounded bg-amber-900/40 text-amber-300">⚡主動</span>' : '';

    return `<tr class="border-b border-slate-700/50 hover:bg-slate-700/30 cursor-pointer" data-symbol="${r.symbol}">
      <td class="py-2 px-2 font-mono font-bold text-slate-200">${sym}</td>
      <td class="py-2 px-2 text-slate-300">${escHtml(r.name_zh)}${activeTag}</td>
      <td class="py-2 px-2 text-slate-500">${CATEGORY_LABELS[r.category] || r.category}</td>
      <td class="py-2 px-2 text-right text-slate-400">${FREQ_LABEL[r.payout_frequency] || '–'}</td>
      <td class="py-2 px-2 text-right tabular-nums ${yieldColor}">${yieldVal != null ? yieldVal + '%' + yieldWarn : '–'}</td>
      <td class="py-2 px-2 text-right tabular-nums text-slate-200">${monthlyDiv}${arrow}</td>
      <td class="py-2 px-2 text-right tabular-nums text-slate-400">${aum}</td>
      <td class="py-2 px-2 text-right tabular-nums text-slate-400">${fee}</td>
      <td class="py-2 px-2 text-right tabular-nums">${ret5y}</td>
    </tr>`;
  }
}
