from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from quiz_helper.models import AppSettings, parse_answer
from quiz_helper.storage import AppStorage, non_c_path, protect_secret, unprotect_secret


ROOT = Path(__file__).resolve().parents[1]


class AnswerTests(unittest.TestCase):
    def answer(self, **updates: object) -> str:
        payload = {"status": "ok", "type": "single", "answers": ["A"], "explanation": "简短理由"}
        payload.update(updates)
        return json.dumps(payload, ensure_ascii=False)

    def test_question_types_and_explanation_switch(self) -> None:
        self.assertEqual(parse_answer(self.answer()).display_text, "A")
        self.assertEqual(parse_answer(self.answer()).explanation, "")
        self.assertEqual(parse_answer(self.answer(), include_explanation=True).explanation, "简短理由")
        self.assertEqual(parse_answer(self.answer(type="multiple", answers=["C", "A"])).display_text, "A、C")
        self.assertEqual(parse_answer(self.answer(type="boolean", answers=["true"])).display_text, "正确")
        self.assertEqual(parse_answer(self.answer(type="boolean", answers=["false"])).display_text, "错误")

    def test_invalid_or_ambiguous_content_is_not_extracted(self) -> None:
        cases = [
            "", "答案是 A", '```json\n{"answers":["A"]}\n```', "[]",
            self.answer(answers=["A", "B"]), self.answer(answers=["a"]),
            self.answer(type="multiple", answers=["A", "A"]),
            self.answer(type="boolean", answers=[True]),
            self.answer(type="boolean", answers=["正确"]),
            self.answer(answers=[]), self.answer(extra="ignored?"),
            self.answer(status="uncertain", answers=["A"]),
            '{"status":"ok","status":"uncertain","type":"single","answers":[]}',
            self.answer(explanation="x" * 1001),
        ]
        for content in cases:
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_answer(content)

    def test_failure_status_and_mismatched_type(self) -> None:
        for status in ("unreadable", "multiple_questions", "uncertain"):
            result = parse_answer(self.answer(status=status, answers=[]))
            self.assertEqual(result.answers, ())
            self.assertNotEqual(result.display_text, "A")
        with self.assertRaises(ValueError):
            parse_answer(self.answer(), expected_type="boolean")


