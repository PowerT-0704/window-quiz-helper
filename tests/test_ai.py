"""Local HTTP fixture tests: no real endpoint or API credential is contacted."""

from __future__ import annotations

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest
from typing import Any, Callable

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from quiz_helper.ai import AIClient, build_payload, endpoint_url
from quiz_helper.models import AppSettings


class _MockHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._reply(body)

    def do_GET(self) -> None:
        self._reply(b"")

    def _reply(self, request_body: bytes) -> None:
        server: Any = self.server
        scenario = dict(server.scenario)
        server.requests.append({"path": self.path, "body": request_body, "auth": self.headers.get("Authorization")})
        time.sleep(scenario.get("delay", 0))
        status = scenario.get("status", 200)
        if self.path.endswith("/models"):
            body: Any = {"data": [{"id": "fixture-model"}]}
        else:
            body = {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"status": "ok", "type": "single", "answers": ["B"], "explanation": "fixture reason"}), "reasoning_content": "private reasoning must never be forwarded"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        body = scenario.get("body", body)
        encoded = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        try:
            self.send_response(status)
            if "location" in scenario:
                self.send_header("Location", scenario["location"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class AIClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self) -> None:
        self.server.scenario = {}  # type: ignore[attr-defined]
        self.server.requests = []  # type: ignore[attr-defined]
        self.settings = replace(AppSettings(), base_url=f"http://127.0.0.1:{self.server.server_port}/gateway/v1/", proxy_mode="none", model="fixture-model", request_timeout=2)
        self.client = AIClient()

    def tearDown(self) -> None:
        self.client.cancel()
        self.client.deleteLater()
        self.app.processEvents()

    def run_operation(self, action: Callable[[], None], wait_ms: int = 4000) -> tuple[str, tuple[Any, ...]]:
        outcomes: list[tuple[str, tuple[Any, ...]]] = []
        loop = QEventLoop()

        def success(*args: Any) -> None:
            outcomes.append(("success", args))
            loop.quit()

        def failure(*args: Any) -> None:
            outcomes.append(("failure", args))
            loop.quit()

        def connected(*args: Any) -> None:
            outcomes.append(("connected", args))
            loop.quit()

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        self.client.succeeded.connect(success)
        self.client.failed.connect(failure)
        self.client.connected.connect(connected)
        try:
            action()
            if not outcomes:
                timer.start(wait_ms)
                loop.exec()
            self.assertTrue(outcomes, "operation produced no result before fixture timeout")
            return outcomes[0]
        finally:
            timer.stop()
            self.client.succeeded.disconnect(success)
            self.client.failed.disconnect(failure)
            self.client.connected.disconnect(connected)

    def solve(self) -> None:
        self.client.solve(b"fixture-image", "image/png", self.settings, "fixture-not-a-real-key")

    def test_success_preserves_gateway_and_uses_one_independent_image(self) -> None:
        kind, values = self.run_operation(self.solve)
        self.assertEqual(kind, "success")
        answer, usage = values
        self.assertEqual(answer.display_text, "B")
        self.assertEqual(answer.explanation, "")
        self.assertEqual(usage["total_tokens"], 15)
        request = self.server.requests[0]  # type: ignore[attr-defined]
        self.assertEqual(request["path"], "/gateway/v1/chat/completions")
        self.assertEqual(request["auth"], "Bearer fixture-not-a-real-key")
        payload = json.loads(request["body"])
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(len(payload["messages"][1]["content"]), 2)
        self.assertNotIn("thinking", payload)
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertFalse(self.client.is_busy)

    def test_connection_uses_get_models(self) -> None:
        kind, _ = self.run_operation(lambda: self.client.test_connection(self.settings, "fixture-key"))
        self.assertEqual(kind, "connected")
        self.assertEqual(self.server.requests[0]["path"], "/gateway/v1/models")  # type: ignore[attr-defined]

    def test_explanation_is_opt_in(self) -> None:
        self.settings.explanation = True
        kind, values = self.run_operation(self.solve)
        self.assertEqual(kind, "success")
        self.assertEqual(values[0].explanation, "fixture reason")

    def test_http_errors_are_sanitized(self) -> None:
        for status in [401, 403, 429, 500, 400]:
            with self.subTest(status=status):
                self.server.scenario = {"status": status, "body": {"error": "fixture-not-a-real-key private provider text"}}  # type: ignore[attr-defined]
                kind, values = self.run_operation(self.solve)
                self.assertEqual(kind, "failure")
                self.assertNotIn("fixture-not-a-real-key", values[0])
                self.assertNotIn("private provider", values[0])

    def test_redirect_does_not_forward_credentials(self) -> None:
        self.server.scenario = {"status": 302, "location": f"http://127.0.0.1:{self.server.server_port}/redirect-target"}  # type: ignore[attr-defined]
        kind, values = self.run_operation(self.solve)
        self.assertEqual(kind, "failure")
        self.assertIn("重定向", values[0])
        self.assertEqual(len(self.server.requests), 1)  # type: ignore[attr-defined]

    def test_malformed_empty_and_truncated_responses_never_show_answers(self) -> None:
        cases: list[Any] = [
            b"not-json",
            {"choices": []},
            {"choices": [{"message": {"content": "   "}, "finish_reason": "stop"}]},
            {"choices": [{"message": {"content": '{"status":"ok","type":"single","answers":["A"]}'}, "finish_reason": "length"}]},
            {"choices": [{"message": {"content": "The answer is A."}, "finish_reason": "stop"}]},
            {"choices": [{"message": {"content": '{"status":"ok","type":"single","answers":["A","B"]}'}, "finish_reason": "stop"}]},
        ]
        for body in cases:
            with self.subTest(body=body):
                self.server.scenario = {"body": body}  # type: ignore[attr-defined]
                kind, _ = self.run_operation(self.solve)
                self.assertEqual(kind, "failure")

    def test_timeout_aborts_without_automatic_retry(self) -> None:
        self.settings.request_timeout = 1
        self.server.scenario = {"delay": 1.5}  # type: ignore[attr-defined]
        kind, values = self.run_operation(self.solve)
        self.assertEqual(kind, "failure")
        self.assertIn("超时", values[0])
        self.assertFalse(self.client.is_busy)
        self.assertEqual(len(self.server.requests), 1)  # type: ignore[attr-defined]

    def test_cancel_suppresses_late_answer_and_can_restart(self) -> None:
        self.server.scenario = {"delay": 0.25}  # type: ignore[attr-defined]
        answers: list[Any] = []
        failures: list[Any] = []
        self.client.succeeded.connect(lambda *args: answers.append(args))
        self.client.failed.connect(lambda *args: failures.append(args))
        loop = QEventLoop()
        self.solve()
        QTimer.singleShot(30, self.client.cancel)
        QTimer.singleShot(400, loop.quit)
        loop.exec()
        self.assertFalse(self.client.is_busy)
        self.assertEqual(answers, [])
        self.assertEqual(failures, [])
        self.server.scenario = {}  # type: ignore[attr-defined]
        kind, _ = self.run_operation(self.solve)
        self.assertEqual(kind, "success")

    def test_missing_key_is_rejected_without_request(self) -> None:
        kind, _ = self.run_operation(lambda: self.client.solve(b"fixture", "image/png", self.settings, ""))
        self.assertEqual(kind, "failure")
        self.assertEqual(self.server.requests, [])  # type: ignore[attr-defined]


class PayloadTests(unittest.TestCase):
    def test_deepseek_parameters_are_explicit_and_controllable(self) -> None:
        settings = AppSettings()
        payload = build_payload(b"fixture", "image/png", settings)
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "low")
        settings.reasoning = "none"
        payload = build_payload(b"fixture", "image/png", settings)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", payload)

    def test_http_only_allowed_for_loopback_and_credentials_rejected(self) -> None:
        for value in ["http://example.com", "https://key:secret@example.com", "https://example.com?key=secret", "https://example.com#secret", "file:///tmp/test", "https://example.com:bad", "https://example.com\n"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                endpoint_url(value, "models")
        self.assertEqual(endpoint_url("https://example.com/api/v1/", "models").toString(), "https://example.com/api/v1/models")
        self.assertEqual(endpoint_url("http://127.0.0.1:8000", "models").scheme(), "http")


if __name__ == "__main__":
    unittest.main()
