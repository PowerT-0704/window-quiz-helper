"""Native z-order regression using only two test windows; never activates the overlay."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from quiz_helper.docking import OverlayFollower
from quiz_helper.models import AppSettings
from quiz_helper.ui import FloatingPanel


def main() -> int:
    app = QApplication([])
    target = QWidget()
    target.setWindowTitle("Overlay z-order verification fixture")
    target.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    target.resize(600, 500)
    target.move(100, 100)
    panel = FloatingPanel()
    panel.apply_settings(AppSettings())
    controller = SimpleNamespace(target=SimpleNamespace(window_id=int(target.winId())),
                                 running=True, paused=False, settings=AppSettings())
    follower = OverlayFollower(panel, controller)
    native = ctypes.WinDLL("user32", use_last_error=True)
    native.WindowFromPoint.argtypes = [wintypes.POINT]
    native.WindowFromPoint.restype = wintypes.HWND
    native.GetForegroundWindow.restype = wintypes.HWND
    native.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    native.IsIconic.argtypes = [wintypes.HWND]
    try:
        target.show()
        follower.start()
        QTest.qWait(200)
        follower.timer.stop()
        target.raise_()
        QTest.qWait(550)  # Allow the automatic layer-recovery debounce to expire.
        center = panel.geometry().center()
        before = int(native.WindowFromPoint(wintypes.POINT(center.x(), center.y())) or 0)
        assert before == int(target.winId()), "Fixture did not cover the overlay"
        foreground = native.GetForegroundWindow()
        follower.refresh()
        QTest.qWait(100)
        after = int(native.WindowFromPoint(wintypes.POINT(center.x(), center.y())) or 0)
        assert after == int(panel.winId()), "Always-on-top target still covers the overlay"
        assert native.GetForegroundWindow() == foreground, "Overlay stole foreground focus"
        print("PASS overlay recovers above always-on-top target without activating", flush=True)
        panel.hide()
        follower.refresh(force=True)
        assert panel.isVisible()
        native.ShowWindow(int(panel.winId()), 7)
        assert native.IsIconic(int(panel.winId()))
        foreground = native.GetForegroundWindow()
        follower.refresh(force=True)
        assert not native.IsIconic(int(panel.winId()))
        assert native.GetForegroundWindow() == foreground
        print("PASS hidden and native-minimized overlay recovery without focus change", flush=True)
        target.showMinimized()
        QTest.qWait(100)
        follower.refresh()
        assert panel.isHidden()
        print("PASS target minimization still hides overlay", flush=True)
        print(json.dumps({"ok": True, "scope": "self-owned fixture windows only"}), flush=True)
        return 0
    finally:
        follower.stop()
        panel.close()
        target.close()
        app.processEvents()


if __name__ == "__main__":
    raise SystemExit(main())
