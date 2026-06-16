// ── Config ──────────────────────────────────────────────────────────────────
const MA_COLORS = { ma5: '#f59e0b', ma10: '#3b82f6', ma20: '#a855f7', ma60: '#ec4899' };
const BB_COLOR = '#06b6d4';

// ── State ────────────────────────────────────────────────────────────────────
let isMock = true;  // always default to MOCK on page load; toggle is runtime-only, not persisted
let currentPeriod = '3M';
let currentTicker = 'AAPL';
let currentData = null;          // full API response (cached)
let priceChart = null, volumeChart = null, rsiChart = null, macdChart = null;
let kdChart = null, obvChart = null;
let annualGrowthChart = null, dividendHistoryChart = null, peHistoryChart = null;
let activeOverlays = new Set(['ma5','ma10','ma20','patterns']);
let sidebarOpen = true;

// ── Watchlist state ──────────────────────────────────────────────────────────
const WL_KEY = 'stock-insights-watchlist';
let watchlist = JSON.parse(localStorage.getItem(WL_KEY) || '["AAPL","TSLA","NVDA"]');
let wlQuotes = {};  // { symbol: { current_price, change, change_pct, ... } }

function saveWatchlist() { localStorage.setItem(WL_KEY, JSON.stringify(watchlist)); }

function toggleSidebar() {
  sidebarOpen = !sidebarOpen;
  document.getElementById('wl-sidebar').classList.toggle('collapsed', !sidebarOpen);
}

function addCurrentToWatchlist() {
  const t = document.getElementById('ticker-input').value.trim().toUpperCase();
  if (t) addToWatchlist(t);
}

function addFromInput() {
  const inp = document.getElementById('wl-add-input');
  const t = inp.value.trim().toUpperCase();
  if (t) { addToWatchlist(t); inp.value = ''; }
}

function addToWatchlist(ticker) {
  const normalized = normalizeTicker(ticker);
  if (watchlist.includes(normalized)) return;
  watchlist.push(normalized);
  saveWatchlist();
  refreshWatchlist();
}

function removeFromWatchlist(ticker) {
  watchlist = watchlist.filter(t => t !== ticker);
  saveWatchlist();
  renderWatchlist();
}

function normalizeTicker(raw) {
  const t = raw.toUpperCase().trim();
  if (t.includes('.')) return t;
  if (/^\d+$/.test(t)) {
    if (t.length === 4 || t.length === 5) return t + '.TW';
    if (t.length === 6) return (t.startsWith('6') ? t + '.SS' : t + '.SZ');
  }
  return t;
}

async function refreshWatchlist() {
  if (!watchlist.length) { renderWatchlist(); return; }
  const icon = document.getElementById('wl-refresh-icon');
  icon.classList.add('spin');
  try {
    const res = await fetch(`/api/batch-quotes?tickers=${watchlist.join(',')}&mock=${isMock}`);
    if (res.ok) {
      const data = await res.json();
      wlQuotes = {};
      for (const q of data.quotes) { if (!q.error) wlQuotes[q.symbol] = q; }
    }
  } catch (e) { console.warn('Watchlist refresh failed:', e); }
  icon.classList.remove('spin');
  renderWatchlist();
}

function renderWatchlist() {
  const list = document.getElementById('wl-list');
  if (!watchlist.length) {
    list.innerHTML = '<div class="px-3 py-6 text-center text-xs text-slate-500">尚未加入自選股<br>使用 + 按鈕新增</div>';
    return;
  }
  list.innerHTML = watchlist.map(ticker => {
    const q = wlQuotes[ticker];
    const active = ticker === currentTicker ? ' active' : '';
    const price = q ? `$${q.current_price.toFixed(2)}` : '–';
    const change = q ? `${q.change >= 0 ? '+' : ''}${q.change.toFixed(2)}` : '';
    const pct = q ? `${q.change_pct >= 0 ? '+' : ''}${q.change_pct.toFixed(2)}%` : '';
    const color = q ? (q.change >= 0 ? 'text-green-400' : 'text-red-400') : 'text-slate-500';
    const displayTicker = ticker.replace(/\.(TW|SS|SZ)$/, '');
    return `
      <div class="wl-row flex items-center px-3 py-2.5 cursor-pointer${active}"
           onclick="switchToStock('${ticker}')">
        <div class="flex-1 min-w-0">
          <div class="text-sm font-bold text-slate-200 truncate">${displayTicker}</div>
          <div class="text-xs ${color} tabular-nums">${change} (${pct})</div>
        </div>
        <div class="text-right shrink-0 mr-2">
          <div class="text-sm font-semibold text-slate-100 tabular-nums">${price}</div>
        </div>
        <button onclick="event.stopPropagation(); removeFromWatchlist('${ticker}')"
          class="p-0.5 rounded hover:bg-red-500/20 transition" title="移除">
          <svg class="w-3.5 h-3.5 text-slate-600 hover:text-red-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
      </div>`;
  }).join('');
}

function switchToStock(ticker) {
  currentTicker = ticker;
  document.getElementById('ticker-input').value = ticker.replace(/\.(TW|SS|SZ)$/, (m) => m);
  setPeriod('3M');  // E2 fix: reset period to default when switching stocks
  analyze();
}

// Single source of truth for period state — keeps DOM active class and
// currentPeriod variable in sync, so they can never drift apart.
function setPeriod(p) {
  currentPeriod = p;
  document.querySelectorAll('.period-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.p === p);
  });
}

// ── Period controls (FIXED: only update charts, not full page) ───────────────
document.getElementById('period-btns').addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-p]');
  if (!btn || btn.dataset.p === currentPeriod) return;
  setPeriod(btn.dataset.p);

  // Show inline chart loading (NOT full page loading)
  document.getElementById('chart-loading').classList.remove('hidden');

  try {
    const ticker = document.getElementById('ticker-input').value.trim().toUpperCase();
    const res = await fetch(`/api/stock-chart?ticker=${ticker}&period=${currentPeriod}&mock=${isMock}`);
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();

    // Only update chart data — fundamentals untouched
    currentData.kline = data.kline;
    currentData.indicators = data.indicators;
    currentData.period = data.period;

    // Only re-render charts (patterns are kept from initial full load)
    renderCandlestick(currentData.kline, currentData.indicators, currentData.patterns);
    renderVolume(currentData.kline);
    renderRSI(currentData.kline, currentData.indicators);
    renderMACD(currentData.kline, currentData.indicators);
    renderKD(currentData.kline, currentData.indicators);
    renderOBV(currentData.kline, currentData.indicators);
    renderMAAlignment(currentData.indicators);
  } catch (e) {
    console.error('Period switch failed:', e);
  }

  document.getElementById('chart-loading').classList.add('hidden');
});

// Overlay toggles — pure client-side, no API call
document.getElementById('overlay-chips').addEventListener('click', e => {
  const chip = e.target.closest('.indicator-chip');
  if (!chip) return;
  const key = chip.dataset.key;
  chip.classList.toggle('active');
  if (activeOverlays.has(key)) activeOverlays.delete(key); else activeOverlays.add(key);
  if (currentData) { renderCandlestick(currentData.kline, currentData.indicators, currentData.patterns); renderVolume(currentData.kline); }
});

