"""Render our UI and verify WGC -> local mock AI -> answer display.

No real API or user windows are used. Test credentials and captured fixture
images live only in a disposable .qa subdirectory on the project drive.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
from collections.abc import Callable
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEventLoop, QRect, Qt, QThreadPool, QTimer
from PySide6.QtGui import QFont, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from quiz_helper.app import MainWindow
from quiz_helper.storage import AppStorage, non_c_path
from quiz_helper.theme import stylesheet
from quiz_helper.docking import target_corner, anchor_position
from quiz_helper.branding import set_windows_identity, APP_ID


class MockState:
    def __init__(self) -> None:
        self.requests = 0
        self.connections = 0
        self.answer_type = "single"
        self.answers = ["B"]
        self.explanation = "1 加 1 等于 2，因此选择 B。"
        self.delay = 0.0
        self.valid_images = 0
        self.invalid_request = False


def mock_server(state: MockState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def send_json(self, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # Cancellation is deliberately exercised by the test.

        def do_GET(self) -> None:
            if self.path != "/v1/models":
                state.invalid_request = True
            state.connections += 1
            self.send_json({"data": [{"id": "deepseek-flash"}]})

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                state.invalid_request = True
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            if "max_tokens" in payload or "max_completion_tokens" in payload:
                state.invalid_request = True
            state.requests += 1
            try:
                parts = payload["messages"][-1]["content"]
                image_url = next(part["image_url"]["url"] for part in parts if part["type"] == "image_url")
                image_data = base64.b64decode(image_url.split(",", 1)[1], validate=True)
                image = QImage.fromData(image_data)
                if image.isNull() or image.width() < 40 or image.height() < 40:
                    raise ValueError("Invalid fixture image")
                state.valid_images += 1
            except (KeyError, StopIteration, ValueError, TypeError):
                state.invalid_request = True
            if state.delay:
                time.sleep(state.delay)
            answer = {
                "status": "ok", "type": state.answer_type,
                "answers": state.answers, "explanation": state.explanation,
            }
            self.send_json({
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(answer, ensure_ascii=False)},
                }],
                "usage": {"prompt_tokens": 123, "completion_tokens": 4, "total_tokens": 127},
            })

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    return server


def wait_for(condition: Callable[[], bool], timeout_ms: int = 12_000) -> None:
    if condition():
        return
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(20)
    deadline = QTimer()
    deadline.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if condition() else None)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout_ms)
    loop.exec()
    poll.stop()
    deadline.stop()
    if not condition():
        raise AssertionError("UI condition did not complete before timeout")


class AutoCropDialog(QDialog):
    """Select our synthetic image only; real CropCanvas is unit tested separately."""

    def __init__(self, image: QImage, parent: QWidget) -> None:
        super().__init__(parent)
        self.canvas = self
        self.image = image

    def pixel_rect(self) -> QRect:
        return QRect(0, 32, self.image.width(), self.image.height() - 32)

    def exec(self) -> int:
        return QDialog.DialogCode.Accepted


def save_widget(widget: QWidget, path: Path) -> None:
    QApplication.processEvents()
    QTest.qWait(120)
    if not widget.grab().save(str(path)):
        raise AssertionError(f"Could not save screenshot: {path.name}")


def run(output: Path, render_only: bool = False) -> int:
    output = non_c_path(output)
    output.mkdir(parents=True, exist_ok=True)
    set_windows_identity()
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyle("Fusion")
    state = MockState()
    server = mock_server(state)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fixture: subprocess.Popen[str] | None = None
    window: MainWindow | None = None
    with tempfile.TemporaryDirectory(prefix="ui-smoke-", dir=output) as directory:
        try:
            storage = AppStorage(Path(directory))
            settings = replace(
                storage.settings,
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                proxy_mode="none",
                request_timeout=5,
            )
            storage.save_settings(settings)
            storage.save_key("ui-fixture-placeholder-not-a-real-key")
            window = MainWindow(storage)
            window.show()
            QTest.qWait(200)
            native = ctypes.WinDLL("user32", use_last_error=True)
            native.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            native.SendMessageW.restype = ctypes.c_ssize_t
            assert native.SendMessageW(int(window.winId()), 0x007f, 0, 0)
            print("PASS native window icon handle", flush=True)
            assert window.size().width() == 960 and window.size().height() == 680
            save_widget(window, output / "ui-home-idle.png")

            window.show_page(1)
            window.settings_page.test_button.click()
            wait_for(lambda: state.connections == 1 and not window._connection_busy)
            assert not state.invalid_request
            save_widget(window, output / "ui-settings.png")
            for index, suffix in ((1, "files"), (2, "display")):
                window.settings_page.tabs.setCurrentIndex(index)
                save_widget(window, output / f"ui-settings-{suffix}.png")
            window.settings_page.tabs.setCurrentIndex(0)
            window.show_page(2)
            save_widget(window, output / "ui-announcements.png")
            window.show_page(0)

            if not render_only:
                fixture = subprocess.Popen(
                    [sys.executable, str(Path(__file__).with_name("capture_smoke.py")), "--fixture"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW,
                )
                assert fixture.stdout is not None
                line = fixture.stdout.readline()
                if not line:
                    raise AssertionError("Synthetic capture fixture failed to initialize")
                hwnd = int(json.loads(line)["hwnd"])
                target = next(
                    item for item in window.controller.capture.list_windows() if item.window_id == hwnd
                )
                errors: list[str] = []
                answers: list[tuple[object, object, float, bool]] = []
                window.controller.error.connect(errors.append)
                window.controller.answer_ready.connect(lambda *values: answers.append(values))
                with patch("quiz_helper.app.CropDialog", AutoCropDialog):
                    window.controller.choose_target(target)
                    wait_for(lambda: not window.controller.region.isEmpty() or bool(errors))
                    assert not errors, errors
                    assert window.home.query_button.isEnabled()
                    placement = target_corner(hwnd)
                    assert placement is not None
                    window.follower.refresh()
                    assert window.overlay.pos() == anchor_position(*placement, window.overlay.size())
                    window.home.refresh_button.click()
                    wait_for(lambda: not window.controller.busy)
                    assert state.requests == 0 and not window.home.preview.full_image.isNull()
                    print("PASS target-corner docking and preview refresh without AI", flush=True)
                    QTest.mouseClick(window.overlay.query, Qt.MouseButton.LeftButton)
                    wait_for(lambda: len(answers) == 1 or bool(errors))
                    assert not errors, errors
                    assert window.home.answer_label.text() == "B"
                    assert window.overlay.answer_text == "B"
                    assert "127" in window.home.metrics_label.text()
                    assert state.requests == 1 and state.valid_images == 1
                    assert not state.invalid_request
                    print("PASS WGC capture -> local mock API -> home and floating answer", flush=True)

                    window.hotkeys.bind("Ctrl+Alt+Shift+F11")
                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                    user32.PostThreadMessageW.restype = wintypes.BOOL
                    assert user32.PostThreadMessageW(kernel32.GetCurrentThreadId(), 0x0312, window.hotkeys._id, 0)
                    wait_for(lambda: len(answers) == 2 or bool(errors))
                    assert not errors, errors
                    assert answers[-1][3] and state.requests == 1
                    print("PASS native global hotkey message and identical-image cache", flush=True)

                    window.home.explanation_check.setChecked(True)
                    QTest.mouseClick(window.home.force_button, Qt.MouseButton.LeftButton)
                    wait_for(lambda: len(answers) == 3 or bool(errors))
                    assert not errors, errors
                    assert state.requests == 2
                    assert "等于" in window.home.explanation_label.text()
                    assert not window.overlay.expand.isHidden()
                    window.overlay.expand.setChecked(True)
                    QTest.qWait(150)
                    assert window.overlay.pos() == anchor_position(*target_corner(hwnd), window.overlay.size())
                    save_widget(window, output / "ui-home.png")
                    window.home.preview.tabs.setCurrentIndex(1)
                    window.home.preview.original()
                    save_widget(window, output / "ui-home-detail.png")
                    window.home.preview.tabs.setCurrentIndex(0)
                    save_widget(window.overlay, output / "ui-overlay.png")
                    print("PASS force refresh and optional short explanation", flush=True)

                    app.setStyleSheet(stylesheet("dark"))
                    save_widget(window, output / "ui-home-dark.png")
                    app.setStyleSheet(stylesheet("light"))

                    assert fixture.stdin is not None
                    old_position = window.overlay.pos()
                    fixture.stdin.write("move\n")
                    fixture.stdin.flush()
                    wait_for(lambda: window.overlay.pos() != old_position)
                    assert window.overlay.pos() == anchor_position(*target_corner(hwnd), window.overlay.size())
                    old_size = window.controller.frame_size
                    calls_before = state.requests
                    fixture.stdin.write("resize\n")
                    fixture.stdin.flush()
                    QTest.qWait(250)
                    window.home.refresh_button.click()
                    wait_for(lambda: not window.controller.busy and window.controller.frame_size != old_size)
                    assert state.requests == calls_before
                    assert window.home.answer_label.text() == "—"
                    print("PASS window move, overlay resize anchoring and refreshed ROI after target resize", flush=True)
                    fixture.stdin.write("minimize\n")
                    fixture.stdin.flush()
                    wait_for(lambda: window.controller.paused)
                    assert not window.home.query_button.isEnabled()
                    assert window.home.answer_label.text() == "—"
                    assert window.overlay.answer_text == ""
                    before = state.requests
                    window.controller.query()
                    QTest.qWait(150)
                    assert state.requests == before
                    fixture.stdin.write("restore\n")
                    fixture.stdin.flush()
                    wait_for(lambda: not window.controller.paused)
                    QTest.mouseClick(window.home.query_button, Qt.MouseButton.LeftButton)
                    wait_for(lambda: len(answers) == 4 or bool(errors))
                    assert not errors, errors
                    assert state.requests == before + 1 and not answers[-1][3]
                    print("PASS minimize pauses and clears answer; restore requires fresh capture", flush=True)

                    state.delay = 0.6
                    QTest.mouseClick(window.home.force_button, Qt.MouseButton.LeftButton)
                    wait_for(lambda: state.requests == before + 2)
                    QTest.mouseClick(window.overlay.cancel_button, Qt.MouseButton.LeftButton)
                    QTest.qWait(900)
                    assert window.controller.running and not window.controller.region.isEmpty()
                    assert not window.controller.busy and len(answers) == 4
                    print("PASS cancel current query preserves target and region", flush=True)
                    QTest.mouseClick(window.home.force_button, Qt.MouseButton.LeftButton)
                    wait_for(lambda: state.requests == before + 3)
                    QTest.mouseClick(window.home.stop_button, Qt.MouseButton.LeftButton)
                    QTest.qWait(900)
                    assert not window.controller.running
                    assert window.home.answer_label.text() == "—"
                    assert window.overlay.isHidden()
                    assert len(answers) == 4
                    print("PASS stop cancels active request and suppresses late answer", flush=True)
            else:
                save_widget(window, output / "ui-home.png")
                window.overlay.show_answer("B", "示例：1 加 1 等于 2。")
                window.overlay.show()
                save_widget(window.overlay, output / "ui-overlay.png")

            assert storage.load_key() == "ui-fixture-placeholder-not-a-real-key"
            assert b"ui-fixture-placeholder" not in storage.key_path.read_bytes()
            print("PASS encrypted placeholder key; screenshots rendered on non-C drive", flush=True)
            return 0
        finally:
            if window is not None:
                window.close()
                QThreadPool.globalInstance().waitForDone(5000)
                app.processEvents()
            if fixture is not None:
                if fixture.poll() is None:
                    fixture.terminate()
                fixture.wait(timeout=5)
                for stream in (fixture.stdin, fixture.stdout, fixture.stderr):
                    if stream is not None:
                        stream.close()
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".qa"))
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.render_only))
