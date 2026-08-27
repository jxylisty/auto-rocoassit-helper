# -*- coding: utf-8 -*-
"""快速截屏 — mss 单例 + 后台抓图线程 + 最新帧丢帧机制"""

from __future__ import annotations

import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False


class FastCapture:
    """高性能截屏：mss 单例持久化，支持后台线程持续抓取最新帧"""

    def __init__(self):
        self._sct = mss.mss() if HAS_MSS else None
        self._fps = 0.0
        self._last_time = 0.0
        # 后台抓图线程
        self._worker: Optional[CaptureWorker] = None

    @property
    def fps(self) -> float:
        return self._fps

    def capture(self, rect: Tuple[int, int, int, int] = None) -> Optional[np.ndarray]:
        """同步截取一帧 (rect = left, top, width, height)"""
        if not self._sct:
            return self._capture_pil(rect)
        t0 = time.perf_counter()
        try:
            if rect:
                left, top, w, h = rect
                monitor = {"left": left, "top": top, "width": w, "height": h}
            else:
                monitor = self._sct.monitors[1]
            img = self._sct.grab(monitor)
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_BGRA2BGR)
            self._update_fps(t0)
            return frame
        except Exception:
            return self._capture_pil(rect)

    def _capture_pil(self, rect) -> Optional[np.ndarray]:
        from PIL import ImageGrab
        try:
            if rect:
                left, top, w, h = rect
                img = ImageGrab.grab(bbox=(left, top, left + w, top + h))
            else:
                img = ImageGrab.grab()
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        except Exception:
            return None

    def start_worker(self, rect: Tuple[int, int, int, int], fps: int = 30):
        """启动后台抓图线程，持续刷新最新帧"""
        if self._worker and self._worker.is_alive():
            self._worker.update_rect(rect)
            return
        self._worker = CaptureWorker(self, rect, fps)
        self._worker.start()

    def stop_worker(self):
        """停止后台抓图线程"""
        if self._worker:
            self._worker.stop()
            self._worker = None

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """获取最新一帧（丢弃旧帧）"""
        if self._worker:
            return self._worker.get_frame()
        return None

    @staticmethod
    def encode_jpeg(frame: np.ndarray, max_width: int = 960, quality: int = 60) -> str:
        """降采样 + JPEG 压缩 → Base64 data URL（减少 80% IPC 传输）"""
        import base64
        h, w = frame.shape[:2]
        if max_width is not None and w > max_width:
            scale = max_width / w
            frame = cv2.resize(frame, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return ""
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")

    def close(self):
        """释放 mss 资源"""
        self.stop_worker()
        if self._sct:
            self._sct.close()
            self._sct = None

    def _update_fps(self, t0: float):
        t1 = time.perf_counter()
        if self._last_time > 0:
            dt = t1 - t0
            if dt > 0:
                self._fps = 0.9 * self._fps + 0.1 / dt
        self._last_time = t1


class CaptureWorker(threading.Thread):
    """后台抓图线程：持续以指定 FPS 抓取画面，只保留最新帧"""

    def __init__(self, capture: FastCapture, rect: Tuple[int, int, int, int], fps: int = 30):
        super().__init__(daemon=True, name="CaptureWorker")
        self._capture = capture
        self._rect = rect
        self._fps = fps
        self._interval = 1.0 / fps
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._running.set()

    def update_rect(self, rect: Tuple[int, int, int, int]):
        """更新抓图区域"""
        self._rect = rect

    def get_frame(self) -> Optional[np.ndarray]:
        """获取最新帧（线程安全）"""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def stop(self):
        self._running.clear()
        self.join(timeout=2.0)

    def run(self):
        while self._running.is_set():
            try:
                frame = self._capture.capture(rect=self._rect)
                if frame is not None and frame.size > 0:
                    with self._lock:
                        self._frame = frame
            except Exception:
                pass
            time.sleep(self._interval)
