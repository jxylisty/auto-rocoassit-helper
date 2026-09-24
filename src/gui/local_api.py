# -*- coding: utf-8 -*-
"""local_api — 本机 HTTP 桥 (AI 陪玩 MCP 工具的数据源)

仅监听 127.0.0.1, 与主程序同进程, 直接复用 bridge 的识别/计算/推送设施。
MCP server (tools/pvp_mcp_server.py) 通过 urllib 调用这些端点。

端点:
    GET  /health                存活探针
    GET  /snapshot              实时对局快照(识别+伤害推演全字段)
    GET  /rules                 PVP 规则知识包(常量/克制表/公式说明)
    POST /analyze  {atk,def}    指定双方精灵 seq 的完整推演(pvp_calc_all_skills)
    POST /act     {action}      AI 自玩操作注入: skill1~4 / energize / switch_1~6 / resonance
    GET  /search?q=&kind=       精灵/技能模糊搜索(kind=pet|skill|all)
    GET  /history?limit=        战报历史(只读)
    POST /comment  {text,mood}  AI 陪玩评论 → 推送悬浮窗弹幕条

安全: 绑定回环 + 可选 token(data/config/ai_companion.json 的 local_token,
缺失则不校验 —— 本机回环上无外部暴露面)。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOCAL_API_PORT = 17365


class LocalApiServer(threading.Thread):
    """bridge 注入式 HTTP 桥线程 (daemon, 随主程序退出)"""

    def __init__(self, bridge, port: int = LOCAL_API_PORT):
        super().__init__(daemon=True, name="LocalApi")
        self.bridge = bridge
        self.port = port
        self._httpd = None
        self._token = ""

    # ---------------- handler 工厂 ----------------

    def _make_handler(self):
        bridge = self.bridge
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # 静默(不走 bridge 日志避免刷屏)
                pass

            def _check_token(self):
                if not server._token:
                    return True
                return self.headers.get("X-LKW-Token") == server._token

            def _send(self, code: int, obj: dict):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > 1 << 20:
                    return {}
                try:
                    return json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception:
                    return {}

            def do_GET(self):
                if not self._check_token():
                    return self._send(401, {"error": "token 校验失败"})
                path, _, query = self.path.partition("?")
                from urllib.parse import parse_qs
                params = {k: v[0] for k, v in parse_qs(query).items()}
                try:
                    if path == "/health":
                        return self._send(200, {"ok": True, "pvp_running": bridge._pvp_running})
                    if path == "/snapshot":
                        return self._send(200, bridge.local_pvp_snapshot())
                    if path == "/rules":
                        return self._send(200, build_rules_pack())
                    if path == "/search":
                        return self._send(200, handle_search(bridge, params))
                    if path == "/history":
                        return self._send(200, handle_history(bridge, params))
                    if path == "/rounds":
                        return self._send(200, handle_rounds(params))
                    if path == "/round":
                        return self._send(200, handle_round_detail(params))
                    return self._send(404, {"error": f"未知端点 {path}"})
                except Exception as e:
                    return self._send(500, {"error": str(e)})

            def do_POST(self):
                if not self._check_token():
                    return self._send(401, {"error": "token 校验失败"})
                path = self.path.split("?")[0]
                body = self._read_body()
                try:
                    if path == "/analyze":
                        return self._send(200, handle_analyze(bridge, body))
                    if path == "/act":
                        return self._send(200, handle_act(bridge, body))
                    if path == "/comment":
                        return self._send(200, handle_comment(bridge, body))
                    if path == "/recommend":
                        return self._send(200, handle_recommend(bridge))
                    return self._send(404, {"error": f"未知端点 {path}"})
                except Exception as e:
                    return self._send(500, {"error": str(e)})

        return Handler

    # ---------------- 生命周期 ----------------

    def run(self):
        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), self._make_handler())
            self._httpd.serve_forever(poll_interval=0.5)
        except Exception:
            pass  # 端口被占(多开/冲突)时静默降级: MCP 不可用, 主程序不受影响

    def stop(self):
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass


# ---------------- 端点实现 ----------------

def build_rules_pack() -> dict:
    """PVP 规则知识包: 常量 + 克制表 + 公式说明(AI 建立 PVP 心智用)"""
    from src.pvp.pvp_rules import PVP_RULES, LEVEL, STAR, IV_RULE, NATURE, DAMAGE
    from src.pvp.type_chart import _CHART, get_attr_multiplier

    return {
        "level_fixed": LEVEL,
        "star_fixed": STAR,
        "iv_rule": IV_RULE,
        "nature_multipliers": NATURE,
        "damage_constants": DAMAGE,
        "scenario_defaults": PVP_RULES.get("DEFAULT_SCENARIO", {}),
        "type_chart": _CHART,
        "type_multiplier_rule": {
            "double_weak": 3.0, "single_weak": 2.0,
            "neutral": 1.0, "single_resist": 0.5, "double_resist": 0.25,
            "note": "计数口径: 对防御方每个属性分别统计 weak/resist, 非连乘",
        },
        "battle_structure": {
            "team_size": 6,
            "hearts": 4,
            "heart_rule": "己方精灵死亡扣 1 心(部分精灵特性影响扣心数), 4 心扣完即负",
            "actions_per_turn": [
                "出招: 从在场精灵的 4 个技能中选 1 个(消耗对应能量)",
                "聚能: 变化类操作, 本回合不攻击, 回复 5 点能量",
                "换宠: 任意存活精灵间自由替换",
            ],
            "energy_rule": "技能消耗能量; 聚能+5; 能量不足的技能不可选",
            "resonance_skill": {
                "name": "愿力冲击",
                "cost": 2,
                "power": 80,
                "attr": "与精灵血脉(属性)相关",
                "note": "第 6 技能(共鸣魔法), 4 技能槽之外的额外选择",
            },
            "win_condition": "扣完对方 4 心",
        },
        "damage_formula": (
            "damage = max(1, (atk/def) * level_const * power * powerBuff "
            "* sameTypeBonus * attrMultiplier * levelMod * weatherMod "
            "* hits * (1-defenseReduction)); "
            "level_const=(level*45/100+10)/41; 60级≈0.9024; "
            "sameTypeBonus=1.25 当技能属性∈攻方属性; "
            "atk/def 按技能类型选 物攻→attack/defense, 魔攻→mattack/mdefense; "
            "实测浮动约为计算值×1.15"
        ),
        "speed_priority_rule": (
            "先手判定: 技能先制值(priority, 如先手+1)优先 → 同先制比速度面板 → "
            "全同视为同时出手(tie)。速度面板可用 calculate_world_speed_range 的种族速度区间估算"
        ),
        "panel_formula_note": (
            "面板 = 种族×0.5 + 实际IV×0.25 + 10 + 等级成长 + 星级加成(hp 20/星, 其他 10/星); "
            "实际IV = 输入IV×(star+1); PVP 固定 60 级 5 星 → 实际IV = 输入×6"
        ),
        "attr_multiplier_example": {
            "火攻击草防御": get_attr_multiplier("火", ["草"]),
            "火攻击水防御": get_attr_multiplier("火", ["水"]),
        },
    }


def handle_search(bridge, params: dict) -> dict:
    """精灵/技能模糊搜索: kind=pet|skill|all"""
    from src.pvp.pet_loader import search_pets
    from src.pvp.skill_loader import search_skills
    q = (params.get("q") or "").strip()
    kind = (params.get("kind") or "all").lower()
    limit = min(int(params.get("limit") or 10), 30)
    if not q:
        return {"pets": [], "skills": []}
    out = {"pets": [], "skills": []}
    if kind in ("pet", "all"):
        out["pets"] = search_pets(q, limit=limit, pvp_filter=True)
    if kind in ("skill", "all"):
        out["skills"] = search_skills(q, limit=limit)
    return out


def handle_history(bridge, params: dict) -> dict:
    """战报历史(只读)。空库时明确告知 AI 无数据(绝不用演示数据冒充)。"""
    limit = min(int(params.get("limit") or 10), 50)
    res = bridge.pvp_get_history(limit=limit)
    matches = res.get("matches", [])
    return {
        "matches": matches,
        "count": len(matches),
        "note": ("当前没有真实对局记录 — 战报由用户在对局结束后手动录入。"
                 "不要假设对手风格或胜率, 如需历史分析请告知用户先打几场积累数据。"
                 ) if not matches else "",
    }


def handle_analyze(bridge, body: dict) -> dict:
    """指定双方精灵 seq 的完整推演 (pvp_calc_all_skills)"""
    atk = body.get("atk") or body.get("attacker_seq")
    dfn = body.get("def") or body.get("defender_seq")
    if not atk or not dfn:
        return {"error": "需要 atk/def 两个精灵 seq"}
    res = bridge.pvp_calc_all_skills(
        int(atk), int(dfn),
        atk_high_ivs=body.get("atk_high_ivs"),
        atk_iv_value=int(body.get("atk_iv_value") or 10),
        def_high_ivs=body.get("def_high_ivs"),
        def_iv_value=int(body.get("def_iv_value") or 10),
        atk_nature_up=body.get("atk_nature_up"),
        atk_nature_down=body.get("atk_nature_down"),
        def_nature_up=body.get("def_nature_up"),
        def_nature_down=body.get("def_nature_down"),
    )
    return {"matchup": res}


def handle_rounds(params: dict) -> dict:
    """列出近期回合日志文件(新→旧)"""
    from src.pvp.round_logger import RoundLogger
    days = min(int(params.get("days") or 7), 30)
    return {"matches": RoundLogger.list_matches(days=days)}


def handle_round_detail(params: dict) -> dict:
    """读一份回合日志全文(事件流) — AI 复盘对局用"""
    from src.pvp.round_logger import RoundLogger
    f = params.get("file") or ""
    if not f or ".." in f:
        return {"error": "需要 file 参数(由 /rounds 返回的路径)"}
    return RoundLogger.read_match(Path(f))


def handle_act(bridge, body: dict) -> dict:
    """AI 自玩操作注入: 按一条操作命令

    支持的 action:
      skill1/2/3/4   → 按数字键出招
      energize        → 按 X 聚能
      switch_1~6      → E → 数字 → Space 换宠
      resonance       → Q → 1 → 1 愿力冲击
    delay: 动作间隔(秒, 默认 0.3)
    """
    action = str(body.get("action") or "").strip()
    delay = body.get("delay")
    if not action:
        return {"ok": False, "error": "需要 action 参数"}
    return bridge.pvp_act(action, delay=delay)


def handle_comment(bridge, body: dict) -> dict:
    """AI 陪玩评论 → 推送悬浮窗弹幕条"""
    text = str(body.get("text") or "").strip()
    mood = str(body.get("mood") or "normal")
    if not text:
        return {"ok": False, "message": "text 为空"}
    ok = bridge.push_ai_comment(text, mood)
    return {"ok": bool(ok)}


def handle_recommend(bridge) -> dict:
    """AI 战术建议: 读取实时快照 → LLM 决策 → 缓存到 bridge"""
    snap = bridge.local_pvp_snapshot()
    if not snap.get("in_battle"):
        return {"in_battle": False, "message": "未在对战中"}
    from src.gui.ai_decision import get_decision
    decision = get_decision(snap)
    # 缓存建议到 bridge
    try:
        from threading import Lock
        lock = getattr(bridge, "_ai_decision_lock", None)
        if lock:
            with lock:
                bridge._ai_recommendation = decision
    except Exception:
        pass
    return decision
