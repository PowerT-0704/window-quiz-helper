"""Session integration tests with fake capture/network and real image encoding."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, QRect, QSize, QThreadPool, QTimer, QEventLoop, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from quiz_helper.capture import WindowInfo
from quiz_helper.controller import SessionController
from quiz_helper.models import AnswerResult
from quiz_helper.storage import AppStorage


class FakeCapture(QObject):
    frame_ready = Signal(object)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[WindowInfo, int]] = []
        self.cancel_count = 0
        self.is_busy = False

    def start(self, target: WindowInfo, timeout_seconds: int = 5) -> None:
        self.calls.append((target, timeout_seconds))
        self.is_busy = True

    def cancel(self) -> None:
        self.cancel_count += 1
        self.is_busy = False

    def deliver(self, image: QImage) -> None:
        self.is_busy = False
        self.frame_ready.emit(image)


class FakeAI(QObject):
    succeeded = Signal(object, object)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[bytes, str, object, str]] = []
        self.cancel_count = 0
        self.is_busy = False

    def solve(self, image: bytes, mime: str, settings: object, key: str) -> None:
        self.calls.append((image, mime, settings, key))
        self.is_busy = True

    def cancel(self) -> None:
        self.cancel_count += 1
        self.is_busy = False

    def answer(self, result: AnswerResult | None = None) -> None:
        self.is_busy = False
        self.succeeded.emit(
            result or AnswerResult("ok", "single", ("A",)),
            {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        )


class SessionControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="quiz-test-session-", dir=Path.cwd())
        self.addCleanup(self.directory.cleanup)
        self.storage = AppStorage(Path(self.directory.name))
        self.storage.save_key("controller-fixture-not-a-real-key")
        self.capture = FakeCapture()
        self.ai = FakeAI()
        self.minimized = False
        self.identity: tuple[int, int, int] | None = (31, 42, 53)
        self.identity_patch = patch(
            "quiz_helper.controller.win32.window_identity", side_effect=lambda _hwnd: self.identity
        )
        self.minimize_patch = patch(
            "quiz_helper.controller.win32.is_minimized", side_effect=lambda _hwnd: self.minimized
        )
        self.identity_patch.start()
        self.minimize_patch.start()
        self.addCleanup(self.identity_patch.stop)
        self.addCleanup(self.minimize_patch.stop)
        self.controller = SessionController(self.storage, capture=self.capture, ai=self.ai)
        self.answers: list[tuple[object, object, float, bool]] = []
        self.errors: list[str] = []
        self.regions: list[QImage] = []
        self.previews: list[QImage] = []
        self.controller.answer_ready.connect(lambda *values: self.answers.append(values))
        self.metrics = []
        self.controller.metrics_ready.connect(self.metrics.append)
        self.controller.error.connect(self.errors.append)
        self.controller.region_needed.connect(self.regions.append)
        self.controller.preview_changed.connect(self.previews.append)
        self.target = WindowInfo(12345, "Synthetic target", object(), identity=self.identity)
        self.image = QImage(240, 180, QImage.Format.Format_RGB32)
        self.image.fill(QColor("#3875d7"))

    def tearDown(self) -> None:
        self.controller.stop()
        self.controller.watcher.stop()
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()
        self.controller.deleteLater()
        self.app.processEvents()

    def wait_for(self, condition: Callable[[], bool], timeout_ms: int = 2000) -> None:
        if condition():
            return
        loop = QEventLoop()
        poll = QTimer()
        deadline = QTimer()
        deadline.setSingleShot(True)
        poll.setInterval(5)
        poll.timeout.connect(lambda: loop.quit() if condition() else None)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(timeout_ms)
        loop.exec()
        poll.stop()
        deadline.stop()
        self.assertTrue(condition(), "controller condition did not become true")

    def prepare_region(self) -> None:
        self.controller.choose_target(self.target)
        self.assertTrue(self.controller.running)
        self.assertTrue(self.controller.busy)
        self.capture.deliver(self.image.copy())
        self.assertEqual(len(self.regions), 1)
        self.controller.set_region(QRect(20, 20, 120, 80), self.image.size())
        self.assertFalse(self.controller.busy)

    def test_refresh_updates_full_preview_without_ai_or_disk_capture(self) -> None:
        self.prepare_region()
        frames = []
        self.controller.frame_preview_changed.connect(lambda image, rect: frames.append((image, rect)))
        self.controller.refresh_preview()
        self.capture.deliver(self.image.copy())
        self.assertFalse(self.controller.busy)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][0].size(), self.image.size())
        self.assertEqual(frames[0][1], self.controller.region)
        self.assertFalse(self.ai.calls)
        self.assertEqual(self.storage.capture_usage(), (0, 0))

    def test_cancel_query_preserves_target_region_and_suppresses_answer(self) -> None:
        self.prepare_region()
        self.start_query()
        region = QRect(self.controller.region)
        self.controller.cancel_query()
        self.ai.answer()
        self.assertTrue(self.controller.running)
        self.assertIs(self.controller.target, self.target)
        self.assertEqual(self.controller.region, region)
        self.assertFalse(self.controller.busy)
        self.assertFalse(self.answers)

    def start_query(self) -> None:
        self.controller.query()
        self.capture.deliver(self.image.copy())
        self.wait_for(lambda: bool(self.ai.calls))

    def test_one_query_encodes_only_region_and_completes_file(self) -> None:
        self.prepare_region()
        self.start_query()
        data, mime, _settings, key = self.ai.calls[0]
        self.assertEqual(mime, "image/png")
        self.assertEqual(QImage.fromData(data).size(), QSize(120, 80))
        self.assertEqual(key, "controller-fixture-not-a-real-key")
        self.assertEqual(self.previews[0].size(), QSize(120, 80))
        self.ai.answer()
        self.assertFalse(self.controller.busy)
        self.assertEqual(len(self.answers), 1)
        self.assertEqual(self.answers[0][0].display_text, "A")
        self.assertFalse(self.answers[0][3])
        self.assertIsNone(self.controller._file)

    def test_duplicate_picture_uses_memory_cache_and_force_bypasses_it(self) -> None:
        self.prepare_region()
        self.start_query()
        self.ai.answer()
        self.controller.query()
        self.capture.deliver(self.image.copy())
        self.wait_for(lambda: len(self.answers) == 2)
        self.assertEqual(len(self.ai.calls), 1)
        self.assertTrue(self.answers[1][3])
        self.controller.query(force=True)
        self.capture.deliver(self.image.copy())
        self.wait_for(lambda: len(self.ai.calls) == 2)
        self.assertTrue(self.controller.busy)

    def test_moving_overlay_does_not_charge_for_same_picture_again(self) -> None:
        self.prepare_region()
        self.start_query()
        self.ai.answer()
        settings = replace(self.controller.settings, overlay_position=[100, 200])
        self.storage.save_settings(settings)
        self.controller.settings = settings
        self.controller.query()
        self.capture.deliver(self.image.copy())
        self.wait_for(lambda: len(self.answers) == 2)
        self.assertEqual(len(self.ai.calls), 1)
        self.assertTrue(self.answers[-1][3])

    def test_resize_requests_new_region_without_sending_to_ai(self) -> None:
        self.prepare_region()
        self.controller.query()
        resized = QImage(300, 200, QImage.Format.Format_RGB32)
        resized.fill(QColor("green"))
        self.capture.deliver(resized)
        self.assertFalse(self.controller.busy)
        self.assertTrue(self.controller.region.isEmpty())
        self.assertEqual(self.regions[-1].size(), resized.size())
        self.assertEqual(self.ai.calls, [])

    def test_accepting_new_region_clears_answer_from_previous_region(self) -> None:
        self.prepare_region()
        self.start_query()
        self.ai.answer()
        cleared: list[bool] = []
        self.controller.answer_cleared.connect(lambda: cleared.append(True))
        self.controller.reselect_region()
        self.capture.deliver(self.image.copy())
        self.controller.set_region(QRect(60, 30, 100, 80), self.image.size())
        self.assertTrue(cleared, "old answer must not remain beside a new question region")
        self.assertIsNone(self.controller._cache)

    def test_worker_completion_after_stop_cannot_save_or_send(self) -> None:
        self.prepare_region()
        self.controller.query()
        self.capture.deliver(self.image.copy())
        self.controller.stop()
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()
        self.assertFalse(self.controller.running)
        self.assertFalse(self.controller.busy)
        self.assertEqual(self.ai.calls, [])
        self.assertEqual(self.storage.capture_usage(), (0, 0))
        self.assertEqual(self.answers, [])

    def test_minimize_cancels_request_and_resume_requires_fresh_capture(self) -> None:
        self.prepare_region()
        self.start_query()
        previous_cancels = self.ai.cancel_count
        self.minimized = True
        self.controller._watch_target()
        self.assertTrue(self.controller.paused)
        self.assertFalse(self.controller.busy)
        self.assertGreater(self.ai.cancel_count, previous_cancels)
        self.ai.answer()
        self.assertEqual(self.answers, [])
        self.minimized = False
        self.controller._watch_target()
        self.assertFalse(self.controller.paused)
        before = len(self.capture.calls)
        self.controller.query()
        self.assertEqual(len(self.capture.calls), before + 1)
        self.assertEqual(len(self.ai.calls), 1)

    def test_settings_change_invalidates_pending_worker_and_cache(self) -> None:
        self.prepare_region()
        self.controller.query()
        self.capture.deliver(self.image.copy())
        self.controller.apply_settings(replace(self.controller.settings, reasoning="high"))
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()
        self.assertFalse(self.controller.busy)
        self.assertEqual(self.ai.calls, [])
        self.assertEqual(self.answers, [])
        self.assertIsNone(self.controller._cache)
        self.assertEqual(self.controller.settings.reasoning, "high")

    def test_closed_target_and_stop_suppress_pending_result(self) -> None:
        self.prepare_region()
        self.start_query()
        self.identity = None
        self.controller._watch_target()
        self.assertFalse(self.controller.running)
        self.ai.answer()
        self.assertEqual(self.answers, [])
        self.assertTrue(any("关闭" in message for message in self.errors))

    def test_second_click_while_busy_does_not_start_another_capture(self) -> None:
        self.prepare_region()
        self.controller.query()
        captures = len(self.capture.calls)
        self.controller.query()
        self.assertEqual(len(self.capture.calls), captures)

    def test_invalid_or_uncertain_answer_is_not_displayed_or_cached(self) -> None:
        self.prepare_region()
        self.start_query()
        self.ai.answer(AnswerResult("uncertain", "single", ()))
        self.assertEqual(self.answers, [])
        self.assertIsNone(self.controller._cache)
        self.assertTrue(any("无法确定" in message for message in self.errors))

    def test_missing_key_does_not_start_query(self) -> None:
        self.prepare_region()
        self.storage.delete_key()
        captures = len(self.capture.calls)
        self.controller.query()
        self.assertEqual(len(self.capture.calls), captures)
        self.assertFalse(self.controller.busy)
        self.assertTrue(any("Key" in message for message in self.errors))

    def test_stage_metrics_and_cache_never_reuse_network_duration(self) -> None:
        self.prepare_region()
        self.start_query()
        self.ai.answer()
        metrics = self.metrics[-1]
        self.assertFalse(metrics.cached)
        durations = [metrics.capture_s, metrics.encode_s, metrics.prepare_s, metrics.request_s]
        self.assertTrue(all(value >= 0 for value in durations))
        self.assertGreaterEqual(metrics.total_s, sum(durations))
        self.assertEqual(metrics.image_bytes, len(self.ai.calls[0][0]))
        self.controller.query()
        self.capture.deliver(self.image.copy())
        self.wait_for(lambda: len(self.metrics) == 2)
        self.assertTrue(self.metrics[-1].cached)
        self.assertEqual(self.metrics[-1].request_s, 0)
        self.assertIn("未调用接口", self.metrics[-1].tooltip())

    def test_cancelled_query_cannot_publish_metrics(self) -> None:
        self.prepare_region()
        self.start_query()
        self.controller.cancel_query()
        self.ai.answer()
        self.assertFalse(self.metrics)


if __name__ == "__main__":
    unittest.main()
