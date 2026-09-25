# -*- coding: utf-8 -*-
"""技能名词库与 OCR 纠错。

背景: 技能名 OCR 没有像精灵名那样的纠错层 —— "淤泥表皮"曾被误读成
"游泥表皮"(2026-09-24 两份回合日志实证), 错名一路穿透图标(按名找
webp 404 → 降级成普通属性图标)、伤害推演(get_skill 落空)与回合日志。

本模块把 OCR 原文清洗成词库(data/pvp/skills.json, 570 条)内的合法
技能名; 纠不回来的返回空串, 让上层沿用上一帧的稳定值(识别结果显示
层与判定层分离: 单帧失败不清空)。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

# 词库来源(并集): data/pvp/skills.json + src/pvp/data/skills_with_tags.json +
# data/pvp/pet_skills.json(精灵→技能列表, 覆盖最广) + 图标库文件名
# (src/gui/web/assets/img/skills/*.webp, 与悬浮窗实际可渲染图标对齐)
_SOURCES = [
    Path(__file__).resolve().parents[2] / "data" / "pvp" / "skills.json",
    Path(__file__).resolve().parents[2] / "src" / "pvp" / "data" / "skills_with_tags.json",
    Path(__file__).resolve().parents[2] / "data" / "pvp" / "pet_skills.json",
    Path(__file__).resolve().parents[2] / "src" / "gui" / "web" / "assets" / "img" / "skills",
]

# 形近/误读混淆表: OCR 常见错字 → 候选真值。命中词库前的第一道纠正。
_CONFUSABLE = {
    "游": "淤",   # 淤泥表皮 → 游泥表皮
    "趟": "躺",
    "末": "未",
    "士": "土",
    "干": "千",
    "己": "已",
    "曰": "日",
    "刀": "刃",
    "爪": "瓜",
    "乌": "鸟",
    "目": "自",
    "拖": "施",
}

_lock = threading.Lock()
_names: list[str] = []
_name_set: set[str] = set()


def _load() -> None:
    global _names, _name_set
    if _names:
        return
    with _lock:
        if _names:
            return
        names: set[str] = set()
        for src in _SOURCES:
            try:
                if src.is_dir():
                    names.update(p.stem for p in src.glob("*.webp") if p.stem)
                    continue
                data = json.loads(src.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        names.add(str(k))
                        # pet_skills: 精灵名 → [技能名, ...]
                        if isinstance(v, list):
                            names.update(str(s) for s in v if isinstance(s, str))
                elif isinstance(data, list):
                    names.update(str(x.get("name")) for x in data
                                 if isinstance(x, dict) and x.get("name"))
            except Exception:
                continue
        names.discard("")
        _names = sorted(names)
        _name_set = set(_names)


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _variants(text: str):
    """原文 + 形近字替换候选(先单字, 长名再做两处)"""
    yield text
    for i, ch in enumerate(text):
        fixed = _CONFUSABLE.get(ch)
        if fixed:
            yield text[:i] + fixed + text[i + 1:]
    if len(text) >= 4:
        for i, ch in enumerate(text):
            fixed = _CONFUSABLE.get(ch)
            if not fixed:
                continue
            base = text[:i] + fixed + text[i + 1:]
            for j, ch2 in enumerate(base):
                fixed2 = _CONFUSABLE.get(ch2)
                if fixed2 and j != i:
                    yield base[:j] + fixed2 + base[j + 1:]


def correct_skill_name(raw: str, allow_fuzzy: bool = True) -> str:
    """OCR 原文 → 词库内技能名; 纠不回来返回空串(调用方沿用旧值)。"""
    _load()
    if not _names or not raw:
        return ""
    text = "".join(ch for ch in raw if ("\u4e00" <= ch <= "\u9fff") or ch.isalnum())
    if not text:
        return ""
    if text in _name_set:
        return text
    for cand in _variants(text):
        if cand in _name_set:
            return cand
    if allow_fuzzy:
        best, best_d = None, 10 ** 9
        for name in _names:
            if abs(len(name) - len(text)) > 2:
                continue
            d = _levenshtein(text, name)
            if d < best_d:
                best, best_d = name, d
        # 2~4 字名容错 1 字, 更长名容错 2 字; 距离超出视为垃圾(如 "VE"/"MMM")
        limit = 1 if len(text) <= 4 else 2
        if best is not None and best_d <= limit:
            return best
    return ""


def all_skill_names() -> list[str]:
    _load()
    return list(_names)
