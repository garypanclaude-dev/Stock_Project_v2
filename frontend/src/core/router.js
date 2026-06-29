// Hash router：URL ↔ 當前 view 同步。
//
// 為何用 hash 而非 history API：
//   - 此專案前端由 FastAPI 的 StaticFiles serve，沒有後端 fallback 路由，
//     用 history API 重新整理就會 404。Hash 對伺服器透明，最省事。
//   - 之後若要升級成 SPA 路由，只要換掉本檔，TabController 與 view 不必動。
//
// URL 格式：
//   #stock                          → 個股 view，預設 ticker
//   #stock?ticker=2330.TW           → 個股 view，指定 ticker
//   #screener                       → 潛力選股 view
//
// 對外 API：
//   router.bind(tabController)      把 router 接到 TabController
//   router.navigate(id, params)     由程式碼觸發切換（會更新 URL）
//   router.start()                  初始化：讀取目前 URL 並切到對應 view

export class Router {
  constructor({ defaultView = 'stock' } = {}) {
    this._tabController = null;
    this._default = defaultView;
    this._navigating = false;       // 防止 hashchange ↔ navigate 互相觸發無限迴圈
  }

  bind(tabController) {
    this._tabController = tabController;
  }

  start() {
    window.addEventListener('hashchange', () => this._handleHashChange());
    this._handleHashChange();
  }

  async navigate(id, params = {}) {
    if (!this._tabController) throw new Error('Router: not bound to TabController');
    const hash = this._buildHash(id, params);
    if (window.location.hash !== hash) {
      this._navigating = true;
      window.location.hash = hash;
      this._navigating = false;
    }
    await this._tabController.switchTo(id, params);
  }

  _handleHashChange() {
    if (this._navigating) return;
    const { id, params } = this._parseHash();
    const targetId = this._tabController?.has(id) ? id : this._default;
    this._tabController?.switchTo(targetId, params);
  }

  _parseHash() {
    const raw = window.location.hash.replace(/^#/, '');
    if (!raw) return { id: this._default, params: {} };
    const [id, query = ''] = raw.split('?');
    const params = {};
    for (const pair of query.split('&').filter(Boolean)) {
      const [k, v = ''] = pair.split('=');
      params[decodeURIComponent(k)] = decodeURIComponent(v);
    }
    return { id, params };
  }

  _buildHash(id, params) {
    const qs = Object.entries(params)
      .filter(([, v]) => v != null && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&');
    return qs ? `#${id}?${qs}` : `#${id}`;
  }
}
