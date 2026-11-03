"""Window metadata and non-activating placement of this process's own overlay."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


if os.name == "nt":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    _enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.EnumWindows.argtypes = [_enum_callback, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.RedrawWindow.argtypes = [
        wintypes.HWND, ctypes.c_void_p, wintypes.HRGN, wintypes.UINT,
    ]
    _user32.RedrawWindow.restype = wintypes.BOOL
    _dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    _dwmapi.DwmGetWindowAttribute.restype = wintypes.LONG
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
        ctypes.POINTER(wintypes.FILETIME)
    ] * 4
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL


def is_window(hwnd: int) -> bool:
    """Whether a native window still exists."""
    return bool(os.name == "nt" and hwnd and _user32.IsWindow(hwnd))


def is_minimized(hwnd: int) -> bool:
    """Read minimized state without changing the target window."""
    return bool(is_window(hwnd) and _user32.IsIconic(hwnd))


def ensure_overlay_visible(hwnd: int, topmost: bool, force: bool = False) -> bool:
    """Recover only our own window, without activating it or touching a target.

    Qt isVisible() does not describe z-order or native minimization. Reasserting
    TOPMOST keeps the overlay above another always-on-top target application.
    """
    if not is_window(hwnd):
        return False
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value != os.getpid():
        return False
    hidden = not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd)
    if hidden:
        _user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE also restores a minimized window.
    if topmost or hidden or force:
        # NOSIZE | NOMOVE | NOACTIVATE | SHOWWINDOW | NOOWNERZORDER.
        return bool(_user32.SetWindowPos(hwnd, -1 if topmost else 0, 0, 0, 0, 0, 0x253))
    return True


def request_redraw(hwnd: int) -> bool:
    """Asynchronously request a repaint without changing visibility or focus.

    A static surface may not emit an initial WGC frame on some Qt/driver
    combinations. Invalidation requests fresh rendering, never target input.
    Do not use RDW_UPDATENOW: an unresponsive application must not block ours.
    """
    if not is_window(hwnd) or is_minimized(hwnd):
        return False
    return bool(_user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0080 | 0x0400))


def window_identity(hwnd: int) -> tuple[int, int, int] | None:
    """Return PID, process creation FILETIME and UI thread ID for an HWND.

    PROCESS_QUERY_LIMITED_INFORMATION reads process metadata, not target memory.
    A zero creation time means Windows denied the optional metadata query.
    """
    if not is_window(hwnd):
        return None
    pid = wintypes.DWORD()
    thread_id = int(_user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
    if not thread_id or not pid.value:
        return None
    creation_time = 0
    process = _kernel32.OpenProcess(0x1000, False, pid.value)
    if process:
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if _kernel32.GetProcessTimes(process, *(ctypes.byref(value) for value in times)):
                creation_time = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            _kernel32.CloseHandle(process)
    return int(pid.value), creation_time, thread_id


def list_window_handles(*, include_own: bool = False) -> list[tuple[int, str]]:
    """Enumerate visible, titled, non-cloaked top-level windows."""
    if os.name != "nt":
        return []
    windows: list[tuple[int, str]] = []

    @_enum_callback
    def collect(hwnd: int, _parameter: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not include_own and pid.value == os.getpid():
            return True
        cloaked = wintypes.DWORD()
        if _dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0:
            if cloaked.value:
                return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, title, len(title))
        if title.value.strip():
            windows.append((int(hwnd), title.value.strip()))
        return True

    if not _user32.EnumWindows(collect, 0):
        raise OSError(ctypes.get_last_error(), "无法枚举 Windows 窗口。")
    return windows
