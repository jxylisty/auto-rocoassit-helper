# -*- coding: utf-8 -*-
"""PVP 规则常量加载器"""

import json
from pathlib import Path
from typing import Dict, Any

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_pvp_rules() -> Dict[str, Any]:
    """加载 PVP 规则常量"""
    with open(DATA_DIR / "pvp_rules.json", "r", encoding="utf-8") as f:
        return json.load(f)


PVP_RULES = load_pvp_rules()

# 便捷访问
LEVEL = PVP_RULES["level"]
STAR = PVP_RULES["star"]
IV_RULE = PVP_RULES["ivRule"]
NATURE = PVP_RULES["nature"]
DAMAGE = PVP_RULES["damage"]
DEFAULT_SCENARIO = PVP_RULES["defaultScenario"]


def calc_actual_iv(input_iv: int) -> int:
    """根据 IV 公式计算实际 IV 值"""
    return input_iv * (STAR + 1)


def calc_full_iv_race(race_value: int, iv: int) -> int:
    """计算满配面板值：种族值 + 实际IV"""
    actual_iv = calc_actual_iv(iv)
    return race_value + actual_iv


def calc_hp_stat(hp_race: int, iv: int, level: int = LEVEL) -> int:
    """计算 HP 面板值（考虑等级缩放）"""
    actual_iv = calc_actual_iv(iv)
    # 洛克王国HP公式：HP = (种族值*2 + 个体值 + 努力值/4) * 等级/100 + 等级 + 10
    # 简化：满配默认 HP = 种族值 + 实际IV，按等级缩放
    base = hp_race + actual_iv
    return int(base * level / 60)  # 60级缩放


def calc_other_stat(race_value: int, iv: int, nature_mult: float = 1.0, level: int = LEVEL) -> int:
    """计算其他属性面板值（攻/防/速）"""
    actual_iv = calc_actual_iv(iv)
    base = race_value + actual_iv
    return int(base * nature_mult * level / 60)