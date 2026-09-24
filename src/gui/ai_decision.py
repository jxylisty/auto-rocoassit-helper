# -*- coding: utf-8 -*-
"""ai_decision — AI 对战决策引擎 (LLM → 结构化战术建议)

定位: 读取实时对局快照, 调用 LLM 生成结构化战术建议(推荐技能/换宠/聚能/愿力)。
只读辅助: 只读快照、只返回建议, 绝不代打(点击/按键由外部 act 端点负责)。

API 配置:
    url=http://127.0.0.1:7863/v1  key=WildWorkAPI  model=codebuddy/deepseek-v4.1-flash
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parents[2] / "data" / "config" / "ai_vision.json"

DEFAULTS = {
    "ai_decision_enabled": True,
    "ai_decision_base_url": "http://127.0.0.1:7863/v1",
    "ai_decision_api_key": "WildWorkAPI",
    "ai_decision_model": "codebuddy/deepseek-v4.1-flash",
    "ai_decision_interval_s": 8.0,
}

SYSTEM_PROMPT = (
    "你是洛克王国《世界》PVP 对战的战术分析师。你需要在每回合开始前, "
    "基于当前战局信息, 推荐最优动作并给出理由。\n\n"
    "对战规则:\n"
    "- 双方各6只精灵, 4心制(精灵死亡扣1心, 4心扣完输)\n"
    "- 每回合可选: 出招(4技能之一) / 聚能(+5能量, 本回合不攻击) / 换宠(任意存活精灵) / 愿力冲击(2能量, 80威力)\n"
    "- 技能消耗能量, 聚能回复5, 能量不足无法使用技能\n"
    "- 先手判定: 技能先制值 → 同先制比速度面板\n"
    "- 伤害公式: (atk/def)×level_const×power×威力系数×同系加成×克制倍率×等级修正×天气×连击×(1-防御减免)\n\n"
    "必须严格按以下 JSON 格式回复, 不要输出多余文字:\n"
    '{"recommendation": {"action": "skill|switch|energize|resonance", "target": "技能名或精灵名", '
    '"confidence": "high|medium|low", "reasoning": "2-3句理由", "risk": "风险提示"}, '
    '"alternatives": [{"action": "...", "target": "...", "reasoning": "..."}]}'
)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k in DEFAULTS:
                if k in data:
                    cfg[k] = data[k]
    except Exception:
        pass
    return cfg


def build_prompt(snapshot: dict) -> str:
    """从识别快照构造 LLM 用户消息"""
    p = snapshot.get("player") or {}
    e = snapshot.get("enemy") or {}
    hands = snapshot.get("hands") or {}
    calc = snapshot.get("calc_skills") or []
    threats = snapshot.get("enemy_threats") or []
    energy_plan = snapshot.get("energy_plan") or {}

    lines = ["当前战局信息:", ""]

    # 双方阵容
    player_lineup = snapshot.get("player_lineup") or []
    enemy_lineup = snapshot.get("enemy_lineup") or []
    if player_lineup:
        lines.append(f"我方完整阵容: {', '.join(n or '?' for n in player_lineup)}")
    if enemy_lineup:
        lines.append(f"敌方完整阵容: {', '.join(n or '?' for n in enemy_lineup)}")
    lines.append("")

    # 当前在场
    p_name = p.get("name", "?")
    p_hp = p.get("hp_val", "?")
    p_hp_max = p.get("hp_max", "?")
    p_energy = p.get("energy_val", "?")
    p_types = p.get("types", [])
    lines.append(f"我方在场: {p_name} (HP {p_hp}/{p_hp_max}, 能量{p_energy}, 属性: {','.join(p_types)})")

    e_name = e.get("name", "?")
    e_hp = f"{float(e.get('hp_pct') or 0):.0%}"
    e_types = e.get("types", [])
    lines.append(f"敌方在场: {e_name} (HP {e_hp}, 属性: {','.join(e_types)})")

    # 速度线
    sd = snapshot.get("speed_diff")
    if sd is not None:
        lines.append(f"速度差: {'先手' if sd > 0 else '后手'} {abs(sd)}")
    esr = snapshot.get("enemy_speed_range") or {}
    if esr:
        lines.append(f"敌方速度区间: {esr.get('range_str', '?')}")

    # 能量线
    if energy_plan:
        now_sk = energy_plan.get("this_turn_skills") or []
        after_sk = energy_plan.get("after_charge_skills") or []
        lines.append(f"能量线: 当前{energy_plan.get('energy_now', '?')}点, 可用技能: {'/'.join(now_sk) if now_sk else '无'}")
        lines.append(f"    聚能后{energy_plan.get('after_charge_energy', '?')}点, 可用技能: {'/'.join(after_sk) if after_sk else '无'}")
        if energy_plan.get("can_resonance_now"):
            lines.append("    当前即可释放愿力冲击(2能量)")

    # 回合/手牌
    turn_n = hands.get("turn_count", "?")
    enemy_dead = hands.get("enemy_dead") or []
    enemy_seen = hands.get("enemy_seen") or []
    unseen = hands.get("enemy_unseen_count", 0)
    hearts = hands.get("enemy_hearts_left_est", "?")
    lines.append(f"回合{ turn_n}, 已见敌方: {', '.join(enemy_seen) if enemy_seen else '无'}, 未出场约{unseen}只")
    lines.append(f"敌方阵亡: {', '.join(enemy_dead) if enemy_dead else '无'}, 剩余心数: {hearts}")
    lines.append("")

    # 我方技能伤害
    lines.append("我方技能推演:")
    if calc:
        for sk in calc:
            name = sk.get("name", "?")
            dmg = f"{sk.get('dmg_min', '?')}~{sk.get('dmg_max', '?')}" if sk.get("dmg_min") else "无伤"
            mult = sk.get("mult", 1)
            mult_tag = f" (克制×{mult})" if mult > 1 else (f" (抵抗×{mult})" if mult < 1 else "")
            kill_tag = " [斩杀!]" if sk.get("is_kill") else ""
            lines.append(f"  {name}: {dmg}{mult_tag}{kill_tag}")
    lines.append("")

    # 敌方威胁
    if threats:
        lines.append("敌方威胁技能:")
        for t in threats[:4]:
            name = t.get("name", "?")
            dmg = f"{t.get('dmg_min', '?')}~{t.get('dmg_max', '?')}"
            lethal = " [致死!]" if t.get("is_lethal") else ""
            lines.append(f"  {name}: {dmg}{lethal}")

    lines.append("")
    lines.append("请给出最优动作建议(仅 JSON, 不要多余文字):")
    return "\n".join(lines)


def call_llm(cfg: dict, user_prompt: str, timeout: int = 15) -> dict | None:
    """调用 LLM 获取结构化建议"""
    url = (cfg.get("ai_decision_base_url") or "").rstrip("/") + "/chat/completions"
    body = {
        "model": cfg.get("ai_decision_model") or "codebuddy/deepseek-v4.1-flash",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 500,
        "temperature": 0.4,
    }
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.get('ai_decision_api_key') or 'none'}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        text = str((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if not text:
            return None
        # 尝试提取 JSON
        # 有些 LLM 会在回包前后加 ```json ... ```
        if "```" in text:
            for block in text.split("```"):
                block = block.strip()
                if block.startswith("json"):
                    block = block[4:].strip()
                try:
                    return json.loads(block)
                except Exception:
                    pass
        try:
            return json.loads(text)
        except Exception:
            # 尝试从文本中截取 {...}
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end+1])
                except Exception:
                    pass
        return None
    except Exception as e:
        return {"error": str(e)}


def get_decision(snapshot: dict) -> dict:
    """入口: 从快照生成 AI 决策(带配置加载和错误兜底)"""
    cfg = load_config()
    if not cfg.get("ai_decision_enabled", False):
        return {"enabled": False}
    prompt = build_prompt(snapshot)
    result = call_llm(cfg, prompt)
    if result is None:
        return {"error": "AI 无返回"}
    if isinstance(result, dict) and "recommendation" in result:
        result["prompt_len"] = len(prompt)
        return result
    if isinstance(result, dict) and "error" in result:
        return result
    return {"error": f"非预期格式: {str(result)[:200]}"}