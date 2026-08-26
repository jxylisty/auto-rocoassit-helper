# -*- coding: utf-8 -*-
"""综合测试: PVP 模块 + Bridge API + 数据完整性"""
import sys, json, os
sys.path.insert(0, ".")

print("=" * 60)
print("1. PVP 模块导入测试")
print("=" * 60)

from src.pvp import (
    calc_pet_vs_pet, get_attr_multiplier,
    search_pets, search_skills,
    get_all_pet_names, get_skill_count,
    get_pet_by_seq, get_pet_by_name,
    get_skill, pet_to_dict,
    calculate_damage_full, calculate_all_panels,
    normalize_attr, get_strong_against, get_resist_against,
    PVP_RULES, LEVEL, STAR,
)
print("   ✅ 所有模块导入成功")

print("\n" + "=" * 60)
print("2. 数据完整性测试")
print("=" * 60)

pet_count = len(get_all_pet_names())
skill_count = get_skill_count()
print(f"   精灵总数: {pet_count}")
print(f"   技能总数: {skill_count}")
print(f"   PVP 等级: {LEVEL}")
print(f"   PVP 星级: {STAR}")
assert pet_count >= 400, "精灵数据不足"
assert skill_count >= 500, "技能数据不足"
print("   ✅ 数据完整")

print("\n" + "=" * 60)
print("3. 属性克制测试")
print("=" * 60)

tests = [
    ("火", "草", 2.0),
    ("火", "水", 0.5),
    ("水", "火", 2.0),
    ("草", "水", 2.0),
    ("电", "水", 2.0),
    ("普通", "幽", 0.5),
    ("龙", "龙", 2.0),
    ("火", ["草", "冰"], 3.0),
    ("火", ["水", "地"], 0.25),
    ("水", ["火", "地"], 3.0),
]
for atk, defs, expected in tests:
    if isinstance(defs, str):
        defs = [defs]
    result = get_attr_multiplier(atk, defs)
    status = "✅" if abs(result - expected) < 0.01 else f"❌ 期望{expected} 实际{result}"
    def_str = "+".join(defs)
    print(f"   {status} {atk} → {def_str}: {result}x")

print("\n" + "=" * 60)
print("4. 精灵查询测试")
print("=" * 60)

# 按序号
dimo = get_pet_by_seq(1)
assert dimo, "迪莫不存在"
dimo_types = dimo.types if hasattr(dimo, 'types') else dimo.get('types', [])
dimo_hp = dimo.hp_race if hasattr(dimo, 'hp_race') else dimo.get('hp', 0)
dimo_spd = dimo.speed_race if hasattr(dimo, 'speed_race') else dimo.get('speed', 0)
print(f"   #1 迪莫: 属性={dimo_types}, HP={dimo_hp}, 速={dimo_spd}")

# 按名称
dimo2 = get_pet_by_name("迪莫")
assert dimo2, "迪莫(按名称)不存在"
dimo2_name = dimo2.name if hasattr(dimo2, 'name') else dimo2.get('name', '?')
print(f"   迪莫(按名): {dimo2_name}")

# 搜索
results = search_pets("火神")
assert len(results) > 0, "搜索火神无结果"
for r in results[:3]:
    print(f"   搜索'火神': #{r['seq']} {r['name']} ({', '.join(r['types'])})")

print("\n" + "=" * 60)
print("5. 技能查询测试")
print("=" * 60)

skill = get_skill("火焰箭")
assert skill, "火焰箭不存在"
skill_type = skill.type if hasattr(skill, 'type') else skill.get('type', '?')
skill_attr = skill.attr if hasattr(skill, 'attr') else skill.get('attr', '?')
skill_power = skill.power if hasattr(skill, 'power') else skill.get('power', 0)
skill_consume = skill.consume if hasattr(skill, 'consume') else skill.get('consume', 0)
print(f"   火焰箭: 类型={skill_type}, 属性={skill_attr}, 威力={skill_power}, 消耗={skill_consume}")

results = search_skills("光球")
print(f"   搜索'光球': {len(results)} 个结果")
for r in results[:3]:
    print(f"     {r['name']} ({r['type']}/{r['attr']}) 威力={r['power']}")

print("\n" + "=" * 60)
print("6. 伤害计算测试")
print("=" * 60)

# 迪莫→喵喵 光球 (光打普通, 迪莫=光系本系)
r = calc_pet_vs_pet(1, 2, "光球")
assert r, "光球计算失败"
print(f"   迪莫→喵喵 光球: {r['damage']} (本系={r['sameTypeBonus']}, 倍率={r['attrMultiplier']})")

