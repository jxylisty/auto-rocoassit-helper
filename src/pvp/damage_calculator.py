# -*- coding: utf-8 -*-
"""
PVP 伤害计算引擎 — 从 luokewangguo 的 pvpDamageEngine.js 完整移植
与 JS 版公式完全一致，确保计算结果可复现。
"""

import re
import math
from typing import Dict, List, Optional, Any, Union

from .pvp_rules import PVP_RULES, LEVEL, STAR, NATURE, DAMAGE, DEFAULT_SCENARIO
from .type_chart import normalize_attr, normalize_attr_list, get_attr_multiplier

# ============================================================
# 基础工具函数
# ============================================================

DAMAGE_SKILL_TYPES = ("物攻", "魔攻")

PANEL_BUFF_KEY_MAP = {
    "attack": ["atkBuff", "attackBuff"],
    "mattack": ["matkBuff", "mattackBuff"],
    "defense": ["defBuff", "defenseBuff"],
    "mdefense": ["mdefBuff", "mdefenseBuff"],
    "speed": ["speedBuff"],
    "hp": ["hpBuff"],
}

NATURE_NAME_TO_KEY = {
    "生命": "hp", "物攻": "attack", "魔攻": "mattack",
    "物防": "defense", "魔防": "mdefense", "速度": "speed",
    "hp": "hp", "attack": "attack", "mattack": "mattack",
    "defense": "defense", "mdefense": "mdefense", "speed": "speed",
}

DYNAMIC_POWER_KEYWORDS = [
    "连击", "连续攻击", "2连击", "3连击", "4连击", "5连击", "6连击", "10连击",
    "威力提升", "威力增加", "威力提高",
    "根据", "基于",
    "速度", "双防", "双攻", "攻击", "防御", "魔攻", "魔防",
    "越高", "越低", "越多",
    "追加", "随机", "随机威力",
    "每次", "永久", "叠加", "递增",
    "生命", "HP", "血量",
    "条件威力", "条件增伤",
]


def to_number(value: Any, fallback: float = 0.0) -> float:
    """安全转换为数值"""
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return fallback


def parse_loose_number(value: Any, fallback: float = 0.0) -> float:
    """从文本中提取数值"""
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    text = str(value).strip() if value else ""
    if not text:
        return fallback
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if m:
        return float(m.group())
    return to_number(text, fallback)


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def get_percent_buff_multiplier(attr_key: str, buffs: dict = None) -> float:
    """百分比 buff → 倍率"""
    if buffs is None:
        buffs = {}
    keys = PANEL_BUFF_KEY_MAP.get(attr_key, [])
    total = sum(to_number(buffs.get(k, 0)) for k in keys)
    return 1.0 + total / 100.0


def nature_up_bonus(star: int) -> float:
    """性格提升倍率随星级变化"""
    s = int(to_number(star, 0))
    if s == 0: return 0.0
    if s == 1: return 0.12
    if s == 2: return 0.14
    if s == 3: return 0.16
    if s == 4: return 0.18
    return 0.20


# ============================================================
# 面板计算
# ============================================================

def calculate_panel_value(
    race_value: float,
    input_iv: float,
    level: int = LEVEL,
    star: int = STAR,
    attr_key: str = "",
    nature_up: str = None,
    nature_down: str = None,
    buffs: dict = None,
) -> float:
    """计算单个面板属性值（与 JS 版完全一致）"""
    actual_iv = clamp(to_number(input_iv, 0), 0, 10) * (to_number(star, 0) + 1)
    race = to_number(race_value, 0)
    base_value = race * 0.5 + actual_iv * 0.25 + 10

    if attr_key == "hp":
        growth = (race + actual_iv * 0.5) * 0.02 + 1
    else:
        growth = (race + actual_iv * 0.5) * 0.01

    raw_panel = base_value + to_number(level, 0) * growth

    # 性格修正
    up_key = NATURE_NAME_TO_KEY.get(nature_up, "") if nature_up else ""
    down_key = NATURE_NAME_TO_KEY.get(nature_down, "") if nature_down else ""
    nature_mod = 1.0
    if up_key and up_key == attr_key:
        nature_mod = 1.0 + nature_up_bonus(star)
    elif down_key and down_key == attr_key:
        nature_mod = NATURE["down"]

    # 面板四舍五入(对齐 roco-cal normal_round = floor(x+0.5)), 再乘性格
    pre_nature_panel = math.floor(raw_panel + 0.5)
    post_nature_panel = round(pre_nature_panel * nature_mod + 0.0000001)
    star_bonus = to_number(star, 0) * 20 if attr_key == "hp" else to_number(star, 0) * 10

    panel = post_nature_panel + star_bonus
    panel *= get_percent_buff_multiplier(attr_key, buffs)
    if attr_key == "speed":
        panel += to_number((buffs or {}).get("speedFlat", 0), 0)

    return panel


