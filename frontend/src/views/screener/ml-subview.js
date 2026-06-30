// 內層 sub-view：ML 預測（動能 / 反轉雙模型）。
//
// 訓練與推論皆走 JobStore：任務跟 view 解耦，切走後背景仍續跑，
// 切回來會接回進度條；同 model 同操作不會重複觸發。

import { View } from '../../core/view.js';
import { eventBus } from '../../core/event-bus.js';
import { stripSuffix } from '../../services/ticker-utils.js';
import { fmtVol, escHtml } from '../../services/formatters.js';
import { JobProgress } from '../../components/job-progress.js';

const MODEL_LABELS = {
  momentum: { name: '動能延續', probLabel: '動能延續機率', desc: '抓延續段（趨勢中的下一波）' },
  reversal: { name: '起漲',     probLabel: '起漲機率',     desc: '抓糾結後第一根放量 K' },
};

const trainKey   = (m) => `ml_train:${m}`;
const predictKey = (m) => `ml_predict:${m}`;


export class MLSubView extends View {
  constructor({ apiClient, jobStore }) {
    super();
    this._api = apiClient;
    this._jobStore = jobStore;
    this._loaded = false;
    this._model = 'momentum';
    this._progress = null;
  }

  mount(container) {
    super.mount(container);
    container.innerHTML = '<div data-bind="ml-content"><div class="text-center text-slate-500 text-sm py-8">載入中…</div></div>';
    this._content = container.querySelector('[data-bind="ml-content"]');
  }

  async activate() {
    super.activate();
    if (!this._loaded) await this.reload();
  }

  invalidate() { this._loaded = false; }

  deactivate() {
    // 切走 ML sub-tab 時取消當前 predict job（train 留著，使用者可能想等它跑完）。
    // 切回來時 reload() 若 train 還在跑會接回進度條；predict 則重新觸發。
    if (this._jobStore?.isActive(predictKey(this._model))) {
      this._jobStore.cancel(predictKey(this._model));
    }
    super.deactivate();
  }

  unmount() {
    this._destroyProgress();
    if (this._jobStore?.isActive(predictKey(this._model))) {
      this._jobStore.cancel(predictKey(this._model));
    }
    super.unmount();
  }

  async reload() {
    // 捕獲當下 model；任何 await 後若 this._model 已被使用者切換，
    // 就放棄這次 reload，避免拿 momentum 的 status 卻 submit reversal job 的 race。
    const model = this._model;
    const isStale = () => this._model !== model;

    this._destroyProgress();
    const toggle = this._renderToggle();
    this._content.innerHTML = toggle + '<div data-bind="progress"></div><div data-bind="body"><div class="text-center text-slate-500 text-sm py-8">檢查模型狀態…</div></div>';
    this._bindToggle();

    // 若有訓練中的 job，直接接回進度條
    if (this._jobStore.isActive(trainKey(model))) {
      this._attachTrainProgress();
      return;
    }

    try {
      const status = await this._api.getMLStatus(model, { signal: this.requestSignal('ml-status') });
      if (isStale()) return;
      if (!status.trained) {
        this._body().innerHTML = this._renderNoModel();
        this._bindTrainButton();
        return;
      }

      // 有模型就觸發推論 job（若同 key 已 active 會自動 dedup）
      this._body().innerHTML = '<div class="text-center text-slate-500 text-sm py-8">執行模型推論中…</div>';
      this._attachPredictProgress();
      await this._jobStore.start(predictKey(model), 'ml_predict', { model });
    } catch (err) {
      if (err.name === 'AbortError' || isStale()) return;
      console.error('ML load failed:', err);
      this._body().innerHTML = `<div class="text-center text-red-400 text-sm py-8">ML 載入失敗：${escHtml(err.message)}</div>`;
    }
  }

  _body()    { return this._content.querySelector('[data-bind="body"]'); }
  _progEl()  { return this._content.querySelector('[data-bind="progress"]'); }

  _renderToggle() {
    const training = this._jobStore.isActive(trainKey(this._model));
    const opts = ['momentum', 'reversal'].map(m => {
      const active = m === this._model;
      const cls = active
        ? 'bg-blue-600 text-white shadow-sm'
        : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200';
      return `<button data-model="${m}" ${training ? 'disabled' : ''}
        class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${cls}">
        ${MODEL_LABELS[m].name}
      </button>`;
    }).join('');
    return `
      <div class="flex items-center justify-between mb-4 pb-3 border-b border-slate-700/60">
        <div class="flex items-center gap-2">
          <span class="text-xs text-slate-500">模型：</span>
          <div class="inline-flex gap-1 bg-slate-900/50 p-1 rounded-xl border border-slate-700" data-bind="model-toggle">${opts}</div>
        </div>
        <span class="text-xs text-slate-600 italic">${MODEL_LABELS[this._model].desc}</span>
      </div>`;
  }

