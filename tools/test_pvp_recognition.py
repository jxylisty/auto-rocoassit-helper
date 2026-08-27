# -*- coding: utf-8 -*-
"""PVP 实时识别测试 v2 — 图像匹配 + 血条分析"""
import json, sys
from pathlib import Path
import cv2, numpy as np, mss

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.capture.window_capture import find_window
from src.ocr.base import ROI
from src.perception.ocr_reader import OcrNumberReader

OUT_DIR = PROJECT_ROOT / "data" / "pvp" / "recognition_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def imwrite(path, img):
    ok, buf = cv2.imencode('.png', img)
    if ok: Path(path).write_bytes(buf.tobytes())
    return ok


def capture_game():
    info = find_window(title_matcher=lambda t: (
        "\u6d1b\u514b\u738b\u56fd" in t and "chatgpt" not in t.lower() and "\u8f85\u52a9" not in t))
    if not info: raise RuntimeError("game not found")
    print(f"Window: {info.title} | {info.width}x{info.height}")
    left, top, w, h = info.rect
    with mss.mss() as sct:
        img = sct.grab({"left": left, "top": top, "width": w-left, "height": h-top})
        frame = cv2.cvtColor(np.array(img), cv2.COLOR_BGRA2BGR)
    return frame, info


def crop_roi(frame, roi, base_w, base_h):
    fh, fw = frame.shape[:2]
    x = int(roi["rx"] * fw); y = int(roi["ry"] * fh)
    w = int(roi["rw"] * fw); h = int(roi["rh"] * fh)
    x = max(0, x); y = max(0, y)
    w = min(w, fw - x); h = min(h, fh - y)
    if w <= 0 or h <= 0: return None
    return frame[y:y+h, x:x+w]


def blood_pct(crop):
    """从血条颜色计算百分比: 绿色像素 / 总条宽"""
    if crop is None or crop.size == 0: return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # 绿色范围: H 35-85, S > 50, V > 50
    green = cv2.inRange(hsv, (35, 50, 50), (85, 255, 255))
    # 红色范围: H 0-10 or 160-180
    red1 = cv2.inRange(hsv, (0, 50, 50), (10, 255, 255))
    red2 = cv2.inRange(hsv, (160, 50, 50), (180, 255, 255))
    red = cv2.bitwise_or(red1, red2)
    total = green.sum() + red.sum()
    if total == 0:
        # 如果没检测到红绿，尝试用亮度方法
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, bright = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)
        return int(bright.sum() / 255 / crop.shape[0] * 100 / crop.shape[1])
    return int(green.sum() / total * 100)


def match_avatar(avatar_crop):
    """用 pvp_lib 匹配精灵头像"""
    if avatar_crop is None or avatar_crop.size == 0: return None
    try:
        from src.pvp.lib.pvp_lib import PvpLib
        lib = PvpLib()
        result = lib.match_avatar(avatar_crop)
        if result:
            return result.get("name") or result.get("label")
    except Exception as e:
        print(f"    [match_avatar error: {e}]")
    return None


def test_battle():
    print("=" * 60)
    print("PVP Battle Recognition Test v2")
    print("=" * 60)

    tmpl = json.loads(
        (PROJECT_ROOT / "data" / "config" / "roi_templates" / "PVP\u6807\u51c6\u6a21\u677f.json")
        .read_text("utf-8"))
    frame, info = capture_game()
    bw, bh = tmpl["base_resolution"]

    imwrite(OUT_DIR / "battle_full.png", frame)

    for roi in tmpl["rois"]:
        rid = roi["id"]
        crop = crop_roi(frame, roi, bw, bh)
        if crop is None: continue
        imwrite(OUT_DIR / f"battle_{rid}.png", crop)

        if "\u7cbe\u7075\u5934\u50cf" in rid:
            # 图像匹配
            name = match_avatar(crop)
            side = "\u6211\u65b9" if "\u6211\u65b9" in rid else "\u654c\u65b9"
            if name:
                print(f"  [MATCH] {rid}: {name}")
            else:
                print(f"  [NO_MATCH] {rid}: {crop.shape[1]}x{crop.shape[0]}")
        elif "\u8840\u6761" in rid:
            pct = blood_pct(crop)
            side = "\u6211\u65b9" if "\u6211\u65b9" in rid else "\u654c\u65b9"
            if pct is not None:
                print(f"  [BLOOD] {rid}: ~{pct}%")
            else:
                print(f"  [FAIL] {rid}")
        elif "\u80fd\u91cf" in rid:
            roi_obj = ROI("temp", 0, 0, crop.shape[1], crop.shape[0])
            reader = OcrNumberReader(roi_obj, upscale=4.0, percent=False)
            result = reader.read(crop)
            val = result.value
            print(f"  [ENERGY] {rid}: {val if val is not None else '?'}")
        else:
            # 精灵名、技能: 保存图片供人工检查
            pass

    print(f"\nSaved to: {OUT_DIR}")


if __name__ == "__main__":
    try:
        test_battle()
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)