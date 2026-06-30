// 高股息定期定額 view 模板。
// 三個內層 sub-view 共用同一個 header（標題 + sub-tab + 描述）。

export const DIVIDEND_DCA_VIEW_TEMPLATE = `
<div class="bg-slate-800 rounded-2xl p-5 border border-slate-700 fade-in">
  <div class="flex items-center justify-between mb-4 flex-wrap gap-3">
    <div class="flex items-center gap-4 flex-wrap">
      <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest">💰 高股息定期定額</h2>
      <div data-bind="sub-tabs" class="flex gap-1 bg-slate-900 rounded-lg p-0.5">
        <button data-tab="list"      class="dca-tab text-xs px-3 py-1 rounded-md transition font-medium bg-slate-700 text-slate-200">ETF 列表</button>
        <button data-tab="detail"    class="dca-tab text-xs px-3 py-1 rounded-md transition font-medium text-slate-500 hover:text-slate-300">ETF 詳情</button>
        <button data-tab="simulator" class="dca-tab text-xs px-3 py-1 rounded-md transition font-medium text-slate-500 hover:text-slate-300">DCA 模擬</button>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <span data-bind="status" class="text-xs text-slate-600"></span>
    </div>
  </div>

  <div data-bind="sub-container"></div>

  <p class="text-xs text-slate-600 mt-3">以上僅為量化分析參考，不構成投資建議。歷史績效不代表未來，投資決策請自行評估風險。</p>
</div>
`;
