// 個股分析 view。
//
// 職責：拉取 /api/stock-insights，渲染 score / price header / 各 chart / 估值表 / 同業比較 / 自選股比較。
//
// 生命週期：
//   - mount：建立模板 DOM、綁定 overlay/period/event-bus 監聽
//   - activate({ symbol, period }?)：刷新資料；symbol 可由 URL 帶入或 event 觸發
//   - deactivate：暫停（保留 DOM；下次 activate 才重抓）
//   - unmount：destroy 所有 Chart instance，避免記憶體洩漏
//
// 與其他模組的耦合：
//   - 透過 apiClient 取得資料（介面注入，未來換 API 不必動本檔）
//   - 訂閱 eventBus 'ticker:analyze'（sidebar / header 廣播）
//   - 訂閱 eventBus 'mock:change' / 'ticker:add'
//   - 透過 stateStore 更新 currentTicker，供 sidebar 高亮使用

import { View } from '../core/view.js';
import { eventBus } from '../core/event-bus.js';
import { stateStore } from '../services/state-store.js';
import { stripSuffix } from '../services/ticker-utils.js';
import { fmtCap } from '../services/formatters.js';
import { renderScoreDonut } from '../components/charts/score-donut.js';
import { renderCandlestick, renderVolume } from '../components/charts/price-charts.js';
import { renderRSI, renderMACD, renderKD, renderOBV } from '../components/charts/indicator-charts.js';
import {
  renderAnnualGrowth, renderDividendHistory, renderPeHistory,
} from '../components/charts/fundamental-charts.js';
import { renderRelativePerformance } from '../components/charts/comparison-chart.js';
import { bindActiveOverlays } from '../components/charts/chart-plugins.js';
import { STOCK_VIEW_TEMPLATE } from './stock-view-template.js';

export class StockView extends View {
  constructor({ apiClient, watchlistStore }) {
    super();
    this._api = apiClient;
    this._watchlist = watchlistStore;

    this._charts = {};               // 集中管理 chart instance
    this._activeOverlays = new Set(['ma5', 'ma10', 'ma20', 'patterns']);
    this._currentData = null;
    this._unsubs = [];                // event-bus 取消訂閱函式
    this._el = {};                    // [data-bind=*] 查詢結果

    bindActiveOverlays(() => this._activeOverlays);
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = STOCK_VIEW_TEMPLATE;
    this._cacheBindings(container);
    this._bindControls();
    this._subscribeEvents();
  }

  async activate(params = {}) {
    super.activate(params);
    const symbol = params.symbol || stateStore.currentTicker;
    if (symbol) await this._analyze(symbol);
  }

  deactivate() {
    super.deactivate();
  }

  unmount() {
    this._unsubs.forEach(u => u());
    this._unsubs = [];
    this._destroyAllCharts();
    super.unmount();
  }

  // ── DOM 查詢與快取 ────────────────────────────────────────────────
  _cacheBindings(root) {
    root.querySelectorAll('[data-bind]').forEach(el => {
      this._el[el.dataset.bind] = el;
    });
    this._sections = {};
    root.querySelectorAll('[data-section]').forEach(el => {
      this._sections[el.dataset.section] = el;
    });
  }

  _bindControls() {
    this._el['period-btns']?.addEventListener('click', e => {
      const btn = e.target.closest('[data-p]');
      if (!btn || btn.dataset.p === stateStore.currentPeriod) return;
      this._setPeriod(btn.dataset.p);
      this._reloadChartsForPeriod();
    });

    this._el['overlay-chips']?.addEventListener('click', e => {
      const chip = e.target.closest('.indicator-chip');
      if (!chip) return;
      const key = chip.dataset.key;
      chip.classList.toggle('active');
      if (this._activeOverlays.has(key)) this._activeOverlays.delete(key);
      else this._activeOverlays.add(key);
      if (this._currentData) {
        this._destroyChart('priceChart');
        this._destroyChart('volumeChart');
        this._charts.priceChart = renderCandlestick(this._el['price-chart'], this._currentData.kline, this._currentData.indicators, this._currentData.patterns, this._activeOverlays);
        this._charts.volumeChart = renderVolume(this._el['volume-chart'], this._currentData.kline);
      }
    });
  }

  _subscribeEvents() {
    this._unsubs.push(eventBus.on('ticker:analyze', ({ symbol }) => this._analyze(symbol)));
    this._unsubs.push(eventBus.on('ticker:add', ({ symbol }) => this._watchlist.add(symbol)));
    this._unsubs.push(eventBus.on('mock:change', () => {
      if (this.active) this._analyze(stateStore.currentTicker);
    }));
  }

