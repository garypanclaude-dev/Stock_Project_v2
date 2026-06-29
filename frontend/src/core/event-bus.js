// 極簡 pub/sub event bus。
//
// 用途：讓 components（header、sidebar）與 views 解耦 —— 元件廣播事件，
// 由有興趣的 view 自行訂閱，元件不需要知道下游 view 的存在。
//
// 約定事件名（命名空間:動作）：
//   ticker:change   payload = { symbol }
//   period:change   payload = { period }
//   mock:change     payload = { isMock }
//   view:change     payload = { from, to }
//   watchlist:change payload = { tickers }

class EventBus {
  constructor() {
    this._handlers = new Map();   // event name → Set<handler>
  }

  on(event, handler) {
    if (!this._handlers.has(event)) this._handlers.set(event, new Set());
    this._handlers.get(event).add(handler);
    return () => this.off(event, handler);  // 回傳取消訂閱函式，方便 view unmount 時清理
  }

  off(event, handler) {
    this._handlers.get(event)?.delete(handler);
  }

  emit(event, payload) {
    const handlers = this._handlers.get(event);
    if (!handlers) return;
    for (const h of handlers) {
      try { h(payload); }
      catch (err) { console.error(`[event-bus] handler for "${event}" threw:`, err); }
    }
  }
}

export const eventBus = new EventBus();
