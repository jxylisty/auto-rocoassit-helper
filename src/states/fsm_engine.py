# -*- coding: utf-8 -*-
"""
有限状态机引擎 - 双号轮切状态管理
"""

from enum import Enum, auto
from typing import Callable, Dict, Optional


class GameState(Enum):
    """游戏状态枚举"""
    IDLE = auto()          # 空闲/待机
    BATTLE = auto()        # 战斗中
    SELECT_PET = auto()    # 选择精灵
    WAITING = auto()       # 等待匹配
    ERROR = auto()         # 异常状态


class FSMEngine:
    """有限状态机引擎"""

    def __init__(self):
        self.current_state = GameState.IDLE
        self.previous_state: Optional[GameState] = None
        self.transitions: Dict[GameState, Dict[GameState, Callable]] = {}

    def add_transition(self, from_state: GameState, to_state: GameState, callback: Callable):
        """添加状态转换"""
        if from_state not in self.transitions:
            self.transitions[from_state] = {}
        self.transitions[from_state][to_state] = callback

    def can_transition(self, to_state: GameState) -> bool:
        """检查是否可以转换到目标状态"""
        if self.current_state not in self.transitions:
            return False
        return to_state in self.transitions[self.current_state]

    def transition(self, to_state: GameState) -> bool:
        """执行状态转换"""
        if not self.can_transition(to_state):
            return False

        callback = self.transitions[self.current_state].get(to_state)
        if callback:
            callback()

        self.previous_state = self.current_state
        self.current_state = to_state
        return True

    def get_state(self) -> GameState:
        """获取当前状态"""
        return self.current_state


__all__ = ['GameState', 'FSMEngine']