// 個股分析 view 的 HTML 模板。
// 抽離成獨立檔，讓 stock-view.js 專注於行為邏輯。

export const STOCK_VIEW_TEMPLATE = `
<div data-section="loading" class="hidden flex-col items-center justify-center h-72 gap-4">
  <div class="spin w-10 h-10 rounded-full border-4 border-blue-500 border-t-transparent"></div>
  <p class="text-slate-400 text-sm">Fetching market data…</p>
</div>

<div data-section="error" class="hidden bg-red-950/40 border border-red-500/30 rounded-2xl p-8 text-center mt-10">
  <p class="text-4xl mb-3">⚠️</p>
  <p data-bind="error-msg" class="text-red-400 font-medium"></p>
</div>

<div data-section="dashboard" class="space-y-5">

  <div data-bind="score-card" class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in">
    <div class="flex flex-col lg:flex-row gap-6">
      <div class="flex flex-col items-center justify-center shrink-0" style="width:140px">
        <div style="position:relative; width:120px; height:120px">
          <canvas data-bind="score-donut"></canvas>
          <div class="absolute inset-0 flex flex-col items-center justify-center">
            <span data-bind="score-number" class="text-3xl font-extrabold tabular-nums">–</span>
            <span data-bind="score-label" class="text-xs font-semibold text-slate-400">–</span>
          </div>
        </div>
      </div>
      <div class="flex-1 min-w-0">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">綜合投資評分</h2>
        <div data-bind="sub-scores" class="space-y-2.5 mb-4"></div>
        <div data-bind="commentary-box" class="bg-slate-900/50 rounded-xl p-3 border border-slate-700">
          <p data-bind="commentary-text" class="text-sm text-slate-300 leading-relaxed">–</p>
        </div>
        <p class="text-xs text-slate-600 mt-2">以上僅為分析參考，不構成投資建議，投資決策請自行評估風險。</p>
      </div>
    </div>
  </div>

  <div class="grid grid-cols-5 gap-5">
    <div class="col-span-5 lg:col-span-3 bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in">
      <div class="flex items-start justify-between gap-4">
        <div>
          <div class="flex items-center gap-2 mb-1">
            <span data-bind="h-symbol" class="text-2xl font-extrabold tracking-tight">–</span>
            <span data-bind="h-currency" class="text-xs bg-slate-700 text-slate-400 px-2 py-0.5 rounded-md font-mono">USD</span>
            <span data-bind="h-sector" class="text-xs bg-slate-700 text-slate-400 px-2 py-0.5 rounded-md"></span>
            <span data-bind="h-mock-tag" class="text-xs bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded-md hidden">MOCK</span>
          </div>
          <div class="flex flex-wrap items-baseline gap-3">
            <span data-bind="h-price" class="text-4xl font-extrabold tabular-nums">–</span>
            <span data-bind="h-change" class="text-lg font-semibold text-slate-500">–</span>
          </div>
          <div class="flex gap-4 mt-2 text-xs text-slate-500 items-center flex-wrap">
            <span>52W High: <strong data-bind="h-52h" class="text-slate-300">–</strong></span>
            <span>52W Low: <strong data-bind="h-52l" class="text-slate-300">–</strong></span>
            <span>Beta: <strong data-bind="h-beta" class="text-slate-300">–</strong></span>
            <span data-bind="h-ma-align" class="text-xs font-semibold px-2 py-0.5 rounded-md border border-slate-600 hidden">–</span>
          </div>
        </div>
        <div class="text-right shrink-0">
          <div class="text-xs text-slate-500 mb-0.5">Market Cap</div>
          <div data-bind="h-mcap" class="text-sm font-bold text-slate-200">–</div>
          <div class="text-xs text-slate-500 mt-2">Prev. Close</div>
          <div data-bind="h-prev" class="text-sm font-medium text-slate-300">–</div>
        </div>
      </div>
    </div>
    <div class="col-span-5 lg:col-span-2 bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in">
      <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">估值指標</h2>
      <div class="grid grid-cols-3 gap-x-4 gap-y-3" data-bind="valuation-grid"></div>
    </div>
  </div>

  <div class="grid grid-cols-5 gap-5">
    <div class="col-span-5 lg:col-span-3 flex flex-col gap-5">
      <div class="bg-slate-800 rounded-2xl p-4 border border-slate-700 fade-in">
        <div class="flex flex-wrap items-center gap-3">
          <span class="text-xs text-slate-500 font-semibold uppercase mr-1">Period</span>
          <div data-bind="period-btns" class="flex gap-1.5">
            <button class="period-btn text-xs px-3 py-1 rounded-lg bg-slate-700 text-slate-300 hover:bg-slate-600" data-p="1M">1M</button>
            <button class="period-btn text-xs px-3 py-1 rounded-lg bg-slate-700 text-slate-300 hover:bg-slate-600 active" data-p="3M">3M</button>
            <button class="period-btn text-xs px-3 py-1 rounded-lg bg-slate-700 text-slate-300 hover:bg-slate-600" data-p="6M">6M</button>
            <button class="period-btn text-xs px-3 py-1 rounded-lg bg-slate-700 text-slate-300 hover:bg-slate-600" data-p="1Y">1Y</button>
            <button class="period-btn text-xs px-3 py-1 rounded-lg bg-slate-700 text-slate-300 hover:bg-slate-600" data-p="YTD">YTD</button>
          </div>
          <div class="w-px h-5 bg-slate-600 mx-1"></div>
          <span class="text-xs text-slate-500 font-semibold uppercase mr-1">Overlay</span>
          <div data-bind="overlay-chips" class="flex flex-wrap gap-1.5">
            <span class="indicator-chip text-xs px-2.5 py-1 rounded-full border border-slate-600 text-slate-400 active" data-key="ma5">MA5</span>
            <span class="indicator-chip text-xs px-2.5 py-1 rounded-full border border-slate-600 text-slate-400 active" data-key="ma10">MA10</span>
            <span class="indicator-chip text-xs px-2.5 py-1 rounded-full border border-slate-600 text-slate-400 active" data-key="ma20">MA20</span>
            <span class="indicator-chip text-xs px-2.5 py-1 rounded-full border border-slate-600 text-slate-400" data-key="ma60">MA60</span>
            <span class="indicator-chip text-xs px-2.5 py-1 rounded-full border border-slate-600 text-slate-400" data-key="bb">BB</span>
            <span class="indicator-chip text-xs px-2.5 py-1 rounded-full border border-slate-600 text-slate-400 active" data-key="patterns">型態</span>
          </div>
        </div>
      </div>

      <div class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in relative" data-bind="chart-wrapper">
        <div data-bind="chart-loading" class="chart-loading hidden">
          <div class="spin w-6 h-6 rounded-full border-2 border-blue-500 border-t-transparent"></div>
        </div>
        <div style="position:relative; height:280px"><canvas data-bind="price-chart"></canvas></div>
        <div style="position:relative; height:48px; margin-top:6px"><canvas data-bind="volume-chart"></canvas></div>
      </div>

      <div class="bg-slate-800 rounded-2xl p-4 border border-slate-700 fade-in">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">RSI (14)</h2>
        <div style="position:relative; height:120px"><canvas data-bind="rsi-chart"></canvas></div>
      </div>
      <div class="bg-slate-800 rounded-2xl p-4 border border-slate-700 fade-in">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">MACD (12, 26, 9)</h2>
        <div style="position:relative; height:140px"><canvas data-bind="macd-chart"></canvas></div>
      </div>
      <div class="bg-slate-800 rounded-2xl p-4 border border-slate-700 fade-in">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">KD (9, 3, 3)</h2>
        <div style="position:relative; height:120px"><canvas data-bind="kd-chart"></canvas></div>
      </div>
      <div class="bg-slate-800 rounded-2xl p-4 border border-slate-700 fade-in">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">OBV (能量潮)</h2>
        <div style="position:relative; height:90px"><canvas data-bind="obv-chart"></canvas></div>
      </div>
    </div>

    <div class="col-span-5 lg:col-span-2 flex flex-col gap-5">
      <div class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">獲利能力</h2>
        <div data-bind="profit-grid" class="grid grid-cols-2 gap-x-4 gap-y-3"></div>
      </div>
      <div class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">股利資訊</h2>
        <div data-bind="dividend-grid" class="grid grid-cols-2 gap-x-4 gap-y-3"></div>
      </div>
      <div class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">季度營收趨勢</h2>
        <div data-bind="quarterly-bars" class="space-y-2.5"></div>
      </div>
      <div data-bind="patterns-card" class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in hidden">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">近期 K 線型態</h2>
        <div data-bind="patterns-list" class="space-y-2"></div>
      </div>
      <div data-bind="annual-growth-card" class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in hidden">
        <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">年度營收成長 (YoY)</h2>
        <div style="position:relative; height:140px"><canvas data-bind="annual-growth-chart"></canvas></div>
      </div>
      <div data-bind="dividend-history-card" class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in hidden">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest">股利配發歷史</h2>
          <span data-bind="dividend-consecutive-badge" class="text-xs font-semibold px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hidden">–</span>
        </div>
        <div style="position:relative; height:130px"><canvas data-bind="dividend-history-chart"></canvas></div>
      </div>
      <div data-bind="pe-history-card" class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in hidden">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest">PE 歷史河流圖</h2>
          <span data-bind="pe-percentile-badge" class="text-xs font-semibold px-2 py-0.5 rounded-md border">–</span>
        </div>
        <div style="position:relative; height:140px"><canvas data-bind="pe-history-chart"></canvas></div>
        <p class="text-[10px] text-slate-600 mt-2">5 年歷史月線 / 以最新 EPS 為錨點推估歷史值，僅供相對估值參考</p>
      </div>
    </div>
  </div>

  <div class="grid grid-cols-2 gap-5">
    <div class="col-span-2 lg:col-span-1 bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in">
      <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">同業比較</h2>
      <div style="position:relative; height:220px"><canvas data-bind="peer-chart"></canvas></div>
      <div data-bind="peer-table" class="mt-3 overflow-x-auto"></div>
    </div>
    <div class="col-span-2 lg:col-span-1 bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in">
      <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">自選股比較</h2>
      <div style="position:relative; height:220px"><canvas data-bind="watchlist-perf-chart"></canvas></div>
      <div data-bind="watchlist-table" class="mt-3 overflow-x-auto"></div>
    </div>
  </div>

</div>
`;
