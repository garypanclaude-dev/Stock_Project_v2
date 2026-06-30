// Job 進度條元件（純呈現）。
//
// 職責：訂閱 JobStore 某個 key 的狀態，繪製進度條 + 訊息 + 取消鈕；
// 任務結束時把自己 detach，並透過 callback 把結果交回呼叫者。
//
// 對外不知道 fetch、不知道 endpoint —— 只認 JobStore 介面：
//   { subscribe(key, cb) → unsubscribe, cancel(key), clear(key) }
//
// 用法：
//   const progress = new JobProgress(jobStore, 'ml_train:momentum', {
//     onDone:   (result) => { ... },
//     onError:  (err)    => { ... },
//     onCancel: ()       => { ... },
//   });
//   container.appendChild(progress.el);
//   progress.start();              // 開始訂閱
//   progress.destroy();            // 解除訂閱 + 移除 DOM

export class JobProgress {
  constructor(jobStore, key, { onDone, onError, onCancel } = {}) {
    this._store = jobStore;
    this._key = key;
    this._onDone = onDone;
    this._onError = onError;
    this._onCancel = onCancel;
    this._unsub = null;
    this._handledTerminal = false;

    this.el = document.createElement('div');
    this.el.className = 'job-progress';
    this.el.innerHTML = `
      <div class="job-progress__row">
        <div class="job-progress__bar"><div class="job-progress__fill" style="width:0%"></div></div>
        <span class="job-progress__pct">0%</span>
        <button type="button" class="job-progress__cancel" data-action="cancel">取消</button>
      </div>
      <div class="job-progress__msg"></div>
    `;
    this._fill = this.el.querySelector('.job-progress__fill');
    this._pct  = this.el.querySelector('.job-progress__pct');
    this._msg  = this.el.querySelector('.job-progress__msg');
    this._cancelBtn = this.el.querySelector('[data-action="cancel"]');

    this._cancelBtn.addEventListener('click', () => {
      this._cancelBtn.disabled = true;
      this._store.cancel(this._key);
    });
  }

  start() {
    if (this._unsub) return;
    this._unsub = this._store.subscribe(this._key, (state) => this._render(state));
  }

  destroy() {
    if (this._unsub) { this._unsub(); this._unsub = null; }
    this.el.remove();
  }

  _render(state) {
    if (!state) return;
    const pct = Math.max(0, Math.min(100, state.progress || 0));
    this._fill.style.width = `${pct}%`;
    this._pct.textContent = `${pct.toFixed(1)}%`;
    this._msg.textContent = state.message || '';

    const terminal = state.status === 'done' || state.status === 'error' || state.status === 'cancelled';
    if (terminal && !this._handledTerminal) {
      this._handledTerminal = true;
      this._cancelBtn.disabled = true;
      this._cancelBtn.style.display = 'none';

      if (state.status === 'done') this._onDone?.(state.result);
      else if (state.status === 'error') this._onError?.(state.error || '未知錯誤');
      else this._onCancel?.();

      // 不必呼叫 store.clear() — JobStore 自己會在 _finalize 中清理 terminal 狀態
    }
  }
}
