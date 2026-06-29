// 內層 sub-view：回測分析（前瞻報酬統計 + 排名分組超額報酬 + 信號明細）。

import { View } from '../../core/view.js';
import { stripSuffix } from '../../services/ticker-utils.js';
import { renderBacktestRankChart } from '../../components/charts/backtest-rank-chart.js';

export class BacktestSubView extends View {
  constructor({ apiClient }) {
    super();
    this._api = apiClient;
    this._loaded = false;
    this._rankChart = null;
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = `
      <div data-bind="summary" class="mb-4"></div>
      <div data-bind="horizon" class="mb-4"></div>
      <div class="bg-slate-900/50 rounded-xl p-4 mb-4">
        <h3 class="text-xs font-semibold text-slate-400 mb-2">排名分組 — 超額報酬比較</h3>
        <div style="position:relative; height:280px"><canvas data-bind="rank-chart"></canvas></div>
      </div>
      <div>
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-xs font-semibold text-slate-400">信號明細</h3>
          <button data-action="toggle-signals" class="text-xs text-slate-500 hover:text-slate-300 transition">展開/收合</button>
        </div>
        <div data-bind="signals" class="overflow-x-auto max-h-96 overflow-y-auto hidden"></div>
      </div>
    `;
    this._el = {};
    container.querySelectorAll('[data-bind]').forEach(el => { this._el[el.dataset.bind] = el; });
    container.querySelector('[data-action="toggle-signals"]')
      ?.addEventListener('click', () => this._el.signals.classList.toggle('hidden'));
  }

  async activate() {
    super.activate();
    if (!this._loaded) await this.reload();
  }

  invalidate() { this._loaded = false; }

  unmount() {
    if (this._rankChart) { this._rankChart.destroy(); this._rankChart = null; }
    super.unmount();
  }

  async reload() {
    this._el.summary.innerHTML = '<div class="text-center text-slate-500 text-sm py-8">載入回測資料中…</div>';
    try {
      const data = await this._api.getBacktest();
      this._renderSummary(data.summary, data.period, data.config);
      this._renderHorizon(data.summary.by_horizon, data.config.forward_days);
      this._renderRankChart(data.summary.by_rank_group, data.config.forward_days);
      this._renderSignals(data.signals);
      this._loaded = true;
    } catch (err) {
      console.error('Backtest load failed:', err);
      this._el.summary.innerHTML = '<div class="text-center text-red-400 text-sm py-8">回測資料載入失敗</div>';
    }
  }

  _renderSummary(summary, period, config) {
    const horizons = Object.entries(summary.by_horizon || {});
    const best = horizons.length
      ? horizons.reduce((a, b) => (b[1].avg_excess > a[1].avg_excess ? b : a))
      : null;
    const cards = [
      { label: '信號總數', value: summary.total_signals.toLocaleString(), color: 'text-blue-400' },
      { label: '回測天數', value: period.trading_days, color: 'text-slate-300' },
      { label: '篩選 Top', value: config.top_n, color: 'text-slate-300' },
    ];
    if (best) {
      const ex = best[1].avg_excess;
      cards.push(
        { label: `最佳天期 ${best[0]}天`, value: `${ex>=0?'+':''}${ex}%`, color: ex >= 0 ? 'text-green-400' : 'text-red-400' },
        { label: `勝率(${best[0]}天)`, value: `${best[1].win_rate}%`, color: best[1].win_rate >= 50 ? 'text-green-400' : 'text-amber-400' },
      );
    }
    this._el.summary.innerHTML = `
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        ${cards.map(c => `
          <div class="bg-slate-900/60 rounded-xl p-3 text-center border border-slate-700/50">
            <div class="text-xs text-slate-500 mb-1">${c.label}</div>
            <div class="text-lg font-bold tabular-nums ${c.color}">${c.value}</div>
          </div>`).join('')}
      </div>
      <div class="flex flex-wrap gap-2 mt-2">
        <span class="text-xs text-slate-500 bg-slate-900/40 px-2 py-0.5 rounded">${period.start} ~ ${period.end}</span>
        <span class="text-xs text-slate-500 bg-slate-900/40 px-2 py-0.5 rounded">隔日開盤買入</span>
        <span class="text-xs text-slate-500 bg-slate-900/40 px-2 py-0.5 rounded">前瞻天數: ${config.forward_days.join(', ')} 天</span>
      </div>`;
  }

