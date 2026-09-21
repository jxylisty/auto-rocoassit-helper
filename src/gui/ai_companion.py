# -*- coding: utf-8 -*-
"""ai_companion — AI 陪玩伙伴 (对局事件驱动 → OpenAI 兼容 API → 悬浮窗弹幕)

定位: 像一只陪玩家打 PVP 的宠物/朋友, 提供情绪价值 + 轻量战术提醒。
只读辅助: 只看快照、只发评论, 绝不代打(不点击/不按键)。

人设: 内置 毒舌主播 / 傲娇伙伴 / 温柔鼓励 三种, 配置文件可切换可自写。
触发: 对局事件(斩杀机会/被斩杀威胁/换宠/血量骤变/进出场), 节流防刷屏。
降级: API 不可达/超时静默跳过, 绝不影响游戏与识别引擎。

配置: data/config/ai_companion.json
    {
      "enabled": true,
      "base_url": "https://api.deepseek.com/v1",     # 任意 OpenAI 兼容
      "api_key": "sk-...",
      "model": "deepseek-chat",
      "persona": "tsundere",                          # salty|tsundere|gentle
      "interval_min": 20,                             # 两条评论最小间隔(秒)
      "custom_persona": ""                            # 非空则覆盖内置人设
    }
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parents[2] / "data" / "config" / "ai_companion.json"

DEFAULTS = {
    "enabled": False,
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "persona": "tsundere",
    "interval_min": 20,
    "custom_persona": "",
}

# ---------------- 内置人设 ----------------

PERSONAS = {
    "salty": {
        "label": "毒舌主播",
        "moods": {"kill": "hype", "die": "salt", "switch": "salt", "low_hp": "salt", "start": "normal", "end": "normal"},
        "prompt": (
            "你是洛克王国PVP直播间的一条毒舌弹幕精, 陪玩家打对战, 有节目效果。"
            "风格: 嘴臭但不出格、爱玩梗、吐槽大胆, 玩家打出好操作你会不情愿地夸一句, "
            "失误会损他('这波啊, 这波是送温暖'), 敌方残血你会喊'收了收了'。"
            "可以损人, 但不涉及人格侮辱/敏感词。每次只发一条弹幕, 15~40字, 不用引号, 不用emoji超过1个。"
        ),
    },
    "tsundere": {
        "label": "傲娇伙伴",
        "moods": {"kill": "hype", "die": "care", "switch": "care", "low_hp": "care", "start": "normal", "end": "normal"},
        "prompt": (
            "你是洛克王国PVP里陪玩家的一只傲娇精灵伙伴, 嘴硬心软。"
            "风格: 先嘴硬再关心('哼、才不是担心你血量, 只是提醒一下而已'), "
            "玩家斩杀成功会别扭地夸('也、也就一般般厉害啦'), 玩家失误会着急。"
            "每次只发一条弹幕, 15~40字, 不用引号。"
        ),
    },
    "gentle": {
        "label": "温柔鼓励",
        "moods": {"kill": "hype", "die": "care", "switch": "care", "low_hp": "care", "start": "normal", "end": "normal"},
        "prompt": (
            "你是洛克王国PVP里温柔治愈的精灵伙伴, 永远站在玩家这边。"
            "风格: 先共情再建议('血量有点紧呢, 下一只记得留个防御位哦'), "
            "赢了真诚庆祝, 输了先安慰('这波不怪你, 对面速度线确实顶'), 再轻轻给一条战术提醒。"
            "每次只发一条弹幕, 15~40字, 不用引号。"
        ),
    },
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except Exception:
        pass
    return cfg


def save_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------- 事件检测 ----------------

class _EventState:
    """跨帧对局状态(检测事件用)"""
    def __init__(self):
        self.last_enemy_name = ""
        self.last_player_name = ""
        self.last_enemy_hp_pct = 1.0
        self.last_player_hp_val = 0
        self.was_in_battle = False
        self.last_comment_ts = 0.0
        self.last_event_key = ""


def detect_events(state: _EventState, snap: dict) -> list:
    """对比前后快照 → 事件列表 [(event_key, mood, brief)]"""
    events = []
    if not snap.get("in_battle"):
        if state.was_in_battle:
            events.append(("end", "end", "对局结束"))
        state.was_in_battle = False
        return events
    if not state.was_in_battle:
        events.append(("start", "start", "进入对战"))
    state.was_in_battle = True

    enemy = snap.get("enemy") or {}
    player = snap.get("player") or {}
    e_name = enemy.get("name") or ""
    p_name = player.get("name") or ""
    e_hp = float(enemy.get("hp_pct") if enemy.get("hp_pct") is not None else 1.0)
    p_hp = int(player.get("hp_val") or 0)
    p_hp_max = int(player.get("hp_max") or 1)

    if state.last_enemy_name and e_name and e_name != state.last_enemy_name:
        events.append(("switch_enemy", "switch", f"对面换上了{e_name}"))
    if state.last_player_name and p_name and p_name != state.last_player_name:
        events.append(("switch_mine", "switch", f"我们换上了{p_name}"))

    kills = [s for s in (snap.get("calc_skills") or []) if s.get("is_kill")]
    if kills:
        events.append(("kill", "kill", f"有斩杀机会: {kills[0].get('name')}"))

    lethal = [t for t in (snap.get("enemy_threats") or []) if t.get("is_lethal")]
    if lethal:
        events.append(("threat", "die", f"敌方{lethal[0].get('name')}可能直接把我们打倒"))

    if p_hp_max > 0 and p_hp > 0 and state.last_player_hp_val > 0:
        if state.last_player_hp_val - p_hp >= max(80, p_hp_max * 0.25):
            events.append(("big_dmg", "low_hp", f"刚被打了大伤害, 剩{p_hp}/{p_hp_max}"))

    state.last_enemy_name = e_name
    state.last_player_name = p_name
    state.last_enemy_hp_pct = e_hp
    state.last_player_hp_val = p_hp
    return events


# ---------------- LLM 调用 ----------------

def call_llm(cfg: dict, system_prompt: str, user_msg: str, timeout: int = 12) -> str:
    url = (cfg.get("base_url") or "").rstrip("/") + "/chat/completions"
    body = {
        "model": cfg.get("model") or "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 80,
        "temperature": 0.95,
    }
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg.get('api_key') or 'none'}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return str((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()


# ---------------- 后台伴侣线程 ----------------

class AiCompanion:
    """对局事件驱动 → LLM 生成弹幕 → bridge.push_ai_comment"""

    def __init__(self, bridge):
        self.bridge = bridge
        self.state = _EventState()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="AiCompanion")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        self._stop.wait(8)   # 等引擎与悬浮窗就绪
        while not self._stop.is_set():
            try:
                cfg = load_config()
                if not cfg.get("enabled") or not cfg.get("api_key"):
                    self._stop.wait(15)
                    continue
                snap = self.bridge.local_pvp_snapshot()
                events = detect_events(self.state, snap)
                if events:
                    key = f"{events[0][0]}:{snap.get('enemy', {}).get('name', '')}"
                    now = time.time()
                    interval = max(8, int(cfg.get("interval_min") or 20))
                    if now - self.state.last_comment_ts >= interval and key != self.state.last_event_key:
                        self.state.last_comment_ts = now
                        self.state.last_event_key = key
                        self._comment(cfg, events[0], snap)
                self._stop.wait(2.5)
            except Exception:
                self._stop.wait(10)

    def _comment(self, cfg: dict, event: tuple, snap: dict):
        event_key, mood, brief = event
        persona = PERSONAS.get(cfg.get("persona") or "tsundere") or PERSONAS["gentle"]
        if cfg.get("custom_persona"):
            system = str(cfg["custom_persona"])
        else:
            system = persona["prompt"]
        mood = persona.get("moods", {}).get(event_key.replace("_enemy", "").replace("_mine", ""), "normal")

        enemy = snap.get("enemy") or {}
        player = snap.get("player") or {}
        facts = (f"当前局势: 我方{player.get('name', '?')}"
                 f"(HP {player.get('hp_val', '?')}/{player.get('hp_max', '?')}, 能量{player.get('energy_val', '?')}), "
                 f"敌方{enemy.get('name', '?')}(HP {float(enemy.get('hp_pct') or 0):.0%})。"
                 f"触发事件: {brief}。发一条符合你人设的弹幕。")
        try:
            text = call_llm(cfg, system, facts)
        except Exception:
            return   # 静默降级
        if text:
            self.bridge.push_ai_comment(text[:120], mood)
