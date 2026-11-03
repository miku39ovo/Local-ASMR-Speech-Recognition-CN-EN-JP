"""后台批处理线程。"""
from __future__ import annotations

import copy
import logging
import time
import traceback

from PySide6.QtCore import QThread, Signal

from ..config import Settings
from ..core.engine import AsrEngine
from ..core.pipeline import Cancelled, Job, process_file

log = logging.getLogger(__name__)


class BatchWorker(QThread):
    job_started = Signal(int)
    job_progress = Signal(int, int, str)
    job_done = Signal(int, str, str)
    message = Signal(str)
    all_done = Signal()

    def __init__(self, rows: list[tuple[int, Job]], settings: Settings, parent=None):
        super().__init__(parent)
        self._rows = rows
        self._settings = copy.deepcopy(settings)
        self._stop = False
        self._paused = False
        self.engine = AsrEngine()

    # ---- 控制 ----
    def stop(self) -> None:
        self._stop = True
        self._paused = False

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def _gate(self) -> bool:
        """返回 True 表示需要停止。暂停期间在此阻塞。"""
        while self._paused and not self._stop:
            time.sleep(0.12)
        return self._stop

    def run(self) -> None:
        try:
            for idx, job in self._rows:
                if self._stop:
                    break
                if self._gate():
                    break
                job.status = "running"
                job.progress = 0
                job.message = ""
                self.job_started.emit(idx)
                self.message.emit(f"▶ {job.path.name}")

                def prog(p: int, m: str, _idx=idx) -> None:
                    self.job_progress.emit(_idx, p, m)

                try:
                    res = process_file(
                        job, self._settings, self.engine,
                        progress=prog,
                        cancel=self._gate,
                        on_log=self.message.emit,
                    )
                    job.status = res.status
                    job.progress = 100 if res.status == "done" else job.progress
                    job.elapsed = res.elapsed
                    job.duration = res.duration or job.duration
                    job.tokens = res.tokens
                    job.tps = res.tps
                    job.message = res.message
                except Cancelled:
                    job.status = "cancelled"
                    job.message = "已取消"
                except Exception as exc:  # noqa: BLE001
                    job.status = "failed"
                    job.message = str(exc)
                    log.error("处理失败 %s: %s\n%s", job.path, exc, traceback.format_exc())
                    self.message.emit(f"✖ {job.path.name}: {exc}")
                self.job_done.emit(idx, job.status, job.message)
        finally:
            self.engine.release()
            self.all_done.emit()
