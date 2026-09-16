# -*- coding: utf-8 -*-
"""Export configured ROI crops from a screenshot."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

from src.perception.vision_pipeline import load_roi_config  # noqa: E402
from src.utils.image_io import imread_unicode, imwrite_unicode  # noqa: E402


def main() -> None:
    image_path = None
    frame = None

    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        image_path = Path(sys.argv[1])
        frame = imread_unicode(image_path)
    else:
        # 寻找最新截图
        shot_dir = PROJECT_ROOT / "data" / "screenshots"
        if shot_dir.exists():
            pngs = sorted(shot_dir.glob("*.png"))
            if pngs:
                image_path = pngs[-1]
                frame = imread_unicode(image_path)

    if frame is None:
        # 直接抓取当前游戏窗口
        from src.capture.window_capture import find_window
        from src.capture.fast_capture import FastCapture
        info = find_window(class_name="UnrealWindow") or find_window()
        if info and info.width >= 50:
            fc = FastCapture()
            l, t, r, b = info.rect
            frame = fc.capture(rect=(l, t, r - l, b - t))
            image_path = Path("live_game.png")

    if frame is None:
        raise SystemExit("❌ 未找到有效截图且游戏窗口未运行")

    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else PROJECT_ROOT / "data" / "vision" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    rois = load_roi_config()

    stem = image_path.stem if image_path else "export"
    count = 0
    for roi_name, roi in rois.items():
        crop = roi.crop(frame)
        if crop.size == 0:
            continue
        target = output_dir / f"{stem}_{roi_name}.png"
        if imwrite_unicode(target, crop):
            print(f"✅ 已导出切片: {target.name}")
            count += 1

    print(f"🎉 导出完成: 共 {count} 个 ROI 切片保存至 {output_dir}")


if __name__ == "__main__":
    main()
