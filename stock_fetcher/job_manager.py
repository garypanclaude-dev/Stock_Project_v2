"""Job 排程與生命週期管理（純記憶體，單機）。

職責：
  - 接收任務提交、配 job_id、跑在 ThreadPoolExecutor
  - 同 task_key 的 single-flight 去重（第二個提交直接回現有 job_id）
  - 維護 job 狀態（pending/running/done/error/cancelled）+ 進度 + 訊息
  - 提供取消（合作式：透過 threading.Event 通知任務，任務需在 check 點主動退出）
  - TTL 自動回收已結束的 job，避免記憶體無限漲

不做的事：
  - 不認識 FastAPI、不認識前端、不認識任何任務函式內部邏輯
  - 不持久化（重啟蒸發，符合需求）
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .cancellation import Cancelled, ProgressReporter

logger = logging.getLogger(__name__)


JobStatus = str  # "pending" | "running" | "done" | "error" | "cancelled"


@dataclass
class Job:
    id: str
    key: str
    status: JobStatus = "pending"
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Optional[Future] = None

    def snapshot(self, include_result: bool = False) -> dict:
        """回傳純資料字典（給 API 序列化）。result 僅在 done 時才帶。"""
        data = {
            "job_id": self.id,
            "key": self.key,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_result and self.status == "done":
            data["result"] = self.result
        return data


class JobManager:
    """進程級單例。透過 get_job_manager() 取用，不要直接 new。"""

    def __init__(self, max_workers: int = 2, ttl_seconds: int = 600):
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}  # task_key -> active job_id
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="job"
        )
        self._ttl = ttl_seconds

    def submit(
        self,
        key: str,
        fn: Callable[..., Any],
        *args,
        **kwargs,
    ) -> Job:
        """提交任務。若同 key 已有 active job，直接回傳該 job（single-flight）。

        fn 必須接受一個 keyword 參數 reporter: ProgressReporter，
        並在內部回報進度 + 在迴圈中呼叫 reporter.check_cancelled()。
        """
        self._cleanup_locked_caller_unsafe()  # 順手清，避免另開背景 thread

        with self._lock:
            existing_id = self._by_key.get(key)
            if existing_id and self._jobs[existing_id].status in ("pending", "running"):
                logger.info("Job dedup: key=%s reuses %s", key, existing_id)
                return self._jobs[existing_id]

            job = Job(id=uuid.uuid4().hex, key=key)
            self._jobs[job.id] = job
            self._by_key[key] = job.id

        def _runner():
            self._mark(job.id, status="running", progress=0.0, message="started")
            reporter = ProgressReporter(
                callback=lambda pct, msg: self._mark(job.id, progress=pct, message=msg),
                cancel_event=job.cancel_event,
            )
            try:
                result = fn(*args, reporter=reporter, **kwargs)
                self._mark(
                    job.id,
                    status="done",
                    progress=100.0,
                    message="done",
                    result=result,
                )
            except Cancelled:
                self._mark(job.id, status="cancelled", message="cancelled")
                logger.info("Job %s cancelled (key=%s)", job.id, key)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Job %s failed (key=%s)", job.id, key)
                self._mark(job.id, status="error", error=str(exc))

        job.future = self._executor.submit(_runner)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        """合作式取消：set event，任務需在下一個 check 點才會真正退出。

        回 True 代表 event 已設定（不保證任務瞬間停）。
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in ("pending", "running"):
                return False
            job.cancel_event.set()
            if job.status == "running":
                job.message = "cancelling"
                job.updated_at = time.time()
        return True

    # ── internal ──────────────────────────────────────────────────────────

    def _mark(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for k, v in fields.items():
                setattr(job, k, v)
            job.updated_at = time.time()

    def _cleanup_locked_caller_unsafe(self) -> None:
        """清掉超過 TTL 的已結束 job。在 submit 時順手做一次。"""
        now = time.time()
        with self._lock:
            stale_ids = [
                jid
                for jid, j in self._jobs.items()
                if j.status in ("done", "error", "cancelled")
                and now - j.updated_at > self._ttl
            ]
            for jid in stale_ids:
                job = self._jobs.pop(jid, None)
                if job and self._by_key.get(job.key) == jid:
                    self._by_key.pop(job.key, None)


_singleton: Optional[JobManager] = None
_singleton_lock = threading.Lock()


def get_job_manager() -> JobManager:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = JobManager()
    return _singleton
