// 潛力選股 view（頂層 view）。
//
// 透過 TabController 管理三個 sub-view，展示 TabController 的可重用性
// （與頂層 view 切換器共用同一份實作）。
//
// 對外監聽：mock 切換時讓所有 sub-view 失效，下次切回再 reload。

import { View } from '../../core/view.js';
import { TabController } from '../../core/tab-controller.js';
import { eventBus } from '../../core/event-bus.js';
import { SCREENER_VIEW_TEMPLATE } from './screener-view-template.js';
import { ScreenerResultsSubView } from './screener-results-subview.js';
import { BacktestSubView } from './backtest-subview.js';
import { MLSubView } from './ml-subview.js';

export class ScreenerView extends View {
  constructor({ apiClient }) {
    super();
    this._api = apiClient;
    this._subTab = null;
    this._subs = {};       // id → sub-view（保留參考方便 invalidate）
    this._unsubs = [];
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = SCREENER_VIEW_TEMPLATE;
    this._el = {};
    container.querySelectorAll('[data-bind]').forEach(el => { this._el[el.dataset.bind] = el; });

    this._subs.results  = new ScreenerResultsSubView({ apiClient: this._api, parent: this });
    this._subs.backtest = new BacktestSubView({ apiClient: this._api });
    this._subs.ml       = new MLSubView({ apiClient: this._api });

    this._subTab = new TabController({
      container: this._el['sub-container'],
      onChange: (_from, to) => this._syncTabButtons(to),
    });
    this._subTab.register('results',  this._subs.results);
    this._subTab.register('backtest', this._subs.backtest);
    this._subTab.register('ml',       this._subs.ml);

    this._el['sub-tabs']?.addEventListener('click', e => {
      const btn = e.target.closest('[data-tab]');
      if (btn) this._subTab.switchTo(btn.dataset.tab);
    });

    this._el['refresh-btn']?.addEventListener('click', () => this._refresh());

    this._unsubs.push(eventBus.on('mock:change', () => this._invalidateAll()));
  }

  async activate(params = {}) {
    super.activate(params);
    const initial = params.subtab && this._subTab.has(params.subtab) ? params.subtab : 'results';
    await this._subTab.switchTo(initial);
  }

  unmount() {
    this._unsubs.forEach(u => u()); this._unsubs = [];
    for (const sv of Object.values(this._subs)) sv.unmount();
    super.unmount();
  }

  setUpdatedText(text) {
    if (this._el?.updated) this._el.updated.textContent = text;
  }

  _syncTabButtons(activeId) {
    this._el['sub-tabs']?.querySelectorAll('[data-tab]').forEach(btn => {
      const active = btn.dataset.tab === activeId;
      btn.classList.toggle('bg-slate-700', active);
      btn.classList.toggle('text-slate-200', active);
      btn.classList.toggle('text-slate-500', !active);
    });
  }

  _invalidateAll() {
    for (const sv of Object.values(this._subs)) sv.invalidate?.();
    // 當前 active 的 sub-view 立即重抓（其他延後到下次切過去）
    const current = this._subTab.current();
    if (current && this._subs[current]?.reload) this._subs[current].reload();
  }

  async _refresh() {
    const btn = this._el['refresh-btn'];
    const updated = this._el.updated;
    const originalLabel = btn.textContent;
    btn.disabled = true;
    try {
      // 此 refresh 是針對「篩選結果」的台股增量抓取，其他 sub-view 共用 backend 資料源
      btn.textContent = '抓取中…';
      try {
        const d = await this._api.refreshTwData();
        if (d.bootstrap_required) {
          updated.textContent = '⚠️ DB 為空，請先跑 python scripts/update_tw_history.py --backfill 60';
        } else if (d.success > 0) {
          updated.textContent = `✅ 新增 ${d.success} 個交易日（最新：${d.latest_date}）`;
        } else if (d.dates_attempted === 0) {
          updated.textContent = `已是最新（${d.latest_date}）`;
        } else if (d.failed?.length) {
          updated.textContent = `⚠️ ${d.failed.length} 個日期抓取失敗`;
        }
      } catch (err) {
        console.error('Refresh TW data failed:', err);
        updated.textContent = '⚠️ 增量更新失敗';
      }
      btn.textContent = '重新計算中…';
      this._invalidateAll();
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }
}
