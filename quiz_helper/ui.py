"""主界面、设置、窗口选择、题区选择及悬浮窗。"""

from __future__ import annotations

from dataclasses import fields
from html import escape
from urllib.parse import urlsplit

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget,
    QTextBrowser, QVBoxLayout, QWidget, QKeySequenceEdit,
)

from . import __version__
from .models import AppSettings
from .releases import RELEASES
from .preview import RegionPreview


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    return widget


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return frame, layout


class ImagePreview(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.image = QImage()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(240, 140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setText("开始运行后，在窗口画面中框选一道题")
        self.setWordWrap(True)
        self.setObjectName("muted")

    def set_image(self, image: QImage) -> None:
        self.image = image.copy()
        self._refresh()

    def _refresh(self) -> None:
        if not self.image.isNull():
            self.setPixmap(QPixmap.fromImage(self.image).scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._refresh()


class HomePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(18)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("窗口题目查询", "title"))
        titles.addWidget(label("选定题区，点击查询，让答案保持简洁。", "muted"))
        header.addLayout(titles, 1)
        self.start_button = button("开始运行", True)
        self.stop_button = button("停止")
        self.stop_button.setEnabled(False)
        header.addWidget(self.stop_button)
        header.addWidget(self.start_button)
        layout.addLayout(header)
        target, box = card()
        row = QHBoxLayout()
        row.addWidget(label("目标窗口", "section"))
        row.addStretch()
        self.status_label = label("未启动", "badge")
        row.addWidget(self.status_label)
        box.addLayout(row)
        row = QHBoxLayout()
        self.target_label = label("尚未选择窗口", "muted")
        self.target_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.select_button = button("选择窗口")
        self.region_button = button("重新框选")
        self.overlay_button = button("显示悬浮窗")
        self.overlay_button.setEnabled(False)
        self.region_button.setEnabled(False)
        row.addWidget(self.target_label, 1)
        row.addWidget(self.select_button)
        row.addWidget(self.region_button)
        row.addWidget(self.overlay_button)
        box.addLayout(row)
        layout.addWidget(target)
        content = QHBoxLayout()
        preview_card, box = card()
        preview_header = QHBoxLayout()
        preview_header.addWidget(label("识别区域", "section"), 1)
        self.refresh_button = button("刷新画面")
        self.refresh_button.setEnabled(False)
        preview_header.addWidget(self.refresh_button)
        box.addLayout(preview_header)
        self.preview = RegionPreview()
        box.addWidget(self.preview, 1)
        box.addWidget(label("一次一道题 · 窗口最小化时暂停", "muted"))
        content.addWidget(preview_card, 6)
        answer_card, box = card()
        box.addWidget(label("最新答案", "section"))
        self.answer_label = label("—", "answer")
        self.answer_label.setWordWrap(True)
        self.answer_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.answer_label)
        self.explanation_check = QCheckBox("显示简短解析")
        box.addWidget(self.explanation_check)
        self.explanation_label = label("查询结果将同时显示在悬浮窗中。", "muted", True)
        box.addWidget(self.explanation_label, 1)
        self.query_button = button("截图搜题", True)
        self.cancel_button = button("取消本次查询")
        self.cancel_button.hide()
        self.force_button = button("强制重新查询")
        self.copy_button = button("复制答案")
        self.query_button.setEnabled(False)
        self.force_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        box.addWidget(self.query_button)
        box.addWidget(self.cancel_button)
        box.addWidget(self.force_button)
        box.addWidget(self.copy_button)
        content.addWidget(answer_card, 4)
        layout.addLayout(content, 1)
        self.metrics_label = label("DeepSeek Flash  ·  等待首次查询", "muted")
        layout.addWidget(self.metrics_label)
        self.message_label = label("截图只限所选窗口；本软件不会向目标进程注入。", "muted", True)
        layout.addWidget(self.message_label)


class SettingsPage(QWidget):
    save_requested = Signal()
    test_requested = Signal()
    delete_key_requested = Signal()
    cleanup_requested = Signal()

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.setObjectName("page")
        self.controls: dict[str, QWidget] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.addWidget(label("设置", "title"))
        layout.addWidget(label("密钥加密保存在本机；应用数据默认保存在软件目录。", "muted"))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        ai = self._tab("接口与答题")
        form = self._group(ai, "AI 接口")
        self._text(form, "base_url", "API Base URL")
        self._text(form, "model", "模型名称")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("输入 API Key；留空保持已保存的 Key")
        self.key_edit.setAccessibleName("API Key")
        form.addRow("API Key", self.key_edit)
        self.key_state = label("尚未保存 Key", "muted")
        form.addRow("保存状态", self.key_state)
        row = QHBoxLayout()
        self.test_button = button("测试连接")
        self.delete_key_button = button("删除已保存 Key")
        row.addWidget(self.test_button)
        row.addWidget(self.delete_key_button)
        form.addRow(row)
        self.test_button.clicked.connect(self.test_requested)
        self.delete_key_button.clicked.connect(self.delete_key_requested)
        form = self._group(ai, "答题策略与请求")
        self._combo(form, "question_type", "题型", [("自动识别", "auto"), ("单选", "single"), ("多选", "multiple"), ("判断", "boolean")])
        self._combo(form, "reasoning", "思考强度", [("关闭 · 快速", "none"), ("低 · 均衡（默认）", "low"), ("高 · 严谨", "high"), ("最高 · 较慢", "max")])
        self._check(form, "explanation", "返回简短解析")
        self._spin(form, "request_timeout", "请求超时（秒）", 1, 600)
        form.addRow(label("思考参数仅发送给 DeepSeek 模型；兼容接口需支持图片及 JSON 输出。", "muted", True))
        files = self._tab("截图与清理")
        form = self._group(files, "题区图片")
        self._combo(form, "image_format", "图片格式", [("PNG · 清晰（默认）", "PNG"), ("JPEG · 较小", "JPEG")])
        self._spin(form, "jpeg_quality", "JPEG 质量", 1, 100)
        self._spin(form, "max_image_edge", "最长边（0 为原图）", 0, 8192)
        self.controls["max_image_edge"].setSingleStep(256)
        self._spin(form, "capture_timeout", "截图超时（秒）", 1, 60)
        form = self._group(files, "保存与自动清理")
        row = QHBoxLayout()
        self._text(None, "capture_dir", "截图目录")
        row.addWidget(self.controls["capture_dir"], 1)
        browse = button("浏览")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        form.addRow("截图目录", row)
        form.addRow(label("留空使用软件目录 data/captures；仅支持非 C 盘可写目录。", "muted", True))
        self._check(form, "auto_cleanup", "自动清理过期截图")
        self._spin(form, "retention_minutes", "任务结束后保留（分钟）", 1, 43200)
        self.usage_label = label("截图占用：0 个文件 / 0 KB", "muted")
        form.addRow(self.usage_label)
        cleanup = button("立即清理已完成任务的截图")
        cleanup.clicked.connect(self.cleanup_requested)
        form.addRow(cleanup)
        display = self._tab("显示与通用")
        form = self._group(display, "界面与悬浮窗")
        self._combo(form, "theme", "主题", [("浅色", "light"), ("深色", "dark")])
        self._combo(form, "overlay_mode", "悬浮定位", [("吸附目标窗口右下角", "target"), ("自由悬浮", "free")])
        self._spin(form, "overlay_font_size", "悬浮答案字号", 12, 72)
        self._spin(form, "overlay_opacity", "悬浮窗透明度（%）", 20, 100)
        self._check(form, "overlay_topmost", "悬浮窗置顶")
        self._check(form, "overlay_remember_position", "记住悬浮窗位置")
        self._spin(form, "answer_hide_seconds", "答案隐藏（秒，0 为持续）", 0, 86400)
        form = self._group(display, "全局搜题快捷键")
        self._check(form, "hotkey_enabled", "启用全局搜题快捷键")
        shortcut = QKeySequenceEdit()
        shortcut.setMaximumSequenceLength(1)
        shortcut.setAccessibleName("搜题快捷键")
        self.controls["query_hotkey"] = shortcut
        form.addRow("搜题快捷键", shortcut)
        form.addRow(label("默认 Ctrl＋Alt＋Q；支持 Ctrl / Alt / Shift 组合或 F1～F11。查询中不会重复提交。", "muted", True))
        form = self._group(display, "代理与日志")
        self._combo(form, "proxy_mode", "代理方式", [("使用系统代理", "system"), ("不使用代理", "none"), ("自定义代理", "custom")])
        self._text(form, "proxy_url", "代理地址")
        self.controls["proxy_url"].setPlaceholderText("http://127.0.0.1:7890 或 socks5://127.0.0.1:1080")
        self._combo(form, "log_level", "脱敏日志级别", [("仅错误", "ERROR"), ("警告", "WARNING"), ("基本运行状态", "INFO"), ("调试状态（无请求正文）", "DEBUG")])
        for index in range(self.tabs.count()):
            self.tabs.widget(index).widget().layout().addStretch()
        row = QHBoxLayout()
        self.feedback = label("修改后点击保存生效。", "muted", True)
        row.addWidget(self.feedback, 1)
        save = button("保存设置", True)
        save.clicked.connect(self.save_requested)
        row.addWidget(save)
        layout.addLayout(row)
        self._settings = settings
        self.load(settings)
        self.controls["image_format"].currentIndexChanged.connect(self._conditional_fields)
        self.controls["proxy_mode"].currentIndexChanged.connect(self._conditional_fields)
        self.controls["auto_cleanup"].toggled.connect(self._conditional_fields)
        self.controls["base_url"].textChanged.connect(self._conditional_fields)
        self.controls["model"].textChanged.connect(self._conditional_fields)
        self.controls["hotkey_enabled"].toggled.connect(self._conditional_fields)
        self._conditional_fields()

    def _tab(self, title: str) -> QVBoxLayout:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        box = QVBoxLayout(inner)
        box.setContentsMargins(0, 8, 8, 8)
        box.setSpacing(12)
        area.setWidget(inner)
        self.tabs.addTab(area, title)
        return box

    def _group(self, box: QVBoxLayout, title: str) -> QFormLayout:
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        box.addWidget(group)
        return form

    def _text(self, form: QFormLayout | None, key: str, title: str) -> None:
        item = QLineEdit()
        item.setAccessibleName(title)
        self.controls[key] = item
        if form is not None:
            form.addRow(title, item)

    def _spin(self, form: QFormLayout, key: str, title: str, low: int, high: int) -> None:
        item = QSpinBox()
        item.setRange(low, high)
        item.setAccessibleName(title)
        self.controls[key] = item
        form.addRow(title, item)

    def _combo(self, form: QFormLayout, key: str, title: str, choices: list[tuple[str, str]]) -> None:
        item = QComboBox()
        for text, value in choices:
            item.addItem(text, value)
        item.setAccessibleName(title)
        self.controls[key] = item
        form.addRow(title, item)

    def _check(self, form: QFormLayout, key: str, title: str) -> None:
        item = QCheckBox(title)
        self.controls[key] = item
        form.addRow(item)

    def load(self, settings: AppSettings) -> None:
        self._settings = settings
        for key, control in self.controls.items():
            value = getattr(settings, key)
            if isinstance(control, QComboBox):
                control.setCurrentIndex(max(0, control.findData(value)))
            elif isinstance(control, QCheckBox):
                control.setChecked(value)
            elif isinstance(control, QSpinBox):
                control.setValue(value)
            elif isinstance(control, QKeySequenceEdit):
                control.setKeySequence(QKeySequence(value))
            else:
                control.setText(value)

    def read_settings(self) -> AppSettings:
        values = {field.name: getattr(self._settings, field.name) for field in fields(AppSettings)}
        for key, control in self.controls.items():
            if isinstance(control, QComboBox):
                values[key] = control.currentData()
            elif isinstance(control, QCheckBox):
                values[key] = control.isChecked()
            elif isinstance(control, QSpinBox):
                values[key] = control.value()
            elif isinstance(control, QKeySequenceEdit):
                values[key] = control.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            else:
                values[key] = control.text().strip()
        result = AppSettings(**values)
        result.validate()
        return result

    def _browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择非 C 盘截图目录", self.controls["capture_dir"].text())
        if directory:
            self.controls["capture_dir"].setText(directory)

    def _conditional_fields(self, *_args: object) -> None:
        self.controls["jpeg_quality"].setEnabled(self.controls["image_format"].currentData() == "JPEG")
        self.controls["proxy_url"].setEnabled(self.controls["proxy_mode"].currentData() == "custom")
        self.controls["retention_minutes"].setEnabled(self.controls["auto_cleanup"].isChecked())
        self.controls["query_hotkey"].setEnabled(self.controls["hotkey_enabled"].isChecked())
        try:
            host = urlsplit(self.controls["base_url"].text().strip()).hostname or ""
        except ValueError:
            host = ""
        deepseek = host.casefold() == "api.deepseek.com" or self.controls["model"].text().strip().casefold().startswith("deepseek-")
        self.controls["reasoning"].setEnabled(deepseek)
        self.controls["reasoning"].setToolTip("DeepSeek 思考强度" if deepseek else "当前兼容模型不发送 DeepSeek 专用思考参数")


class AnnouncementsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("page")
        box = QVBoxLayout(self)
        box.setContentsMargins(28, 24, 28, 24)
        box.addWidget(label("开发公告", "title"))
        box.addWidget(label("记录每次改进，也明确当前的能力边界。", "muted"))
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        parts = []
        for release in RELEASES:
            changes = "".join(f"<li>{escape(item)}</li>" for item in release["changes"])
            limits = "".join(f"<li>{escape(item)}</li>" for item in release["limitations"])
            parts.append(f'<h2>v{release["version"]} · {release["title"]}</h2><p>{release["date"]} · 预览版本</p><h3>本轮新增</h3><ul>{changes}</ul><h3>已知限制与待验收</h3><ul>{limits}</ul>')
        browser.setHtml("<style>body{line-height:1.65}li{margin:8px 0}h2{color:#318773}</style>" + "".join(parts))
        box.addWidget(browser, 1)
        box.addWidget(label(f"当前版本 {__version__} · 公告随软件发布，无后台联网更新", "muted"))


class WindowPicker(QDialog):
    def __init__(self, windows: list[object], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择要识别的窗口")
        self.resize(560, 430)
        box = QVBoxLayout(self)
        box.addWidget(label("选择目标窗口", "section"))
        box.addWidget(label("仅捕获所选窗口画面，不操作目标程序。", "muted"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索窗口标题…")
        box.addWidget(self.search)
        self.list = QListWidget()
        for window in windows:
            item = QListWidgetItem(f"{window.title}  ·  {window.window_id:#x}")
            item.setData(Qt.ItemDataRole.UserRole, window)
            self.list.addItem(item)
        box.addWidget(self.list, 1)
        if not windows:
            box.addWidget(label("没有可捕获的窗口。请打开并恢复目标程序后重试。", "muted", True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("选择")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.list.itemDoubleClicked.connect(self._accept)
        self.search.textChanged.connect(self._filter)
        box.addWidget(buttons)

    def _filter(self, text: str) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(text.casefold() not in item.text().casefold())

    def _accept(self, *_args: object) -> None:
        if self.list.currentItem() is not None and not self.list.currentItem().isHidden():
            self.accept()

    def selected(self) -> object | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None


class CropCanvas(QWidget):
    changed = Signal()

    def __init__(self, image: QImage) -> None:
        super().__init__()
        self.image = image
        self.selection = QRect()
        self._origin = QPoint()
        self.setMinimumSize(400, 260)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def image_rect(self) -> QRect:
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width() - size.width()) // 2, (self.height() - size.height()) // 2, size.width(), size.height())

    def pixel_rect(self) -> QRect:
        display = self.image_rect()
        selected = self.selection.intersected(display)
        if selected.isEmpty():
            return QRect()
        x = round((selected.x() - display.x()) * self.image.width() / display.width())
        y = round((selected.y() - display.y()) * self.image.height() / display.height())
        width = round(selected.width() * self.image.width() / display.width())
        height = round(selected.height() * self.image.height() / display.height())
        return QRect(x, y, width, height).intersected(self.image.rect())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(event.position().toPoint()):
            self._origin = event.position().toPoint()
            self.selection = QRect(self._origin, self._origin)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.selection = QRect(self._origin, event.position().toPoint()).normalized().intersected(self.image_rect())
            self.update()
            self.changed.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.changed.emit()

    def resizeEvent(self, event: object) -> None:
        self.selection = QRect()
        self.changed.emit()
        super().resizeEvent(event)

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#e8f1ec"))
        painter.drawImage(self.image_rect(), self.image)
        if not self.selection.isEmpty():
            painter.setPen(QPen(Qt.GlobalColor.white, 1))
            painter.drawRect(self.selection.adjusted(-1, -1, 1, 1))
            painter.setPen(QPen(QColor("#318773"), 2))
            painter.drawRect(self.selection)
        painter.end()


class CropDialog(QDialog):
    def __init__(self, image: QImage, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("框选一道题 · 包含完整题干与选项")
        self.resize(900, 650)
        box = QVBoxLayout(self)
        box.addWidget(label("拖动框选题目区域", "section"))
        box.addWidget(label("请包含完整题干与全部选项；图片坐标不受屏幕缩放影响。", "muted"))
        self.canvas = CropCanvas(image)
        box.addWidget(self.canvas, 1)
        self.info = label("尚未选择区域", "muted")
        box.addWidget(self.info)
        row = QHBoxLayout()
        full = button("使用整个窗口")
        full.clicked.connect(self._full)
        row.addWidget(full)
        row.addStretch()
        cancel = button("取消")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.confirm = button("确认题区", True)
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self.accept)
        row.addWidget(self.confirm)
        box.addLayout(row)
        self.canvas.changed.connect(self._changed)

    def _full(self) -> None:
        self.canvas.selection = self.canvas.image_rect()
        self.canvas.update()
        self._changed()

    def _changed(self) -> None:
        rect = self.canvas.pixel_rect()
        valid = rect.width() >= 40 and rect.height() >= 40
        self.confirm.setEnabled(valid)
        self.info.setText(f"已选 {rect.width()} × {rect.height()} 像素" if valid else "请框选至少 40 × 40 像素的完整题目")


class FloatingPanel(QFrame):
    query_requested = Signal()
    stop_requested = Signal()
    show_main_requested = Signal()
    moved = Signal(object)
    restore_anchor_requested = Signal()
    cancel_requested = Signal()
    resized = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("overlay")
        self.setWindowTitle("题目查询助手 · 悬浮窗")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setFixedWidth(300)
        self._drag_offset: QPoint | None = None
        self.dragging = False
        self.answer_text = ""
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.clear_answer)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 14)
        top = QHBoxLayout()
        self.status = label("准备就绪 · 拖动空白处移动", "muted", True)
        top.addWidget(self.status, 1)
        main = button("主页")
        main.setMaximumWidth(58)
        main.clicked.connect(self.show_main_requested)
        top.addWidget(main)
        box.addLayout(top)
        self.answer = label("—", "answer")
        self.answer.setWordWrap(True)
        box.addWidget(self.answer)
        self.details = label("", "muted", True)
        self.details.setVisible(False)
        box.addWidget(self.details)
        row = QHBoxLayout()
        self.query = button("截图搜题", True)
        self.query.clicked.connect(self.query_requested)
        self.copy = button("复制")
        self.copy.setEnabled(False)
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.answer_text))
        stop = button("停止")
        stop.clicked.connect(self.stop_requested)
        row.addWidget(self.query, 1)
        row.addWidget(self.copy)
        row.addWidget(stop)
        box.addLayout(row)
        self.hotkey_label = label("Ctrl＋Alt＋Q · 全局搜题", "muted")
        box.addWidget(self.hotkey_label)
        self.cancel_button = button("取消本次查询")
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.cancel_button.hide()
        box.addWidget(self.cancel_button)
        self.anchor_button = button("恢复吸附到目标窗口")
        self.anchor_button.clicked.connect(self.restore_anchor_requested)
        self.anchor_button.hide()
        box.addWidget(self.anchor_button)
        self.expand = QPushButton("展开简短解析")
        self.expand.setCheckable(True)
        self.expand.setVisible(False)
        self.expand.toggled.connect(self._toggle_details)
        box.addWidget(self.expand)

    def apply_settings(self, settings: AppSettings) -> None:
        self.setWindowOpacity(settings.overlay_opacity / 100)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, settings.overlay_topmost)
        color = "#79d9b8" if settings.theme == "dark" else "#267563"
        self.answer.setStyleSheet(f"font-size: {settings.overlay_font_size}px; font-weight: 700; color: {color};")
        self.hide_seconds = settings.answer_hide_seconds
        self.hotkey_label.setText(settings.query_hotkey.replace("+", "＋") + " · 全局搜题" if settings.hotkey_enabled else "全局快捷键已关闭")
        self.anchor_button.setVisible(settings.overlay_mode == "free")

    def clear_answer(self) -> None:
        self.hide_timer.stop()
        self.answer_text = ""
        self.answer.setText("—")
        self.copy.setEnabled(False)
        self.details.clear()
        self.details.hide()
        self.expand.hide()
        self.expand.setChecked(False)
        self.adjustSize()

    def show_answer(self, text: str, explanation: str) -> None:
        self.clear_answer()
        self.answer_text = text
        self.answer.setText(text)
        self.copy.setEnabled(True)
        self.details.setText(explanation)
        self.expand.setVisible(bool(explanation))
        if self.hide_seconds:
            self.hide_timer.start(self.hide_seconds * 1000)
        self.adjustSize()

    def _toggle_details(self, checked: bool) -> None:
        self.details.setVisible(checked and bool(self.details.text()))
        self.expand.setText("收起简短解析" if checked else "展开简短解析")
        self.adjustSize()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.dragging = False
            self.moved.emit([self.x(), self.y()])

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self.resized.emit()
