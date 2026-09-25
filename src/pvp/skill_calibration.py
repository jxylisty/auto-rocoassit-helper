# -*- coding: utf-8 -*-
"""skill_calibration — 技能 ID→名字 校准表(OCR 槽位对齐, 最高优先级数据源)

背景(2026-09-25): 抓包技能名是启发式配对产物, 与 wiki 权威表大面积冲突
(41 条真实对照 0 命中, "你的技能真好用"。被当成技能名)。ID 是稳定锚点,
OCR 是唯一可靠的名字来源 —— 两者在"我方技能栏"处天然对齐:

    battle_enter 的 skill_round_data 带 (pos=HUD槽位1~4, skill_id)
    我方技能栏 OCR (read_skill_bar) 按同样 4 个槽位读出准确名字
    → id→名 逐槽写入本表, 零猜测。

本表是 resolve_skill_name 的第一优先级; wiki 索引次之; 都查不到返回
空串(宁空勿错, 绝不返回启发式猜测名)。

存储: data/pvp/skill_id_calibrated.json
    { "7020620": {"name": "力量增效", "src": "ocr_slot", "ts": "..."}, ... }
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

_CALIB_FILE = Path(__file__).resolve().parents[2] / "data" / "pvp" / "skill_id_calibrated.json"

_lock = threading.Lock()
_table: dict[str, dict] | None = None
_conflicts: list[dict] = []          # 同 ID 不同名的证据(落盘供排查)


def _load() -> dict[str, dict]:
    global _table
    if _table is not None:
        return _table
    with _lock:
        if _table is not None:
            return _table
        table: dict[str, dict] = {}
        try:
            raw = json.loads(_CALIB_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                table = {str(k): v for k, v in raw.items() if isinstance(v, dict) and v.get("name")}
        except Exception:
            table = {}
        _table = table
        return _table


def _save() -> None:
    try:
        _CALIB_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CALIB_FILE.write_text(
            json.dumps(_table or {}, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8")
    except Exception:
        pass


def record(pairs: dict, *, source: str = "ocr_slot", overwrite: bool = False) -> list[dict]:
    """写入校准对 {7位id(str/int): 名字}。同名幂等; 冲突保留首个并记证据。

    返回本次实际新增/更新的条目列表 [{id, name}]。
    """
    global _table
    if not pairs:
        return []
    with _lock:
        if _table is None:
            _load()
        changed: list[dict] = []
        for raw_id, name in pairs.items():
            sid = str(raw_id).strip()
            nm = str(name or "").strip()
            if not sid or not nm:
                continue
            cur = (_table or {}).get(sid)
            if cur is None:
                _table[sid] = {"name": nm, "src": source, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
                changed.append({"id": sid, "name": nm})
            elif cur.get("name") != nm:
                _conflicts.append({"id": sid, "kept": cur.get("name"), "new": nm,
                                   "src_new": source, "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
                if overwrite:
                    _table[sid] = {"name": nm, "src": source, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
                    changed.append({"id": sid, "name": nm})
        if changed:
            _save()
        return changed


def name_for(skill_id) -> str:
    """校准表查询: 有则返回权威名, 无则空串(调用方继续走 wiki/降级)。"""
    if skill_id is None:
        return ""
    sid = str(skill_id).strip()
    if not sid:
        return ""
    entry = _load().get(sid)
    return str(entry.get("name") or "") if entry else ""


def take_conflicts() -> list[dict]:
    """取出并清空冲突证据(UI 日志/落盘用)。"""
    with _lock:
        out, _conflicts[:] = list(_conflicts), []
        return out


def size() -> int:
    return len(_load())


def all_ids() -> list[str]:
    return list(_load().keys())
