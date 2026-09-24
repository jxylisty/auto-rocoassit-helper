# -*- coding: utf-8 -*-
"""rkpp_client — 订阅 RKPP opencode-server 的 /events，翻译成同构快照

架构定位（与 snapshot_adapter.py 平级，都是「抓包数据源适配器」）：

    [RKPP 独立进程]  rkpp_ref\\rkpp_live_tools.py opencode-server
          │  HTTP GET /events  (application/x-ndjson 实时流)
          ▼
    [本模块]  RkppEventClient  ← 后台线程订阅 + 事件翻译
          ▼
    [bridge_pvp.py]  source="rkpp" → 复用 _pvp_loop 下游(悬浮窗/推演/回合日志/AI)

为什么走 RKPP 而不是自研解密：
    0x1002 握手 key 是账号级、且解密后是嵌套 protobuf(schema 极深)；
    RKPP 已把 opcode → 结构化 JSON 全部做好，并额外给出精灵名/技能名/伤害。
    按 AGPL-3.0-only，RKPP 作为**独立进程/独立目录**运行，本项目只通过 HTTP
    订阅其输出，不拷贝其源码进仓库。

事件 schema（来自 RKPP rkpp_analyzer / rkpp_proto_battle，已实测核对）：
    battle_enter  detail.{battle_mode, battle_id, round, max_round,
                          weather_id, is_reconnect, wrappers:[...]}
    round_start   detail.{state_type, round, series_index, has_perform,
                          is_battle_finished, wrappers:[...]}
    server_skill_declare  detail.{skill_id, skill_name, skill_id_x100,
                                  command_slot, action_name, battle_token}
    action_resolve        detail.{primary_skill:{skill_id,skill_name},
                                  damage_event:{damage,damage_target_side,
                                                damage_target_side_name,
                                                target_hp_after,target_side},
                                  energy_event:{energy_delta,energy_after},
                                  effect_ids, has_defeat}
    battle_finish detail.{result_code, result_name, rounds, seconds,
                          is_surrender, pvp_score, finish_pet_infos:[...]}

    wrapper（精灵状态，battle_enter/round_start 都带）：
        {name, level, slot, pet_id, battle_max_hp, current_hp, battle_stats}

注意：本模块**不改 OCR 管线**，也不写 RKPP 源码；只做「事件 → 字段」的翻译。
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from src.pvp.pvp_pipeline import PvpResult
from src.pvp.skill_ids import resolve_skill_name

# ---- 我方 / 敌方判定 ----
# RKPP 的 side_name()：6/1 → 我方，401 → 敌方（实测对齐）
_PLAYER_SIDES = frozenset({1, 6})
_ENEMY_SIDES = frozenset({401})

# ---- 战斗 opcode → summary_kind（用于从 content/opencode 反查种类） ----
_OPCODE_TO_KIND = {
    "0x1316": "battle_enter",
    "0x131a": "round_start",
    "0x1322": "server_skill_declare",
    "0x1324": "action_resolve",
    "0x132c": "battle_finish",
}

# 进入战斗的事件种类
_ENTER_KINDS = frozenset({"battle_enter", "round_start", "server_skill_declare",
                          "action_resolve", "preplay", "pvp_perform"})
# 结束战斗的事件种类
_FINISH_KINDS = frozenset({"battle_finish"})


def _side_of(side_value: Any) -> str:
    """把 RKPP 的 side / damage_target_side 归一成 'player' / 'enemy' / ''."""
    try:
        s = int(side_value)
    except (TypeError, ValueError):
        return ""
    if s in _PLAYER_SIDES:
        return "player"
    if s in _ENEMY_SIDES:
        return "enemy"
    return ""


def _kind_of_event(event: dict) -> str:
    """从事件里取出 summary_kind（缺失时用 opencode 反查）。"""
    kind = str(event.get("summary_kind") or "").strip()
    if kind:
        return kind
    op = str(event.get("opencode") or "").strip().lower()
    if not op.startswith("0x"):
        try:
            op = hex(int(op))
        except (TypeError, ValueError):
            op = ""
    return _OPCODE_TO_KIND.get(op, "")


def _detail_of(event: dict) -> dict:
    """取事件的业务 detail（RKPP 把结构化数据放在 content.detail 里）。"""
    content = event.get("content")
    if not isinstance(content, dict):
        return {}
    detail = content.get("detail")
    if isinstance(detail, dict):
        return detail
    return content


class RkppEventClient:
    """订阅 RKPP relay /events，边收边翻译成 PvpResult 同构快照。

    线程模型（与 CaptureSnapshotAdapter 一致，便于 bridge_pvp 无差别消费）：
        - 订阅线程：阻塞读 NDJSON 流，每收到一条事件调 _apply_event() 更新状态
        - 主循环线程：调 analyze() 产出 PvpResult；调 to_dict()/to_snapshot_dict()
    内部用锁保护状态；in_battle 边沿（battle_start/battle_end）只投递一次。
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765",
                 *, logger=None) -> None:
        self.base_url = base_url.rstrip("/")
        self._logger = logger
        self._lock = threading.Lock()

        # ---- 状态机 ----
        self._battle_active = False
        self._prev_in_battle = False
        self._last_event_ts = 0.0
        self._last_kind = ""
        self._last_opcode_hex = ""

        # ---- 本局字段 ----
        self._round_no = 0
        self._declared_skills: list[str] = []      # 本局宣告技能名（去重）
        self._player_name = ""
        self._player_hp_val = 0
        self._player_hp_max = 0
        self._enemy_name = ""
        self._enemy_hp_val = 0
        self._enemy_hp_max = 0
        self._enemy_hp_pct = 0.0
        self._player_lineup: list = []
        self._enemy_lineup: list = []
        self._lineup_done = False
        self._errors: list[str] = []

        # ---- 订阅线程 ----
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------------- 生命周期 ----------------

    def start(self) -> None:
        """启动后台订阅线程（幂等）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="RkppEventClient")
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=timeout)
        self._thread = None

    def reset(self) -> None:
        with self._lock:
            self._battle_active = False
            self._prev_in_battle = False
            self._last_kind = ""
            self._last_opcode_hex = ""
            self._round_no = 0
            self._declared_skills.clear()
            self._player_name = ""
            self._player_hp_val = 0
            self._player_hp_max = 0
            self._enemy_name = ""
            self._enemy_hp_val = 0
            self._enemy_hp_max = 0
            self._enemy_hp_pct = 0.0
            self._player_lineup = []
            self._enemy_lineup = []
            self._lineup_done = False
            self._errors = []

    # ---------------- 订阅线程 ----------------

    def _run(self) -> None:
        url = f"{self.base_url}/events"
        backoff = 0.5
        while not self._stop.is_set():
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/x-ndjson"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    backoff = 0.5  # 连上就重置退避
                    for raw in resp:
                        if self._stop.is_set():
                            return
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(event, dict):
                            self.ingest_event(event)
            except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
                # relay 未起来/断开：退避重试，不刷屏
                self._stop.wait(backoff)
                backoff = min(5.0, backoff * 1.5)
            except Exception as exc:  # noqa: BLE001 - 订阅线程不能因单条异常退出
                self._log(f"RKPP 事件流异常: {exc}")
                self._stop.wait(1.0)

    def _log(self, msg: str) -> None:
        if self._logger is not None:
            try:
                self._logger(msg)
            except Exception:
                pass

    # ---------------- 健康检查 ----------------

    def health(self) -> Optional[dict]:
        """GET /health，relay 未启动/异常返回 None。"""
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=2) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def is_connected(self) -> bool:
        return self.health() is not None

    # ---------------- 事件翻译（核心） ----------------

    def ingest_event(self, event: dict) -> None:
        """把一条 RKPP 事件翻译成内部状态（订阅线程调用）。"""
        kind = _kind_of_event(event)
        if not kind:
            return
        op_hex = str(event.get("opencode") or "").strip().lower()
        with self._lock:
            self._last_event_ts = time.time()
            self._last_kind = kind
            self._last_opcode_hex = op_hex

            if kind in _ENTER_KINDS:
                self._battle_active = True
            elif kind in _FINISH_KINDS:
                # 胜负结果先落地，再让 analyze() 投递 battle_end 沿
                self._apply_finish(_detail_of(event))
                self._battle_active = False

            if kind == "battle_enter":
                self._apply_enter(_detail_of(event))
            elif kind == "round_start":
                self._apply_round_start(_detail_of(event))
            elif kind == "server_skill_declare":
                self._apply_skill_declare(_detail_of(event))
            elif kind == "action_resolve":
                self._apply_action_resolve(_detail_of(event))

    def _apply_enter(self, detail: dict) -> None:
        rnd = _as_int(detail.get("round"))
        if rnd and rnd > self._round_no:
            self._round_no = rnd
        self._apply_wrappers(detail.get("wrappers"))

    def _apply_round_start(self, detail: dict) -> None:
        rnd = _as_int(detail.get("round"))
        if rnd and rnd > self._round_no:
            self._round_no = rnd
        self._apply_wrappers(detail.get("wrappers"))

    def _apply_skill_declare(self, detail: dict) -> None:
        name = str(detail.get("skill_name") or "").strip()
        if not name:
            sid = detail.get("skill_id") or detail.get("skill_id_x100")
            if sid is not None:
                name = resolve_skill_name(sid)
        if name and name not in self._declared_skills:
            self._declared_skills.append(name)

    def _apply_action_resolve(self, detail: dict) -> None:
        primary = detail.get("primary_skill") or {}
        if isinstance(primary, dict):
            name = str(primary.get("skill_name") or "").strip()
            if not name and primary.get("skill_id") is not None:
                name = resolve_skill_name(primary["skill_id"])
            if name and name not in self._declared_skills:
                self._declared_skills.append(name)

        dmg = detail.get("damage_event") or {}
        if isinstance(dmg, dict):
            target = _side_of(dmg.get("damage_target_side") or dmg.get("target_side"))
            hp_after = _as_int(dmg.get("target_hp_after"))
            if target == "enemy" and hp_after is not None:
                self._enemy_hp_val = hp_after
                if self._enemy_hp_max > 0:
                    self._enemy_hp_pct = max(0.0, min(1.0, hp_after / self._enemy_hp_max))
            elif target == "player" and hp_after is not None:
                self._player_hp_val = hp_after

    def _apply_finish(self, detail: dict) -> None:
        pets = detail.get("finish_pet_infos") or []
        if isinstance(pets, list):
            for p in pets:
                if not isinstance(p, dict):
                    continue
                rhp = _as_int(p.get("remain_hp"))
                mhp = _as_int(p.get("battle_max_hp"))
                if rhp is not None and mhp:
                    pass  # 战后明细暂不入阵容，保留结构
        # 结果文本进 errors 之外不落字段（胜负由 in_battle 沿 + 回合日志消费）
        self._enemy_hp_pct = 0.0 if self._enemy_hp_val <= 0 else self._enemy_hp_pct

    def _apply_wrappers(self, wrappers: Any) -> None:
        """从精灵状态 wrappers 里挑出「场上双方」，填名字/血量/阵容。"""
        if not isinstance(wrappers, list) or not wrappers:
            return
        # wrappers 只有 name/level/slot/pet_id/current_hp/battle_max_hp，无 side。
        # 靠槽位约定：我方与敌方各占一批；用 slot 排序，前段作我方候选。
        # 实战中 0x1316/0x131A 的 wrappers 常同时含双方，故按「名字首次出现」填：
        #   第一个非空 → 我方；第二个不同名 → 敌方。
        names = []
        for w in wrappers:
            if not isinstance(w, dict):
                continue
            nm = str(w.get("name") or "").strip()
            if nm and nm not in names:
                names.append(nm)
        if not names:
            return

        if not self._player_name:
            self._player_name = names[0]
        if len(names) >= 2 and not self._enemy_name:
            self._enemy_name = names[1]

        # 血量：优先用与当前敌方同名的那条
        for w in wrappers:
            if not isinstance(w, dict):
                continue
            nm = str(w.get("name") or "").strip()
            mhp = _as_int(w.get("battle_max_hp")) or 0
            chp = _as_int(w.get("current_hp"))
            if nm == self._enemy_name and chp is not None:
                if mhp > 0:
                    self._enemy_hp_max = mhp
                    self._enemy_hp_val = chp
                    self._enemy_hp_pct = max(0.0, min(1.0, chp / mhp))
            elif nm == self._player_name and chp is not None:
                if mhp > 0:
                    self._player_hp_max = mhp
                    self._player_hp_val = chp

        # 阵容：把出现的名字按顺序补进去（最多 6）
        if not self._lineup_done:
            lineup = list(names[:6])
            if len(lineup) >= 2:
                self._player_lineup = lineup
                self._enemy_lineup = []
                self._lineup_done = False  # 单场对手只解出 1 只时不标 done

    # ---------------- 主循环侧：产出同构快照 ----------------

    def analyze(self) -> PvpResult:
        """产出与 OCR 管线完全同构的 PvpResult（含 battle_start/battle_end 沿）。"""
        with self._lock:
            in_battle = self._battle_active
            prev = self._prev_in_battle
            self._prev_in_battle = in_battle

            result = PvpResult(in_battle=in_battle)
            result.battle_start = in_battle and not prev
            result.battle_end = (not in_battle) and prev

            round_no = self._round_no
            declared = list(self._declared_skills)

            if result.battle_start:
                # 新一局开局：清空上局残留（技能/回合/血量）
                self._declared_skills.clear()
                self._round_no = 0
                self._player_hp_val = 0
                self._player_hp_max = 0
                self._enemy_hp_pct = 0.0
                round_no = 0
                declared = []

            if in_battle:
                result.player_name = self._player_name
                result.player_name_conf = 1.0
                result.player_name_via_avatar = True
                result.enemy_name = self._enemy_name
                result.enemy_name_conf = 1.0
                result.enemy_name_via_avatar = True
                result.player_hp_val = self._player_hp_val
                result.player_hp_max = self._player_hp_max
                if self._player_hp_max > 0:
                    result.player_hp = f"{self._player_hp_val}/{self._player_hp_max}"
                result.enemy_hp_pct = self._enemy_hp_pct
                result.enemy_hp_color = 1.0 if self._enemy_hp_max > 0 else 0.0
                if declared:
                    slots = ["", "", "", ""]
                    for i, nm in enumerate(declared[:4]):
                        slots[i] = nm
                    result.skills = slots
            else:
                # 非战斗态清空精灵名（与 PvpPipeline 语义一致，防串场）
                result.player_name = ""
                result.enemy_name = ""
                result.player_name_conf = 0.0
                result.enemy_name_conf = 0.0
                result.skills = ["", "", "", ""]

            # 抓包特有字段（回合日志 set_authoritative_round 会读它）
            result.round_no = round_no
            result._rkpp_kind = self._last_kind  # type: ignore[attr-defined]
            result._rkpp_opcode_hex = self._last_opcode_hex  # type: ignore[attr-defined]
        return result

    def to_dict(self, result: PvpResult) -> dict:
        """复用 PvpPipeline.to_dict，保证键集合与 OCR 源 100% 同构。"""
        from src.pvp.pvp_pipeline import get_pipeline
        return get_pipeline().to_dict(result)


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_client: Optional[RkppEventClient] = None


def get_rkpp_client(base_url: str = "http://127.0.0.1:8765", *, logger=None) -> RkppEventClient:
    global _client
    if _client is None:
        _client = RkppEventClient(base_url, logger=logger)
    return _client
