# -*- coding: utf-8 -*-
"""临时诊断: 在真实战斗截图上复现 PVP 识别全链路"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

FRAME = PROJECT_ROOT / "data" / "screenshots" / "战斗画面截图.png"

from src.pvp.pvp_pipeline import PvpPipeline, ocr_batch_chinese
from src.pvp.pvp_pipeline import _fuzzy_match
from src.pvp import skill_loader, seadata

frame = cv2.imdecode(np.fromfile(str(FRAME), dtype=np.uint8), cv2.IMREAD_COLOR)
print(f"frame: {FRAME.name} shape={frame.shape}")

pipe = PvpPipeline()
print(f"rois loaded: {list(pipe._rois.keys())}")

# ---- 1. 裁剪 + 质量闸门数据 ----
crops = []
for rid in ["我方精灵名", "敌方精灵名", "我方血条", "敌方血条",
            "技能1", "技能2", "技能3", "技能4", "剩余能量"]:
    c = pipe._crop(frame, rid)
    if c is not None:
        crops.append((rid, c))
    print(f"  crop {rid}: {'OK ' + str(c.shape) if c is not None else 'MISSING'}")

for rid in ["我方精灵头像", "敌方精灵头像"]:
    c = pipe._crop(frame, rid)
    if c is None:
        print(f"  avatar {rid}: MISSING")
        continue
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    print(f"  avatar {rid}: shape={c.shape} std={g.std():.1f} range={int(g.max())-int(g.min())}")

# ---- 2. OCR 原始输出 ----
ocr = ocr_batch_chinese(crops)
print("\n=== OCR raw ===")
for rid, txt in ocr.items():
    print(f"  {rid}: {txt!r}")

# ---- 3. 名字模糊匹配 ----
print("\n=== name fuzzy ===")
for rid in ["我方精灵名", "敌方精灵名"]:
    raw = ocr.get(rid, "")
    cleaned = "".join(ch for ch in raw if ("\u4e00" <= ch <= "\u9fff") or ch.isalnum())
    m = _fuzzy_match(cleaned, pipe._pet_list)
    print(f"  {rid}: raw={raw!r} cleaned={cleaned!r} -> {m!r}")

# ---- 4. 头像匹配: 完整 Top5(绕过闸门) ----
print("\n=== avatar full rank ===")
import sys as _s
for p in (str(PROJECT_ROOT / "src" / "pvp" / "lib"), str(PROJECT_ROOT)):
    if p not in _s.path:
        _s.path.insert(0, p)
from pvp_lib import PvpTemplateLibrary
lib = PvpTemplateLibrary()
lib.load()
print(f"  lib templates={lib.status().get('n_templates')}")
for side, rid in [("player", "我方精灵头像"), ("enemy", "敌方精灵头像")]:
    c = pipe._crop(frame, rid)
    if c is None or lib is None:
        print(f"  {side}: skip (crop={c is not None}, lib={lib is not None})")
        continue
    hits = lib.match(c, n_top=5)
    print(f"  {side} ({rid}):")
    for h in hits:
        print(f"    #{h['rank']} {h['name']} raw={h['raw']} margin={h['margin']} conf={h['confidence']}")
    gate = pipe._match_avatars(frame).get(side)
    print(f"    -> pipeline gate adopted: {gate}")

# ---- 5. 技能查表 ----
print("\n=== skills ===")
print(f"  seadata ready={seadata.is_ready()} skills_loaded={skill_loader.get_skill_count()}")
for i in range(1, 5):
    name = ocr.get(f"技能{i}", "")
    sk = skill_loader.get_skill(name)
    print(f"  技能{i}: ocr={name!r} -> hit={bool(sk)}" +
          (f" type={sk.get('type')} power={sk.get('power')}" if sk else ""))
    if not sk and name:
        cand = skill_loader.search_skills(name[:2], limit=5)
        print(f"      近似: {[c['name'] for c in cand]}")

# ---- 6. 完整 analyze ----
print("\n=== pipeline.analyze ===")
res = pipe.analyze(frame)
d = pipe.to_dict(res)
print(f"  in_battle={d['in_battle']}")
print(f"  player: name={d['player']['name']!r} conf={d['player']['name_conf']} via_avatar={d['player']['name_via_avatar']}")
print(f"  enemy : name={d['enemy']['name']!r} conf={d['enemy']['name_conf']} via_avatar={d['enemy']['name_via_avatar']}")
print(f"  skills={d['player']['skills']}")
print(f"  errors={d['errors']}")
