// 潛力選股 view 模板。
// 三個內層子 view 共用同一個 header（標題 + tab 按鈕 + 重新整理按鈕 + 更新時間）。

export const SCREENER_VIEW_TEMPLATE = `
<div class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in">
  <div class="flex items-center justify-between mb-4 flex-wrap gap-3">
    <div class="flex items-center gap-4 flex-wrap">
      <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest">🏆 潛力股篩選</h2>
      <div data-bind="sub-tabs" class="flex gap-1 bg-slate-900 rounded-lg p-0.5">
        <button data-tab="results"  class="screener-tab text-xs px-3 py-1 rounded-md transition font-medium bg-slate-700 text-slate-200">篩選結果</button>
        <button data-tab="backtest" class="screener-tab text-xs px-3 py-1 rounded-md transition font-medium text-slate-500 hover:text-slate-300">回測分析</button>
        <button data-tab="ml"       class="screener-tab text-xs px-3 py-1 rounded-md transition font-medium text-slate-500 hover:text-slate-300">ML 選股</button>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <span data-bind="updated" class="text-xs text-slate-600"></span>
      <button data-bind="refresh-btn" class="text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed px-3 py-1 rounded-lg text-slate-300 transition">重新整理</button>
    </div>
  </div>

  <div data-bind="sub-container"></div>

  <p class="text-xs text-slate-600 mt-3">以上僅為量化篩選結果，不構成投資建議，投資決策請自行評估風險。</p>
</div>
`;
