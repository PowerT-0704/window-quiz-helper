"""Application identity and deterministic multi-resolution icon generation."""

from __future__ import annotations

import ctypes
from pathlib import Path
import struct
import sys

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter


APP_ID = "WindowQuiz.Helper"
ICON_PATH = Path(__file__).with_name("assets") / "app.ico"


def set_windows_identity() -> None:
    if sys.platform == "win32":
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        shell.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def application_icon() -> QIcon:
    return QIcon(str(ICON_PATH))


def make_icon(path: Path = ICON_PATH) -> None:
    """Write an ICO with PNG layers using Qt and the standard library only."""
    layers: list[tuple[int, bytes]] = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#318773"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, size, size), size * .24, size * .24)
        painter.setPen(QColor("#ffffff"))
        font = QFont("Segoe UI")
        font.setBold(True)
        font.setPixelSize(round(size * .65))
        painter.setFont(font)
        painter.drawText(QRectF(0, -size * .02, size, size), Qt.AlignmentFlag.AlignCenter, "Q")
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise OSError("图标 PNG 编码失败。")
        buffer.close()
        layers.append((size, bytes(data)))
    offset = 6 + 16 * len(layers)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(layers)))
    for size, data in layers:
        directory.extend(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(bytes(directory) + b"".join(data for _size, data in layers))
