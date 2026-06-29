// 全域 app 狀態（mock 開關、目前 ticker、目前 period、目前 view）。
//
// 刻意做成 store + event 模式，而非散落的全域變數。任何改動透過
// set 方法觸發 emit，components / views 訂閱關心的欄位。

class StateStore {
  constructor() {
    this._state = {
      isMock: true,            // 預設 MOCK（與舊版行為一致）
      currentTicker: 'AAPL',
      currentPeriod: '3M',
      currentView: null,
    };
    this._handlers = new Map();  // key → Set<handler>
  }

  get isMock()         { return this._state.isMock; }
  get currentTicker()  { return this._state.currentTicker; }
  get currentPeriod()  { return this._state.currentPeriod; }
  get currentView()    { return this._state.currentView; }

  set(key, value) {
    if (!(key in this._state)) {
      console.warn(`[state-store] unknown key "${key}"`);
      return;
    }
    if (this._state[key] === value) return;
    const oldValue = this._state[key];
    this._state[key] = value;
    this._emit(key, value, oldValue);
  }

  on(key, handler) {
    if (!this._handlers.has(key)) this._handlers.set(key, new Set());
    this._handlers.get(key).add(handler);
    return () => this._handlers.get(key)?.delete(handler);
  }

  _emit(key, value, oldValue) {
    const hs = this._handlers.get(key);
    if (!hs) return;
    for (const h of hs) {
      try { h(value, oldValue); }
      catch (err) { console.error(`[state-store] handler for "${key}" threw:`, err); }
    }
  }
}

export const stateStore = new StateStore();
