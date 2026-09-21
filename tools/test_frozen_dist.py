# -*- coding: utf-8 -*-
"""冻结产物终验 v2: 模拟攻击者拿到分发包后的世界 (环境 = 解包产物)
组成: exe 提取出的 PYZ 代码 + dist/_internal 的 pyd 与 .bin 数据
  1. pyd 公钥锚点与 keys.json 配套
  2. 无密钥时密封数据必须拒绝 (dist 无明文回退)
  3. 正确 seed (模拟云端下发) 解密成功
  4. 错误 seed 必须拒绝
"""
import sys
import marshal
import zlib
import struct
from pathlib import Path

EXTRACTED = Path(r"D:\autoclaw\resources\gateway\openclaw\洛克王国助手.exe_extracted")
PYZ_DIR = EXTRACTED / "PYZ.pyz_extracted"
DIST_INTERNAL = Path(r"D:\洛克王国ai\lkwgai_pvp_assistant\dist\洛克王国助手\_internal")

# 搭一个"以 pyc 运行"的 src 包: PYZ 代码 + dist 数据 + dist pyd
WORK = Path(r"C:\Users\zzx05\lkwg_audit\frozen_test")
if WORK.exists():
    import shutil
    shutil.rmtree(WORK)
(WORK / "src" / "pvp").mkdir(parents=True)
(WORK / "src" / "gui").mkdir(parents=True)

for mod in ["seadata", "pet_loader", "skill_loader", "type_chart", "pvp_rules", "damage_calculator", "data_collector", "history_db", "pvp_pipeline", "resource_updater", "roi_template", "__init__"]:
    src = PYZ_DIR / "src" / "pvp" / f"{mod}.pyc"
    (WORK / "src" / "pvp" / f"{mod}.pyc").write_bytes(src.read_bytes())
# gui 包的 __init__ 会 from .bridge import AppBridge/Api; bridge 顶层 import
# auto_throw_ball / updater 等, 一并带上 (带不上就清空 __init__ 导出)
for mod in ["auth", "__init__", "bridge", "updater", "window_sizing"]:
    src = PYZ_DIR / "src" / "gui" / f"{mod}.pyc"
    (WORK / "src" / "gui" / f"{mod}.pyc").write_bytes(src.read_bytes())
# bridge.py 顶层依赖 auto_throw_ball (项目根) —— 直接放个空壳替代, 终验不触发它
(WORK / "auto_throw_ball.py").write_text(
    "class AutoThrowBall:\n"
    "    def __init__(self, *a, **k):\n"
    "        raise RuntimeError('stub: not used in dist test')\n", encoding="utf-8")
# auth.py 是相对导入 auth_core 的包模块, 还需 src/__init__
src_init = PYZ_DIR / "src" / "__init__.pyc"
(WORK / "src" / "__init__.pyc").write_bytes(src_init.read_bytes())
# dist 的 pyd 与数据
import shutil
shutil.copy2(DIST_INTERNAL / "src" / "gui" / "auth_core.pyd", WORK / "src" / "gui" / "auth_core.pyd")
shutil.copytree(DIST_INTERNAL / "src" / "pvp" / "data", WORK / "src" / "pvp" / "data")

sys.path.insert(0, str(WORK))

import json
keys = json.load(open(r"D:\洛克王国ai\lkwgai_pvp_assistant\build\_hardened\keys.json"))

from src.gui import auth_core
assert auth_core.__file__.endswith(".pyd"), auth_core.__file__
print("[1] pyd loaded:", Path(auth_core.__file__).name)
assert auth_core.builtin_pubkey() == keys["ed25519_public_raw"]
print("[2] pubkey anchor matches keys.json")

from src.pvp import seadata, pet_loader, skill_loader

seadata.set_key(b"")
try:
    seadata.load("pet_skills")
    raise SystemExit("FAIL: 未授权却读到了 pet_skills")
except seadata.SeadataError:
    print("[3] no-key correctly rejected for pet_skills")
try:
    seadata.load("skills")
    raise SystemExit("FAIL: 未授权却读到了 skills")
except seadata.SeadataError:
    print("[4] no-key correctly rejected for skills")

assert len(pet_loader._PET_DETAIL) == 0
print("[5] loaders idle (empty) without key")

seadata.set_key_from_seed(keys["data_seed"])
assert len(pet_loader._PET_DETAIL) > 100
assert len(pet_loader._PET_SKILLS) > 100
assert len(skill_loader._SKILLS) > 100
assert len(pet_loader._TITLE_TO_FORM) > 100
print("[6] correct seed decrypts: pets=%d titles=%d skills=%d" % (
    len(pet_loader._PET_DETAIL), len(pet_loader._TITLE_TO_FORM), len(skill_loader._SKILLS)))

seadata.set_key_from_seed("attacker-guessed-seed")
try:
    seadata.load("pet_skills")
    raise SystemExit("FAIL: 错误 seed 解密成功")
except seadata.SeadataError:
    print("[7] wrong seed correctly rejected")

print("FROZEN_DIST_OK")
