"""Base data structures and interfaces for recognition modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Optional, Tuple, TypeVar

import numpy as np


T = TypeVar("T")


@dataclass(frozen=True)
class ROI:
    """Normalized ROI definition based on a frame's size."""

    name: str
    left: float
    top: float
    width: float
    height: float

    def to_pixels(self, frame_shape: Tuple[int, int, int] | Tuple[int, int]) -> tuple[int, int, int, int]:
        frame_height = frame_shape[0]
        frame_width = frame_shape[1]
        x = max(0, int(frame_width * self.left))
        y = max(0, int(frame_height * self.top))
        w = max(1, int(frame_width * self.width))
        h = max(1, int(frame_height * self.height))
        x2 = min(frame_width, x + w)
        y2 = min(frame_height, y + h)
        return x, y, x2, y2

    def crop(self, frame: np.ndarray) -> np.ndarray:
        x1, y1, x2, y2 = self.to_pixels(frame.shape)
        return frame[y1:y2, x1:x2].copy()


@dataclass
class RecognitionResult(Generic[T]):
    """Standard output of any vision reader."""

    reader_name: str
    value: Optional[T]
    confidence: float
    roi_name: str
    candidates: list[dict[str, Any]] = field(default_factory=list)
    debug: Dict[str, Any] = field(default_factory=dict)


class BaseReader(Generic[T]):
    """Common interface for all visual readers."""

    reader_name = "base"

    def __init__(self, roi: ROI):
        self.roi = roi

    def read(self, frame: np.ndarray) -> RecognitionResult[T]:
        raise NotImplementedError
