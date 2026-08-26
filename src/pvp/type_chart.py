# -*- coding: utf-8 -*-
"""
属性克制表 — 与 luokewangguo 的 typeChart.js 完全一致
所有克制倍率计算必须复用本模块，禁止在各处复制克制表。
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"

# 加载原始克制表
with open(DATA_DIR / "type_chart.json", "r", encoding="utf-8") as f:
    _CHART: Dict[str, Dict[str, List[str]]] = json.load(f)

# 加载属性类型信息
with open(DATA_DIR / "pet_types.json", "r", encoding="utf-8") as f:
    PET_TYPES: List[Dict] = json.load(f)

# 属性名列表
ALL_ATTRS: List[str] = [t["key"] for t in PET_TYPES]
# 属性名 → 颜色
ATTR_COLORS: Dict[str, str] = {t["key"]: t["color"] for t in PET_TYPES}
# 属性名 → 显示名
ATTR_LABELS: Dict[str, str] = {t["key"]: t["label"] for t in PET_TYPES}


def normalize_attr(attr: str) -> str:
    """标准化属性名：去除'系'后缀，统一为键名"""
    attr = attr.strip()
    # 去掉"系"后缀
    if attr.endswith("系"):
        attr = attr[:-1]
    # 映射常见别名
    ALIASES = {
        "普通": "普通", "一般": "普通",
        "火": "火", "水": "水", "草": "草",
        "电": "电", "冰": "冰", "虫": "虫",
        "翼": "翼", "飞行": "翼",
        "地": "地", "地面": "地",
        "萌": "萌", "妖精": "萌",
        "武": "武", "格斗": "武",
        "毒": "毒", "龙": "龙",
        "幽": "幽", "幽灵": "幽",
        "恶": "恶", "黑暗": "恶",
        "光": "光", "机械": "机械",
        "幻": "幻", "超能": "幻",
    }
    if attr in ALIASES:
        return ALIASES[attr]
    return attr


def normalize_attr_list(attrs: List[str]) -> List[str]:
    """标准化属性列表"""
    return [normalize_attr(a) for a in attrs]


def get_attr_multiplier(attack_attr: str, defense_attrs: List[str]) -> float:
    """
    计算属性克制倍率 (攻击方属性 → 防御方属性列表)
    
    与 JS 版 getAttrMultiplier 完全一致:
    - 查攻击方属性的 strong/resist 列表
    - 统计防御方属性中有几个被克制、几个被抵抗
    - 双克制=3x, 单克制=2x, 双抵抗=0.25x, 单抵抗=0.5x, 一克一抗=1x
    """
    atk_type = normalize_attr(attack_attr)
    chart = _CHART.get(atk_type)
    if chart is None:
        return 1.0

    defenses = normalize_attr_list(defense_attrs)
    strong_count = 0
    resist_count = 0

    for def_type in defenses:
        if def_type in chart.get("strong", []):
            strong_count += 1
        elif def_type in chart.get("resist", []):
            resist_count += 1

    if strong_count >= 2:
        return 3.0  # 双克制
    if strong_count == 1 and resist_count == 0:
        return 2.0  # 单克制
    if resist_count >= 2 and strong_count == 0:
        return 0.25  # 双抵抗
    if resist_count == 1 and strong_count == 0:
        return 0.5  # 单抵抗
    return 1.0  # 普通 / 一克一抗


def get_strong_against(attr: str) -> List[str]:
    """获取该属性克制的属性列表"""
    attr = normalize_attr(attr)
    if attr in _CHART:
        return _CHART[attr].get("strong", [])
    return []


def get_resist_against(attr: str) -> List[str]:
    """获取该属性抵抗的属性列表"""
    attr = normalize_attr(attr)
    if attr in _CHART:
        return _CHART[attr].get("resist", [])
    return []


def get_weak_against(attr: str) -> List[str]:
    """获取克制该属性的属性列表（防御方弱点）"""
    attr = normalize_attr(attr)
    if attr in _CHART:
        return _CHART[attr].get("weak", [])
    return []


def get_defense_resist(attr: str) -> List[str]:
    """获取该属性防御抵抗的属性列表"""
    attr = normalize_attr(attr)
    if attr in _CHART:
        return _CHART[attr].get("defenseResist", [])
    return []