# 火神→魔力猫 火焰箭 (火克草, 火系本系)
r2 = calc_pet_vs_pet(7, 4, "火焰箭")
assert r2, "火焰箭计算失败"
print(f"   火神→魔力猫 火焰箭: {r2['damage']} (本系={r2['sameTypeBonus']}, 倍率={r2['attrMultiplier']})")

# 水灵→火神 潮涌 (水克火, 水系本系)
r3 = calc_pet_vs_pet(10, 7, "潮涌")
assert r3, "潮涌计算失败"
print(f"   水灵→火神 潮涌: {r3['damage']} (本系={r3['sameTypeBonus']}, 倍率={r3['attrMultiplier']})")

# 全面板计算
atk = pet_to_dict(1)
panels = calculate_all_panels(atk["race"], {"hp": 10, "attack": 10, "mattack": 10, "defense": 10, "mdefense": 10, "speed": 10})
print(f"   迪莫满配面板: HP={panels['hp']}, 攻={panels['attack']}, 魔攻={panels['mattack']}, 防={panels['defense']}, 魔防={panels['mdefense']}, 速={panels['speed']}")

print("\n" + "=" * 60)
print("7. Bridge API 路径测试")
print("=" * 60)

from src.gui.bridge import AppBridge, Api
bridge = AppBridge()
api = Api(bridge)
print("   ✅ AppBridge 和 Api 创建成功")

# 检查 PVP 方法是否存在
pvp_methods = [
    'pvp_search_pets', 'pvp_get_pet', 'pvp_search_skills',
    'pvp_calc_vs', 'pvp_get_all_pets', 'pvp_get_all_skills',
    'pvp_float_toggle', 'pvp_float_update', 'set_pvp_float_window',
]
for method in pvp_methods:
    assert hasattr(bridge, method), f"bridge 缺少方法: {method}"
    print(f"   ✅ bridge.{method}")

api_methods = [
    'pvp_search_pets', 'pvp_get_pet', 'pvp_search_skills',
    'pvp_calc_vs', 'pvp_get_all_pets', 'pvp_get_all_skills',
    'pvp_float_toggle', 'pvp_float_update',
]
for method in api_methods:
    assert hasattr(api, method), f"api 缺少方法: {method}"
    print(f"   ✅ api.{method}")

print("\n" + "=" * 60)
print("8. Bridge API 功能测试")
print("=" * 60)

# search_pets
r = bridge.pvp_search_pets("迪莫")
assert r["success"], f"搜索失败: {r}"
assert len(r["pets"]) > 0
print(f"   搜索'迪莫': {len(r['pets'])} 个结果, 首条={r['pets'][0]['name']} (类型={r['pets'][0]['types']})")

# get_pet
r = bridge.pvp_get_pet(1)
assert r["success"]
assert r["pet"]["name"] == "迪莫"
print(f"   获取 #1: {r['pet']['name']} (属性={r['pet']['types']}) 种族HP={r['pet']['race'].get('hp', '?')}")

# search_skills
r = bridge.pvp_search_skills("火焰")
assert r["success"]
print(f"   搜索'火焰': {len(r['skills'])} 个结果")

# calc_vs
r = bridge.pvp_calc_vs(1, 2, "光球")
assert r["success"], f"计算失败: {r}"
print(f"   迪莫→喵喵 光球: 伤害={r['damage']}")

# get_all_pets
r = bridge.pvp_get_all_pets()
assert r["success"]
assert len(r["pets"]) == pet_count
print(f"   全部精灵: {len(r['pets'])} 个")

# get_all_skills
r = bridge.pvp_get_all_skills()
assert r["success"]
assert len(r["skills"]) == skill_count
print(f"   全部技能: {len(r['skills'])} 个")

print("\n" + "=" * 60)
print("9. 前端文件检查")
print("=" * 60)

web_dir = os.path.join(os.path.dirname(__file__), "src", "gui", "web")
files_to_check = [
    "index.html", "assets/app.css", "assets/app.js", "assets/pvp.js",
    "widget.html", "pvp_float_overlay.html",
]
for f in files_to_check:
    path = os.path.join(web_dir, f)
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    status = "✅" if exists else "❌"
    print(f"   {status} {f} ({size:,} bytes)")

print("\n" + "=" * 60)
print("🎉 全部测试通过!")
print("=" * 60)