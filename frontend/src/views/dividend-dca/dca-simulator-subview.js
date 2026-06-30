// 內層 sub-view：DCA 定期定額模擬器。
//
// 左輸入面板（每月金額、年期、DRIP/領現金、起始日）+ 右輸出面板（摘要 + 折線圖 + 退休現金流）。
// 對照標的固定 0050。輸入變動 debounce 300ms 自動重算。

import { View } from '../../core/view.js';
import { eventBus } from '../../core/event-bus.js';
import { escHtml } from '../../services/formatters.js';
import { stripSuffix } from '../../services/ticker-utils.js';
import { renderEtfDcaChart } from '../../components/charts/etf-dca-chart.js';

const BENCHMARK_SYMBOL = '0050.TW';

function fmtTWD(v) {
  if (v == null) return '–';
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)} 億`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(1)} 萬`;
  return v.toLocaleString();
}

function todayIso() {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}

function yearsAgoIso(years) {
  const d = new Date();
  d.setFullYear(d.getFullYear() - years);
  return d.toISOString().slice(0, 10);
}

export class DcaSimulatorSubView extends View {
  constructor({ apiClient, parent }) {
    super();
    this._api = apiClient;
    this._parent = parent;
    this._symbol = null;
    this._chart = null;
    this._debounceTimer = null;
    this._inputs = {
      monthly_amount: 10000,
      years: 5,
      drip: true,
      start_date: yearsAgoIso(5),
    };
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = '<div data-bind="content"></div>';
    this._el = { content: container.querySelector('[data-bind="content"]') };
  }

  async activate(params = {}) {
    super.activate(params);
    const symbol = params.symbol || this._symbol;
    if (!symbol) {
      this._el.content.innerHTML = '<div class="text-slate-500 text-center py-10">請先從列表選一檔 ETF</div>';
      return;
    }
    if (symbol !== this._symbol) {
      this._symbol = symbol;
      this._renderShell();
    }
    await this._runSimulation();
  }

  deactivate() {
    super.deactivate();
    clearTimeout(this._debounceTimer);
    this._destroyChart();
  }

  unmount() {
    clearTimeout(this._debounceTimer);
    this._destroyChart();
    super.unmount();
  }

  _renderShell() {
    const sym = stripSuffix(this._symbol);
    this._el.content.innerHTML = `
      <div class="space-y-4">
        <div class="flex items-center justify-between flex-wrap gap-3">
          <div>
            <div class="text-lg font-bold text-slate-100">
              <span class="font-mono">${sym}</span>
              <span class="text-slate-400 text-sm ml-2">定期定額模擬</span>
            </div>
            <div class="text-xs text-slate-500 mt-0.5">對照標的：${stripSuffix(BENCHMARK_SYMBOL)} 元大台灣 50（含息）</div>
          </div>
          <button data-action="back-to-detail" class="text-xs px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300">← 回詳情</button>
        </div>

        <div class="grid md:grid-cols-3 gap-4">
          <!-- 左：輸入 -->
          <div class="bg-slate-900/40 rounded-xl p-4 md:col-span-1">
            <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">⚙️ 輸入</h3>

            <div class="mb-4">
              <label class="text-xs text-slate-500 mb-1 block">每月投入</label>
              <input data-bind="monthly" type="range" min="1000" max="100000" step="1000" value="${this._inputs.monthly_amount}"
                     class="w-full accent-emerald-500">
              <div class="text-right text-sm text-emerald-400 tabular-nums mt-1">
                $<span data-bind="monthly-val">${this._inputs.monthly_amount.toLocaleString()}</span>
              </div>
            </div>

            <div class="mb-4">
              <label class="text-xs text-slate-500 mb-1 block">投入期間（年）</label>
              <input data-bind="years" type="range" min="1" max="20" step="1" value="${this._inputs.years}"
                     class="w-full accent-emerald-500">
              <div class="text-right text-sm text-emerald-400 tabular-nums mt-1">
                <span data-bind="years-val">${this._inputs.years}</span> 年
              </div>
            </div>

            <div class="mb-4">
              <label class="text-xs text-slate-500 mb-2 block">股息處理</label>
              <div class="flex gap-2">
                <label class="flex-1 cursor-pointer">
                  <input type="radio" name="drip" value="true" ${this._inputs.drip ? 'checked' : ''} class="peer hidden" data-bind="drip-yes">
                  <div class="text-xs text-center py-2 rounded-lg border peer-checked:bg-emerald-700 peer-checked:border-emerald-600 peer-checked:text-white border-slate-700 text-slate-400">
                    再投入 (DRIP)
                  </div>
                </label>
                <label class="flex-1 cursor-pointer">
                  <input type="radio" name="drip" value="false" ${!this._inputs.drip ? 'checked' : ''} class="peer hidden" data-bind="drip-no">
                  <div class="text-xs text-center py-2 rounded-lg border peer-checked:bg-slate-700 peer-checked:border-slate-600 peer-checked:text-white border-slate-700 text-slate-400">
                    領現金
                  </div>
                </label>
              </div>
            </div>

            <div class="mb-2">
              <label class="text-xs text-slate-500 mb-1 block">起始日</label>
              <input data-bind="start-date" type="date" value="${this._inputs.start_date}" max="${todayIso()}"
                     class="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200">
            </div>
            <div class="text-[11px] text-slate-500">期間自動為「起始日 + 年期」或今天，取較早者。</div>
          </div>

          <!-- 右：輸出 -->
          <div class="md:col-span-2 space-y-3">
            <div data-bind="summary"></div>
            <div class="bg-slate-900/40 rounded-xl p-4">
              <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">📈 累積市值對照</h3>
              <div class="relative" style="height:300px">
                <canvas data-bind="dca-chart"></canvas>
              </div>
            </div>
            <div data-bind="cashflow"></div>
          </div>
        </div>
      </div>
    `;

    this._cacheBindings();
    this._bindEvents();
  }

