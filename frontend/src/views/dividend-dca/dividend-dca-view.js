// 高股息定期定額 view（頂層 view）。
//
// 內聚三個 sub-view：列表 → 詳情 → DCA 模擬器，
// 透過 TabController 管理切換（與 ScreenerView 同模式）。
//
// Sub-view 之間透過 navigate 事件協作：
//   list 點某列 → emit('navigate', { view:'dividend-dca', params:{ subtab:'detail', symbol }})
//   detail 點 CTA → emit('navigate', { view:'dividend-dca', params:{ subtab:'simulator', symbol }})

import { View } from '../../core/view.js';
import { TabController } from '../../core/tab-controller.js';
import { DIVIDEND_DCA_VIEW_TEMPLATE } from './dividend-dca-view-template.js';
import { EtfListSubView } from './etf-list-subview.js';
import { EtfDetailSubView } from './etf-detail-subview.js';
import { DcaSimulatorSubView } from './dca-simulator-subview.js';

export class DividendDcaView extends View {
  constructor({ apiClient }) {
    super();
    this._api = apiClient;
    this._subTab = null;
    this._subs = {};
    this._currentSymbol = null;
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = DIVIDEND_DCA_VIEW_TEMPLATE;
    this._el = {};
    container.querySelectorAll('[data-bind]').forEach(el => { this._el[el.dataset.bind] = el; });

    this._subs.list      = new EtfListSubView({ apiClient: this._api, parent: this });
    this._subs.detail    = new EtfDetailSubView({ apiClient: this._api, parent: this });
    this._subs.simulator = new DcaSimulatorSubView({ apiClient: this._api, parent: this });

    this._subTab = new TabController({
      container: this._el['sub-container'],
      onChange: (_from, to) => this._syncTabButtons(to),
    });
    this._subTab.register('list',      this._subs.list);
    this._subTab.register('detail',    this._subs.detail);
    this._subTab.register('simulator', this._subs.simulator);

    this._el['sub-tabs']?.addEventListener('click', e => {
      const btn = e.target.closest('[data-tab]');
      if (!btn) return;
      const tab = btn.dataset.tab;
      // detail / simulator 需要 symbol；若還沒選過，回列表
      if ((tab === 'detail' || tab === 'simulator') && !this._currentSymbol) {
        this._subTab.switchTo('list');
        this.setStatus('請先從列表選一檔 ETF');
        return;
      }
      this._subTab.switchTo(tab, { symbol: this._currentSymbol });
    });
  }

  async activate(params = {}) {
    super.activate(params);
    if (params.symbol) this._currentSymbol = params.symbol;
    const initial = params.subtab && this._subTab.has(params.subtab) ? params.subtab : 'list';
    // detail / simulator 沒帶 symbol → fallback list
    const target = (initial !== 'list' && !this._currentSymbol) ? 'list' : initial;
    await this._subTab.switchTo(target, { symbol: this._currentSymbol });
  }

  unmount() {
    for (const sv of Object.values(this._subs)) sv.unmount();
    super.unmount();
  }

  // ── 給 sub-view 用 ────────────────────────────────────────────────
  setCurrentSymbol(symbol) {
    this._currentSymbol = symbol;
  }

  setStatus(text) {
    if (this._el?.status) this._el.status.textContent = text || '';
  }

  _syncTabButtons(activeId) {
    this._el['sub-tabs']?.querySelectorAll('[data-tab]').forEach(btn => {
      const active = btn.dataset.tab === activeId;
      btn.classList.toggle('bg-slate-700', active);
      btn.classList.toggle('text-slate-200', active);
      btn.classList.toggle('text-slate-500', !active);
    });
  }
}
