"""Global shortcuts through RegisterHotKey; no keyboard hook or injection."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal

from .models import parse_hotkey


class HotkeyManager(QObject, QAbstractNativeEventFilter):
    activated = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._id: int | None = None
        self._shortcut = ""
        self._api = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
        if self._api is not None:
            self._api.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            self._api.RegisterHotKey.restype = wintypes.BOOL
            self._api.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            self._api.UnregisterHotKey.restype = wintypes.BOOL
        QCoreApplication.instance().installNativeEventFilter(self)

    def bind(self, shortcut: str, enabled: bool = True) -> None:
        if not enabled:
            self.release()
            return
        modifiers, key, canonical = parse_hotkey(shortcut)
        if self._id is not None and self._shortcut == canonical:
            return
        if self._api is None:
            raise ValueError("全局快捷键仅支持 Windows。")
        candidate = 0x6211 if self._id == 0x6210 else 0x6210
        if not self._api.RegisterHotKey(None, candidate, modifiers | 0x4000, key):
            raise ValueError(f"快捷键 {canonical} 已被占用或无法注册，请选择其他组合；原快捷键保持不变。")
        old_id = self._id
        self._id, self._shortcut = candidate, canonical
        if old_id is not None:
            self._api.UnregisterHotKey(None, old_id)

    def release(self) -> None:
        if self._id is not None and self._api is not None:
            self._api.UnregisterHotKey(None, self._id)
        self._id = None
        self._shortcut = ""

    def close(self) -> None:
        self.release()
        application = QCoreApplication.instance()
        if application is not None:
            application.removeNativeEventFilter(self)

    def nativeEventFilter(self, event_type: object, message: object) -> tuple[bool, int]:
        if self._id is not None and bytes(event_type) in {b"windows_generic_MSG", b"windows_dispatcher_MSG"}:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == self._id:
                self.activated.emit()
                return True, 0
        return False, 0
