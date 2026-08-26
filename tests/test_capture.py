# -*- coding: utf-8 -*-
"""截图与图像 IO 的离线测试（不依赖游戏窗口/真实屏幕）"""

import numpy as np
import pytest

from src.ocr.base import ROI
from src.utils.image_io import imread_unicode, imwrite_unicode


class TestROI:
    """ROI 归一化坐标换算与裁剪"""

    FRAME = np.zeros((1000, 1920, 3), dtype=np.uint8)

    def test_to_pixels(self):
        roi = ROI(name="t", left=0.5, top=0.25, width=0.25, height=0.5)
        x1, y1, x2, y2 = roi.to_pixels(self.FRAME.shape)
        assert (x1, y1, x2, y2) == (960, 250, 1440, 750)

    def test_to_pixels_clamped(self):
        # 越界 ROI 被夹在画面内
        roi = ROI(name="t", left=0.95, top=0.95, width=0.2, height=0.2)
        x1, y1, x2, y2 = roi.to_pixels(self.FRAME.shape)
        assert 0 <= x1 < x2 <= 1920
        assert 0 <= y1 < y2 <= 1000

    def test_crop_shape(self):
        frame = np.arange(1000 * 1920 * 3, dtype=np.uint8).reshape(1000, 1920, 3)
        roi = ROI(name="t", left=0.1, top=0.1, width=0.5, height=0.4)
        crop = roi.crop(frame)
        assert crop.shape == (400, 960, 3)
        # 裁剪内容与原帧对应区域一致
        np.testing.assert_array_equal(crop, frame[100:500, 192:1152])


class TestImageIO:
    """中文路径图像读写"""

    def test_roundtrip(self, tmp_path):
        image = np.random.randint(0, 255, (60, 80, 3), dtype=np.uint8)
        path = tmp_path / "中文目录" / "测试图.png"
        path.parent.mkdir(parents=True)
        assert imwrite_unicode(path, image) is True

        loaded = imread_unicode(path)
        assert loaded is not None
        assert loaded.shape == (60, 80, 3)

    def test_read_missing(self, tmp_path):
        assert imread_unicode(tmp_path / "不存在.png") is None
