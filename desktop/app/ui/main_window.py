from __future__ import annotations

import csv
import os
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np
from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..extractor import ExtractOptions
from ..license_client import LicenseError, LicenseSession
from ..output import OutputOptions
from ..pipeline import MODE_AUTO, MODE_GEMINI, MODE_LOCAL, JobOptions, Processor

COL_NAME, COL_STATUS, COL_METHOD, COL_CONF, COL_NOTE = range(5)


@dataclass
class Item:
    src: str
    rel: str  # 相对导入根目录的路径（不含扩展名），决定输出文件名
    status: str = "待处理"
    output: str = ""


def _checker(w: int, h: int) -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    size = 12
    for y in range(0, h, size):
        for x in range(0, w, size):
            if (x // size + y // size) % 2:
                p.fillRect(x, y, size, size, QColor("#e6e6e2"))
    p.end()
    return pm


def _load_pixmap(path: str, max_side: int = 520) -> QPixmap | None:
    data = np.fromfile(path, np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    h, w = img.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
    qimg = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0], QImage.Format_RGBA8888).copy()
    art = QPixmap.fromImage(qimg)
    canvas = _checker(art.width(), art.height())
    p = QPainter(canvas)
    p.drawPixmap(0, 0, art)
    p.end()
    return canvas


class Worker(QThread):
    item_done = Signal(int, object)  # row, result or exception
    item_started = Signal(int)
    license_lost = Signal(str)

    def __init__(self, processor: Processor, jobs: list[tuple[int, str, str]], opts: JobOptions):
        super().__init__()
        self.processor = processor
        self.jobs = jobs
        self.opts = opts
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        for row, src, dst in self.jobs:
            if self._stop.is_set():
                break
            self.item_started.emit(row)
            try:
                result = self.processor.process(src, dst, self.opts)
                self.item_done.emit(row, result)
            except LicenseError as exc:
                self.item_done.emit(row, exc)
                self.license_lost.emit(exc.message)
                break
            except Exception as exc:
                self.item_done.emit(row, exc)