// ── Mock toggle ──────────────────────────────────────────────────────────────
function toggleMock() {
  isMock = !isMock;
  backtestLoaded = false;  // force re-fetch on mode switch
  document.getElementById('toggle-track').className = `w-10 h-5 rounded-full transition-colors duration-200 ${isMock ? 'bg-amber-500' : 'bg-slate-600'}`;
  document.getElementById('toggle-dot').className = `absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${isMock ? 'translate-x-5' : 'translate-x-0'}`;
  document.getElementById('mock-badge').className = `text-xs font-semibold px-2.5 py-1 rounded-full border ${isMock ? 'bg-amber-500/15 text-amber-400 border-amber-500/30' : 'bg-slate-700 text-slate-500 border-slate-600'}`;
  document.getElementById('mock-badge').textContent = isMock ? 'MOCK' : 'LIVE';
  refreshWatchlist();
  loadScreener();
  // Re-load backtest if the tab is currently visible
  if (!document.getElementById('panel-backtest').classList.contains('hidden')) {
    loadBacktest();
  }
}

function syncMockUI() {
  document.getElementById('toggle-track').className = `w-10 h-5 rounded-full transition-colors duration-200 ${isMock ? 'bg-amber-500' : 'bg-slate-600'}`;
  document.getElementById('toggle-dot').className = `absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${isMock ? 'translate-x-5' : 'translate-x-0'}`;
  document.getElementById('mock-badge').className = `text-xs font-semibold px-2.5 py-1 rounded-full border ${isMock ? 'bg-amber-500/15 text-amber-400 border-amber-500/30' : 'bg-slate-700 text-slate-500 border-slate-600'}`;
  document.getElementById('mock-badge').textContent = isMock ? 'MOCK' : 'LIVE';
}

// ── UI state helpers ─────────────────────────────────────────────────────────
function showState(state) {
  ['loading','error','dashboard'].forEach(s => {
    const el = document.getElementById(`state-${s}`) || document.getElementById(s);
    if (el) { el.classList.add('hidden'); el.classList.remove('flex'); }
  });
  const el = document.getElementById(`state-${state}`) || document.getElementById(state);
  if (el) { el.classList.remove('hidden'); }
}

