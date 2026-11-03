"""源码及 PyInstaller 共用启动入口。"""

from pathlib import Path
import sys


def diagnose(root: Path) -> int:
    """离屏检查便携运行组件；不联网、不显示对话框、不读取真实 Key。"""
    import json
    import os

    if root.drive.upper() == "C:":
        return 2
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    report: dict[str, object] = {"ok": False}
    try:
        from quiz_helper.app import MainWindow
        from quiz_helper.storage import protect_secret, unprotect_secret
        from PySide6 import __version__ as qt_version
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
        from PySide6.QtGui import QImage
        from PySide6.QtMultimedia import QWindowCapture
        from PySide6.QtNetwork import QSslSocket
        from PySide6.QtWidgets import QApplication
        from quiz_helper.branding import application_icon, set_windows_identity, APP_ID
        from quiz_helper import __version__

        set_windows_identity()
        application = QApplication(["quiz-helper-diagnostics"])
        if application_icon().isNull():
            raise RuntimeError("application icon missing")
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(0x3478F6)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("image encoding")
        buffer.close()
        if unprotect_secret(protect_secret("quiz-helper-diagnostic-placeholder")) != "quiz-helper-diagnostic-placeholder":
            raise RuntimeError("credential encryption")
        if not QSslSocket.supportsSsl():
            raise RuntimeError("TLS backend")
        report.update(ok=True, app_version=__version__, app_user_model_id=APP_ID, pyside_version=qt_version, tls_backends=QSslSocket.availableBackends(),
                      image_encoding=True, dpapi=True, application_import=True, application_icon=True,
                      window_capture_import=QWindowCapture is not None and MainWindow is not None)
        application.quit()
    except Exception as exc:
        # This path never loads settings or real credentials and never contacts
        # a server; a bounded local runtime error helps diagnose bundled DLLs.
        report.update(error_type=type(exc).__name__, missing_module=getattr(exc, "name", None),
                      details=str(exc).replace(str(root), "<app>")[:500])
    try:
        directory = root / "data"
        directory.mkdir(exist_ok=True)
        (directory / "diagnostics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return 2
    return 0 if report["ok"] else 1


def main() -> int:
    if sys.platform != "win32":
        print("题目查询助手仅支持 Windows 10/11 64 位。")
        return 1
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    if "--diagnose" in sys.argv:
        return diagnose(root)
    try:
        from quiz_helper.app import run
    except ImportError:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "界面或捕获组件缺失。源码运行请安装 requirements.txt；便携版请完整解压整个文件夹。", "题目查询助手 · 依赖缺失", 0x10)
        return 1
    return run(root)


if __name__ == "__main__":
    raise SystemExit(main())
