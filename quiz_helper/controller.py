"""会话状态、任务失效和单次截图查询调度。"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
import time

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QRect, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage

from .ai import AIClient
from .capture import CaptureService, WindowInfo
from .models import AnswerResult, AppSettings
from .storage import AppStorage
from . import win32


class EncodeSignals(QObject):
    done = Signal(int, object, str)
    failed = Signal(int, str)


class ImageEncoder(QRunnable):
    def __init__(self, token: int, image: QImage, settings: AppSettings) -> None:
        super().__init__()
        self.token, self.image, self.settings = token, image, settings
        self.signals = EncodeSignals()

    def run(self) -> None:
        try:
            image = self.image
            edge = self.settings.max_image_edge
            if edge and max(image.width(), image.height()) > edge:
                image = image.scaled(edge, edge, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
                raise ValueError("无法创建图片缓冲区。")
            quality = self.settings.jpeg_quality if self.settings.image_format == "JPEG" else -1
            if not image.save(buffer, self.settings.image_format, quality):
                raise ValueError("图片编码失败。")
            buffer.close()
            mime = "image/jpeg" if self.settings.image_format == "JPEG" else "image/png"
            self.signals.done.emit(self.token, bytes(data), mime)
        except (ValueError, RuntimeError, MemoryError):
            self.signals.failed.emit(self.token, "图片处理失败，请缩小识别区域后重试。")


class SessionController(QObject):
    status_changed = Signal(str)
    target_changed = Signal(str)
    preview_changed = Signal(object)
    frame_preview_changed = Signal(object, object)
    answer_ready = Signal(object, object, float, bool)
    error = Signal(str)
    running_changed = Signal(bool)
    region_needed = Signal(object)
    busy_changed = Signal(bool)
    answer_cleared = Signal()

    def __init__(self, storage: AppStorage, parent: QObject | None = None,
                 capture: CaptureService | None = None, ai: AIClient | None = None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = storage.settings
        self.capture = capture if capture is not None else CaptureService(self)
        self.ai = ai if ai is not None else AIClient(self)
        self.target: WindowInfo | None = None
        self.running = False
        self.busy = False
        self.paused = False
        self.region = QRect()
        self.frame_size = QSize()
        self.last_frame = QImage()
        self._token = 0
        self._intent = ""
        self._started = 0.0
        self._job_settings = self.settings
        self._force = False
        self._file: Path | None = None
        self._pending_hash = ""
        self._cache: tuple[str, AnswerResult, dict] | None = None
        self._workers: dict[int, ImageEncoder] = {}
        self.capture.frame_ready.connect(self._captured)
        self.capture.failed.connect(self._fail)
        self.ai.succeeded.connect(self._answered)
        self.ai.failed.connect(self._fail)
        self.watcher = QTimer(self)
        self.watcher.setInterval(400)
        self.watcher.timeout.connect(self._watch_target)
        self.watcher.start()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.busy_changed.emit(busy)

    def _finish_file(self) -> None:
        if self._file is not None:
            path, self._file = self._file, None
            try:
                self.storage.finish_capture(path)
            except (OSError, ValueError):
                self.error.emit("任务已结束，但截图清理登记失败，请检查数据目录。")

    def _invalidate(self) -> None:
        self._token += 1
        self._intent = ""
        self.capture.cancel()
        self.ai.cancel()
        self._finish_file()
        self._set_busy(False)

    def choose_target(self, window: WindowInfo) -> None:
        self._invalidate()
        self._cache = None
        self.region = QRect()
        self.frame_size = QSize()
        self.last_frame = QImage()
        self.target = window
        self.running = True
        self.paused = False
        self.answer_cleared.emit()
        self.target_changed.emit(window.title)
        self.running_changed.emit(True)
        self.reselect_region()

    def stop(self) -> None:
        self._invalidate()
        self._cache = None
        self.running = False
        self.paused = False
        self.target = None
        self.region = QRect()
        self.frame_size = QSize()
        self.last_frame = QImage()
        self.answer_cleared.emit()
        self.status_changed.emit("已停止")
        self.target_changed.emit("尚未选择窗口")
        self.running_changed.emit(False)

    def apply_settings(self, settings: AppSettings) -> None:
        self._invalidate()
        self.settings = settings
        self._cache = None
        self.answer_cleared.emit()
        self.status_changed.emit("已暂停 · 目标最小化" if self.paused else "准备就绪" if self.running else "未启动")

    def set_region(self, rect: QRect, frame_size: QSize) -> None:
        bounds = QRect(0, 0, frame_size.width(), frame_size.height())
        if rect.width() < 40 or rect.height() < 40 or not bounds.contains(rect):
            self._fail("题区无效，请重新框选完整题目。")
            return
        self.region = QRect(rect)
        self.frame_size = QSize(frame_size)
        self._cache = None
        self.answer_cleared.emit()
        if not self.last_frame.isNull() and self.last_frame.size() == frame_size:
            self.frame_preview_changed.emit(self.last_frame, self.region)
        self.status_changed.emit("准备就绪")

    def _target_ready(self) -> bool:
        if not self.running or self.target is None:
            self.error.emit("请先选择窗口并开始运行。")
            return False
        identity = win32.window_identity(self.target.window_id)
        if identity is None or (self.target.identity is not None and identity != self.target.identity):
            self.stop()
            self.error.emit("目标窗口已关闭或身份改变，请重新选择。")
            return False
        if win32.is_minimized(self.target.window_id):
            self._pause()
            return False
        return True

    def _watch_target(self) -> None:
        if not self.running or self.target is None:
            return
        if not self._target_ready():
            return
        if self.paused:
            self.paused = False
            self._cache = None
            self.status_changed.emit("准备就绪 · 窗口已恢复" if not self.region.isEmpty() else "请重新框选题区")
            self.busy_changed.emit(False)

    def _pause(self) -> None:
        if not self.paused:
            self._invalidate()
            self._cache = None
            self.paused = True
            self.answer_cleared.emit()
            self.status_changed.emit("已暂停 · 目标最小化")
            self.busy_changed.emit(False)

    def reselect_region(self) -> None:
        if self.busy or not self._target_ready():
            return
        self._invalidate()
        self._intent = "region"
        self._set_busy(True)
        self.status_changed.emit("截图中")
        self.capture.start(self.target, self.settings.capture_timeout)

    def refresh_preview(self) -> None:
        if self.busy or not self._target_ready():
            return
        if self.region.isEmpty():
            self.reselect_region()
            return
        self._invalidate()
        self._intent = "preview"
        self._set_busy(True)
        self.status_changed.emit("刷新画面中")
        self.capture.start(self.target, self.settings.capture_timeout)

    def cancel_query(self) -> None:
        if self.busy:
            self._invalidate()
            self.answer_cleared.emit()
            self.status_changed.emit("准备就绪 · 已取消本次查询")

    def query(self, force: bool = False) -> None:
        if self.busy or not self._target_ready():
            return
        if self.region.isEmpty():
            self.reselect_region()
            return
        try:
            if not self.storage.load_key():
                self.error.emit("请先在设置页保存 API Key。")
                return
        except (OSError, ValueError):
            self.error.emit("无法读取加密 Key，请在设置页重新保存。")
            return
        self._invalidate()
        self._job_settings = replace(self.settings)
        self._force = force
        self._started = time.monotonic()
        self._intent = "query"
        self.answer_cleared.emit()
        self._set_busy(True)
        self.status_changed.emit("截图中")
        self.capture.start(self.target, self.settings.capture_timeout)

    def _captured(self, image: QImage) -> None:
        if not self.busy or not self._target_ready():
            return
        self.last_frame = image.copy()
        if self._intent == "region":
            self._intent = ""
            self._set_busy(False)
            self.status_changed.emit("请选择一道题")
            self.region_needed.emit(image)
            return
        if self._intent not in {"query", "preview"}:
            return
        if image.size() != self.frame_size:
            self._invalidate()
            self.region = QRect()
            self._cache = None
            self.answer_cleared.emit()
            self.status_changed.emit("画面尺寸变化，请重新框选")
            self.region_needed.emit(image)
            return
        cropped = image.copy(self.region)
        self.frame_preview_changed.emit(image, self.region)
        self.preview_changed.emit(cropped)
        if self._intent == "preview":
            self._intent = ""
            self._set_busy(False)
            self.status_changed.emit("准备就绪")
            return
        worker = ImageEncoder(self._token, cropped, self._job_settings)
        self._workers[self._token] = worker
        worker.signals.done.connect(self._encoded)
        worker.signals.failed.connect(self._encode_failed)
        QThreadPool.globalInstance().start(worker)

    def _encoded(self, token: int, data: bytes, mime: str) -> None:
        self._workers.pop(token, None)
        if token != self._token or not self.busy or not self._target_ready():
            return
        try:
            self._file = self.storage.save_capture(data, ".jpg" if mime == "image/jpeg" else ".png")
            values = {name: getattr(self._job_settings, name) for name in (
                "base_url", "model", "question_type", "explanation", "reasoning",
            )}
            # No credential, raw screenshot or prompt text is persisted in logs.
            fingerprint = hashlib.sha256(data + json.dumps(values, sort_keys=True).encode()).hexdigest()
            self._pending_hash = fingerprint
            if not self._force and self._cache is not None and fingerprint == self._cache[0]:
                self._complete(self._cache[1], self._cache[2], True)
                return
            key = self.storage.load_key()
            if not key:
                raise ValueError("请先在设置页保存 API Key。")
            self.status_changed.emit("查询中")
            self.ai.solve(data, mime, self._job_settings, key)
        except (ValueError, OSError) as exc:
            self._fail(str(exc) if isinstance(exc, ValueError) else "无法保存截图，请检查目录权限和剩余空间。")

    def _encode_failed(self, token: int, message: str) -> None:
        self._workers.pop(token, None)
        if token == self._token and self.busy:
            self._fail(message)

    def _answered(self, result: AnswerResult, usage: dict) -> None:
        if self.busy and self._intent == "query" and self._target_ready():
            self._complete(result, usage, False)

    def _complete(self, result: AnswerResult, usage: dict, cached: bool) -> None:
        self._finish_file()
        self._intent = ""
        self._set_busy(False)
        if result.status != "ok":
            self.status_changed.emit("请核对题目")
            self.error.emit(result.display_text)
            return
        if not cached:
            self._cache = (self._pending_hash, result, dict(usage))
        self.status_changed.emit("准备就绪")
        logging.info("query completed; cached=%s", cached)
        self.answer_ready.emit(result, usage, time.monotonic() - self._started, cached)

    def _fail(self, message: str) -> None:
        if not self.busy and not self.running:
            return
        self._invalidate()
        if self.target is not None and win32.is_minimized(self.target.window_id):
            self._pause()
        else:
            self.status_changed.emit("查询失败，可重试")
            self.error.emit(message)
