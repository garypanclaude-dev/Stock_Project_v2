// View 抽象基底類別。
//
// 所有頂層 view（個股分析、潛力選股、策略回測…）與內層子 view 都應繼承本類別，
// 由 TabController / Router 統一驅動生命週期，避免每個 view 自己土法煉鋼控制顯示/隱藏、
// 重複初始化、或忘記釋放 Chart instance 造成記憶體洩漏。
//
// 生命週期（呼叫順序）：
//   1. constructor(deps)        ← 依賴注入（services、event bus 等），不碰 DOM
//   2. mount(container)         ← 第一次進入時：建立 DOM、Chart instance、訂閱事件
//   3. activate(params)         ← 每次切回來時：刷新資料；mount 之後一定會接 activate
//   4. deactivate()             ← 切走時：暫停輪詢、隱藏容器；DOM 保留以便快速回返
//   5. unmount()                ← 真正銷毀：destroy charts、unsubscribe、清空 DOM
//
// 子類別只需 override 用得到的階段；用不到的階段保留 no-op 預設即可。

export class View {
  constructor() {
    this.container = null;
    this.mounted = false;
    this.active = false;
    this._abortCtl = null;
    this._namedCtls = new Map();   // name → AbortController（同名再呼叫會 abort 前一個）
  }

  mount(container) {
    this.container = container;
    this.mounted = true;
  }

  activate(_params = {}) {
    this.active = true;
    if (this.container) this.container.classList.remove('hidden');
    // 每次 activate 開新的 AbortController，舊請求若還在飛會被切走
    this._abortCtl = new AbortController();
  }

  deactivate() {
    this.active = false;
    if (this.container) this.container.classList.add('hidden');
    // 切走時 abort 所有掛在此 view 上的短請求（長任務走 JobStore 不受影響）
    this._abortCtl?.abort();
    this._abortCtl = null;
    this._abortNamed();
  }

  /** view 生命週期級別的 signal — deactivate 時統一 abort。 */
  signal() {
    return this._abortCtl?.signal;
  }

  /**
   * 「同名請求」signal — 第二次以同 name 呼叫會 abort 前一次。
   * 解決「同 view 內連按按鈕造成 race」的問題：
   *   const sig = this.requestSignal('analyze');
   *   await this._api.getStockInsights(ticker, period, { signal: sig });
   * deactivate / unmount 時所有 named 也會被 abort。
   */
  requestSignal(name) {
    this._namedCtls.get(name)?.abort();
    const ctl = new AbortController();
    this._namedCtls.set(name, ctl);
    return ctl.signal;
  }

  _abortNamed() {
    for (const ctl of this._namedCtls.values()) ctl.abort();
    this._namedCtls.clear();
  }

  unmount() {
    this._abortCtl?.abort();
    this._abortCtl = null;
    this._abortNamed();
    if (this.container) this.container.innerHTML = '';
    this.mounted = false;
  }
}