  _renderNoModel() {
    const label = MODEL_LABELS[this._model];
    return `
      <div class="text-center py-12">
        <div class="text-4xl mb-3">🤖</div>
        <p class="text-slate-400 text-sm mb-4">尚未訓練「${label.name}」模型</p>
        <button data-action="train" class="bg-blue-600 hover:bg-blue-500 active:bg-blue-700 px-4 py-2 rounded-lg font-semibold text-sm transition-colors">
          開始訓練
        </button>
        <p class="text-xs text-slate-600 mt-3">訓練約需 1-3 分鐘，使用歷史資料建立 LightGBM 預測模型</p>
      </div>`;
  }

  _renderResults(data) {
    const info = data.model_info || {};
    const picks = data.top_picks || data.predictions || [];
    const label = MODEL_LABELS[this._model];
    const metrics = info.metrics || {};

    const infoHtml = `
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <div class="bg-slate-900/50 rounded-xl p-3 border border-slate-700 text-center">
          <div class="text-xs text-slate-500 mb-1">訓練樣本</div>
          <div class="text-lg font-bold tabular-nums">${(info.total_samples||0).toLocaleString()}</div>
        </div>
        <div class="bg-slate-900/50 rounded-xl p-3 border border-slate-700 text-center">
          <div class="text-xs text-slate-500 mb-1">OOS AUC</div>
          <div class="text-lg font-bold tabular-nums">${metrics.oos_auc ?? '–'}</div>
        </div>
        <div class="bg-slate-900/50 rounded-xl p-3 border border-slate-700 text-center">
          <div class="text-xs text-slate-500 mb-1">Precision@Top10</div>
          <div class="text-lg font-bold tabular-nums">${metrics.oos_precision_top10 ?? '–'}%</div>
        </div>
        <div class="bg-slate-900/50 rounded-xl p-3 border border-slate-700 text-center">
          <div class="text-xs text-slate-500 mb-1">訓練區間</div>
          <div class="text-xs font-mono text-slate-300">${info.train_period?.start?.slice(0,10)||'–'}<br/>${info.train_period?.end?.slice(0,10)||'–'}</div>
        </div>
      </div>`;

    const fi = (info.feature_importance || []).slice(0, 10);
    const fiHtml = fi.length ? `
      <div class="bg-slate-900/50 rounded-xl p-4 border border-slate-700 mb-4">
        <h3 class="text-xs font-semibold text-slate-400 mb-3">特徵重要性 Top 10 (Gain)</h3>
        <div class="space-y-1.5">
          ${fi.map(([name, pct]) => `
            <div class="flex items-center gap-2 text-xs">
              <span class="w-32 text-slate-400 font-mono text-right shrink-0">${name}</span>
              <div class="flex-1 bg-slate-800 rounded-full h-4 overflow-hidden">
                <div class="h-full rounded-full bg-blue-500/70" style="width:${Math.min(pct / fi[0][1] * 100, 100)}%"></div>
              </div>
              <span class="w-12 text-right tabular-nums text-slate-300">${pct}%</span>
            </div>`).join('')}
        </div>
      </div>` : '';

    const tableHtml = picks.length ? `
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-xs font-semibold text-slate-400">預測排名 — ${label.probLabel} Top 30</h3>
        <button data-action="train"
          class="text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed px-3 py-1 rounded-lg text-slate-300 transition">
          重新訓練
        </button>
      </div>
      <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead><tr class="text-slate-500 border-b border-slate-700">
          <th class="py-2 px-2 text-left font-medium w-10">#</th>
          <th class="py-2 px-2 text-left font-medium">代號</th>
          <th class="py-2 px-2 text-left font-medium">名稱</th>
          <th class="py-2 px-2 text-right font-medium">${label.probLabel}%</th>
          <th class="py-2 px-2 text-center font-medium">推薦</th>
          <th class="py-2 px-2 text-right font-medium">收盤價</th>
          <th class="py-2 px-2 text-right font-medium">漲跌%</th>
          <th class="py-2 px-2 text-right font-medium">成交量(張)</th>
        </tr></thead>
        <tbody>${picks.map((p, i) => {
          const chgColor = p.change_pct >= 0 ? 'text-green-400' : 'text-red-400';
          const prob = p.breakout_probability;
          const probColor = prob >= 70 ? '#16a34a' : prob >= 50 ? '#22c55e' : prob >= 30 ? '#f59e0b' : '#94a3b8';
          const tierLabel = p.tier === 'high' ? '★★★' : p.tier === 'medium' ? '★★' : '★';
          const tierColor = p.tier === 'high' ? 'text-yellow-400' : p.tier === 'medium' ? 'text-blue-400' : 'text-slate-500';
          const sym = stripSuffix(p.symbol);
          return `<tr class="border-b border-slate-700/50 hover:bg-slate-700/30 cursor-pointer" data-symbol="${p.symbol}">
            <td class="py-2 px-2 text-slate-500">${i+1}</td>
            <td class="py-2 px-2 font-mono font-bold text-slate-200">${sym}</td>
            <td class="py-2 px-2 text-slate-300">${escHtml(p.name)}</td>
            <td class="py-2 px-2 text-right font-bold tabular-nums" style="color:${probColor}">${prob}%</td>
            <td class="py-2 px-2 text-center ${tierColor}">${tierLabel}</td>
            <td class="py-2 px-2 text-right tabular-nums text-slate-200">$${p.close}</td>
            <td class="py-2 px-2 text-right tabular-nums ${chgColor}">${p.change_pct>=0?'+':''}${p.change_pct}%</td>
            <td class="py-2 px-2 text-right tabular-nums text-slate-400">${fmtVol(p.volume)}</td>
          </tr>`;
        }).join('')}</tbody>
      </table>
      </div>` : '<div class="text-slate-500 text-sm text-center py-6">無預測結果</div>';

    this._body().innerHTML = infoHtml + fiHtml + tableHtml;
    this._bindTrainButton();
    this._bindRowNavigation();
  }

