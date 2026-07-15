# -*- coding: utf-8 -*-
"""
洛克王国 PVP 伤害计算器

功能:
1. 计算精灵面板属性 (种族值 + 个体资质 + 性格 + 星级)
2. 计算伤害 (物攻/魔攻)
3. 个体资质预测 (基于PVP常见配置: 3项高资质7-10 + 3项低资质0)
4. 伤害反推 (根据伤害值反推对方资质)

作者: 洛克王国AI项目
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ============================================================================
# 常量配置
# ============================================================================

# 默认等级和星级
DEFAULT_LEVEL = 60      # 默认等级
DEFAULT_STAR = 5        # 默认星级

# 性格/星级加成
STAR_NATURE_BONUS = 0.20    # 性格/星级加成比例 (20%)
HP_STAR_BONUS = 20          # 星级对HP的固定加成
ATTR_STAR_BONUS = 10        # 星级对其他属性的固定加成

# 属性映射 (中文 -> 英文)
ATTR_MAP = {
    '生命': 'hp',
    '物攻': 'attack',
    '魔攻': 'mattack',
    '物防': 'defense',
    '魔防': 'mdefense',
    '速度': 'speed'
}

# 反向映射
ATTR_REVERSE_MAP = {v: k for k, v in ATTR_MAP.items()}

# 所有属性选项
ATTR_OPTIONS = [
    '火', '水', '草', '电', '冰', '虫', '翼', '地', 
    '萌', '武', '毒', '龙', '幽', '恶', '光', '幻', '普通', '机械'
]

# 属性克制表
# 格式: {攻击属性: {'strong': [克制属性列表], 'resist': [抵抗属性列表], 'weak': [弱点属性], 'vulnerable': [易伤属性]}}
TYPE_EFFECT_CHART = {
    '普通': {'strong': [], 'resist': ['地', '幽', '机械'], 'weak': ['武'], 'vulnerable': ['幽']},
    '草': {'strong': ['水', '光', '地'], 'resist': ['火', '龙', '毒', '虫', '翼', '机械'], 'weak': ['火', '冰', '毒', '虫', '翼'], 'vulnerable': ['水', '地', '电', '光']},
    '火': {'strong': ['草', '冰', '虫', '机械'], 'resist': ['水', '地', '龙'], 'weak': ['水', '地'], 'vulnerable': ['草', '冰', '虫', '萌', '机械']},
    '水': {'strong': ['火', '地', '机械'], 'resist': ['草', '冰', '龙'], 'weak': ['草', '电'], 'vulnerable': ['火', '机械']},
    '光': {'strong': ['幽', '恶'], 'resist': ['草', '冰'], 'weak': ['草', '幽'], 'vulnerable': ['恶', '幻']},
    '地': {'strong': ['火', '冰', '电', '毒'], 'resist': ['草', '武'], 'weak': ['草', '水', '冰', '武', '机械'], 'vulnerable': ['普通', '火', '电', '毒', '翼']},
    '冰': {'strong': ['草', '地', '龙', '翼'], 'resist': ['火', '冰', '机械'], 'weak': ['火', '地', '武', '机械'], 'vulnerable': ['水', '冰', '光']},
    '龙': {'strong': ['龙'], 'resist': ['机械'], 'weak': ['冰', '龙', '萌'], 'vulnerable': ['草', '火', '水', '电', '翼']},
    '电': {'strong': ['水', '翼'], 'resist': ['草', '地', '龙', '电'], 'weak': ['地'], 'vulnerable': ['电', '翼', '机械']},
    '毒': {'strong': ['草', '萌'], 'resist': ['地', '毒', '幽', '机械'], 'weak': ['地', '恶', '幻'], 'vulnerable': ['草', '毒', '虫', '武', '萌']},
    '虫': {'strong': ['草', '恶', '幻'], 'resist': ['火', '毒', '武', '翼', '萌', '幽', '机械'], 'weak': ['火', '翼'], 'vulnerable': ['草', '武']},
    '武': {'strong': ['普通', '地', '冰', '恶', '机械'], 'resist': ['毒', '虫', '翼', '萌', '幽', '幻'], 'weak': ['翼', '萌', '幻'], 'vulnerable': ['地', '虫', '恶']},
    '翼': {'strong': ['草', '虫', '武'], 'resist': ['地', '龙', '电', '机械'], 'weak': ['冰', '电'], 'vulnerable': ['草', '虫', '武']},
    '萌': {'strong': ['武', '毒', '幽'], 'resist': ['虫', '武', '萌', '恶'], 'weak': ['毒', '恶'], 'vulnerable': ['武', '萌']},
    '幽': {'strong': ['普通', '萌', '幽'], 'resist': ['普通', '毒', '虫', '武', '萌', '恶'], 'weak': ['光', '幽'], 'vulnerable': ['普通', '萌', '幽']},
    '恶': {'strong': ['萌', '幽'], 'resist': ['虫', '武', '萌', '恶', '幻'], 'weak': ['虫', '武', '光'], 'vulnerable': ['光', '恶']},
    '机械': {'strong': ['冰', '光', '幽'], 'resist': ['草', '冰', '虫', '翼', '萌', '恶'], 'weak': ['火', '水', '地', '武'], 'vulnerable': ['电', '机械']},
    '幻': {'strong': ['光', '萌'], 'resist': ['武', '萌', '恶'], 'weak': ['虫', '萌'], 'vulnerable': ['虫', '武', '恶']},
}


# ============================================================================
# 数据加载
# ============================================================================

def load_pet_data() -> Dict:
    """从pet_data_all.py加载所有精灵数据"""
    try:
        from backend.pet_data_all import PET_DATA
        return PET_DATA
    except ImportError:
        print("警告: 未找到pet_data_all.py，使用空数据")
        return {}


# 加载精灵数据
PET_DATA = load_pet_data()


def get_pet_by_id(pet_id: str) -> Optional[Dict]:
    """根据ID获取精灵数据"""
    return PET_DATA.get(str(pet_id))


def get_pet_by_name(name: str) -> Optional[Dict]:
    """根据名称获取精灵数据"""
    for pet_id, pet in PET_DATA.items():
        if pet.get('name') == name:
            return pet
    return None


def search_pets(keyword: str) -> List[Dict]:
    """搜索精灵"""
    results = []
    for pet_id, pet in PET_DATA.items():
        if keyword in pet.get('name', ''):
            results.append({'id': pet_id, **pet})
    return results


# ============================================================================
# 面板计算
# ============================================================================

def calculate_panel_value(
    race_value: int, 
    iv_value: int, 
    level: int, 
    star: int, 
    attr_key: str, 
    nature_up: Optional[str] = None, 
    nature_down: Optional[str] = None, 
    buffs: Optional[Dict] = None
) -> int:
    """
    计算单项目面板值
    
    公式说明:
    - 基础值 = 种族值 * 0.5 + 个体资质 * 0.25 + 10
    - 成长 = (种族值 + 个体资质 * 0.5) * 成长系数 + 基础成长
      - HP: 2% + 1
      - 其他: 1%
    - 面板 = 基础值 + 等级 * 成长
    - 性格修正: 提升项 * 1.2, 降低项 * 0.9
    - 星级加成: HP +20/星, 其他 +10/星
    - BUFF修正: 攻击/防御/魔攻/魔防的百分比修正
    
    参数:
        race_value: 种族值
        iv_value: 个体资质 (0-10)
        level: 等级
        star: 星级 (0-5)
        attr_key: 属性键 (hp/attack/mattack/defense/mdefense/speed)
        nature_up: 提升项属性中文名
        nature_down: 降低项属性中文名
        buffs: BUFF修正字典
    
    返回:
        面板值 (整数)
    """
    # 1. 基础值计算
    base = race_value * 0.5 + iv_value * 0.25 + 10
    
    # 2. 成长计算
    # HP: 2%种族值 + 1, 其他: 1%种族值
    if attr_key == 'hp':
        per_level_growth = (race_value + iv_value * 0.5) * 0.02 + 1
    else:
        per_level_growth = (race_value + iv_value * 0.5) * 0.01
    
    panel = base + level * per_level_growth
    
    # 3. 性格修正
    nature_mod = 1.0
    attr_name = ATTR_REVERSE_MAP.get(attr_key, '')
    if nature_up == attr_name:
        nature_mod = 1 + STAR_NATURE_BONUS  # 1.2
    elif nature_down == attr_name:
        nature_mod = 0.9
    
    panel *= nature_mod
    
    # 4. 星级加成
    if attr_key == 'hp':
        panel += star * HP_STAR_BONUS
    else:
        panel += star * ATTR_STAR_BONUS
    
    # 5. BUFF修正
    if buffs:
        if attr_key == 'attack':
            panel *= (1 + buffs.get('atk_buff', 0) / 100)
        elif attr_key == 'mattack':
            panel *= (1 + buffs.get('matk_buff', 0) / 100)
        elif attr_key == 'defense':
            panel *= (1 + buffs.get('def_buff', 0) / 100)
            panel *= (1 - buffs.get('def_debuff', 0) / 100)
        elif attr_key == 'mdefense':
            panel *= (1 + buffs.get('mdef_buff', 0) / 100)
            panel *= (1 - buffs.get('mdef_debuff', 0) / 100)
    
    return float(panel)  # 保留小数精度


def calculate_all_panels(
    pet_key: str, 
    iv_values: Dict[str, int], 
    level: int, 
    star: int, 
    nature_up: Optional[str], 
    nature_down: Optional[str], 
    buffs: Optional[Dict] = None
) -> Dict[str, int]:
    """
    计算精灵所有面板属性
    
    参数:
        pet_key: 精灵ID或键名
        iv_values: 个体资质字典, 如 {'hp': 10, 'attack': 7, ...}
        level: 等级
        star: 星级
        nature_up: 提升属性
        nature_down: 降低属性
        buffs: BUFF状态
    
    返回:
        面板属性字典
    """
    if pet_key not in PET_DATA:
        raise ValueError(f"未知精灵: {pet_key}, 请检查精灵ID是否正确")
    
    pet_info = PET_DATA[pet_key]
    race = pet_info['race']
    
    results = {}
    for attr_key in ['hp', 'attack', 'mattack', 'defense', 'mdefense', 'speed']:
        race_value = race[attr_key]
        
        # 个体资质: 实际值 = 输入值 * (星级 + 1)
        # 这是因为高星级宠物资质可以超过10
        iv_value = iv_values.get(attr_key, 0) * (star + 1)
        
        results[attr_key] = calculate_panel_value(
            race_value, iv_value, level, star, attr_key,
            nature_up, nature_down, buffs
        )
    
    return results


def calculate_default_panel(pet_key: str, level: int = DEFAULT_LEVEL, star: int = DEFAULT_STAR) -> Dict[str, int]:
    """
    计算精灵默认面板 (PVP标准配置)
    
    PVP标准配置:
    - 3项高资质: 7-10 (取平均值8)
    - 3项低资质: 0
    - 性格: 无 (中性)
    - 无BUFF
    
    参数:
        pet_key: 精灵ID
        level: 等级
        star: 星级
    
    返回:
        面板属性字典
    """
    if pet_key not in PET_DATA:
        raise ValueError(f"未知精灵: {pet_key}")
    
    # 根据种族值判断哪3项应该是高资质
    # 通常: 输出种族值最高的3项为高资质, 其他为0
    pet_info = PET_DATA[pet_key]
    race = pet_info['race']
    
    # 排序获取最高的3项
    sorted_attrs = sorted(race.items(), key=lambda x: x[1], reverse=True)
    high_attrs = [sorted_attrs[0][0], sorted_attrs[1][0], sorted_attrs[2][0]]  # 前3项
    
    # 构建资质字典
    iv_values = {}
    for attr in ['hp', 'attack', 'mattack', 'defense', 'mdefense', 'speed']:
        if attr in high_attrs:
            iv_values[attr] = 8  # 高资质取8 (7-10的平均值)
        else:
            iv_values[attr] = 0  # 低资质为0
    
    return calculate_all_panels(pet_key, iv_values, level, star, None, None, None)


def calculate_panel_range(pet_key: str, level: int = DEFAULT_LEVEL, star: int = DEFAULT_STAR) -> Dict[str, Tuple[int, int]]:
    """
    计算精灵面板属性范围 (性格+资质未知)
    
    简化: 只计算边界
    - 最小: 0资质 + 降低性格
    - 最大: 10资质 + 提升性格
    
    返回:
        {属性: (最小值, 最大值)}
    """
    if pet_key not in PET_DATA:
        raise ValueError(f"未知精灵: {pet_key}")
    
    attrs = ['hp', 'attack', 'mattack', 'defense', 'mdefense', 'speed']
    
    # 最小面板: 0资质, 全部降低性格
    min_iv = {a: 0 for a in attrs}
    min_panel = calculate_all_panels(pet_key, min_iv, level, star, None, 'speed', None)
    
    # 最大面板: 10资质, 全部提升性格
    max_iv = {a: 10 for a in attrs}
    max_panel = calculate_all_panels(pet_key, max_iv, level, star, 'attack', None, None)
    
    results = {}
    for attr in attrs:
        results[attr] = (int(min_panel[attr]), int(max_panel[attr]))
    
    return results


# ============================================================================
# 伤害计算
# ============================================================================

def calculate_damage_simple(
    skill_power: int, 
    power_buff: float = 1.0, 
    weather_mod: float = 1.0, 
    defense_reduction: float = 0.0, 
    hits: int = 1
) -> int:
    """
    简化伤害计算 (仅考虑技能威力)
    
    用于粗略估算伤害
    
    参数:
        skill_power: 技能威力
        power_buff: 威力加成 (如 1.5 表示150%)
        weather_mod: 天气修正
        defense_reduction: 防御减伤 (0-1)
        hits: 攻击次数
    
    返回:
        伤害值
    """
    base_damage = skill_power * power_buff * weather_mod
    base_damage = max(1, base_damage)
    total_damage = base_damage * hits
    total_damage = total_damage * (1 - defense_reduction)
    return float(total_damage)


def calculate_damage_full(
    attacker_panel: Dict[str, int], 
    defender_panel: Dict[str, int], 
    skill_power: int, 
    skill_type: str, 
    skill_attr: str,
    defender_attrs: List[str],
    attacker_attrs: List[str] = None,
    power_buff: float = 1.0, 
    weather_mod: float = 1.0, 
    defense_reduction: float = 0.0,
    atk_level: int = 0, 
    def_level: int = 0, 
    hits: int = 1
) -> int:
    """
    完整伤害计算公式
    
    公式:
    伤害 = (攻击/防御) * 0.9 * 威力 * 威力BUFF * 属性一致加成(1.25) 
          * 属性克制 * 等级修正 * 天气修正 * 次数 * (1 - 防御减伤)
    
    参数:
        attacker_panel: 攻击方面板
        defender_panel: 防御方面板
        skill_power: 技能威力
        skill_type: 技能类型 ('物攻' 或 '魔攻')
        skill_attr: 技能属性
        pet_attrs: 精灵属性列表
        power_buff: 威力加成
        weather_mod: 天气修正
        defense_reduction: 防御减伤 (0-1)
        atk_level: 攻击方等级修正 (如 +6阶级 = +100%)
        def_level: 防御方等级修正
        hits: 攻击次数
    
    返回:
        伤害值
    """
    # 1. 选择攻击/防御属性
    if skill_type == '物攻':
        atk = attacker_panel['attack']
        defense = defender_panel['defense']
    else:  # 魔攻
        atk = attacker_panel['mattack']
        defense = defender_panel['mdefense']
    
    # 2. 属性一致加成 (STAB) - 用攻击方属性判断
    if attacker_attrs is None:
        attacker_attrs = defender_attrs  # 兼容旧代码
    same_type_bonus = 1.25 if skill_attr in attacker_attrs else 1.0
    
    # 3. 属性克制 - 用防御方属性判断
    attr_multiplier = get_attr_multiplier(skill_attr, defender_attrs)
    
    # 4. 等级修正
    # 阶级每级+10%, +6级=+60%
    # 基础为1.0，无阶级加成时
    level_mod = 1.0 *(1+atk_level / 10.0) *(1+def_level / 10.0)
    
    # 5. 计算伤害
    base_damage = (atk / defense) * 0.9 * skill_power * power_buff * same_type_bonus * attr_multiplier * level_mod * weather_mod
    base_damage = max(1, base_damage)  # 最低1点伤害
    
    # 6. 次数修正
    total_damage = base_damage * hits
    
    # 7. 防御减伤
    total_damage = total_damage * (1 - defense_reduction)
    
    return float(total_damage)  # 保留小数精度


def get_attr_multiplier(attack_attr: str, defense_attrs: List[str]) -> float:
    """
    计算属性克制倍率
    
    考虑双属性精灵的情况:
    - 双重克制 = 3倍伤害
    - 双重抵抗 = 1/3倍伤害
    - 克制+抵抗 = 正常 (1倍)
    
    参数:
        attack_attr: 攻击属性 (如 '火', '火系')
        defense_attrs: 防御方属性列表 (如 ['草'], ['草系', '水'])
    
    返回:
        伤害倍率 (0=无效, 0.5=减半, 1=正常, 2=加倍, 3=双重克制)
    """
    if not defense_attrs:
        return 1.0
    
    # 清理属性名称 (去掉"系"字)
    attack_attr_clean = attack_attr.replace('系', '')
    
    if attack_attr_clean not in TYPE_EFFECT_CHART:
        return 1.0
    
    effects = TYPE_EFFECT_CHART[attack_attr_clean]
    strong_list = effects.get('strong', [])      # 克制属性
    resist_list = effects.get('resist', [])      # 抵抗属性
    
    # 统计克制和抵抗的属性数量
    strong_count = 0
    resist_count = 0
    
    for def_attr in defense_attrs:
        def_attr_clean = def_attr.replace('系', '')
        if def_attr_clean in strong_list:
            strong_count += 1
        elif def_attr_clean in resist_list:
            resist_count += 1
    
    # 计算最终倍率
    if strong_count == 2:
        return 3.0      # 双重克制
    elif resist_count == 2:
        return 1/3      # 双重抵抗
    elif strong_count == 1 and resist_count == 0:
        return 2.0      # 克制
    elif resist_count == 1 and strong_count == 0:
        return 0.5      # 抵抗
    else:
        return 1.0     # 正常


def can_one_shot(damage: int, defender_hp: int) -> bool:
    """判断是否能够一击秒杀"""
    return damage >= defender_hp


# ============================================================================
# 个体资质预测 (AI核心)
# ============================================================================

def predict_iv_distribution(pet_key: str, observed_damage: int, skill_power: int, 
                            skill_type: str, skill_attr: str, my_panel: Dict,
                            level: int = DEFAULT_LEVEL, star: int = DEFAULT_STAR) -> Dict:
    """
    根据观察到的伤害反推对方资质分布
    
    PVP常见配置:
    - 3项高资质: 7-10 (优质PVP宠物)
    - 3项低资质: 0 (不浪费资源)
    - 性格: 提升主输出属性
    
    参数:
        pet_key: 对方精灵ID
        observed_damage: 观察到的伤害值
        skill_power: 使用的技能威力
        skill_type: 技能类型 (物攻/魔攻)
        skill_attr: 技能属性
        my_panel: 我方攻击面板
        level: 等级
        star: 星级
    
    返回:
        预测的资质分布和概率
    """
    if pet_key not in PET_DATA:
        return {'error': f'未知精灵: {pet_key}'}
    
    pet_info = PET_DATA[pet_key]
    race = pet_info['race']
    
    # 尝试不同的资质组合
    candidates = []
    
    # 资质范围: 0-10
    iv_options = [0, 5, 7, 8, 9, 10]
    
    # 生成所有可能的资质组合
    # 简化: 假设3项高(7-10), 3项低(0-3)
    from itertools import product
    
    for high_ivs in product(iv_options, repeat=3):
        for low_ivs in [0, 1, 2, 3]:
            # 构造资质字典 - 高资质对应种族值最高的三项
            sorted_attrs = sorted(race.items(), key=lambda x: x[1], reverse=True)
            high_attrs = [sorted_attrs[0][0], sorted_attrs[1][0], sorted_attrs[2][0]]
            
            iv_values = {}
            for i, attr in enumerate(['hp', 'attack', 'mattack', 'defense', 'mdefense', 'speed']):
                if attr in high_attrs:
                    # 找到在高资质属性中的索引
                    idx = high_attrs.index(attr)
                    iv_values[attr] = high_ivs[idx]
                else:
                    iv_values[attr] = low_ivs
            
            # 计算对方防御面板
            def_panel = calculate_all_panels(pet_key, iv_values, level, star, None, None)
            
            # 计算伤害
            pet_attrs = pet_info.get('attrs', [])
            calc_damage = calculate_damage_full(
                my_panel, def_panel, skill_power, skill_type, skill_attr,
                defender_attrs=pet_attrs, attacker_attrs=None,
                power_buff=1.0, weather_mod=1.0, defense_reduction=0.0,
                atk_level=0, def_level=0, hits=1
            )
            
            # 计算误差
            error = abs(calc_damage - observed_damage)
            
            candidates.append({
                'iv_values': iv_values,
                'def_panel': def_panel,
                'calc_damage': calc_damage,
                'error': error
            })
    
    # 按误差排序，取最佳匹配
    candidates.sort(key=lambda x: x['error'])
    
    # 返回最佳3个候选
    return {
        'pet': pet_info['name'],
        'observed_damage': observed_damage,
        'best_candidates': candidates[:3]
    }


def analyze_threat(pet_key: str, my_panel: Dict, skill_power: int,
                   skill_type: str, skill_attr: str, my_hp: int,
                   level: int = DEFAULT_LEVEL, star: int = DEFAULT_STAR) -> Dict:
    """
    分析对方精灵对我方的威胁程度
    
    参数:
        pet_key: 对方精灵ID
        my_panel: 我方面板
        skill_power: 对方技能威力
        skill_type: 技能类型
        skill_attr: 技能属性
        my_hp: 我方当前HP
        level: 等级
        star: 星级
    
    返回:
        威胁分析结果
    """
    if pet_key not in PET_DATA:
        return {'error': f'未知精灵: {pet_key}'}
    
    pet_info = PET_DATA[pet_key]
    race = pet_info['race']
    
    # 使用默认资质分布计算
    def_panel = calculate_default_panel(pet_key, level, star)
    pet_attrs = pet_info.get('attrs', [])
    
    # 计算对方可能的伤害范围
    min_damage = calculate_damage_full(
        def_panel, my_panel, skill_power, skill_type, skill_attr,
        pet_attrs, 0.8, 1.0, 0.0, 0, 0, 1
    )
    
    max_damage = calculate_damage_full(
        def_panel, my_panel, skill_power, skill_type, skill_attr,
        pet_attrs, 1.5, 1.0, 0.0, 0, 0, 1
    )
    
    avg_damage = calculate_damage_full(
        def_panel, my_panel, skill_power, skill_type, skill_attr,
        pet_attrs, 1.0, 1.0, 0.0, 0, 0, 1
    )
    
    # 判断威胁等级
    if max_damage >= my_hp:
        threat_level = '秒杀'
    elif avg_damage >= my_hp * 0.7:
        threat_level = '高危'
    elif avg_damage >= my_hp * 0.4:
        threat_level = '中等'
    elif min_damage >= my_hp * 0.2:
        threat_level = '低'
    else:
        threat_level = '安全'
    
    return {
        'pet': pet_info['name'],
        'damage_range': {'min': min_damage, 'avg': avg_damage, 'max': max_damage},
        'my_hp': my_hp,
        'can_one_shot': max_damage >= my_hp,
        'threat_level': threat_level,
        'def_panel': def_panel
    }


# ============================================================================
# 工具函数
# ============================================================================

def format_panel_result(panel: Dict[str, int]) -> Dict:
    """格式化面板结果"""
    return {
        'hp': panel['hp'],
        'attack': panel['attack'],
        'mattack': panel['mattack'],
        'defense': panel['defense'],
        'mdefense': panel['mdefense'],
        'speed': panel['speed']
    }


def print_panel(panel: Dict[str, int], name: str = "面板"):
    """打印面板属性"""
    print(f"\n=== {name} ===")
    print(f"生命(HP):   {panel['hp']}")
    print(f"物攻:       {panel['attack']}")
    print(f"魔攻:       {panel['mattack']}")
    print(f"物防:       {panel['defense']}")
    print(f"魔防:       {panel['mdefense']}")
    print(f"速度:       {panel['speed']}")


def print_damage_result(damage: int, attacker: str, defender: str):
    """打印伤害结果"""
    print(f"\n{attacker} → {defender}: {damage} 伤害")


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == '__main__':
    print("=" * 50)
    print("洛克王国 PVP 伤害计算器测试")
    print("=" * 50)
    
    # 测试1: 迪莫默认面板
    print("\n【测试1】迪莫默认面板 (PVP标准配置)")
    dimo_panel = calculate_default_panel('1', level=60, star=5)
    print_panel(dimo_panel, "迪莫 (ID:1)")
    
    # 测试2: 自定义资质
    print("\n【测试2】迪莫自定义资质")
    custom_iv = {'hp': 10, 'attack': 10, 'mattack': 0, 'defense': 10, 'mdefense': 0, 'speed': 0}
    dimo_custom = calculate_all_panels('1', custom_iv, 60, 5, '生命', '速度')
    print_panel(dimo_custom, "迪莫 (满攻速)")
    
    # 测试3: 伤害计算
    print("\n【测试3】伤害计算")
    print(f"假设对方防御面板: {dimo_panel}")
    damage = calculate_damage_full(
        dimo_panel, dimo_panel, 65, '物攻', '普通', ['光'],
        1.0, 1.0, 0.0, 0, 0, 1
    )
    print_damage_result(damage, "迪莫", "迪莫")
    
    # 测试4: 属性克制
    print("\n【测试4】属性克制")
    mult = get_attr_multiplier('火', ['草'])
    print(f"火 攻击 草: {mult}x (克制)")
    
    mult = get_attr_multiplier('水', ['火'])
    print(f"水 攻击 火: {mult}x (克制)")
    
    mult = get_attr_multiplier('火', ['草', '水'])  # 草系是火系克制的，水系被火系抵抗
    print(f"火 攻击 草+水: {mult}x (正常，克制+抵抗)")
    
    # 测试5: 威胁分析
    print("\n【测试5】威胁分析")
    threat = analyze_threat('1', dimo_panel, 65, '物攻', '普通', dimo_panel['hp'])
    print(f"威胁等级: {threat['threat_level']}")
    print(f"伤害范围: {threat['damage_range']}")
    print(f"能否秒杀: {threat['can_one_shot']}")
    
    print("\n" + "=" * 50)
    print("测试完成!")
    print("=" * 50)
