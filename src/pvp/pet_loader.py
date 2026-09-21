# -*- coding: utf-8 -*-
"""精灵数据加载器 — 从 JSON 加载并按名称/编号查询"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR = Path(__file__).resolve().parent / "data"

from src.pvp import seadata


def _load_all() -> None:
    """加载核心数据 (授权后可读的密封数据)。未授权时静默空载, 注册重载后自动解锁。"""
    global _PET_DETAIL, _PET_INDEX, _PET_SKILLS, _PET_RACE_SPEED, _LEADER_FORMS
    global _LEADER_FORM_SET, _TITLE_TO_FORM, _NAME_TO_TITLE, _FINAL_ALLOWED
    try:
        _PET_DETAIL = seadata.load("pet_detail")
        _PET_INDEX = seadata.load("pet_index")
        _PET_SKILLS = seadata.load("pet_skills")
        _PET_RACE_SPEED = seadata.load("pet_race_speed")
        _LEADER_FORMS = seadata.load("leader_forms")
    except Exception:
        # 密钥未就绪 (未授权/首次运行): 空载启动, 授权后 seadata 触发重载
        _PET_DETAIL, _PET_INDEX, _PET_SKILLS = {}, {}, {}
        _PET_RACE_SPEED, _LEADER_FORMS = {}, []
        return
    _rebuild_indexes()


def _rebuild_indexes() -> None:
    """由原始数据重建全部派生索引 (与数据加载解耦, 重载时只跑这里)"""
    global _LEADER_FORM_SET, _TITLE_TO_FORM, _NAME_TO_TITLE, _FINAL_ALLOWED
    _LEADER_FORM_SET = set(_LEADER_FORMS)

    # page_title → {seq, form}  每个形态独立索引
    ttf: Dict[str, Dict] = {}
    for seq_str, forms in _PET_DETAIL.items():
        seq = int(seq_str)
        for form in forms:
            title = form.get("page_title", "")
            if title:
                ttf[title] = {"seq": seq, "form": form}
    _TITLE_TO_FORM = ttf

    # 名字 → 形态映射 (pet_index 的 name 字段)
    ntt: Dict[str, str] = {}
    for key, entry in _PET_INDEX.items():
        seq = entry.get("seq", 0)
        name = entry.get("name", "")
        page_title = entry.get("page_title", name)
        if name and seq:
            ntt[name] = page_title
    _NAME_TO_TITLE = ntt

    # PVP 选宠过滤: 高级形态(uiTag=最终形态) + 变体高级形态
    fa: Dict[str, Dict] = {}
    for _key, _entry in _PET_INDEX.items():
        if _entry.get("uiTag") != "最终形态":
            continue
        _seq = int(_entry.get("seq", 0))
        for _form in _PET_DETAIL.get(str(_seq), []):
            _t = _form.get("page_title", "")
            if _t:
                fa[_t] = {"seq": _seq, "form": _form}
    _FINAL_ALLOWED = fa


# 模块加载: 空载初始化 + 尝试立即加载 (开发环境/已授权时直接可用) + 注册重载
_PET_DETAIL: Dict[str, List[Dict]] = {}
_PET_INDEX: Dict[str, Dict] = {}
_PET_SKILLS: Dict[str, Dict] = {}
_PET_RACE_SPEED: Dict[str, int] = {}
_LEADER_FORMS: List[int] = []
_LEADER_FORM_SET: set = set()
_TITLE_TO_FORM: Dict[str, Dict] = {}
_NAME_TO_TITLE: Dict[str, str] = {}
_FINAL_ALLOWED: Dict[str, Dict] = {}

_load_all()
seadata.register_reload(_load_all)


def _build_pet_dict(seq: int, form: Dict) -> Dict:
    """从 form 字典构建标准化精灵数据"""
    return {
        "seq": seq,
        "name": form.get("page_title", ""),
        "types": form.get("type", []),
        "race": form.get("race", {}),
        "trait": form.get("trait", ""),
        "img": form.get("img", ""),
        "speed_race": _PET_RACE_SPEED.get(str(seq), 0),
        "skills": _PET_SKILLS.get(str(seq), {}).get("skills", []),
        "is_leader": seq in _LEADER_FORM_SET,
    }


def pvp_allowed_titles() -> Dict[str, Dict]:
    """PVP 可选精灵标题集合(高级形态 + 变体高级形态)"""
    return _FINAL_ALLOWED


# ---- 查询 API ----

def get_pet_count() -> int:
    return len(_PET_DETAIL)


# 常见别名/简称映射
_PET_ALIASES: Dict[str, str] = {
    "独角兽": "白金独角兽",
    "白金独角": "白金独角兽",
    "彩虹独角": "彩虹独角兽",
}


def get_pet_by_name(name: str) -> Optional[Dict]:
    """按精灵名称查询（优先精确匹配 page_title）"""
    if not name:
        return None
    name_clean = name.strip()
    # 优先按 page_title 精确匹配（图片文件名用的就是这个）
    info = _TITLE_TO_FORM.get(name_clean)
    if info:
        return _build_pet_dict(info["seq"], info["form"])
    # 别名映射
    alias_target = _PET_ALIASES.get(name_clean)
    if alias_target and alias_target in _TITLE_TO_FORM:
        info = _TITLE_TO_FORM[alias_target]
        return _build_pet_dict(info["seq"], info["form"])
    # 去除括号形态修饰（如 "白金独角兽（变体形态）" -> "白金独角兽"）
    import re
    base_name = re.sub(r'[\(（].*?[\)）]', '', name_clean).strip()
    if base_name and base_name in _TITLE_TO_FORM:
        info = _TITLE_TO_FORM[base_name]
        return _build_pet_dict(info["seq"], info["form"])
    # 兜底：按 pet_index 的 name 字段查
    title = _NAME_TO_TITLE.get(name_clean) or _NAME_TO_TITLE.get(base_name)
    if title:
        info = _TITLE_TO_FORM.get(title)
        if info:
            return _build_pet_dict(info["seq"], info["form"])
    return None


def get_pet_by_title(title: str) -> Optional[Dict]:
    """按 page_title 查询（返回特定形态，不是第一个形态）"""
    info = _TITLE_TO_FORM.get(title)
    if info is None:
        return None
    return _build_pet_dict(info["seq"], info["form"])


def get_pet_by_seq(seq: int, title: str = None) -> Optional[Dict]:
    """按编号查询。如果给了 title 则返回特定形态，否则返回第一个"""
    if title:
        return get_pet_by_title(title)
    forms = _PET_DETAIL.get(str(seq), [])
    if not forms:
        return None
    return _build_pet_dict(seq, forms[0])


def get_all_forms(seq: int) -> List[Dict]:
    return _PET_DETAIL.get(str(seq), [])


def get_pet_race(pet_seq: int, title: str = None) -> Optional[Dict[str, int]]:
    pet = get_pet_by_seq(pet_seq, title)
    return pet.get("race") if pet else None


def get_pet_speed_race(pet_seq: int) -> int:
    return _PET_RACE_SPEED.get(str(pet_seq), 0)


def get_pet_types(pet_seq: int, title: str = None) -> List[str]:
    pet = get_pet_by_seq(pet_seq, title)
    return pet.get("types", []) if pet else []


def get_pet_skills(pet_seq: int) -> List[Dict]:
    return _PET_SKILLS.get(str(pet_seq), {}).get("skills", [])


def get_pet_trait(pet_seq: int, title: str = None) -> str:
    pet = get_pet_by_seq(pet_seq, title)
    return pet.get("trait", "") if pet else ""


def is_leader_form(pet_seq: int) -> bool:
    return pet_seq in _LEADER_FORM_SET


def search_pets(query: str, limit: int = 20, pvp_filter: bool = False) -> List[Dict]:
    """模糊搜索。优先按 page_title 搜索（按 title 去重，保留不同形态）
    pvp_filter=True 时只返回高级形态及变体高级形态(PVP 伤害计算用)"""
    query_lower = query.lower()
    if pvp_filter:
        allowed = _FINAL_ALLOWED
    else:
        allowed = _TITLE_TO_FORM
    # 别名替换支持
    alias_target = _PET_ALIASES.get(query.strip())
    results = []
    seen_titles = set()

    # 如果有别名目标优先置顶
    if alias_target and alias_target in allowed:
        info = allowed[alias_target]
        seen_titles.add(alias_target)
        results.append({
            "seq": info["seq"], "name": alias_target,
            "title": alias_target, "types": info["form"].get("type", []),
            "match_by": "alias",
        })

    # 按 page_title 搜索（图片用的名字）
    for title, info in allowed.items():
        if query_lower in title.lower():
            if title not in seen_titles:
                seen_titles.add(title)
                form = info["form"]
                results.append({
                    "seq": info["seq"], "name": title,
                    "title": title, "types": form.get("type", []),
                    "match_by": "title",
                })

    # 按 pet_index 的 name 补搜
    for name, title in _NAME_TO_TITLE.items():
        if title not in seen_titles and query_lower in name.lower() and title in allowed:
            info = allowed[title]
            seen_titles.add(title)
            form = info["form"]
            results.append({
                "seq": info["seq"], "name": title,
                "title": title, "types": form.get("type", []),
                "match_by": "name",
            })

    # PVP 模式: 命中的最终形态把它 seq 下的变体高级形态一起带出来(如搜"魔力猫"带出"武斗酷猫")
    if pvp_filter:
        hit_seqs = {r["seq"] for r in results}
        for title, info in _FINAL_ALLOWED.items():
            if info["seq"] in hit_seqs and title not in seen_titles:
                seen_titles.add(title)
                form = info["form"]
                results.append({
                    "seq": info["seq"], "name": title,
                    "title": title, "types": form.get("type", []),
                    "match_by": "variant",
                })

    return results[:limit]


def get_all_pet_names() -> List[str]:
    """返回所有 page_title（与图片文件名一致）"""
    return sorted(_TITLE_TO_FORM.keys())


def get_all_pets_list(pvp_filter: bool = False) -> List[Dict]:
    """返回包含正确 seq 和 name 的全部精灵列表
    pvp_filter=True 时只返回高级形态及变体高级形态"""
    source = _FINAL_ALLOWED if pvp_filter else _TITLE_TO_FORM
    names = sorted(source.keys())
    return [{"name": n, "seq": source[n]["seq"]} for n in names]


def pet_to_dict(pet_seq: int, title: str = None) -> Optional[Dict[str, Any]]:
    return get_pet_by_seq(pet_seq, title)