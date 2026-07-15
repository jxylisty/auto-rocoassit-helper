# -*- coding: utf-8 -*-
"""测试屏幕捕获模块"""

import pytest
from src.capture.screen_capture import ScreenCapture


class TestScreenCapture:
    """屏幕捕获测试"""

    def test_init(self):
        """测试初始化"""
        capture = ScreenCapture()
        assert capture is not None

    def test_capture(self):
        """测试截图"""
        capture = ScreenCapture()
        frame = capture.capture()
        assert frame is not None
        assert frame.shape[2] == 3  # RGB