def calculate_world_speed_range(race_speed: float, level: int = LEVEL, star: int = STAR) -> dict:
    """
    计算《洛克王国：世界》PVP真实速度极值区间（完全对齐游戏内点击头像显示）
    - 极限最低速度: 0加点, 减速性格 (0.9x)
    - 中位基准速度: 0加点, 平衡性格 (1.0x)
    - 满配平衡速度: 10满加点, 平衡性格 (1.0x)
    - 极限最高速度: 10满加点, 5星加速性格 (1.2x)
    """
    s_min = int(calculate_panel_value(race_speed, input_iv=0, level=level, star=star, attr_key="speed", nature_down="速度"))
    s_mid = int(calculate_panel_value(race_speed, input_iv=0, level=level, star=star, attr_key="speed"))
    s_balanced_max = int(calculate_panel_value(race_speed, input_iv=10, level=level, star=star, attr_key="speed"))
    s_max = int(calculate_panel_value(race_speed, input_iv=10, level=level, star=star, attr_key="speed", nature_up="速度"))
    return {
        "race": race_speed,
        "min": s_min,
        "mid": s_mid,
        "balanced_max": s_balanced_max,
        "max": s_max,
        "range_str": f"{s_min} ~ {s_max}"
    }


def calculate_all_panels(
    race: dict = None,
    ivs: dict = None,
    level: int = LEVEL,
    star: int = STAR,
    nature_up: str = None,
    nature_down: str = None,
    buffs: dict = None,
) -> Dict[str, float]:
    """计算全部 6 个面板值"""
    if race is None:
        race = {}
    if ivs is None:
        ivs = {}
    return {
        "hp": calculate_panel_value(race.get("hp", 0), ivs.get("hp", 0), level, star, "hp", nature_up, nature_down, buffs),
        "attack": calculate_panel_value(race.get("attack", 0), ivs.get("attack", 0), level, star, "attack", nature_up, nature_down, buffs),
        "mattack": calculate_panel_value(race.get("mattack", 0), ivs.get("mattack", 0), level, star, "mattack", nature_up, nature_down, buffs),
        "defense": calculate_panel_value(race.get("defense", 0), ivs.get("defense", 0), level, star, "defense", nature_up, nature_down, buffs),
        "mdefense": calculate_panel_value(race.get("mdefense", 0), ivs.get("mdefense", 0), level, star, "mdefense", nature_up, nature_down, buffs),
        "speed": calculate_panel_value(race.get("speed", 0), ivs.get("speed", 0), level, star, "speed", nature_up, nature_down, buffs),
    }


def calculate_full_panels(
    pet_seq: int,
    ivs: dict = None,
    level: int = LEVEL,
    star: int = STAR,
    nature_up: str = None,
    nature_down: str = None,
    buffs: dict = None,
) -> Optional[Dict[str, float]]:
    """计算精灵满配面板（自动加载种族值）"""
    from .pet_loader import get_pet_race
    race = get_pet_race(pet_seq)
    if race is None:
        return None
    return calculate_all_panels(race, ivs, level, star, nature_up, nature_down, buffs)


# ============================================================
# 技能解析
# ============================================================

def parse_base_hits(describe: str = "") -> int:
    """从技能描述中解析基础连击数"""
    m = re.search(r"(?:^|[^\d])([1-6]|10)连击", describe)
    return max(1, int(m.group(1))) if m else 1


def parse_priority(describe: str = "") -> int:
    """从技能描述中解析先手值"""
    m = re.search(r"(?:先手|先制)\s*([+-]\d+)", describe)
    if m:
        return int(m.group(1))
    m = re.search(r"(?:先手|先制)\s*(\d+)", describe)
    return int(m.group(1)) if m else 0


