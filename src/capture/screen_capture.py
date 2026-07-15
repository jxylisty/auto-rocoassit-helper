"""Visible screen-region capture based on the game window rect."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import ImageGrab

from src.capture.window_capture import WindowInfo


class ScreenRegionCapture:
    def __init__(self, get_window_info):
        self.get_window_info = get_window_info

    def capture(self) -> np.ndarray:
        info: WindowInfo = self.get_window_info()
        if info.width <= 0 or info.height <= 0:
            raise RuntimeError("窗口尺寸无效，无法裁剪屏幕区域")

        left, top = info.rect[0], info.rect[1]
        width, height = info.width, info.height
        image = ImageGrab.grab(
            bbox=(left, top, left + width, top + height),
            all_screens=True,
        )
        return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
