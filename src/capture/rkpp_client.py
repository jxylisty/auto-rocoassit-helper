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

事件 schema（实测自 rkpp_opencode_server_*/opencode_summary.csv 与 /latest 真实流）：
    relay 每个事件的顶层键：opencode / meaning / summary_kind / summary_text / content
    业务数据全部在 content 里，**没有** detail 包裹层，也**没有** wrappers 数组。

    battle_enter  (0x1316)  content.{battle_mode, round, weather_id, max_round,
                                      init_info:{player_team:[], enemy_team:[]}}
        init_info.player_team[i].pets[j].battle_inside_pet_info:
            {pet_id, name(hex), conf_name, battle_attr:[...]}
            battle_attr[1]  = 当前血量（权威）
            battle_attr[25] = 最大血量（权威）
        battle_common_pet_info.{conf_name, level}
        玩家 pet_id 取值范围 1..6；敌方 pet_id=401（不是 side 字段）。

    round_start   (0x131A)  content.{state_info:{round,battle_id},
                                      perform_cmd:{perform_info:[...]}}
        perform_info[].data_update:
            .pet.battle_inside_pet_info        → 我方上场宠
            .other.{role_uin, pets:[...]}      → 敌方上场宠
            .pet_skill.{pet_id, skills:[{skill_desc,...}]} → 技能名

    server_skill_declare (0x1322) content.{player_uin,
                                      req:{cast_skill:{skill_id, skill_desc}}}

    action_resolve (0x1324) content.perform_cmd.perform_info:[
            {type:1, skill_cast:{caster_id, target_id:[], skill_desc}}
            {type:4, damage_info:{caster_id, target_id, source_id},
                     sync_data:{pet_sync_info:[{pet_id, hp_result}, ...]}}
        ]

    battle_finish (0x132C)  content.settle_info.{result, real_pvp, real_pve,
                                      rounds, seconds, monster_info:[...]}
        result: 12=RUNAWAY, 2=WIN, 4=LOSE（见 rkpp_proto_battle.BATTLE_RESULT_MAP）

注意：本模块**不改 OCR 管线**，也不写 RKPP 源码；只做「事件 → 字段」的翻译。
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from src.pvp.pvp_pipeline import PvpResult
from src.pvp.pet_names import pet_name_by_id
from src.pvp.skill_ids import resolve_skill_name

# id→名 对照表落盘位置（每局结束追加合并，越跑越全）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SKILL_MAP_FILE = _PROJECT_ROOT / "data" / "pvp" / "skill_id_name_map.json"

# ---- 我方 / 敌方判定 ----
# 实测：玩家队伍 pet_id ∈ 1..6，敌方 pet_id = 401。battle_enter 的 base.side
# 是 0(玩家)/1(敌人)，但 perform 里的 caster_id/target_id 用的是 pet_id，
# 因此统一按「pet_id 区间」判定，避免 6/401 与 0/1 混淆。
_ENEMY_PET_ID = 401


def _side_of_pet_id(pet_id: Any) -> str:
    """把 pet_id 归一成 'player' / 'enemy' / ''。"""
    try:
        pid = int(pet_id)
    except (TypeError, ValueError):
        return ""
    if pid == _ENEMY_PET_ID:
        return "enemy"
    if 1 <= pid <= 6:
        return "player"
    return ""


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

# battle_finish.result → 胜负（对齐 rkpp_proto_battle.BATTLE_RESULT_MAP 的关键项）
_RESULT_MAP = {
    2: "WIN", 4: "LOSE", 18: "WIN", 34: "WIN", 66: "WIN", 68: "LOSE",
    10: "RUNAWAY", 12: "RUNAWAY", 260: "RUNAWAY", 132: "RUNAWAY", 516: "RUNAWAY",
}

# RKPP 对「隐藏特性/占位技能」给的说明文本，不是真正的技能名，需过滤
_SKILL_PLACEHOLDERS = frozenset({
    "此精灵被隐藏起来了，看不出特性",
    "对对手赋予EFFECT。",
    "？？？",
    "赋予效果用技能",
})


