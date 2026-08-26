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

    pre_nature_panel = math.floor(raw_panel)
    post_nature_panel = round(pre_nature_panel * nature_mod + 0.0000001)
    star_bonus = to_number(star, 0) * 20 if attr_key == "hp" else to_number(star, 0) * 10

    panel = post_nature_panel + star_bonus
    panel *= get_percent_buff_multiplier(attr_key, buffs)
    if attr_key == "speed":
        panel += to_number((buffs or {}).get("speedFlat", 0), 0)

    return panel


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

    damage = max(
        1.0,
        (atk_used / def_used)
        * 0.9
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
            "baseConstant": 0.9,
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