"""Capture guards and stale-callback checks without manipulating user windows."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QCapturableWindow, QVideoFrame

from quiz_helper.capture import CaptureService, WindowInfo
from quiz_helper import win32


class CaptureGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self.service = CaptureService()
        self.errors: list[str] = []
        self.frames: list[QImage] = []
        self.service.failed.connect(self.errors.append)
        self.service.frame_ready.connect(self.frames.append)

    def tearDown(self) -> None:
        self.service.cancel()

    def prepare_target(self) -> None:
        self.service._window = WindowInfo(123, "fixture", QCapturableWindow(), identity=(7, 8, 9))
        self.service._busy = True

    def test_invalid_hwnd_has_no_identity(self) -> None:
        self.assertFalse(win32.is_window(0))
        self.assertFalse(win32.is_minimized(0))
        self.assertIsNone(win32.window_identity(0))

    def test_minimized_target_fails_without_frame(self) -> None:
        self.prepare_target()
        with patch("quiz_helper.win32.window_identity", return_value=(7, 8, 9)), patch(
            "quiz_helper.win32.is_minimized", return_value=True
        ):
            self.assertFalse(self.service._check_target())
        self.assertIn("最小化", self.errors[0])
        self.assertFalse(self.service.is_busy)
        self.assertEqual(self.frames, [])

    def test_reused_hwnd_rejects_changed_process_identity(self) -> None:
        self.prepare_target()
        with patch("quiz_helper.win32.window_identity", return_value=(77, 88, 99)):
            self.assertFalse(self.service._check_target())
        self.assertIn("身份", self.errors[0])

    def test_closed_target_fails(self) -> None:
        self.prepare_target()
        with patch("quiz_helper.win32.window_identity", return_value=None):
            self.assertFalse(self.service._check_target())
        self.assertFalse(self.service.is_busy)

    def test_cancel_suppresses_late_error_and_frame(self) -> None:
        self.prepare_target()
        generation = self.service._generation
        self.service.cancel()
        self.service._on_error(generation)
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("green"))
        self.service._on_frame(QVideoFrame(image), generation)
        self.assertEqual(self.errors, [])
        self.assertEqual(self.frames, [])

    def test_delayed_repaint_is_only_for_current_nonminimized_target(self) -> None:
        self.prepare_target()
        generation = self.service._generation
        with patch("quiz_helper.win32.window_identity", return_value=(7, 8, 9)), patch(
            "quiz_helper.win32.is_minimized", return_value=False
        ), patch("quiz_helper.win32.request_redraw") as redraw:
            self.service._request_initial_frame(generation)
            redraw.assert_called_once_with(123)
            self.service.cancel()
            self.service._request_initial_frame(generation)
            redraw.assert_called_once_with(123)

    def test_success_detaches_image_and_completes_only_once(self) -> None:
        self.prepare_target()
        generation = self.service._generation
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("green"))
        frame = QVideoFrame(image)
        with patch("quiz_helper.win32.window_identity", return_value=(7, 8, 9)), patch(
            "quiz_helper.win32.is_minimized", return_value=False
        ):
            self.service._on_frame(frame, generation)
            self.service._on_frame(frame, generation)
        self.assertEqual(len(self.frames), 1)
        self.assertFalse(self.service.is_busy)
        image.fill(QColor("red"))
        self.assertEqual(self.frames[0].pixelColor(0, 0), QColor("green"))

    def test_black_frame_is_not_uploaded(self) -> None:
        self.prepare_target()
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("black"))
        with patch("quiz_helper.win32.window_identity", return_value=(7, 8, 9)), patch(
            "quiz_helper.win32.is_minimized", return_value=False
        ):
            self.service._on_frame(QVideoFrame(image), self.service._generation)
        self.assertEqual(self.frames, [])
        self.assertIn("空白", self.errors[0])


if __name__ == "__main__":
    unittest.main()