def _is_effect_text(text: str) -> bool:
    """判断一段文本是不是「技能效果描述」（而非技能名）。

    ★ 实测规律（用 2 局真实对局、29 个技能全量统计得出）：
      RKPP 的 skill_desc / skill_name 在**部分**技能里是反置的，且无法靠
      「含『。』」区分（名字本身就带句号的例子：desc='“你的技能真好用”。'，
      name='对战课的某个老师，认为…是为“截”。'）。真正稳定的判据是「文本
      结构」——效果描述必然是句子/带内嵌标记，技能名是短标签：
        · 含内嵌标记 <desc_id=  或 </>  → 效果
        · 含中文逗号「，」/分号「；」   → 效果
        · 以「。」结尾且长度 > 8        → 效果
        · 长度 > 12                     → 效果
      用「谁不像效果谁就是名」，在 29 个技能上 100% 命中。
    """
    t = str(text or "").strip()
    if not t:
        return False
    if "<desc_id=" in t or "</>" in t:
        return True
    if "，" in t or "；" in t or ":" in t:
        return True
    if t.endswith("。") and len(t) > 8:
        return True
    return len(t) > 12


def _skill_display_name(sk: dict) -> str:
    """取一条 skill 条目的「显示名」（应对 skill_desc / skill_name 反置）。

    规则：desc 不像效果 → 用 desc（多数情况）；否则若 name 不像效果 → 用 name；
    两边都像效果时退回 desc。技能名原样返回，不做任何字符裁剪（名字可能自带
    引号/句号，如 desc='“你的技能真好用”。' 就是真名）。
        id=7040390 desc='闪燃'        name='造成物伤，自己回复1能量。' → 闪燃
        id=7020780 desc='敌方获得…+2。' name='聒噪'                     → 聒噪
    """
    desc = str(sk.get("skill_desc") or "").strip()
    name = str(sk.get("skill_name") or "").strip()
    if not _is_effect_text(desc):
        return desc
    if not _is_effect_text(name):
        return name
    return desc or name


def _enemy_cast_name(sk: dict) -> str:
    """敌方施法的显示名: ID 解析优先, 词库次之, 结构启发式最后。

    2026-09-25: 启发式配对被证实与 wiki 权威表大面积错位(41/41 冲突),
    ID 才是稳定锚点 —— 校准表(OCR 槽位实测) → wiki 图鉴索引 → 包内名字
    (须经词库校验, 防反置/描述句) → 启发式兜底。
    """
    sid = _as_int(sk.get("skill_id")) if isinstance(sk, dict) else None
    if sid is not None:
        by_id = resolve_skill_name(sid)
        if by_id:
            return by_id
    desc = str(sk.get("skill_desc") or "").strip()
    name = str(sk.get("skill_name") or "").strip()
    try:
        from src.pvp.skill_lexicon import correct_skill_name
        for cand in (name, desc):
            if cand and correct_skill_name(cand, allow_fuzzy=False):
                return cand
    except Exception:
        pass
    return _skill_display_name(sk)


def _iter_battle_skill_pairs(skills: Any):
    """从一组 skill 条目里产出 (skill_id, 显示名)，只保留战斗技能。

    特性/占位项的 skill_id 是 6 位（200146/7000010/7000030），战斗技能是 7 位
    （如 7040390）。过滤条件：skill_id >= 1000000 且名字非占位文本。
    名字用 _skill_display_name 判定（应对 skill_desc/skill_name 反置）。
    """
    if not isinstance(skills, list):
        return
    for sk in skills:
        if not isinstance(sk, dict):
            continue
        sid = _as_int(sk.get("skill_id"))
        if sid is None or sid < 1000000:
            continue
        nm = _skill_display_name(sk)
        if not nm or nm in _SKILL_PLACEHOLDERS:
            continue
        yield sid, nm