  _setPeriod(p) {
    stateStore.set('currentPeriod', p);
    this._el['period-btns']?.querySelectorAll('.period-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.p === p);
    });
  }

  // ── 主要流程：fetch + render ─────────────────────────────────────
  async _analyze(rawSymbol) {
    if (!rawSymbol) return;
    stateStore.set('currentTicker', rawSymbol);
    this._showSection('loading');

    try {
      const data = await this._api.getStockInsights(rawSymbol, stateStore.currentPeriod, { signal: this.requestSignal('analyze') });
      this._currentData = data;
      this._renderAll(data);
      this._showSection('dashboard');
      this._updateWatchlistQuote(rawSymbol, data);
    } catch (err) {
      if (err.name === 'AbortError') return;
      this._el['error-msg'].textContent = `Error: ${err.message}`;
      this._showSection('error');
    }
  }

  async _reloadChartsForPeriod() {
    this._el['chart-loading']?.classList.remove('hidden');
    try {
      const ticker = stateStore.currentTicker;
      const data = await this._api.getStockChart(ticker, stateStore.currentPeriod, { signal: this.requestSignal('chart') });
      this._currentData.kline = data.kline;
      this._currentData.indicators = data.indicators;
      this._currentData.period = data.period;
      this._renderTechnicals(this._currentData);
    } catch (err) {
      if (err.name === 'AbortError') return;
      console.error('Period switch failed:', err);
    } finally {
      this._el['chart-loading']?.classList.add('hidden');
    }
  }

  _showSection(name) {
    Object.entries(this._sections).forEach(([k, el]) => {
      el.classList.toggle('hidden', k !== name);
    });
  }

  // ── Render：分散到多個 _render* 私有方法，單一職責 ──────────────────
  _renderAll(d) {
    this._renderScore(d.score, d.commentary);
    this._renderPriceHeader(d.latest_quote, d.is_mock, d.fundamentals);
    this._renderTechnicals(d);
    this._renderPatterns(d.patterns);
    this._renderFundamentals(d.fundamentals);
    this._loadPeerComparison();
    this._loadWatchlistComparison();
  }

  _renderTechnicals(d) {
    this._destroyChart('priceChart');
    this._destroyChart('volumeChart');
    this._destroyChart('rsiChart');
    this._destroyChart('macdChart');
    this._destroyChart('kdChart');
    this._destroyChart('obvChart');
    this._charts.priceChart  = renderCandlestick(this._el['price-chart'], d.kline, d.indicators, d.patterns, this._activeOverlays);
    this._charts.volumeChart = renderVolume(this._el['volume-chart'], d.kline);
    this._charts.rsiChart    = renderRSI(this._el['rsi-chart'], d.kline, d.indicators);
    this._charts.macdChart   = renderMACD(this._el['macd-chart'], d.kline, d.indicators);
    this._charts.kdChart     = renderKD(this._el['kd-chart'], d.kline, d.indicators);
    this._charts.obvChart    = renderOBV(this._el['obv-chart'], d.kline, d.indicators);
    this._renderMAAlignment(d.indicators);
  }

  _renderScore(score, commentary) {
    if (!score) { this._el['score-card'].classList.add('hidden'); return; }
    this._el['score-card'].classList.remove('hidden');

    const val = score.composite;
    const grade = score.grade || {};
    const color = grade.color || '#f59e0b';

    this._destroyChart('scoreDonut');
    this._charts.scoreDonut = renderScoreDonut(this._el['score-donut'], val, color);

    this._el['score-number'].textContent = val;
    this._el['score-number'].style.color = color;
    this._el['score-label'].textContent = `${grade.label || ''} ${grade.label_en || ''}`;

    const subs = [
      { label: '技術面', score: score.technical?.score ?? 0, weight: score.weights_used?.technical ?? 0 },
      { label: '基本面', score: score.fundamental?.score ?? 0, weight: score.weights_used?.fundamental ?? 0 },
    ];
    this._el['sub-scores'].innerHTML = subs.map(s => {
      const pct = s.score;
      const barColor = pct >= 61 ? '#22c55e' : pct >= 41 ? '#f59e0b' : '#ef4444';
      const weightPct = Math.round((s.weight || 0) * 100);
      return `
        <div>
          <div class="flex justify-between items-center mb-1">
            <span class="text-xs text-slate-400">${s.label} <span class="text-slate-600">${weightPct}%</span></span>
            <span class="text-xs font-bold tabular-nums" style="color:${barColor}">${pct}</span>
          </div>
          <div class="h-1.5 rounded-full bg-slate-700 overflow-hidden">
            <div class="h-1.5 rounded-full transition-all duration-500" style="width:${pct}%;background:${barColor}"></div>
          </div>
        </div>`;
    }).join('');

    const cEl = this._el['commentary-text'];
    if (commentary) {
      cEl.textContent = commentary;
      this._el['commentary-box'].classList.remove('hidden');
    } else {
      cEl.textContent = 'AI 研判暫時不可用';
      cEl.classList.add('text-slate-500');
    }
  }

  _renderPriceHeader(q, isMock, fund) {
    this._el['h-symbol'].textContent = q.symbol;
    this._el['h-currency'].textContent = q.currency || 'USD';
    this._el['h-price'].textContent = `$${q.current_price.toFixed(2)}`;
    this._el['h-prev'].textContent = `$${q.previous_close.toFixed(2)}`;
    const diff = q.current_price - q.previous_close;
    const pct = (diff / q.previous_close) * 100;
    const sign = diff >= 0 ? '+' : '';
    this._el['h-change'].textContent = `${sign}$${diff.toFixed(2)} (${sign}${pct.toFixed(2)}%)`;
    this._el['h-change'].className = `text-lg font-semibold ${diff >= 0 ? 'text-green-400' : 'text-red-400'}`;
    this._el['h-mcap'].textContent = fmtCap(q.market_cap);
    this._el['h-mock-tag'].classList.toggle('hidden', !isMock);
    if (fund?.summary) {
      this._el['h-sector'].textContent = fund.summary.sector || '';
      this._el['h-52h'].textContent = fund.summary.fifty_two_week_high ? `$${fund.summary.fifty_two_week_high}` : '–';
      this._el['h-52l'].textContent = fund.summary.fifty_two_week_low ? `$${fund.summary.fifty_two_week_low}` : '–';
      this._el['h-beta'].textContent = fund.summary.beta ?? '–';
    }
  }

  _renderMAAlignment(indicators) {
    const el = this._el['h-ma-align'];
    const a = indicators?.ma_alignment;
    if (!a?.label || a.label === '資料不足') { el.classList.add('hidden'); return; }
    el.textContent = a.label;
    el.style.color = a.color;
    el.style.borderColor = a.color;
    el.style.backgroundColor = (a.color || '#94a3b8') + '15';
    el.classList.remove('hidden');
  }

  _renderPatterns(patterns) {
    const card = this._el['patterns-card'];
    const list = this._el['patterns-list'];
    if (!patterns?.length) { card.classList.add('hidden'); list.innerHTML = ''; return; }
    card.classList.remove('hidden');
    const sorted = [...patterns].sort((a, b) => b.date.localeCompare(a.date));
    list.innerHTML = sorted.slice(0, 8).map(p => {
      const icon = p.direction === 'bullish' ? '▲' : p.direction === 'bearish' ? '▼' : '◆';
      return `<div class="flex items-start gap-2 px-2.5 py-1.5 rounded-lg border" style="border-color:${p.color}40;background:${p.color}10">
        <span class="text-sm leading-none mt-0.5" style="color:${p.color}">${icon}</span>
        <div class="flex-1 min-w-0">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs font-bold" style="color:${p.color}">${p.label}</span>
            <span class="text-[10px] text-slate-500 tabular-nums">${p.date}</span>
          </div>
          <div class="text-[11px] text-slate-400 leading-snug mt-0.5">${p.description}</div>
        </div>
      </div>`;
    }).join('');
  }

  _renderFundamentals(fund) {
    if (!fund) return;
    this._renderValuationGrid(fund);
    this._renderProfitabilityGrid(fund);
    this._renderDividendGrid(fund);
    this._renderQuarterlyBars(fund);
    this._renderAnnualGrowthCard(fund);
    this._renderDividendHistoryCard(fund);
    this._renderPeHistoryCard(fund);
  }

  _renderValuationGrid(fund) {
    const v = fund.valuation || {}, ps = fund.per_share || {};
    const items = [
      ['P/E (TTM)', v.pe_ratio], ['Forward P/E', v.forward_pe], ['P/B', v.pb_ratio],
      ['P/S', v.ps_ratio], ['PEG', v.peg_ratio],
      ['EPS (TTM)', ps.eps_ttm ? `$${ps.eps_ttm}` : null],
      ['EPS (Fwd)', ps.eps_forward ? `$${ps.eps_forward}` : null],
      ['Book Value', ps.book_value ? `$${ps.book_value}` : null],
      ['Rev/Share', ps.revenue_per_share ? `$${ps.revenue_per_share}` : null],
    ];
    this._el['valuation-grid'].innerHTML = items.map(([l, v]) =>
      `<div><div class="fund-label">${l}</div><div class="fund-value">${v ?? '–'}</div></div>`
    ).join('');
  }

  _renderProfitabilityGrid(fund) {
    const p = fund.profitability || {};
    const items = [
      ['ROE', p.roe, '%'], ['ROA', p.roa, '%'],
      ['Profit Margin', p.profit_margin, '%'], ['Gross Margin', p.gross_margin, '%'],
      ['Operating Margin', p.operating_margin, '%'],
    ];
    this._el['profit-grid'].innerHTML = items.map(([l, v, s]) => {
      const d = v != null ? `${v}${s}` : '–';
      const c = v != null ? (v >= 20 ? 'text-green-400' : v >= 10 ? 'text-amber-400' : 'text-red-400') : '';
      return `<div><div class="fund-label">${l}</div><div class="fund-value ${c}">${d}</div></div>`;
    }).join('');
  }

  _renderDividendGrid(fund) {
    const d = fund.dividend || {};
    const items = [
      ['Yield', d.dividend_yield != null ? `${d.dividend_yield}%` : null],
      ['Annual Rate', d.dividend_rate != null ? `$${d.dividend_rate}` : null],
      ['Payout Ratio', d.payout_ratio != null ? `${d.payout_ratio}%` : null],
      ['Ex-Div Date', d.ex_dividend_date],
    ];
    this._el['dividend-grid'].innerHTML = items.map(([l, v]) =>
      `<div><div class="fund-label">${l}</div><div class="fund-value">${v ?? '–'}</div></div>`
    ).join('');
  }

  _renderQuarterlyBars(fund) {
    const el = this._el['quarterly-bars'];
    if (!fund?.quarterly_financials?.length) {
      el.innerHTML = '<div class="text-slate-500 text-sm text-center py-4">無季度數據</div>';
      return;
    }
    const q = [...fund.quarterly_financials].reverse();
    const maxRev = Math.max(...q.map(x => x.revenue || 0));
    el.innerHTML = q.map(x => {
      const r = x.revenue || 0, ni = x.net_income || 0;
      const pct = maxRev > 0 ? (r / maxRev * 100) : 0;
      const m = r > 0 ? (ni / r * 100).toFixed(1) : '–';
      return `<div><div class="flex justify-between text-xs mb-1"><span class="text-slate-400">${x.period}</span><span class="text-slate-200 font-semibold tabular-nums">${fmtCap(r)} <span class="text-slate-500 font-normal">/ ${m}% margin</span></span></div><div class="h-2 rounded-full bg-slate-700 overflow-hidden"><div class="quarter-bar h-2 rounded-full bg-blue-500" style="width:${pct}%"></div></div></div>`;
    }).join('');
  }

  _renderAnnualGrowthCard(fund) {
    const card = this._el['annual-growth-card'];
    this._destroyChart('annualGrowthChart');
    const chart = renderAnnualGrowth(this._el['annual-growth-chart'], fund.annual_revenue_growth);
    if (!chart) { card.classList.add('hidden'); return; }
    card.classList.remove('hidden');
    this._charts.annualGrowthChart = chart;
  }

  _renderDividendHistoryCard(fund) {
    const card = this._el['dividend-history-card'];
    const badge = this._el['dividend-consecutive-badge'];
    this._destroyChart('dividendHistoryChart');
    const chart = renderDividendHistory(this._el['dividend-history-chart'], fund.dividend_history);
    if (!chart) { card.classList.add('hidden'); badge.classList.add('hidden'); return; }
    card.classList.remove('hidden');
    this._charts.dividendHistoryChart = chart;
    const years = fund.dividend_consecutive_years || 0;
    if (years > 0) { badge.textContent = `連續 ${years} 年配息`; badge.classList.remove('hidden'); }
    else { badge.classList.add('hidden'); }
  }

  _renderPeHistoryCard(fund) {
    const card = this._el['pe-history-card'];
    const badge = this._el['pe-percentile-badge'];
    this._destroyChart('peHistoryChart');
    const chart = renderPeHistory(this._el['pe-history-chart'], fund.pe_history);
    if (!chart) { card.classList.add('hidden'); return; }
    card.classList.remove('hidden');
    this._charts.peHistoryChart = chart;
    const peHist = fund.pe_history;
    const p = peHist.current_percentile;
    if (p != null) {
      const color = p < 30 ? '#22c55e' : p < 70 ? '#f59e0b' : '#ef4444';
      badge.textContent = `當前 PE ${peHist.current_pe} / 歷史 ${p}%`;
      badge.style.color = color;
      badge.style.borderColor = color;
      badge.style.backgroundColor = color + '20';
    } else {
      badge.textContent = '–';
    }
  }

  // ── 同業 / 自選股比較 ─────────────────────────────────────────────
  async _loadPeerComparison() {
    try {
      const data = await this._api.getPeerComparison(stateStore.currentTicker, stateStore.currentPeriod, { signal: this.requestSignal('peer') });
      this._destroyChart('peerChart');
      this._charts.peerChart = renderRelativePerformance(this._el['peer-chart'], data.relative_performance);
      this._renderComparisonTable(this._el['peer-table'], data.comparison_table);
    } catch (e) {
      if (e.name === 'AbortError') return;
      console.warn('Peer comparison failed:', e);
    }
  }

  async _loadWatchlistComparison() {
    const tickers = this._watchlist.list();
    if (!tickers.length) return;
    try {
      const data = await this._api.getWatchlistComparison(tickers, stateStore.currentPeriod, { signal: this.requestSignal('watchlist-cmp') });
      this._destroyChart('wlPerfChart');
      this._charts.wlPerfChart = renderRelativePerformance(this._el['watchlist-perf-chart'], data.relative_performance);
      this._renderComparisonTable(this._el['watchlist-table'], data.comparison_table);
    } catch (e) {
      if (e.name === 'AbortError') return;
      console.warn('Watchlist comparison failed:', e);
    }
  }

  _renderComparisonTable(container, rows) {
    if (!rows?.length) return;
    const headers = ['代號', '評分', 'P/E', 'ROE', 'Margin', '市值', '報酬率', '殖利率', 'Beta'];
    container.innerHTML = `
      <table class="w-full text-xs">
        <thead><tr class="text-slate-500 border-b border-slate-700">
          ${headers.map(h => `<th class="py-1.5 px-2 text-left font-medium">${h}</th>`).join('')}
        </tr></thead>
        <tbody>${rows.map(r => {
          if (r.error) return '';
          const highlight = r.is_target ? 'bg-blue-500/10 font-bold' : r.is_index ? 'text-slate-500 italic' : '';
          const retColor = (r.return_period || 0) >= 0 ? 'text-green-400' : 'text-red-400';
          const sym = stripSuffix(r.symbol);
          const sc = r.score;
          const scoreColor = sc != null ? (sc >= 61 ? '#22c55e' : sc >= 41 ? '#f59e0b' : '#ef4444') : '';
          return `<tr class="${highlight} border-b border-slate-700/50 hover:bg-slate-700/30">
            <td class="py-1.5 px-2 font-mono">${sym}${r.is_index ? ' 📊' : ''}</td>
            <td class="py-1.5 px-2 tabular-nums font-bold" style="color:${scoreColor}">${sc ?? '–'}</td>
            <td class="py-1.5 px-2 tabular-nums">${r.pe ?? '–'}</td>
            <td class="py-1.5 px-2 tabular-nums">${r.roe != null ? r.roe + '%' : '–'}</td>
            <td class="py-1.5 px-2 tabular-nums">${r.margin != null ? r.margin + '%' : '–'}</td>
            <td class="py-1.5 px-2 tabular-nums">${fmtCap(r.mcap)}</td>
            <td class="py-1.5 px-2 tabular-nums ${retColor}">${r.return_period != null ? (r.return_period >= 0 ? '+' : '') + r.return_period + '%' : '–'}</td>
            <td class="py-1.5 px-2 tabular-nums">${r.yield != null ? r.yield + '%' : '–'}</td>
            <td class="py-1.5 px-2 tabular-nums">${r.beta ?? '–'}</td>
          </tr>`;
        }).join('')}</tbody>
      </table>`;
  }

  _updateWatchlistQuote(symbol, data) {
    if (!data.latest_quote || !this._watchlist.has(symbol)) return;
    const q = data.latest_quote;
    const diff = q.current_price - q.previous_close;
    const pct = q.previous_close ? (diff / q.previous_close) * 100 : 0;
    this._watchlist.setQuote(symbol, {
      symbol,
      current_price: q.current_price,
      previous_close: q.previous_close,
      change: Math.round(diff * 100) / 100,
      change_pct: Math.round(pct * 100) / 100,
      currency: q.currency || 'USD',
      market_cap: q.market_cap,
      error: null,
    });
  }

  // ── Chart 生命週期管理 ───────────────────────────────────────────
  _destroyChart(key) {
    if (this._charts[key]) {
      this._charts[key].destroy();
      this._charts[key] = null;
    }
  }

  _destroyAllCharts() {
    Object.keys(this._charts).forEach(k => this._destroyChart(k));
  }
}
