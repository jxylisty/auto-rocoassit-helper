# -*- coding: utf-8 -*-
"""帧差检测 — ROI 变动触发识别，静态帧复用缓存"""

import hashlib
from typing import Optional, Tuple, Dict

import cv2
import numpy as np


class FrameDiff:
    """ROI 区域变动检测器
    
    对关键 ROI 计算感知哈希，变动 < 阈值则复用上一帧结果。
    """

    def __init__(self, threshold: float = 0.05):
        self._threshold = threshold
        self._cache: Dict[str, Tuple[str, object]] = {}  # roi_id → (hash, result)

    def has_changed(self, roi_id: str, frame: np.ndarray,
                    roi: Tuple[int, int, int, int] = None) -> bool:
        """判断 ROI 区域是否变化
        
        Args:
            roi_id: 区域标识
            frame: 完整帧
            roi: (x, y, w, h) 像素坐标，None 则比较整帧
        
        Returns:
            True 表示变化超过阈值，需要重新识别
        """
        if roi:
            x, y, w, h = roi
            if x < 0 or y < 0 or w <= 0 or h <= 0:
                return True
            region = frame[y:y + h, x:x + w]
        else:
            region = frame

        if region.size == 0:
            return True

        h = self._phash(region)
        cached = self._cache.get(roi_id)
        if cached is None:
            self._cache[roi_id] = (h, None)
            return True

        old_h = cached[0]
        diff = self._hamming(old_h, h) / 64.0
        self._cache[roi_id] = (h, cached[1])
        return diff > self._threshold

    def get_cached(self, roi_id: str) -> Optional[object]:
        """获取缓存的上次识别结果"""
        cached = self._cache.get(roi_id)
        return cached[1] if cached else None

    def set_cache(self, roi_id: str, result: object):
        """更新缓存结果"""
        cached = self._cache.get(roi_id)
        if cached:
            self._cache[roi_id] = (cached[0], result)
        else:
            self._cache[roi_id] = ("", result)

    def reset(self):
        self._cache.clear()

    @staticmethod
    def _phash(img: np.ndarray) -> str:
        """感知哈希 (64-bit)"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        resized = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
        avg = resized.mean()
        bits = (resized > avg).flatten()
        return ''.join('1' if b else '0' for b in bits)

    @staticmethod
    def _hamming(h1: str, h2: str) -> int:
        return sum(c1 != c2 for c1, c2 in zip(h1, h2))