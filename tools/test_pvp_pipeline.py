# -*- coding: utf-8 -*-
"""快速验证 PVP 管线：识别战斗截图"""
import cv2, numpy as np, os, sys, time

PROJECT_ROOT = r'D:\洛克王国ai\lkwgai_pvp_assistant'
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# 读取截图
img = cv2.imdecode(np.fromfile(os.path.join(PROJECT_ROOT, 'data/screenshots/战斗画面截图.png'), dtype=np.uint8), cv2.IMREAD_COLOR)

from src.pvp.pvp_pipeline import PvpPipeline, ocr_number, ocr_name, enemy_hp_color_ratio

pipeline = PvpPipeline()
print(f"已加载模板，{len(pipeline._rois)} 个 ROI\n")

t0 = time.time()
result = pipeline.analyze(img)
elapsed = time.time() - t0

print(f"===== PVP 识别结果 ({elapsed:.1f}s) =====")
print(f"战斗状态: {'✅ 战斗中' if result.in_battle else '❌ 未检测到'}")
print(f"")
print(f"我方:")
print(f"  精灵名: {result.player_name} (conf={result.player_name_conf:.2f})")
print(f"  血量: {result.player_hp} (当前={result.player_hp_val} 最大={result.player_hp_max})")
print(f"  能量: {result.energy}")
print(f"  技能: {result.skills}")
print(f"")
print(f"敌方:")
print(f"  精灵名: {result.enemy_name} (conf={result.enemy_name_conf:.2f})")
print(f"  血量%: {result.enemy_hp_pct:.0%}")
print(f"  色彩积分: {result.enemy_hp_color:.2f}")
print(f"")
if result.errors:
    print(f"错误: {result.errors}")
print(f"===== 结束 =====")