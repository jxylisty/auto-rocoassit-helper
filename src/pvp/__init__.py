# -*- coding: utf-8 -*-
"""
PVP 对战助手模块

包含:
  - 伤害计算引擎 (damage_calculator)
  - 属性克制表 (type_chart)
  - 精灵数据加载 (pet_loader)
  - 技能数据加载 (skill_loader)
  - PVP 规则常量 (pvp_rules)
  - 精灵识别封装 (recognizer)
  - 游戏悬浮窗 (float_overlay)
"""

from .damage_calculator import (
    calculate_damage_full,
    calculate_panel_value,
    calculate_all_panels,
    calculate_full_panels,
    calc_pet_vs_pet,
    normalize_battle_skill,
    can_act_before_enemy,
    is_damage_skill,
)
from .type_chart import (
    get_attr_multiplier,
    normalize_attr,
    normalize_attr_list,
    get_strong_against,
    get_resist_against,
    get_weak_against,
    ALL_ATTRS,
    ATTR_COLORS,
    ATTR_LABELS,
)
from .pet_loader import (
    get_pet_count,
    get_pet_by_name,
    get_pet_by_title,
    get_pet_by_seq,
    get_all_forms,
    get_pet_race,
    get_pet_speed_race,
    get_pet_types,
    get_pet_skills,
    get_pet_trait,
    is_leader_form,
    search_pets,
    get_all_pet_names,
    pet_to_dict,
)
from .skill_loader import (
    get_skill,
    get_skill_power,
    get_skill_consume,
    get_skill_type,
    get_skill_attr,
    search_skills,
    get_all_skill_names,
    get_skill_count,
)
from .pvp_rules import PVP_RULES, LEVEL, STAR, NATURE, DAMAGE, DEFAULT_SCENARIO