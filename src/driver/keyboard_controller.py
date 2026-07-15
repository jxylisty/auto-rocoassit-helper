# -*- coding: utf-8 -*-
"""
键盘控制器 - 基于 Interception 内核级驱动
"""

import interception


class KeyboardController:
    """键盘控制器"""

    def __init__(self):
        interception.auto_capture_devices()

    def press(self, key: str):
        """按下并释放按键"""
        interception.press(key)

    def key_down(self, key: str):
        """按下按键"""
        interception.key_down(key)

    def key_up(self, key: str):
        """释放按键"""
        interception.key_up(key)

    def type_text(self, text: str, interval: float = 0.05):
        """输入文本"""
        interception.write(text, interval=interval)


__all__ = ['KeyboardController']