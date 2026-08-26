# -*- coding: utf-8 -*-
"""Phase 4 最终综合测试"""
import sys
sys.path.insert(0, ".")

print("=" * 60)
print("Phase 4 综合测试")
print("=" * 60)

# 1. 模块导入
print("\n1. 模块完整性")
from src.pvp import (
    calc_pet_vs_pet, get_attr_multiplier,
    search_pets, get_pet_by_seq, get_pet_by_name, pet_to_dict,
    search_skills, get_skill, get_all_pet_names, get_all_skill_names,
    calculate_all_panels,
)
from src.pvp.pvp_rules import PVP_RULES
print("   ✅ 所有模块导入成功")

# 2. 精灵数据完整性
print("\n2. 精灵数据")
pet = get_pet_by_seq(1)
assert pet, "迪莫不存在"
race = pet.get("race", {})
assert race.get("hp", 0) == 120, f"迪莫HP种族值应为120, 实际: {race.get('hp')}"
assert pet.get("types") == ["光"], f"迪莫属性应为['光'], 实际: {pet.get('types')}"
assert pet.get("name") == "迪莫", f"迪莫name应为'迪莫', 实际: {pet.get('name')}"
print(f"   ✅ 迪莫: 属性={pet['types']}, HP种族={race['hp']}, 攻={race['attack']}, 速={pet['speed_race']}")

pet2 = get_pet_by_name("火神")
assert pet2, "火神不存在"
assert pet2["name"] == "火神"
print(f"   ✅ 火神: 属性={pet2['types']}, HP种族={pet2['race']['hp']}")

# 3. 技能数据
print("\n3. 技能数据")
skill = get_skill("火焰箭")
assert skill, "火焰箭不存在"
print(f"   ✅ 火焰箭: 类型={skill['type']}, 属性={skill['attr']}, 威力={skill['power']}")

# 4. 伤害计算
print("\n4. 伤害计算")
# 火神(火) → 魔力猫(草) 火焰箭(火系)
result = calc_pet_vs_pet(7, 4, "火焰箭")
assert result, "计算失败"
assert result["attrMultiplier"] == 2.0, f"火克草应为2x, 实际: {result['attrMultiplier']}"
assert result["sameTypeBonus"] == 1.25, "火神火系技能应为本系1.25x"
print(f"   ✅ 火神→魔力猫 火焰箭: 伤害={result['damage']}, 本系={result['sameTypeBonus']}, 倍率={result['attrMultiplier']}")

# 迪莫(光) → 喵喵(草) 光球(光系)
result2 = calc_pet_vs_pet(1, 2, "光球")
assert result2, "计算失败"
print(f"   ✅ 迪莫→喵喵 光球: 伤害={result2['damage']}, 本系={result2['sameTypeBonus']}, 倍率={result2['attrMultiplier']}")

# 5. 面板计算
print("\n5. 面板计算")
atk = pet_to_dict(1)
panels = calculate_all_panels(atk["race"], {"hp": 10, "attack": 10, "mattack": 10, "defense": 10, "mdefense": 10, "speed": 10})
assert panels["hp"] >= 400, f"60级HP应>=400, 实际: {panels['hp']}"
print(f"   ✅ 迪莫满配: HP={panels['hp']}, 攻={panels['attack']}, 防={panels['defense']}, 速={panels['speed']}")

# 6. Bridge API
print("\n6. Bridge API")
from src.gui.bridge import AppBridge, Api
bridge = AppBridge()
api = Api(bridge)

# 所有方法存在
methods = [
    "pvp_search_pets", "pvp_get_pet", "pvp_search_skills",
    "pvp_calc_vs", "pvp_get_all_pets", "pvp_get_all_skills",
    "pvp_calc_quick", "pvp_float_toggle", "pvp_float_update",
]
for m in methods:
    assert hasattr(bridge, m), f"bridge.{m} 缺失"
    assert hasattr(api, m), f"api.{m} 缺失"
print(f"   ✅ 所有 {len(methods)} 个 Bridge API 方法存在")

# pvp_calc_quick
r = bridge.pvp_calc_quick(200, 150, 80, "物攻", "火", ["火"], ["草"])
assert r["success"]
assert r["attrMultiplier"] == 2.0, f"火→草应为2x, 实际: {r['attrMultiplier']}"
print(f"   ✅ 快速计算: 伤害={r['damage']}, 倍率={r['attrMultiplier']}x")

# pvp_get_pet
r = bridge.pvp_get_pet(1)
assert r["success"]
assert r["pet"]["race"]["hp"] == 120
assert r["pet"]["types"] == ["光"]
print(f"   ✅ pvp_get_pet(1): {r['pet']['name']}, HP={r['pet']['race']['hp']}")

# pvp_search_pets
r = bridge.pvp_search_pets("火神")
assert r["success"]
assert len(r["pets"]) > 0
print(f"   ✅ pvp_search_pets('火神'): {len(r['pets'])} 结果")

# pvp_calc_vs
r = bridge.pvp_calc_vs(7, 4, "火焰箭")
assert r["success"]
assert r["damage"] > 200
print(f"   ✅ pvp_calc_vs(7,4,'火焰箭'): {r['damage']}")

# pvp_get_all_pets
r = bridge.pvp_get_all_pets()
assert len(r["pets"]) > 600, f"期望>600，实际{len(r['pets'])}"
print(f"   ✅ pvp_get_all_pets: {len(r['pets'])} 个（含所有形态）")

# 7. 前端文件
print("\n7. 前端文件")
import os
web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "gui", "web")
files = ["index.html", "assets/app.css", "assets/app.js", "assets/pvp.js", "pvp_float_overlay.html"]
for f in files:
    fpath = os.path.join(web_dir, f)
    assert os.path.exists(fpath), f"文件缺失: {f}"
    size = os.path.getsize(fpath)
    print(f"   ✅ {f} ({size:,} bytes)")

print("\n" + "=" * 60)
print("✅ 全部测试通过！Phase 4 完成！")
print("=" * 60)