  _bindToggle() {
    this._content.querySelectorAll('[data-model]').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.disabled || btn.dataset.model === this._model) return;
        // 切走前先取消舊 model 還在跑的 predict job，避免後端 thread pool 被堆爆。
        // train job 通常使用者會等它跑完，這裡不主動取消（要取消有 UI 取消鈕）。
        const oldModel = this._model;
        if (this._jobStore.isActive(predictKey(oldModel))) {
          this._jobStore.cancel(predictKey(oldModel));
        }
        this._model = btn.dataset.model;
        this._loaded = false;
        this.reload();
      });
    });
  }

  _bindTrainButton() {
    this._content.querySelectorAll('[data-action="train"]').forEach(btn => {
      btn.addEventListener('click', () => this._train());
    });
  }

  _bindRowNavigation() {
    this._content.querySelectorAll('[data-symbol]').forEach(row => {
      row.addEventListener('click', () => {
        eventBus.emit('navigate', { view: 'stock', params: { ticker: row.dataset.symbol } });
      });
    });
  }

  _destroyProgress() {
    if (this._progress) { this._progress.destroy(); this._progress = null; }
  }

  _attachPredictProgress() {
    this._destroyProgress();
    const model = this._model;
    this._progress = new JobProgress(this._jobStore, predictKey(model), {
      onDone: (data) => {
        if (model !== this._model) return;  // 用戶可能已切換 model
        this._renderResults(data);
        this._loaded = true;
      },
      onError: (err) => {
        if (model !== this._model) return;
        this._body().innerHTML = `<div class="text-center text-red-400 text-sm py-8">推論失敗：${escHtml(err)}</div>`;
      },
      onCancel: () => {
        if (model !== this._model) return;
        this._body().innerHTML = '<div class="text-center text-slate-500 text-sm py-8">已取消</div>';
      },
    });
    this._progEl().innerHTML = '';
    this._progEl().appendChild(this._progress.el);
    this._progress.start();
  }

  _attachTrainProgress() {
    this._destroyProgress();
    const label = MODEL_LABELS[this._model];
    this._body().innerHTML = `
      <div class="text-center py-6">
        <p class="text-slate-400 text-sm">「${label.name}」模型訓練中 …</p>
        <p class="text-xs text-slate-600 mt-1">正在計算歷史因子並訓練 LightGBM</p>
      </div>`;
    const model = this._model;
    this._progress = new JobProgress(this._jobStore, trainKey(model), {
      onDone: () => {
        if (model !== this._model) return;
        this._loaded = false;
        this.reload();
      },
      onError: (err) => {
        if (model !== this._model) return;
        this._body().innerHTML = `
          <div class="text-center py-12">
            <p class="text-red-400 text-sm mb-4">訓練失敗：${escHtml(err)}</p>
            <button data-action="train" class="bg-slate-700 hover:bg-slate-600 px-4 py-2 rounded-lg text-sm transition-colors">重試</button>
          </div>`;
        this._bindTrainButton();
      },
      onCancel: () => {
        if (model !== this._model) return;
        this._body().innerHTML = `
          <div class="text-center py-12">
            <p class="text-slate-500 text-sm mb-4">訓練已取消</p>
            <button data-action="train" class="bg-slate-700 hover:bg-slate-600 px-4 py-2 rounded-lg text-sm transition-colors">重新訓練</button>
          </div>`;
        this._bindTrainButton();
      },
    });
    this._progEl().innerHTML = '';
    this._progEl().appendChild(this._progress.el);
    this._progress.start();
  }

  async _train() {
    if (this._jobStore.isActive(trainKey(this._model))) return;
    this._attachTrainProgress();
    try {
      await this._jobStore.start(trainKey(this._model), 'ml_train', { model: this._model });
    } catch {
      // onError 已處理
    }
  }
}
