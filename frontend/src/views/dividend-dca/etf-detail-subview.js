// 內層 sub-view：ETF 詳情頁。
//
// 五個 section：概覽 / 績效 / 配息 / 持股；
// 主動式 ETF 歷史 < 1 年時，3Y/5Y 報酬自動隱藏。

import { View } from '../../core/view.js';
import { eventBus } from '../../core/event-bus.js';
import { escHtml } from '../../services/formatters.js';
import { stripSuffix } from '../../services/ticker-utils.js';
import { renderEtfDividendChart } from '../../components/charts/etf-dividend-chart.js';
import { renderEtfPerformanceChart } from '../../components/charts/etf-performance-chart.js';
import { renderEtfHoldingsChart, renderEtfSectorChart } from '../../components/charts/etf-holdings-chart.js';

const FREQ_LABEL = { 1: '月配', 3: '季配', 6: '半年配', 12: '年配', 2: '半年配' };

const CATEGORY_LABELS = {
  core: '核心高股息', monthly: '月配息', factor: '因子型',
  active: '主動式', benchmark: '對照組',
};

export class EtfDetailSubView extends View {
  constructor({ apiClient, parent }) {
    super();
    this._api = apiClient;
    this._parent = parent;
    this._symbol = null;
    this._loaded = false;
    this._charts = {};
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = '<div data-bind="content"></div>';
    this._el = { content: container.querySelector('[data-bind="content"]') };

    this._el.content.addEventListener('click', e => {
      const back = e.target.closest('[data-action="back-to-list"]');
      if (back) {
        eventBus.emit('navigate', { view: 'dividend-dca', params: { subtab: 'list' } });
        return;
      }
      const sim = e.target.closest('[data-action="goto-simulator"]');
      if (sim) {
        eventBus.emit('navigate', {
          view: 'dividend-dca',
          params: { subtab: 'simulator', symbol: this._symbol },
        });
      }
    });
  }

  async activate(params = {}) {
    super.activate(params);
    const symbol = params.symbol || this._symbol;
    if (!symbol) {
      this._el.content.innerHTML = '<div class="text-slate-500 text-center py-10">請從列表選一檔 ETF</div>';
      return;
    }
    if (symbol !== this._symbol || !this._loaded) {
      this._symbol = symbol;
      this._loaded = false;
      await this.reload();
    }
  }

  deactivate() {
    super.deactivate();
    this._destroyCharts();
  }

  unmount() {
    this._destroyCharts();
    super.unmount();
  }

  async reload() {
    this._destroyCharts();
    this._el.content.innerHTML = '<div class="text-slate-500 text-sm text-center py-10">載入中…</div>';
    this._parent.setStatus('載入詳情中…');
    try {
      const data = await this._api.getEtfDetail(this._symbol, { signal: this.signal() });
      this._loaded = true;
      this._parent.setStatus('');
      this._render(data);
    } catch (err) {
      if (err.name === 'AbortError') return;
      this._el.content.innerHTML = `<div class="text-red-400 text-sm text-center py-6">載入失敗：${escHtml(err.message)}</div>`;
      this._parent.setStatus('載入失敗');
    }
  }

  _render(d) {
    const m = d.meta || {};
    const sym = stripSuffix(m.symbol || this._symbol);
    const isActive = !!m.is_active;
    const navPrice = m.nav_price != null ? `$${m.nav_price.toFixed(2)}` : '–';
    const yieldStr = m.yield_rate != null ? (m.yield_rate * 100).toFixed(2) + '%' : '–';
    const aum = m.aum
      ? m.aum >= 1e11 ? `${(m.aum / 1e11).toFixed(1)} 千億`
        : m.aum >= 1e8 ? `${(m.aum / 1e8).toFixed(0)} 億` : `$${m.aum.toLocaleString()}`
      : '–';

    this._el.content.innerHTML = `
      <div class="space-y-5">
        <!-- Header -->
        <div class="flex items-start justify-between flex-wrap gap-3">
          <div>
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-2xl font-bold font-mono text-slate-100">${sym}</span>
              <span class="text-lg text-slate-300">${escHtml(m.name_zh || '')}</span>
              ${isActive ? '<span class="px-2 py-0.5 text-xs rounded bg-amber-900/40 text-amber-300">⚡ 主動式</span>' : ''}
            </div>
            <div class="text-xs text-slate-500 mt-1">NAV ${navPrice}　殖利率 ${yieldStr}　規模 ${aum}</div>
          </div>
          <div class="flex gap-2">
            <button data-action="back-to-list" class="text-xs px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300">← 回列表</button>
            <button data-action="goto-simulator" class="text-xs px-3 py-1.5 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white">模擬定期定額 →</button>
          </div>
        </div>

        <!-- 1. 概覽 -->
        ${this._renderOverview(m)}

        <!-- 2. 績效 -->
        ${this._renderPerformance(d.performance || {}, isActive)}

        <!-- 3. 配息 -->
        ${this._renderDividends(d.dividends || {})}

        <!-- 4. 持股 -->
        ${this._renderHoldings(d.holdings || {})}
      </div>
    `;

    // 等 DOM 落地後 render charts
    this._renderCharts(d);
  }

