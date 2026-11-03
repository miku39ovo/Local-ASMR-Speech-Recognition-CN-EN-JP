"""文件队列表格模型。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from ..core.pipeline import Job
from .progress import PROGRESS_ROLE

COLS = ["文件名", "时长", "语言", "状态", "进度", "用时", "备注"]
LANG_LABEL = {"ja": "日语", "en": "英语", "zh": "中文", "auto": "自动", None: "跟随"}
STATUS_LABEL = {
    "pending": "等待", "running": "识别中", "done": "完成",
    "skipped": "跳过", "failed": "失败", "cancelled": "已取消",
}
STATUS_COLOR = {
    "pending": "#8b94a5", "running": "#6ea8ff", "done": "#5fd08a",
    "skipped": "#a2a9b8", "failed": "#ff8080", "cancelled": "#c39a6b",
}


def fmt_dur(sec: float) -> str:
    if sec <= 0:
        return "--:--"
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


class JobTableModel(QAbstractTableModel):
    def __init__(self, jobs: list[Job] | None = None):
        super().__init__()
        self.jobs: list[Job] = jobs or []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.jobs)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        job = self.jobs[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return job.display_name
            if col == 1:
                return fmt_dur(job.duration)
            if col == 2:
                return LANG_LABEL.get(job.language, "跟随")
            if col == 3:
                return STATUS_LABEL.get(job.status, job.status)
            if col == 4:
                return f"{job.progress}%"
            if col == 5:
                return f"{job.elapsed:.0f}s" if job.elapsed else ""
            if col == 6:
                return job.message
        elif role == PROGRESS_ROLE:
            return job.progress
        elif role == Qt.ForegroundRole:
            if col == 3:
                return QBrush(QColor(STATUS_COLOR.get(job.status, "#c9d1de")))
            if col == 6:
                return QBrush(QColor("#9aa4b4") if job.status == "done" else "#d99b9b")
        elif role == Qt.TextAlignmentRole:
            if col in (1, 4, 5):
                return int(Qt.AlignCenter)
            return int(Qt.AlignVCenter | Qt.AlignLeft)
        elif role == Qt.ToolTipRole:
            if col == 0:
                return str(job.path)
            if col == 6 and job.message:
                return job.message
        return None

    # ---- 操作 ----
    def add_paths(self, paths: list[Path]) -> int:
        existing = {str(j.path).lower() for j in self.jobs}
        new_jobs = []
        for p in paths:
            key = str(p).lower()
            if key in existing:
                continue
            existing.add(key)
            new_jobs.append(Job(path=p))
        if new_jobs:
            start = len(self.jobs)
            self.beginInsertRows(QModelIndex(), start, start + len(new_jobs) - 1)
            self.jobs.extend(new_jobs)
            self.endInsertRows()
        return len(new_jobs)

    def remove_rows(self, rows: list[int]) -> None:
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < len(self.jobs):
                self.beginRemoveRows(QModelIndex(), row, row)
                del self.jobs[row]
                self.endRemoveRows()

    def clear(self) -> None:
        self.beginResetModel()
        self.jobs.clear()
        self.endResetModel()

    def refresh_row(self, row: int) -> None:
        if 0 <= row < len(self.jobs):
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLS) - 1))

    def job(self, row: int) -> Job | None:
        return self.jobs[row] if 0 <= row < len(self.jobs) else None
