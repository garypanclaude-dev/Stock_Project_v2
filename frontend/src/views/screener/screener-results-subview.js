// 內層 sub-view：篩選結果表格。

import { View } from '../../core/view.js';
import { eventBus } from '../../core/event-bus.js';
import { stripSuffix } from '../../services/ticker-utils.js';
import { fmtVol } from '../../services/formatters.js';

export class ScreenerResultsSubView extends View {
  constructor({ apiClient, parent }) {
    super();
    this._api = apiClient;
    this._parent = parent;       // ScreenerView，用來更新「最後更新」欄位
    this._loaded = false;
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = '<div data-bind="screener-table" class="overflow-x-auto"></div>';
    this._table = container.querySelector('[data-bind="screener-table"]');
  }

  async activate() {
    super.activate();
    if (!this._loaded) await this.reload();
  }

  invalidate() { this._loaded = false; }

  async reload() {
    try {
      const data = await this._api.getScreener();
      this._render(data);
      this._loaded = true;
    } catch (err) {
      console.warn('Screener failed:', err);
    }
  }

  _render(data) {
    this._parent.setUpdatedText(
      data.last_updated ? `最後更新：${data.last_updated.slice(0,10)}　共 ${data.total_stocks} 支` : ''
    );

    const picks = data.top_picks || [];
    if (!picks.length) {
      this._table.innerHTML = '<div class="text-slate-500 text-sm text-center py-6">無篩選結果</div>';
      return;
    }

    this._table.innerHTML = `
      <table class="w-full text-xs">
        <thead><tr class="text-slate-500 border-b border-slate-700">
          <th class="py-2 px-2 text-left font-medium w-10">#</th>
          <th class="py-2 px-2 text-left font-medium">代號</th>
          <th class="py-2 px-2 text-left font-medium">名稱</th>
          <th class="py-2 px-2 text-right font-medium">評分</th>
          <th class="py-2 px-2 text-right font-medium">收盤價</th>
          <th class="py-2 px-2 text-right font-medium">漲跌%</th>
          <th class="py-2 px-2 text-right font-medium">P/E</th>
          <th class="py-2 px-2 text-right font-medium">殖利率</th>
          <th class="py-2 px-2 text-right font-medium">成交量(張)</th>
        </tr></thead>
        <tbody>${picks.map(p => {
          const chgColor = p.change_pct >= 0 ? 'text-green-400' : 'text-red-400';
          const scoreColor = p.score >= 80 ? '#16a34a' : p.score >= 60 ? '#22c55e' : '#f59e0b';
          const sym = stripSuffix(p.symbol);
          return `<tr class="border-b border-slate-700/50 hover:bg-slate-700/30 cursor-pointer" data-symbol="${p.symbol}">
            <td class="py-2 px-2 text-slate-500">${p.rank}</td>
            <td class="py-2 px-2 font-mono font-bold text-slate-200">${sym}</td>
            <td class="py-2 px-2 text-slate-300">${p.name}</td>
            <td class="py-2 px-2 text-right font-bold tabular-nums" style="color:${scoreColor}">${p.score}</td>
            <td class="py-2 px-2 text-right tabular-nums text-slate-200">$${p.close}</td>
            <td class="py-2 px-2 text-right tabular-nums ${chgColor}">${p.change_pct>=0?'+':''}${p.change_pct}%</td>
            <td class="py-2 px-2 text-right tabular-nums">${p.pe ?? '–'}</td>
            <td class="py-2 px-2 text-right tabular-nums">${p.yield_pct != null ? p.yield_pct + '%' : '–'}</td>
            <td class="py-2 px-2 text-right tabular-nums text-slate-400">${fmtVol(p.volume)}</td>
          </tr>`;
        }).join('')}</tbody>
      </table>`;

    this._table.querySelectorAll('[data-symbol]').forEach(row => {
      row.addEventListener('click', () => {
        eventBus.emit('navigate', { view: 'stock', params: { ticker: row.dataset.symbol } });
      });
    });
  }
}
