"""Missing-overlay regressions; use our own windows and synthetic metadata."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import TypeVar
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from quiz_helper.app import MainWindow
from quiz_helper.docking import OverlayFollower
from quiz_helper.models import AppSettings
from quiz_helper.storage import AppStorage
from quiz_helper import win32

QtObject = TypeVar("QtObject", bound=QObject)


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.objects: list[QObject] = []

    def own(self, value: QtObject) -> QtObject:
        self.objects.append(value)
        return value

    def tearDown(self) -> None:
        # Drain native Qt deletion while QApplication is alive. Leaving the
        # unparented follower/timer cycles to interpreter shutdown is unsafe.
        for value in reversed(self.objects):
            if isinstance(value, OverlayFollower):
                value.stop()
            elif isinstance(value, QWidget):
                value.close()
            value.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.objects.clear()

    def test_visible_panel_still_reasserts_native_layer(self) -> None:
        panel = self.own(QWidget())
        panel.resize(300, 200)
        panel.show()
        controller = SimpleNamespace(target=SimpleNamespace(window_id=123), running=True,
                                     paused=False, settings=AppSettings())
        follower = self.own(OverlayFollower(panel, controller))
        with patch("quiz_helper.docking.win32.is_window", return_value=True), \
             patch("quiz_helper.docking.win32.is_minimized", return_value=False), \
             patch("quiz_helper.docking.target_corner", return_value=(QPoint(700, 500), QRect(0, 0, 1000, 800))), \
             patch("quiz_helper.docking.QGuiApplication.platformName", return_value="windows"), \
             patch("quiz_helper.docking.win32.ensure_overlay_visible", return_value=True) as ensure:
            follower.refresh()
            follower.refresh(force=True)
            self.assertEqual(ensure.call_count, 2)
            self.assertEqual(ensure.call_args.args, (int(panel.winId()), True, True))
        follower.stop()
        panel.close()

    def test_unavailable_target_position_recovers_offscreen_panel(self) -> None:
        panel = self.own(QWidget())
        panel.resize(300, 200)
        panel.move(-100000, -100000)
        controller = SimpleNamespace(target=SimpleNamespace(window_id=123), running=True,
                                     paused=False, settings=AppSettings())
        follower = self.own(OverlayFollower(panel, controller))
        with patch("quiz_helper.docking.win32.is_window", return_value=True), \
             patch("quiz_helper.docking.win32.is_minimized", return_value=False), \
             patch("quiz_helper.docking.target_corner", return_value=None):
            follower.refresh()
            self.assertTrue(panel.isVisible())
            self.assertTrue(any(screen.availableGeometry().intersects(panel.geometry()) for screen in self.app.screens()))
        follower.stop()
        panel.close()

    def test_native_placement_never_changes_foreign_process_window(self) -> None:
        with patch.object(win32, "is_window", return_value=True), \
             patch.object(win32, "_user32") as native:
            def foreign_pid(_hwnd: int, output: object) -> int:
                ctypes.cast(output, ctypes.POINTER(wintypes.DWORD)).contents.value = os.getpid() + 1
                return 1
            native.GetWindowThreadProcessId.side_effect = foreign_pid
            self.assertFalse(win32.ensure_overlay_visible(123, True, True))
            native.SetWindowPos.assert_not_called()
            native.ShowWindow.assert_not_called()

    def test_native_restore_uses_nonactivating_flags(self) -> None:
        with patch.object(win32, "is_window", return_value=True), \
             patch.object(win32, "_user32") as native:
            def own_pid(_hwnd: int, output: object) -> int:
                ctypes.cast(output, ctypes.POINTER(wintypes.DWORD)).contents.value = os.getpid()
                return 1
            native.GetWindowThreadProcessId.side_effect = own_pid
            native.IsWindowVisible.return_value = False
            native.IsIconic.return_value = True
            native.SetWindowPos.return_value = True
            self.assertTrue(win32.ensure_overlay_visible(123, True))
            native.ShowWindow.assert_called_once_with(123, 4)
            self.assertTrue(native.SetWindowPos.call_args.args[-1] & 0x10)
            self.assertEqual(native.SetWindowPos.call_args.args[1], -1)

    def test_home_reveal_button_retries_without_query(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            window = self.own(MainWindow(AppStorage(Path(directory))))
            self.own(window.overlay)
            try:
                window.controller.running = True
                window._update_actions()
                with patch.object(window.follower, "refresh") as refresh, \
                     patch.object(window.controller, "query") as query:
                    window.home.overlay_button.click()
                    refresh.assert_called_once_with(force=True)
                    query.assert_not_called()
            finally:
                window.close()

    def test_crop_error_cannot_leave_overlay_following_suspended(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            window = self.own(MainWindow(AppStorage(Path(directory))))
            self.own(window.overlay)
            try:
                window.controller.running = True
                image = QImage(100, 100, QImage.Format.Format_RGB32)
                with patch("quiz_helper.app.CropDialog.exec", side_effect=RuntimeError("fixture")), \
                     patch.object(window.follower, "refresh") as refresh:
                    with self.assertRaises(RuntimeError):
                        window._choose_region(image)
                    self.assertFalse(window.follower.suspended)
                    refresh.assert_called_once()
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
