"""Simple template matching helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import cv2
import numpy as np


def load_grayscale_templates(directory: Path) -> dict[str, np.ndarray]:
    templates: dict[str, np.ndarray] = {}
    if not directory.exists():
        return templates

    for file in directory.iterdir():
        if file.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
            continue
        image = cv2.imread(str(file), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        templates[file.stem] = image
    return templates


def preprocess_digit_roi(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


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
        resized = cv2.resize(template, (image.shape[1], image.shape[0]))
        result = cv2.matchTemplate(image, resized, cv2.TM_CCOEFF_NORMED)
        _, score, _, _ = cv2.minMaxLoc(result)
        if score > best_score:
            best_score = float(score)
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
        resized = cv2.resize(template, (image.shape[1], image.shape[0]))
        result = cv2.matchTemplate(image, resized, cv2.TM_CCOEFF_NORMED)
        _, score, _, _ = cv2.minMaxLoc(result)
        ranked.append({"name": name, "score": float(score)})

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