  _cacheBindings() {
    const c = this._el.content;
    this._b = {
      monthly:     c.querySelector('[data-bind="monthly"]'),
      monthlyVal:  c.querySelector('[data-bind="monthly-val"]'),
      years:       c.querySelector('[data-bind="years"]'),
      yearsVal:    c.querySelector('[data-bind="years-val"]'),
      dripYes:     c.querySelector('[data-bind="drip-yes"]'),
      dripNo:      c.querySelector('[data-bind="drip-no"]'),
      startDate:   c.querySelector('[data-bind="start-date"]'),
      summary:     c.querySelector('[data-bind="summary"]'),
      cashflow:    c.querySelector('[data-bind="cashflow"]'),
      dcaCanvas:   c.querySelector('[data-bind="dca-chart"]'),
    };
  }

  _bindEvents() {
    this._b.monthly.addEventListener('input', () => {
      this._inputs.monthly_amount = +this._b.monthly.value;
      this._b.monthlyVal.textContent = this._inputs.monthly_amount.toLocaleString();
      this._schedule();
    });
    this._b.years.addEventListener('input', () => {
      this._inputs.years = +this._b.years.value;
      this._b.yearsVal.textContent = this._inputs.years;
      this._inputs.start_date = yearsAgoIso(this._inputs.years);
      this._b.startDate.value = this._inputs.start_date;
      this._schedule();
    });
    [this._b.dripYes, this._b.dripNo].forEach(el => {
      el.addEventListener('change', () => {
        this._inputs.drip = this._b.dripYes.checked;
        this._schedule();
      });
    });
    this._b.startDate.addEventListener('change', () => {
      this._inputs.start_date = this._b.startDate.value;
      this._schedule();
    });

    this._el.content.addEventListener('click', e => {
      const back = e.target.closest('[data-action="back-to-detail"]');
      if (back) {
        eventBus.emit('navigate', {
          view: 'dividend-dca',
          params: { subtab: 'detail', symbol: this._symbol },
        });
      }
    });
  }

  _schedule() {
    clearTimeout(this._debounceTimer);
    this._debounceTimer = setTimeout(() => this._runSimulation(), 300);
  }

