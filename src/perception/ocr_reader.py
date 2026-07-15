"""Concrete readers for damage, energy, avatar and element recognition."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.ocr.base import BaseReader, ROI, RecognitionResult
from src.ocr.template_matcher import (
    best_template_match,
    load_grayscale_templates,
    preprocess_digit_roi,
    rank_template_matches,
    split_digit_boxes,
)


ASSET_ROOT = Path("data/vision")


class DigitSequenceReader(BaseReader[int]):
    """Template-based digit reader for stable HUD numbers."""

    reader_name = "digit_sequence"

    def __init__(self, roi: ROI, template_dir: Path, min_score: float = 0.6):
        super().__init__(roi)
        self.templates = load_grayscale_templates(template_dir)
        self.min_score = min_score

    def read(self, frame: np.ndarray) -> RecognitionResult[int]:
        cropped = self.roi.crop(frame)
        binary = preprocess_digit_roi(cropped)
        boxes = split_digit_boxes(binary)
        digits: list[str] = []
        candidates: list[dict[str, float | str]] = []

        for x, y, w, h in boxes:
            roi_image = binary[y : y + h, x : x + w]
            name, score = best_template_match(roi_image, self.templates, threshold=self.min_score)
            if name is None or not name.isdigit():
                continue
            digits.append(name)
            candidates.append({"digit": name, "score": score, "box": (x, y, w, h)})

        value = int("".join(digits)) if digits else None
        confidence = min((float(item["score"]) for item in candidates), default=0.0)
        return RecognitionResult(
            reader_name=self.reader_name,
            value=value,
            confidence=confidence,
            roi_name=self.roi.name,
            candidates=candidates,
            debug={"box_count": len(boxes)},
        )


class DamageReader(DigitSequenceReader):
    reader_name = "damage_reader"

    def __init__(self, roi: ROI):
        super().__init__(roi, ASSET_ROOT / "digits")


class EnergyReader(DigitSequenceReader):
    reader_name = "energy_reader"

    def __init__(self, roi: ROI):
        super().__init__(roi, ASSET_ROOT / "digits")


class AvatarMatcher(BaseReader[str]):
    """Top-k avatar candidate matcher."""

    reader_name = "avatar_matcher"

    def __init__(self, roi: ROI):
        super().__init__(roi)
        self.templates = load_grayscale_templates(ASSET_ROOT / "avatars")

    def read(self, frame: np.ndarray) -> RecognitionResult[str]:
        cropped = self.roi.crop(frame)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        ranked = rank_template_matches(gray, self.templates, top_k=5)
        best = ranked[0] if ranked else {"name": None, "score": 0.0}
        return RecognitionResult(
            reader_name=self.reader_name,
            value=best["name"],
            confidence=float(best["score"]),
            roi_name=self.roi.name,
            candidates=ranked,
        )


class ElementMatcher(BaseReader[list[str]]):
    """Attribute icon matcher. Supports one or two element guesses."""

    reader_name = "element_matcher"

    def __init__(self, roi: ROI):
        super().__init__(roi)
        self.templates = load_grayscale_templates(ASSET_ROOT / "elements")

    def read(self, frame: np.ndarray) -> RecognitionResult[list[str]]:
        cropped = self.roi.crop(frame)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        ranked = rank_template_matches(gray, self.templates, top_k=4)
        selected = [str(item["name"]) for item in ranked if float(item["score"]) >= 0.65][:2]
        confidence = float(ranked[0]["score"]) if ranked else 0.0
        return RecognitionResult(
            reader_name=self.reader_name,
            value=selected or None,
            confidence=confidence,
            roi_name=self.roi.name,
            candidates=ranked,
        )
