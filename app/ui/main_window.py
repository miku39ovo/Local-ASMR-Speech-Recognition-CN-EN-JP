"""主窗口。"""
from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QScrollArea, QSpinBox, QSplitter, QTableView,
    QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from ..config import (
    AUDIO_EXTS, ENCODINGS, OUTPUT_DIR, PRESETS, Settings,
)
from ..core.audio import duration as probe_duration
from ..core.gpu import query_vram
from ..core.models import MODEL_SPECS, installed, model_key_for
from .model_dialog import ModelDialog
from .progress import ProgressBar, ProgressDelegate
from .table import LANG_LABEL, JobTableModel
from .worker import BatchWorker


def scan_paths(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                    found.append(f)
        elif p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            found.append(p)
    return found


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.model = JobTableModel()
        self.worker: BatchWorker | None = None
        self._current_dir: Path | None = None
        self._loading = True
        self._applying_preset = False
        self.setWindowTitle(
            f"ASMR2LRC  {__version__}  ·  本地音视频转文字 · 日语/英语/中文 · LRC / TXT / SRT"
        )
        self.resize(1240, 900)
        self._fit_to_screen()
        self.setAcceptDrops(True)
        self._build_ui()
        self._apply_settings_to_ui()
        self._loading = False
        self._start_telemetry()
        QTimer.singleShot(400, self._startup_check)

    # ================= 界面 =================
    def _fit_to_screen(self) -> None:
        """窗口别超出屏幕可用区域（小屏 / 高缩放时很常见）。"""
        screen = self.screen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        w = min(self.width(), max(860, avail.width() - 30))
        h = min(self.height(), max(520, avail.height() - 50))
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(9)

        root.addLayout(self._build_toolbar())

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 7):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(self._open_current_file)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.setItemDelegateForColumn(4, ProgressDelegate(self.table))
        lv.addWidget(self.table, 1)
        split.addWidget(left)

        split.addWidget(self._build_settings())
        split.setStretchFactor(0, 1)
        split.setSizes([820, 392])
        root.addWidget(split, 1)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setFixedHeight(118)
        self.log_view.setPlaceholderText("运行日志…")
        root.addWidget(self.log_view)

        sb = self.statusBar()
        self.status_msg = QLabel("就绪")
        self.tps_label = QLabel("")
        self.tps_label.setObjectName("tps")
        self.tps_label.setMinimumWidth(168)
        self.tps_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.gpu_label = QLabel("显存查询中…")
        self.gpu_label.setObjectName("hint")
        self.overall_bar = ProgressBar()
        self.overall_bar.setFixedWidth(240)
        self.overall_bar.setValue(0)
        sb.addWidget(self.status_msg, 1)
        sb.addPermanentWidget(self.overall_bar)
        sb.addPermanentWidget(self.tps_label)
        sb.addPermanentWidget(self.gpu_label)
        pad = QWidget()
        pad.setFixedWidth(8)
        sb.addPermanentWidget(pad)

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(7)

        def btn(text, slot, name=""):
            b = QPushButton(text)
            if name:
                b.setObjectName(name)
            b.clicked.connect(slot)
            bar.addWidget(b)
            return b

        self.btn_add = btn("添加文件", self._add_files)
        self.btn_add_dir = btn("添加文件夹", self._add_folder)
        self.btn_remove = btn("移除选中", self._remove_selected)
        self.btn_clear = btn("清空", self._clear_all)
        bar.addSpacing(10)
        self.btn_start = btn("开始识别", self._start, "primary")
        self.btn_pause = btn("暂停", self._toggle_pause)
        self.btn_pause.setEnabled(False)
        self.btn_stop = btn("停止", self._stop, "danger")
        self.btn_stop.setEnabled(False)
        bar.addSpacing(10)
        self.btn_retry = btn("重试失败", self._retry_failed)
        self.btn_out = btn("打开输出目录", self._open_output)
        self.btn_model = btn("模型管理", self._open_models)
        bar.addStretch(1)
        self.banner = QLabel("")
        self.banner.setObjectName("banner")
        self.banner.setVisible(False)
        bar.addWidget(self.banner)
        return bar

    def _build_settings(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(392)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 6, 0)
        layout.setSpacing(4)

        # --- 识别 ---
        g1 = QGroupBox("识别")
        f1 = QFormLayout(g1)
        f1.setLabelAlignment(Qt.AlignLeft)
        f1.setSpacing(7)

        self.cb_lang = QComboBox()
        for label, data in (("日语", "ja"), ("英语", "en"), ("中文", "zh"), ("自动检测", "auto")):
            self.cb_lang.addItem(label, data)
        self.cb_lang.currentIndexChanged.connect(self._lang_changed)
        f1.addRow("默认语言", self.cb_lang)

        self.cb_ja_model = QComboBox()
        for spec in MODEL_SPECS.values():
            if spec.lang == "ja":
                self.cb_ja_model.addItem(spec.label, spec.key)
        f1.addRow("日语模型", self.cb_ja_model)

        self.cb_en_model = QComboBox()
        for spec in MODEL_SPECS.values():
            if spec.lang == "en":
                self.cb_en_model.addItem(spec.label, spec.key)
        f1.addRow("英语模型", self.cb_en_model)

        self.cb_zh_model = QComboBox()
        for spec in MODEL_SPECS.values():
            if spec.lang == "zh":
                self.cb_zh_model.addItem(spec.label, spec.key)
        self.cb_zh_model.setToolTip(
            "标点版：中文断句和标点更自然，约占 2.9GB 显存\n"
            "turbo 版：速度快约 3 倍、显存减半，标点稍差"
        )
        f1.addRow("中文模型", self.cb_zh_model)

        self.cb_preset = QComboBox()
        for key, p in PRESETS.items():
            self.cb_preset.addItem(p["label"], key)
        self.cb_preset.currentIndexChanged.connect(self._preset_changed)
        f1.addRow("参数预设", self.cb_preset)

        self.chk_vad = QCheckBox("启用 VAD 静音过滤")
        f1.addRow("", self.chk_vad)

        self.sp_vad = QDoubleSpinBox()
        self.sp_vad.setRange(0.05, 0.9)
        self.sp_vad.setSingleStep(0.05)
        self.sp_vad.setDecimals(2)
        f1.addRow("VAD 阈值", self.sp_vad)

        self.sp_beam = QSpinBox()
        self.sp_beam.setRange(1, 10)
        f1.addRow("beam size", self.sp_beam)

        # --- 断句与时间轴 ---
        g2 = QGroupBox("断句与时间轴")
        f2 = QFormLayout(g2)
        f2.setSpacing(7)
        self.sp_chars = QSpinBox()
        self.sp_chars.setRange(8, 80)
        f2.addRow("每行最多字数", self.sp_chars)

        self.sp_line_sec = QDoubleSpinBox()
        self.sp_line_sec.setRange(2.0, 30.0)
        self.sp_line_sec.setSingleStep(0.5)
        f2.addRow("单行最长秒数", self.sp_line_sec)

        self.sp_merge = QDoubleSpinBox()
        self.sp_merge.setRange(0.0, 2.0)
        self.sp_merge.setSingleStep(0.1)
        f2.addRow("合并间隔（秒）", self.sp_merge)

        self.sp_pre = QDoubleSpinBox()
        self.sp_pre.setRange(0.0, 1.5)
        self.sp_pre.setSingleStep(0.05)
        f2.addRow("时间提前（秒）", self.sp_pre)

        self.sp_offset = QDoubleSpinBox()
        self.sp_offset.setRange(-10.0, 10.0)
        self.sp_offset.setSingleStep(0.1)
        f2.addRow("整体偏移（秒）", self.sp_offset)

        self.chk_blank = QCheckBox("长静音插入空行")
        f2.addRow("", self.chk_blank)

        # --- 输出 ---
        g3 = QGroupBox("输出")
        v3 = QVBoxLayout(g3)
        v3.setSpacing(7)

        fmt_row = QHBoxLayout()
        self.chk_lrc = QCheckBox("LRC")
        self.chk_txt = QCheckBox("TXT")
        self.chk_srt = QCheckBox("SRT")
        for c in (self.chk_lrc, self.chk_txt, self.chk_srt):
            fmt_row.addWidget(c)
        fmt_row.addStretch(1)
        v3.addLayout(fmt_row)

        self.rb_same = QRadioButton("保存到音频同目录")
        self.rb_custom = QRadioButton("统一输出到指定目录")
        self.rb_same.toggled.connect(self._output_mode_changed)
        v3.addWidget(self.rb_same)
        v3.addWidget(self.rb_custom)

        dir_row = QHBoxLayout()
        self.ed_out = QLineEdit()
        self.ed_out.setPlaceholderText(str(OUTPUT_DIR))
        self.btn_browse = QPushButton("…")
        self.btn_browse.setFixedWidth(34)
        self.btn_browse.clicked.connect(self._pick_output)
        dir_row.addWidget(self.ed_out, 1)
        dir_row.addWidget(self.btn_browse)
        v3.addLayout(dir_row)

        self.chk_struct = QCheckBox("保持子目录结构")
        v3.addWidget(self.chk_struct)

        f3 = QFormLayout()
        self.cb_enc = QComboBox()
        self.cb_enc.addItems(ENCODINGS)
        f3.addRow("编码", self.cb_enc)

        self.cb_overwrite = QComboBox()
        for label, data in (("跳过已有文件", "skip"), ("覆盖", "overwrite"), ("自动重命名", "rename")):
            self.cb_overwrite.addItem(label, data)
        f3.addRow("同名文件", self.cb_overwrite)

        self.chk_hour = QCheckBox("超过 1 小时用 hh:mm:ss")
        f3.addRow("", self.chk_hour)
        v3.addLayout(f3)

        # --- 性能 ---
        g4 = QGroupBox("性能与显存")
        f4 = QFormLayout(g4)
        self.cb_compute = QComboBox()
        for label, data in (
            ("自动（按可用显存）", "auto"),
            ("float16（质量优先）", "float16"),
            ("int8 低显存（约省一半）", "int8_float16"),
        ):
            self.cb_compute.addItem(label, data)
        f4.addRow("精度", self.cb_compute)
        hint = QLabel("同时只加载一个模型；切换语言会先释放显存。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f4.addRow(hint)

        tabs = QTabWidget()
        for page, title in ((g1, "识别"), (g2, "断句"), (g3, "输出")):
            wrap = QWidget()
            lw = QVBoxLayout(wrap)
            lw.setContentsMargins(2, 4, 2, 2)
            lw.addWidget(page)
            lw.addStretch(1)
            tabs.addTab(wrap, title)

        perf = QWidget()
        lp = QVBoxLayout(perf)
        lp.setContentsMargins(2, 4, 2, 2)
        lp.addWidget(g4)
        lp.addStretch(1)
        tabs.addTab(perf, "性能")

        layout.addWidget(tabs, 1)

        scroll.setWidget(panel)

        for form in panel.findChildren(QFormLayout):
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for cls in (QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit):
            for w in panel.findChildren(cls):
                w.setMinimumWidth(80)
        for cb in panel.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(8)
        return scroll

    # ================= 设置读写 =================
    def _apply_settings_to_ui(self) -> None:
        s = self.settings
        self._set_combo_data(self.cb_lang, s.language)
        self._set_combo_data(self.cb_ja_model, s.ja_model)
        self._set_combo_data(self.cb_en_model, s.en_model)
        self._set_combo_data(self.cb_zh_model, s.zh_model)
        self._set_combo_data(self.cb_preset, s.preset)
        self.chk_vad.setChecked(s.vad)
        self.sp_vad.setValue(s.vad_threshold)
        self.sp_beam.setValue(s.beam_size)
        self.sp_chars.setValue(s.max_chars)
        self.sp_line_sec.setValue(s.max_line_sec)
        self.sp_merge.setValue(s.merge_gap)
        self.sp_pre.setValue(s.pre_roll)
        self.sp_offset.setValue(s.offset)
        self.chk_blank.setChecked(s.blank_on_silence)
        self.chk_lrc.setChecked("lrc" in s.formats)
        self.chk_txt.setChecked("txt" in s.formats)
        self.chk_srt.setChecked("srt" in s.formats)
        self.rb_same.setChecked(s.output_mode != "custom")
        self.rb_custom.setChecked(s.output_mode == "custom")
        self.ed_out.setText(s.output_dir)
        self.chk_struct.setChecked(s.keep_structure)
        self.cb_enc.setCurrentText(s.encoding)
        self._set_combo_data(self.cb_overwrite, s.overwrite)
        self.chk_hour.setChecked(s.hour_timestamp)
        self._set_combo_data(self.cb_compute, s.compute_mode)
        self._output_mode_changed()

    @staticmethod
    def _set_combo_data(cb: QComboBox, data) -> None:
        idx = cb.findData(data)
        if idx >= 0:
            cb.setCurrentIndex(idx)

    def _collect(self) -> Settings:
        s = self.settings
        s.language = self.cb_lang.currentData()
        s.ja_model = self.cb_ja_model.currentData()
        s.en_model = self.cb_en_model.currentData()
        s.zh_model = self.cb_zh_model.currentData()
        s.preset = self.cb_preset.currentData()
        s.vad = self.chk_vad.isChecked()
        s.vad_threshold = self.sp_vad.value()
        s.beam_size = self.sp_beam.value()
        s.max_chars = self.sp_chars.value()
        s.max_line_sec = self.sp_line_sec.value()
        s.merge_gap = self.sp_merge.value()
        s.pre_roll = self.sp_pre.value()
        s.offset = self.sp_offset.value()
        s.blank_on_silence = self.chk_blank.isChecked()
        fmts = []
        if self.chk_lrc.isChecked():
            fmts.append("lrc")
        if self.chk_txt.isChecked():
            fmts.append("txt")
        if self.chk_srt.isChecked():
            fmts.append("srt")
        s.formats = fmts
        s.output_mode = "custom" if self.rb_custom.isChecked() else "same"
        s.output_dir = self.ed_out.text().strip()
        s.keep_structure = self.chk_struct.isChecked()
        s.encoding = self.cb_enc.currentText()
        s.overwrite = self.cb_overwrite.currentData()
        s.hour_timestamp = self.chk_hour.isChecked()
        s.compute_mode = self.cb_compute.currentData()
        return s

    def _lang_changed(self) -> None:
        if self._loading or self._applying_preset:
            return
        data = self.cb_lang.currentData()
        preset_map = {"ja": "ja_whisper", "en": "en_soft", "zh": "zh_soft"}
        key = preset_map.get(data)
        if not key:
            return
        self._loading = True
        self._set_combo_data(self.cb_preset, key)
        self._loading = False
        self._preset_changed()

    def _preset_changed(self) -> None:
        if self._loading:
            return
        key = self.cb_preset.currentData()
        if not key or key == "custom":
            return
        s = Settings(**vars(self.settings))
        s.apply_preset(key)
        self._applying_preset = True
        self._apply_settings_to_ui_values_only(s)
        self._applying_preset = False

    def _apply_settings_to_ui_values_only(self, s: Settings) -> None:
        self._set_combo_data(self.cb_lang, s.language)
        self.chk_vad.setChecked(s.vad)
        self.sp_vad.setValue(s.vad_threshold)
        self.sp_beam.setValue(s.beam_size)
        self.sp_chars.setValue(s.max_chars)
        self.sp_line_sec.setValue(s.max_line_sec)
        self.sp_merge.setValue(s.merge_gap)
        self.sp_pre.setValue(s.pre_roll)

    def _output_mode_changed(self) -> None:
        custom = self.rb_custom.isChecked()
        for w in (self.ed_out, self.btn_browse, self.chk_struct):
            w.setEnabled(custom)

    def _pick_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.ed_out.text() or str(OUTPUT_DIR))
        if d:
            self.ed_out.setText(d)

    # ================= 文件操作 =================
    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择音频/视频",
            str(self._current_dir or Path.home()),
            "音视频 (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.wma *.mp4 *.mkv *.mov *.avi *.webm);;所有文件 (*.*)",
        )
        if files:
            self._current_dir = Path(files[0]).parent
            self._append([Path(f) for f in files])

    def _add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择文件夹", str(self._current_dir or Path.home()))
        if d:
            self._current_dir = Path(d)
            self._append(scan_paths([Path(d)]), root=Path(d))

    def _append(self, paths: list[Path], root: Path | None = None) -> None:
        start = len(self.model.jobs)
        n = self.model.add_paths(paths)
        if n:
            for i in range(start, len(self.model.jobs)):
                job = self.model.jobs[i]
                job.duration = probe_duration(job.path)
                if root:
                    job.root = root
                self.model.refresh_row(i)
        self._log(f"添加 {n} 个文件，队列共 {len(self.model.jobs)} 个")

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()}, reverse=True)
        self.model.remove_rows(rows)

    def _clear_all(self) -> None:
        if not self.model.jobs:
            return
        if QMessageBox.question(self, "清空队列", "确定清空所有文件？") == QMessageBox.Yes:
            self.model.clear()

    def _open_current_file(self) -> None:
        job = self.model.job(self.table.currentIndex().row())
        if job:
            self._reveal(job.path)

    @staticmethod
    def _reveal(path: Path) -> None:
        if path.exists():
            os.system(f'explorer /select,"{path}"')  # noqa: S605

    def _table_menu(self, pos) -> None:
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        job = self.model.job(idx.row())
        if not job:
            return
        menu = QMenu(self)
        lang_menu = menu.addMenu("语言")
        for label, data in (("跟随全局", None), ("日语", "ja"), ("英语", "en"),
                            ("中文", "zh"), ("自动检测", "auto")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(job.language == data)
            act.triggered.connect(lambda _=False, d=data, j=job: self._set_job_lang(j, d))
            lang_menu.addAction(act)
        menu.addSeparator()
        menu.addAction("在资源管理器中显示", lambda: self._reveal(job.path))
        menu.addAction("重试此项", lambda: self._retry_rows([idx.row()]))
        menu.addAction("移除", lambda: self.model.remove_rows([idx.row()]))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _set_job_lang(self, job, lang) -> None:
        job.language = lang
        for i, j in enumerate(self.model.jobs):
            if j is job:
                self.model.refresh_row(i)
                break

    # ================= 队列控制 =================
    def _pending_rows(self, retry: bool = False) -> list[tuple[int, object]]:
        rows = []
        for i, job in enumerate(self.model.jobs):
            if job.status in ("pending",) or (retry and job.status in ("failed", "cancelled", "skipped")):
                rows.append((i, job))
        # 按语言分组，减少模型反复加载
        order = {"ja": 0, "en": 1, "zh": 2, "auto": 3, None: 4}
        default = self.cb_lang.currentData() or "ja"
        rows.sort(key=lambda it: order.get(it[1].language or default, 3))
        return rows

    def _start(self) -> None:
        s = self._collect()
        if not s.formats:
            QMessageBox.warning(self, "缺少输出格式", "请至少勾选一种输出格式（LRC / TXT / SRT）。")
            return
        if s.output_mode == "custom" and not s.output_dir:
            QMessageBox.warning(self, "缺少输出目录", "请选择统一的输出目录。")
            return
        rows = self._pending_rows()
        if not rows:
            QMessageBox.information(self, "没有任务", "请先添加文件，或所有文件已处理完成。")
            return
        missing = self._missing_models(rows)
        if missing:
            QMessageBox.warning(
                self, "模型未就绪",
                "以下模型尚未下载：\n\n" + "\n".join(missing) + "\n\n请在「模型管理」中下载后再开始。",
            )
            self._open_models()
            return

        s.save()
        self.log_view.clear()
        for b in (self.btn_start, self.btn_add, self.btn_add_dir, self.btn_remove,
                  self.btn_clear, self.btn_retry, self.btn_model):
            b.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("暂停")
        self.btn_stop.setEnabled(True)
        self.overall_bar.setValue(0)
        self.tps_label.setText("")
        self._done_count = 0
        self._total = len(rows)
        self._log(f"开始处理 {len(rows)} 个文件")

        self.worker = BatchWorker(rows, s, self)
        self.worker.job_started.connect(self._on_started)
        self.worker.job_progress.connect(self._on_progress)
        self.worker.job_done.connect(self._on_done)
        self.worker.message.connect(self._log)
        self.worker.all_done.connect(self._on_all_done)
        self.worker.start()

    def _missing_models(self, rows) -> list[str]:
        keys = set()
        default = self.cb_lang.currentData() or "ja"
        for _, job in rows:
            lang = job.language or default
            keys.add(model_key_for(self.settings, lang))
        missing = []
        for spec_key in keys:
            spec = MODEL_SPECS.get(spec_key)
            if spec and not installed(spec):
                missing.append(f"· {spec.label}（{spec_key}）")
        return missing

    def _toggle_pause(self) -> None:
        if not self.worker:
            return
        if self.btn_pause.text() == "暂停":
            self.worker.pause()
            self.btn_pause.setText("继续")
            self.status_msg.setText("已暂停")
        else:
            self.worker.resume()
            self.btn_pause.setText("暂停")
            self.status_msg.setText("识别中…")

    def _stop(self) -> None:
        if self.worker:
            self.worker.stop()
            self.status_msg.setText("正在停止…")

    def _retry_failed(self) -> None:
        rows = [(i, j) for i, j in enumerate(self.model.jobs) if j.status in ("failed", "cancelled")]
        if not rows:
            QMessageBox.information(self, "提示", "没有失败的任务。")
            return
        for i, j in rows:
            j.status = "pending"
            j.progress = 0
            j.message = ""
            self.model.refresh_row(i)
        self._start()

    def _retry_rows(self, rows: list[int]) -> None:
        for r in rows:
            j = self.model.job(r)
            if j:
                j.status = "pending"
                j.progress = 0
                j.message = ""
                self.model.refresh_row(r)
        self._start()

    def _on_started(self, idx: int) -> None:
        self.model.refresh_row(idx)
        job = self.model.job(idx)
        if job:
            self.status_msg.setText(f"识别中：{job.path.name}")

    def _on_progress(self, idx: int, pct: int, msg: str) -> None:
        job = self.model.job(idx)
        if not job:
            return
        job.progress = pct
        job.message = msg
        self.model.refresh_row(idx)
        total = getattr(self, "_total", 1) or 1
        done = getattr(self, "_done_count", 0)
        self.overall_bar.setValue(int((done + pct / 100) / total * 100))

    def _on_done(self, idx: int, status: str, msg: str) -> None:
        if status != "cancelled":
            self._done_count = getattr(self, "_done_count", 0) + 1
        total = getattr(self, "_total", 1) or 1
        self.overall_bar.setValue(int(self._done_count / total * 100))
        job = self.model.job(idx)
        if job and msg:
            # 进度回调是排队来的，可能晚于最终结果覆盖 message，这里回填最终信息
            job.message = msg
        self.model.refresh_row(idx)
        name = job.path.name if job else str(idx)
        icon = {"done": "✓", "skipped": "⏭", "failed": "✖", "cancelled": "■"}.get(status, "·")
        self._log(f"{icon} {name}  {msg}")

    def _on_all_done(self) -> None:
        for b in (self.btn_start, self.btn_add, self.btn_add_dir, self.btn_remove,
                  self.btn_clear, self.btn_retry, self.btn_model):
            b.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setText("暂停")
        self.status_msg.setText("全部完成")
        done = sum(1 for j in self.model.jobs if j.status == "done")
        failed = sum(1 for j in self.model.jobs if j.status == "failed")
        skipped = sum(1 for j in self.model.jobs if j.status == "skipped")
        pending = sum(1 for j in self.model.jobs if j.status in ("pending", "running"))
        if pending == 0:
            self.overall_bar.setValue(100)
        self._log(f"队列结束：成功 {done}，失败 {failed}，跳过 {skipped}")
        self.worker = None
        self._update_tps()

    # ================= 其它 =================
    def _open_output(self) -> None:
        s = self._collect()
        target = Path(s.output_dir) if s.output_mode == "custom" and s.output_dir else OUTPUT_DIR
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(str(target))  # noqa: S606

    def _open_models(self) -> None:
        dlg = ModelDialog(self)
        dlg.exec()
        self._startup_check()

    def _startup_check(self) -> None:
        keys = [self.settings.ja_model, self.settings.en_model]
        if self.settings.language == "zh":
            keys.append(self.settings.zh_model)  # 不用中文就不催下 2.9GB
        missing = []
        for key in keys:
            spec = MODEL_SPECS.get(key)
            if spec and not installed(spec):
                missing.append(spec.label)
        if missing:
            self.banner.setText("缺少模型：" + "、".join(missing) + "   → 点「模型管理」下载")
            self.banner.setVisible(True)
            self._log("检测到模型未安装：" + "、".join(missing))
        else:
            self.banner.setVisible(False)

    def _start_telemetry(self) -> None:
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.timeout.connect(self._update_telemetry)
        self._telemetry_timer.start(700)
        self._update_telemetry()

    def _update_telemetry(self) -> None:
        info = query_vram()
        if not info.available:
            self.gpu_label.setText("GPU 不可用")
        else:
            parts = [f"显存 {info.used_mb}/{info.total_mb} MB"]
            if info.util_pct >= 0:
                parts.append(f"GPU {info.util_pct}%")
            if info.power_w > 0:
                parts.append(f"{info.power_w:.0f} W")
            if info.temp_c >= 0:
                parts.append(f"{info.temp_c} ℃")
            self.gpu_label.setText("  ·  ".join(parts))

            # 显存告急或温度过高时整行标红；70℃ 以上转橙，提示持续高负载
            hot = info.temp_c >= 70
            if info.free_mb < 1200 or info.temp_c >= 80:
                color = "#ff8080"
            elif hot:
                color = "#f0b64a"
            else:
                color = "#8b94a5"
            self.gpu_label.setStyleSheet(f"color:{color};")
            if info.temp_c >= 0:
                tip = f"GPU 核心温度 {info.temp_c} ℃"
                if info.temp_slowdown_c > 0:
                    tip += f"（降频阈值 {info.temp_slowdown_c} ℃）"
                self.gpu_label.setToolTip(tip)
        self._update_tps()

    def _update_tps(self) -> None:
        worker = self.worker
        metrics = getattr(getattr(worker, "engine", None), "metrics", None) if worker else None
        running = bool(worker and worker.isRunning())
        if not running or metrics is None:
            self.tps_label.setText("")
            self.tps_label.setStyleSheet("color:#5b6373;")
            return
        if metrics.tokens <= 0:
            self.tps_label.setText("解码中…")
            self.tps_label.setStyleSheet("color:#7f8a9c;")
            return
        if metrics.tps <= 0:
            self.tps_label.setText(f"—  ·  {metrics.tokens} tok")
        else:
            self.tps_label.setText(f"{metrics.tps:.1f} tok/s · {metrics.tokens} tok")
        self.tps_label.setStyleSheet("color:#8ad7ff; font-family:'Cascadia Mono','Consolas',monospace;")

    def _log(self, text: str) -> None:
        if not text:
            return
        self.log_view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {text}")

    # ---- 拖拽 ----
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            files = scan_paths(paths)
            root = next((p for p in paths if p.is_dir()), None)
            self._append(files, root=root)
            event.acceptProposedAction()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, "退出", "正在识别，确定退出？") != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.stop()
            self.worker.wait(3000)
        try:
            self._collect().save()
        except Exception:
            pass
        super().closeEvent(event)
