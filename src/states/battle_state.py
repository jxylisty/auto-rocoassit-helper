# -*- coding: utf-8 -*-
"""
战斗状态管理
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PetInfo:
    """精灵信息"""
    name: str
    hp_percent: float
    level: int
    elements: list[str]


@dataclass
class BattleState:
    """战斗状态"""
    in_battle: bool = False
    my_pet: Optional[PetInfo] = None
    enemy_pet: Optional[PetInfo] = None
    turn_count: int = 0

    def update_my_pet(self, name: str, hp: float, level: int = 0, elements: list = None):
        """更新我方精灵信息"""
        self.my_pet = PetInfo(name, hp, level, elements or [])

    def update_enemy_pet(self, name: str, hp: float, level: int = 0, elements: list = None):
        """更新敌方精灵信息"""
        self.enemy_pet = PetInfo(name, hp, level, elements or [])

    def clear(self):
        """清除战斗状态"""
        self.in_battle = False
        self.my_pet = None
        self.enemy_pet = None
        self.turn_count = 0


__all__ = ['BattleState', 'PetInfo']