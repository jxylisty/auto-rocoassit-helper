# -*- coding: utf-8 -*-
"""Run the vision pipeline on a local screenshot or live game window."""

from __future__ import annotations

import json
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

from src.perception.vision_pipeline import VisionPipeline
from src.utils.image_io import imread_unicode


def main() -> None:
    frame = None
    image_path = None

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
            print(f"📸 实时抓取游戏窗口: {info.title} ({info.width}x{info.height})")

    if frame is None:
        raise SystemExit("❌ 未找到有效截图且游戏窗口未运行")

    if image_path:
        print(f"📸 使用截图: {image_path.name}")

    pipeline = VisionPipeline()
    result = pipeline.analyze(frame)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
