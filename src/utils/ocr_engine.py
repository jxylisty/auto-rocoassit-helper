# -*- coding: utf-8 -*-
"""
统一 OCR 引擎 —— RapidOCR(ONNX) 单例适配层

替代 Tesseract(体积 -230MB)与 PaddleOCR(体积 -1GB)。
全项目所有文字识别都从这里拿引擎,便于将来整体更换 OCR 后端。

接口:
    read_texts(crop) -> list[dict]      # [(text, score, box)] 按置信度降序
    read_best(crop)  -> tuple[str|None, float]   # 最佳单条 (text, score)
"""

from __future__ import annotations

import threading

from typing import Optional

import cv2
import numpy as np

_ocr = None
_lock = threading.Lock()


def get_ocr():
    """RapidOCR 懒加载单例(首次约1秒,之后复用)。

    use_cls=False: 游戏 HUD 文字永不旋转,角度分类纯属浪费(~0.5s/次)。
    """
    global _ocr
    if _ocr is None:
        with _lock:
            if _ocr is None:
                from rapidocr_onnxruntime import RapidOCR
                _ocr = RapidOCR(use_cls=False)
    return _ocr


def read_texts(crop: np.ndarray) -> list[dict]:
    """识别图中所有文字块。小图自动放大(游戏HUD字普遍 12~20px 高)。"""
    if crop is None or crop.size == 0:
        return []
    img = crop
    if img.shape[0] < 28:  # 小字放大利于检测
        scale = max(2.0, 28.0 / img.shape[0])
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    result, _ = get_ocr()(img)
    items = []
    if result:
        for box, text, score in result:
            items.append({"text": str(text), "score": float(score), "box": box})
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def read_best(crop: np.ndarray) -> tuple[Optional[str], float]:
    """返回最佳单条文字与置信度"""
    items = read_texts(crop)
    if not items:
        return None, 0.0
    best = items[0]
    return best["text"], best["score"]


def read_combined(crop: np.ndarray) -> tuple[Optional[str], float]:
    """把图中多个文字块拼成一个字符串(适合数字序列/名字)"""
    items = read_texts(crop)
    if not items:
        return None, 0.0
    # 按从左到右排序拼接
    items.sort(key=lambda x: min(p[0] for p in x["box"]) if x.get("box") else 0)
    text = "".join(it["text"] for it in items)
    score = min(it["score"] for it in items)
    return text, score
