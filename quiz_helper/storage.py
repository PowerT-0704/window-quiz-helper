"""Portable data storage, current-user DPAPI, and manifest-scoped image cleanup."""

from __future__ import annotations

import ctypes
import json
import os
import re
import time
import uuid
from dataclasses import asdict, fields
from pathlib import Path, PureWindowsPath

from .models import AppSettings


_CAPTURE_NAME = re.compile(r"quiz-capture-[0-9a-f]{32}\.(?:png|jpg|jpeg)\Z")


def non_c_path(path: Path) -> Path:
    """Resolve junctions before checking the final drive, without creating it."""
    original = Path(path).expanduser()
    if PureWindowsPath(str(original)).drive.upper() == "C:":
        raise ValueError("应用数据和截图必须保存在非 C 盘目录。")
    resolved = original.resolve()
    if resolved.drive.upper() == "C:" or PureWindowsPath(str(resolved)).drive.upper() == "C:":
        raise ValueError("该目录实际指向 C 盘，请选择其他磁盘。")
    return resolved


def _dpapi(payload: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI 密钥保护仅支持 Windows。")
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    source_buffer = ctypes.create_string_buffer(payload)
    source = DataBlob(len(payload), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = DataBlob()
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.POINTER(DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
    ]
    operation.restype = wintypes.BOOL
    try:
        if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.memset(source_buffer, 0, ctypes.sizeof(source_buffer))
        if output.pbData:
            if decrypt:
                ctypes.memset(output.pbData, 0, output.cbData)
            kernel32.LocalFree(ctypes.cast(output.pbData, wintypes.HLOCAL))


def protect_secret(secret: str) -> bytes:
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("API Key 不能为空。")
    return _dpapi(secret.encode("utf-8"), decrypt=False)


def unprotect_secret(ciphertext: bytes) -> str:
    if not ciphertext:
        raise ValueError("加密凭据为空，请重新输入 API Key。")
    try:
        return _dpapi(ciphertext, decrypt=True).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("无法解密 API Key，请在当前 Windows 账户重新输入。") from exc


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _is_reparse(path: Path) -> bool:
    status = path.lstat()
    return path.is_symlink() or bool(getattr(status, "st_file_attributes", 0) & 0x400)


class AppStorage:
    def __init__(self, app_root: Path) -> None:
        self.app_root = non_c_path(app_root)
        if not self.app_root.is_dir():
            raise ValueError("软件目录不存在，请解压到非 C 盘的可写文件夹。")
        self.data_dir = non_c_path(self.app_root / "data")
        self.data_dir.mkdir(exist_ok=True)
        self.settings_path = self.data_dir / "settings.json"
        self.key_path = self.data_dir / "credentials.bin"
        self._index_path = self.data_dir / "capture-index.json"
        self._active: set[str] = set()
        self._probe(self.data_dir)
        self.settings = AppSettings(capture_dir=str(self.data_dir / "captures"))
        self._recovered_index = False
        self._entries: dict[str, dict[str, object]] = self._load_index()
        self.load_settings()
        if self._recovered_index:
            self._save_index()
        self.cleanup()

    @staticmethod
    def _probe(directory: Path) -> None:
        marker = directory / f".quiz-write-probe-{uuid.uuid4().hex}.tmp"
        try:
            with marker.open("xb") as stream:
                stream.write(b"")
        except OSError as exc:
            raise OSError("所选数据目录不可写，请将软件解压到非 C 盘可写文件夹。") from exc
        finally:
            marker.unlink(missing_ok=True)

    def _capture_directory(self, settings: AppSettings | None = None) -> Path:
        current = settings if settings is not None else self.settings
        directory = non_c_path(Path(current.capture_dir) if current.capture_dir else self.data_dir / "captures")
        directory.mkdir(parents=True, exist_ok=True)
        self._probe(directory)
        return directory

    def load_settings(self) -> AppSettings:
        if not self.settings_path.exists():
            self.settings.validate()
            return self.settings
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.pop("max_tokens", None)  # v0.1 legacy; never constrain a new request.
            if not isinstance(payload, dict) or set(payload) - {item.name for item in fields(AppSettings)}:
                raise ValueError("存在未知设置项。")
            settings = AppSettings(**payload)
            settings.validate()
            if settings.capture_dir:
                non_c_path(Path(settings.capture_dir))
        except (ValueError, TypeError, RecursionError) as exc:
            raise ValueError("设置文件无效，请检查 data/settings.json；原文件未被覆盖。") from exc
        self.settings = settings
        return settings

    def save_settings(self, settings: AppSettings) -> None:
        settings.validate()
        self._capture_directory(settings)
        content = json.dumps(asdict(settings), ensure_ascii=False, indent=2).encode("utf-8")
        _atomic_write(self.settings_path, content)
        self.settings = settings

    def save_key(self, secret: str) -> None:
        _atomic_write(self.key_path, protect_secret(secret))

    def load_key(self) -> str:
        if not self.key_path.exists():
            return ""
        return unprotect_secret(self.key_path.read_bytes())

    def delete_key(self) -> None:
        self.key_path.unlink(missing_ok=True)

    def _load_index(self) -> dict[str, dict[str, object]]:
        if not self._index_path.exists():
            return {}
        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("索引不是对象。")
            for path, entry in payload.items():
                if not isinstance(path, str) or not _CAPTURE_NAME.fullmatch(Path(path).name):
                    raise ValueError("索引包含未知文件。")
                if not isinstance(entry, dict) or set(entry) != {"created_at", "completed_at", "size", "inode", "device"}:
                    raise ValueError("索引记录格式不正确。")
                if any(type(entry[key]) not in {int, float} for key in ("created_at", "size", "inode", "device")):
                    raise ValueError("索引记录数值不正确。")
                completed = entry["completed_at"]
                if completed is not None and type(completed) not in {int, float}:
                    raise ValueError("索引完成时间不正确。")
                non_c_path(Path(path))
                if completed is None:
                    entry["completed_at"] = time.time()
                    self._recovered_index = True
            return payload
        except (ValueError, TypeError, RecursionError) as exc:
            raise ValueError("截图清理索引无效，为避免误删，未自动清理任何文件。") from exc

    def _save_index(self) -> None:
        _atomic_write(self._index_path, json.dumps(self._entries, ensure_ascii=False, indent=2).encode("utf-8"))

    def save_capture(self, data: bytes, suffix: str = ".png") -> Path:
        suffix = suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"} or not data:
            raise ValueError("截图格式不受支持或截图内容为空。")
        path = self._capture_directory() / f"quiz-capture-{uuid.uuid4().hex}{suffix}"
        with path.open("xb") as stream:
            stream.write(data)
        status = path.stat()
        key = str(path)
        self._entries[key] = {
            "created_at": time.time(), "completed_at": None, "size": status.st_size,
            "inode": status.st_ino, "device": status.st_dev,
        }
        self._active.add(key)
        try:
            self._save_index()
        except OSError:
            self._active.discard(key)
            self._entries.pop(key, None)
            path.unlink(missing_ok=True)
            raise
        return path

    def finish_capture(self, path: Path) -> None:
        key = str(non_c_path(path))
        if key not in self._entries:
            return
        self._entries[key]["completed_at"] = time.time()
        self._active.discard(key)
        self._save_index()

    def _owned_stat(self, key: str, entry: dict[str, object]) -> os.stat_result | None:
        path = Path(key)
        if not _CAPTURE_NAME.fullmatch(path.name) or not path.is_absolute():
            return None
        try:
            if _is_reparse(path) or non_c_path(path) != path:
                return None
            status = path.stat()
        except FileNotFoundError:
            return None
        if not path.is_file() or status.st_ino != entry["inode"] or status.st_dev != entry["device"]:
            return None
        return status

    def cleanup(self, manual: bool = False) -> tuple[int, int]:
        if not manual and not self.settings.auto_cleanup:
            return 0, 0
        count = size = 0
        changed = False
        failure: OSError | None = None
        cutoff = time.time() - self.settings.retention_minutes * 60
        for key, entry in list(self._entries.items()):
            if key in self._active:
                continue
            completed = entry["completed_at"]
            if completed is None or (not manual and completed > cutoff):
                continue
            try:
                status = self._owned_stat(key, entry)
                if status is not None:
                    Path(key).unlink()
                    count += 1
                    size += status.st_size
                del self._entries[key]
                changed = True
            except OSError as exc:
                failure = exc
        if changed:
            self._save_index()
        if failure is not None:
            raise OSError("部分截图无法清理，请检查目录权限或文件是否被其他程序占用。") from failure
        return count, size

    def capture_usage(self) -> tuple[int, int]:
        count = size = 0
        for key, entry in self._entries.items():
            status = self._owned_stat(key, entry)
            if status is not None:
                count += 1
                size += status.st_size
        return count, size
