# -*- coding: utf-8 -*-
"""
鼠标控制器 - 基于 Interception 内核级驱动
"""

import interception


class MouseController:
    """鼠标控制器"""

    def __init__(self):
        interception.auto_capture_devices()

    def click(self, button: str = 'left', delay: float = 0.1):
        """点击鼠标"""
        interception.mouse_down(button=button)
        import time
        time.sleep(delay)
        interception.mouse_up(button=button)

    def move_to(self, x: int, y: int):
        """移动鼠标到指定位置"""
        interception.move_to(x, y)

    def move_relative(self, dx: int, dy: int):
        """相对移动鼠标"""
        interception.move_relative(dx, dy)

    def scroll(self, amount: int):
        """滚动鼠标滚轮"""
        interception.scroll(amount)


__all__ = ['MouseController']