"""模型管理对话框。"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..config import MODELS_DIR
from ..core.models import MODEL_SPECS, ModelSpec, dir_size, download, human_size, import_local, installed


class _DownloadWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(bool, str)

    def __init__(self, spec: ModelSpec, src: Path | None = None, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.src = src

    def run(self) -> None:
        try:
            if self.src:
                import_local(self.spec, self.src, self.progress.emit)
            else:
                download(self.spec, self.progress.emit)
            self.finished_ok.emit(True, "完成")
        except Exception as exc:  # noqa: BLE001
            self.finished_ok.emit(False, str(exc))


class ModelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("模型管理")
        self.resize(760, 360)
        self._worker: _DownloadWorker | None = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        tip = QLabel("模型保存在 D 盘程序目录下的 models\\，下载源走国内镜像。")
        tip.setObjectName("hint")
        root.addWidget(tip)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["模型", "语言", "大小", "状态", "说明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        root.addWidget(self.bar)

        row = QHBoxLayout()
        self.btn_dl = QPushButton("下载选中模型")
        self.btn_dl.setObjectName("primary")
        self.btn_import = QPushButton("导入本地模型…")
        self.btn_open = QPushButton("打开模型目录")
        btn_close = QPushButton("关闭")
        row.addWidget(self.btn_dl)
        row.addWidget(self.btn_import)
        row.addWidget(self.btn_open)
        row.addStretch(1)
        row.addWidget(btn_close)
        root.addLayout(row)

        self.btn_dl.clicked.connect(self._download)
        self.btn_import.clicked.connect(self._import)
        self.btn_open.clicked.connect(lambda: self._open_dir(MODELS_DIR))
        btn_close.clicked.connect(self.accept)

    def _open_dir(self, path: Path) -> None:
        import os

        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))  # noqa: S606

    def refresh(self) -> None:
        self.table.setRowCount(0)
        for spec in MODEL_SPECS.values():
            r = self.table.rowCount()
            self.table.insertRow(r)
            ok = installed(spec)
            size = dir_size(spec.path)
            values = [
                spec.label,
                {"ja": "日语", "en": "英语", "zh": "中文"}.get(spec.lang, spec.lang),
                f"{spec.size_gb:.1f}GB",
                f"已安装 {human_size(size)}" if ok else "未安装",
                spec.note,
            ]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c == 3:
                    item.setForeground(Qt.GlobalColor.green if ok else Qt.GlobalColor.gray)
                self.table.setItem(r, c, item)
        self.table.selectRow(0)

    def _selected(self) -> ModelSpec | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return list(MODEL_SPECS.values())[row]

    def _download(self) -> None:
        spec = self._selected()
        if not spec:
            return
        if installed(spec):
            QMessageBox.information(self, "提示", "该模型已安装")
            return
        self._start(spec)

    def _import(self) -> None:
        spec = self._selected()
        if not spec:
            QMessageBox.information(self, "提示", "请先选择一个模型槽位")
            return
        src = QFileDialog.getExistingDirectory(self, "选择 CT2 模型文件夹")
        if src:
            self._start(spec, Path(src))

    def _start(self, spec: ModelSpec, src: Path | None = None) -> None:
        self.btn_dl.setEnabled(False)
        self.btn_import.setEnabled(False)
        self.bar.setValue(0)
        self._worker = _DownloadWorker(spec, src, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, pct: int, msg: str) -> None:
        self.bar.setValue(pct)
        self.bar.setFormat(f"{pct}%  {msg}")

    def _on_done(self, ok: bool, msg: str) -> None:
        self.btn_dl.setEnabled(True)
        self.btn_import.setEnabled(True)
        self.refresh()
        if ok:
            self.bar.setValue(100)
            self.bar.setFormat("下载完成")
        else:
            self.bar.setFormat("失败")
            QMessageBox.warning(self, "失败", msg)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "请稍候", "下载进行中，请等待完成后再关闭。")
            event.ignore()
            return
        super().closeEvent(event)