  _renderHorizon(byHorizon, forwardDays) {
    if (!byHorizon || !forwardDays) return;
    const days = forwardDays.map(String);
    const rows = days.map(d => {
      const h = byHorizon[d];
      if (!h?.count) return '';
      const retColor = h.avg_return >= 0 ? 'text-green-400' : 'text-red-400';
      const medColor = h.median_return >= 0 ? 'text-green-400' : 'text-red-400';
      const exColor = h.avg_excess >= 0 ? 'text-green-400' : 'text-red-400';
      const wrColor = h.win_rate >= 50 ? 'text-green-400' : 'text-amber-400';
      return `<tr class="border-b border-slate-700/30 hover:bg-slate-700/20">
        <td class="py-2 px-3 font-medium text-slate-200">${d} 天</td>
        <td class="py-2 px-3 text-right tabular-nums text-slate-400">${h.count.toLocaleString()}</td>
        <td class="py-2 px-3 text-right tabular-nums font-medium ${retColor}">${h.avg_return>=0?'+':''}${h.avg_return}%</td>
        <td class="py-2 px-3 text-right tabular-nums ${medColor}">${h.median_return>=0?'+':''}${h.median_return}%</td>
        <td class="py-2 px-3 text-right tabular-nums ${wrColor}">${h.win_rate}%</td>
        <td class="py-2 px-3 text-right tabular-nums text-slate-400">${h.avg_benchmark>=0?'+':''}${h.avg_benchmark}%</td>
        <td class="py-2 px-3 text-right tabular-nums font-bold ${exColor}">${h.avg_excess>=0?'+':''}${h.avg_excess}%</td>
      </tr>`;
    }).join('');
    this._el.horizon.innerHTML = `
      <div class="bg-slate-900/50 rounded-xl p-4">
        <h3 class="text-xs font-semibold text-slate-400 mb-3">前瞻報酬率統計</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-xs">
            <thead><tr class="text-slate-500 border-b border-slate-700">
              <th class="py-1.5 px-3 text-left font-medium">持有天數</th>
              <th class="py-1.5 px-3 text-right font-medium">信號數</th>
              <th class="py-1.5 px-3 text-right font-medium">平均報酬</th>
              <th class="py-1.5 px-3 text-right font-medium">中位數</th>
              <th class="py-1.5 px-3 text-right font-medium">勝率</th>
              <th class="py-1.5 px-3 text-right font-medium">大盤報酬</th>
              <th class="py-1.5 px-3 text-right font-medium">超額報酬</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
  }

  _renderRankChart(byRankGroup, forwardDays) {
    if (this._rankChart) { this._rankChart.destroy(); this._rankChart = null; }
    this._rankChart = renderBacktestRankChart(this._el['rank-chart'], byRankGroup, forwardDays);
  }

  _renderSignals(signals) {
    if (!signals?.length) {
      this._el.signals.innerHTML = '<div class="text-slate-500 text-sm text-center py-4">無信號資料</div>';
      return;
    }
    const recent = signals.slice(-100).reverse();
    const fwdKeys = Object.keys(signals[0].returns).sort((a, b) => a - b);
    this._el.signals.innerHTML = `
      <div class="text-xs text-slate-500 mb-2">顯示最近 ${recent.length} / ${signals.length} 筆信號</div>
      <table class="w-full text-xs">
        <thead><tr class="text-slate-500 border-b border-slate-700">
          <th class="py-1.5 px-2 text-left font-medium">信號日</th>
          <th class="py-1.5 px-2 text-left font-medium">代號</th>
          <th class="py-1.5 px-2 text-left font-medium">名稱</th>
          <th class="py-1.5 px-2 text-center font-medium">排名</th>
          <th class="py-1.5 px-2 text-right font-medium">分數</th>
          <th class="py-1.5 px-2 text-right font-medium">買入價</th>
          ${fwdKeys.map(d => `<th class="py-1.5 px-2 text-right font-medium">${d}天</th>`).join('')}
        </tr></thead>
        <tbody>${recent.map(s => {
          const sym = stripSuffix(s.symbol);
          const rankColor = s.rank <= 5 ? 'text-blue-400 font-bold' : s.rank <= 10 ? 'text-cyan-400' : 'text-slate-400';
          return `<tr class="border-b border-slate-700/30 hover:bg-slate-700/20">
            <td class="py-1.5 px-2 text-slate-400 tabular-nums">${s.signal_date.slice(5)}</td>
            <td class="py-1.5 px-2 font-mono font-bold text-slate-200">${sym}</td>
            <td class="py-1.5 px-2 text-slate-300">${s.name}</td>
            <td class="py-1.5 px-2 text-center tabular-nums ${rankColor}">#${s.rank}</td>
            <td class="py-1.5 px-2 text-right tabular-nums text-slate-300">${s.score}</td>
            <td class="py-1.5 px-2 text-right tabular-nums text-slate-300">$${s.entry_price}</td>
            ${fwdKeys.map(d => {
              const r = s.returns[d];
              if (r == null) return '<td class="py-1.5 px-2 text-right text-slate-600">–</td>';
              const color = r >= 0 ? 'text-green-400' : 'text-red-400';
              return `<td class="py-1.5 px-2 text-right tabular-nums ${color}">${r>=0?'+':''}${r}%</td>`;
            }).join('')}
          </tr>`;
        }).join('')}</tbody>
      </table>`;
  }
}
