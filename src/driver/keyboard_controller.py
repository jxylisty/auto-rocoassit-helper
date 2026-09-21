# -*- coding: utf-8 -*-
"""
键盘控制器 - 基于 Interception 内核级驱动
"""

import interception


class KeyboardController:
    """键盘控制器"""

    def __init__(self):
        # 设备号自动捕获: interception 需要知道键盘占用哪个设备号(1-10),
        # 不捕获时按键可能发到无效设备位而"静默无效"(Esc/按键游戏无反应)
        try:
            if not getattr(interception, "_devices_captured", False):
                interception.auto_capture_devices(keyboard=True, mouse=False)
                interception._devices_captured = True
        except Exception:
            pass  # 已捕获过或失败(用默认设备号), 不阻塞初始化

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