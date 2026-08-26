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
    exclude_own_process: bool = True,
) -> Optional[WindowInfo]:
    """查找目标窗口

    Args:
        title_matcher: 标题匹配函数,默认包含"洛克王国"
        class_name: 限定窗口类名(游戏为 UnrealWindow)
        exclude_own_process: 排除本进程的窗口。
            控制台标题同样含"洛克王国",不排除会把自己当游戏窗口(截到自己)。
    """
    import os

    try:
        import win32process
        own_pid = os.getpid() if exclude_own_process else -1
    except ImportError:
        own_pid = -1

    matcher = title_matcher or _default_title_matcher
    found: Optional[WindowInfo] = None

    def enum_handler(hwnd: int, _: int) -> None:
        nonlocal found
        if found is not None:
            return
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return
        if own_pid != -1:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == own_pid:
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
        try:
            win32gui.SetForegroundWindow(self.hwnd)
            return
        except Exception:
            pass
        # Windows 前台锁:后台进程不能直接抢前台,附加到前台窗口线程的输入队列后再切
        try:
            import win32api
            import win32process
            fg_hwnd = win32gui.GetForegroundWindow()
            fg_tid = win32process.GetWindowThreadProcessId(fg_hwnd)[0]
            cur_tid = win32api.GetCurrentThreadId()
            win32process.AttachThreadInput(cur_tid, fg_tid, True)
            try:
                win32gui.SetForegroundWindow(self.hwnd)
            finally:
                win32process.AttachThreadInput(cur_tid, fg_tid, False)
        except Exception:
            pass
        # 最后兜底:最小化再还原,系统发起的还原通常能拿到前台
        try:
            if win32gui.GetForegroundWindow() != self.hwnd:
                win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        except Exception:
            pass

    def capture(self, mode: str = "auto") -> np.ndarray:
        if not win32gui.IsWindow(self.hwnd):
            raise RuntimeError("窗口已关闭")
        if win32gui.IsIconic(self.hwnd):
            raise RuntimeError("游戏窗口处于最小化状态，请先还原窗口再截图")

        info = self.get_info()
        if info.width <= 0 or info.height <= 0:
            raise RuntimeError("窗口尺寸无效，无法截图")

        def _frame_std(f: np.ndarray) -> float:
            try:
                return float(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).std())
            except Exception:
                return -1.0

        errors: list[str] = []
        if mode in {"auto", "printwindow"}:
            try:
                frame = self._capture_printwindow(info)
                if self._is_valid_frame(frame):
                    return frame
                errors.append(
                    f"PrintWindow 画面全黑(std={_frame_std(frame):.1f}),窗口可能被遮挡/独占全屏/加载中")
            except Exception as exc:
                errors.append(f"PrintWindow 失败: {exc}")
            if mode == "printwindow":
                raise RuntimeError("; ".join(errors))

        if mode in {"auto", "bitblt"}:
            try:
                frame = self._capture_bitblt(info)
                if self._is_valid_frame(frame):
                    return frame
                errors.append(
                    f"BitBlt 画面全黑(std={_frame_std(frame):.1f}),窗口区域被其他窗口遮挡")
            except Exception as exc:
                errors.append(f"BitBlt 失败: {exc}")

        raise RuntimeError(
            f"截图失败(窗口区域={info.rect}): " + "; ".join(errors if errors else ["未知原因"]))

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
            # 部分 pywin32 版本没有 win32gui.PrintWindow,用 ctypes 直调更通用
            user32 = ctypes.windll.user32
            hdc = mem_dc.GetSafeHdc()
            result = user32.PrintWindow(info.hwnd, hdc, PW_RENDERFULLCONTENT)
            if result != 1:
                result = user32.PrintWindow(info.hwnd, hdc, 0)
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
