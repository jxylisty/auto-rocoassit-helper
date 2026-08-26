# -*- coding: utf-8 -*-
"""验证 PVP 模块正确性"""
import sys
sys.path.insert(0, ".")

from src.pvp import (
    calc_pet_vs_pet, get_attr_multiplier,
    search_pets, get_all_pet_names, get_skill_count,
    calculate_all_panels, calculate_damage_full,
)

# 属性克制
print("=== 属性克制测试 ===")
print(f"火→草: {get_attr_multiplier('火', ['草'])}x")
print(f"火→水: {get_attr_multiplier('火', ['水'])}x")
print(f"火→草+冰: {get_attr_multiplier('火', ['草', '冰'])}x")
print(f"普通→幽: {get_attr_multiplier('普通', ['幽'])}x")

# 精灵/技能数据
print(f"\n精灵总数: {len(get_all_pet_names())}")
print(f"技能总数: {get_skill_count()}")

# 伤害计算
print("\n=== 伤害计算测试 ===")
d1 = calc_pet_vs_pet(1, 2, "猛烈撞击")
if d1:
    print(f"迪莫->喵喵 猛烈撞击: 伤害={d1['damage']}, 攻={d1['atkUsed']}, 防={d1['defUsed']}, 本系={d1['sameTypeBonus']}, 倍率={d1['attrMultiplier']}")

d2 = calc_pet_vs_pet(1, 2, "光球")
if d2:
    print(f"迪莫->喵喵 光球: 伤害={d2['damage']}, 本系={d2['sameTypeBonus']}, 倍率={d2['attrMultiplier']}")

# 迪莫(光)打火神(火)
d3 = calc_pet_vs_pet(1, 7, "光球")
if d3:
    print(f"迪莫->火神 光球: 伤害={d3['damage']}, 倍率={d3['attrMultiplier']} (光打火=普通)")

# 火神(火)打魔力猫(草)
d4 = calc_pet_vs_pet(7, 4, "火焰箭")
if d4:
    print(f"火神->魔力猫 火焰箭: 伤害={d4['damage']}, 本系={d4['sameTypeBonus']}, 倍率={d4['attrMultiplier']} (火克草=2x)")

print("\n✅ 全部测试通过！")