def is_dynamic_power_skill(skill: dict = None) -> bool:
    """判断是否为动态威力技能"""
    if skill is None:
        return False
    describe = str(skill.get("describe", ""))
    power_text = str(skill.get("power", ""))
    name = str(skill.get("name", ""))

    if any(kw in describe for kw in DYNAMIC_POWER_KEYWORDS):
        return True
    if re.search(r"(?:^|[^\d])([2-9]|10)连击", describe):
        return True
    if re.search(r"(?:先于|若|如果|当).*?威力", describe):
        return True
    if re.search(r"^\d+技能威力", power_text) and not re.match(r"^\d+$", power_text.replace("技能威力", "")):
        return True
    if name and re.search(r"(?:扫尾|撕裂|贯穿|暴击)", name):
        return True
    return False


def parse_conditional_effects(describe: str = "") -> list:
    """解析技能条件效果"""
    effects = []

    # 先手威力加成
    power_matches = re.findall(
        r"(?:若|如果|当).*?(?:先于敌方攻击|先手攻击|先于敌方|先手).*?(?:威力|技能威力)\+(\d+)%",
        describe
    )
    for m in power_matches:
        effects.append({
            "type": "powerBuff",
            "conditionType": "acts_before_enemy",
            "value": 1 + int(m) / 100,
            "text": f"先于敌方时威力 +{m}%",
        })

    # 先手连击
    hits_m = re.search(r"(?:若|如果|当).*?(?:先于敌方攻击|先手攻击|先于敌方|先手).*?(?:改为|变为|变成)?([1-6]|10)连击", describe)
    if hits_m:
        effects.append({
            "type": "hitsOverride",
            "conditionType": "acts_before_enemy",
            "value": int(hits_m.group(1)),
            "text": f"条件连击：改为 {hits_m.group(1)} 连击",
        })

    # 连击翻倍
    if re.search(r"(?:若|如果|当).*?连击数翻倍", describe):
        effects.append({
            "type": "hitsMultiplier",
            "conditionType": "state",
            "value": 2,
            "text": "条件连击：本次技能连击数翻倍",
        })

    # 低血量加连击
    hp_m = re.search(r"(?:若|如果|当).*?生命低于50%.*?连击数\+(\d+)", describe)
    if hp_m:
        effects.append({
            "type": "hitsDelta",
            "conditionType": "hp_below_50",
            "value": int(hp_m.group(1)),
            "text": f"生命低于50%时连击数 +{hp_m.group(1)}",
        })

    return effects


def normalize_battle_skill(skill: dict = None) -> dict:
    """标准化技能数据"""
    if skill is None:
        skill = {}
    name = str(skill.get("name", ""))
    skill_type = str(skill.get("type", ""))
    skill_attr = str(skill.get("attr", ""))
    power = parse_loose_number(skill.get("power", 0), 0)
    consume = parse_loose_number(skill.get("consume", 0), 0)
    describe = str(skill.get("describe", ""))
    base_hits = parse_base_hits(describe)
    priority = parse_priority(describe)
    is_quick = "迅捷" in describe
    damage_skill = skill_type in DAMAGE_SKILL_TYPES and power > 0
    is_dynamic = is_dynamic_power_skill(skill)

    mechanic_tags = []
    if "连击" in describe: mechanic_tags.append("连击")
    if re.search(r"(?:先手|先制)\s*[+-]?\d+", describe): mechanic_tags.append("先手")
    if "迅捷" in describe: mechanic_tags.append("迅捷")
    if "威力+%" in describe or re.search(r"威力\+\d+%", describe): mechanic_tags.append("条件威力")
    if "连击数" in describe or "多段" in describe: mechanic_tags.append("条件连击")
    if "脱离" in describe: mechanic_tags.append("脱离")
    if "减伤" in describe: mechanic_tags.append("减伤")
    if re.search(r"增效|强化|提升|增加", describe): mechanic_tags.append("强化")
    if "吸血" in describe or "回复" in describe and "生命" in describe: mechanic_tags.append("吸血")
    if "应对" in describe: mechanic_tags.append("应对")
    if "传动" in describe or "啮合传递" in describe: mechanic_tags.append("传动")

    return {
        "name": name,
        "type": skill_type,
        "attr": skill_attr,
        "power": power,
        "consume": consume,
        "describe": describe,
        "baseHits": base_hits,
        "priority": priority,
        "isQuick": is_quick,
        "isDynamic": is_dynamic,
        "isDamageSkill": damage_skill,
        "mechanicTags": list(dict.fromkeys(mechanic_tags)),
        "conditionalEffects": parse_conditional_effects(describe),
    }


