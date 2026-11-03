"""One-shot, window-isolated Windows Graphics Capture via Qt Multimedia."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import sys

# These are process-local Qt backend choices, not persistent environment changes.
# Set them before the first multimedia integration is created. No desktop fallback.
os.environ["QT_MEDIA_BACKEND"] = "ffmpeg"
os.environ["QT_WINDOW_CAPTURE_BACKEND"] = "uwp"

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QWindow
from PySide6.QtMultimedia import (
    QCapturableWindow,
    QMediaCaptureSession,
    QVideoFrame,
    QVideoSink,
    QWindowCapture,
)

from . import win32


@dataclass
class WindowInfo:
    window_id: int
    title: str
    capturable: object
    foreign_window: QWindow | None = field(default=None, repr=False, compare=False)
    identity: tuple[int, int, int] | None = field(default=None, repr=False)


class CaptureService(QObject):
    """Capture one fresh window frame and release native capture resources.

    Public methods must be called on the Qt application thread. The returned
    QImage owns a detached copy and is safe for later worker-thread encoding.
    """

    frame_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._generation = 0
        self._window: WindowInfo | None = None
        self._capture: QWindowCapture | None = None
        self._session: QMediaCaptureSession | None = None
        self._sink: QVideoSink | None = None
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(lambda: self._fail("窗口截图超时，请检查窗口是否可捕获。"))
        self._watcher = QTimer(self)
        self._watcher.setInterval(100)
        self._watcher.timeout.connect(self._check_target)

    @property
    def is_busy(self) -> bool:
        return self._busy

    def list_windows(self) -> list[WindowInfo]:
        """Create unambiguous HWND-backed capture items, including duplicate titles.

        QCapturableWindow exposes no native ID getter. Qt 6.10+ can construct an
        item from a foreign QWindow. The wrapper is never shown, reparented,
        resized or otherwise used to manipulate the target application.
        """
        windows: list[WindowInfo] = []
        for hwnd, title in win32.list_window_handles():
            foreign = QWindow.fromWinId(hwnd)
            if foreign is None:
                continue
            item = QCapturableWindow(foreign)
            if not item.isValid():
                foreign.deleteLater()
                continue
            windows.append(WindowInfo(hwnd, title, item, foreign, win32.window_identity(hwnd)))
        return windows

    def start(self, window: WindowInfo, timeout_seconds: int = 5) -> None:
        """Start a new one-shot capture; cancel any previous operation silently."""
        self.cancel()
        self._busy = True
        self._window = window
        if sys.platform != "win32":
            self._fail("窗口捕获仅支持 Windows 10 1903 及以上或 Windows 11。")
            return
        if not isinstance(window.capturable, QCapturableWindow):
            self._fail("窗口捕获信息无效，请重新选择窗口。")
            return
        if not self._check_target():
            return
        if not window.capturable.isValid():
            self._fail("目标窗口已失效，请重新选择窗口。")
            return
        generation = self._generation
        capture = QWindowCapture(self)
        session = QMediaCaptureSession(self)
        sink = QVideoSink(self)
        self._capture, self._session, self._sink = capture, session, sink
        sink.videoFrameChanged.connect(lambda frame: self._on_frame(frame, generation))
        capture.errorOccurred.connect(lambda _error, _description: self._on_error(generation))
        session.setWindowCapture(capture)
        session.setVideoSink(sink)
        capture.setWindow(window.capturable)
        if not self._busy:
            return
        if hasattr(capture, "setMaximumFrameRate"):
            capture.setMaximumFrameRate(10.0)
        self._deadline.start(max(1, int(timeout_seconds)) * 1000)
        self._watcher.start()
        capture.start()
        # Some Qt/driver combinations miss the initial WGC frame of a static
        # surface. Request asynchronous repaint once, without focus/state/input
        # changes. The generation guard prevents touching a superseded target.
        QTimer.singleShot(250, lambda: self._request_initial_frame(generation))

    def cancel(self) -> None:
        """Invalidate queued callbacks before stopping and releasing resources."""
        self._generation += 1
        self._busy = False
        self._deadline.stop()
        self._watcher.stop()
        capture, session, sink = self._capture, self._session, self._sink
        self._capture = self._session = self._sink = None
        self._window = None
        if capture is not None:
            capture.blockSignals(True)
        if sink is not None:
            sink.blockSignals(True)
        if capture is not None:
            capture.stop()
        if session is not None:
            session.setVideoSink(None)
            session.setWindowCapture(None)
        for resource in (sink, session, capture):
            if resource is not None:
                resource.deleteLater()

    @Slot()
    def _check_target(self) -> bool:
        window = self._window
        if not self._busy or window is None:
            return False
        identity = win32.window_identity(window.window_id)
        if identity is None or (window.identity is not None and identity != window.identity):
            self._fail("目标窗口已关闭或身份已改变，请重新选择窗口。")
            return False
        if win32.is_minimized(window.window_id):
            self._fail("目标窗口已最小化，查询已暂停。恢复窗口后请重新查询。")
            return False
        return True

    def _on_frame(self, frame: QVideoFrame, generation: int) -> None:
        if not self._busy or generation != self._generation or not frame.isValid():
            return
        if not self._check_target():
            return
        image: QImage = frame.toImage()
        if image.isNull() or image.width() <= 1 or image.height() <= 1:
            return
        # Fully blank/transparent frames frequently signal protected content or
        # an unavailable window surface; never silently upload them to the AI.
        probe = image.scaled(32, 32).convertToFormat(QImage.Format.Format_RGBA8888)
        raw = bytes(probe.constBits())
        visible = any(raw[offset + 3] and any(raw[offset:offset + 3]) for offset in range(0, len(raw), 4))
        if not visible:
            self._fail("窗口返回空白画面，可能受截图保护或尚未完成渲染。")
            return
        detached = image.copy()
        self.cancel()
        self.frame_ready.emit(detached)

    def _on_error(self, generation: int) -> None:
        if self._busy and generation == self._generation:
            self._fail("无法捕获该窗口，请检查系统捕获权限、窗口状态及截图保护。")

    def _request_initial_frame(self, generation: int) -> None:
        if self._busy and generation == self._generation and self._check_target():
            assert self._window is not None
            win32.request_redraw(self._window.window_id)

    def _fail(self, message: str) -> None:
        if not self._busy:
            return
        self.cancel()
        self.failed.emit(message)
