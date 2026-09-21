# -*- coding: utf-8 -*-
"""技能数据加载器 — 按名称查询技能详细数据"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR = Path(__file__).resolve().parent / "data"

from src.pvp import seadata

_SKILLS: Dict[str, Dict] = {}


def _merge_tags(tags_data: Dict) -> None:
    """合并官方标签数据 (7大行为标签) 到技能表"""
    for k, v in tags_data.items():
        if k in _SKILLS:
            _SKILLS[k]["tags"] = v.get("tags", [])
            if not _SKILLS[k].get("describe") and v.get("description"):
                _SKILLS[k]["describe"] = v.get("description")
        else:
            _SKILLS[k] = {
                "name": k,
                "type": v.get("damage_type", "变化"),
                "attr": v.get("element", "普通"),
                "power": v.get("power", "0"),
                "consume": v.get("cost", "0"),
                "describe": v.get("description", ""),
                "tags": v.get("tags", [])
            }


def _load_all() -> None:
    """加载技能数据。未授权时静默空载, 注册重载后自动解锁。"""
    try:
        global _SKILLS
        _SKILLS = seadata.load("skills")
    except Exception:
        _SKILLS = {}
        return
    try:
        _merge_tags(seadata.load_optional("skills_with_tags", {}) or {})
    except Exception:
        pass


# 模块加载: 空载初始化 + 尝试立即加载 + 注册重载
_load_all()
seadata.register_reload(_load_all)


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