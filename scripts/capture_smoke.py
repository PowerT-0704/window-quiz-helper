"""Opt-in WGC verification using only our own disposable fixture windows.

Run from the project directory:
    .venv\\Scripts\\python.exe scripts\\capture_smoke.py
The test covers a window with a different-colored window, checks the captured
pixels still belong to the target, and checks minimized/closed guards.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from quiz_helper.capture import CaptureService, WindowInfo
from quiz_helper import win32


def fixture(fixture_type: str = "qt") -> int:
    app = QApplication([])
    if fixture_type == "chromium":
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView

        profile = QWebEngineProfile(app)  # Off-the-record: no persistent profile.
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        target = QWebEngineView()
        target.setPage(QWebEnginePage(profile, target))
        target.setHtml(
            "<html><meta charset='utf-8'><body style='margin:0;"
            "background:rgb(34,180,85);font:22px sans-serif'>"
            "验证题目：1 + 1 = ?<br>A. 1　B. 2　C. 3<br>"
            "静态 Chromium 页面</body></html>"
        )
    else:
        target = QWidget()
        layout = QVBoxLayout(target)
        label = QLabel("验证题目：1 + 1 = ?\nA. 1    B. 2    C. 3\n绿色背景属于目标窗口")
        label.setStyleSheet("font-size: 22px;")
        layout.addWidget(label)
    target.setWindowTitle("题目查询助手 - 捕获验证题目")
    target.setStyleSheet("background-color: rgb(34, 180, 85); color: black;")
    target.resize(640, 420)
    target.move(200, 180)
    cover = QWidget()
    cover.setWindowTitle("题目查询助手 - 遮挡验证（洋红色）")
    cover.setStyleSheet("background-color: rgb(210, 35, 160);")
    cover.resize(660, 460)
    cover.move(190, 150)
    target.show()
    # Give DWM a rendered target surface before covering it. Showing both
    # windows in the same initial event can prevent any target frame existing.
    def cover_target() -> None:
        cover.show()
        cover.raise_()

    QTimer.singleShot(300, cover_target)

    class Commands(QObject):
        command = Signal(str)

    commands = Commands()

    def handle(command: str) -> None:
        if command == "minimize":
            target.showMinimized()
        elif command == "restore":
            target.showNormal()
            cover.raise_()
        elif command == "move":
            target.move(350, 260)
            cover.move(340, 230)
        elif command == "resize":
            target.resize(700, 450)
            cover.resize(720, 490)
        elif command == "close":
            target.close()
        elif command == "quit":
            app.quit()

    commands.command.connect(handle)

    def read_commands() -> None:
        for line in sys.stdin:
            commands.command.emit(line.strip())

    threading.Thread(target=read_commands, daemon=True).start()
    QTimer.singleShot(600, lambda: print(json.dumps({"hwnd": int(target.winId())}), flush=True))
    QTimer.singleShot(60000, app.quit)
    return app.exec()


def wait(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def capture_once(service: CaptureService, window: WindowInfo) -> tuple[object | None, str]:
    loop = QEventLoop()
    result: dict[str, object] = {}

    def image_ready(image: object) -> None:
        result["image"] = image
        loop.quit()

    def error(message: str) -> None:
        result["error"] = message
        loop.quit()

    service.frame_ready.connect(image_ready)
    service.failed.connect(error)
    service.start(window, 10)
    if service.is_busy:
        QTimer.singleShot(12000, loop.quit)
        loop.exec()
    service.frame_ready.disconnect(image_ready)
    service.failed.disconnect(error)
    return result.get("image"), str(result.get("error", ""))


def verify(output: Path | None, fixture_type: str = "qt") -> int:
    if sys.platform != "win32":
        print("SKIP: Windows interactive desktop required")
        return 0
    app = QApplication([])
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--fixture", "--fixture-type", fixture_type],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        assert child.stdout is not None
        line = child.stdout.readline()
        if not line:
            raise RuntimeError("Fixture did not initialize")
        hwnd = int(json.loads(line)["hwnd"])
        service = CaptureService()
        selected = next((item for item in service.list_windows() if item.window_id == hwnd), None)
        if selected is None:
            raise RuntimeError("Fixture window was not enumerated")
        image, error = capture_once(service, selected)
        if image is None:
            raise RuntimeError(f"Occluded capture failed: {error}")
        color = image.pixelColor(image.width() // 2, image.height() * 3 // 4)
        expected = QColor(34, 180, 85)
        differences = (
            abs(color.red() - expected.red()),
            abs(color.green() - expected.green()),
            abs(color.blue() - expected.blue()),
        )
        if max(differences) > 10:
            raise RuntimeError(f"Expected target green pixel, got {color.name()}")
        if output is not None:
            output = output.resolve()
            if output.drive.casefold() == "c:":
                raise ValueError("Screenshot output must not be on C drive")
            output.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(str(output)):
                raise RuntimeError("Could not save verification image")
        print(f"PASS occluded capture: {image.width()}x{image.height()} target pixel {color.name()}")
        assert child.stdin is not None
        child.stdin.write("minimize\n")
        child.stdin.flush()
        wait(400)
        if not win32.is_minimized(hwnd):
            raise RuntimeError("Fixture minimize command failed")
        image, error = capture_once(service, selected)
        if image is not None or "最小化" not in error:
            raise RuntimeError(f"Minimized target should pause without image: {error}")
        print("PASS minimized guard: no cached frame, no target restoration")
        child.stdin.write("restore\n")
        child.stdin.flush()
        wait(400)
        image, error = capture_once(service, selected)
        if image is None:
            raise RuntimeError(f"Fresh capture after restore failed: {error}")
        print("PASS restored window: new capture session succeeds")
        child.stdin.write("close\n")
        child.stdin.flush()
        wait(300)
        image, error = capture_once(service, selected)
        if image is not None or "关闭" not in error:
            raise RuntimeError(f"Closed target should reject capture: {error}")
        print("PASS closed-window guard")
        service.cancel()
        app.processEvents()
        return 0
    finally:
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                stream.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fixture-type", choices=["qt", "chromium"], default="qt")
    args = parser.parse_args()
    raise SystemExit(fixture(args.fixture_type) if args.fixture else verify(args.output, args.fixture_type))
