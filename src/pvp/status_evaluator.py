# -*- coding: utf-8 -*-
"""status_evaluator — 异常状态与印记数值推演引擎

核心机制(实战与最新规则对齐):
1. 灼烧 (Burn): 火属性，基准 2%/层 (10层=20%)，回合结束层数减半(至少减1层)。火系免疫。
   * 吃属性克制！例如火克草(2.0x)，10层灼烧打草系造成 40% 最大生命伤害！
2. 寄生 (Leech): 草属性，最新版本调整为基准 2%/层，吸取等量生命回复自身，草系免疫。
   * 吃属性克制！例如草克水(2.0x)，3层寄生打水系造成 12% 吸血。
3. 中毒 (Poison): 毒属性，基准 3%/层，不衰减。毒系、机械系免疫。
   * 吃属性克制！例如毒克草/萌(2.0x)。
4. 冻结 (Freeze): 冰属性，基准 5%/层锁定血线，当生命值百分比 <= 冻结阈值时直接力竭(即死斩杀)。冰系免疫。
5. 星陨 (Meteor): 幻属性，基准 30 威力/层，受非幻系技能攻击或回合触发。
6. 麻痹/减速: 速度修正 (麻痹有效速度 * 0.5，减速印记 -10%)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.pvp.type_chart import get_attr_multiplier, normalize_attr_list

# ============================================================
# 异常状态与印记参数配置 (参数化设计，支持随时微调)
# ============================================================

STATUS_RULES: Dict[str, Dict[str, Any]] = {
    "burn": {
        "name": "灼烧",
        "alias": ["灼烧", "烧伤", "火伤"],
        "element": "火",
        "base_pct_per_stack": 0.02,       # 基准 2% / 层 (10层=20%)
        "decay": "half",                  # 回合结束层数减半(至少减1)
        "immune_elements": ["火"],
        "desc": "每层扣除2%最大生命(受属性克制加成)，回合末层数减半，火系免疫",
    },
    "leech": {
        "name": "寄生",
        "alias": ["寄生", "吸血"],
        "element": "草",
        "base_pct_per_stack": 0.02,       # 最新版本调整为 2% / 层
        "decay": "none",
        "heal_caster": True,              # 吸血给施加者
        "immune_elements": ["草"],
        "desc": "每层吸取2%最大生命并回复自身(受属性克制加成)，草系免疫",
    },
    "poison": {
        "name": "中毒",
        "alias": ["中毒", "剧毒", "毒"],
        "element": "毒",
        "base_pct_per_stack": 0.03,       # 基准 3% / 层
        "decay": "none",                  # 不衰减
        "immune_elements": ["毒", "机械"],
        "desc": "每层扣除3%最大生命(受属性克制加成)，不衰减，毒/机械免疫",
    },
    "freeze": {
        "name": "冻结",
        "alias": ["冻结", "冰冻", "霜冻"],
        "element": "冰",
        "threshold_pct_per_stack": 0.05,  # 基准每层 5% 斩杀线
        "decay": "none",
        "immune_elements": ["冰"],
        "desc": "锁定生命值，当前血量低于冻结阈值直接力竭斩杀，冰系免疫",
    },
    "meteor": {
        "name": "星陨",
        "alias": ["星陨", "星陨印记"],
        "element": "幻",
        "power_per_stack": 30,            # 每层 30 威力
        "decay": "clear_on_hit",          # 非幻系攻击触发后清空
        "immune_elements": [],
        "desc": "受非幻系攻击或3回合触发，每层造成30威力魔法伤害",
    },
}


@dataclass
class DotDetail:
    """单个 DOT / 状态的详细结算信息"""
    status_key: str
    name: str
    element: str
    stacks: int
    mult: float                     # 属性克制倍率 (2.0x克制, 0.5x抵抗, 0.0x免疫)
    is_immune: bool
    dmg_pct: float                  # 本回合结算扣血百分比 (如 0.40 表示 40%)
    dmg_val: int                    # 本回合结算点数伤害
    next_stacks: int                # 回合末衰减后的剩余层数
    freeze_threshold_pct: float = 0.0  # 若为冻结，斩杀阈值百分比
    desc: str = ""


@dataclass
class StatusEvaluation:
    """综合状态评估结果"""
    total_dot_pct: float = 0.0       # 本回合末 DOT 扣血总百分比 (0.0~1.0+)
    total_dot_val: int = 0          # 本回合末 DOT 扣血总数值
    freeze_threshold_pct: float = 0.0 # 冻结直接力竭斩杀线 (如 0.20 表示 <=20% 即死)
    is_dot_lethal: bool = False     # 仅凭回合末 DOT 是否能直接斩杀
    is_freeze_lethal: bool = False  # 是否已满足冻结力竭斩杀
    speed_modifier: float = 1.0     # 状态带来的有效速度修正 (如麻痹 *0.5)
    details: List[DotDetail] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    summary_text: str = ""          # 供 UI 和 AI Prompt 消费的自然语言描述


def parse_buff_entry(item: Any) -> Tuple[str, int]:
    """从字典或字符串中解析出状态名称和层数。
    示例:
      "10层灼烧" -> ("灼烧", 10)
      "灼烧×5"   -> ("灼烧", 5)
      {"name": "灼烧", "stack": 10} -> ("灼烧", 10)
    """
    if isinstance(item, dict):
        raw_name = str(item.get("name") or item.get("text") or "").strip()
        stack = int(item.get("stack") or 1)
        # 兼容 name 中自带层数的情况，如 "10层灼烧"
        m = re.search(r"(\d+)\s*层", raw_name)
        if m:
            stack = int(m.group(1))
            raw_name = re.sub(r"\d+\s*层", "", raw_name).strip()
        return raw_name, max(1, stack)
    
    text = str(item).strip()
    m_stack = re.search(r"(\d+)\s*层", text)
    if m_stack:
        stack = int(m_stack.group(1))
        name = re.sub(r"\d+\s*层", "", text).strip()
        return name, stack
    
    m_x = re.search(r"[×xX*](\d+)", text)
    if m_x:
        stack = int(m_x.group(1))
        name = re.sub(r"[×xX*]\d+", "", text).strip()
        return name, stack
        
    return text, 1


def match_status_rule(name: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """根据状态名称匹配 STATUS_RULES 中的规则"""
    name_clean = name.strip()
    for key, rule in STATUS_RULES.items():
        if name_clean == rule["name"]:
            return key, rule
        for alias in rule["alias"]:
            if alias in name_clean:
                return key, rule
    return None


def evaluate_status(
    buffs: List[Any],
    target_attrs: List[str],
    current_hp_pct: float = 1.0,
    current_hp_val: Optional[int] = None,
    max_hp_val: Optional[int] = None,
) -> StatusEvaluation:
    """评估目标精灵身上所有异常状态与印记的综合数值与斩杀线。

    参数:
        buffs: 状态列表，元素可为 {"name": "...", "stack": ...} 或字符串 "10层灼烧"
        target_attrs: 目标防御方的属性列表，如 ["草"] 或 ["水", "龙"]
        current_hp_pct: 目标当前血量百分比 (0.0 ~ 1.0)
        current_hp_val: 目标当前血量数值 (可选)
        max_hp_val: 目标最大血量数值 (可选)

    返回:
        StatusEvaluation 结构
    """
    clean_attrs = normalize_attr_list(target_attrs or [])
    eval_res = StatusEvaluation()
    
    # 汇总各状态层数: rule_key -> total_stacks
    merged_stacks: Dict[str, int] = {}
    has_paralysis = False
    has_slow_mark = False

    for item in buffs or []:
        raw_name, stack = parse_buff_entry(item)
        if not raw_name:
            continue
        
        # 麻痹 / 减速特殊识别
        if "麻痹" in raw_name or "麻醉" in raw_name:
            has_paralysis = True
        if "减速" in raw_name:
            has_slow_mark = True

        matched = match_status_rule(raw_name)
        if matched:
            key, _ = matched
            merged_stacks[key] = merged_stacks.get(key, 0) + stack

    # 速度修正计算
    speed_mod = 1.0
    if has_paralysis:
        speed_mod *= 0.5
    if has_slow_mark:
        speed_mod *= 0.9
    eval_res.speed_modifier = speed_mod

    # 逐项计算 DOT 与克制
    total_dot_pct = 0.0
    total_dot_val = 0
    freeze_threshold = 0.0
    details: List[DotDetail] = []
    tag_list: List[str] = []

    for key, stacks in merged_stacks.items():
        rule = STATUS_RULES[key]
        element = rule["element"]
        is_immune = any(imm in clean_attrs for imm in rule.get("immune_elements", []))

        # 核心：计算属性克制倍率 (克制=2.0x/3.0x, 抵抗=0.5x/0.25x, 普通=1.0x)
        if is_immune:
            mult = 0.0
        else:
            mult = get_attr_multiplier(element, clean_attrs)

        dmg_pct = 0.0
        dmg_val = 0
        next_stacks = stacks
        frz_pct = 0.0

        if key in ("burn", "leech", "poison"):
            base_pct = rule.get("base_pct_per_stack", 0.0)
            dmg_pct = base_pct * stacks * mult
            if max_hp_val and max_hp_val > 0:
                dmg_val = int(round(max_hp_val * dmg_pct))
            elif current_hp_val and current_hp_pct > 0:
                # 倒推估计 max_hp
                estimated_max = current_hp_val / current_hp_pct
                dmg_val = int(round(estimated_max * dmg_pct))

            total_dot_pct += dmg_pct
            total_dot_val += dmg_val

            # 衰减机制
            if rule.get("decay") == "half":
                next_stacks = max(1, stacks // 2) if stacks > 1 else 0

        elif key == "freeze":
            base_thresh = rule.get("threshold_pct_per_stack", 0.05)
            # 冻结斩杀阈值同样遵循属性克制关系
            frz_pct = base_thresh * stacks * mult
            freeze_threshold = max(freeze_threshold, frz_pct)

        # 构造详情标签与描述
        mult_desc = f"×{mult:.1f}克制" if mult > 1.0 else (f"×{mult:.2g}抵抗" if 0 < mult < 1.0 else ("免疫" if is_immune else "1.0倍"))
        if is_immune:
            desc = f"{rule['name']}×{stacks} ({element}系免疫, 0伤害)"
        elif key == "freeze":
            desc = f"{rule['name']}×{stacks} (锁定{frz_pct:.0%}, {mult_desc})"
            tag_list.append(f"冻结斩杀线{frz_pct:.0%}")
        else:
            desc = f"{rule['name']}×{stacks} ({element}系{mult_desc}, 扣{dmg_pct:.0%}HP"
            if rule.get("decay") == "half":
                desc += f", 次轮衰减至{next_stacks}层"
            desc += ")"
            tag_list.append(f"{rule['name']}×{stacks}(-{dmg_pct:.0%})")

        details.append(DotDetail(
            status_key=key,
            name=rule["name"],
            element=element,
            stacks=stacks,
            mult=mult,
            is_immune=is_immune,
            dmg_pct=dmg_pct,
            dmg_val=dmg_val,
            next_stacks=next_stacks,
            freeze_threshold_pct=frz_pct,
            desc=desc,
        ))

    eval_res.total_dot_pct = round(total_dot_pct, 4)
    eval_res.total_dot_val = total_dot_val
    eval_res.freeze_threshold_pct = round(freeze_threshold, 4)
    eval_res.details = details
    eval_res.tags = tag_list

    # 纯百分比斩杀判定 (敌方HP在对战中本就是百分比)
    if current_hp_pct <= eval_res.total_dot_pct and eval_res.total_dot_pct > 0:
        eval_res.is_dot_lethal = True
    if freeze_threshold > 0 and current_hp_pct <= freeze_threshold:
        eval_res.is_freeze_lethal = True

    # 汇总战术说明 (完全对齐百分比，让 AI 和玩家一目了然)
    parts = []
    if details:
        parts.append(" | ".join(d.desc for d in details))
    if eval_res.is_dot_lethal:
        parts.append(f"【DOT必死! 回合末扣{total_dot_pct:.0%} >= 目标血量{current_hp_pct:.0%}】")
    elif eval_res.is_freeze_lethal:
        parts.append(f"【冻结力竭! 目标血量{current_hp_pct:.0%} <= 冻结线{freeze_threshold:.0%}】")
    elif total_dot_pct > 0:
        parts.append(f"回合末合计扣除约 {total_dot_pct:.0%} 生命")

    if speed_mod < 1.0:
        parts.append(f"速度受负面影响降至 {speed_mod:.0%}")

    eval_res.summary_text = "；".join(parts) if parts else "正常(无持续负面)"
    return eval_res