  _renderOverview(m) {
    const inception = m.inception_date || '–';
    const fee = m.expense_ratio != null ? (m.expense_ratio * 100).toFixed(2) + '%' : '–';
    const freq = FREQ_LABEL[m.payout_frequency] || '–';
    const idx = m.tracking_index || (m.is_active ? '（主動式，不追蹤指數）' : '–');

    return `
      <section class="bg-slate-900/40 rounded-xl p-4">
        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">📋 概覽</h3>
        <div class="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
          ${this._kv('追蹤指數', escHtml(idx))}
          ${this._kv('配息頻率', freq)}
          ${this._kv('費用率', fee)}
          ${this._kv('分類', CATEGORY_LABELS[m.category] || m.category)}
          ${this._kv('成立日', inception)}
          ${this._kv('發行商', escHtml(m.fund_family || '–'))}
        </div>
      </section>`;
  }

  _renderPerformance(p, isActive) {
    const hideLong = isActive; // 主動式 ETF 通常歷史 < 1 年
    const r = (v) => v == null ? '–' : `<span class="${v >= 0 ? 'text-green-400' : 'text-red-400'}">${v >= 0 ? '+' : ''}${v.toFixed(2)}%</span>`;
    const n = (v, suffix = '') => v == null ? '–' : `${v.toFixed(2)}${suffix}`;

    return `
      <section class="bg-slate-900/40 rounded-xl p-4">
        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">📈 績效（含息）</h3>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mb-4">
          ${this._kv('1Y 年化', r(p.return_1y_pct))}
          ${hideLong ? '' : this._kv('3Y 年化', r(p.return_3y_pct))}
          ${hideLong ? '' : this._kv('5Y 年化', r(p.return_5y_pct))}
          ${this._kv('成立至今', r(p.return_since_inception_pct))}
          ${this._kv('最大回撤', r(p.mdd_pct))}
          ${this._kv('年化波動度', n(p.volatility_pct, '%'))}
          ${this._kv('Sharpe', n(p.sharpe))}
          ${this._kv('資料區間', `${p.history_start || '–'} → ${p.history_end || '–'}`)}
        </div>
        <div class="relative" style="height:240px">
          <canvas data-bind="perf-chart"></canvas>
        </div>
      </section>`;
  }

