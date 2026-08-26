# -*- coding: utf-8 -*-
"""模板自动对齐:在完整游戏窗口截图上定位各模板,反推 ROI 坐标写回 roi_config.json

用法:
    python tools/align_roi_from_templates.py <完整游戏窗口截图.png> [--dry-run]

前提: 截图必须是"整个游戏窗口"(F8 框选游戏全部区域),战斗画面最佳。
对齐范围: battle_left / battle_right 模板 → 战斗检测 ROI;avatar 模板 → 头像 ROI。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from src.utils.image_io import imread_unicode
from src.perception.vision_pipeline import DEFAULT_ROI_CONFIG

# 模板目录 -> roi_config.json 中的 ROI 名
ALIGN_MAP = [
    (PROJECT_ROOT / "data" / "vision" / "battle" / "left", "battle_left_indicator"),
    (PROJECT_ROOT / "data" / "vision" / "battle" / "right", "battle_right_indicator"),
    (PROJECT_ROOT / "data" / "vision" / "avatars", "enemy_avatar"),
]


def find_templates(frame: np.ndarray, template_dir: Path):
    """在整幅画面上找模板目录中所有模板的最佳匹配位置,返回 [(score,x1,y1,x2,y2)] 按分数降序"""
    results = []
    files = [p for p in template_dir.iterdir() if p.suffix.lower() == ".png"] \
        if template_dir.exists() else []
    if not files:
        return results

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    for path in files:
        tpl = imread_unicode(path, flags=cv2.IMREAD_GRAYSCALE)
        if tpl is None or tpl.shape[0] >= frame.shape[0] or tpl.shape[1] >= frame.shape[1]:
            continue
        result = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        x1, y1 = loc
        results.append((float(score), x1, y1, x1 + tpl.shape[1], y1 + tpl.shape[0]))

    results.sort(key=lambda r: r[0], reverse=True)
    return results


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    frame_path = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv
    frame = imread_unicode(frame_path)
    if frame is None:
        raise SystemExit(f"无法读取截图: {frame_path}")
    fh, fw = frame.shape[:2]
    print(f"参考截图: {frame_path.name} ({fw}x{fh})")

    config = json.loads(DEFAULT_ROI_CONFIG.read_text(encoding="utf-8"))
    changed = False

    for tpl_dir, roi_name in ALIGN_MAP:
        hits = find_templates(frame, tpl_dir)
        if not hits:
            print(f"[跳过] {roi_name}: 模板目录为空 ({tpl_dir.name})")
            continue
        score, x1, y1, x2, y2 = hits[0]
        if score < 0.6:
            print(f"[跳过] {roi_name}: 最佳匹配分数过低 ({score:.2f} < 0.6),不采用")
            continue
        # ROI 外扩 10% 作为匹配搜索窗口(局部匹配允许小偏移),并夹在画面内
        pad_x = int((x2 - x1) * 0.10)
        pad_y = int((y2 - y1) * 0.10)
        x1, y1, x2, y2 = max(0, x1 - pad_x), max(0, y1 - pad_y), \
            min(fw, x2 + pad_x), min(fh, y2 + pad_y)
        new_roi = {
            "left": round(x1 / fw, 4), "top": round(y1 / fh, 4),
            "width": round((x2 - x1) / fw, 4), "height": round((y2 - y1) / fh, 4),
        }
        old = config.get(roi_name)
        print(f"[对齐] {roi_name}: 分数 {score:.2f} 像素({x1},{y1})-({x2},{y2})")
        print(f"       旧 ROI: {old}")
        print(f"       新 ROI: {new_roi}")
        config[roi_name] = new_roi
        changed = True

    if not changed:
        print("没有任何 ROI 被更新")
        return
    if dry_run:
        print("(dry-run,未写入)")
        return

    DEFAULT_ROI_CONFIG.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {DEFAULT_ROI_CONFIG.name}")


if __name__ == "__main__":
    main()
