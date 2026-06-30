// 統一 API 客戶端。
//
// 集中所有 backend endpoint 呼叫，view 不直接 fetch。好處：
//   - mock 開關集中管理（每次呼叫自動帶 mock 參數）
//   - 錯誤處理統一（HTTP 非 2xx 時丟 Error）
//   - 短請求支援 AbortSignal（view 切換可中斷）
//   - 長任務一律走 jobs endpoint（submit/poll/cancel）
//
// 透過依賴注入取得 mock 狀態，避免直接耦合 global state（state-store）：
//   const api = new ApiClient(() => stateStore.isMock);

export class ApiClient {
  constructor(getMockFlag) {
    this._getMock = typeof getMockFlag === 'function' ? getMockFlag : () => false;
  }

  async _get(path, params = {}, { signal } = {}) {
    const qs = this._buildQuery({ ...params, mock: this._getMock() });
    const res = await fetch(`${path}${qs ? '?' + qs : ''}`, { signal });
    return this._handle(res);
  }

  async _postJson(path, body) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return this._handle(res);
  }

  async _delete(path) {
    const res = await fetch(path, { method: 'DELETE' });
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

  // ── 短請求（可被 AbortSignal 中斷） ────────────────────────────────
  getStockInsights(ticker, period, opts)    { return this._get('/api/stock-insights', { ticker, period }, opts); }
  getStockChart(ticker, period, opts)       { return this._get('/api/stock-chart', { ticker, period }, opts); }
  getBatchQuotes(tickers, opts)             { return this._get('/api/batch-quotes', { tickers: tickers.join(',') }, opts); }
  getPeerComparison(ticker, period, opts)   { return this._get('/api/peer-comparison', { ticker, period }, opts); }
  getWatchlistComparison(tickers, period, opts) {
    return this._get('/api/watchlist-comparison', { tickers: tickers.join(','), period }, opts);
  }
  getScreener(opts)                         { return this._get('/api/stock-screener', {}, opts); }
  getMLStatus(model, opts)                  { return this._get('/api/ml/status', { model }, opts); }

  // ── ETF（高股息定期定額 dividend-dca view） ──────────────────────────
  // 注意：ETF endpoint 後端目前未實作 mock 模式，永遠直接打 yfinance + etf.db。
  // 仍透過 _get 以保持風格一致與 abort 能力。
  getEtfList(opts)                          { return this._get('/api/etf/list', {}, opts); }
  getEtfDetail(symbol, opts)                { return this._get(`/api/etf/${encodeURIComponent(symbol)}/detail`, {}, opts); }
  simulateEtfDca(body)                      { return this._postJson('/api/etf/dca-simulate', body); }

  // ── Job 系統（長任務統一入口） ─────────────────────────────────────
  // type ∈ "backtest" | "refresh_tw" | "ml_train" | "ml_predict"
  // 回傳 { job_id, key, status, progress, message, ... }
  submitJob(type, params = {}) {
    return this._postJson('/api/jobs', { type, mock: this._getMock(), params });
  }

  // 回傳 job snapshot（done 時含 result）
  getJob(jobId) {
    return this._get(`/api/jobs/${encodeURIComponent(jobId)}`);
  }

  cancelJob(jobId) {
    return this._delete(`/api/jobs/${encodeURIComponent(jobId)}`);
  }
}
