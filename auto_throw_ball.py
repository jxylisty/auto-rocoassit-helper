# -*- coding: utf-8 -*-
"""
洛克王国 - 自动丢球工具
使用 interception 内核级硬件模拟，拟人化蓄力延迟

所有延迟参数均为实例属性，可在运行中动态调整（GUI / 外部调用）。
命令行运行: python auto_throw_ball.py
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

    def __init__(self, on_log=None):
        # 日志回调（GUI 注入），为 None 时仅 print
        self.on_log = on_log

        # 自动捕获设备
        try:
            interception.auto_capture_devices()
            self._log("Interception 设备初始化完成", "success")
        except Exception as e:
            self._log(f"Interception 初始化失败: {e}", "error")

        # 可调延迟参数（秒），GUI 可运行中修改
        self.normal_min = 0.5          # 普通模式蓄力下限
        self.normal_max = 0.8          # 普通模式蓄力上限
        self.bomber_charge_min = 0.3   # 轰炸机蓄力下限
        self.bomber_charge_max = 0.5   # 轰炸机蓄力上限
        self.bomber_hover_min = 2.0    # 悬浮按键间隔下限
        self.bomber_hover_max = 2.2    # 悬浮按键间隔上限
        self.skill_min = 1.0           # 技能按键间隔下限
        self.skill_max = 2.0           # 技能按键间隔上限

        # 计数器（GUI 展示用）
        self.normal_count = 0
        self.bomber_count = 0
        self.skill_count = 0

        # 状态控制（普通模式）
        self.running = False
        self.thread = None

        # 状态控制（轰炸机模式）
        self.bomber_running = False
        self.bomber_thread = None

        # 状态控制（技能模式）
        self.skill_running = False
        self.skill_thread = None

        # "窗口不在前台"只提醒一次，避免刷屏
        self._inactive_warned = False

    def _log(self, message, level="info"):
        """输出日志：print + 可选回调"""
        print(message)
        if self.on_log:
            try:
                self.on_log(message, level)
            except Exception:
                pass

    def is_game_window_active(self):
        """检查游戏窗口是否在最前面（纯查询，无副作用）"""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return False

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)

        return TARGET_WINDOW_TITLE in buffer.value

    def _check_active_or_warn(self):
        """检查窗口前台状态，非前台时只警告一次"""
        if self.is_game_window_active():
            if self._inactive_warned:
                self._inactive_warned = False
                self._log("游戏窗口已回到前台，继续执行", "success")
            return True
        if not self._inactive_warned:
            self._inactive_warned = True
            self._log("游戏窗口不在最前面，暂停执行…", "warning")
        return False

    def get_humanized_delay(self):
        """普通模式蓄力延迟（正态分布，截断在 normal_min ~ normal_max）"""
        return self.get_delay_zt(self.normal_min, self.normal_max)

    def get_delay_zt(self, l, r):
        """
        生成正态分布延迟

        均值: (l+r)/2
        标准差: 由 l/r 推导
        范围: l - r 秒
        """
        mean = (l + r) / 2
        std = (r ** 2 + l ** 2 - mean ** 2) ** 0.5
        delay = random.gauss(mean, std)
        delay = max(l, delay)
        delay = min(r, delay)
        return delay

    def mouse_down(self):
        """模拟鼠标按下"""
        interception.mouse_down(button='left')

    def mouse_up(self):
        """模拟鼠标松开"""
        interception.mouse_up(button='left')

    def throw_ball(self):
        """执行单次扔球动作"""
        self.mouse_down()
        time.sleep(self.get_humanized_delay())
        self.mouse_up()

    def throw_loop(self):
        """持续扔球循环"""
        while self.running:
            if self._check_active_or_warn():
                self.throw_ball()
                self.normal_count += 1
            time.sleep(0.1)

    def toggle(self):
        """切换普通模式运行状态"""
        if self.running:
            self.running = False
            self._log("[停止] 自动扔球已关闭", "warning")
            return False
        else:
            self.running = True
            self._inactive_warned = False
            self.thread = threading.Thread(target=self.throw_loop, daemon=True)
            self.thread.start()
            self._log("[开始] 自动扔球已启动", "success")
            return True

    def bomber_loop(self):
        """
        轰炸机丢球循环 - 悬浮+轰炸模式

        1. 空格双击起飞
        2. 每 hover_min~hover_max 秒按一次空格保持高度
        3. 持续蓄力丢球（charge_min~charge_max 秒）
        """
        from src.driver import human_input
        self._log("[轰炸机] 双击空格起飞！", "info")
        human_input.press('space')
        time.sleep(0.05)
        human_input.press('space')
        time.sleep(0.3)

        last_hover_time = time.time()

        while self.bomber_running:
            if not self._check_active_or_warn():
                time.sleep(0.1)
                continue

            current_time = time.time()

            # 按悬浮间隔按空格保持高度
            hover_interval = self.get_delay_zt(self.bomber_hover_min, self.bomber_hover_max)
            if current_time - last_hover_time >= hover_interval:
                human_input.press('space')
                last_hover_time = current_time

            time.sleep(0.05)

            # 快速蓄力丢球
            interception.mouse_down(button='left')
            time.sleep(self.get_delay_zt(self.bomber_charge_min, self.bomber_charge_max))
            interception.mouse_up(button='left')
            self.bomber_count += 1

    def toggle_bomber(self):
        """切换轰炸机模式运行状态"""
        if self.bomber_running:
            self.bomber_running = False
            self._log("[停止] 轰炸机丢球已关闭", "warning")
            return False
        else:
            self.bomber_running = True
            self._inactive_warned = False
            self.bomber_thread = threading.Thread(target=self.bomber_loop, daemon=True)
            self.bomber_thread.start()
            self._log("[开始] 轰炸机丢球已启动", "success")
            return True

    def skill_loop(self):
        """
        技能循环 - 自动按技能

        交替按数字 3 / 字母 X，间隔 skill_min ~ skill_max 秒
        """
        self._log("[技能] 自动技能已启动（交替按 3 和 X）", "info")
        from src.driver import human_input

        while self.skill_running:
            if not self._check_active_or_warn():
                time.sleep(0.1)
                continue

            human_input.press('3')
            self.skill_count += 1
            time.sleep(self.get_delay_zt(self.skill_min, self.skill_max))

            if not self.skill_running:
                break

            human_input.press('x')
            self.skill_count += 1
            time.sleep(self.get_delay_zt(self.skill_min, self.skill_max))

    def toggle_skill(self):
        """切换技能模式运行状态"""
        if self.skill_running:
            self.skill_running = False
            self._log("[停止] 自动技能已关闭", "warning")
            return False
        else:
            self.skill_running = True
            self._inactive_warned = False
            self.skill_thread = threading.Thread(target=self.skill_loop, daemon=True)
            self.skill_thread.start()
            self._log("[开始] 自动技能已启动", "success")
            return True

    def stop_all(self):
        """停止全部模式"""
        was_running = self.running or self.bomber_running or self.skill_running
        self.running = False
        self.bomber_running = False
        self.skill_running = False
        if was_running:
            self._log("已停止全部模式", "warning")

    def register_hotkeys(self):
        """注册模式切换快捷键(不阻塞)"""
        keyboard.add_hotkey('f4', self.toggle)
        keyboard.add_hotkey('f9', self.toggle_bomber)
        keyboard.add_hotkey('f10', self.toggle_skill)
        self._log("快捷键已注册: F4 普通丢球 / F9 轰炸机 / F10 技能", "info")

    def start(self):
        """命令行模式：注册快捷键并等待 ESC 退出"""
        print("=" * 50)
        print("洛克王国 - 自动丢球工具")
        print("=" * 50)
        print("按 F4 开始/停止普通扔球")
        print("按 F9 开始/停止轰炸机扔球（悬浮+轰炸）")
        print("按 F10 开始/停止自动技能（交替按3和X）")
        print("按 ESC 退出")
        print("=" * 50)

        self.register_hotkeys()
        keyboard.wait('esc')
        self.stop_all()
        print("已退出")


if __name__ == "__main__":
    tool = AutoThrowBall()
    tool.start()
