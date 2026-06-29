// 統一 API 客戶端。
//
// 集中所有 backend endpoint 呼叫，view 不直接 fetch。好處：
//   - mock 開關集中管理（每次呼叫自動帶 mock 參數）
//   - 錯誤處理統一（HTTP 非 2xx 時丟 Error）
//   - 將來要加 retry / cache / abort 都改一個地方
//
// 透過依賴注入取得 mock 狀態，避免直接耦合 global state（state-store）：
//   const api = new ApiClient(() => stateStore.isMock);

export class ApiClient {
  constructor(getMockFlag) {
    this._getMock = typeof getMockFlag === 'function' ? getMockFlag : () => false;
  }

  async _get(path, params = {}) {
    const qs = this._buildQuery({ ...params, mock: this._getMock() });
    const res = await fetch(`${path}${qs ? '?' + qs : ''}`);
    return this._handle(res);
  }

  async _post(path, params = {}) {
    const qs = this._buildQuery(params);
    const res = await fetch(`${path}${qs ? '?' + qs : ''}`, { method: 'POST' });
    return this._handle(res);
  }

  async _handle(res) {
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  }

  _buildQuery(params) {
    return Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&');
  }

  // ── 個股 view ──────────────────────────────────────────────────
  getStockInsights(ticker, period)    { return this._get('/api/stock-insights', { ticker, period }); }
  getStockChart(ticker, period)       { return this._get('/api/stock-chart', { ticker, period }); }
  getBatchQuotes(tickers)             { return this._get('/api/batch-quotes', { tickers: tickers.join(',') }); }
  getPeerComparison(ticker, period)   { return this._get('/api/peer-comparison', { ticker, period }); }
  getWatchlistComparison(tickers, period) {
    return this._get('/api/watchlist-comparison', { tickers: tickers.join(','), period });
  }

  // ── 潛力選股 view ───────────────────────────────────────────────
  getScreener()                       { return this._get('/api/stock-screener'); }
  refreshTwData()                     { return this._post('/api/refresh-tw-data'); }
  getBacktest()                       { return this._get('/api/stock-screener/backtest'); }
  getMLStatus(model)                  { return this._get('/api/ml/status', { model }); }
  getMLPredict(model)                 { return this._get('/api/ml/predict', { model }); }
  trainML(model)                      { return this._post('/api/ml/train', { model }); }
}
