# -*- coding: utf-8 -*-
"""skill_ids — 抓包技能 ID → 技能名 反查

背景（实测对齐真值得到）：
    抓包 0x1322/0x1324 里的技能 ID 是 9 位数字，形如 704017000；
    而技能图标库里用的是 7 位 ID（7040170），二者关系为：
        9 位抓包值 = 7 位技能 ID * 1000 + 形态/参数位
    即去尾三位（取前 7 位）即可命中图标库。

    实测对齐（用户亲述本局操作）：
        704017000 -> 7040170 -> 火苗
        702078000 -> 7020780 -> 防御
        704021000 -> 7040210 -> 流星火雨
        700001000 -> 7000010 -> (不在技能库, 为「聚能」等战斗动作)

数据来源：data/pvp/skill_icons.json（{技能名: "data/pvp/skill_icons/<7位ID>.png"}）。
    该文件含 547 个带数字 ID 的技能，ID 唯一无重复。

用法：
    from src.pvp.skill_ids import resolve_skill_name
    resolve_skill_name(704017000)   # -> "火苗"
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ICON_INDEX = PROJECT_ROOT / "data" / "pvp" / "skill_icons.json"

_ID_RE = re.compile(r"(\d{7})")

_id_to_name: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _id_to_name
    if _id_to_name is not None:
        return _id_to_name
    mapping: dict[str, str] = {}
    try:
        raw = json.loads(_ICON_INDEX.read_text(encoding="utf-8"))
        for name, path in raw.items():
            m = _ID_RE.search(str(path))
            if m:
                mapping.setdefault(m.group(1), name)
    except Exception:
        mapping = {}
    _id_to_name = mapping
    return mapping


def normalize_skill_id(value: int | str) -> str | None:
    """把抓包里的技能 ID 规范成图标库的 7 位 ID。

    算法与 RKPP 同源：抓包原始值形如 7 位技能 ID * 1000（即 9 位、末三位为 0），
        9 位值 // 1000 == 7 位技能 ID
    仅当「值 >= 100000 且末两位为 0」时才去尾两位，避免误截 6 位尾变体；
    已是 7 位（或其它形态）的值原样保留，若不足 7 位则返回 None。

    实测对齐（与 RKPP normalize_skill_id 在真实技能 ID 上完全等价）：
        704017000 -> 7040170
        702078000 -> 7020780
        704021000 -> 7040210
    """
    if value is None:
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    # 9 位抓包值（末两位为 0）-> 7 位技能 ID
    if v >= 100_000 and v % 100 == 0:
        sid = v // 100
    else:
        sid = v
    s = str(sid)
    if len(s) < 7:
        return None
    return s


def resolve_skill_name(value: int | str) -> str:
    """抓包技能 ID → 技能名。查不到返回空字符串（调用方自行降级）。

    优先级: wiki 图鉴索引 → 校准表(skill_calibration, 仅补 wiki 缺口)。
    实测 2026-09-26: wiki 对真实技能组 4/4 命中, 而残缺帧 OCR 曾把
    7040260(引燃) 校准成 '一拳' —— 校准表优先会让毒数据压住权威名。
    wiki 优先后, 校准表只负责 wiki 覆盖不到的 ID, 毒数据自动失效。
    """
    sid = normalize_skill_id(value)
    if sid is None:
        return ""
    name = _load().get(sid, "")
    if name:
        return name
    try:
        from src.pvp.skill_calibration import name_for
        return name_for(sid)
    except Exception:
        return ""


def resolve_skill_name_or_raw(value: int | str) -> str:
    """查得到返回技能名，查不到返回原始 ID 字符串（用于调试/未知动作）。"""
    sid = normalize_skill_id(value)
    if sid is None:
        return str(value)
    return _load().get(sid, str(value))


def index_size() -> int:
    return len(_load())


def reload() -> None:
    global _id_to_name
    _id_to_name = None
    _load()