def damage_constant(level: int = LEVEL) -> float:
    """等级伤害常量(口径对齐 roco-cal damresult.py): (level*45/100 + 10) / 41, 60级≈0.9024"""
    return (to_number(level, LEVEL) * 45 / 100 + 10) / 41


def is_damage_skill(skill: dict = None) -> bool:
    """判断技能是否为伤害技能"""
    if skill is None:
        return False
    normalized = normalize_battle_skill(skill)
    return normalized["isDamageSkill"]


# ============================================================
# 先后手判断
# ============================================================

def can_act_before_enemy(
    my_panel: dict = None,
    enemy_panel: dict = None,
    selected_skill: dict = None,
    enemy_selected_skill: dict = None,
) -> dict:
    """判断我方是否先手"""
    if my_panel is None: my_panel = {}
    if enemy_panel is None: enemy_panel = {}
    if selected_skill is None: selected_skill = {}
    if enemy_selected_skill is None: enemy_selected_skill = {}

    my_priority = to_number(selected_skill.get("priority", 0), 0)
    enemy_priority = to_number(enemy_selected_skill.get("priority", 0), 0)
    my_speed = to_number(my_panel.get("speed", 0), 0)
    enemy_speed = to_number(enemy_panel.get("speed", 0), 0)

    compare = {
        "myPriority": my_priority, "enemyPriority": enemy_priority,
        "mySpeed": my_speed, "enemySpeed": enemy_speed,
    }

    if my_priority > enemy_priority:
        return {"result": True, "reason": "我方技能先制值更高", "compare": compare}
    if my_priority < enemy_priority:
        return {"result": False, "reason": "敌方技能先制值更高", "compare": compare}
    if my_speed > enemy_speed:
        return {"result": True, "reason": "双方先制相同，我方速度更高", "compare": compare}
    if my_speed < enemy_speed:
        return {"result": False, "reason": "双方先制相同，敌方速度更高", "compare": compare}
    return {"result": "tie", "reason": "双方先制和速度相同，先后手不确定", "compare": compare}


# ============================================================
# 核心伤害计算
# ============================================================

