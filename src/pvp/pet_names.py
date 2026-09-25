# -*- coding: utf-8 -*-
"""pet_names — 游戏图鉴 ID → 显示名 映射(含全部进化形态)。

背景: RKPP 抓包的宠物名(conf_name)来自其内置 id→名 查表, 而那张表混有
大量游戏内部测试/野外模板条目("40级水桶模板"、"5星30级测试水蓝蓝"),
且部分表项停留在未进化形态 —— 导致抓包把已进化的精灵显示成低级形态。

本模块用项目自己的 wiki 数据(src/pvp/data/pet_detail.json)重建映射:
img URL 里的 /pets/<id>/ 就是游戏图鉴 ID(实测 迪莫=3004 / 圣光迪莫=5025 /
喵呜=3025 / 护主犬=3070), 每个进化形态是独立条目, 共 649 条, 是显示名的
权威来源。

用法:
    from src.pvp.pet_names import pet_name_by_id
    pet_name_by_id(3025)        # -> "喵呜"
    pet_name_by_id("3025")      # -> "喵呜"
    pet_name_by_id(0)           # -> ""
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

_PET_DETAIL = Path(__file__).resolve().parents[2] / "src" / "pvp" / "data" / "pet_detail.json"

_ID_RE = re.compile(r"/pets/(\d+)/")

_lock = threading.Lock()
_map: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _map
    if _map is not None:
        return _map
    with _lock:
        if _map is not None:
            return _map
        mapping: dict[str, str] = {}
        try:
            data = json.loads(_PET_DETAIL.read_text(encoding="utf-8"))
            stack = [data]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    title = cur.get("page_title")
                    img = cur.get("img") or ""
                    if title and img:
                        m = _ID_RE.search(str(img))
                        if m:
                            mapping.setdefault(m.group(1), str(title))
                    stack.extend(cur.values())
                elif isinstance(cur, list):
                    stack.extend(cur)
        except Exception:
            pass
        _map = mapping
        return _map


def pet_name_by_id(pet_id) -> str:
    """图鉴 ID( int 或数字串 ) → 显示名; 查不到返回空串。"""
    m = _load()
    if not m or pet_id is None:
        return ""
    key = str(pet_id).strip()
    return m.get(key, "")


def map_size() -> int:
    return len(_load())
