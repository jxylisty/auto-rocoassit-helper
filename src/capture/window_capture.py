"""Win32 window helpers and fallback capture backends."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np
import win32con
import win32gui
import win32ui

try:
    import win32api
except ImportError:  # pragma: no cover
    win32api = None


PW_RENDERFULLCONTENT = 0x00000002
DWMWA_EXTENDED_FRAME_BOUNDS = 9


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


enable_dpi_awareness()


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    rect: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return max(0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> int:
        return max(0, self.rect[3] - self.rect[1])


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    try:
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            int(hwnd),
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if result == 0:
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    return win32gui.GetWindowRect(hwnd)


def _default_title_matcher(title: str) -> bool:
    return "洛克王国" in title


def find_window(
    title_matcher: Optional[Callable[[str], bool]] = None,
    class_name: Optional[str] = None,
) -> Optional[WindowInfo]:
    matcher = title_matcher or _default_title_matcher
    found: Optional[WindowInfo] = None

    def enum_handler(hwnd: int, _: int) -> None:
        nonlocal found
        if found is not None:
            return
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        hwnd_class = win32gui.GetClassName(hwnd)
        if class_name and hwnd_class != class_name:
            return
        if title and matcher(title):
            found = WindowInfo(
                hwnd=hwnd,
                title=title,
                class_name=hwnd_class,
                rect=get_window_rect(hwnd),
            )

    win32gui.EnumWindows(enum_handler, 0)
    return found


def get_foreground_hwnd() -> int:
    return int(win32gui.GetForegroundWindow())


class WindowCapture:
    def __init__(self, hwnd: int):
        self.hwnd = hwnd

    def get_info(self) -> WindowInfo:
        if not win32gui.IsWindow(self.hwnd):
            raise RuntimeError(f"窗口句柄无效: {self.hwnd}")
        return WindowInfo(
            hwnd=self.hwnd,
            title=win32gui.GetWindowText(self.hwnd).strip(),
            class_name=win32gui.GetClassName(self.hwnd),
            rect=get_window_rect(self.hwnd),
        )

    def is_foreground(self) -> bool:
        return get_foreground_hwnd() == self.hwnd

    def bring_to_front(self) -> None:
        if not win32gui.IsWindow(self.hwnd):
            raise RuntimeError(f"窗口句柄无效: {self.hwnd}")
        if win32gui.IsIconic(self.hwnd):
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(self.hwnd)

    def capture(self, mode: str = "auto") -> np.ndarray:
        info = self.get_info()
        if info.width <= 0 or info.height <= 0:
            raise RuntimeError("窗口尺寸无效，无法截图")

        errors: list[str] = []
        if mode in {"auto", "printwindow"}:
            try:
                frame = self._capture_printwindow(info)
                if self._is_valid_frame(frame):
                    return frame
                errors.append("PrintWindow 返回了空白或无效画面")
            except Exception as exc:
                errors.append(f"PrintWindow 失败: {exc}")
            if mode == "printwindow":
                raise RuntimeError("; ".join(errors))

        if mode in {"auto", "bitblt"}:
            try:
                frame = self._capture_bitblt(info)
                if self._is_valid_frame(frame):
                    return frame
                errors.append("BitBlt 返回了空白或无效画面")
            except Exception as exc:
                errors.append(f"BitBlt 失败: {exc}")

        raise RuntimeError("; ".join(errors) if errors else "截图失败")

    def _capture_printwindow(self, info: WindowInfo) -> np.ndarray:
        hwnd_dc = win32gui.GetWindowDC(info.hwnd)
        if not hwnd_dc:
            raise RuntimeError("GetWindowDC 失败")
        src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        mem_dc = src_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(src_dc, info.width, info.height)
            mem_dc.SelectObject(bitmap)
            result = win32gui.PrintWindow(info.hwnd, mem_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
            if result != 1:
                result = win32gui.PrintWindow(info.hwnd, mem_dc.GetSafeHdc(), 0)
            if result != 1:
                raise RuntimeError(f"PrintWindow 返回值异常: {result}")
            bmp_info = bitmap.GetInfo()
            bmp_bytes = bitmap.GetBitmapBits(True)
            frame = np.frombuffer(bmp_bytes, dtype=np.uint8)
            frame = frame.reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            mem_dc.DeleteDC()
            src_dc.DeleteDC()
            win32gui.ReleaseDC(info.hwnd, hwnd_dc)

    def _capture_bitblt(self, info: WindowInfo) -> np.ndarray:
        left, top, right, bottom = info.rect
        hwnd_dc = win32gui.GetWindowDC(info.hwnd)
        if not hwnd_dc:
            raise RuntimeError("GetWindowDC 失败")
        src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        mem_dc = src_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(src_dc, info.width, info.height)
            mem_dc.SelectObject(bitmap)
            mem_dc.BitBlt((0, 0), (info.width, info.height), src_dc, (0, 0), win32con.SRCCOPY)
            bmp_info = bitmap.GetInfo()
            bmp_bytes = bitmap.GetBitmapBits(True)
            frame = np.frombuffer(bmp_bytes, dtype=np.uint8)
            frame = frame.reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            if win32api is not None:
                monitor = win32api.MonitorFromRect((left, top, right, bottom), win32con.MONITOR_DEFAULTTONEAREST)
                monitor_info = win32api.GetMonitorInfo(monitor)
                if left < monitor_info["Monitor"][0] or top < monitor_info["Monitor"][1]:
                    raise RuntimeError("窗口坐标异常，可能跨屏或已离开可见区域")
            return frame
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            mem_dc.DeleteDC()
            src_dc.DeleteDC()
            win32gui.ReleaseDC(info.hwnd, hwnd_dc)

    @staticmethod
    def _is_valid_frame(frame: np.ndarray) -> bool:
        if frame is None or frame.size == 0:
            return False
        if frame.shape[0] < 10 or frame.shape[1] < 10:
            return False
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(gray.std()) > 3.0
