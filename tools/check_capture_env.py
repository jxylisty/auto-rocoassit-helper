# -*- coding: utf-8 -*-
"""Basic diagnostics for Win32 capture capabilities."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def check_ctypes_user32() -> None:
    print_header("ctypes / user32")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    enum_windows = user32.EnumWindows
    enum_windows.argtypes = [callback_type, wintypes.LPARAM]
    enum_windows.restype = wintypes.BOOL

    count = {"value": 0}

    @callback_type
    def callback(hwnd, lparam):
        count["value"] += 1
        return True

    result = enum_windows(callback, 0)
    print(f"EnumWindows result: {result}")
    print(f"EnumWindows last_error: {ctypes.get_last_error()}")
    print(f"Enumerated windows: {count['value']}")

    foreground = user32.GetForegroundWindow()
    print(f"GetForegroundWindow: {foreground}")
    print(f"GetForegroundWindow last_error: {ctypes.get_last_error()}")


def check_pywin32() -> None:
    print_header("pywin32")
    try:
        import win32gui

        print(f"win32gui module: {getattr(win32gui, '__file__', 'n/a')}")
        try:
            hwnd = win32gui.GetForegroundWindow()
            print(f"win32gui.GetForegroundWindow: {hwnd}")
        except Exception as exc:
            print(f"win32gui.GetForegroundWindow failed: {exc}")

        try:
            handles = []

            def enum_handler(hwnd, extra):
                handles.append(hwnd)
                return True

            win32gui.EnumWindows(enum_handler, None)
            print(f"win32gui.EnumWindows count: {len(handles)}")
        except Exception as exc:
            print(f"win32gui.EnumWindows failed: {exc}")
    except Exception as exc:
        print(f"Import pywin32 failed: {exc}")


def main() -> None:
    print("Python:", sys.version)
    print("Executable:", sys.executable)
    check_ctypes_user32()
    check_pywin32()

    print_header("结论提示")
    print("如果 EnumWindows 和 GetForegroundWindow 都返回 0，通常不是截图代码问题，而是当前 Python 进程不在交互桌面会话。")
    print("如果 ctypes 正常但 pywin32 异常，优先重装 pywin32 或执行 pywin32_postinstall。")
    print("如果 PrintWindow 能抓到图但 BitBlt 不稳定，说明后台窗口模式可行。")


if __name__ == "__main__":
    main()
