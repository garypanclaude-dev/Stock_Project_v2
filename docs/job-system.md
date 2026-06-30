# Job System — 長任務統一機制

> 版本：v1.0　最後更新：2026-06-30

## 為什麼存在

舊架構下，所有長任務（backtest、ML train/predict、refresh TW data）都是同步
HTTP endpoint，前端發 `fetch` 後就只能等。產生兩個問題：

1. **切走 view 或 refresh 瀏覽器 → 後端 thread 還在跑**。Python `to_thread`
   無法強殺 worker thread，前端取消 Promise 完全沒效。
2. **沒有 single-flight**：使用者連點幾次按鈕，就會堆出幾條重複 thread，
   各自跑完整輪。

Job 系統把長任務跟 HTTP 請求生命週期解耦：請求只負責「提交」與「查狀態」，
真正的工作跑在 background thread pool，並且：

- 同一邏輯任務（如 `ml_train:momentum`）任何時刻只會有一個在跑（single-flight）。
- 任務可主動取消（合作式：任務需在迴圈中 check `cancel_event`）。
- 任務可回報百分比進度與訊息。
- 切走 view 或 refresh 瀏覽器，任務不中斷；前端透過 localStorage 存的
  `job_id` 自動接回輪詢。

## 架構

```
┌────────────┐  submitJob   ┌─────────────┐  submit   ┌──────────────┐
│ View       │ ───────────▶ │ JobStore    │ ────────▶ │ /api/jobs    │
│ (button)   │              │ (frontend)  │           │ FastAPI      │
│            │ ◀─ subscribe │             │ ◀─ poll ─ │              │
└────────────┘              └─────────────┘           └──────┬───────┘
       │                          ▲                         │
       │ JobProgress              │                         ▼
       │ (進度條 + 取消鈕)        │              ┌──────────────────┐
       │                          │              │ JobManager       │
       │                          │   GET/DEL    │ (singleton)      │
       │                          └──────────────│ ThreadPoolExecutor│
       │                                         │ + by_key dedup   │
       │                                         └────────┬─────────┘
       │                                                  │
       │                                                  ▼
       │                                         ┌─────────────────┐
       │                                         │ 任務函式         │
       │                                         │ (run_backtest…) │
       │                                         │ + ProgressReporter│
       │                                         └─────────────────┘
```

## 端點

| Method | Path                | Body / Param                                   | 回傳                                       |
|--------|---------------------|------------------------------------------------|--------------------------------------------|
| POST   | `/api/jobs`         | `{type, mock, params}`                         | `{job_id, key, status, progress, message}` |
| GET    | `/api/jobs/{id}`    | —                                              | 同上 + `result`（done 時）/ `error`        |
| DELETE | `/api/jobs/{id}`    | —                                              | `{cancelled: true}` 或 409                 |

支援的 `type`：

- `backtest`
- `refresh_tw`
- `ml_train`（`params.model = "momentum" | "reversal"`）
- `ml_predict`（同上）

## 取消語意（重要）

Python thread 無法強殺，所以「取消」是合作式：

1. 前端 DELETE → 後端 `JobManager.cancel(job_id)` 設 `cancel_event`。
2. 任務內部每個迭代呼叫 `reporter.update()`，內部會 check event，已設定就拋 `Cancelled`。
3. 任務捕到 `Cancelled` → JobManager 標 `cancelled` → 前端輪詢拿到。

**結論：取消不是即時。** 點下取消後，任務會在下個 check 點（通常 < 1 秒）真正退出。
若任務正卡在單一大呼叫（如 `lgb.predict(...)`），則要等該呼叫跑完才停。
UI 在等待期間顯示「取消中…」。

## TTL 與重啟

- 已結束（done / error / cancelled）的 job 在 10 分鐘後自動回收。
- JobManager 沒有持久化，**伺服器重啟 → 所有 job 蒸發**。
- 前端若有 localStorage 存的 `job_id`，重啟後 GET 會拿 404，store 自動清掉並把
  UI 標為「任務已過期」，使用者可重新觸發。

## 新增一個任務型別

1. **任務函式**：在對應模組寫一個函式，接受 `*, reporter: ProgressReporter | None = None`，
   在主迴圈呼叫 `reporter.update(pct, msg)`。
2. **app.py**：在 `_build_job_task` 加 dispatch case，同時將 type 名稱加入 `_JOB_TYPES`。
3. **mock**：在 `mock_data.py` 加對應 mock 函式（用 `_mock_run_with_progress` 模擬）。
4. **前端**：在對應 view 用 `jobStore.start(key, type, params)` + `JobProgress` 元件。
   `key` 應包含必要的去重參數（例如 `ml_train:momentum`、`ml_train:reversal` 分開）。

## 不適用 Job 系統的場景

短請求（< 2 秒、直讀 cache/DB）不需要走 job：

- `/api/stock-screener`、`/api/ml/status` 仍是同步 GET。
- 個股分析、batch quotes、chart 等也是同步 GET，並由 view AbortController 控制
  「切走 view 自動取消」。
