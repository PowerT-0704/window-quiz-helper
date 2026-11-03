"""Native no-op, drag threshold, icon contents and DPI math regressions."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from quiz_helper import win32
from quiz_helper.branding import ICON_PATH, icon_image
from quiz_helper.docking import OverlayFollower, anchor_position, logical_corner
from quiz_helper.models import AppSettings
from quiz_helper.ui import FloatingPanel


class V022Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.objects: list[QObject] = []

    def tearDown(self) -> None:
        for obj in reversed(self.objects):
            if isinstance(obj, OverlayFollower):
                obj.stop()
            if isinstance(obj, QWidget):
                obj.close()
            obj.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_native_stable_topmost_does_not_write(self) -> None:
        with patch.object(win32, "is_window", return_value=True), patch.object(win32, "_user32") as native:
            native.IsWindowVisible.return_value = True
            native.IsIconic.return_value = False
            native.GetWindowLongPtrW.return_value = 0x8

            def own_pid(_hwnd: int, output: object) -> int:
                ctypes.cast(output, ctypes.POINTER(wintypes.DWORD)).contents.value = os.getpid()
                return 1

            native.GetWindowThreadProcessId.side_effect = own_pid
            self.assertFalse(win32.overlay_needs_recovery(1, True))
            self.assertTrue(win32.ensure_overlay_visible(1, True))
            native.SetWindowPos.assert_not_called()
            native.ShowWindow.assert_not_called()

    def test_only_overlapping_target_above_panel_needs_recovery(self) -> None:
        with patch.object(win32, "is_window", return_value=True), patch.object(win32, "_user32") as native:
            native.IsWindowVisible.return_value = True
            native.IsIconic.return_value = False
            native.GetWindowLongPtrW.return_value = 0x8
            target_left = [50]

            def rect(hwnd: int, output: object) -> bool:
                value = ctypes.cast(output, ctypes.POINTER(wintypes.RECT)).contents
                value.left, value.top = (0 if hwnd == 1 else target_left[0]), 0
                value.right, value.bottom = value.left + 100, 100
                return True

            native.GetWindowRect.side_effect = rect
            native.EnumWindows.side_effect = lambda callback, arg: callback(2, arg)
            self.assertTrue(win32.overlay_needs_recovery(1, True, 2))
            native.EnumWindows.side_effect = lambda callback, arg: callback(1, arg)
            self.assertFalse(win32.overlay_needs_recovery(1, True, 2))
            target_left[0] = 1000
            native.EnumWindows.reset_mock()
            self.assertFalse(win32.overlay_needs_recovery(1, True, 2))
            native.EnumWindows.assert_not_called()
            native.SetWindowPos.assert_not_called()

    def test_follower_noop_and_recovery_debounce(self) -> None:
        panel = QWidget()
        self.objects.append(panel)
        panel.resize(300, 200)
        panel.move(100, 100)
        panel.show()
        controller = SimpleNamespace(target=SimpleNamespace(window_id=123), running=True,
                                     paused=False, settings=AppSettings())
        follower = OverlayFollower(panel, controller)
        self.objects.append(follower)
        corner = panel.pos() + QPoint(panel.width() + 12, panel.height() + 12)
        with patch("quiz_helper.docking.win32.is_window", return_value=True), \
             patch("quiz_helper.docking.win32.is_minimized", return_value=False), \
             patch("quiz_helper.docking.target_corner", return_value=(corner, QRect(0, 0, 1000, 800))), \
             patch("quiz_helper.docking.QGuiApplication.platformName", return_value="windows"), \
             patch("quiz_helper.docking.time.monotonic", return_value=10.0) as clock, \
             patch("quiz_helper.docking.win32.overlay_needs_recovery", return_value=False) as needs, \
             patch("quiz_helper.docking.win32.ensure_overlay_visible", return_value=True) as ensure, \
             patch.object(panel, "move", wraps=panel.move) as move:
            for _ in range(20):
                follower.refresh()
            move.assert_not_called()
            ensure.assert_not_called()
            needs.return_value = True
            follower.refresh()
            clock.return_value = 10.1
            follower.refresh()
            self.assertEqual(ensure.call_count, 1)
            clock.return_value = 10.5
            follower.refresh()
            self.assertEqual(ensure.call_count, 2)
            follower.refresh(force=True)
            self.assertEqual(ensure.call_count, 3)

    def test_click_and_small_motion_do_not_detach_but_drag_does(self) -> None:
        panel = FloatingPanel()
        self.objects.append(panel)
        panel.move(100, 100)
        panel.show()
        moved: list[object] = []
        panel.moved.connect(moved.append)

        def send(kind: QEvent.Type, position: QPoint, button: Qt.MouseButton, buttons: Qt.MouseButton) -> None:
            QCoreApplication.sendEvent(panel, QMouseEvent(kind, QPointF(position - panel.pos()),
                                                         QPointF(position), button, buttons, Qt.KeyboardModifier.NoModifier))

        origin = panel.pos() + QPoint(2, 2)
        send(QEvent.Type.MouseButtonPress, origin, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseMove, origin + QPoint(1, 0), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseButtonRelease, origin, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        self.assertFalse(moved)
        self.assertFalse(panel.dragging)
        send(QEvent.Type.MouseButtonPress, origin, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        destination = origin + QPoint(QApplication.startDragDistance() + 20, 15)
        send(QEvent.Type.MouseMove, destination, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        self.assertTrue(panel.dragging)
        send(QEvent.Type.MouseButtonRelease, destination, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0], [panel.x(), panel.y()])
        self.assertFalse(panel.dragging)

    def test_identical_visual_settings_preserve_native_window(self) -> None:
        panel = FloatingPanel()
        self.objects.append(panel)
        panel.apply_settings(AppSettings())
        panel.show()
        with patch.object(panel, "setWindowFlag") as flags, patch.object(panel, "setWindowOpacity") as opacity:
            panel.apply_settings(AppSettings())
            flags.assert_not_called()
            opacity.assert_not_called()
            self.assertTrue(panel.isVisible())

    def test_ico_layers_contain_scan_and_check_not_font_box(self) -> None:
        data = ICON_PATH.read_bytes()
        self.assertEqual(struct.unpack_from("<HHH", data), (0, 1, 7))
        for index, size in enumerate((16, 24, 32, 48, 64, 128, 256)):
            entry = struct.unpack_from("<BBBBHHII", data, 6 + index * 16)
            image = QImage.fromData(data[entry[7]:entry[7] + entry[6]])
            self.assertEqual(image.size(), QSize(size, size))
            self.assertEqual(image, icon_image(size))
            # A hollow missing-glyph box has no center tick. Sample an area
            # along the descending check stroke with pixel-size tolerance.
            pixels = [image.pixelColor(x, y) for x in range(int(size * .41), int(size * .49) + 1)
                      for y in range(int(size * .50), int(size * .59) + 1)]
            self.assertTrue(any(p.red() > 220 and p.green() > 220 and p.blue() > 220 for p in pixels), size)
            self.assertLess(image.pixelColor(0, 0).alpha(), 40)

    def test_scaled_corner_math_and_negative_display(self) -> None:
        for ratio, expected in ((1.0, QPoint(-720, 900)), (1.5, QPoint(-1120, 600)), (2.0, QPoint(-1320, 450))):
            corner = logical_corner(QPoint(-720, 900), QPoint(-1920, 0), QPoint(-1920, 0), ratio)
            self.assertEqual(corner, expected)
            bounds = QRect(-1920, 0, 1920, 1080)
            position = anchor_position(corner, bounds, QSize(300, 200))
            self.assertEqual(position, corner - QPoint(312, 212))


if __name__ == "__main__":
    unittest.main()
