"""Regression checks for the v0.2 request, preview, docking and hotkeys."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, replace
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from quiz_helper.ai import build_payload
from quiz_helper.branding import ICON_PATH, application_icon
from quiz_helper.docking import OverlayFollower, anchor_position
from quiz_helper.hotkeys import HotkeyManager
from quiz_helper.models import AppSettings, parse_hotkey
from quiz_helper.preview import Locator, RegionPreview
from quiz_helper.storage import AppStorage


class V020Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_request_has_no_client_token_limit(self) -> None:
        payload = build_payload(b"fixture", "image/png", AppSettings())
        self.assertNotIn("max_tokens", payload)
        self.assertNotIn("max_completion_tokens", payload)
        self.assertNotIn("max_tokens", asdict(AppSettings()))
        self.assertEqual(AppSettings().request_timeout, 60)

    def test_legacy_settings_preserve_timeout_and_ciphertext(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            storage = AppStorage(Path(directory))
            storage.save_key("v020-placeholder-not-real")
            ciphertext = storage.key_path.read_bytes()
            payload = asdict(storage.settings)
            payload.update(max_tokens=2048, request_timeout=173)
            storage.settings_path.write_text(json.dumps(payload), encoding="utf-8")
            settings = storage.load_settings()
            self.assertEqual(settings.request_timeout, 173)
            storage.save_settings(settings)
            self.assertNotIn("max_tokens", json.loads(storage.settings_path.read_text(encoding="utf-8")))
            self.assertEqual(ciphertext, storage.key_path.read_bytes())
            self.assertEqual(settings.overlay_mode, "target")

    def test_hotkey_validation_and_canonicalization(self) -> None:
        self.assertEqual(parse_hotkey("alt+ctrl+q"), (3, ord("Q"), "Ctrl+Alt+Q"))
        self.assertEqual(parse_hotkey("F8"), (0, 0x77, "F8"))
        for value in ("Q", "Shift+A", "F12", "Win+Q", "Ctrl+Ctrl+Q", "Ctrl+A, Ctrl+B"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_hotkey(value)
        AppSettings(hotkey_enabled=False, query_hotkey="").validate()

    def test_hotkey_conflict_keeps_previous_binding(self) -> None:
        calls = []
        successful = [True]
        manager = HotkeyManager()
        manager._api = SimpleNamespace(
            RegisterHotKey=lambda *args: calls.append(("register", args)) or successful[0],
            UnregisterHotKey=lambda *args: calls.append(("unregister", args)) or True,
        )
        try:
            manager.bind("Ctrl+Alt+Q")
            previous = manager._id
            self.assertTrue(calls[0][1][2] & 0x4000)
            successful[0] = False
            with self.assertRaises(ValueError):
                manager.bind("Ctrl+Alt+W")
            self.assertEqual(previous, manager._id)
            self.assertFalse(any(item[0] == "unregister" for item in calls))
            successful[0] = True
            manager.bind("Ctrl+Alt+W")
            self.assertNotEqual(previous, manager._id)
            self.assertIn(("unregister", (None, previous)), calls)
            manager.bind("", enabled=False)
            self.assertIsNone(manager._id)
        finally:
            manager.close()
        self.assertIsNone(manager._id)

    def test_hotkey_native_message_dispatch(self) -> None:
        manager = HotkeyManager()
        manager._id = 123
        activated = []
        manager.activated.connect(lambda: activated.append(True))
        message = wintypes.MSG()
        message.message, message.wParam = 0x0312, 123
        try:
            self.assertEqual(manager.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(message)), (True, 0))
            message.wParam = 456
            self.assertEqual(manager.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(message)), (False, 0))
            self.assertEqual(activated, [True])
        finally:
            manager._id = None
            manager.close()

    def test_anchor_clamps_at_display_edges(self) -> None:
        bounds = QRect(0, 0, 1920, 1080)
        size = QSize(300, 200)
        self.assertEqual(anchor_position(QPoint(1000, 800), bounds, size), QPoint(688, 588))
        self.assertEqual(anchor_position(QPoint(100, 100), bounds, size), QPoint(0, 0))
        self.assertEqual(anchor_position(QPoint(3000, 2000), bounds, size), QPoint(1620, 880))
        self.assertEqual(anchor_position(QPoint(-800, 800), QRect(-1920, 0, 1920, 1080), size), QPoint(-1112, 588))

    def test_follower_drag_minimize_restore_and_stop(self) -> None:
        panel = QWidget()
        panel.resize(300, 200)
        panel.dragging = False
        controller = SimpleNamespace(target=SimpleNamespace(window_id=1), running=True, paused=False, settings=AppSettings())
        follower = OverlayFollower(panel, controller)
        minimized = [False]
        restored = []
        follower.restored.connect(lambda: restored.append(True))
        with patch("quiz_helper.docking.win32.is_window", return_value=True), \
             patch("quiz_helper.docking.win32.is_minimized", side_effect=lambda _hwnd: minimized[0]), \
             patch("quiz_helper.docking.target_corner", return_value=(QPoint(1000, 800), QRect(0, 0, 1920, 1080))):
            follower.start()
            self.assertEqual(panel.pos(), QPoint(688, 588))
            panel.dragging = True
            panel.move(20, 30)
            follower.refresh()
            self.assertEqual(panel.pos(), QPoint(20, 30))
            panel.dragging = False
            controller.settings = replace(controller.settings, overlay_mode="free")
            follower.refresh()
            self.assertEqual(panel.pos(), QPoint(20, 30))
            minimized[0] = True
            follower.refresh()
            self.assertFalse(panel.isVisible())
            minimized[0] = False
            follower.refresh()
            self.assertEqual(restored, [True])
            self.assertTrue(panel.isVisible())
            follower.stop()
            self.assertFalse(follower.timer.isActive())
            self.assertFalse(panel.isVisible())
        panel.close()

    def test_preview_locator_and_question_zoom(self) -> None:
        preview = RegionPreview()
        preview.resize(500, 400)
        image = QImage(1000, 600, QImage.Format.Format_RGB32)
        image.fill(0xffffff)
        region = QRect(100, 100, 400, 200)
        preview.set_frame(image, region)
        self.assertEqual(preview.image.size(), QSize(400, 200))
        self.assertEqual(preview.locator.region, region)
        preview.original()
        self.assertEqual(preview.detail.size(), QSize(400, 200))
        preview.zoom(2)
        self.assertEqual(preview.detail.size(), QSize(800, 400))
        locator = Locator()
        locator.image, locator.region = image, region
        locator.resize(500, 300)
        rendered = locator.grab().toImage()
        self.assertGreater(rendered.pixelColor(200, 120).red(), rendered.pixelColor(10, 10).red())
        locator.close()
        preview.clear()
        self.assertTrue(preview.full_image.isNull())
        self.assertTrue(preview.image.isNull())
        preview.close()

    def test_icon_contains_all_sizes_and_loads(self) -> None:
        data = ICON_PATH.read_bytes()
        self.assertEqual(struct.unpack_from("<HHH", data), (0, 1, 7))
        sizes = [struct.unpack_from("<B", data, 6 + 16 * index)[0] or 256 for index in range(7)]
        self.assertEqual(sizes, [16, 24, 32, 48, 64, 128, 256])
        self.assertFalse(application_icon().isNull())

    def test_detail_fit_updates_after_switching_tab(self) -> None:
        preview = RegionPreview()
        preview.resize(500, 400)
        image = QImage(1200, 800, QImage.Format.Format_RGB32)
        image.fill(0xffffff)
        preview.set_frame(image, image.rect())
        preview.show()
        preview.tabs.setCurrentIndex(1)
        self.app.processEvents()
        self.app.processEvents()
        bounds = preview.scroll.viewport().size()
        self.assertLessEqual(preview.detail.width(), bounds.width())
        self.assertLessEqual(preview.detail.height(), bounds.height())
        self.assertGreater(preview.detail.width(), 100)
        preview.close()

    def test_shortcut_recording_and_busy_state_do_not_submit(self) -> None:
        from quiz_helper.app import MainWindow
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            window = MainWindow(AppStorage(Path(directory)))
            try:
                window.controller.running = True
                window.controller.region = QRect(0, 0, 80, 80)
                editor = window.settings_page.controls["query_hotkey"]
                with patch.object(window.controller, "query") as query, \
                     patch.object(QApplication, "activeModalWidget", return_value=None):
                    with patch.object(QApplication, "focusWidget", return_value=editor):
                        window._hotkey_query()
                    query.assert_not_called()
                    with patch.object(QApplication, "focusWidget", return_value=None):
                        window._hotkey_query()
                        query.assert_called_once()
                        window.controller.busy = True
                        window._hotkey_query()
                    query.assert_called_once()
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
