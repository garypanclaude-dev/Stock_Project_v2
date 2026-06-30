"""任務取消與進度回報的共用協定。

設計目的：讓重活函式（backtester / ml train / refresh tw_data ...）不需要
直接認識 JobManager 的存在，只透過 ProgressReporter 這層薄協定回報進度
與檢查是否被取消。這樣：
  - 任務函式可獨立測試（傳 None 或 mock reporter 即可）
  - 任務函式對 job 系統零耦合，未來換成 celery / RQ 也不用改任務本身
"""

from __future__ import annotations

import threading
from typing import Callable, Optional


class Cancelled(Exception):
    """任務在 cancel_event 被設定後，於下一個 check 點主動拋出。"""


ProgressCallback = Callable[[float, str], None]


class ProgressReporter:
    """任務內部唯一接觸的協定。

    用法：
        reporter.update(40, "building dataset")
        reporter.section(0.4, 0.7)  # 切子區段，內部 update(0~100) 會被線性映射

    傳 None 給任務函式時，任務可用 ProgressReporter.noop() 取得空實作，
    避免每個呼叫點都要 `if reporter is not None`。
    """

    def __init__(
        self,
        callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
        _base: float = 0.0,
        _span: float = 100.0,
    ):
        self._cb = callback
        self._cancel = cancel_event
        self._base = _base
        self._span = _span

    @classmethod
    def noop(cls) -> "ProgressReporter":
        return cls()

    def update(self, pct: float, message: str = "") -> None:
        """回報進度（0-100）。同時檢查取消旗標。"""
        self.check_cancelled()
        if self._cb is None:
            return
        mapped = self._base + (max(0.0, min(100.0, pct)) / 100.0) * self._span
        self._cb(round(mapped, 1), message)

    def check_cancelled(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            raise Cancelled()

    def section(self, start_frac: float, end_frac: float) -> "ProgressReporter":
        """建立子區段 reporter。子任務的 0~100 會被映射到父的 start~end。

        例如父 reporter 是 0~100，呼叫 section(0.1, 0.7) 取得的子 reporter
        在內部 update(50) 時，父實際回報 40。
        """
        assert 0.0 <= start_frac <= end_frac <= 1.0
        child_base = self._base + start_frac * self._span
        child_span = (end_frac - start_frac) * self._span
        return ProgressReporter(self._cb, self._cancel, child_base, child_span)
