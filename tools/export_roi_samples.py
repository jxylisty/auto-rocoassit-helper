# -*- coding: utf-8 -*-
"""Export configured ROI crops from a screenshot."""

from __future__ import annotations

import sys
from pathlib import Path

from src.analysis.vision_pipeline import load_roi_config
from src.utils.image_io import imread_unicode, imwrite_unicode


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("用法: python export_roi_samples.py <image_path> [output_dir]")

    image_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/vision/exports")

    if not image_path.exists():
        raise SystemExit(f"截图不存在: {image_path}")

    frame = imread_unicode(image_path)
    if frame is None:
        raise SystemExit(f"无法读取截图: {image_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    rois = load_roi_config()

    for roi_name, roi in rois.items():
        crop = roi.crop(frame)
        target = output_dir / f"{image_path.stem}_{roi_name}.png"
        if not imwrite_unicode(target, crop):
            raise SystemExit(f"保存失败: {target}")
        print(f"saved: {target}")


if __name__ == "__main__":
    main()