// ── API (full analyze) ───────────────────────────────────────────────────────
async function analyze() {
  const ticker = document.getElementById('ticker-input').value.trim().toUpperCase();
  if (!ticker) return;
  currentTicker = normalizeTicker(ticker);

  showState('loading');
  try {
    const res = await fetch(`/api/stock-insights?ticker=${ticker}&period=${currentPeriod}&mock=${isMock}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    currentData = await res.json();
    renderDashboard(currentData);
    showState('dashboard');

    // Update this stock's quote in watchlist from the fresh data
    if (currentData.latest_quote && watchlist.includes(currentTicker)) {
      const q = currentData.latest_quote;
      const diff = q.current_price - q.previous_close;
      const pct = q.previous_close ? (diff / q.previous_close) * 100 : 0;
      wlQuotes[currentTicker] = {
        symbol: currentTicker,
        current_price: q.current_price,
        previous_close: q.previous_close,
        change: Math.round(diff * 100) / 100,
        change_pct: Math.round(pct * 100) / 100,
        currency: q.currency || 'USD',
        market_cap: q.market_cap,
        error: null,
      };
    }
    renderWatchlist(); // update active highlight + fresh quote
  } catch (e) {
    document.getElementById('error-msg').textContent = `Error: ${e.message}`;
    showState('error');
  }
}

// ── Render: full dashboard ───────────────────────────────────────────────────
let scoreDonut = null;

function renderDashboard(d) {
  renderScore(d.score, d.commentary);
  renderRisk(d.risk);
  renderPriceHeader(d.latest_quote, d.is_mock, d.fundamentals);
  renderCandlestick(d.kline, d.indicators, d.patterns);
  renderVolume(d.kline);
  renderRSI(d.kline, d.indicators);
  renderMACD(d.kline, d.indicators);
  renderKD(d.kline, d.indicators);
  renderOBV(d.kline, d.indicators);
  renderMAAlignment(d.indicators);
  renderPatterns(d.patterns);
  renderAnnualGrowth(d.fundamentals);
  renderDividendHistory(d.fundamentals);
  renderPeHistory(d.fundamentals);
  renderValuation(d.fundamentals);
  renderProfitability(d.fundamentals);
  renderDividend(d.fundamentals);
  renderQuarterly(d.fundamentals);

  // Load comparison data (non-blocking)
  loadPeerComparison();
  loadWatchlistComparison();
}

// ── Render: composite score ───────────────────────────────────────────────────
function renderScore(score, commentary) {
  if (!score) { document.getElementById('score-card').classList.add('hidden'); return; }
  document.getElementById('score-card').classList.remove('hidden');

  const val = score.composite;
  const grade = score.grade || {};
  const color = grade.color || '#f59e0b';

  // Donut chart
  if (scoreDonut) scoreDonut.destroy();
  const ctx = document.getElementById('score-donut').getContext('2d');
  scoreDonut = new Chart(ctx, {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [val, 100 - val],
        backgroundColor: [color, '#1e293b'],
        borderWidth: 0,
        cutout: '78%',
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      animation: { duration: 600, easing: 'easeOutQuart' },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    },
  });

  // Score text
  document.getElementById('score-number').textContent = val;
  document.getElementById('score-number').style.color = color;
  document.getElementById('score-label').textContent = `${grade.label || ''} ${grade.label_en || ''}`;

  // Sub-score bars
  const subs = [
    { label: '技術面', score: score.technical?.score ?? 0, weight: score.weights_used?.technical ?? 0 },
    { label: '基本面', score: score.fundamental?.score ?? 0, weight: score.weights_used?.fundamental ?? 0 },
  ];
  document.getElementById('sub-scores').innerHTML = subs.map(s => {
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

  // Commentary
  const commentaryEl = document.getElementById('commentary-text');
  if (commentary) {
    commentaryEl.textContent = commentary;
    document.getElementById('commentary-box').classList.remove('hidden');
  } else {
    commentaryEl.textContent = 'AI 研判暫時不可用';
    commentaryEl.classList.add('text-slate-500');
  }
}

// ── Render: risk metrics ─────────────────────────────────────────────────────
function renderRisk(risk) {
  const card = document.getElementById('risk-card');
  if (!risk) { card.classList.add('hidden'); return; }
  card.classList.remove('hidden');

  // Warnings (B7: technical risk alerts)
  const warningsBox = document.getElementById('risk-warnings');
  const warnings = risk.warnings || [];
  if (warnings.length === 0) {
    warningsBox.classList.add('hidden');
    warningsBox.innerHTML = '';
  } else {
    warningsBox.classList.remove('hidden');
    warningsBox.innerHTML = warnings.map(w => {
      const bg = (w.color || '#f97316') + '20';
      return `<div class="flex items-start gap-2 px-3 py-2 rounded-lg border" style="border-color:${w.color};background:${bg}">
        <span class="text-base leading-none mt-0.5">⚠️</span>
        <div>
          <div class="text-xs font-bold" style="color:${w.color}">${w.label}</div>
          <div class="text-xs text-slate-300 mt-0.5">${w.description}</div>
        </div>
      </div>`;
    }).join('');
  }

  // HV level badge
  const level = risk.volatility?.level || { label: '–', color: '#64748b' };
  const badge = document.getElementById('risk-hv-badge');
  badge.textContent = level.label;
  badge.style.color = level.color;
  badge.style.borderColor = level.color + '80';
  badge.style.backgroundColor = level.color + '20';

  // Volatility block
  const hv20 = risk.volatility?.hv_20d;
  const hv60 = risk.volatility?.hv_60d;
  document.getElementById('risk-volatility').innerHTML = `
    <div class="flex justify-between items-baseline">
      <span class="text-xs text-slate-400">20 日 HV</span>
      <span class="text-xl font-bold tabular-nums">${hv20 != null ? hv20 + '%' : '<span class="text-slate-600 text-sm">–</span>'}</span>
    </div>
    <div class="flex justify-between items-baseline">
      <span class="text-xs text-slate-400">60 日 HV</span>
      <span class="text-xl font-bold tabular-nums ${hv60==null?'text-slate-600':''}">${hv60 != null ? hv60 + '%' : '<span class="text-xs text-slate-600">資料不足</span>'}</span>
    </div>
  `;

  // Drawdown block
  const dd = risk.drawdown || {};
  const ddEl = document.getElementById('risk-drawdown');
  if (dd.mdd_pct == null) {
    ddEl.innerHTML = '<span class="text-slate-600 text-sm">資料不足</span>';
  } else {
    const ddColor = dd.mdd_pct <= -30 ? '#ef4444' : dd.mdd_pct <= -15 ? '#f59e0b' : '#22c55e';
    const recovery = dd.recovered
      ? `<span class="text-green-400">已回復 (${dd.recovery_days} 日)</span>`
      : `<span class="text-amber-400">尚未回復</span>`;
    ddEl.innerHTML = `
      <div class="text-2xl font-extrabold tabular-nums mb-1" style="color:${ddColor}">${dd.mdd_pct}%</div>
      <div class="text-xs text-slate-500">${dd.peak_date} → ${dd.trough_date}</div>
      <div class="text-xs text-slate-400 mt-1">距高點: <strong class="tabular-nums text-slate-200">${dd.current_drawdown_pct}%</strong></div>
      <div class="text-xs mt-1">${recovery}</div>
    `;
  }

  // Current + ATR block
  const sug = risk.suggestions || {};
  document.getElementById('risk-current').innerHTML = `
    <div class="flex justify-between items-baseline mb-2">
      <span class="text-xs text-slate-400">當前價</span>
      <span class="text-xl font-bold tabular-nums">${sug.current_price != null ? '$' + sug.current_price : '–'}</span>
    </div>
    <div class="flex justify-between items-baseline">
      <span class="text-xs text-slate-400">ATR(14)</span>
      <span class="text-xl font-bold tabular-nums ${sug.atr_14==null?'text-slate-600':''}">${sug.atr_14 != null ? sug.atr_14.toFixed(2) : '–'}</span>
    </div>
    <p class="text-xs text-slate-600 mt-2">ATR = 平均真實波動，用於動態停損</p>
  `;

  // Four-method comparison table
  const methods = sug.methods || {};
  const order = ['atr_standard', 'atr_conservative', 'atr_aggressive', 'fixed_pct', 'bollinger', 'swing'];
  const tbody = document.getElementById('risk-methods-tbody');
  tbody.innerHTML = order.filter(k => methods[k]).map(k => {
    const m = methods[k];
    const rr = m.rr_ratio;
    const rrColor = rr == null ? 'text-slate-500' : rr >= 2 ? 'text-green-400' : rr >= 1 ? 'text-amber-400' : 'text-red-400';
    const stopCell = m.stop_loss != null ? `$${m.stop_loss}` : '–';
    const tgtCell = m.take_profit != null ? `$${m.take_profit}` : '–';
    const riskCell = m.risk_pct != null ? m.risk_pct.toFixed(2) + '%' : '–';
    const rewardCell = m.reward_pct != null ? '+' + m.reward_pct.toFixed(2) + '%' : '–';
    const rrCell = rr != null ? '1 : ' + rr.toFixed(2) : '–';
    return `
      <tr class="border-b border-slate-800 hover:bg-slate-900/30">
        <td class="py-2 px-2 text-slate-300">${m.label}</td>
        <td class="py-2 px-2 text-right tabular-nums text-red-400">${stopCell}</td>
        <td class="py-2 px-2 text-right tabular-nums text-green-400">${tgtCell}</td>
        <td class="py-2 px-2 text-right tabular-nums text-slate-400">${riskCell}</td>
        <td class="py-2 px-2 text-right tabular-nums text-slate-400">${rewardCell}</td>
        <td class="py-2 px-2 text-right tabular-nums font-bold ${rrColor}">${rrCell}</td>
      </tr>
    `;
  }).join('') || '<tr><td colspan="6" class="py-3 text-center text-slate-600 text-xs">資料不足，無法計算</td></tr>';
}

// ── Render: price header ─────────────────────────────────────────────────────
function renderPriceHeader(q, isMockData, fund) {
  document.getElementById('h-symbol').textContent = q.symbol;
  document.getElementById('h-currency').textContent = q.currency || 'USD';
  document.getElementById('h-price').textContent = `$${q.current_price.toFixed(2)}`;
  document.getElementById('h-prev').textContent = `$${q.previous_close.toFixed(2)}`;
  const diff = q.current_price - q.previous_close;
  const pct = (diff / q.previous_close) * 100;
  const sign = diff >= 0 ? '+' : '';
  const el = document.getElementById('h-change');
  el.textContent = `${sign}$${diff.toFixed(2)} (${sign}${pct.toFixed(2)}%)`;
  el.className = `text-lg font-semibold ${diff >= 0 ? 'text-green-400' : 'text-red-400'}`;
  document.getElementById('h-mcap').textContent = fmtCap(q.market_cap);
  document.getElementById('h-mock-tag').classList.toggle('hidden', !isMockData);
  if (fund && fund.summary) {
    document.getElementById('h-sector').textContent = fund.summary.sector || '';
    document.getElementById('h-52h').textContent = fund.summary.fifty_two_week_high ? `$${fund.summary.fifty_two_week_high}` : '–';
    document.getElementById('h-52l').textContent = fund.summary.fifty_two_week_low ? `$${fund.summary.fifty_two_week_low}` : '–';
    document.getElementById('h-beta').textContent = fund.summary.beta ?? '–';
  }
}

// ── Render: candlestick + overlays ───────────────────────────────────────────
const CandlestickPlugin = {
  id: 'candlestick',
  afterDatasetsDraw(chart) {
    const { ctx, scales: { x, y } } = chart;
    const klines = chart._klines;
    if (!klines) return;
    const meta = chart.getDatasetMeta(0);
    meta.data.forEach((bar, i) => {
      const k = klines[i]; if (!k || bar.x == null) return;
      const xc = bar.x;
      const bull = k.close >= k.open;
      const color = bull ? '#22c55e' : '#ef4444';
      const hw = Math.max(3, Math.min(7, Math.round(chart.width / klines.length * 0.3)));
      ctx.save();
      ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 1.5;
      ctx.moveTo(xc, y.getPixelForValue(k.high)); ctx.lineTo(xc, y.getPixelForValue(k.low)); ctx.stroke();
      const openY = y.getPixelForValue(k.open), closeY = y.getPixelForValue(k.close);
      const by = Math.min(openY, closeY), bh = Math.max(Math.abs(openY - closeY), 2);
      ctx.fillStyle = bull ? 'rgba(34,197,94,.75)' : 'rgba(239,68,68,.9)';
      ctx.fillRect(xc - hw, by, hw * 2, bh);
      ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.strokeRect(xc - hw, by, hw * 2, bh);
      ctx.restore();
    });
  }
};

// Pattern markers: triangles below bullish patterns, above bearish, dot for neutral
const PatternMarkerPlugin = {
  id: 'pattern-markers',
  afterDatasetsDraw(chart) {
    const patterns = chart._patterns;
    const klines = chart._klines;
    if (!patterns || !patterns.length || !klines) return;
    if (!activeOverlays.has('patterns')) return;
    const { ctx, scales: { y } } = chart;
    const meta = chart.getDatasetMeta(0);

    // Group by date to stack multiple patterns per bar
    const byDate = {};
    patterns.forEach(p => {
      const idx = klines.findIndex(k => k.date === p.date);
      if (idx < 0) return;
      if (!byDate[idx]) byDate[idx] = [];
      byDate[idx].push(p);
    });

    Object.entries(byDate).forEach(([idxStr, pats]) => {
      const idx = +idxStr;
      const bar = meta.data[idx];
      if (!bar) return;
      const xc = bar.x;
      const k = klines[idx];

      pats.forEach((p, stackI) => {
        const size = 6;
        const offset = 10 + stackI * (size * 2 + 2);
        ctx.save();
        ctx.fillStyle = p.color;
        if (p.direction === 'bullish') {
          const yPos = y.getPixelForValue(k.low) + offset;
          ctx.beginPath();
          ctx.moveTo(xc, yPos);
          ctx.lineTo(xc - size, yPos + size);
          ctx.lineTo(xc + size, yPos + size);
          ctx.closePath();
          ctx.fill();
        } else if (p.direction === 'bearish') {
          const yPos = y.getPixelForValue(k.high) - offset;
          ctx.beginPath();
          ctx.moveTo(xc, yPos);
          ctx.lineTo(xc - size, yPos - size);
          ctx.lineTo(xc + size, yPos - size);
          ctx.closePath();
          ctx.fill();
        } else {
          // neutral — small diamond above
          const yPos = y.getPixelForValue(k.high) - offset;
          ctx.beginPath();
          ctx.moveTo(xc, yPos - size/2);
          ctx.lineTo(xc + size/2, yPos);
          ctx.lineTo(xc, yPos + size/2);
          ctx.lineTo(xc - size/2, yPos);
          ctx.closePath();
          ctx.fill();
        }
        ctx.restore();
      });
    });
  }
};

function thinLabels(klines) {
  return klines.map((k, i) => {
    if (klines.length > 120) return i % 20 === 0 ? k.date.slice(5) : '';
    if (klines.length > 60)  return i % 10 === 0 ? k.date.slice(5) : '';
    if (klines.length > 30)  return i % 5  === 0 ? k.date.slice(5) : '';
    return k.date.slice(5);
  });
}

function renderCandlestick(klines, indicators, patterns) {
  if (priceChart) priceChart.destroy();
  const ctx = document.getElementById('price-chart').getContext('2d');
  const lo = Math.min(...klines.map(k => k.low)), hi = Math.max(...klines.map(k => k.high));
  const pad = (hi - lo) * 0.12;
  const datasets = [{ data: klines.map(k => [k.low, k.high]), backgroundColor: 'transparent', borderColor: 'transparent' }];
  if (indicators?.ma) {
    for (const [key, color] of Object.entries(MA_COLORS)) {
      if (activeOverlays.has(key) && indicators.ma[key])
        datasets.push({ type:'line', label:key.toUpperCase(), data:indicators.ma[key], borderColor:color, borderWidth:1.5, pointRadius:0, tension:0.3, spanGaps:true });
    }
  }
  if (activeOverlays.has('bb') && indicators?.bollinger) {
    datasets.push({ type:'line', label:'BB Upper', data:indicators.bollinger.upper, borderColor:BB_COLOR, borderWidth:1, borderDash:[4,3], pointRadius:0, tension:0.3, spanGaps:true, fill:false });
    datasets.push({ type:'line', label:'BB Lower', data:indicators.bollinger.lower, borderColor:BB_COLOR, borderWidth:1, borderDash:[4,3], pointRadius:0, tension:0.3, spanGaps:true, fill:'-1', backgroundColor:'rgba(6,182,212,.06)' });
  }
  priceChart = new Chart(ctx, {
    type:'bar', data:{ labels:thinLabels(klines), datasets },
    options:{
      responsive:true, maintainAspectRatio:false, animation:{duration:300},
      scales:{
        x:{grid:{color:'#1e293b'},ticks:{color:'#64748b',font:{size:10},maxRotation:0},border:{color:'#334155'}},
        y:{position:'right',min:lo-pad,max:hi+pad,grid:{color:'#1e293b80'},ticks:{color:'#64748b',font:{size:11},callback:v=>'$'+v.toFixed(1)},border:{color:'#334155'}},
      },
      plugins:{legend:{display:false},tooltip:{callbacks:{title:items=>klines[items[0].dataIndex]?.date||'',label:item=>{if(item.datasetIndex===0){const k=klines[item.dataIndex];return[`  Open  $${k.open.toFixed(2)}`,`  High  $${k.high.toFixed(2)}`,`  Low   $${k.low.toFixed(2)}`,`  Close $${k.close.toFixed(2)}`]}return`  ${item.dataset.label}: $${item.raw?.toFixed(2)??'–'}`}},backgroundColor:'#0f172a',borderColor:'#334155',borderWidth:1,titleColor:'#f1f5f9',bodyColor:'#94a3b8',padding:10}},
    },
    plugins:[CandlestickPlugin, PatternMarkerPlugin],
  });
  priceChart._klines = klines;
  priceChart._patterns = patterns || [];
}

function renderVolume(klines) {
  if (volumeChart) volumeChart.destroy();
  const ctx = document.getElementById('volume-chart').getContext('2d');
  volumeChart = new Chart(ctx, {
    type:'bar', data:{ labels:klines.map(()=>''), datasets:[{data:klines.map(k=>k.volume),backgroundColor:klines.map(k=>k.close>=k.open?'rgba(34,197,94,.45)':'rgba(239,68,68,.45)'),borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:300},scales:{x:{display:false},y:{display:true,position:'right',ticks:{color:'#475569',font:{size:9},callback:v=>fmtVol(v)},grid:{display:false},border:{display:false}}},plugins:{legend:{display:false},tooltip:{callbacks:{label:item=>`  Volume  ${fmtVol(item.raw)}`},backgroundColor:'#0f172a',borderColor:'#334155',borderWidth:1,bodyColor:'#94a3b8',padding:10}}},
  });
}

function renderRSI(klines, indicators) {
  if (rsiChart) rsiChart.destroy();
  if (!indicators?.rsi) return;
  const ctx = document.getElementById('rsi-chart').getContext('2d');
  rsiChart = new Chart(ctx, {
    type:'line', data:{ labels:thinLabels(klines), datasets:[{data:indicators.rsi,borderColor:'#a855f7',borderWidth:1.5,pointRadius:0,tension:0.3,spanGaps:true,fill:false}]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:300},scales:{x:{grid:{color:'#1e293b'},ticks:{color:'#64748b',font:{size:9},maxRotation:0},border:{color:'#334155'}},y:{position:'right',min:0,max:100,grid:{color:ctx2=>[30,70].includes(ctx2.tick.value)?'#475569':'#1e293b40'},ticks:{color:'#64748b',font:{size:10},stepSize:10},border:{color:'#334155'}}},plugins:{legend:{display:false},tooltip:{callbacks:{label:item=>`  RSI: ${item.raw?.toFixed(1)??'–'}`},backgroundColor:'#0f172a',borderColor:'#334155',borderWidth:1,bodyColor:'#94a3b8',padding:8}}},
    plugins:[{id:'rsi-zones',beforeDatasetsDraw(chart){const{ctx:c,chartArea:{left,right},scales:{y}}=chart;c.save();c.fillStyle='rgba(239,68,68,.06)';c.fillRect(left,y.getPixelForValue(100),right-left,y.getPixelForValue(70)-y.getPixelForValue(100));c.fillStyle='rgba(34,197,94,.06)';c.fillRect(left,y.getPixelForValue(30),right-left,y.getPixelForValue(0)-y.getPixelForValue(30));c.restore()}}],
  });
}

function renderMACD(klines, indicators) {
  if (macdChart) macdChart.destroy();
  if (!indicators?.macd) return;
  const ctx = document.getElementById('macd-chart').getContext('2d');
  const hist = indicators.macd.histogram || [];
  macdChart = new Chart(ctx, {
    type:'bar', data:{ labels:thinLabels(klines), datasets:[
      {data:hist.map(v=>v??0),backgroundColor:hist.map(v=>v===null?'transparent':v>=0?'rgba(34,197,94,.6)':'rgba(239,68,68,.6)'),borderWidth:0,order:2},
      {type:'line',label:'MACD',data:indicators.macd.macd,borderColor:'#3b82f6',borderWidth:1.5,pointRadius:0,tension:0.3,spanGaps:true,order:1},
      {type:'line',label:'Signal',data:indicators.macd.signal,borderColor:'#f59e0b',borderWidth:1.5,pointRadius:0,tension:0.3,spanGaps:true,order:1},
    ]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:300},scales:{x:{grid:{color:'#1e293b'},ticks:{color:'#64748b',font:{size:9},maxRotation:0},border:{color:'#334155'}},y:{position:'right',grid:{color:'#1e293b80'},ticks:{color:'#64748b',font:{size:10}},border:{color:'#334155'}}},plugins:{legend:{display:true,position:'top',align:'end',labels:{color:'#94a3b8',boxWidth:10,boxHeight:10,font:{size:10},usePointStyle:true,padding:12,filter:item=>item.datasetIndex>0}},tooltip:{backgroundColor:'#0f172a',borderColor:'#334155',borderWidth:1,bodyColor:'#94a3b8',padding:8}}},
  });
}

function renderKD(klines, indicators) {
  if (kdChart) kdChart.destroy();
  if (!indicators?.kd) return;
  const ctx = document.getElementById('kd-chart').getContext('2d');
  kdChart = new Chart(ctx, {
    type:'line', data:{ labels:thinLabels(klines), datasets:[
      {label:'K',data:indicators.kd.k,borderColor:'#3b82f6',borderWidth:1.5,pointRadius:0,tension:0.3,spanGaps:true},
      {label:'D',data:indicators.kd.d,borderColor:'#f59e0b',borderWidth:1.5,pointRadius:0,tension:0.3,spanGaps:true},
    ]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:300},scales:{x:{grid:{color:'#1e293b'},ticks:{color:'#64748b',font:{size:9},maxRotation:0},border:{color:'#334155'}},y:{position:'right',min:0,max:100,grid:{color:c=>[20,80].includes(c.tick.value)?'#475569':'#1e293b40'},ticks:{color:'#64748b',font:{size:10},stepSize:20},border:{color:'#334155'}}},plugins:{legend:{display:true,position:'top',align:'end',labels:{color:'#94a3b8',boxWidth:10,boxHeight:10,font:{size:10},usePointStyle:true,padding:12}},tooltip:{callbacks:{label:item=>`  ${item.dataset.label}: ${item.raw?.toFixed(1)??'–'}`},backgroundColor:'#0f172a',borderColor:'#334155',borderWidth:1,bodyColor:'#94a3b8',padding:8}}},
    plugins:[{id:'kd-zones',beforeDatasetsDraw(chart){const{ctx:c,chartArea:{left,right},scales:{y}}=chart;c.save();c.fillStyle='rgba(239,68,68,.05)';c.fillRect(left,y.getPixelForValue(100),right-left,y.getPixelForValue(80)-y.getPixelForValue(100));c.fillStyle='rgba(34,197,94,.05)';c.fillRect(left,y.getPixelForValue(20),right-left,y.getPixelForValue(0)-y.getPixelForValue(20));c.restore();}}],
  });
}

function renderOBV(klines, indicators) {
  if (obvChart) obvChart.destroy();
  if (!indicators?.obv) return;
  const ctx = document.getElementById('obv-chart').getContext('2d');
  obvChart = new Chart(ctx, {
    type:'line', data:{ labels:thinLabels(klines), datasets:[
      {data:indicators.obv,borderColor:'#a78bfa',borderWidth:1.5,pointRadius:0,tension:0.3,spanGaps:true,fill:{target:'origin',above:'rgba(167,139,250,.08)',below:'rgba(167,139,250,.03)'}},
    ]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:300},scales:{x:{display:false},y:{display:true,position:'right',ticks:{color:'#64748b',font:{size:9},callback:v=>fmtVol(v)},grid:{color:'#1e293b40'},border:{display:false}}},plugins:{legend:{display:false},tooltip:{callbacks:{label:item=>`  OBV: ${fmtVol(item.raw)}`},backgroundColor:'#0f172a',borderColor:'#334155',borderWidth:1,bodyColor:'#94a3b8',padding:8}}},
  });
}

function renderMAAlignment(indicators) {
  const el = document.getElementById('h-ma-align');
  if (!el) return;
  const a = indicators?.ma_alignment;
  if (!a || !a.label || a.label === '資料不足') {
    el.classList.add('hidden');
    return;
  }
  el.textContent = a.label;
  el.style.color = a.color;
  el.style.borderColor = a.color;
  el.style.backgroundColor = (a.color || '#94a3b8') + '15';
  el.classList.remove('hidden');
}

// ── B9: Annual revenue YoY chart ────────────────────────────────────────────
function renderAnnualGrowth(fund) {
  const card = document.getElementById('annual-growth-card');
  const annual = fund?.annual_revenue_growth || [];
  if (annualGrowthChart) annualGrowthChart.destroy();
  if (!annual.length) { card.classList.add('hidden'); return; }
  card.classList.remove('hidden');
  // chronological order
  const sorted = [...annual].sort((a, b) => a.year - b.year);
  const labels = sorted.map(r => String(r.year));
  const yoys = sorted.map(r => r.yoy_pct ?? null);
  const ctx = document.getElementById('annual-growth-chart').getContext('2d');
  annualGrowthChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{
      data: yoys, label: 'YoY %',
      backgroundColor: yoys.map(v => v == null ? '#475569' : v >= 0 ? 'rgba(34,197,94,.7)' : 'rgba(239,68,68,.7)'),
      borderWidth: 0,
    }]},
    options: { responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#64748b', font: { size: 10 } }, border: { color: '#334155' } },
        y: { position: 'right', grid: { color: '#1e293b80' }, ticks: { color: '#64748b', font: { size: 10 }, callback: v => v + '%' }, border: { color: '#334155' } },
      },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: i => `  YoY: ${i.raw != null ? i.raw.toFixed(2) + '%' : '–'}` }, backgroundColor: '#0f172a', borderColor: '#334155', borderWidth: 1, bodyColor: '#94a3b8', padding: 8 } }
    }
  });
}

// ── B9: Dividend history chart ──────────────────────────────────────────────
function renderDividendHistory(fund) {
  const card = document.getElementById('dividend-history-card');
  const badge = document.getElementById('dividend-consecutive-badge');
  const history = fund?.dividend_history || [];
  if (dividendHistoryChart) dividendHistoryChart.destroy();
  if (!history.length) { card.classList.add('hidden'); badge.classList.add('hidden'); return; }
  card.classList.remove('hidden');

  const years = fund.dividend_consecutive_years || 0;
  if (years > 0) {
    badge.textContent = `連續 ${years} 年配息`;
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }

  const labels = history.map(r => String(r.year));
  const amounts = history.map(r => r.amount);
  const ctx = document.getElementById('dividend-history-chart').getContext('2d');
  dividendHistoryChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data: amounts, backgroundColor: 'rgba(16,185,129,.7)', borderWidth: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#64748b', font: { size: 10 } }, border: { color: '#334155' } },
        y: { position: 'right', grid: { color: '#1e293b80' }, ticks: { color: '#64748b', font: { size: 10 }, callback: v => '$' + v }, border: { color: '#334155' } },
      },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: i => `  $${i.raw}` }, backgroundColor: '#0f172a', borderColor: '#334155', borderWidth: 1, bodyColor: '#94a3b8', padding: 8 } }
    }
  });
}

// ── B9: PE history (river) chart ────────────────────────────────────────────
function renderPeHistory(fund) {
  const card = document.getElementById('pe-history-card');
  const badge = document.getElementById('pe-percentile-badge');
  const peHist = fund?.pe_history || {};
  if (peHistoryChart) peHistoryChart.destroy();
  if (!peHist.labels || !peHist.series) { card.classList.add('hidden'); return; }
  card.classList.remove('hidden');

  // Percentile badge color
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

  const labels = peHist.labels;
  const series = peHist.series;
  const median = Array(labels.length).fill(peHist.median);
  const p25 = Array(labels.length).fill(peHist.p25);
  const p75 = Array(labels.length).fill(peHist.p75);
  const ctx = document.getElementById('pe-history-chart').getContext('2d');
  peHistoryChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [
      { label: 'P75', data: p75, borderColor: 'rgba(148,163,184,.25)', borderWidth: 1, pointRadius: 0, fill: false, borderDash: [3,3] },
      { label: 'P25', data: p25, borderColor: 'rgba(148,163,184,.25)', borderWidth: 1, pointRadius: 0, fill: '-1', backgroundColor: 'rgba(148,163,184,.06)', borderDash: [3,3] },
      { label: 'Median', data: median, borderColor: 'rgba(148,163,184,.5)', borderWidth: 1, pointRadius: 0, fill: false, borderDash: [5,3] },
      { label: 'PE', data: series, borderColor: '#a78bfa', borderWidth: 1.5, pointRadius: 0, tension: 0.3, spanGaps: true, fill: false },
    ]},
    options: { responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      scales: {
        x: { grid: { color: '#1e293b' }, ticks: { color: '#64748b', font: { size: 9 }, maxRotation: 0, callback: (v, i) => i % 12 === 0 ? labels[i] : '' }, border: { color: '#334155' } },
        y: { position: 'right', grid: { color: '#1e293b80' }, ticks: { color: '#64748b', font: { size: 10 } }, border: { color: '#334155' } },
      },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: i => `  ${i.dataset.label}: ${i.raw != null ? i.raw.toFixed(1) : '–'}` }, backgroundColor: '#0f172a', borderColor: '#334155', borderWidth: 1, bodyColor: '#94a3b8', padding: 8 } }
    }
  });
}

function renderPatterns(patterns) {
  const card = document.getElementById('patterns-card');
  const list = document.getElementById('patterns-list');
  if (!patterns || patterns.length === 0) {
    card.classList.add('hidden');
    list.innerHTML = '';
    return;
  }
  card.classList.remove('hidden');
  // Show newest first
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

// ── Render: fundamentals ─────────────────────────────────────────────────────
function renderValuation(fund) {
  if (!fund) return;
  const v = fund.valuation||{}, ps = fund.per_share||{};
  const items = [['P/E (TTM)',v.pe_ratio],['Forward P/E',v.forward_pe],['P/B',v.pb_ratio],['P/S',v.ps_ratio],['PEG',v.peg_ratio],['EPS (TTM)',ps.eps_ttm?`$${ps.eps_ttm}`:null],['EPS (Fwd)',ps.eps_forward?`$${ps.eps_forward}`:null],['Book Value',ps.book_value?`$${ps.book_value}`:null],['Rev/Share',ps.revenue_per_share?`$${ps.revenue_per_share}`:null]];
  document.getElementById('valuation-grid').innerHTML = items.map(([l,v])=>`<div><div class="fund-label">${l}</div><div class="fund-value">${v??'–'}</div></div>`).join('');
}
function renderProfitability(fund) {
  if (!fund) return;
  const p = fund.profitability||{};
  const items = [['ROE',p.roe,'%'],['ROA',p.roa,'%'],['Profit Margin',p.profit_margin,'%'],['Gross Margin',p.gross_margin,'%'],['Operating Margin',p.operating_margin,'%']];
  document.getElementById('profit-grid').innerHTML = items.map(([l,v,s])=>{const d=v!=null?`${v}${s}`:'–';const c=v!=null?(v>=20?'text-green-400':v>=10?'text-amber-400':'text-red-400'):'';return`<div><div class="fund-label">${l}</div><div class="fund-value ${c}">${d}</div></div>`}).join('');
}
function renderDividend(fund) {
  if (!fund) return;
  const d = fund.dividend||{};
  const items = [['Yield',d.dividend_yield!=null?`${d.dividend_yield}%`:null],['Annual Rate',d.dividend_rate!=null?`$${d.dividend_rate}`:null],['Payout Ratio',d.payout_ratio!=null?`${d.payout_ratio}%`:null],['Ex-Div Date',d.ex_dividend_date]];
  document.getElementById('dividend-grid').innerHTML = items.map(([l,v])=>`<div><div class="fund-label">${l}</div><div class="fund-value">${v??'–'}</div></div>`).join('');
}
function renderQuarterly(fund) {
  const el = document.getElementById('quarterly-bars');
  if (!fund?.quarterly_financials?.length) { el.innerHTML = '<div class="text-slate-500 text-sm text-center py-4">無季度數據</div>'; return; }
  const q = [...fund.quarterly_financials].reverse();
  const maxRev = Math.max(...q.map(x=>x.revenue||0));
  el.innerHTML = q.map(x=>{const r=x.revenue||0,ni=x.net_income||0,pct=maxRev>0?(r/maxRev*100):0,m=r>0?(ni/r*100).toFixed(1):'–';return`<div><div class="flex justify-between text-xs mb-1"><span class="text-slate-400">${x.period}</span><span class="text-slate-200 font-semibold tabular-nums">${fmtCap(r)} <span class="text-slate-500 font-normal">/ ${m}% margin</span></span></div><div class="h-2 rounded-full bg-slate-700 overflow-hidden"><div class="quarter-bar h-2 rounded-full bg-blue-500" style="width:${pct}%"></div></div></div>`}).join('');
}

// ── Render: peer comparison ───────────────────────────────────────────────────
let peerChart = null, wlPerfChart = null;
const PEER_COLORS = ['#3b82f6','#22c55e','#f59e0b','#a855f7','#ef4444','#06b6d4','#ec4899','#84cc16'];

function renderRelativeChart(canvasId, chartRef, perfData) {
  if (chartRef) chartRef.destroy();
  if (!perfData || !perfData.labels) return null;

  const ctx = document.getElementById(canvasId).getContext('2d');
  const syms = Object.keys(perfData.series);
  const datasets = syms.map((sym, i) => ({
    label: sym.replace(/\.(TW|SS|SZ)$/,''),
    data: perfData.series[sym],
    borderColor: PEER_COLORS[i % PEER_COLORS.length],
    borderWidth: sym.includes('SPY') || sym.includes('0050') ? 2 : 1.5,
    borderDash: sym.includes('SPY') || sym.includes('0050') ? [5,3] : [],
    pointRadius: 0, tension: 0.3, fill: false,
  }));

  const labels = perfData.labels.length > 60
    ? perfData.labels.map((l,i) => i % 10 === 0 ? l : '')
    : perfData.labels.length > 30
      ? perfData.labels.map((l,i) => i % 5 === 0 ? l : '')
      : perfData.labels;

  return new Chart(ctx, {
    type: 'line', data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      scales: {
        x: { grid:{color:'#1e293b'}, ticks:{color:'#64748b',font:{size:9},maxRotation:0}, border:{color:'#334155'} },
        y: { position:'right', grid:{color:'#1e293b80'}, ticks:{color:'#64748b',font:{size:10},callback:v=>v.toFixed(0)+'%'}, border:{color:'#334155'} },
      },
      plugins: {
        legend: { display:true, position:'top', labels:{color:'#94a3b8',boxWidth:10,boxHeight:3,font:{size:10},usePointStyle:false,padding:8} },
        tooltip: { backgroundColor:'#0f172a',borderColor:'#334155',borderWidth:1,bodyColor:'#94a3b8',padding:8,
          callbacks:{ label: item => `  ${item.dataset.label}: ${item.raw?.toFixed(1)}%` } },
      },
    },
  });
}

function renderComparisonTable(containerId, rows) {
  if (!rows || !rows.length) return;
  const el = document.getElementById(containerId);
  const headers = ['代號','評分','P/E','ROE','Margin','市值','報酬率','殖利率','Beta'];
  el.innerHTML = `
    <table class="w-full text-xs">
      <thead><tr class="text-slate-500 border-b border-slate-700">
        ${headers.map(h => `<th class="py-1.5 px-2 text-left font-medium">${h}</th>`).join('')}
      </tr></thead>
      <tbody>${rows.map(r => {
        if (r.error) return '';
        const highlight = r.is_target ? 'bg-blue-500/10 font-bold' : r.is_index ? 'text-slate-500 italic' : '';
        const retColor = (r.return_period||0) >= 0 ? 'text-green-400' : 'text-red-400';
        const sym = r.symbol.replace(/\.(TW|SS|SZ)$/,'');
        const sc = r.score;
        const scoreColor = sc!=null ? (sc>=61?'#22c55e':sc>=41?'#f59e0b':'#ef4444') : '';
        return `<tr class="${highlight} border-b border-slate-700/50 hover:bg-slate-700/30">
          <td class="py-1.5 px-2 font-mono">${sym}${r.is_index?' 📊':''}</td>
          <td class="py-1.5 px-2 tabular-nums font-bold" style="color:${scoreColor}">${sc??'–'}</td>
          <td class="py-1.5 px-2 tabular-nums">${r.pe??'–'}</td>
          <td class="py-1.5 px-2 tabular-nums">${r.roe!=null?r.roe+'%':'–'}</td>
          <td class="py-1.5 px-2 tabular-nums">${r.margin!=null?r.margin+'%':'–'}</td>
          <td class="py-1.5 px-2 tabular-nums">${fmtCap(r.mcap)}</td>
          <td class="py-1.5 px-2 tabular-nums ${retColor}">${r.return_period!=null?(r.return_period>=0?'+':'')+r.return_period+'%':'–'}</td>
          <td class="py-1.5 px-2 tabular-nums">${r.yield!=null?r.yield+'%':'–'}</td>
          <td class="py-1.5 px-2 tabular-nums">${r.beta??'–'}</td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
}

async function loadPeerComparison() {
  const ticker = document.getElementById('ticker-input').value.trim().toUpperCase();
  if (!ticker) return;
  try {
    const res = await fetch(`/api/peer-comparison?ticker=${ticker}&period=${currentPeriod}&mock=${isMock}`);
    if (!res.ok) return;
    const data = await res.json();
    peerChart = renderRelativeChart('peer-chart', peerChart, data.relative_performance);
    renderComparisonTable('peer-table', data.comparison_table);
  } catch (e) { console.warn('Peer comparison failed:', e); }
}

async function loadWatchlistComparison() {
  if (!watchlist.length) return;
  try {
    const res = await fetch(`/api/watchlist-comparison?tickers=${watchlist.join(',')}&period=${currentPeriod}&mock=${isMock}`);
    if (!res.ok) return;
    const data = await res.json();
    wlPerfChart = renderRelativeChart('watchlist-perf-chart', wlPerfChart, data.relative_performance);
    renderComparisonTable('watchlist-table', data.comparison_table);
  } catch (e) { console.warn('Watchlist comparison failed:', e); }
}

// ── Render: stock screener ───────────────────────────────────────────────────
// LIVE 模式：先觸發後端增量抓取，再 reload screener
// MOCK 模式：直接 reload（mock 資料用不到 SQLite）
async function refreshScreener() {
  const btn = document.getElementById('screener-refresh-btn');
  const updated = document.getElementById('screener-updated');
  const originalLabel = btn.textContent;

  btn.disabled = true;

  try {
    if (!isMock) {
      btn.textContent = '抓取中…';
      updated.textContent = '正在從 TWSE/TPEX 增量更新…';
      try {
        const r = await fetch('/api/refresh-tw-data', { method: 'POST' });
        if (r.ok) {
          const d = await r.json();
          if (d.bootstrap_required) {
            updated.textContent = '⚠️ DB 為空，請先跑 python scripts/update_tw_history.py --backfill 60';
          } else if (d.success > 0) {
            updated.textContent = `✅ 新增 ${d.success} 個交易日（最新：${d.latest_date}）`;
          } else if (d.dates_attempted === 0) {
            updated.textContent = `已是最新（${d.latest_date}）`;
          } else if (d.failed && d.failed.length) {
            updated.textContent = `⚠️ ${d.failed.length} 個日期抓取失敗`;
          }
        } else {
          updated.textContent = '⚠️ 增量更新失敗';
        }
      } catch (err) {
        console.error('Refresh TW data failed:', err);
        updated.textContent = '⚠️ 增量更新失敗';
      }
    }
    btn.textContent = '重新計算中…';
    await loadScreener();
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
}

async function loadScreener() {
  try {
    const res = await fetch(`/api/stock-screener?mock=${isMock}`);
    if (!res.ok) return;
    const data = await res.json();
    renderScreenerTable(data);
  } catch (e) { console.warn('Screener failed:', e); }
}

function renderScreenerTable(data) {
  document.getElementById('screener-updated').textContent = data.last_updated
    ? `最後更新：${data.last_updated.slice(0,10)}　共 ${data.total_stocks} 支`
    : '';

  const picks = data.top_picks || [];
  if (!picks.length) {
    document.getElementById('screener-table').innerHTML = '<div class="text-slate-500 text-sm text-center py-6">無篩選結果</div>';
    return;
  }

  document.getElementById('screener-table').innerHTML = `
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
        const sym = p.symbol.replace('.TW','');
        return `<tr class="border-b border-slate-700/50 hover:bg-slate-700/30 cursor-pointer" onclick="switchToStock('${p.symbol}')">
          <td class="py-2 px-2 text-slate-500">${p.rank}</td>
          <td class="py-2 px-2 font-mono font-bold text-slate-200">${sym}</td>
          <td class="py-2 px-2 text-slate-300">${p.name}</td>
          <td class="py-2 px-2 text-right font-bold tabular-nums" style="color:${scoreColor}">${p.score}</td>
          <td class="py-2 px-2 text-right tabular-nums text-slate-200">$${p.close}</td>
          <td class="py-2 px-2 text-right tabular-nums ${chgColor}">${p.change_pct>=0?'+':''}${p.change_pct}%</td>
          <td class="py-2 px-2 text-right tabular-nums">${p.pe??'–'}</td>
          <td class="py-2 px-2 text-right tabular-nums">${p.yield_pct!=null?p.yield_pct+'%':'–'}</td>
          <td class="py-2 px-2 text-right tabular-nums text-slate-400">${fmtVol(p.volume)}</td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
}

// ── Screener tab switching ───────────────────────────────────────────────────
let backtestLoaded = false;
let backtestRankChart = null;

function switchScreenerTab(tab) {
  document.querySelectorAll('.screener-tab').forEach(btn => {
    btn.classList.remove('bg-slate-700', 'text-slate-200');
    btn.classList.add('text-slate-500');
  });
  const activeBtn = document.getElementById(`tab-${tab}`);
  activeBtn.classList.add('bg-slate-700', 'text-slate-200');
  activeBtn.classList.remove('text-slate-500');

  document.getElementById('panel-screener').classList.toggle('hidden', tab !== 'screener');
  document.getElementById('panel-backtest').classList.toggle('hidden', tab !== 'backtest');

  if (tab === 'backtest' && !backtestLoaded) {
    loadBacktest();
  }
}

async function loadBacktest() {
  document.getElementById('backtest-summary').innerHTML =
    '<div class="text-center text-slate-500 text-sm py-8">載入回測資料中…</div>';
  try {
    const res = await fetch(`/api/stock-screener/backtest?mock=${isMock}`);
    if (!res.ok) throw new Error('API error');
    const data = await res.json();
    backtestLoaded = true;
    renderBacktest(data);
  } catch (e) {
    console.error('Backtest load failed:', e);
    document.getElementById('backtest-summary').innerHTML =
      '<div class="text-center text-red-400 text-sm py-8">回測資料載入失敗</div>';
  }
}

function renderBacktest(data) {
  renderBacktestSummary(data.summary, data.period, data.config);
  renderBacktestHorizon(data.summary.by_horizon, data.config.forward_days);
  renderBacktestRankChart(data.summary.by_rank_group, data.config.forward_days);
  renderBacktestSignals(data.signals);
}

// ── Backtest: summary cards ─────────────────────────────────────────────────
function renderBacktestSummary(summary, period, config) {
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

  document.getElementById('backtest-summary').innerHTML = `
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      ${cards.map(c => `
        <div class="bg-slate-900/60 rounded-xl p-3 text-center border border-slate-700/50">
          <div class="text-xs text-slate-500 mb-1">${c.label}</div>
          <div class="text-lg font-bold tabular-nums ${c.color}">${c.value}</div>
        </div>
      `).join('')}
    </div>
    <div class="flex flex-wrap gap-2 mt-2">
      <span class="text-xs text-slate-500 bg-slate-900/40 px-2 py-0.5 rounded">${period.start} ~ ${period.end}</span>
      <span class="text-xs text-slate-500 bg-slate-900/40 px-2 py-0.5 rounded">隔日開盤買入</span>
      <span class="text-xs text-slate-500 bg-slate-900/40 px-2 py-0.5 rounded">前瞻天數: ${config.forward_days.join(', ')} 天</span>
    </div>
  `;
}

// ── Backtest: horizon stats table ───────────────────────────────────────────
function renderBacktestHorizon(byHorizon, forwardDays) {
  if (!byHorizon || !forwardDays) return;
  const days = forwardDays.map(String);

  const rows = days.map(d => {
    const h = byHorizon[d];
    if (!h || !h.count) return '';
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

  document.getElementById('backtest-horizon').innerHTML = `
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
    </div>
  `;
}

// ── Backtest: rank group chart ──────────────────────────────────────────────
function renderBacktestRankChart(byRankGroup, forwardDays) {
  if (backtestRankChart) { backtestRankChart.destroy(); backtestRankChart = null; }
  if (!byRankGroup || !forwardDays) return;

  const groups = ['1-5', '6-10', '11-15', '16-20'];
  const colors = ['#3b82f6', '#06b6d4', '#f59e0b', '#64748b'];
  const labels = forwardDays.map(d => `${d}天`);

  const datasets = groups.map((g, gi) => ({
    label: `排名 ${g}`,
    data: forwardDays.map(d => {
      const stats = byRankGroup[g]?.[String(d)];
      return stats ? stats.avg_excess : 0;
    }),
    backgroundColor: colors[gi] + '99',
    borderColor: colors[gi],
    borderWidth: 1,
  }));

  const ctx = document.getElementById('backtest-rank-chart').getContext('2d');
  backtestRankChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#94a3b8', boxWidth: 14, font: { size: 11 } } },
        tooltip: {
          backgroundColor: '#1e293b',
          titleColor: '#e2e8f0',
          bodyColor: '#cbd5e1',
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y>=0?'+':''}${ctx.parsed.y.toFixed(2)}%`,
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#94a3b8', font: { size: 11 } },
          grid: { color: '#1e293b' },
        },
        y: {
          ticks: {
            color: '#64748b', font: { size: 10 },
            callback: v => `${v>=0?'+':''}${parseFloat(v.toFixed(2))}%`,
          },
          grid: { color: '#1e293b' },
        },
      },
    },
  });
}

