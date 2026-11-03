"""Target-relative overlay placement with per-monitor coordinate conversion."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

from PySide6.QtCore import QObject, QPoint, QRect, QSize, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from . import win32
from .controller import SessionController


def anchor_position(corner: QPoint, bounds: QRect, size: QSize, margin: int = 12) -> QPoint:
    return QPoint(
        max(bounds.left(), min(corner.x() - size.width() - margin, bounds.right() - size.width() + 1)),
        max(bounds.top(), min(corner.y() - size.height() - margin, bounds.bottom() - size.height() + 1)),
    )


def target_corner(hwnd: int) -> tuple[QPoint, QRect] | None:
    if os.name != "nt" or not win32.is_window(hwnd):
        return None

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD),
                    ("device", wintypes.WCHAR * 32)]

    user = ctypes.WinDLL("user32", use_last_error=True)
    dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowRect.restype = wintypes.BOOL
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwm.DwmGetWindowAttribute.restype = ctypes.c_long
    rect = wintypes.RECT()
    if (dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0
            or rect.right <= rect.left or rect.bottom <= rect.top):
        if not user.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    user.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user.MonitorFromPoint.restype = wintypes.HANDLE
    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user.GetMonitorInfoW.restype = wintypes.BOOL
    monitor = user.MonitorFromPoint(wintypes.POINT(rect.right - 1, rect.bottom - 1), 2)
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    if not user.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    screen = next((screen for screen in QGuiApplication.screens()
                   if screen.name().casefold() == info.device.casefold()), None)
    if screen is None:
        # Qt may expose an EDID friendly name (e.g. G75), not \\.\DISPLAY1.
        # Windows Qt retains physical monitor origins when scaling each screen.
        screen = next((screen for screen in QGuiApplication.screens()
                       if screen.geometry().topLeft() == QPoint(info.monitor.left, info.monitor.top)), None)
    if screen is None:
        return None  # Do not guess coordinates on an unknown display.
    ratio = screen.devicePixelRatio()
    origin = screen.geometry().topLeft()
    corner = QPoint(origin.x() + round((rect.right - info.monitor.left) / ratio),
                    origin.y() + round((rect.bottom - info.monitor.top) / ratio))
    return corner, screen.availableGeometry()


class OverlayFollower(QObject):
    restored = Signal()

    def __init__(self, panel: QWidget, controller: SessionController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.panel, self.controller = panel, controller
        self.suspended = False
        self._was_minimized = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)

    def start(self) -> None:
        self._was_minimized = False
        self.timer.start()
        self.refresh()

    def stop(self) -> None:
        self.timer.stop()
        self.panel.hide()

    def refresh(self, force: bool = False) -> None:
        target = self.controller.target
        if self.suspended or getattr(self.panel, "dragging", False):
            return
        if not self.controller.running or target is None or not win32.is_window(target.window_id):
            self.panel.hide()
            return
        if win32.is_minimized(target.window_id):
            self._was_minimized = True
            self.panel.hide()
            return
        if self.controller.paused:
            self.panel.hide()
            return
        if self._was_minimized:
            self._was_minimized = False
            self.restored.emit()
        positioned = False
        if self.controller.settings.overlay_mode == "target":
            placement = target_corner(target.window_id)
            if placement is not None:
                corner, bounds = placement
                self.panel.move(anchor_position(corner, bounds, self.panel.size()))
                positioned = True
        if not positioned:
            screens = QGuiApplication.screens()
            if screens and not any(screen.availableGeometry().contains(self.panel.geometry()) for screen in screens):
                screen = QGuiApplication.screenAt(self.panel.geometry().center()) or QGuiApplication.primaryScreen()
                bounds = screen.availableGeometry()
                desired_corner = self.panel.pos() + QPoint(self.panel.width() + 12, self.panel.height() + 12)
                self.panel.move(anchor_position(desired_corner, bounds, self.panel.size()))
        if not self.panel.isVisible():
            self.panel.show()
        if QGuiApplication.platformName() == "windows":
            win32.ensure_overlay_visible(int(self.panel.winId()), self.controller.settings.overlay_topmost, force)
