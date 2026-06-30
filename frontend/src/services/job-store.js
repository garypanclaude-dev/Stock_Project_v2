// Job store — 集中管理長任務狀態（submit / poll / cancel / 復原）。
//
// 設計目的：
//   - View 不直接操作 setInterval / fetch；只負責 subscribe(key, cb) 和
//     start(key, type, params)，狀態變化會推給 callback
//   - 任務跟 view 解耦：切走 view、refresh 瀏覽器都不會中斷 job，
//     回來時 store 從 localStorage 取回 job_id 繼續輪詢
//   - 同一個邏輯任務（如「訓練 momentum」）以業務 key 識別，避免重複觸發
//
// 與後端的對應：
//   start(key, type, params)         → POST /api/jobs
//   輪詢                              → GET /api/jobs/{id}
//   cancel(key)                       → DELETE /api/jobs/{id}

const POLL_INTERVAL_MS = 1000;
const STORAGE_PREFIX = 'job_store:';

const TERMINAL = new Set(['done', 'error', 'cancelled']);


export class JobStore {
  constructor(apiClient) {
    this._api = apiClient;
    this._jobs = new Map();          // key -> { jobId, status, progress, message, result, error }
    this._timers = new Map();        // key -> setInterval id
    this._subscribers = new Map();   // key -> Set<cb>
    this._restoreFromStorage();
  }

  // ── 對外 API ─────────────────────────────────────────────────────

  /**
   * 訂閱某個任務 key 的狀態變化。會立即用目前狀態呼叫一次 cb（若有）。
   * 回傳 unsubscribe 函式。
   */
  subscribe(key, cb) {
    if (!this._subscribers.has(key)) this._subscribers.set(key, new Set());
    this._subscribers.get(key).add(cb);

    const current = this._jobs.get(key);
    if (current) cb(current);

    return () => {
      const set = this._subscribers.get(key);
      if (set) set.delete(cb);
    };
  }

  /** 取得 key 目前狀態（同步），無則 undefined。 */
  get(key) { return this._jobs.get(key); }

  /** 該 key 是否有 in-flight 任務。 */
  isActive(key) {
    const j = this._jobs.get(key);
    return !!j && !TERMINAL.has(j.status);
  }

  /**
   * 提交新任務。若同 key 已 active，直接回現有狀態（不重送）。
   * type / params 對應後端 /api/jobs 的 body。
   */
  async start(key, type, params = {}) {
    if (this.isActive(key)) return this._jobs.get(key);

    // 進 optimistic pending 狀態，UI 立刻可以顯示「送出中 …」
    this._update(key, {
      jobId: null, status: 'pending', progress: 0, message: '送出中 …',
      result: null, error: null,
    });

    try {
      const snap = await this._api.submitJob(type, params);
      this._update(key, this._normalize(snap));
      this._persist(key);
      this._startPolling(key);
      return this._jobs.get(key);
    } catch (err) {
      this._update(key, {
        jobId: null, status: 'error', progress: 0, message: '',
        result: null, error: err.message || String(err),
      });
      this._finalize(key);
      throw err;
    }
  }

  /** 取消任務。
   *  本地立刻 mark cancelled 並 _finalize，讓 isActive() 即刻回 false，
   *  使用者連續「取消→重啟」同 key 才不會卡在「取消中 …」的舊 job。
   *  後端的真正中止仍是合作式（任務需在迴圈中 check event），這裡 best-effort。
   */
  async cancel(key) {
    const job = this._jobs.get(key);
    if (!job || !job.jobId || TERMINAL.has(job.status)) return;
    this._update(key, { ...job, status: 'cancelled', message: '已取消', progress: job.progress });
    this._finalize(key);
    try {
      await this._api.cancelJob(job.jobId);
    } catch (err) {
      // 後端可能已結束或不存在；前端狀態已是終態，忽略即可
      console.warn('[job-store] cancel ack failed:', err.message);
    }
  }

  /** 清掉已結束任務的本地狀態（讓 UI 收掉進度條）。 */
  clear(key) {
    this._stopPolling(key);
    this._jobs.delete(key);
    this._removeStorage(key);
    this._notify(key, null);
  }

  /** 內部使用：任務進入 terminal 後同步呼叫，集中清理輪詢/儲存/快取狀態。
   *
   *  之所以**刪除** _jobs 中的 terminal 狀態：避免下次 subscribe 時 initial cb
   *  立刻把舊結果送出去，造成「切走又切回來，UI 顯示上一輪殘留資料」的 bug。
   *  此處的順序很重要 — 必須在 _update notify 之後呼叫，subscribers 才有機會
   *  收到 terminal 狀態並處理。
   */
  _finalize(key) {
    this._stopPolling(key);
    this._removeStorage(key);
    this._jobs.delete(key);
  }

  // ── 內部 ─────────────────────────────────────────────────────────

  _normalize(snap) {
    return {
      jobId: snap.job_id,
      status: snap.status,
      progress: snap.progress ?? 0,
      message: snap.message ?? '',
      result: snap.result ?? null,
      error: snap.error ?? null,
    };
  }

  _update(key, state) {
    this._jobs.set(key, state);
    this._notify(key, state);
  }

  _notify(key, state) {
    const subs = this._subscribers.get(key);
    if (subs) subs.forEach((cb) => { try { cb(state); } catch (e) { console.error(e); } });
  }

  _startPolling(key) {
    this._stopPolling(key);
    const tick = async () => {
      const job = this._jobs.get(key);
      if (!job || !job.jobId) return this._stopPolling(key);
      try {
        const snap = await this._api.getJob(job.jobId);
        this._update(key, this._normalize(snap));
        if (TERMINAL.has(snap.status)) {
          this._finalize(key);
        }
      } catch (err) {
        // 404 = 後端已回收（重啟過），視為不存在，停止輪詢
        if (/not found/i.test(err.message) || /404/.test(err.message)) {
          this._update(key, {
            jobId: null, status: 'error', progress: 0, message: '',
            result: null, error: '任務已過期（伺服器可能重啟過）',
          });
          this._finalize(key);
        }
      }
    };
    // 立即跑一次再開始定時，避免 1 秒空窗
    tick();
    this._timers.set(key, setInterval(tick, POLL_INTERVAL_MS));
  }

  _stopPolling(key) {
    const id = this._timers.get(key);
    if (id) clearInterval(id);
    this._timers.delete(key);
  }

  // ── localStorage 持久化（只存 jobId，狀態還是回伺服器拿） ──────────

  _persist(key) {
    const job = this._jobs.get(key);
    if (!job || !job.jobId || TERMINAL.has(job.status)) return;
    try {
      localStorage.setItem(STORAGE_PREFIX + key, job.jobId);
    } catch {}
  }

  _removeStorage(key) {
    try { localStorage.removeItem(STORAGE_PREFIX + key); } catch {}
  }

  _restoreFromStorage() {
    try {
      for (let i = 0; i < localStorage.length; i += 1) {
        const storageKey = localStorage.key(i);
        if (!storageKey || !storageKey.startsWith(STORAGE_PREFIX)) continue;
        const key = storageKey.slice(STORAGE_PREFIX.length);
        const jobId = localStorage.getItem(storageKey);
        if (!jobId) continue;
        this._jobs.set(key, {
          jobId, status: 'pending', progress: 0, message: '恢復中 …',
          result: null, error: null,
        });
        this._startPolling(key);
      }
    } catch (err) {
      console.warn('[job-store] restore failed:', err);
    }
  }
}
