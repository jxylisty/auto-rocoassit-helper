"""Simple template matching helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from src.utils.image_io import imread_unicode


def load_grayscale_templates(directory: Path) -> dict[str, np.ndarray]:
    templates: dict[str, np.ndarray] = {}
    if not directory.exists():
        return templates

    for file in directory.iterdir():
        if file.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
            continue
        # 模板文件名常为中文(光.png/冰.png),必须走 unicode 安全读取
        image = imread_unicode(file, flags=cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        templates[file.stem] = image
    return templates


def preprocess_digit_roi(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def _match_score(image: np.ndarray, template: np.ndarray,
                 scales: tuple[float, ...] = (1.0, 0.8, 0.6, 0.45, 1.3)) -> float:
    """模板在图内的最佳匹配分数。

    - 多尺度:游戏窗口大小变化时图标尺寸跟着变,模板按多个比例缩放各试一次
    - 图比模板小时复制边缘补齐,避免整体缩放造成畸变
    """
    if image is None or image.size == 0 or template is None or template.size == 0:
        return 0.0

    best = 0.0
    for scale in scales:
        tpl = template if scale == 1.0 else cv2.resize(
            template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        th, tw = tpl.shape[:2]
        if th < 6 or tw < 6:
            continue
        canvas = image
        ih, iw = image.shape[:2]
        if th > ih or tw > iw:
            pad_h = max(0, th - ih) + 4
            pad_w = max(0, tw - iw) + 4
            canvas = cv2.copyMakeBorder(canvas, pad_h, pad_h, pad_w, pad_w,
                                        cv2.BORDER_REPLICATE)
        result = cv2.matchTemplate(canvas, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, _ = cv2.minMaxLoc(result)
        best = max(best, float(score))
    return best


def best_template_match(
    image: np.ndarray,
    templates: dict[str, np.ndarray],
    threshold: float = 0.65,
) -> tuple[str | None, float]:
    if image is None or image.size == 0 or not templates:
        return None, 0.0

    best_name = None
    best_score = 0.0

    for name, template in templates.items():
        score = _match_score(image, template)
        if score > best_score:
            best_score = score
            best_name = name

    if best_score < threshold:
        return None, best_score
    return best_name, best_score


def rank_template_matches(
    image: np.ndarray,
    templates: dict[str, np.ndarray],
    top_k: int = 5,
) -> list[dict[str, float | str]]:
    ranked: list[dict[str, float | str]] = []
    if image is None or image.size == 0:
        return ranked

    for name, template in templates.items():
        ranked.append({"name": name, "score": _match_score(image, template)})

    ranked.sort(key=lambda item: float(item["score"]), reverse=True)
    return ranked[:top_k]


def split_digit_boxes(binary_image: np.ndarray) -> list[tuple[int, int, int, int]]:
    contours, _ = cv2.findContours(binary_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if 4 <= w <= 80 and 10 <= h <= 100:
            boxes.append((x, y, w, h))
    boxes.sort(key=lambda box: box[0])
    return boxes
