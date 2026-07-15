"""Battle-state detector based on simple UI icon matching."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.ocr.base import ROI
from src.ocr.template_matcher import load_grayscale_templates, rank_template_matches


ASSET_ROOT = Path("data/vision/battle")


class BattleDetector:
    """Detect whether the game is currently in battle."""

    def __init__(
        self,
        left_roi: ROI,
        right_roi: ROI,
        threshold: float = 0.72,
    ) -> None:
        self.left_roi = left_roi
        self.right_roi = right_roi
        self.threshold = threshold
        self.left_templates = load_grayscale_templates(ASSET_ROOT / "left")
        self.right_templates = load_grayscale_templates(ASSET_ROOT / "right")

    def detect(self, frame: np.ndarray) -> dict[str, object]:
        left_score = self._best_score(frame, self.left_roi, self.left_templates)
        right_score = self._best_score(frame, self.right_roi, self.right_templates)

        left_ready = bool(self.left_templates)
        right_ready = bool(self.right_templates)

        if left_ready and right_ready:
            in_battle = left_score >= self.threshold and right_score >= self.threshold
        elif left_ready:
            in_battle = left_score >= self.threshold
        elif right_ready:
            in_battle = right_score >= self.threshold
        else:
            # Without templates, stay idle instead of forcing battle mode.
            in_battle = False

        return {
            "in_battle": in_battle,
            "left_score": left_score,
            "right_score": right_score,
            "configured": left_ready or right_ready,
        }

    @staticmethod
    def _best_score(frame: np.ndarray, roi: ROI, templates: dict[str, np.ndarray]) -> float:
        if not templates:
            return 0.0
        cropped = roi.crop(frame)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        ranked = rank_template_matches(gray, templates, top_k=1)
        return float(ranked[0]["score"]) if ranked else 0.0
