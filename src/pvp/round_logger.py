# -*- coding: utf-8 -*-
"""round_logger — PVP 回合日志自动记录 (记忆系统的数据地基)

每 500ms 的识别快照在这里做 diff, 产出结构化回合事件:
    出场(我方/敌方换宠) / 血量增减(带出招方猜测) / 技能使用变化 / 对局开始结束

落盘: data/rounds/<日期>/<时间戳>_vs<敌方>.jsonl (一行一个事件, 追加写)
对局结束时自动汇总写一条战报到 history_db(result 由血量归零方判定)。

MCP: pvp_round_log 工具读取 jsonl 供 AI 复盘。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUNDS_DIR = PROJECT_ROOT / "data" / "rounds"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class RoundLogger:
    """对局级回合日志器 (bridge 持有, in_battle 状态切换时开新文件)"""

    def __init__(self):
        self.file: Path | None = None
        self.match_id: str | None = None
        self.started_at: float | None = None
        self.last_enemy_name = ""
        self.last_player_name = ""
        self.last_enemy_hp_pct: float | None = None
        self.last_player_hp_val: int | None = None
        self.last_skills: list = []
        self.player_hp_max_seen = 0
        self.enemy_names_seen: list = []   # 本局敌方出场序列
        self.player_names_seen: list = []
        self._closed = True
        # 手牌追踪: 敌方已出场精灵 → {hp_seen_min(最低血量比例), turns(在场回合数)}
        self.enemy_roster: dict[str, dict] = {}
        self.player_energy_last: int | None = None
        self.turn_count = 0

    # ---------------- 生命周期 ----------------

    def start_match(self, player_name: str, enemy_name: str) -> Path:
        """进战斗: 开新 jsonl"""
        day = time.strftime("%Y%m%d")
        ts = time.strftime("%H%M%S")
        safe_enemy = "".join(ch for ch in (enemy_name or "未知") if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")[:12] or "未知"
        d = ROUNDS_DIR / day
        d.mkdir(parents=True, exist_ok=True)
        self.file = d / f"{ts}_vs{safe_enemy}.jsonl"
        self.match_id = self.file.stem
        self.started_at = time.time()
        self.last_enemy_name = enemy_name
        self.last_player_name = player_name
        self.last_enemy_hp_pct = None
        self.last_player_hp_val = None
        self.last_skills = []
        self.player_hp_max_seen = 0
        self.enemy_names_seen = [enemy_name] if enemy_name else []
        self.player_names_seen = [player_name] if player_name else []
        self.enemy_roster = {}
        self.player_energy_last = None
        self.turn_count = 0
        self._closed = False
        self._write({"t": _now(), "event": "match_start",
                     "player": player_name, "enemy": enemy_name})
        return self.file

    def close_match(self, final_snapshot: dict | None = None) -> dict | None:
        """脱战斗: 收尾并写战报到 history_db。返回写入的战报概要。"""
        if self._closed or not self.file:
            return None
        self._closed = True
        duration = int(time.time() - (self.started_at or time.time()))
        self._write({"t": _now(), "event": "match_end", "duration_sec": duration})

        # ---- 自动战报: 血量归零方判负(最后一帧快照为准) ----
        result = None
        player_team = [{"name": n, "types": [], "hp_pct": 1.0} for n in self.player_names_seen]
        enemy_team = [{"name": n, "types": [], "hp_pct": 1.0} for n in self.enemy_names_seen]
        try:
            from src.pvp.history_db import get_history_db
            db = get_history_db()
            if final_snapshot:
                p_hp = int((final_snapshot.get("player") or {}).get("hp_val") or 0)
                e_hp_pct = float((final_snapshot.get("enemy") or {}).get("hp_pct") or 0)
                # 我方血量 OCR 精确; 敌方血条比例 — 敌方归零→WIN, 我方归零→LOSS
                if e_hp_pct <= 0.02 and p_hp > 0:
                    result = "WIN"
                elif p_hp <= 0:
                    result = "LOSS"
                else:
                    result = None  # 中途逃跑/断线, 不写结果(可人工补录)
            if result:
                db.record_match(
                    result=result,
                    my_team=player_team,
                    enemy_team=enemy_team,
                    duration_sec=duration,
                    rank_tier="",
                    notes=f"自动记录({self.match_id})",
                )
        except Exception:
            result = None
        out = {"match_id": self.match_id, "file": str(self.file),
               "duration_sec": duration, "recorded": result}
        self.file = None
        self.match_id = None
        return out

    # ---------------- 每帧更新 ----------------

    def update(self, snap: dict) -> list[dict]:
        """消费 500ms 快照 → diff 出事件列表(同时写 jsonl)。
        snap 结构 = pipeline.to_dict + enrich 字段。"""
        if self._closed or not self.file:
            return []
        events: list[dict] = []
        now = _now()
        player = snap.get("player") or {}
        enemy = snap.get("enemy") or {}
        p_name = player.get("name") or ""
        e_name = enemy.get("name") or ""
        e_hp = enemy.get("hp_pct")
        p_hp = player.get("hp_val")
        p_hp_max = player.get("hp_max") or 0
        skills = [s for s in ((player or {}).get("skills") or []) if s]

        # --- 换宠检测 ---
        if p_name and p_name != self.last_player_name:
            if self.last_player_name:
                events.append({"t": now, "event": "switch_mine",
                               "from": self.last_player_name, "to": p_name})
            if p_name not in self.player_names_seen:
                self.player_names_seen.append(p_name)
            self.last_player_name = p_name
            self.last_skills = []   # 换宠后技能栏重置
        if e_name and e_name != self.last_enemy_name:
            if self.last_enemy_name:
                events.append({"t": now, "event": "switch_enemy",
                               "from": self.last_enemy_name, "to": e_name})
            if e_name not in self.enemy_names_seen:
                self.enemy_names_seen.append(e_name)
            self.enemy_roster.setdefault(e_name, {
                "hp_seen_max": 0.0, "hp_seen_min": 1.0, "turns": 0, "seen_down": False})
            self.last_enemy_name = e_name
            self.last_enemy_hp_pct = None   # 新宠血量基线重置

        # --- 血量增减 ---
        if isinstance(e_hp, (int, float)) and e_hp > 0:
            roster = self.enemy_roster.setdefault(e_name, {
                "hp_seen_max": 0.0, "hp_seen_min": 1.0, "turns": 0, "seen_down": False})
            roster["hp_seen_max"] = max(roster["hp_seen_max"], float(e_hp))
            roster["hp_seen_min"] = min(roster["hp_seen_min"], float(e_hp))
            roster["turns"] += 1
            if self.last_enemy_hp_pct is not None:
                delta = e_hp - self.last_enemy_hp_pct
                if abs(delta) >= 0.01:   # 1% 以上才记
                    events.append({"t": now, "event": "enemy_hp_change",
                                   "from": round(self.last_enemy_hp_pct, 3),
                                   "to": round(e_hp, 3),
                                   "delta_pct": round(delta, 3),
                                   # 血量下降=我方造成(出招方猜测: 最近技能栏有变化或换宠后首伤)
                                   "caused_by": "player"})
            self.last_enemy_hp_pct = e_hp
        if isinstance(p_hp, int) and p_hp > 0:
            if p_hp_max > self.player_hp_max_seen:
                self.player_hp_max_seen = p_hp_max
            if self.last_player_hp_val is not None:
                delta = p_hp - self.last_player_hp_val
                if abs(delta) >= 10:
                    events.append({"t": now, "event": "player_hp_change",
                                   "from": self.last_player_hp_val,
                                   "to": p_hp, "delta": delta,
                                   "caused_by": "enemy"})
            self.last_player_hp_val = p_hp

        # --- 技能栏变化(我方可用技能集) — 变化一次≈过了一回合, 递增回合数 ---
        if skills and skills != self.last_skills:
            self.turn_count += 1
            events.append({"t": now, "event": "skills_seen",
                           "turn": self.turn_count,
                           "skills": skills})
            self.last_skills = skills

        # 敌方被打倒检测: 血量曾见底(<3%) → 该精灵已阵亡(粗判, 换宠前最后一次)
        for name, info in self.enemy_roster.items():
            if info["hp_seen_min"] <= 0.03:
                info["seen_down"] = True

        # 事件写盘
        for e in events:
            self._write(e)
        return events

    def hands_summary(self, current_enemy: str = "") -> dict:
        """手牌/心数/能量摘要 (snapshot 透出给 AI):
        enemy_roster: 敌方已出场精灵及状态; enemy_dead/alive 计数; enemy_hearts_left 估算"""
        dead = [n for n, i in self.enemy_roster.items() if i.get("seen_down")]
        alive = [n for n in self.enemy_roster if n not in dead]
        # 未出场精灵 = 6 - 已见; 心数 = 4 - 阵亡数(忽略扣心特性)
        enemy_hearts_left = max(0, 4 - len(dead))
        roster_view = {n: {
            "status": ("dead" if n in dead else
                       (f"hp_min_seen={i['hp_seen_min']:.0%}" if n != current_enemy else "on_field")),
            "hp_seen_min": round(i["hp_seen_min"], 2),
            "turns_on_field": i["turns"],
        } for n, i in self.enemy_roster.items()}
        return {
            "enemy_seen": self.enemy_names_seen,
            "enemy_roster": roster_view,
            "enemy_dead": dead,
            "enemy_alive_seen": alive,
            "enemy_unseen_count": max(0, 6 - len(self.enemy_names_seen)),
            "enemy_hearts_left_est": enemy_hearts_left,
            "enemy_hearts_lost_est": 4 - enemy_hearts_left,
            "turn_count": self.turn_count,
        }

    def _write(self, obj: dict):
        try:
            with open(self.file, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ---------------- 查询(MCP 用) ----------------

    @staticmethod
    def read_match(path: Path) -> dict:
        """读一份 jsonl 为结构化对局"""
        events = []
        try:
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
        except Exception:
            pass
        return {"file": str(path), "events": events}

    @staticmethod
    def list_matches(days: int = 7) -> list[dict]:
        """列出近 N 天的对局文件(新→旧)"""
        out = []
        if not ROUNDS_DIR.exists():
            return out
        dirs = sorted(ROUNDS_DIR.glob("*"), reverse=True)[:days]
        for d in dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.jsonl"), reverse=True):
                out.append({"file": str(f), "name": f.stem,
                            "mtime": f.stat().st_mtime})
        return out
