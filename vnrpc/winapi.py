from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_EnumWindows = user32.EnumWindows
_EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
_EnumWindows.restype = wintypes.BOOL

_GetWindowTextLengthW = user32.GetWindowTextLengthW
_GetWindowTextLengthW.argtypes = [wintypes.HWND]
_GetWindowTextLengthW.restype = ctypes.c_int

_GetWindowTextW = user32.GetWindowTextW
_GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_GetWindowTextW.restype = ctypes.c_int

_IsWindowVisible = user32.IsWindowVisible
_IsWindowVisible.argtypes = [wintypes.HWND]
_IsWindowVisible.restype = wintypes.BOOL

_IsWindow = user32.IsWindow
_IsWindow.argtypes = [wintypes.HWND]
_IsWindow.restype = wintypes.BOOL

_GetWindow = user32.GetWindow
_GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_GetWindow.restype = wintypes.HWND

_GetWindowLongW = user32.GetWindowLongW
_GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_GetWindowLongW.restype = ctypes.c_long

_GetClassNameW = user32.GetClassNameW
_GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_GetClassNameW.restype = ctypes.c_int

_GetWindowThreadProcessId = user32.GetWindowThreadProcessId
_GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_GetWindowThreadProcessId.restype = wintypes.DWORD

_GetForegroundWindow = user32.GetForegroundWindow
_GetForegroundWindow.restype = wintypes.HWND

_OpenProcess = kernel32.OpenProcess
_OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_OpenProcess.restype = wintypes.HANDLE

_CloseHandle = kernel32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]
_CloseHandle.restype = wintypes.BOOL

_QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
_QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_QueryFullProcessImageNameW.restype = wintypes.BOOL

GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    exe_path: str
    class_name: str

    @property
    def exe(self) -> str:
        return self.exe_path.rsplit("\\", 1)[-1] if self.exe_path else ""


def _window_title(hwnd: int) -> str:
    length = _GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _GetClassNameW(hwnd, buf, 256)
    return buf.value


def _process_image_path(pid: int) -> str:
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if _QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        _CloseHandle(handle)


def _pid_for_window(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_window(hwnd: int) -> bool:
    return bool(_IsWindow(hwnd))


def get_window_title(hwnd: int) -> str:
    return _window_title(hwnd)


def foreground_window() -> int:
    return _GetForegroundWindow()


def list_top_level_windows(include_toolwindows: bool = False) -> list[WindowInfo]:
    """Return visible, top-level, titled windows (roughly the Alt-Tab set)."""
    results: list[WindowInfo] = []
    seen: set[int] = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if not _IsWindowVisible(hwnd):
            return True
        if _GetWindow(hwnd, GW_OWNER):
            return True  # owned windows (dialogs) -> skip
        if not include_toolwindows:
            ex_style = _GetWindowLongW(hwnd, GWL_EXSTYLE)
            if ex_style & WS_EX_TOOLWINDOW:
                return True
        title = _window_title(hwnd)
        if not title.strip():
            return True
        if hwnd in seen:
            return True
        seen.add(hwnd)
        pid = _pid_for_window(hwnd)
        results.append(
            WindowInfo(
                hwnd=int(hwnd),
                title=title,
                pid=pid,
                exe_path=_process_image_path(pid),
                class_name=_class_name(hwnd),
            )
        )
        return True

    _EnumWindows(_cb, 0)
    return results
