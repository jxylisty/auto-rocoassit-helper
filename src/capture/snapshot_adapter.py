# -*- coding: utf-8 -*-
"""snapshot_adapter — 抓包数据源适配器

把「抓包 → 解密 → 业务记录」的结果翻译成与 OCR 管线完全同构的
PvpResult 对象 / to_dict() 字典，从而让 bridge_pvp 的 _pvp_loop
可以「一行切换数据源」，下游（悬浮窗 / 伤害推演 / 回合日志 / AI / MCP）
零改动复用。

设计原则：
    1. 只读，不抓包：真正的抓包由 PacketCaptureEngine 在后台线程跑，
       本模块只维护「最新一帧快照」并做 opcode → 字段的语义映射。
    2. 同构优先：BattleSnapshot.to_dict() 的键集合与 PvpPipeline.to_dict
       完全一致（player/player_lineup/enemy/enemy_lineup/in_battle/errors/lineup_done）。
    3. 语义映射分层：目前 opcode 语义只解出「是否在战斗中」这一层；
       精灵名/血量/技能等字段留占位，等 opcode → 字段映射补齐后填入。
       未填的字段给安全默认值，让下游按「名字未识别」正常降级，不报错。

用法（在 bridge_pvp._pvp_loop 里）：
    adapter = get_capture_adapter()
    adapter.set_source_records(...)   # 由抓包线程喂入
    result = adapter.analyze()        # 产出 BattleSnapshot
    data = adapter.to_dict(result)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from src.pvp.skill_ids import resolve_skill_name

# ---- 战斗相关 opcode（与 battle_listener 的解析口径一致）----
OP_BATTLE_PAIR = 0x1314        # 对战配对（进战斗）
OP_BATTLE_ENTER = 0x1316       # 进入战斗
OP_BATTLE_ROUND_START = 0x131A  # 回合开始
OP_SKILL_DECLARE = 0x1322      # 服务端技能宣告（含技能 ID）
OP_ACTION_RESOLVE = 0x1324     # 行动结算（伤害/换宠）
OP_BATTLE_FINISH = 0x132C      # 战斗结束

# 判定「当前处于战斗中」的 opcode 集合
_IN_BATTLE_OPS = frozenset({
    OP_BATTLE_PAIR, OP_BATTLE_ENTER, OP_BATTLE_ROUND_START,
    OP_SKILL_DECLARE, OP_ACTION_RESOLVE,
})
# 判定「战斗已结束」的 opcode 集合
_BATTLE_END_OPS = frozenset({OP_BATTLE_FINISH})


@dataclass
class BattleSnapshot:
    """与 pvp_pipeline.PvpResult 字段对齐的快照对象。

    _enrich_result(data, result) 会读取 result.player_name / enemy_name /
    skills / player_hp_val / enemy_hp_pct，故这些属性必须齐备。
    """

    player_name: str = ""
    player_name_conf: float = 0.0
    player_hp: str = ""            # 形如 "326/326"
    player_hp_val: int = 0
    player_hp_max: int = 0
    enemy_name: str = ""
    enemy_name_conf: float = 0.0
    enemy_name_via_avatar: bool = False
    player_name_via_avatar: bool = False
    enemy_hp_pct: float = 0.0
    enemy_hp_color: float = 0.0
    skills: list[str] = field(default_factory=lambda: ["", "", "", ""])
    energy: str = ""
    energy_val: int = 0
    in_battle: bool = False
    battle_start: bool = False
    battle_end: bool = False
    lineup_new: bool = False
    errors: list[str] = field(default_factory=list)
    player_lineup: list = field(default_factory=list)
    enemy_lineup: list = field(default_factory=list)
    lineup_done: bool = False
    # 抓包特有：真实回合号（来自 0x131A，权威值；OCR 侧无此信息，靠猜）
    round_no: int = 0
    # 抓包特有：最新一条业务记录的 opcode（便于排查/调试）
    last_opcode: int = 0


def to_snapshot_dict(result: BattleSnapshot) -> dict[str, Any]:
    """与 PvpPipeline.to_dict 严格同构的字典（键集合完全一致）。

    刻意不追加任何额外键，保证下游（悬浮窗 / 回合日志 / AI / MCP）拿到的
    结构与 OCR 数据源 100% 一致，可无差别消费。
    """
    return {
        "player": {
            "name": result.player_name,
            "name_conf": result.player_name_conf,
            "hp": result.player_hp,
            "hp_val": result.player_hp_val,
            "hp_max": result.player_hp_max,
            "skills": result.skills,
            "name_via_avatar": result.player_name_via_avatar,
            "energy": result.energy,
            "energy_val": result.energy_val,
        },
        "enemy": {
            "name": result.enemy_name,
            "name_conf": result.enemy_name_conf,
            "name_via_avatar": result.enemy_name_via_avatar,
            "hp_pct": result.enemy_hp_pct,
            "hp_color": result.enemy_hp_color,
            "occluded": (result.enemy_hp_color <= 0.0
                         and result.enemy_name_conf < 0.9),
        },
        "in_battle": result.in_battle,
        "errors": result.errors,
        "player_lineup": result.player_lineup if result.lineup_done else [],
        "enemy_lineup": result.enemy_lineup if result.lineup_done else [],
        "lineup_done": result.lineup_done,
    }


def _walk_varints(tree: dict | None) -> list[int]:
    """递归收集 protobuf 树里所有 varint（wire==0）字段的值。"""
    out: list[int] = []
    if not isinstance(tree, dict):
        return out
    for f in tree.get("fields", ()) or ():
        if f.get("wire") == 0 and "value" in f:
            out.append(int(f["value"]))
        sub = f.get("sub")
        if isinstance(sub, dict):
            out += _walk_varints(sub)
    return out


def _top_varint(tree: dict | None, field_no: int) -> int | None:
    """取 protobuf 顶层某个 field 的 varint 值（不存在返回 None）。"""
    if not isinstance(tree, dict):
        return None
    for f in tree.get("fields", ()) or ():
        if f.get("field") == field_no and f.get("wire") == 0 and "value" in f:
            return int(f["value"])
    return None


def _extract_round_no(tree: dict | None) -> int | None:
    """从 0x131A（回合开始）里提取真实回合号。

    实测结构：顶层 field=3 为回合计数 varint（1,2,3,4... 逐回合递增）。
    """
    return _top_varint(tree, 3)


def _extract_skill_ids(tree: dict | None) -> list[int]:
    """从 0x1322 的 protobuf 树里提取技能 ID。

    实测结构：tree.fields[f=2].sub.fields[f=2].sub.fields[f=1] = 9 位技能 ID。
    这里做通用兜底：取所有形如「7~9 位、且去尾三位能命中技能库」的 varint。
    """
    out: list[int] = []
    for v in _walk_varints(tree):
        s = str(v)
        if 7 <= len(s) <= 10 and s[0] != "0" and resolve_skill_name(v):
            if v not in out:
                out.append(v)
    return out


class CaptureSnapshotAdapter:
    """把抓包业务流翻译成 PvpResult 同构快照。

    线程模型：
        抓包线程调 ingest(record) 喂入业务记录（record 为 battle_listener
        产出的 dict，含 opcode_hex / tree 等）；主循环线程调 analyze() 取快照。
        内部用锁保护「最新快照」，保证边沿标记只投递一次。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prev_in_battle = False
        self._latest_opcode = 0
        self._battle_active = False
        self._last_ingest_ts = 0.0
        # 本局宣告过的技能名（按出现顺序去重），来自 0x1322
        self._declared_skills: list[str] = []
        # 真实回合号（来自 0x131A，权威值），0 表示尚未收到
        self._round_no = 0

    # ---------------- 抓包线程侧：喂入 ----------------

    def ingest(self, record: dict) -> None:
        """喂入一条业务记录（battle_listener 产出的 dict）。"""
        opcode = int(record.get("opcode") or 0)
        with self._lock:
            self._latest_opcode = opcode
            self._last_ingest_ts = time.time()
            if opcode in _IN_BATTLE_OPS:
                self._battle_active = True
            elif opcode in _BATTLE_END_OPS:
                self._battle_active = False

            if opcode == OP_SKILL_DECLARE:
                for sid in _extract_skill_ids(record.get("tree")):
                    name = resolve_skill_name(sid)
                    if name and name not in self._declared_skills:
                        self._declared_skills.append(name)

            if opcode == OP_BATTLE_ROUND_START:
                # 新回合开始：刷新权威回合号（只增不减，防乱序回退）
                rn = _extract_round_no(record.get("tree"))
                if rn is not None and rn > self._round_no:
                    self._round_no = rn

    # ---------------- 主循环侧：产出快照 ----------------

    def analyze(self) -> BattleSnapshot:
        """产出当前快照。in_battle 由 opcode 状态机决定，并计算状态沿。"""
        with self._lock:
            in_battle = self._battle_active
            prev = self._prev_in_battle
            self._prev_in_battle = in_battle
            last_opcode = self._latest_opcode
            declared = list(self._declared_skills)
            round_no = self._round_no

        snap = BattleSnapshot(in_battle=in_battle, last_opcode=last_opcode)
        snap.battle_start = in_battle and not prev
        snap.battle_end = (not in_battle) and prev
        if snap.battle_start or snap.battle_end:
            # 场景切换：阵容会话失效（与 OCR 管线语义一致）
            snap.lineup_done = False
        if snap.battle_start:
            with self._lock:
                self._declared_skills.clear()
                self._round_no = round_no = 0

        # ---- 语义映射：真实回合号（来自 0x131A，权威值） ----
        snap.round_no = round_no

        # ---- 语义映射：技能（已实测对齐真值） ----
        # 0x1322 逐条宣告技能 ID，去尾三位查图标库得技能名。
        # 填进 skills 前 4 个槽位（与 OCR 的 4 技能布局一致）。
        if snap.in_battle and declared:
            slots = ["", "", "", ""]
            for i, name in enumerate(declared[:4]):
                slots[i] = name
            snap.skills = slots

        # ---- 语义映射占位（精灵名/血量待补） ----
        if not snap.in_battle:
            snap.player_name = ""
            snap.enemy_name = ""
            snap.skills = ["", "", "", ""]
        return snap

    def to_dict(self, result: BattleSnapshot) -> dict[str, Any]:
        return to_snapshot_dict(result)

    def reset(self) -> None:
        with self._lock:
            self._prev_in_battle = False
            self._latest_opcode = 0
            self._battle_active = False
            self._declared_skills.clear()
            self._round_no = 0


_adapter: CaptureSnapshotAdapter | None = None


def get_capture_adapter() -> CaptureSnapshotAdapter:
    global _adapter
    if _adapter is None:
        _adapter = CaptureSnapshotAdapter()
    return _adapter
