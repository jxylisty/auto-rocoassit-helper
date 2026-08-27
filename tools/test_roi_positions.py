"""验证 PVP 模板 ROI 位置 — 截取游戏画面，裁剪各 ROI 区域保存为图片"""
import json, cv2, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mss, numpy as np
from src.capture.window_capture import find_window

def find_game_window():
    return find_window(title_matcher=lambda t: "洛克王国" in t)

def load_template(name):
    path = os.path.join(os.path.dirname(__file__), "..", "data", "config", "roi_templates", f"{name}.json")
    if not os.path.exists(path):
        print(f"模板不存在: {path}")
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def crop_and_save(frame, roi, name, out_dir, color=(0, 255, 0)):
    """裁剪 ROI 区域并保存，同时在原图上画框"""
    if not roi or roi.get("rx") is None:
        return
    h, w = frame.shape[:2]
    x = int(roi["rx"] * w)
    y = int(roi["ry"] * h)
    rw = int(roi["rw"] * w)
    rh = int(roi["rh"] * h)
    if rw <= 0 or rh <= 0:
        return
    crop = frame[y:y+rh, x:x+rw]
    out_path = os.path.join(out_dir, f"{name}.png")
    cv2.imwrite(out_path, crop)
    print(f"  ✅ {name}: ({x},{y}) {rw}x{rh} → {out_path}")

def main():
    info = find_game_window()
    if not info:
        print("❌ 未找到洛克王国窗口，请确认游戏已启动")
        return

    print(f"游戏窗口: {info.title} · {info.width}x{info.height} · rect={info.rect}")

    # 截图
    left, top, right, bottom = info.rect
    with mss.mss() as sct:
        monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        img = sct.grab(monitor)
        frame = cv2.cvtColor(np.array(img), cv2.COLOR_BGRA2BGR)

    out_dir = os.path.join(os.path.dirname(__file__), "..", "data", "pvp", "roi_test")
    os.makedirs(out_dir, exist_ok=True)

    # 保存全图
    full_path = os.path.join(out_dir, "full_screenshot.png")
    cv2.imwrite(full_path, frame)
    print(f"全图保存: {full_path} ({frame.shape[1]}x{frame.shape[0]})")

    # 测试 PVP标准模板
    tmpl = load_template("PVP标准模板")
    if tmpl:
        print(f"\n--- PVP标准模板 ({len(tmpl['rois'])} ROI) ---")
        for roi in tmpl["rois"]:
            crop_and_save(frame, roi, roi["id"], out_dir)

    # 测试 PVP对战模板
    tmpl2 = load_template("PVP对战模板")
    if tmpl2:
        print(f"\n--- PVP对战模板 ({len(tmpl2['rois'])} ROI) ---")
        for roi in tmpl2["rois"]:
            crop_and_save(frame, roi, roi["id"], out_dir)

    print(f"\n所有裁剪图保存到: {out_dir}")
    print("请检查裁剪图是否准确覆盖了目标区域 ✅")

if __name__ == "__main__":
    main()