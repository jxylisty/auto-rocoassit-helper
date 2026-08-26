# -*- coding: utf-8 -*-
"""快速截屏 — Win32 BitBlt 优先，mss 回退"""

from __future__ import annotations

import time
from typing import Optional, Tuple

import cv2
import numpy as np

try:
    import win32gui
    import win32ui
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False


class FastCapture:
    """高性能截屏：BitBlt → mss → PIL 逐级回退"""

    def __init__(self, hwnd: int = None):
        self._hwnd = hwnd
        self._mss = None
        self._last_time = 0.0
        self._fps = 0.0

    @property
    def fps(self) -> float:
        return self._fps

    def capture(self, hwnd: int = None, rect: Tuple[int, int, int, int] = None) -> Optional[np.ndarray]:
        """截取窗口/区域，返回 BGR numpy array"""
        t0 = time.perf_counter()
        hwnd = hwnd or self._hwnd

        # 1. Win32 BitBlt (最快)
        if HAS_WIN32 and hwnd:
            frame = self._capture_bitblt(hwnd, rect)
            if frame is not None:
                self._update_fps(t0)
                return frame

        # 2. mss (跨平台，快速)
        if HAS_MSS:
            frame = self._capture_mss(rect)
            if frame is not None:
                self._update_fps(t0)
                return frame

        # 3. PIL (最慢，兜底)
        from PIL import ImageGrab
        if rect:
            img = ImageGrab.grab(bbox=rect)
        else:
            img = ImageGrab.grab()
        frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        self._update_fps(t0)
        return frame

    def _capture_bitblt(self, hwnd: int, rect: Tuple[int, int, int, int] = None) -> Optional[np.ndarray]:
        """Win32 BitBlt 窗口捕获"""
        try:
            if rect:
                left, top, right, bottom = rect
            else:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)

            w, h = right - left, bottom - top
            if w <= 0 or h <= 0:
                return None

            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bitmap)
            save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)

            bmp_info = bitmap.GetInfo()
            bmp_bits = bitmap.GetBitmapBits(True)
            frame = np.frombuffer(bmp_bits, dtype=np.uint8).reshape(
                (bmp_info['bmHeight'], bmp_info['bmWidth'], 4))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            return frame
        except Exception:
            return None

    def _capture_mss(self, rect: Tuple[int, int, int, int] = None) -> Optional[np.ndarray]:
        """mss 屏幕捕获"""
        try:
            if self._mss is None:
                self._mss = mss.mss()
            if rect:
                monitor = {"left": rect[0], "top": rect[1],
                           "width": rect[2] - rect[0], "height": rect[3] - rect[1]}
            else:
                monitor = self._mss.monitors[1]  # 主屏幕
            img = self._mss.grab(monitor)
            return cv2.cvtColor(np.array(img), cv2.COLOR_BGRA2BGR)
        except Exception:
            return None

    def _update_fps(self, t0: float):
        t1 = time.perf_counter()
        if self._last_time > 0:
            self._fps = 0.9 * self._fps + 0.1 / (t1 - t0)
        self._last_time = t1