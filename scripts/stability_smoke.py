"""Hover stability: only our own Qt fixture windows and Qt test input."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from quiz_helper import win32
from quiz_helper.docking import OverlayFollower
from quiz_helper.models import AppSettings
from quiz_helper.storage import non_c_path
from quiz_helper.theme import stylesheet
from quiz_helper.ui import FloatingPanel


class EventCounts(QObject):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.counts = {"Show": 0, "Hide": 0, "Move": 0, "WinIdChange": 0}

    def eventFilter(self, _watched: QObject, event: QEvent) -> bool:
        if event.type().name in self.counts:
            self.counts[event.type().name] += 1
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, default=Path(".qa/v022"))
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("seconds must be positive")
    output = non_c_path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyleSheet(stylesheet("light"))
    target = QWidget()
    target.setWindowTitle("Hover stability fixture (self-owned)")
    target.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    target.resize(620, 500)
    target.move(60, 60)
    panel = FloatingPanel()
    settings = AppSettings()
    panel.apply_settings(settings)
    controller = SimpleNamespace(target=SimpleNamespace(window_id=int(target.winId())),
                                 running=True, paused=False, settings=settings)
    follower = OverlayFollower(panel, controller)
    events = EventCounts(panel)
    native = ctypes.WinDLL("user32", use_last_error=True)
    native.GetForegroundWindow.restype = wintypes.HWND
    for name in ("IsWindowVisible", "IsIconic"):
        function = getattr(native, name)
        function.argtypes = [wintypes.HWND]
        function.restype = wintypes.BOOL
    try:
        target.show()
        follower.start()
        QTest.qWait(800)
        panel.installEventFilter(events)
        foreground = native.GetForegroundWindow()
        points = ((target, QPoint(20, 20)), (panel, QPoint(2, 2)),
                  (panel.query, QPoint(10, 10)), (panel.copy, QPoint(10, 10)))
        began = time.monotonic()
        iterations = 0
        snapshots = []
        recoveries = []
        read_state = win32.overlay_needs_recovery

        def needs_recovery(hwnd: int, topmost: bool, target_hwnd: int) -> bool:
            needed = read_state(hwnd, topmost, target_hwnd)
            if needed:
                recoveries.append({"elapsed": round(time.monotonic() - began, 2),
                                   "visible": bool(native.IsWindowVisible(hwnd)),
                                   "minimized": bool(native.IsIconic(hwnd)),
                                   "foreground_changed": native.GetForegroundWindow() != foreground})
                print(json.dumps({"recovery": recoveries[-1]}), flush=True)
            return needed

        with patch.object(win32._user32, "SetWindowPos", wraps=win32._user32.SetWindowPos) as placement, \
             patch.object(win32, "overlay_needs_recovery", side_effect=needs_recovery):
            while time.monotonic() - began < args.seconds:
                widget, position = points[iterations % len(points)]
                QTest.mouseMove(widget, position)
                QTest.qWait(100)
                iterations += 1
                assert panel.isVisible(), {"elapsed": time.monotonic() - began, "events": events.counts,
                                           "target_exists": win32.is_window(controller.target.window_id),
                                           "target_minimized": win32.is_minimized(controller.target.window_id),
                                           "target_hwnd_changed": int(target.winId()) != controller.target.window_id}
                if iterations in (1, 200, 400):
                    path = output / f"hover-{iterations}.png"
                    assert panel.grab().save(str(path))
                    snapshots.append(path.name)
                if iterations % 200 == 0:
                    print(f"Hover progress: {time.monotonic() - began:.0f}s, writes={placement.call_count}", flush=True)
            assert placement.call_count == 0, placement.call_count
        assert not any(events.counts.values()), events.counts
        assert native.GetForegroundWindow() == foreground, "Overlay stole focus"
        report = {"seconds": round(time.monotonic() - began, 2), "iterations": iterations,
                  "native_zorder_writes": 0, "events": events.counts, "focus_unchanged": True,
                  "snapshots": snapshots, "scope": "self-owned Qt fixtures only"}
        (output / "hover-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
        return 0
    finally:
        panel.removeEventFilter(events)
        follower.stop()
        panel.close()
        target.close()
        app.processEvents()


if __name__ == "__main__":
    raise SystemExit(main())
