# -*- coding: utf-8 -*-
"""感知模块离线测试（合成图像,不依赖模板库与游戏）"""

import numpy as np
import cv2
import pytest

from src.ocr.base import ROI
from src.perception.template_matcher import (
    best_template_match,
    load_grayscale_templates,
    preprocess_digit_roi,
    rank_template_matches,
    split_digit_boxes,
)


def _make_frame(text: str, size=(200, 400)) -> np.ndarray:
    """生成黑底白数字/字符画面"""
    img = np.zeros(size, dtype=np.uint8)
    cv2.putText(img, text, (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 3.0, 255, 6)
    return img


class TestTemplateMatcher:

    def test_load_templates(self, tmp_path):
        for name in ("a", "b"):
            cv2.imwrite(str(tmp_path / f"{name}.png"), np.full((20, 20), 128, np.uint8))
        (tmp_path / "readme.txt").write_text("not an image")

        templates = load_grayscale_templates(tmp_path)
        assert set(templates.keys()) == {"a", "b"}

    def test_load_templates_missing_dir(self, tmp_path):
        assert load_grayscale_templates(tmp_path / "nope") == {}

    def test_best_match_identical(self):
        frame = _make_frame("7")
        templates = {"7": frame.copy(), "1": _make_frame("1")}
        name, score = best_template_match(frame, templates)
        assert name == "7"
        assert score > 0.9

    def test_best_match_below_threshold(self):
        frame = _make_frame("7")
        templates = {"1": _make_frame("1")}
        name, score = best_template_match(frame, templates, threshold=0.99)
        assert name is None

    def test_rank_ordering(self):
        frame = _make_frame("3")
        templates = {"3": frame.copy(), "8": _make_frame("8"), "1": _make_frame("1")}
        ranked = rank_template_matches(frame, templates, top_k=3)
        assert ranked[0]["name"] == "3"
        scores = [item["score"] for item in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_rank_empty_image(self):
        assert rank_template_matches(None, {"a": np.zeros((5, 5), np.uint8)}) == []


class TestDigitProcessing:

    def test_preprocess_binary(self):
        color = cv2.cvtColor(_make_frame("42"), cv2.COLOR_GRAY2BGR)
        binary = preprocess_digit_roi(color)
        assert binary.ndim == 2
        assert set(np.unique(binary)).issubset({0, 255})

    def test_split_digit_boxes(self):
        binary = _make_frame("42")
        boxes = split_digit_boxes(binary)
        assert len(boxes) == 2
        # 按从左到右排序
        assert boxes[0][0] < boxes[1][0]
