// 通用 tab 控制器。
//
// 同時驅動頂層分頁（個股分析 / 潛力選股 / 策略回測 / …）與
// 內層分頁（screener 內的 篩選結果 / 回測 / ML）。零業務知識：只負責切換 view。
//
// 與 View 介面協作：第一次切到某個 view 時呼叫 mount，再 activate；
// 切走時呼叫前一個 view 的 deactivate。view 自己決定要不要在 deactivate
// 暫停輪詢、釋放資源。
//
// 用法：
//   const ctrl = new TabController({ container, onChange });
//   ctrl.register('stock',    new StockView(...));
//   ctrl.register('screener', new ScreenerView(...));
//   ctrl.switchTo('stock');

export class TabController {
  constructor({ container = null, onChange = null } = {}) {
    this._container = container;     // 所有 view 共用的父容器（每個 view 一個子 div）
    this._onChange = onChange;       // (from, to) → void，可用來同步 URL / 發事件
    this._views = new Map();         // id → View instance
    this._panels = new Map();        // id → HTMLElement（view 的容器 div）
    this._activeId = null;
  }

  register(id, view) {
    if (this._views.has(id)) throw new Error(`TabController: id "${id}" already registered`);
    this._views.set(id, view);
    // Lazy mount：第一次 switchTo 才建立 panel + 呼叫 view.mount
  }

  has(id) { return this._views.has(id); }
  current() { return this._activeId; }

  async switchTo(id, params = {}) {
    if (!this._views.has(id)) {
      console.warn(`TabController: unknown view "${id}"`);
      return;
    }
    if (id === this._activeId) {
      // 重複觸發只刷新一次 activate（讓 view 自行決定要不要重抓資料）
      await this._views.get(id).activate(params);
      return;
    }

    const from = this._activeId;
    if (from) {
      await this._views.get(from).deactivate();
    }

    const view = this._views.get(id);
    if (!view.mounted) {
      const panel = this._ensurePanel(id);
      await view.mount(panel);
    }
    await view.activate(params);

    this._activeId = id;
    this._onChange?.(from, id);
  }

  _ensurePanel(id) {
    if (this._panels.has(id)) return this._panels.get(id);
    if (!this._container) {
      throw new Error('TabController: container not provided; cannot create panel');
    }
    const panel = document.createElement('div');
    panel.id = `view-panel-${id}`;
    panel.className = 'hidden';
    this._container.appendChild(panel);
    this._panels.set(id, panel);
    return panel;
  }
}