// ── Backtest: signal details ────────────────────────────────────────────────
function renderBacktestSignals(signals) {
  if (!signals || !signals.length) {
    document.getElementById('backtest-signals').innerHTML =
      '<div class="text-slate-500 text-sm text-center py-4">無信號資料</div>';
    return;
  }

  const recent = signals.slice(-100).reverse();
  const fwdKeys = Object.keys(signals[0].returns).sort((a,b) => a - b);

  document.getElementById('backtest-signals').innerHTML = `
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
        const sym = s.symbol.replace('.TW','');
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
    </table>
  `;
}

function toggleBacktestSignals() {
  document.getElementById('backtest-signals').classList.toggle('hidden');
}

// ── Utilities ────────────────────────────────────────────────────────────────
function fmtCap(n){if(!n)return'–';if(n>=1e12)return`$${(n/1e12).toFixed(2)}T`;if(n>=1e9)return`$${(n/1e9).toFixed(2)}B`;if(n>=1e6)return`$${(n/1e6).toFixed(0)}M`;return`$${n.toLocaleString()}`}
function fmtVol(v){if(v>=1e6)return(v/1e6).toFixed(1)+'M';if(v>=1e3)return(v/1e3).toFixed(0)+'K';return String(v)}
function escHtml(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  syncMockUI();  // restore LIVE/MOCK toggle from LocalStorage
  showState('dashboard');
  analyze();
  refreshWatchlist();
  loadScreener();
});