def calculate_damage_full(
    attacker_panel: dict = None,
    defender_panel: dict = None,
    skill_power: float = 0,
    skill_type: str = "",
    skill_attr: str = "",
    attacker_attrs: list = None,
    defender_attrs: list = None,
    power_buff: float = None,
    weather_mod: float = None,
    defense_reduction: float = None,
    atk_level: float = None,
    def_level: float = None,
    hits: int = None,
    skip_attr_and_stab: bool = False,
    level: int = LEVEL,
) -> dict:
    """
    完整伤害计算（与 JS 版公式完全一致）
    
    公式: damage = (atk/def) * 0.9 * skillPower * powerBuff * sameTypeBonus * attrMultiplier * levelMod * weatherMod * hits * reductionMultiplier
    
    参数:
        attacker_panel: 攻击方面板 {hp, attack, mattack, defense, mdefense, speed}
        defender_panel: 防御方面板
        skill_power: 技能威力（数值）
        skill_type: 技能类型 "物攻" / "魔攻"
        skill_attr: 技能属性
        attacker_attrs: 攻击方精灵属性列表
        defender_attrs: 防御方精灵属性列表
        power_buff: 威力 buff 倍率 (默认 1.0)
        weather_mod: 天气修正 (默认 1.0)
        defense_reduction: 减伤比例 (0~1, 默认 0)
        atk_level: 攻击等级 (+1=+10%)
        def_level: 防御等级
        hits: 连击数
        skip_attr_and_stab: 跳过属性克制和本系加成
    """
    if attacker_panel is None: attacker_panel = {}
    if defender_panel is None: defender_panel = {}
    if attacker_attrs is None: attacker_attrs = []
    if defender_attrs is None: defender_attrs = []

    if power_buff is None: power_buff = DEFAULT_SCENARIO["powerBuff"]
    if weather_mod is None: weather_mod = DEFAULT_SCENARIO["weatherMod"]
    if defense_reduction is None: defense_reduction = DEFAULT_SCENARIO["defenseReduction"]
    if atk_level is None: atk_level = DEFAULT_SCENARIO["atkLevel"]
    if def_level is None: def_level = DEFAULT_SCENARIO["defLevel"]
    if hits is None: hits = DEFAULT_SCENARIO["hits"]

    is_physical = str(skill_type).strip() == "物攻"
    atk_used = to_number(attacker_panel.get("attack" if is_physical else "mattack", 1), 1)
    raw_defense = to_number(defender_panel.get("defense" if is_physical else "mdefense", 1), 1)
    def_used = max(1.0, raw_defense)

    normalized_skill_attr = normalize_attr(skill_attr)
    normalized_attacker_attrs = normalize_attr_list(attacker_attrs)
    normalized_defender_attrs = normalize_attr_list(defender_attrs)

    same_type_bonus = 1.0
    if not skip_attr_and_stab and normalized_skill_attr in normalized_attacker_attrs:
        same_type_bonus = DAMAGE["sameTypeBonus"]

    attr_multiplier = 1.0
    if not skip_attr_and_stab:
        attr_multiplier = get_attr_multiplier(normalized_skill_attr, normalized_defender_attrs)

    level_mod = 1.0 * (1 + to_number(atk_level, 0) / 10.0) * (1 + to_number(def_level, 0) / 10.0)
    hit_count = max(1, int(to_number(hits, 1)))
    reduction_multiplier = 1 - clamp(to_number(defense_reduction, 0), 0, 1)

    # 等级伤害常量(对齐 luokewangguo pvpDamageEngine): (lv*0.45+10)/41, 60级≈0.9024, 而非固定 0.9
    level_const = damage_constant(level)
    damage = max(
        1.0,
        (atk_used / def_used)
        * level_const
        * to_number(skill_power, 0)
        * to_number(power_buff, 1)
        * same_type_bonus
        * attr_multiplier
        * level_mod
        * to_number(weather_mod, 1)
        * hit_count
        * reduction_multiplier,
    )

    return {
        "damage": round(damage, 1),
        "atkUsed": round(atk_used, 1),
        "defUsed": round(def_used, 1),
        "sameTypeBonus": same_type_bonus,
        "attrMultiplier": attr_multiplier,
        "hits": hit_count,
        "formulaParts": {
            "attackRatio": round(atk_used / def_used, 4),
            "baseConstant": round(level_const, 4),
            "skillPower": to_number(skill_power, 0),
            "powerBuff": to_number(power_buff, 1),
            "sameTypeBonus": same_type_bonus,
            "attrMultiplier": attr_multiplier,
            "levelMod": round(level_mod, 4),
            "weatherMod": to_number(weather_mod, 1),
            "hits": hit_count,
            "defenseReduction": clamp(to_number(defense_reduction, 0), 0, 1),
            "skillType": str(skill_type).strip(),
        },
    }


# ============================================================
# 便捷计算：精灵 vs 精灵，技能 vs 技能
# ============================================================

