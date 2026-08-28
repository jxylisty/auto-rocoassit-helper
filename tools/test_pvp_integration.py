# -*- coding: utf-8 -*-
"""验证 PVP 管线 → 伤害引擎 → 完整 payload 串联"""
import sys, os, json, time
PROJECT_ROOT = r'D:\洛克王国ai\lkwgai_pvp_assistant'
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

import cv2, numpy as np

# 1. 识别
from src.pvp.pvp_pipeline import get_pipeline
pipeline = get_pipeline()
img = cv2.imdecode(np.fromfile('data/screenshots/战斗画面截图.png', dtype=np.uint8), cv2.IMREAD_COLOR)
result = pipeline.analyze(img)
data = pipeline.to_dict(result)
print(f"识别: 我方={result.player_name} HP={result.player_hp} 技能={result.skills}")
print(f"      敌方={result.enemy_name} HP%={result.enemy_hp_pct:.0%} 能量={result.energy}")

# 2. 伤害计算
from src.pvp.pet_loader import get_pet_by_name
from src.pvp.skill_loader import get_skill
from src.pvp.damage_calculator import calculate_all_panels, calculate_damage_full

self_pet = get_pet_by_name(result.player_name)
enemy_pet = get_pet_by_name(result.enemy_name)
print(f"\n精灵: 我方={self_pet['name'] if self_pet else 'NOT FOUND'} 敌方={enemy_pet['name'] if enemy_pet else 'NOT FOUND'}")

if self_pet and enemy_pet:
    self_panel = calculate_all_panels(self_pet["race"])
    enemy_panel = calculate_all_panels(enemy_pet["race"])
    speed_diff = self_panel["speed"] - enemy_panel["speed"]
    print(f"面板: 速差={speed_diff:.0f} 我HP={self_panel['hp']:.0f} 敌HP={enemy_panel['hp']:.0f}")

    # 技能伤害
    print("\n--- 我方技能 ---")
    for sk_name in result.skills:
        sk = get_skill(sk_name) or {}
        sk_power = float(sk.get("power", 0)) if sk.get("power") else 0
        sk_type = sk.get("type", "")
        if sk_power > 0 and sk_type in ("物攻", "魔攻"):
            dmg = calculate_damage_full(self_panel, enemy_panel, skill_power=sk_power,
                skill_type=sk_type, skill_attr=sk.get("attr","普"),
                attacker_attrs=self_pet["types"], defender_attrs=enemy_pet["types"])
            enemy_est = int(enemy_panel["hp"] * result.enemy_hp_pct)
            print(f"  {sk_name}: {dmg['damage']:.0f}~{dmg['damage']*1.15:.0f} (×{dmg['attrMultiplier']:.1f}) {'🔥必杀' if dmg['damage']>=enemy_est>0 else ''}")
        else:
            print(f"  {sk_name}: 非伤害 (类型={sk_type})")

    # 敌方威胁
    print("\n--- 敌方威胁 (top2) ---")
    enemy_skills = [s["name"] if isinstance(s,dict) else s for s in enemy_pet.get("skills",[])][:10]
    count = 0
    for esk_name in enemy_skills:
        esk = get_skill(esk_name) or {}
        esk_power = float(esk.get("power", 0)) if esk.get("power") else 0
        esk_type = esk.get("type", "")
        if esk_power > 0 and esk_type in ("物攻", "魔攻"):
            edmg = calculate_damage_full(enemy_panel, self_panel, skill_power=esk_power,
                skill_type=esk_type, skill_attr=esk.get("attr","普"),
                attacker_attrs=enemy_pet["types"], defender_attrs=self_pet["types"])
            is_lethal = result.player_hp_val > 0 and edmg["damage"] >= result.player_hp_val
            print(f"  {esk_name}: {edmg['damage']:.0f}~{edmg['damage']*1.15:.0f} (×{edmg['attrMultiplier']:.1f}) {'☠致死' if is_lethal else ''}")
            count += 1
            if count >= 2: break

print("\n✅ 串联验证完成")