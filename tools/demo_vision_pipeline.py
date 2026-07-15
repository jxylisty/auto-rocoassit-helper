# -*- coding: utf-8 -*-
"""Run the vision pipeline on a local screenshot."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.analysis.vision_pipeline import VisionPipeline
from src.utils.image_io import imread_unicode


def main() -> None:
    image_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/vision/samples/sample.png")
    if not image_path.exists():
        raise SystemExit(f"截图不存在: {image_path}")

    frame = imread_unicode(image_path)
    if frame is None:
        raise SystemExit(f"无法读取截图: {image_path}")

    pipeline = VisionPipeline()
    result = pipeline.analyze(frame)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