class SettingsTests(unittest.TestCase):
    def test_defaults_and_loopback_are_valid(self) -> None:
        AppSettings().validate()
        AppSettings(base_url="http://127.0.0.1:8000/v1").validate()
        AppSettings(base_url="http://[::1]:8000/v1").validate()

    def test_invalid_settings(self) -> None:
        cases = [
            {"base_url": "http://remote.example/v1"},
            {"base_url": "https://user:password@example.com"},
            {"base_url": "https://example.com?key=secret"},
            {"request_timeout": True}, {"query_hotkey": "F12"}, {"theme": "blue"},
            {"reasoning": []},
            {"max_image_edge": 1}, {"overlay_position": [1]},
            {"proxy_mode": "custom", "proxy_url": "http://host"},
            {"proxy_mode": "custom", "proxy_url": "http://u:p@host:8080"},
        ]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                AppSettings(**values).validate()

    def test_c_drive_rejected(self) -> None:
        with self.assertRaises(ValueError):
            non_c_path(Path("C:/do-not-create-quiz-data"))


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="quiz-test-", dir=ROOT)
        self.root = Path(self.temporary.name)
        self.storage = AppStorage(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_settings_roundtrip_and_malformed_file_is_preserved(self) -> None:
        settings = self.storage.settings
        settings.model = "custom-image-model"
        self.storage.save_settings(settings)
        self.assertEqual(AppStorage(self.root).settings.model, "custom-image-model")
        self.storage.settings_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.storage.load_settings()
        self.assertEqual(self.storage.settings_path.read_text(encoding="utf-8"), "{broken")

    def test_unusable_capture_directory_is_rejected_before_settings_are_written(self) -> None:
        self.storage.save_settings(self.storage.settings)
        original = self.storage.settings_path.read_bytes()
        blocked = self.root / "not-a-directory.txt"
        blocked.write_text("keep", encoding="utf-8")
        candidate = replace(self.storage.settings, capture_dir=str(blocked))
        with self.assertRaises(OSError):
            self.storage.save_settings(candidate)
        self.assertEqual(self.storage.settings_path.read_bytes(), original)
        self.assertNotEqual(self.storage.settings.capture_dir, str(blocked))

    def test_cleanup_only_owned_completed_images(self) -> None:
        directory = self.root / "data" / "captures"
        active = self.storage.save_capture(b"active")
        completed = self.storage.save_capture(b"complete")
        foreign = directory / "user-picture.png"
        foreign.write_bytes(b"foreign")
        untracked = directory / ("quiz-capture-" + "a" * 32 + ".png")
        untracked.write_bytes(b"untracked")
        self.storage.finish_capture(completed)
        self.assertEqual(self.storage.cleanup(manual=True), (1, 8))
        self.assertTrue(active.exists())
        self.assertTrue(foreign.exists())
        self.assertTrue(untracked.exists())
        self.assertEqual(self.storage.capture_usage(), (1, 6))

    def test_retention_starts_at_task_completion_and_restart_cleans_expired(self) -> None:
        with patch("quiz_helper.storage.time.time", return_value=1000):
            path = self.storage.save_capture(b"image")
        with patch("quiz_helper.storage.time.time", return_value=2000):
            self.storage.finish_capture(path)
            self.assertEqual(self.storage.cleanup(), (0, 0))
        with patch("quiz_helper.storage.time.time", return_value=2599):
            self.assertEqual(self.storage.cleanup(), (0, 0))
        with patch("quiz_helper.storage.time.time", return_value=2601):
            reopened = AppStorage(self.root)
        self.assertFalse(path.exists())
        self.assertEqual(reopened.capture_usage(), (0, 0))

    def test_auto_cleanup_can_be_disabled_but_manual_still_works(self) -> None:
        path = self.storage.save_capture(b"image")
        self.storage.finish_capture(path)
        self.storage.settings.auto_cleanup = False
        self.assertEqual(self.storage.cleanup(), (0, 0))
        self.assertEqual(self.storage.cleanup(manual=True), (1, 5))

    def test_crashed_task_recovery_keeps_a_stable_completion_timestamp(self) -> None:
        with patch("quiz_helper.storage.time.time", return_value=1000):
            path = self.storage.save_capture(b"image")
        with patch("quiz_helper.storage.time.time", return_value=2000):
            AppStorage(self.root)
        with patch("quiz_helper.storage.time.time", return_value=2500):
            AppStorage(self.root)
            self.assertTrue(path.exists())
        with patch("quiz_helper.storage.time.time", return_value=2601):
            AppStorage(self.root)
        self.assertFalse(path.exists())

    def test_replaced_file_is_not_deleted(self) -> None:
        path = self.storage.save_capture(b"original")
        self.storage.finish_capture(path)
        path.rename(path.with_suffix(".backup"))
        path.write_bytes(b"replacement-owned-by-someone-else")
        self.assertEqual(self.storage.cleanup(manual=True), (0, 0))
        self.assertEqual(path.read_bytes(), b"replacement-owned-by-someone-else")

    def test_symbolic_link_is_not_followed(self) -> None:
        path = self.storage.save_capture(b"original")
        self.storage.finish_capture(path)
        path.rename(path.with_suffix(".backup"))
        foreign = self.root / "foreign.png"
        foreign.write_bytes(b"keep-this")
        try:
            path.symlink_to(foreign)
        except OSError:
            self.skipTest("Creating symbolic links requires additional Windows permission")
        self.assertEqual(self.storage.cleanup(manual=True), (0, 0))
        self.assertEqual(foreign.read_bytes(), b"keep-this")
        self.assertTrue(path.is_symlink())

    @unittest.skipUnless(os.name == "nt", "DPAPI requires Windows")
    def test_dpapi_and_key_file_roundtrip_without_plaintext(self) -> None:
        sentinel = "quiz-test-only-not-a-real-api-key"
        encrypted = protect_secret(sentinel)
        self.assertNotIn(sentinel.encode(), encrypted)
        self.assertEqual(unprotect_secret(encrypted), sentinel)
        self.storage.save_key(sentinel)
        self.assertNotIn(sentinel.encode(), self.storage.key_path.read_bytes())
        self.assertEqual(AppStorage(self.root).load_key(), sentinel)
        self.storage.delete_key()
        self.assertEqual(self.storage.load_key(), "")
        with self.assertRaises(ValueError):
            unprotect_secret(b"invalid-encrypted-key")


if __name__ == "__main__":
    unittest.main()