def _iter_battle_skill_entries(skills: Any):
    """产出战斗技能的完整条目 {skill_id, name, pos, original_skill_id}。

    与 _iter_battle_skill_pairs 的区别: 保留槽位号(pos, HUD 1~4)与变体回链
    (original_skill_id, 应对/形态变化时游戏换用变体 ID 并回填原 ID) ——
    OCR 槽位校准闭环靠这两个字段做精确对齐。
    """
    if not isinstance(skills, list):
        return
    for sk in skills:
        if not isinstance(sk, dict):
            continue
        sid = _as_int(sk.get("skill_id"))
        if sid is None or sid < 1000000:
            continue
        nm = _skill_display_name(sk)
        if not nm or nm in _SKILL_PLACEHOLDERS:
            continue
        yield {
            "skill_id": sid,
            "name": nm,
            "pos": _as_int(sk.get("pos")),
            "original_skill_id": _as_int(sk.get("original_skill_id")),
        }


def _pick_battle_skills(skills: Any) -> list[str]:
    """从一组 skill 条目里挑出 4 个「战斗技能」名（去重）。"""
    bar: list[str] = []
    for _sid, nm in _iter_battle_skill_pairs(skills):
        if nm not in bar:
            bar.append(nm)
    return bar[:4]


def _skill_pairs_map(skills: Any) -> dict:
    """从一组 skill 条目里取 {7位skill_id: 技能名}，用于导出 id→名 对照表。"""
    out: dict[str, str] = {}
    for sid, nm in _iter_battle_skill_pairs(skills):
        out[str(sid)] = nm
    return out


def _decode_cn_hex(raw: Any) -> str:
    """battle_inside_pet_info.name 是 UTF-8 的 hex 串（如 e78ab9→火），可解则解。"""
    s = str(raw or "").strip()
    if len(s) < 4 or len(s) % 2 or any(ch not in "0123456789abcdefABCDEF" for ch in s):
        return ""
    try:
        return bytes.fromhex(s).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def _parse_pet_info(bip: dict, *, common: Optional[dict] = None) -> dict:
    """从 battle_inside_pet_info 解析出 {pet_id, name, level, hp, hp_max, pos}。

    ★ 名字解析链(2026-09-25 重排, 修"进化宠显示低级形态"):
        1. 服务器下发的 name(field 23, hex→明文) — 客户端实际显示什么就传什么
        2. conf_id 用项目 wiki 图鉴映射(pet_names) 查显示名 — 每个进化形态是
           独立图鉴条目(迪莫=3004/圣光迪莫=5025), 覆盖全部 649 形态
        3. RKPP 附带的 conf_name — 其内置查表混有测试/野外模板且偏基础形态,
           只作兜底
      conf_id / base_conf_id 原始值一并带出(out["conf_id"] 等), 供证据日志。

    ★ battle_attr 布局（实测全事件一致，与事件种类无关）：
        battle_attr[1]  = 最大血量（恒定）
        battle_attr[25] = 当前血量（会随回合递减）
    battle_enter 时二者相等（满血）。早期版本误以为布局会反转，实为同布局，
    这里统一取值即可。

    ★ pos：uint64。pos 为小值(如 1) 表示该精灵正在场上；
       pos=18446744073709551615(uint64 max) 表示不在场。
    """
    out = {"pet_id": None, "name": "", "level": 0, "hp": None, "hp_max": 0, "pos": None,
           "skills": [], "skill_map": {}, "conf_id": None, "base_conf_id": None,
           "bar_entries": []}
    if not isinstance(bip, dict):
        return out
    out["pet_id"] = _as_int(bip.get("pet_id"))
    out["conf_id"] = _as_int(bip.get("conf_id"))
    out["base_conf_id"] = _as_int(bip.get("base_conf_id"))

    # 1) 服务器直接下发的名字(field 23, hex 明文) — 最贴近客户端实际显示
    name = _decode_cn_hex(bip.get("name"))
    # 2) conf_id → 项目 wiki 图鉴映射(含全部进化形态)
    conf_id = out["conf_id"]
    wiki_name = pet_name_by_id(conf_id) if conf_id else ""
    if not name and wiki_name:
        name = wiki_name
    # 3) RKPP 内置查表的 conf_name 只作兜底(表混有测试模板, 且偏基础形态)
    if not name:
        name = str(bip.get("conf_name") or "").strip()
    out["name"] = name
    if isinstance(common, dict):
        lv = _as_int(common.get("level"))
        if lv:
            out["level"] = lv
        if not name:
            out["name"] = str(common.get("conf_name") or "").strip()
    pos = _as_int(bip.get("pos"))
    if pos is not None and 0 < pos < 100:
        out["pos"] = pos
    ba = bip.get("battle_attr")
    if isinstance(ba, list):
        if len(ba) > 1:
            out["hp_max"] = _as_int(ba[1]) or 0
        if len(ba) > 25:
            out["hp"] = _as_int(ba[25])
    # ★ battle_enter 的 battle_inside_pet_info.skill_round_data 是每只精灵
    #   完整技能表（含 4 个战斗技能 + 特性/占位），是技能栏的权威来源。
    srd = bip.get("skill_round_data")
    if isinstance(srd, list):
        out["skills"] = _pick_battle_skills(srd)
        out["skill_map"] = _skill_pairs_map(srd)
        out["bar_entries"] = list(_iter_battle_skill_entries(srd))
    return out


