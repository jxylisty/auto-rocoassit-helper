# -*- coding: utf-8 -*-
"""
洛克王国 - 自动丢球工具
使用 interception 内核级硬件模拟，拟人化蓄力延迟
"""

import random
import time
import threading
import keyboard
import interception
import ctypes
from ctypes import wintypes

# Windows API 定义
user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.restype = ctypes.c_int

# 目标窗口信息
TARGET_WINDOW_TITLE = "洛克王国：世界"
TARGET_WINDOW_CLASS = "UnrealWindow"


class AutoThrowBall:
    """自动扔球工具"""

    def __init__(self):
        # 自动捕获设备
        interception.auto_capture_devices()

        # 蓄力参数
        self.base_charge_time = 0.8  # 期望蓄力时间
        self.std_charge_time = 0.05  # 标准差

        # 状态控制
        self.running = False
        self.thread = None

        print("Interception 设备初始化完成")

    def is_game_window_active(self):
        """检查游戏窗口是否在最前面"""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        # 获取窗口标题
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return False

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value

        # 检查标题是否包含目标
        return TARGET_WINDOW_TITLE in title

    def get_humanized_delay(self):
        """生成拟人化蓄力延迟"""
        # 正态分布生成延迟
        delay = random.gauss(self.base_charge_time, self.std_charge_time)

        # 安全截断，防止异常极值
        delay = max(0.6, delay)  # 最小0.6秒
        delay = min(1.0, delay)  # 最大1.0秒

        return delay

    def mouse_down(self):
        """模拟鼠标按下"""
        interception.mouse_down(button='left')

    def mouse_up(self):
        """模拟鼠标松开"""
        interception.mouse_up(button='left')

    def throw_ball(self):
        """执行单次扔球动作"""
        # 按下鼠标
        self.mouse_down()

        # 拟人化蓄力延迟
        charge_time = self.get_humanized_delay()
        time.sleep(charge_time)

        # 松开鼠标
        self.mouse_up()

    def throw_loop(self):
        """持续扔球循环"""
        while self.running:
            # 只有游戏窗口在最前面时才执行
            if self.is_game_window_active():
                self.throw_ball()
            else:
                print("游戏窗口不在最前面，跳过扔球")
            # 等待0.1秒，避免过快扔球
            # 每次循环短暂间隔
            time.sleep(0.1)

    def toggle(self):
        """切换运行状态"""
        if self.running:
            # 停止
            self.running = False
            print("\n[停止] 自动扔球已关闭")
        else:
            # 开始
            self.running = True
            self.thread = threading.Thread(target=self.throw_loop, daemon=True)
            self.thread.start()
            print("\n[开始] 自动扔球已启动")

    def start(self):
        """启动监听"""
        print("="*50)
        print("洛克王国 - 自动丢球工具")
        print("="*50)
        print("按 F8 开始/停止扔球")
        print("按 ESC 退出")
        print("="*50)

        # 注册快捷键
        keyboard.add_hotkey('f8', self.toggle)

        # 等待退出
        keyboard.wait('esc')

        # 确保停止
        self.running = False
        print("已退出")


if __name__ == "__main__":
    tool = AutoThrowBall()
    tool.start()