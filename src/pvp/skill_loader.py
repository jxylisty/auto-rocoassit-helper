# -*- coding: utf-8 -*-
"""技能数据加载器 — 按名称查询技能详细数据"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR = Path(__file__).resolve().parent / "data"

with open(DATA_DIR / "skills.json", "r", encoding="utf-8") as f:
    _SKILLS: Dict[str, Dict] = json.load(f)


def get_skill(name: str) -> Optional[Dict[str, Any]]:
    """按技能名称查询"""
    return _SKILLS.get(name)


def get_skill_power(name: str) -> int:
    """获取技能威力 (数值)"""
    skill = get_skill(name)
    if skill is None:
        return 0
    power = skill.get("power", "0")
    try:
        return int(power)
    except (ValueError, TypeError):
        return 0


def get_skill_consume(name: str) -> int:
    """获取技能消耗（能量）"""
    skill = get_skill(name)
    if skill is None:
        return 0
    consume = skill.get("consume", "0")
    try:
        return int(consume)
    except (ValueError, TypeError):
        return 0


def get_skill_type(name: str) -> str:
    """获取技能类型：物攻/魔攻/状态"""
    skill = get_skill(name)
    if skill is None:
        return "未知"
    return skill.get("type", "未知")


def get_skill_attr(name: str) -> str:
    """获取技能属性（去掉'系'后缀）"""
    from .type_chart import normalize_attr

    skill = get_skill(name)
    if skill is None:
        return "未知"
    attr = skill.get("attr", "未知")
    return normalize_attr(attr)


def get_skill_describe(name: str) -> str:
    """获取技能描述"""
    skill = get_skill(name)
    if skill is None:
        return ""
    return skill.get("describe", "")


def is_damage_skill(name: str) -> bool:
    """判断是否为伤害技能（物攻/魔攻）"""
    skill_type = get_skill_type(name)
    return skill_type in ("物攻", "魔攻")


def is_magic_skill(name: str) -> bool:
    """判断是否为魔攻技能"""
    return get_skill_type(name) == "魔攻"


def is_physical_skill(name: str) -> bool:
    """判断是否为物攻技能"""
    return get_skill_type(name) == "物攻"


def search_skills(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """模糊搜索技能"""
    query_lower = query.lower()
    results = []
    for name, data in _SKILLS.items():
        if query_lower in name.lower():
            results.append({
                "name": name,
                "type": data.get("type", ""),
                "attr": data.get("attr", ""),
                "power": data.get("power", "0"),
                "consume": data.get("consume", "0"),
                "describe": data.get("describe", ""),
            })
    return results[:limit]


def get_all_skill_names() -> List[str]:
    """获取所有技能名称"""
    return sorted(_SKILLS.keys())


def get_skill_count() -> int:
    """获取技能总数"""
    return len(_SKILLS)