def _iter_team_pets(team: dict):
    """遍历 init_info.player_team[i] / enemy_team[i] 里的 pets，产出 (bip, common)。"""
    if not isinstance(team, dict):
        return
    for p in team.get("pets") or []:
        if not isinstance(p, dict):
            continue
        bip = p.get("battle_inside_pet_info")
        common = p.get("battle_common_pet_info")
        if isinstance(bip, dict):
            yield bip, (common if isinstance(common, dict) else None)


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
    """取事件的业务 content（实测：RKPP relay 推送的 content 就是加工后结构，
    没有 detail 包裹层）。为兼容旧版若真出现 detail 字段也一并支持。"""
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
        self._skill_bar: list[str] = []            # 我方上场宠 4 技能栏
        self._pet_skills: dict = {}                # pet_id → pet_skill.skills（全队）
        self._on_field_pid: Optional[int] = None   # 我方当前上场宠 pet_id
        self._skill_map: dict = {}                 # 本局累计 {7位skill_id: 技能名}
        self._enemy_casts: list = []               # 敌方施法记录 [{round, skill}]（本局）
        self._enemy_last_cast = ""                 # 敌方最近一次释放的技能名
        self._bar_entries: list = []               # 我方上场宠 (pos, skill_id) 条目(校准用)
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
        self._last_result = ""
        self._last_real_pvp = False
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
            self._skill_bar = []
            self._pet_skills = {}
            self._on_field_pid = None
            self._skill_map = {}
            self._enemy_casts = []
            self._enemy_last_cast = ""
            self._bar_entries = []
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
            self._last_result = ""
            self._last_real_pvp = False
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
        # stdout 同步打一份: 启动日志(startup.log)可追溯, 不止进 UI 日志队列
        try:
            print(f"[RKPP] {msg}", flush=True)
        except Exception:
            pass
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

    def _dump_raw(self, event: dict) -> None:
        """原始事件完美落盘: data/logs/rkpp_raw/<日期>.jsonl (NDJSON, 可离线重放)。

        用于验证 id→名 映射/wiki 权威性/pos 槽位填充率 —— 在线解析出错时
        原始数据仍在, 随时可重放修正。
        """
        try:
            day = time.strftime("%Y%m%d")
            d = _PROJECT_ROOT / "data" / "logs" / "rkpp_raw"
            d.mkdir(parents=True, exist_ok=True)
            with open(d / f"{day}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    def ingest_event(self, event: dict) -> None:
        """把一条 RKPP 事件翻译成内部状态（订阅线程调用）。"""
        kind = _kind_of_event(event)
        if not kind:
            return
        self._dump_raw(event)
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
        """0x1316 battle_enter：从 init_info.player_team / enemy_team 取双方阵容。

        开新局时先清掉上局残留（技能栏/pet_skill/血量），避免串场。
        注意：清理必须在事件侧做，而不是 analyze()，否则会误删本局
        battle_enter 之后已到达的 round_start 数据。
        """
        self._declared_skills.clear()
        self._skill_bar = []
        self._pet_skills = {}
        self._on_field_pid = None
        self._skill_map = {}
        self._enemy_casts = []
        self._enemy_last_cast = ""
        self._bar_entries = []
        self._round_no = 0
        self._player_hp_val = 0
        self._player_hp_max = 0
        self._enemy_hp_val = 0
        self._enemy_hp_max = 0
        self._enemy_hp_pct = 0.0
        self._last_result = ""
        self._last_real_pvp = False
        rnd = _as_int(detail.get("round"))
        if rnd and rnd > self._round_no:
            self._round_no = rnd
        init = detail.get("init_info")
        if not isinstance(init, dict):
            return
        player_lineup, player_cur = self._collect_team(init.get("player_team"), "player")
        enemy_lineup, enemy_cur = self._collect_team(init.get("enemy_team"), "enemy")
        if player_lineup:
            self._player_lineup = player_lineup
        if enemy_lineup:
            self._enemy_lineup = enemy_lineup
        if self._player_lineup and self._enemy_lineup:
            self._lineup_done = True
        self._apply_on_field(player_cur, enemy_cur)
        # 证据日志: 名字解析链的原始输入与结果(修"低级形态"问题的可追溯性)
        for side, lineup in (("我方", player_lineup), ("敌方", enemy_lineup)):
            if lineup:
                self._log(f"[阵容] {side}: {lineup}")
        sample_pets = []
        for team in (init.get("player_team") or []) if isinstance(init.get("player_team"), list) else []:
            for bip, _c in _iter_team_pets(team):
                if isinstance(bip, dict):
                    sample_pets.append(bip)
        for bip in sample_pets[:2]:
            self._log(
                f"[名字证据] pet_id={bip.get('pet_id')} conf_id={bip.get('conf_id')} "
                f"base_conf_id={bip.get('base_conf_id')} "
                f"服务器name={_decode_cn_hex(bip.get('name'))!r} "
                f"conf_name={bip.get('conf_name')!r} "
                f"wiki(conf_id)={pet_name_by_id(bip.get('conf_id'))!r}")
        # 槽位证据: 验证 skill_round_data 的 pos 填充率与链式顺序
        # (OCR 槽位校准依赖它; 缺失则退化多局收敛方案)
        if self._bar_entries:
            self._log("[技能槽位] " + str([
                (e.get("pos"), e.get("skill_id"), e.get("original_skill_id"), e.get("name"))
                for e in self._bar_entries]))

    def _collect_team(self, teams: Any, side: str):
        """收集一方的全部精灵与「当前上场」那只。"""
        lineup: list[str] = []
        cur: Optional[dict] = None
        if not isinstance(teams, list):
            return lineup, cur
        for team in teams:
            for bip, common in _iter_team_pets(team):
                info = _parse_pet_info(bip, common=common)
                nm = info["name"]
                if nm and nm not in lineup:
                    lineup.append(nm)
                # 累计 id→名 对照表(仅我方；敌方 skill_round_data 可能不完整)
                if side == "player" and info.get("skill_map"):
                    self._skill_map.update(info["skill_map"])
                if cur is None and self._is_on_field(bip):
                    cur = info
        if cur is None and lineup:
            # 没显式上场态：首个带血量的当上场宠
            for team in teams:
                for bip, common in _iter_team_pets(team):
                    info = _parse_pet_info(bip, common=common)
                    if info["hp"] is not None:
                        cur = info
                        break
                if cur:
                    break
        return lineup, cur

    @staticmethod
    def _is_on_field(bip: dict) -> bool:
        """battle_inside_pet_info 里 pos/pet_change_status 暗示上场。"""
        if not isinstance(bip, dict):
            return False
        pcs = bip.get("pet_change_status")
        if isinstance(pcs, int) and pcs not in (0,):
            return True
        pos = bip.get("pos")
        if isinstance(pos, int) and 0 < pos < 100:
            return True
        return False

    def _apply_round_start(self, detail: dict) -> None:
        """0x131A round_start：perform_info[].data_update 携带双方上场宠与技能。"""
        si = detail.get("state_info")
        if isinstance(si, dict):
            rnd = _as_int(si.get("round"))
            if rnd and rnd > self._round_no:
                self._round_no = rnd
        pc = detail.get("perform_cmd")
        if not isinstance(pc, dict):
            return
        for item in pc.get("perform_info") or []:
            if not isinstance(item, dict):
                continue
            du = item.get("data_update")
            if not isinstance(du, dict):
                continue
            # 我方上场宠
            pet = du.get("pet")
            if isinstance(pet, dict):
                bip = pet.get("battle_inside_pet_info")
                if isinstance(bip, dict) and _as_int(bip.get("pet_id")) is not None:
                    self._apply_on_field(
                        _parse_pet_info(bip, common=pet.get("battle_common_pet_info")), None)
                    # round_start 也带完整技能表 → 累计进对照表(无 battle_enter 时的兜底)
                    self._absorb_skill_map(bip.get("skill_round_data"))
            # 敌方上场宠
            other = du.get("other")
            if isinstance(other, dict):
                for bip, common in _iter_team_pets(other):
                    self._apply_on_field(None, _parse_pet_info(bip, common=common))
            # 我方上场宠的技能栏：round_start 给的是「全队」pet_skill 列表
            # (pet_id=1..6)，需用场上宠的 pet_id 匹配，取其 4 个战斗技能。
            ps = du.get("pet_skill")
            if isinstance(ps, dict):
                pid = _as_int(ps.get("pet_id"))
                if pid is not None and 1 <= pid <= 6:
                    self._pet_skills[pid] = ps.get("skills")
                # pet_skill.skills 同样带 id+name → 累计进对照表
                self._absorb_skill_map(ps.get("skills"))

    def _apply_skill_declare(self, detail: dict) -> None:
        """0x1322 cmd_sync：req.cast_skill 是本回合我方宣告技能。"""
        req = detail.get("req")
        cast = req.get("cast_skill") if isinstance(req, dict) else None
        if isinstance(cast, dict):
            self._add_skill_name(
                _skill_display_name(cast) or cast.get("skill_id"), cast.get("skill_id"))

    def _apply_action_resolve(self, detail: dict) -> None:
        """0x1324 perform：perform_info 里 type=1 技能、type=4 伤害/扣血。

        我方(caster_id∈1..6)施法 → 累计技能对照表；
        敌方施法 → 记入 _enemy_casts/_enemy_last_cast（回合日志的
        enemy_skill_cast 事件与悬浮窗"敌方上招"都吃这个, 此前直接丢弃）。
        """
        pc = detail.get("perform_cmd")
        if not isinstance(pc, dict):
            return
        for item in pc.get("perform_info") or []:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t == 1:
                sc = item.get("skill_cast")
                if not isinstance(sc, dict):
                    continue
                side = _side_of_pet_id(sc.get("caster_id"))
                if side == "player":
                    self._add_skill_name(
                        _skill_display_name(sc) or sc.get("skill_id"), sc.get("skill_id"))
                elif side == "enemy":
                    name = _enemy_cast_name(sc) or str(sc.get("skill_id") or "").strip()
                    if name:
                        self._enemy_last_cast = name
                        self._enemy_casts.append(
                            {"round": self._round_no, "skill": name})
            elif t == 4:
                di = item.get("damage_info") or {}
                sync = item.get("sync_data") or {}
                self._apply_damage(di, sync)

    def _apply_damage(self, damage_info: dict, sync_data: dict) -> None:
        """sync_data.pet_sync_info[].hp_result 是该 pet 的最新血量。"""
        if not isinstance(sync_data, dict):
            return
        for info in sync_data.get("pet_sync_info") or []:
            if not isinstance(info, dict):
                continue
            side = _side_of_pet_id(info.get("pet_id"))
            hp = _as_int(info.get("hp_result"))
            if hp is None:
                continue
            if side == "enemy":
                self._enemy_hp_val = hp
                if self._enemy_hp_max > 0:
                    self._enemy_hp_pct = max(0.0, min(1.0, hp / self._enemy_hp_max))
            elif side == "player":
                self._player_hp_val = hp

    def _apply_finish(self, detail: dict) -> None:
        """0x132C battle_finish：settle_info 里取回合数/胜负。"""
        si = detail.get("settle_info")
        if not isinstance(si, dict):
            return
        rounds = _as_int(si.get("rounds"))
        if rounds and rounds > self._round_no:
            self._round_no = rounds
        code = _as_int(si.get("result"))
        self._last_result = _RESULT_MAP.get(code, "") if code is not None else ""
        # real_pvp=0 说明这局不是真人 PVP（可能是 PVE/逃跑）
        self._last_real_pvp = bool(_as_int(si.get("real_pvp")))
        # settle_info 里带「本局用过的所有技能」(含 id+name) → 累计进对照表，
        # 这是无 battle_enter/round_start 时的最后兜底来源。
        self._absorb_skill_map(si.get("skill_records"))
        for mon in si.get("monster_info") or []:
            if isinstance(mon, dict):
                self._absorb_skill_map(mon.get("skill_records"))
        # 每局结束：把本局累计的 id→名 对照表合并落盘（越跑越全）
        self._export_skill_map()

    def _export_skill_map(self) -> None:
        """把 self._skill_map 合并进 data/pvp/skill_id_name_map.json。

        结构：{"<7位skill_id>": "<技能名>", ...}。已存在则合并更新（新值覆盖旧值，
        便于后续修正），不会删除已有条目。失败静默（不影响主流程）。
        """
        if not self._skill_map:
            return
        try:
            merged: dict = {}
            if _SKILL_MAP_FILE.exists():
                try:
                    old = json.loads(_SKILL_MAP_FILE.read_text(encoding="utf-8"))
                    if isinstance(old, dict):
                        merged = {str(k): str(v) for k, v in old.items()}
                except Exception:
                    merged = {}
            before = len(merged)
            merged.update({str(k): str(v) for k, v in self._skill_map.items()})
            # 可信名覆盖: 启发式配对与 wiki 权威表大面积错位(41/41), 导出的
            # 对照表按 校准表(OCR实测) → wiki图鉴 顺序覆盖, 都没有才保留启发式名
            from src.pvp.skill_calibration import name_for as _cal_name, all_ids as _cal_table_ids
            for sid in list(merged.keys()):
                trusted = _cal_name(sid) or resolve_skill_name(sid)
                if trusted and trusted != merged[sid]:
                    merged[sid] = trusted
            for sid in list(_cal_table_ids()):
                if sid not in merged:
                    nm = _cal_name(sid)
                    if nm:
                        merged[sid] = nm
            _SKILL_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
            _SKILL_MAP_FILE.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8")
            added = len(merged) - before
            if self._logger:
                self._logger(f"[RKPP] 技能对照表已导出: +{added} 条, 共 {len(merged)} 条"
                             f" (名字已按 校准/wiki 权威覆盖)")
        except Exception:
            pass

    def _absorb_skill_map(self, skills: Any) -> None:
        """把一组 skill 条目里的 {7位id: 技能名} 累计进本局对照表。

        多来源复用：battle_enter.skill_round_data、round_start.pet_skill.skills、
        battle_finish.settle_info.skill_records 都带该结构。只收战斗技能
        (id>=1000000) 且名字非占位。
        """
        pairs = _skill_pairs_map(skills)
        if pairs:
            self._skill_map.update(pairs)

    def _add_skill_name(self, name: Any, skill_id: Any = None) -> None:
        nm = str(name or "").strip()
        if not nm and skill_id is not None:
            nm = resolve_skill_name(skill_id)
        if not nm or nm in _SKILL_PLACEHOLDERS:
            return
        if nm not in self._declared_skills:
            self._declared_skills.append(nm)

    def _set_skill_bar(self, skills: Any) -> None:
        """填我方上场宠技能栏。

        skills 既可能是原始 skill 条目（dict，来自 skill_round_data /
        round_start 的 pet_skill.skills），也可能是已提取好的技能名列表
        （来自 _parse_pet_info 的 skills 字段）。两种都支持。
        """
        if not isinstance(skills, list) or not skills:
            return
        if all(isinstance(s, str) for s in skills):
            bar = [s for s in skills if s and s not in _SKILL_PLACEHOLDERS]
        else:
            bar = _pick_battle_skills(skills)
        if bar:
            self._skill_bar = bar[:4]

    def _apply_on_field(self, player_info: Optional[dict], enemy_info: Optional[dict]) -> None:
        """更新场上双方的名字/血量（None 表示本次不动那一侧）。

        battle_attr[1]=最大血、[25]=当前血，全事件同布局，直接采用。
        场上宠确定后，顺带把它的技能栏填上（按 pet_id 查 _pet_skills）。
        """
        if player_info:
            nm = player_info.get("name")
            if nm:
                self._player_name = nm
            hp = player_info.get("hp")
            mhp = player_info.get("hp_max") or 0
            if hp is not None:
                self._player_hp_val = hp
            if mhp > 0 and self._player_hp_max <= 0:
                self._player_hp_max = mhp
            # 若当前血大于已知上限，用该值刷新上限
            if self._player_hp_max > 0 and self._player_hp_val > self._player_hp_max:
                self._player_hp_max = self._player_hp_val
            # 上场宠确定 → 更新技能栏
            pid = player_info.get("pet_id")
            if player_info.get("pos") is not None and pid is not None:
                self._on_field_pid = pid
                # 我方上场宠的 (槽位, 技能ID) 条目 → OCR 槽位校准闭环的数据源
                self._bar_entries = list(player_info.get("bar_entries") or [])
                own = player_info.get("skills")
                if own:
                    self._set_skill_bar(own)
                else:
                    self._set_skill_bar(self._pet_skills.get(pid))
        if enemy_info:
            nm = enemy_info.get("name")
            if nm:
                self._enemy_name = nm
            hp = enemy_info.get("hp")
            mhp = enemy_info.get("hp_max") or 0
            if mhp > 0 and self._enemy_hp_max <= 0:
                self._enemy_hp_max = mhp
            if hp is not None:
                self._enemy_hp_val = hp
            if self._enemy_hp_max > 0 and self._enemy_hp_val > self._enemy_hp_max:
                self._enemy_hp_max = self._enemy_hp_val
            if self._enemy_hp_max > 0 and self._enemy_hp_val is not None:
                self._enemy_hp_pct = max(0.0, min(1.0, self._enemy_hp_val / self._enemy_hp_max))

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
            # ★ 我方技能栏一律不在此产出（恒为空），完全交给 OCR 侧填充。
            #   原因：抓包 skill_desc/skill_name 的名字判定不可靠（应对！类技能触发
            #   特殊机制后名字会变）；且旧的 skill_icons ID 表与当前版本对不上。
            #   抓包侧仅继续累计 self._skill_map 供编号校准（在 _collect_team 里做）。
            if result.battle_start:
                # 新一局开局：本帧快照先给空（状态已由 _apply_enter 清理）
                round_no = 0

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
                result.player_lineup = list(self._player_lineup)
                result.enemy_lineup = list(self._enemy_lineup)
                result.lineup_done = self._lineup_done
                result.skills = ["", "", "", ""]
                result.enemy_last_cast = self._enemy_last_cast
                # 我方上场宠 (pos, skill_id) 条目: bridge 层与 OCR 槽位名做校准
                result._rkpp_bar_entries = [dict(e) for e in self._bar_entries]  # type: ignore[attr-defined]
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
