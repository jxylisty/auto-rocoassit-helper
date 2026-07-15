"""Image I/O helpers that support Windows Unicode paths."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread_unicode(path: str | Path, flags: int = cv2.IMREAD_COLOR):
    file_path = Path(path)
    if not file_path.exists():
        return None
    data = np.fromfile(str(file_path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite_unicode(path: str | Path, image) -> bool:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = file_path.suffix.lower() or ".png"
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    ok, encoded = cv2.imencode(ext, image)
    if not ok:
        return False
    encoded.tofile(str(file_path))
    return True
