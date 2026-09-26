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
    "你是洛克王国《世界》顶级 PVP 对战的专业战术军师。你需要在每回合开始前，"
    "基于当前战局的双方在场精灵、特性(被动)、属性克制关系、4个技能的详细官方效果描述、"
    "能量点数以及敌方上回合真实出招，给出精确、严密的最优动作推荐及战术理由。\n\n"
    "对战核心机制准则:\n"
    "1. 严格区分我方(Player)与敌方(Enemy)，绝不混淆敌我精灵与技能！\n"
    "2. 很多技能虽然基础直接伤害为0，但具有极其强力的状态效果（如「引燃」可造成10层灼烧，「抽枝」应对回复50%血量和5能），"
    "   务必深入分析技能官方效果描述与精灵被动特性（如燃薪虫的煤渣草特性使灼烧只增不减），切忌将机制状态技能当成无用技能！\n"
    "3. 状态栏与异常层数（核心战情）：密切关注双方状态栏！"
    "   若我方有属性强化（如物攻+100%），伤害已大幅提升，应优先打出毁灭爆发；"
    "   若敌方被挂高层异常（如10层灼烧、冻结），考虑配合机制技能引爆或消耗；若我方被挂危险异常，考虑换宠或解控。\n"
    "4. 伤害与克制：注意属性克制倍率（2.0x克制/0.5x抵抗/0.25x双抵抗），有斩杀机会优先斩杀；血量危险注意防守或换宠。\n"
    "5. 能量管理：注意技能消耗，能量不足无法出招，必要时选择聚能(+5能量)或愿力冲击。\n\n"
    "必须严格按以下 JSON 格式回复，不要输出任何多余问候或 markdown 代码块外的杂音:\n"
    '{"recommendation": {"action": "skill|switch|energize|resonance", "target": "推荐的具体技能名或精灵名", '
    '"confidence": "high|medium|low", "reasoning": "2-3句极精辟的战术解析(说明技能机制/特性联动/属性克制/状态栏)", "risk": "针对敌方出招或反制的风险提示"}, '
    '"alternatives": [{"action": "skill|switch|energize", "target": "备选技能或精灵", "reasoning": "备选理由"}]}'
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
    """从快照中提取完整战局信息，拼接技能官方效果描述、特性、克制矩阵与敌方上招"""
    try:
        from src.pvp.pet_loader import get_pet_by_name
        from src.pvp.skill_loader import get_skill
        from src.pvp.type_chart import get_attr_multiplier
    except Exception:
        get_pet_by_name = lambda n: {}
        get_skill = lambda n: {}
        get_attr_multiplier = lambda a, d: 1.0

    p = snapshot.get("player") or {}
    e = snapshot.get("enemy") or {}
    hands = snapshot.get("hands") or {}
    calc = snapshot.get("calc_skills") or snapshot.get("damage_calc") or []
    if not calc and p.get("skills"):
        calc = [{"name": s} for s in p.get("skills") if s]
    threats = snapshot.get("enemy_threats") or []
    energy_plan = snapshot.get("energy_plan") or {}
    enemy_last_cast = snapshot.get("enemy_last_cast") or ""

    p_name = p.get("name", "?")
    p_species = p.get("species") or p_name
    p_pet = get_pet_by_name(p_species) or get_pet_by_name(p_name) or {}
    p_trait = p_pet.get("trait", "暂无特殊特性记录")
    p_types = p.get("types") or p_pet.get("types") or []

    e_name = e.get("name", "?")
    e_species = e.get("species") or e_name
    e_pet = get_pet_by_name(e_species) or get_pet_by_name(e_name) or {}
    e_trait = e_pet.get("trait", "暂无特殊特性记录")
    e_types = e.get("types") or e_pet.get("types") or []

    lines = ["【当前对局实时战况】", ""]

    # 1. 我方在场
    p_hp = p.get("hp_val", "?")
    p_hp_max = p.get("hp_max", "?")
    p_energy = p.get("energy_val", "?")
    p_buffs = p.get("buffs") or snapshot.get("player_buffs") or []
    p_buff_texts = [b.get("text") or b.get("name") for b in p_buffs if isinstance(b, dict)]
    lines.append(f"▶ 我方在场精灵: {p_name}" + (f" (物种: {p_species})" if p_species != p_name else ""))
    lines.append(f"  • 属性: {', '.join(p_types) if p_types else '未知'}")
    lines.append(f"  • 血量: {p_hp}/{p_hp_max} | 当前能量: {p_energy}")
    lines.append(f"  • 特性(被动): {p_trait}")
    lines.append(f"  • 实时状态/强化栏: {', '.join(p_buff_texts) if p_buff_texts else '正常 (无异常/强化)'}")
    lines.append("")

    # 2. 敌方在场
    e_hp = f"{float(e.get('hp_pct') or 0):.0%}"
    e_buffs = e.get("buffs") or snapshot.get("enemy_buffs") or []
    e_buff_texts = [b.get("text") or b.get("name") for b in e_buffs if isinstance(b, dict)]
    lines.append(f"▶ 敌方在场精灵: {e_name}" + (f" (物种: {e_species})" if e_species != e_name else ""))
    lines.append(f"  • 属性: {', '.join(e_types) if e_types else '未知'}")
    lines.append(f"  • 当前血量百分比: {e_hp}")
    lines.append(f"  • 特性(被动): {e_trait}")
    lines.append(f"  • 实时状态/异常栏: {', '.join(e_buff_texts) if e_buff_texts else '正常 (无异常/强化)'}")
    if enemy_last_cast:
        sk_info = get_skill(enemy_last_cast) or {}
        desc = sk_info.get("describe") or ""
        lines.append(f"  • 敌方上回合实际施放技能: 【{enemy_last_cast}】" + (f" (效果: {desc})" if desc else ""))
    lines.append("")

    # 3. 速度与局势
    sd = snapshot.get("speed_diff")
    speed_text = "先手 (+" + str(sd) + ")" if sd is not None and sd > 0 else ("后手 (" + str(sd) + ")" if sd is not None and sd < 0 else "同速")
    lines.append(f"▶ 先后手状态: 我方{speed_text}")
    esr = snapshot.get("enemy_speed_range") or {}
    if esr:
        lines.append(f"  敌方速度参考区间: {esr.get('range_str', '?')}")
    lines.append("")

    # 4. 我方技能库与详细推演
    lines.append("▶ 我方当前 4 个可选技能与效果详细信息:")
    if calc:
        for sk in calc:
            name = (sk.get("name") or "").strip()
            if not name:
                continue
            sk_meta = get_skill(name) or {}
            desc = sk_meta.get("describe") or "常规技能"
            cost = sk_meta.get("consume") or "0"
            sk_type = sk_meta.get("type") or sk.get("type", "普通")
            sk_attr = sk_meta.get("attr") or sk.get("attr", "普通")
            mult = sk.get("mult", 1.0)
            mult_str = f"克制×{mult:.1f}" if mult > 1.0 else (f"抵抗×{mult:.1f}" if mult < 1.0 else "等倍1.0")
            dmg = f"{sk.get('dmg_min', 0)}~{sk.get('dmg_max', 0)}" if sk.get("dmg_min") else "0/状态技能"
            kill_str = "【可直接斩杀!】" if sk.get("is_kill") else ""
            lines.append(f"  • 【{name}】 消耗:{cost}能 | 类型:{sk_type}/{sk_attr} | 伤害预测:{dmg} ({mult_str}) {kill_str}")
            lines.append(f"    官方技能效果: {desc}")
    else:
        lines.append("  (技能推演中...)")
    lines.append("")

    # 5. 敌方潜在威胁预测
    if threats:
        lines.append("▶ 敌方潜在高威胁技能预测:")
        for t in threats[:3]:
            t_name = t.get("name", "")
            t_meta = get_skill(t_name) or {}
            t_desc = t_meta.get("describe") or ""
            t_dmg = f"{t.get('dmg_min', 0)}~{t.get('dmg_max', 0)}"
            lethal = "【可能直接致死我方!】" if t.get("is_lethal") else ""
            lines.append(f"  • {t_name}: 预测伤害 {t_dmg} {lethal}" + (f" ({t_desc})" if t_desc else ""))
        lines.append("")

    # 6. 双方阵容与手牌
    p_lineup = snapshot.get("player_lineup") or []
    e_lineup = snapshot.get("enemy_lineup") or []
    if p_lineup:
        lines.append(f"我方候补阵容: {', '.join(p_lineup)}")
    if e_lineup:
        lines.append(f"敌方已知阵容: {', '.join(e_lineup)}")

    lines.append("")
    lines.append("请作为最高水平 PVP 军师，综合我方技能效果（包含灼烧/控制/状态回复等机制）、双方特性加成、属性克制倍率及敌方上招，给出本回合最优决策。必须严格只回复指定 JSON。")
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