def calc_pet_vs_pet(
    attacker_seq: int,
    defender_seq: int,
    skill_name: str,
    attacker_ivs: dict = None,
    defender_ivs: dict = None,
    attacker_nature_up: str = None,
    attacker_nature_down: str = None,
    power_buff: float = 1.0,
    weather_mod: float = 1.0,
    atk_level: float = 0,
    def_level: float = 0,
    hits: int = 1,
) -> Optional[dict]:
    """
    便捷方法：精灵对精灵伤害计算
    
    参数:
        attacker_seq: 攻击方精灵编号
        defender_seq: 防御方精灵编号
        skill_name: 技能名称
        attacker_ivs: 攻击方个体值 (默认全10)
        defender_ivs: 防御方个体值 (默认全10)
    """
    from .pet_loader import pet_to_dict, get_pet_types
    from .skill_loader import get_skill

    if attacker_ivs is None:
        attacker_ivs = {"hp": 10, "attack": 10, "mattack": 10, "defense": 10, "mdefense": 10, "speed": 10}
    if defender_ivs is None:
        defender_ivs = {"hp": 10, "attack": 10, "mattack": 10, "defense": 10, "mdefense": 10, "speed": 10}

    attacker = pet_to_dict(attacker_seq)
    defender = pet_to_dict(defender_seq)
    if attacker is None or defender is None:
        return None

    skill_data = get_skill(skill_name)
    if skill_data is None:
        return None

    attacker_panel = calculate_all_panels(
        attacker["race"], attacker_ivs,
        nature_up=attacker_nature_up, nature_down=attacker_nature_down,
    )
    defender_panel = calculate_all_panels(defender["race"], defender_ivs)

    return calculate_damage_full(
        attacker_panel=attacker_panel,
        defender_panel=defender_panel,
        skill_power=skill_data.get("power", 0),
        skill_type=skill_data.get("type", ""),
        skill_attr=skill_data.get("attr", ""),
        attacker_attrs=attacker["types"],
        defender_attrs=defender["types"],
        power_buff=power_buff,
        weather_mod=weather_mod,
        atk_level=atk_level,
        def_level=def_level,
        hits=hits,
    )


