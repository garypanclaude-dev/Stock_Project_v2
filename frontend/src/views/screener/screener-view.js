// 潛力選股 view（頂層 view）。
//
// 透過 TabController 管理三個 sub-view，展示 TabController 的可重用性
// （與頂層 view 切換器共用同一份實作）。
//
// 對外監聽：mock 切換時讓所有 sub-view 失效，下次切回再 reload。

import { View } from '../../core/view.js';
import { TabController } from '../../core/tab-controller.js';
import { eventBus } from '../../core/event-bus.js';
import { JobProgress } from '../../components/job-progress.js';
import { SCREENER_VIEW_TEMPLATE } from './screener-view-template.js';
import { ScreenerResultsSubView } from './screener-results-subview.js';
import { BacktestSubView } from './backtest-subview.js';
import { MLSubView } from './ml-subview.js';

export class ScreenerView extends View {
  constructor({ apiClient, jobStore }) {
    super();
    this._api = apiClient;
    this._jobStore = jobStore;
    this._subTab = null;
    this._subs = {};       // id → sub-view（保留參考方便 invalidate）
    this._unsubs = [];
    this._refreshProgress = null;
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = SCREENER_VIEW_TEMPLATE;
    this._el = {};
    container.querySelectorAll('[data-bind]').forEach(el => { this._el[el.dataset.bind] = el; });

    this._subs.results  = new ScreenerResultsSubView({ apiClient: this._api, parent: this });
    this._subs.backtest = new BacktestSubView({ apiClient: this._api, jobStore: this._jobStore });
    this._subs.ml       = new MLSubView({ apiClient: this._api, jobStore: this._jobStore });

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
    if (this._jobStore.isActive('refresh_tw')) return;  // 防重複點

    btn.disabled = true;
    updated.textContent = '提交任務 …';

    // 進度條掛在 updated 旁邊
    this._refreshProgress?.destroy();
    this._refreshProgress = new JobProgress(this._jobStore, 'refresh_tw', {
      onDone: (d) => {
        if (d?.bootstrap_required) {
          updated.textContent = '⚠️ DB 為空，請先跑 python scripts/update_tw_history.py --backfill 60';
        } else if (d?.success > 0) {
          updated.textContent = `✅ 新增 ${d.success} 個交易日（最新：${d.latest_date}）`;
        } else if (d?.dates_attempted === 0) {
          updated.textContent = `已是最新（${d.latest_date}）`;
        } else if (d?.failed?.length) {
          updated.textContent = `⚠️ ${d.failed.length} 個日期抓取失敗`;
        }
        this._invalidateAll();
        btn.disabled = false;
      },
      onError: (err) => {
        console.error('Refresh TW data failed:', err);
        updated.textContent = `⚠️ 增量更新失敗：${err}`;
        btn.disabled = false;
      },
      onCancel: () => {
        updated.textContent = '已取消';
        btn.disabled = false;
      },
    });
    updated.parentElement?.appendChild(this._refreshProgress.el);
    this._refreshProgress.start();

    try {
      await this._jobStore.start('refresh_tw', 'refresh_tw');
    } catch (err) {
      // start 內部已 update store 為 error，progress component 會接到並 reset 按鈕
    }
  }
}
