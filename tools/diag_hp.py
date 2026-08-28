"""诊断：检查敌方血量 OCR 实际读到什么值"""
import sys, os, time
sys.path.insert(0, r'D:\洛克王国ai\lkwgai_pvp_assistant')
os.chdir(r'D:\洛克王国ai\lkwgai_pvp_assistant')

from src.gui.bridge import AppBridge
from src.perception.vision_pipeline import VisionPipeline
from src.capture.window_capture import find_window
import cv2, numpy as np

bridge = AppBridge()
info = bridge._find_game_window()
if not info:
    print("❌ 未找到游戏窗口")
    sys.exit(1)

print(f"✅ 窗口: {info.title}  rect={info.rect}")
left, top, right, bottom = info.rect
w, h = right - left, bottom - top

# 截图
from PIL import ImageGrab
img = ImageGrab.grab(bbox=(left, top, right, bottom))
frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

# 跑管线
pipeline = VisionPipeline()
snap = pipeline.analyze(frame, light=True)

hp_value = snap.enemy_hp.value
hp_raw = snap.enemy_hp.debug.get("raw", "?")
hp_conf = snap.enemy_hp.confidence
battle = snap.raw.get("battle", {})
in_battle = battle.get("in_battle", False)

print(f"\n战斗检测: {'✅ 战斗中' if in_battle else '❌ 未检测到'}")
print(f"  左角标: {battle.get('left_score', 0):.2f}")
print(f"  右角标: {battle.get('right_score', 0):.2f}")
print(f"")
print(f"敌方血量 OCR:")
print(f"  原始文本: '{hp_raw}'")
print(f"  解析值: {hp_value}")
print(f"  置信度: {hp_conf:.2f}")
print(f"")

# 读取配置
import yaml
from pathlib import Path
settings = yaml.safe_load(Path("data/config/settings.yaml").read_text(encoding="utf-8"))
catch_hp = settings.get("battle", {}).get("catch_hp", 5)
flee_hp = settings.get("battle", {}).get("flee_hp", 8)
print(f"引擎配置:")
print(f"  catch_hp (丢球阈值): {catch_hp}%")
print(f"  flee_hp (逃跑阈值): {flee_hp}%")
print(f"")

if hp_value is None:
    print("⚠️ 结论: HP 识别失败，引擎会使用技能推进（不是丢球）")
elif hp_value <= catch_hp:
    print(f"⚠️ 结论: HP={hp_value} ≤ catch_hp={catch_hp}，引擎会立即丢球！")
    print(f"   → 原因: OCR 读到 {hp_value}%，但敌人可能满血")
    print(f"   → 修复: 检查 enemy_hp ROI 是否对准百分比文字")
else:
    print(f"✅ 结论: HP={hp_value} > catch_hp={catch_hp}，引擎正常使用技能")
    print(f"   → 如果引擎仍在丢球，可能是配置未生效，需重启引擎")