  async _runSimulation() {
    if (!this._b) return;
    this._b.summary.innerHTML = '<div class="text-slate-500 text-sm py-4 text-center">計算中…</div>';
    this._parent.setStatus('模擬計算中…');
    try {
      const data = await this._api.simulateEtfDca({
        symbol: this._symbol,
        monthly_amount: this._inputs.monthly_amount,
        start_date: this._inputs.start_date,
        end_date: todayIso(),
        drip: this._inputs.drip,
        benchmark: BENCHMARK_SYMBOL,
      });
      this._parent.setStatus('');
      this._render(data);
    } catch (err) {
      this._b.summary.innerHTML = `<div class="text-red-400 text-sm py-4 text-center">模擬失敗：${escHtml(err.message)}</div>`;
      this._parent.setStatus('模擬失敗');
    }
  }

  _render(data) {
    const t = data.target;
    const b = data.benchmark;
    if (!t) {
      this._b.summary.innerHTML = '<div class="text-amber-400 text-sm py-4 text-center">沒有可用的資料</div>';
      return;
    }

    const r = (v, cls = 'text-slate-200') =>
      v == null ? '–' : `<span class="${cls} tabular-nums">${v.toFixed(2)}%</span>`;

    const targetSym = stripSuffix(t.symbol);
    const benchSym = b ? stripSuffix(b.symbol) : null;

    this._b.summary.innerHTML = `
      <div class="bg-slate-900/40 rounded-xl p-4">
        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">💼 結果摘要</h3>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div>
            <div class="text-slate-500 mb-0.5">累積投入</div>
            <div class="text-base text-slate-200 tabular-nums">${fmtTWD(t.total_invested)}</div>
          </div>
          <div>
            <div class="text-slate-500 mb-0.5">期末市值</div>
            <div class="text-base text-emerald-400 tabular-nums">${fmtTWD(t.total_value)}</div>
          </div>
          <div>
            <div class="text-slate-500 mb-0.5">含息年化 (CAGR)</div>
            <div class="text-base">${r(t.cagr_pct, 'text-emerald-400')}</div>
          </div>
          <div>
            <div class="text-slate-500 mb-0.5">XIRR</div>
            <div class="text-base">${r(t.xirr_pct, 'text-slate-200')}</div>
          </div>
          ${this._inputs.drip ? '' : `
          <div>
            <div class="text-slate-500 mb-0.5">期間累積領息</div>
            <div class="text-base text-amber-400 tabular-nums">${fmtTWD(t.cash_dividends_received)}</div>
          </div>`}
          <div class="${this._inputs.drip ? 'col-span-2 md:col-span-3' : 'col-span-2 md:col-span-2'}">
            <div class="text-slate-500 mb-0.5">同期 ${benchSym || '0050'} 對照</div>
            <div class="text-sm text-slate-300 tabular-nums">
              ${b ? `期末 ${fmtTWD(b.total_value)} (年化 ${b.cagr_pct?.toFixed(2) ?? '–'}%)` : '對照資料不可用'}
            </div>
          </div>
        </div>
        <div class="text-[11px] text-slate-500 mt-3">區間 ${t.period}</div>
      </div>
    `;

    // 退休現金流
    const monthlyIncome = t.estimated_monthly_income_now;
    this._b.cashflow.innerHTML = `
      <div class="bg-slate-900/40 rounded-xl p-4">
        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">💰 退休現金流預估</h3>
        <div class="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
          <div>
            <div class="text-slate-500 mb-0.5">目前持股</div>
            <div class="text-sm text-slate-200 tabular-nums">${t.shares?.toLocaleString(undefined, { maximumFractionDigits: 0 })} 股</div>
          </div>
          <div>
            <div class="text-slate-500 mb-0.5">預估月領（依近一年月均配息）</div>
            <div class="text-lg font-bold text-emerald-400 tabular-nums">${monthlyIncome != null ? '$' + monthlyIncome.toLocaleString() : '–'}</div>
          </div>
          <div>
            <div class="text-slate-500 mb-0.5">預估年領</div>
            <div class="text-sm text-slate-200 tabular-nums">${monthlyIncome != null ? '$' + (monthlyIncome * 12).toLocaleString() : '–'}</div>
          </div>
        </div>
        <div class="text-[11px] text-slate-500 mt-2">＊ 假設未來配息維持近一年水準，不考慮減配風險與通膨。</div>
      </div>
    `;

    // 圖
    this._destroyChart();
    this._chart = renderEtfDcaChart(this._b.dcaCanvas, t, b);
  }

  _destroyChart() {
    this._chart?.destroy?.();
    this._chart = null;
  }
}