  _renderDividends(div) {
    const latest = div.monthly_dividend_latest != null ? `$${div.monthly_dividend_latest.toFixed(4)}` : '–';
    const avg12m = div.monthly_dividend_avg_12m != null ? `$${div.monthly_dividend_avg_12m.toFixed(4)}` : '–';
    const delta = div.latest_vs_avg_pct;
    const deltaText = delta == null ? ''
      : delta >= 0
        ? `<span class="text-green-400">▲ 比近一年高 ${delta.toFixed(1)}%</span>`
        : `<span class="text-red-400">▼ 比近一年低 ${Math.abs(delta).toFixed(1)}%</span>`;
    const latestSrc = div.latest_dividend != null
      ? `最新一期 $${div.latest_dividend.toFixed(2)}（${div.latest_ex_date}，${FREQ_LABEL[div.payout_frequency] || ''}）/ ${div.payout_frequency || 1}`
      : '無配息資料';

    const recent = (div.history || []).slice(-12).reverse();
    const rows = recent.map(d => `
      <tr class="border-b border-slate-700/50">
        <td class="py-1.5 px-2 text-slate-300">${d.ex_date}</td>
        <td class="py-1.5 px-2 text-right tabular-nums text-slate-200">$${d.dividend.toFixed(4)}</td>
      </tr>`).join('');

    return `
      <section class="bg-slate-900/40 rounded-xl p-4">
        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">💵 配息</h3>
        <div class="bg-slate-800 rounded-lg p-4 mb-4">
          <div class="text-xs text-slate-500 mb-1">每股月化配息（最新一期推算）</div>
          <div class="flex items-baseline gap-4 flex-wrap">
            <div class="text-2xl font-bold text-emerald-400 tabular-nums">${latest}</div>
            <div class="text-xs text-slate-500">${latestSrc}</div>
          </div>
          <div class="text-xs text-slate-400 mt-2">
            近一年月均 <span class="tabular-nums text-slate-300">${avg12m}</span>　${deltaText}
          </div>
        </div>
        <div class="grid md:grid-cols-2 gap-4">
          <div class="relative" style="height:200px">
            <canvas data-bind="div-chart"></canvas>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead><tr class="text-slate-500 border-b border-slate-700">
                <th class="py-1.5 px-2 text-left font-medium">除息日</th>
                <th class="py-1.5 px-2 text-right font-medium">每股配息</th>
              </tr></thead>
              <tbody>${rows || '<tr><td colspan="2" class="text-slate-500 text-center py-3">無配息紀錄</td></tr>'}</tbody>
            </table>
          </div>
        </div>
      </section>`;
  }

  _renderHoldings(h) {
    const top = h.top || [];
    const sectors = h.sectors || [];
    const top10Pct = top.slice(0, 10).reduce((s, x) => s + (x.weight || 0), 0);
    const top1Pct = top[0]?.weight || 0;

    return `
      <section class="bg-slate-900/40 rounded-xl p-4">
        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">📊 持股</h3>
        <div class="grid md:grid-cols-2 gap-4 mb-3">
          <div>
            <div class="text-xs text-slate-500 mb-2">前 10 大持股</div>
            <div class="relative" style="height:240px">
              <canvas data-bind="holdings-chart"></canvas>
            </div>
          </div>
          <div>
            <div class="text-xs text-slate-500 mb-2">產業分布</div>
            <div class="relative" style="height:240px">
              <canvas data-bind="sector-chart"></canvas>
            </div>
          </div>
        </div>
        <div class="text-xs text-slate-500">
          Top 10 集中度 <span class="text-slate-300">${(top10Pct * 100).toFixed(1)}%</span>　|
          最大持股 <span class="text-slate-300">${(top1Pct * 100).toFixed(2)}%</span>　|
          ${h.snapshot_at ? `快照時間 ${h.snapshot_at.slice(0, 10)}` : ''}
        </div>
      </section>`;
  }

  _kv(label, value) {
    return `<div>
      <div class="text-slate-500 text-[11px] mb-0.5">${label}</div>
      <div class="text-slate-200 tabular-nums">${value}</div>
    </div>`;
  }

  _renderCharts(d) {
    const ph = d.performance?.price_history || [];
    const divHist = d.dividends?.history || [];
    const top = d.holdings?.top || [];
    const sectors = d.holdings?.sectors || [];

    const perfCanvas = this._el.content.querySelector('[data-bind="perf-chart"]');
    if (perfCanvas && ph.length) {
      this._charts.perf = renderEtfPerformanceChart(perfCanvas, ph);
    }
    const divCanvas = this._el.content.querySelector('[data-bind="div-chart"]');
    if (divCanvas && divHist.length) {
      this._charts.div = renderEtfDividendChart(divCanvas, divHist);
    }
    const holdCanvas = this._el.content.querySelector('[data-bind="holdings-chart"]');
    if (holdCanvas && top.length) {
      this._charts.hold = renderEtfHoldingsChart(holdCanvas, top);
    }
    const sectCanvas = this._el.content.querySelector('[data-bind="sector-chart"]');
    if (sectCanvas && sectors.length) {
      this._charts.sect = renderEtfSectorChart(sectCanvas, sectors);
    }
  }

  _destroyCharts() {
    for (const c of Object.values(this._charts)) c?.destroy?.();
    this._charts = {};
  }
}