def calculate_resonance_impact_damages(
    enemy_panel: dict,
    self_panel: dict,
    enemy_types: list,
    self_types: list,
    self_current_hp: int = None,
) -> dict:
    """
    推算敌方暗手【愿力冲击】（共鸣魔法）在不同情境下的即时伤害：
    
    设定规则：
    1. 基础威力: 80
    2. 攻防判定: 敌方物攻/魔攻较高项作为主攻输出
    3. 本系加成: 若愿力属性在敌方本系中则乘 1.25x
    4. 应对加成: 我方出状态技能时被应对到，伤害乘以 2.5 倍
    5. 智能推算: 根据「克制敌方弱点的属性」与「克制我方属性」取交集，推算敌方针对性携带的愿力属性
    
    输出情境（至少3种）：
    - 克制不应对愿力 (2.0x / 1.0x应对)
    - 克制应对愿力 (2.0x / 2.5x应对)
    - 不克制应对愿力 (1.0x / 2.5x应对)
    - 特例：3倍极限克制不应对愿力 (若我方存在 3.0x 双弱点属性)
    """
    from .type_chart import ALL_ATTRS, get_attr_multiplier, normalize_attr_list

    normalized_enemy_types = normalize_attr_list(enemy_types or [])
    normalized_self_types = normalize_attr_list(self_types or [])

    # 1. 敌方主攻类型推导
    is_physical = to_number(enemy_panel.get("attack", 0)) >= to_number(enemy_panel.get("mattack", 0))
    skill_type = "物攻" if is_physical else "魔攻"
    atk_stat_name = "物攻" if is_physical else "魔攻"

    # 2. 敌方的弱点属性集合
    enemy_weak_attrs = [a for a in ALL_ATTRS if get_attr_multiplier(a, normalized_enemy_types) >= 2.0]

    # 3. 敌方为了反制自身弱点可能携带的愿力属性
    counter_attrs = set()
    for w in enemy_weak_attrs:
        for a in ALL_ATTRS:
            if get_attr_multiplier(a, [w]) >= 2.0:
                counter_attrs.add(a)

    # 4. 对我方造成克制的属性
    self_weak_2x = [a for a in ALL_ATTRS if get_attr_multiplier(a, normalized_self_types) == 2.0]
    self_weak_3x = [a for a in ALL_ATTRS if get_attr_multiplier(a, normalized_self_types) >= 3.0]

    # 5. 交集推导
    intersect_2x = [a for a in sorted(counter_attrs) if a in self_weak_2x]
    intersect_3x = [a for a in sorted(counter_attrs) if a in self_weak_3x]

    likely_counter_attrs = intersect_2x if intersect_2x else self_weak_2x
    rep_2x_attr = likely_counter_attrs[0] if likely_counter_attrs else ("火" if "草" in normalized_self_types else "普通")

    # 3倍弱点代表属性
    rep_3x_attr = intersect_3x[0] if intersect_3x else (self_weak_3x[0] if self_weak_3x else None)

    hp_threshold = self_current_hp if (self_current_hp is not None and self_current_hp > 0) else int(self_panel.get("hp", 450))

    def _calc_dmg(attr: str, counter_mult: float) -> dict:
        base_res = calculate_damage_full(
            attacker_panel=enemy_panel,
            defender_panel=self_panel,
            skill_power=80,
            skill_type=skill_type,
            skill_attr=attr,
            attacker_attrs=normalized_enemy_types,
            defender_attrs=normalized_self_types,
        )
        dmg_min = int(base_res["damage"] * counter_mult)
        dmg_max = int(dmg_min * 1.15)
        is_lethal = dmg_min >= hp_threshold
        return {
            "attr": attr,
            "dmg_min": dmg_min,
            "dmg_max": dmg_max,
            "is_lethal": is_lethal,
            "attr_mult": base_res["attrMultiplier"],
            "same_type": base_res["sameTypeBonus"] > 1.0,
        }

    cases = []

    # 场景1：克制不应对愿力 (2.0x, counter 1.0x)
    c1 = _calc_dmg(rep_2x_attr, 1.0)
    cases.append({
        "id": "resist_no_counter",
        "name": "克制不应对愿力",
        "tag": "克制 · 常规",
        "desc": f"对方克制愿力({rep_2x_attr})，我方出非状态技能 (2.0x)",
        "attr": rep_2x_attr,
        "dmg_min": c1["dmg_min"],
        "dmg_max": c1["dmg_max"],
        "is_lethal": c1["is_lethal"],
        "multiplier": c1["attr_mult"],
        "counter_mult": 1.0,
        "badge": "2.0x 常规",
    })

    # 场景2：克制应对愿力 (2.0x, counter 2.5x)
    c2 = _calc_dmg(rep_2x_attr, 2.5)
    cases.append({
        "id": "resist_counter",
        "name": "克制应对愿力",
        "tag": "克制 · 应对×2.5",
        "desc": f"对方克制愿力({rep_2x_attr})应对我方状态技能 (2.0x × 2.5)",
        "attr": rep_2x_attr,
        "dmg_min": c2["dmg_min"],
        "dmg_max": c2["dmg_max"],
        "is_lethal": c2["is_lethal"],
        "multiplier": c2["attr_mult"],
        "counter_mult": 2.5,
        "badge": "2.0x 应对爆发",
    })

    # 场景3：不克制应对愿力 (1.0x, counter 2.5x)
    normal_attr = "普通"
    for a in ALL_ATTRS:
        if get_attr_multiplier(a, normalized_self_types) == 1.0 and a not in normalized_enemy_types:
            normal_attr = a
            break
    c3 = _calc_dmg(normal_attr, 2.5)
    cases.append({
        "id": "normal_counter",
        "name": "不克制应对愿力",
        "tag": "非克制 · 应对×2.5",
        "desc": f"对方非克制愿力({normal_attr})应对我方状态技能 (1.0x × 2.5)",
        "attr": normal_attr,
        "dmg_min": c3["dmg_min"],
        "dmg_max": c3["dmg_max"],
        "is_lethal": c3["is_lethal"],
        "multiplier": 1.0,
        "counter_mult": 2.5,
        "badge": "1.0x 应对",
    })

    # 特殊情况：如果我方存在 3 倍双克制弱点
    if rep_3x_attr:
        c4 = _calc_dmg(rep_3x_attr, 1.0)
        cases.append({
            "id": "3x_no_counter",
            "name": "3倍极限克制不应对愿力",
            "tag": "3.0x 极限双克",
            "desc": f"对方针对我方双弱点的愿力({rep_3x_attr}) (3.0x)",
            "attr": rep_3x_attr,
            "dmg_min": c4["dmg_min"],
            "dmg_max": c4["dmg_max"],
            "is_lethal": c4["is_lethal"],
            "multiplier": 3.0,
            "counter_mult": 1.0,
            "badge": "3.0x 极限克制",
        })

    return {
        "success": True,
        "power": 80,
        "atk_stat_name": atk_stat_name,
        "likely_counter_attrs": likely_counter_attrs,
        "has_3x_weakness": bool(rep_3x_attr),
        "cases": cases,
    }