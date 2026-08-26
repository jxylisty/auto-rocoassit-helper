# -*- coding: utf-8 -*-
"""精灵数据加载器 — 从 JSON 加载并按名称/编号查询"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR = Path(__file__).resolve().parent / "data"

with open(DATA_DIR / "pet_detail.json", "r", encoding="utf-8") as f:
    _PET_DETAIL: Dict[str, List[Dict]] = json.load(f)
with open(DATA_DIR / "pet_index.json", "r", encoding="utf-8") as f:
    _PET_INDEX: Dict[str, Dict] = json.load(f)
with open(DATA_DIR / "pet_skills.json", "r", encoding="utf-8") as f:
    _PET_SKILLS: Dict[str, Dict] = json.load(f)
with open(DATA_DIR / "pet_race_speed.json", "r", encoding="utf-8") as f:
    _PET_RACE_SPEED: Dict[str, int] = json.load(f)
with open(DATA_DIR / "leader_forms.json", "r", encoding="utf-8") as f:
    _LEADER_FORMS: List[int] = json.load(f)

LEADER_FORM_SET = set(_LEADER_FORMS)

# page_title → {seq, form}  每个形态独立索引
_TITLE_TO_FORM: Dict[str, Dict] = {}

for seq_str, forms in _PET_DETAIL.items():
    seq = int(seq_str)
    for form in forms:
        title = form.get("page_title", "")
        if title:
            _TITLE_TO_FORM[title] = {"seq": seq, "form": form}

# 名字 → 形态映射 (pet_index 的 name 字段)
_NAME_TO_TITLE: Dict[str, str] = {}
for key, entry in _PET_INDEX.items():
    seq = entry.get("seq", 0)
    name = entry.get("name", "")
    page_title = entry.get("page_title", name)
    if name and seq:
        _NAME_TO_TITLE[name] = page_title


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
        "is_leader": seq in LEADER_FORM_SET,
    }


# ---- 查询 API ----

def get_pet_count() -> int:
    return len(_PET_DETAIL)


def get_pet_by_name(name: str) -> Optional[Dict]:
    """按精灵名称查询（优先精确匹配 page_title）"""
    # 优先按 page_title 精确匹配（图片文件名用的就是这个）
    info = _TITLE_TO_FORM.get(name)
    if info:
        return _build_pet_dict(info["seq"], info["form"])
    # 兜底：按 pet_index 的 name 字段查
    title = _NAME_TO_TITLE.get(name)
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
    return pet_seq in LEADER_FORM_SET


def search_pets(query: str, limit: int = 20) -> List[Dict]:
    """模糊搜索。优先按 page_title 搜索（图片文件名一致）"""
    query_lower = query.lower()
    results = []
    seen = set()

    # 按 page_title 搜索（图片用的名字）
    for title, info in _TITLE_TO_FORM.items():
        if query_lower in title.lower():
            if info["seq"] not in seen:
                seen.add(info["seq"])
                form = info["form"]
                results.append({
                    "seq": info["seq"], "name": title,
                    "title": title, "types": form.get("type", []),
                    "match_by": "title",
                })

    # 按 pet_index 的 name 补搜
    for name, title in _NAME_TO_TITLE.items():
        if title not in seen and query_lower in name.lower():
            info = _TITLE_TO_FORM.get(title)
            if info:
                seen.add(info["seq"])
                form = info["form"]
                results.append({
                    "seq": info["seq"], "name": title,
                    "title": title, "types": form.get("type", []),
                    "match_by": "name",
                })

    return results[:limit]


def get_all_pet_names() -> List[str]:
    """返回所有 page_title（与图片文件名一致）"""
    return sorted(_TITLE_TO_FORM.keys())


def pet_to_dict(pet_seq: int, title: str = None) -> Optional[Dict[str, Any]]:
    return get_pet_by_seq(pet_seq, title)