class MainWindow(QMainWindow):
    logout_requested = Signal(str)
    heartbeat_failed = Signal(str)

    def __init__(self, session: LicenseSession):
        super().__init__()
        self.session = session
        self.processor = Processor(session)
        self.items: list[Item] = []
        self.worker: Worker | None = None
        self.settings = QSettings("TemuPrintExtractor", "Desktop")
        self._closing_for_logout = False

        self.setWindowTitle(f"{config.APP_NAME} v{config.APP_VERSION}")
        self.resize(1360, 860)
        self.setAcceptDrops(True)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        self.setCentralWidget(central)

        self.notice = QLabel(objectName="Notice", wordWrap=True)
        self.notice.hide()
        root.addWidget(self.notice)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_settings())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_preview())
        splitter.setSizes([400, 560, 400])
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        self.license_label = QLabel()
        self.model_label = QLabel(objectName="Muted")
        self.statusBar().addWidget(self.license_label)
        self.statusBar().addPermanentWidget(self.model_label)

        self.heartbeat_failed.connect(self._force_logout)
        self.timer = QTimer(self, interval=max(30, session.heartbeat_seconds) * 1000)
        self.timer.timeout.connect(self._heartbeat)
        self.timer.start()
        self.clock = QTimer(self, interval=30_000)
        self.clock.timeout.connect(self._refresh_license_info)
        self.clock.start()
        self._refresh_license_info()
        self._restore_settings()
        QTimer.singleShot(200, lambda: self.model_label.setText(self.processor.model_status))

    # ---------- 布局 ----------

    def _build_settings(self) -> QWidget:
        panel = QFrame(objectName="Panel")
        panel.setMinimumWidth(380)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        layout.addWidget(QLabel("抠图设置", objectName="Title"))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.mode = QComboBox()
        self.mode.addItem("本地 U2-Net（免费、离线）", MODE_LOCAL)
        self.mode.addItem("Google AI 线上（适合不清晰图）", MODE_GEMINI)
        self.mode.addItem("智能（本地优先，不清晰自动用 AI）", MODE_AUTO)
        form.addRow("抠图方式", self.mode)

        self.shirt = QComboBox()
        self.shirt.addItem("自动识别", "auto")
        self.shirt.addItem("黑色 T 恤", "black")
        self.shirt.addItem("白色 T 恤", "white")
        form.addRow("衣服颜色", self.shirt)
        layout.addLayout(form)

        self.sensitivity, s_row = self._slider("灵敏度", 0, 100, 50, "越高越能抠出淡色细节，过高会带入褶皱")
        layout.addLayout(s_row)
        self.feather, f_row = self._slider("边缘柔化", 0, 5, 2, "数值越大边缘越柔和")
        layout.addLayout(f_row)

        self.enclosed = QCheckBox("只提取衣服上的区域")
        self.enclosed.setToolTip("排除皮肤、头发、背景等衣服外的内容")
        self.enclosed.setChecked(True)
        self.remove_small = QCheckBox("去除领标、吊牌等小杂块")
        self.remove_small.setChecked(True)
        self.verify_ai = QCheckBox("AI 结果与原图对比校验（防货不对板）")
        self.verify_ai.setChecked(True)
        self.knockout = QCheckBox("斑驳做旧印花：镂空露出的布料（Google AI）")
        self.knockout.setToolTip("只在做旧/裂纹印花时勾选。普通照片类印花（如老虎）不要勾，否则深色部分会被挖空")
        self.knockout.setChecked(False)
        for cb in (self.enclosed, self.remove_small, self.verify_ai, self.knockout):
            layout.addWidget(cb)

        fallback_row = QHBoxLayout()
        fallback_row.setSpacing(6)
        self.auto_fallback = QCheckBox("可信度低于")
        self.auto_fallback.setChecked(True)
        self.auto_threshold = self._spin(10, 100, 80)
        self.auto_threshold.setSuffix(" %")
        self.auto_threshold.setFixedWidth(90)
        self.auto_fallback.toggled.connect(self.auto_threshold.setEnabled)
        fallback_row.addWidget(self.auto_fallback)
        fallback_row.addWidget(self.auto_threshold)
        fallback_row.addWidget(QLabel("时自动改用 Google AI"))
        fallback_row.addStretch()
        layout.addLayout(fallback_row)
        layout.addWidget(
            QLabel("本地结果不可靠时自动交给 Google AI 重抠，需要先填写 API Key。", objectName="Muted", wordWrap=True)
        )

        if getattr(self.session, "is_local", False):
            layout.addWidget(QLabel("Google AI", objectName="Section"))
            self.api_key = QLineEdit(placeholderText="粘贴 Google AI Studio 的 API Key")
            self.api_key.setEchoMode(QLineEdit.Password)
            self.api_key.setText(self.session.api_key)
            layout.addWidget(self.api_key)
            key_row = QHBoxLayout()
            save_key = QPushButton("保存并启用")
            save_key.clicked.connect(self._save_api_key)
            show_key = QCheckBox("显示")
            show_key.toggled.connect(
                lambda on: self.api_key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
            )
            key_row.addWidget(save_key)
            key_row.addWidget(show_key)
            key_row.addStretch()
            layout.addLayout(key_row)
            layout.addWidget(
                QLabel("Key 只保存在本机。没有 Key 时只能用本地模式。", objectName="Muted", wordWrap=True)
            )

        layout.addWidget(QLabel("导出设置", objectName="Section"))
        form2 = QFormLayout()
        self.size_mode = QComboBox()
        self.size_mode.addItem("原始大小（裁掉留白）", "crop")
        self.size_mode.addItem("长边放大到指定像素", "long")
        self.size_mode.addItem("放入固定印刷画布", "canvas")
        self.size_mode.currentIndexChanged.connect(self._toggle_size_inputs)
        form2.addRow("尺寸", self.size_mode)
        self.long_side = self._spin(500, 12000, 4500)
        form2.addRow("长边像素", self.long_side)
        self.canvas_w = self._spin(500, 12000, 4500)
        self.canvas_h = self._spin(500, 12000, 5400)
        canvas_row = QHBoxLayout()
        canvas_row.addWidget(self.canvas_w)
        canvas_row.addWidget(QLabel("×"))
        canvas_row.addWidget(self.canvas_h)
        form2.addRow("画布宽×高", canvas_row)
        self.align = QComboBox()
        self.align.addItem("居中", "center")
        self.align.addItem("顶部居中", "top")
        form2.addRow("画布位置", self.align)
        self.padding = self._spin(0, 500, 20)
        form2.addRow("四周留白(px)", self.padding)
        self.dpi = self._spin(72, 1200, 300)
        form2.addRow("DPI", self.dpi)
        layout.addLayout(form2)

        layout.addWidget(QLabel("输出文件夹", objectName="Section"))
        out_row = QHBoxLayout()
        self.out_dir = QLineEdit(placeholderText="默认：原图所在文件夹/印花导出")
        browse = QPushButton("选择")
        browse.clicked.connect(self._choose_out_dir)
        out_row.addWidget(self.out_dir, 1)
        out_row.addWidget(browse)
        layout.addLayout(out_row)
        self.keep_tree = QCheckBox("保持子文件夹结构")
        self.keep_tree.setChecked(True)
        layout.addWidget(self.keep_tree)
        layout.addWidget(QLabel("导出文件名与导入图片同名，扩展名为 .png", objectName="Muted", wordWrap=True))
        layout.addStretch()
        for combo in body.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(10)
            combo.setMinimumHeight(34)
        for form_layout in (form, form2):
            form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form_layout.setVerticalSpacing(10)
            form_layout.setHorizontalSpacing(12)
        self._toggle_size_inputs()
        return panel

    def _slider(self, label: str, lo: int, hi: int, value: int, hint: str):
        box = QVBoxLayout()
        head = QHBoxLayout()
        head.addWidget(QLabel(label))
        val = QLabel(str(value), objectName="Muted")
        head.addStretch()
        head.addWidget(val)
        slider = QSlider(Qt.Horizontal, minimum=lo, maximum=hi, value=value)
        slider.valueChanged.connect(lambda v: val.setText(str(v)))
        box.addLayout(head)
        box.addWidget(slider)
        box.addWidget(QLabel(hint, objectName="Muted", wordWrap=True))
        return slider, box

    def _spin(self, lo: int, hi: int, value: int) -> QSpinBox:
        s = QSpinBox(minimum=lo, maximum=hi, value=value)
        s.setButtonSymbols(QSpinBox.NoButtons)
        s.setMinimumHeight(34)
        return s

    def _build_center(self) -> QWidget:
        panel = QFrame(objectName="Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        add_files = QPushButton("导入图片")
        add_files.clicked.connect(self._add_files)
        add_dir = QPushButton("导入文件夹")
        add_dir.clicked.connect(self._add_folder)
        clear = QPushButton("清空列表")
        clear.clicked.connect(self._clear)
        open_out = QPushButton("打开导出文件夹")
        open_out.clicked.connect(self._open_out_dir)
        for b in (add_files, add_dir, clear, open_out):
            top.addWidget(b)
        top.addStretch()
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["文件名", "状态", "方式", "可信度", "说明"])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col in (COL_STATUS, COL_METHOD, COL_CONF):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_NOTE, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._update_preview)
        layout.addWidget(self.table, 1)

        self.empty_hint = QLabel("把商品主图或文件夹拖到这里，或点击上方“导入”", objectName="Muted", alignment=Qt.AlignCenter)
        layout.addWidget(self.empty_hint)

        bottom = QHBoxLayout()
        self.progress = QProgressBar(textVisible=False)
        self.progress_label = QLabel("0 / 0", objectName="Muted")
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.progress_label)
        self.retry_btn = QPushButton("重新处理选中")
        self.retry_btn.clicked.connect(lambda: self._start(selected_only=True))
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.start_btn = QPushButton("开始批量处理", objectName="Accent")
        self.start_btn.clicked.connect(lambda: self._start(selected_only=False))
        bottom.addWidget(self.retry_btn)
        bottom.addWidget(self.stop_btn)
        bottom.addWidget(self.start_btn)
        layout.addLayout(bottom)
        return panel

    def _build_preview(self) -> QWidget:
        panel = QFrame(objectName="Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("预览", objectName="Title"))
        layout.addWidget(QLabel("原图", objectName="Section"))
        self.preview_src = QLabel(alignment=Qt.AlignCenter, minimumHeight=260)
        layout.addWidget(self.preview_src, 1)
        layout.addWidget(QLabel("导出印花（透明底）", objectName="Section"))
        self.preview_out = QLabel("处理后显示", objectName="Muted", alignment=Qt.AlignCenter, minimumHeight=260)
        layout.addWidget(self.preview_out, 1)
        return panel

    # ---------- 文件导入 ----------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        for p in paths:
            if os.path.isdir(p):
                self._import_folder(p)
            else:
                self._import_files([p])

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择商品主图", self.settings.value("last_dir", ""), "图片 (*.jpg *.jpeg *.png *.webp *.bmp)"
        )
        if files:
            self.settings.setValue("last_dir", os.path.dirname(files[0]))
            self._import_files(files)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹", self.settings.value("last_dir", ""))
        if folder:
            self.settings.setValue("last_dir", folder)
            self._import_folder(folder)

    def _import_files(self, files: list[str]):
        self._append([(f, os.path.splitext(os.path.basename(f))[0]) for f in files])

    def _import_folder(self, folder: str):
        entries = []
        for dirpath, _, names in os.walk(folder):
            if os.path.basename(dirpath) == "印花导出":
                continue
            for n in sorted(names):
                if n.lower().endswith(config.SUPPORTED_EXTS):
                    full = os.path.join(dirpath, n)
                    rel = os.path.splitext(os.path.relpath(full, folder))[0]
                    entries.append((full, rel))
        self._append(entries)

    def _append(self, entries: list[tuple[str, str]]):
        existing = {os.path.normcase(os.path.abspath(i.src)) for i in self.items}
        for src, rel in entries:
            if not src.lower().endswith(config.SUPPORTED_EXTS):
                continue
            key = os.path.normcase(os.path.abspath(src))
            if key in existing:
                continue
            existing.add(key)
            self.items.append(Item(src=src, rel=rel))
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [rel + os.path.splitext(src)[1], "待处理", "", "", ""]
            for col, v in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(v))
        self._update_counts()

    def _clear(self):
        if self.worker and self.worker.isRunning():
            return
        self.items.clear()
        self.table.setRowCount(0)
        self.preview_src.clear()
        self.preview_out.setText("处理后显示")
        self._update_counts()

    # ---------- 处理 ----------

    def _job_options(self) -> JobOptions:
        return JobOptions(
            mode=self.mode.currentData(),
            verify_ai=self.verify_ai.isChecked(),
            auto_fallback=self.auto_fallback.isChecked(),
            auto_threshold=self.auto_threshold.value() / 100.0,
            extract=ExtractOptions(
                shirt_color=self.shirt.currentData(),
                sensitivity=self.sensitivity.value(),
                feather=self.feather.value(),
                enclosed_only=self.enclosed.isChecked(),
                remove_small=self.remove_small.isChecked(),
                knockout_fabric=self.knockout.isChecked(),
            ),
            output=OutputOptions(
                size_mode=self.size_mode.currentData(),
                long_side=self.long_side.value(),
                canvas_w=self.canvas_w.value(),
                canvas_h=self.canvas_h.value(),
                align=self.align.currentData(),
                padding=self.padding.value(),
                dpi=self.dpi.value(),
            ),
        )

    def _output_path(self, item: Item) -> str:
        base = self.out_dir.text().strip() or os.path.join(os.path.dirname(item.src) if not self.keep_tree.isChecked() or os.sep not in item.rel else self._import_root(item), "印花导出")
        rel = item.rel if self.keep_tree.isChecked() else os.path.basename(item.rel)
        return os.path.join(base, rel + ".png")

    @staticmethod
    def _import_root(item: Item) -> str:
        src_no_ext = os.path.splitext(os.path.abspath(item.src))[0]
        return src_no_ext[: len(src_no_ext) - len(item.rel)].rstrip("\\/") or os.path.dirname(item.src)

    def _start(self, selected_only: bool):
        if self.worker and self.worker.isRunning():
            return
        opts = self._job_options()
        if opts.mode == MODE_GEMINI and not self.session.gemini_enabled:
            tip = (
                "请先在左侧填写 Google API Key 并点“保存并启用”"
                if getattr(self.session, "is_local", False)
                else "当前卡密未开通 Google AI，请使用本地模式或联系管理员"
            )
            QMessageBox.warning(self, "提示", tip)
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()}) if selected_only else [
            r for r, it in enumerate(self.items) if it.status not in ("完成", "需复核")
        ]
        if not rows:
            QMessageBox.information(self, "提示", "没有需要处理的图片" if not selected_only else "请先在列表中选中图片")
            return

        jobs, seen = [], {}
        for r in rows:
            item = self.items[r]
            dst = self._output_path(item)
            key = os.path.normcase(os.path.abspath(dst))
            if key == os.path.normcase(os.path.abspath(item.src)):
                self._set_row(r, "失败", note="输出会覆盖原图，请换一个输出文件夹")
                continue
            if key in seen:
                self._set_row(r, "失败", note=f"与 {os.path.basename(self.items[seen[key]].src)} 重名，已跳过（导出名须与原图一致）")
                continue
            seen[key] = r
            jobs.append((r, item.src, dst))
        if not jobs:
            return

        self._save_settings()
        self._batch_total = len(jobs)
        self._batch_done = 0
        self._batch_start = time.time()
        self.progress.setMaximum(len(jobs))
        self.progress.setValue(0)
        self.worker = Worker(self.processor, jobs, opts)
        self.worker.item_started.connect(lambda r: self._set_row(r, "处理中…"))
        self.worker.item_done.connect(self._on_item_done)
        self.worker.license_lost.connect(self._force_logout)
        self.worker.finished.connect(self._on_batch_finished)
        self._set_running(True)
        self.worker.start()

    def _stop(self):
        if self.worker:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("正在停止…")

    def _on_item_done(self, row: int, result):
        self._batch_done += 1
        self.progress.setValue(self._batch_done)
        elapsed = time.time() - self._batch_start
        remain = elapsed / self._batch_done * (self._batch_total - self._batch_done)
        self.progress_label.setText(f"{self._batch_done} / {self._batch_total}  剩余约 {int(remain)} 秒")
        if isinstance(result, Exception):
            self._set_row(row, "失败", note=getattr(result, "message", None) or str(result))
            return
        item = self.items[row]
        item.output = result.output_path
        status = "需复核" if result.needs_review else "完成"
        self._set_row(row, status, result.method, f"{result.confidence:.0%}", result.message)
        if row in {i.row() for i in self.table.selectedIndexes()}:
            self._update_preview()

    def _on_batch_finished(self):
        self._set_running(False)
        self.stop_btn.setText("停止")
        self._write_report()
        failed = sum(1 for i in self.items if i.status == "失败")
        review = sum(1 for i in self.items if i.status == "需复核")
        if self._batch_done:
            msg = f"处理完成：{self._batch_done} 张"
            if review:
                msg += f"，其中 {review} 张需人工复核"
            if failed:
                msg += f"，{failed} 张失败"
            self.statusBar().showMessage(msg, 15000)

    def _write_report(self):
        outputs = {os.path.dirname(i.output) for i in self.items if i.output}
        if not outputs:
            return
        root = os.path.commonpath(list(outputs))
        try:
            with open(os.path.join(root, "处理报告.csv"), "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["原图", "导出文件", "状态", "方式", "可信度", "说明"])
                for r, it in enumerate(self.items):
                    w.writerow([it.src, it.output, it.status] + [self.table.item(r, c).text() for c in (COL_METHOD, COL_CONF, COL_NOTE)])
        except OSError:
            pass

    def _set_row(self, row: int, status: str, method: str = "", conf: str = "", note: str = ""):
        self.items[row].status = status
        colors = {"完成": "#1f7a3a", "需复核": "#b45309", "失败": "#c0261c", "处理中…": "#e8590c"}
        for col, val in ((COL_STATUS, status), (COL_METHOD, method), (COL_CONF, conf), (COL_NOTE, note)):
            cell = self.table.item(row, col)
            cell.setText(val)
            if col == COL_STATUS:
                cell.setForeground(QColor(colors.get(status, "#1c1c1c")))
            if col == COL_NOTE:
                cell.setToolTip(val)

    def _set_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.retry_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def _update_counts(self):
        self.empty_hint.setVisible(not self.items)
        done = sum(1 for i in self.items if i.status in ("完成", "需复核"))
        self.progress_label.setText(f"{done} / {len(self.items)}")

    def _update_preview(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        item = self.items[rows[0]]
        src = _load_pixmap(item.src)
        if src:
            self.preview_src.setPixmap(src.scaled(self.preview_src.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        out = _load_pixmap(item.output) if item.output and os.path.exists(item.output) else None
        if out:
            self.preview_out.setPixmap(out.scaled(self.preview_out.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview_out.clear()
            self.preview_out.setText("处理后显示")

    # ---------- 授权 ----------

    def _heartbeat(self):
        def run():
            try:
                self.session.heartbeat()
            except LicenseError as exc:
                self.heartbeat_failed.emit(exc.message)

        threading.Thread(target=run, daemon=True).start()
        QTimer.singleShot(3000, self._refresh_license_info)

    def _refresh_license_info(self):
        exp = self.session.expires_at
        if getattr(self.session, "is_local", False):
            text = "免卡密模式"
        elif exp:
            remain = exp / 1000 - self.session.server_now()
            text = f"到期：{time.strftime('%Y-%m-%d %H:%M', time.localtime(exp / 1000))}（剩余 {max(0, int(remain // 86400))} 天 {max(0, int(remain % 86400 // 3600))} 小时）"
        else:
            text = "授权：永久"
        text += "  |  Google AI：" + ("已开通" if self.session.gemini_enabled else "未开通")
        self.license_label.setText(text)
        gemini_idx = self.mode.findData(MODE_GEMINI)
        self.mode.model().item(gemini_idx).setEnabled(self.session.gemini_enabled)

        notices = []
        if self.session.notice:
            notices.append(self.session.notice)
        if self.session.latest_version and self._version_tuple(self.session.latest_version) > self._version_tuple(config.APP_VERSION):
            notices.append(f"发现新版本 {self.session.latest_version}，请联系管理员获取")
        self.notice.setText("\n".join(notices))
        self.notice.setVisible(bool(notices))
        try:
            self.session.ensure_valid()
        except LicenseError as exc:
            self._force_logout(exc.message)

    def _save_api_key(self):
        key = self.api_key.text().strip()
        self.session.set_api_key(key)
        self.settings.setValue("gemini_key", key)
        self._refresh_license_info()
        self.statusBar().showMessage("Google AI 已启用" if key else "已清除 Google API Key", 5000)

    @staticmethod
    def _version_tuple(v: str):
        return tuple(int(p) if p.isdigit() else 0 for p in v.strip().split("."))

    def _force_logout(self, message: str):
        if self._closing_for_logout:
            return
        self._closing_for_logout = True
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(5000)
        self.timer.stop()
        self.clock.stop()
        QMessageBox.warning(self, "授权失效", message or "授权已失效，请重新登录")
        self.logout_requested.emit(message)
        self.close()

    # ---------- 设置保存 ----------

    def _toggle_size_inputs(self):
        mode = self.size_mode.currentData()
        self.long_side.setEnabled(mode == "long")
        for w in (self.canvas_w, self.canvas_h, self.align):
            w.setEnabled(mode == "canvas")

    def _choose_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出文件夹", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def _open_out_dir(self):
        path = self.out_dir.text().strip()
        if not path:
            outs = [i.output for i in self.items if i.output]
            path = os.path.dirname(outs[0]) if outs else ""
        if path and os.path.isdir(path):
            os.startfile(path) if hasattr(os, "startfile") else None
        else:
            QMessageBox.information(self, "提示", "还没有导出的文件")

    def _save_settings(self):
        s = self.settings
        s.setValue("mode", self.mode.currentIndex())
        s.setValue("shirt", self.shirt.currentIndex())
        s.setValue("sensitivity", self.sensitivity.value())
        s.setValue("feather", self.feather.value())
        s.setValue("enclosed", self.enclosed.isChecked())
        s.setValue("remove_small", self.remove_small.isChecked())
        s.setValue("verify_ai", self.verify_ai.isChecked())
        s.setValue("knockout", self.knockout.isChecked())
        s.setValue("auto_fallback", self.auto_fallback.isChecked())
        s.setValue("auto_threshold", self.auto_threshold.value())
        s.setValue("size_mode", self.size_mode.currentIndex())
        for name in ("long_side", "canvas_w", "canvas_h", "padding", "dpi"):
            s.setValue(name, getattr(self, name).value())
        s.setValue("align", self.align.currentIndex())
        s.setValue("out_dir", self.out_dir.text())
        s.setValue("keep_tree", self.keep_tree.isChecked())

    def _restore_settings(self):
        s = self.settings

        def b(key, default):
            v = s.value(key, default)
            return v if isinstance(v, bool) else str(v).lower() == "true"

        self.mode.setCurrentIndex(int(s.value("mode", 0)))
        self.shirt.setCurrentIndex(int(s.value("shirt", 0)))
        self.sensitivity.setValue(int(s.value("sensitivity", 50)))
        self.feather.setValue(int(s.value("feather", 2)))
        self.enclosed.setChecked(b("enclosed", True))
        self.remove_small.setChecked(b("remove_small", True))
        self.verify_ai.setChecked(b("verify_ai", True))
        self.knockout.setChecked(b("knockout", False))
        self.auto_fallback.setChecked(b("auto_fallback", True))
        self.auto_threshold.setValue(int(s.value("auto_threshold", 80)))
        self.size_mode.setCurrentIndex(int(s.value("size_mode", 0)))
        for name, default in (("long_side", 4500), ("canvas_w", 4500), ("canvas_h", 5400), ("padding", 20), ("dpi", 300)):
            getattr(self, name).setValue(int(s.value(name, default)))
        self.align.setCurrentIndex(int(s.value("align", 0)))
        self.out_dir.setText(str(s.value("out_dir", "")))
        self.keep_tree.setChecked(b("keep_tree", True))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning() and not self._closing_for_logout:
            if QMessageBox.question(self, "确认退出", "正在处理中，确定退出？") != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.stop()
            self.worker.wait(5000)
        self._save_settings()
        super().closeEvent(event)
