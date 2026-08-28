# -*- coding: utf-8 -*-
"""挂机引擎诊断: 测试截图 → 战斗检测 → 敌方血量读取 全链路"""
import sys, time, os
sys.path.insert(0, r'D:\洛克王国ai\lkwgai_pvp_assistant')
os.chdir(r'D:\洛克王国ai\lkwgai_pvp_assistant')

import cv2, numpy as np
from src.capture.window_capture import find_window
from src.capture.fast_capture import FastCapture
from src.perception.vision_pipeline import VisionPipeline

print("=" * 50)
print("挂机引擎诊断")
print("=" * 50)

# 1. 找窗口
print("\n[1] 查找游戏窗口...")
info = find_window(class_name="UnrealWindow")
if not info:
    info = find_window()
if info:
    print(f"  ✅ 找到: {info.title}  rect={info.rect}")
    left, top, right, bottom = info.rect
    w, h = right - left, bottom - top
    print(f"  尺寸: {w}x{h}")
else:
    print("  ❌ 未找到! 请确保游戏已打开")
    sys.exit(1)

# 2. 截图
print("\n[2] 截图测试...")
fc = FastCapture()
t0 = time.perf_counter()
frame = fc.capture(rect=(left, top, w, h))
t1 = time.perf_counter()
if frame is not None:
    print(f"  ✅ 截取成功 ({t1-t0:.0f}ms)  shape={frame.shape}")
    print(f"  标准差={frame.std():.1f}  {'⚠️ 画面可能全黑' if frame.std() < 3 else '✅ 画面正常'}")
else:
    print("  ❌ 截图失败")
    sys.exit(1)

# 3. 战斗检测
print("\n[3] 战斗检测...")
pipeline = VisionPipeline()
t0 = time.perf_counter()
snap = pipeline.analyze(frame, light=True)
t1 = time.perf_counter()
battle = snap.raw.get("battle", {})
print(f"  耗时: {t1-t0:.1f}s")
print(f"  in_battle: {battle.get('in_battle')}")
print(f"  left_score: {battle.get('left_score', 'N/A')}")
print(f"  right_score: {battle.get('right_score', 'N/A')}")
print(f"  via_nameplate: {battle.get('via_nameplate', False)}")

# 4. 敌方血量
print("\n[4] 敌方血量读取...")
hp = snap.enemy_hp
print(f"  value: {hp.value}")
print(f"  confidence: {hp.confidence}")
print(f"  debug: {hp.debug}")

# 5. 连续测试 (模拟反复截帧)
print("\n[5] 连续截帧测试 (5帧)...")
for i in range(5):
    t0 = time.perf_counter()
    frame2 = fc.capture(rect=(left, top, w, h))
    if frame2 is None:
        print(f"  [{i+1}] ❌ 截图失败")
        continue
    snap2 = pipeline.analyze(frame2, light=True)
    t1 = time.perf_counter()
    b2 = snap2.raw.get("battle", {})
    hp2 = snap2.enemy_hp
    print(f"  [{i+1}] {t1-t0:.1f}s  battle={b2.get('in_battle')}  hp={hp2.value}  left={b2.get('left_score', 'N/A'):.3f}  right={b2.get('right_score', 'N/A'):.3f}")

print("\n" + "=" * 50)
print("诊断完成")
print("=" * 50)