"""桌面应用入口与页面连接。"""

from __future__ import annotations

from dataclasses import replace
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from PySide6.QtCore import QLockFile, QRect, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QFont, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from . import __version__
from .ai import AIClient
from .controller import SessionController
from .branding import application_icon, set_windows_identity
from .docking import OverlayFollower
from .hotkeys import HotkeyManager
from .models import AnswerResult, AppSettings
from .storage import AppStorage, non_c_path
from .theme import stylesheet
from .ui import AnnouncementsPage, CropDialog, FloatingPanel, HomePage, SettingsPage, WindowPicker, button, label


class MainWindow(QMainWindow):
    def __init__(self, storage: AppStorage) -> None:
        super().__init__()
        self.storage = storage
        self.controller = SessionController(storage, self)
        self.connection_client = AIClient(self)
        self.setWindowTitle("题目查询助手")
        self.setWindowIcon(application_icon())
        self.resize(960, 680)
        self.setMinimumSize(860, 620)
        self._answer_text = ""
        self._connection_busy = False
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(166)
        box = QVBoxLayout(sidebar)
        box.setContentsMargins(16, 25, 16, 20)
        box.setSpacing(10)
        logo = label("Q", "brand")
        logo.setFixedSize(46, 46)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(logo)
        box.addWidget(label("题目查询助手", "section"))
        box.addWidget(label("WINDOW QUIZ", "muted"))
        box.addSpacing(26)
        self.nav_buttons = []
        for index, text in enumerate(("主页", "设置", "开发公告")):
            item = button(text)
            item.setObjectName("nav")
            item.setCheckable(True)
            item.clicked.connect(lambda _checked, position=index: self.show_page(position))
            box.addWidget(item)
            self.nav_buttons.append(item)
        box.addStretch()
        box.addWidget(label("本地工具 · 按次查询", "muted"))
        box.addWidget(label(f"v{__version__}  预览版", "muted"))
        layout.addWidget(sidebar)
        self.stack = QStackedWidget()
        self.home = HomePage()
        self.settings_page = SettingsPage(storage.settings)
        self.announcements = AnnouncementsPage()
        for page in (self.home, self.settings_page, self.announcements):
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)
        self.overlay = FloatingPanel()
        self.overlay.setWindowIcon(application_icon())
        self.follower = OverlayFollower(self.overlay, self.controller, self)
        self.hotkeys = HotkeyManager(self)
        self.hotkeys.activated.connect(self._hotkey_query)
        self.follower.restored.connect(self._restore_anchor)
        self.show_page(0)
        self._wire()
        self._apply_visual_settings()
        self._update_key_state()
        self._update_usage()
        self._update_actions()
        try:
            self._bind_hotkey(self.controller.settings)
        except ValueError as exc:
            self.settings_page.feedback.setText(str(exc))
            self.overlay.hotkey_label.setText("快捷键未注册，请在设置中更换")
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.setInterval(30_000)
        self.cleanup_timer.timeout.connect(self._auto_cleanup)
        self.cleanup_timer.start()

    def _wire(self) -> None:
        home, controller = self.home, self.controller
        home.start_button.clicked.connect(self._select_window)
        home.select_button.clicked.connect(self._select_window)
        home.stop_button.clicked.connect(controller.stop)
        home.region_button.clicked.connect(controller.reselect_region)
        home.overlay_button.clicked.connect(self._reveal_overlay)
        home.refresh_button.clicked.connect(controller.refresh_preview)
        home.cancel_button.clicked.connect(controller.cancel_query)
        home.query_button.clicked.connect(lambda: controller.query())
        home.force_button.clicked.connect(lambda: controller.query(force=True))
        home.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self._answer_text))
        home.explanation_check.toggled.connect(self._toggle_explanation)
        controller.status_changed.connect(self._status)
        controller.target_changed.connect(home.target_label.setText)
        controller.preview_changed.connect(home.preview.set_image)
        controller.frame_preview_changed.connect(home.preview.set_frame)
        controller.region_needed.connect(self._choose_region)
        controller.answer_ready.connect(self._show_answer)
        controller.answer_cleared.connect(self._clear_answer)
        controller.error.connect(self._show_error)
        controller.running_changed.connect(self._running_changed)
        controller.busy_changed.connect(lambda _busy: self._update_actions())
        page = self.settings_page
        page.save_requested.connect(self._save_settings)
        page.test_requested.connect(self._test_connection)
        page.delete_key_requested.connect(self._delete_key)
        page.cleanup_requested.connect(self._manual_cleanup)
        self.connection_client.connected.connect(self._connection_success)
        self.connection_client.failed.connect(self._connection_error)
        self.overlay.query_requested.connect(lambda: controller.query())
        self.overlay.stop_requested.connect(controller.stop)
        self.overlay.show_main_requested.connect(self._show_main)
        self.overlay.moved.connect(self._remember_overlay)
        self.overlay.restore_anchor_requested.connect(self._restore_anchor)
        self.overlay.cancel_requested.connect(controller.cancel_query)
        self.overlay.resized.connect(self.follower.refresh)

    def _bind_hotkey(self, settings: AppSettings) -> None:
        if QGuiApplication.platformName() != "offscreen":
            self.hotkeys.bind(settings.query_hotkey, settings.hotkey_enabled)

    def _hotkey_query(self) -> None:
        controller = self.controller
        focus = QApplication.focusWidget()
        shortcut_editor = self.settings_page.controls["query_hotkey"]
        if QApplication.activeModalWidget() is not None or (focus is not None and (focus is shortcut_editor or shortcut_editor.isAncestorOf(focus))):
            return
        if controller.running and not controller.paused and not controller.busy and not self._connection_busy and not self.follower.suspended and not controller.region.isEmpty():
            controller.query()

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for number, item in enumerate(self.nav_buttons):
            item.setChecked(number == index)

    def _show_main(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _select_window(self) -> None:
        if self.controller.busy:
            return
        try:
            windows = self.controller.capture.list_windows()
            dialog = WindowPicker(windows, self)
            if dialog.exec() == dialog.DialogCode.Accepted:
                selected = dialog.selected()
                if selected is not None:
                    self.controller.choose_target(selected)
        except (OSError, RuntimeError):
            self._show_error("无法列出可捕获窗口，请确认目标程序已打开。")

    def _choose_region(self, image: QImage) -> None:
        if not self.controller.running:
            return
        self.overlay.hide()
        self.follower.suspended = True
        try:
            dialog = CropDialog(image, self)
            if dialog.exec() == dialog.DialogCode.Accepted and self.controller.running and not self.controller.paused:
                rect = dialog.canvas.pixel_rect()
                self.controller.set_region(rect, image.size())
                self.home.preview.set_frame(image, rect)
                self.home.message_label.setText(f"题区 {rect.width()} × {rect.height()} 像素；窗口移动不会改变题区。")
            else:
                self._status("已暂停 · 目标最小化" if self.controller.paused else "请框选题区" if self.controller.region.isEmpty() else "准备就绪")
        finally:
            self.follower.suspended = False
            self.follower.refresh()
            self._update_actions()

    def _status(self, text: str) -> None:
        self.home.status_label.setText(text)
        self.overlay.status.setText(text)
        self._update_actions()

    def _running_changed(self, running: bool) -> None:
        if running:
            self._position_overlay()
            self.follower.start()
        else:
            self.follower.stop()
            self.home.preview.clear()
        self._update_actions()

    def _update_actions(self) -> None:
        controller, home = self.controller, self.home
        busy = controller.busy or self._connection_busy
        ready = controller.running and not controller.paused and not controller.region.isEmpty() and not busy
        home.start_button.setEnabled(not busy)
        home.start_button.setText("更换窗口" if controller.running else "开始运行")
        home.select_button.setEnabled(not busy)
        home.region_button.setEnabled(controller.running and not controller.paused and not busy)
        home.overlay_button.setEnabled(controller.running and not controller.paused)
        home.refresh_button.setEnabled(ready)
        home.stop_button.setEnabled(controller.running)
        home.query_button.setEnabled(ready)
        home.force_button.setEnabled(ready)
        home.explanation_check.setEnabled(not busy)
        self.overlay.query.setEnabled(ready)
        home.cancel_button.setVisible(controller.busy)
        self.overlay.cancel_button.setVisible(controller.busy)
        self.overlay.adjustSize()
        self.settings_page.test_button.setEnabled(not busy)

    def _clear_answer(self) -> None:
        self._answer_text = ""
        self.home.answer_label.setText("—")
        self.home.copy_button.setEnabled(False)
        self.home.explanation_label.setText("查询结果将同时显示在悬浮窗中。")
        self.home.metrics_label.setText(f"{self.controller.settings.model} · 等待查询")
        self.overlay.clear_answer()

    def _show_answer(self, result: AnswerResult, usage: dict, elapsed: float, cached: bool) -> None:
        self._answer_text = result.display_text
        self.home.answer_label.setText(result.display_text)
        self.home.copy_button.setEnabled(True)
        self.home.explanation_label.setText(result.explanation or "已关闭简短解析。可在查询前开启。")
        if cached:
            metrics = f"本次运行内复用 · 本次未调用 AI · {elapsed:.2f} 秒"
        else:
            total = usage.get("total_tokens")
            if total is None and isinstance(usage.get("prompt_tokens"), int) and isinstance(usage.get("completion_tokens"), int):
                total = usage["prompt_tokens"] + usage["completion_tokens"]
            token_text = str(total) if type(total) is int and total >= 0 else "接口未提供"
            metrics = f"{self.controller.settings.model} · {elapsed:.2f} 秒 · Token {token_text}"
        self.home.metrics_label.setText(metrics)
        self.home.message_label.setText("答案来自 AI，请结合完整题目核对。")
        self.overlay.show_answer(result.display_text, result.explanation)
        self._update_usage()

    def _show_error(self, message: str) -> None:
        self.home.message_label.setText(message)
        self.overlay.status.setText(message)
        self.overlay.adjustSize()
        self._update_actions()

    def _apply_visual_settings(self) -> None:
        settings = self.controller.settings
        QApplication.instance().setStyleSheet(stylesheet(settings.theme))
        self.overlay.apply_settings(settings)
        self.follower.refresh()
        self.home.explanation_check.blockSignals(True)
        self.home.explanation_check.setChecked(settings.explanation)
        self.home.explanation_check.blockSignals(False)
        logging.getLogger().setLevel(getattr(logging, settings.log_level))

    def _save_settings(self) -> None:
        try:
            settings = self.settings_page.read_settings()
            previous = self.controller.settings
            self._bind_hotkey(settings)
            try:
                self.storage.save_settings(settings)
            except (OSError, ValueError):
                self._bind_hotkey(previous)
                raise
            self.controller.apply_settings(settings)
            self.settings_page.load(settings)
            self._apply_visual_settings()
            self.connection_client.cancel()
            self._connection_busy = False
            key = self.settings_page.key_edit.text().strip()
            if key:
                try:
                    self.storage.save_key(key)
                except (OSError, ValueError):
                    self.settings_page.feedback.setText("设置已保存，但 Key 加密保存失败，请重试。")
                    return
                self.settings_page.key_edit.clear()
            self.settings_page.feedback.setText("设置已保存并生效；密钥仅以 DPAPI 密文保存。")
        except (OSError, ValueError) as exc:
            self.settings_page.feedback.setText(str(exc) if isinstance(exc, ValueError) else "设置保存失败，请检查非 C 盘目录权限。")
        finally:
            self._update_key_state()
            self._update_actions()
            self._update_usage()

    def _toggle_explanation(self, enabled: bool) -> None:
        if self.controller.settings.explanation == enabled:
            return
        settings = replace(self.controller.settings, explanation=enabled)
        try:
            self.storage.save_settings(settings)
            self.controller.apply_settings(settings)
            self.settings_page.load(settings)
        except (OSError, ValueError):
            self._show_error("解析设置保存失败，请检查数据目录。")
            self._apply_visual_settings()

    def _update_key_state(self) -> None:
        self.settings_page.key_state.setText("已加密保存 · 留空保持" if self.storage.key_path.exists() else "尚未保存 Key")

    def _delete_key(self) -> None:
        try:
            self.controller.apply_settings(self.controller.settings)
            self.connection_client.cancel()
            self._connection_busy = False
            self.storage.delete_key()
            self.settings_page.key_edit.clear()
            self.settings_page.feedback.setText("本机已保存的 Key 已删除。")
        except OSError:
            self.settings_page.feedback.setText("Key 删除失败，请检查数据目录权限。")
        self._update_key_state()
        self._update_actions()

    def _test_connection(self) -> None:
        try:
            settings = self.settings_page.read_settings()
            key = self.settings_page.key_edit.text().strip() or self.storage.load_key()
            self._connection_busy = True
            self.settings_page.feedback.setText("正在测试接口连接…（不提交截图）")
            self._update_actions()
            self.connection_client.test_connection(settings, key)
        except (OSError, ValueError):
            self._connection_error("请检查接口配置及本机加密 Key，必要时重新输入。")

    def _connection_success(self, message: str) -> None:
        self._connection_busy = False
        self.settings_page.feedback.setText(message)
        self._update_actions()

    def _connection_error(self, message: str) -> None:
        self._connection_busy = False
        self.settings_page.feedback.setText(message)
        self._update_actions()

    def _update_usage(self) -> None:
        try:
            count, size = self.storage.capture_usage()
            self.settings_page.usage_label.setText(f"截图占用：{count} 个文件 / {size / 1024:.1f} KB")
        except (OSError, ValueError):
            self.settings_page.usage_label.setText("无法读取截图占用，请检查目录。")

    def _manual_cleanup(self) -> None:
        try:
            count, size = self.storage.cleanup(manual=True)
            self.settings_page.feedback.setText(f"已清理 {count} 张已完成任务截图，释放 {size / 1024:.1f} KB；使用中的截图保留。")
        except (OSError, ValueError) as exc:
            self.settings_page.feedback.setText(str(exc))
        self._update_usage()

    def _auto_cleanup(self) -> None:
        try:
            self.storage.cleanup()
        except (OSError, ValueError):
            logging.warning("scheduled capture cleanup failed")
            self.home.message_label.setText("部分过期截图清理失败，请在设置中检查目录并手动清理。")
        self._update_usage()

    def _position_overlay(self) -> None:
        settings = self.controller.settings
        if settings.overlay_mode == "target":
            self.follower.refresh()
            return
        position = settings.overlay_position if settings.overlay_remember_position else None
        if position is not None:
            desired = QRect(position[0], position[1], self.overlay.width(), max(120, self.overlay.height()))
            screen = next((item for item in QGuiApplication.screens() if item.availableGeometry().intersects(desired)), None)
        else:
            screen = None
        if screen is not None:
            bounds = screen.availableGeometry()
            self.overlay.move(max(bounds.left(), min(position[0], bounds.right() - self.overlay.width())), max(bounds.top(), min(position[1], bounds.bottom() - self.overlay.height())))
        else:
            screen = self.screen() or QApplication.primaryScreen()
            bounds = screen.availableGeometry()
            self.overlay.move(bounds.right() - self.overlay.width() - 24, bounds.bottom() - 220)

    def _remember_overlay(self, position: list[int]) -> None:
        current = self.controller.settings
        settings = replace(current, overlay_mode="free", overlay_position=list(position) if current.overlay_remember_position else current.overlay_position)
        self._save_overlay_settings(settings)

    def _reveal_overlay(self) -> None:
        if not self.follower.suspended and QApplication.activeModalWidget() is None:
            self.follower.refresh(force=True)

    def _restore_anchor(self) -> None:
        self._save_overlay_settings(replace(self.controller.settings, overlay_mode="target"))

    def _save_overlay_settings(self, settings: AppSettings) -> None:
        try:
            self.storage.save_settings(settings)
            self.controller.settings = settings
            self.settings_page._settings = settings
            self.settings_page.controls["overlay_mode"].setCurrentIndex(0 if settings.overlay_mode == "target" else 1)
            self.overlay.anchor_button.setVisible(settings.overlay_mode == "free")
            self.overlay.adjustSize()
            self.follower.refresh()
        except (OSError, ValueError):
            self._show_error("悬浮窗位置保存失败，请检查数据目录。")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.connection_client.cancel()
        self.hotkeys.close()
        self.follower.stop()
        self.controller.stop()
        self.controller.watcher.stop()
        self.cleanup_timer.stop()
        self.overlay.close()
        event.accept()


def run(app_root: Path) -> int:
    set_windows_identity()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    application = QApplication(sys.argv)
    application.setApplicationName("题目查询助手")
    application.setApplicationVersion(__version__)
    application.setWindowIcon(application_icon())
    application.setFont(QFont("Microsoft YaHei UI", 10))
    application.setStyle("Fusion")
    try:
        root = non_c_path(app_root)
        data = non_c_path(root / "data")
        data.mkdir(exist_ok=True)
        instance_lock = QLockFile(str(data / "application.lock"))
        instance_lock.setStaleLockTime(0)
        if not instance_lock.tryLock(0):
            QMessageBox.information(None, "题目查询助手", "本目录的软件已在运行，请使用已打开的窗口。")
            return 0
        storage = AppStorage(root)
        logs = non_c_path(data / "logs")
        logs.mkdir(exist_ok=True)
        handler = RotatingFileHandler(logs / "app.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(storage.settings.log_level)
    except (OSError, ValueError) as exc:
        QMessageBox.critical(None, "无法启动", str(exc))
        return 1

    def exception_hook(exc_type: type, _value: BaseException, _traceback: object) -> None:
        logging.error("unhandled error type=%s", exc_type.__name__)
        QMessageBox.warning(None, "操作失败", "发生未处理错误，请停止运行后重试。日志仅记录错误类型，不记录密钥或请求正文。")

    sys.excepthook = exception_hook
    window = MainWindow(storage)
    window.show()
    logging.info("application started; version=%s", __version__)
    exit_code = application.exec()
    instance_lock.unlock()
    handler.close()
    logging.getLogger().removeHandler(handler)
    return exit_code
