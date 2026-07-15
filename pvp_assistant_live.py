# -*- coding: utf-8 -*-
"""Stable right-docked helper panel."""

from __future__ import annotations

import ctypes
import json
import time
import tkinter as tk
from tkinter import ttk

import win32con

from src.analysis.vision_pipeline import VisionPipeline
from src.capture.screen_capture import ScreenRegionCapture
from src.capture.window_capture import WindowCapture, find_window
from src.utils.image_io import imwrite_unicode


HOTKEY_START_STOP = 1
HOTKEY_SAVE = 2
WM_HOTKEY = 0x0312


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_size_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


class LiveAssistantApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("洛克王国 PVP 助手")
        self.root.geometry("380x360+100+100")
        self.root.minsize(360, 320)
        self.root.attributes("-topmost", True)

        self.window_info = None
        self.capture_backend = None
        self.screen_backend = None
        self.current_frame = None
        self.pipeline = VisionPipeline()

        self.running = False
        self.after_job = None
        self.capture_mode = tk.StringVar(value="screen")
        self.dock_right = tk.BooleanVar(value=True)

        self.status_var = tk.StringVar(value="等待绑定游戏窗口")
        self.battle_var = tk.StringVar(value="待机")
        self.energy_var = tk.StringVar(value="-")
        self.damage_var = tk.StringVar(value="-")
        self.avatar_var = tk.StringVar(value="-")
        self.element_var = tk.StringVar(value="-")
        self.hint_var = tk.StringVar(value="先点击“刷新窗口”，再点击“开始”。")
        self.foreground_var = tk.StringVar(value="未知")

        self._build_ui()
        self._register_hotkeys()
        self.root.after(100, self._poll_hotkeys)
        self.root.after(300, self.refresh_window)

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(4, weight=1)

        top = tk.Frame(self.root)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        for col in range(4):
            top.grid_columnconfigure(col, weight=1)

        ttk.Button(top, text="刷新窗口", command=self.refresh_window).grid(row=0, column=0, padx=3, pady=3, sticky="ew")
        ttk.Button(top, text="开始", command=self.start).grid(row=0, column=1, padx=3, pady=3, sticky="ew")
        ttk.Button(top, text="停止", command=self.stop).grid(row=0, column=2, padx=3, pady=3, sticky="ew")
        ttk.Button(top, text="保存截图", command=self.save_screenshot).grid(row=0, column=3, padx=3, pady=3, sticky="ew")
        ttk.Button(top, text="切到游戏", command=self.focus_game).grid(row=1, column=0, columnspan=4, padx=3, pady=(3, 0), sticky="ew")

        bar = tk.Frame(self.root)
        bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        ttk.Checkbutton(bar, text="贴在游戏右侧", variable=self.dock_right, command=self._dock_to_game_right).pack(
            side="left", padx=(0, 12)
        )
        ttk.Label(bar, text="截图模式").pack(side="left")
        ttk.Combobox(
            bar,
            textvariable=self.capture_mode,
            values=("screen", "bitblt", "auto", "printwindow"),
            width=12,
            state="readonly",
        ).pack(side="left", padx=(6, 0))

        info = tk.LabelFrame(self.root, text="状态")
        info.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        info.grid_columnconfigure(1, weight=1)

        self._info_row(info, 0, "窗口", self.status_var)
        self._info_row(info, 1, "前台", self.foreground_var)
        self._info_row(info, 2, "战斗", self.battle_var)
        self._info_row(info, 3, "能量", self.energy_var)
        self._info_row(info, 4, "伤害", self.damage_var)
        self._info_row(info, 5, "头像", self.avatar_var)
        self._info_row(info, 6, "属性", self.element_var)

        hint = tk.Label(self.root, textvariable=self.hint_var, justify="left", anchor="w", wraplength=340)
        hint.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))

        hotkey_hint = tk.Label(
            self.root,
            text="热键：F8 保存截图  |  F9 开始/停止",
            justify="left",
            anchor="w",
            wraplength=340,
            fg="#666666",
        )
        hotkey_hint.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 6))

        self.raw_text = tk.Text(self.root, height=8)
        self.raw_text.grid(row=5, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.root.grid_rowconfigure(5, weight=1)

    def _info_row(self, parent, row: int, label: str, value_var: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(parent, textvariable=value_var).grid(row=row, column=1, sticky="w", padx=8, pady=4)

    def refresh_window(self) -> None:
        info = find_window(class_name="UnrealWindow") or find_window()
        if info is None:
            self.window_info = None
            self.capture_backend = None
            self.status_var.set("未找到")
            self.hint_var.set("请先把游戏开成窗口模式，再点刷新窗口。")
            return

        self.window_info = info
        self.capture_backend = WindowCapture(info.hwnd)
        self.screen_backend = ScreenRegionCapture(self.capture_backend.get_info)
        self.status_var.set(f"{info.width}x{info.height}")
        self.hint_var.set(f"已绑定：{info.title}")
        self._dock_to_game_right()

    def _register_hotkeys(self) -> None:
        user32 = ctypes.windll.user32
        ok_save = user32.RegisterHotKey(None, HOTKEY_SAVE, 0, win32con.VK_F8)
        ok_toggle = user32.RegisterHotKey(None, HOTKEY_START_STOP, 0, win32con.VK_F9)
        if not ok_save or not ok_toggle:
            self.hint_var.set("热键注册失败，F8/F9 可能不可用。")

    def _unregister_hotkeys(self) -> None:
        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(None, HOTKEY_SAVE)
        user32.UnregisterHotKey(None, HOTKEY_START_STOP)

    def _poll_hotkeys(self) -> None:
        msg = MSG()
        user32 = ctypes.windll.user32
        while user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, 1):
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_SAVE:
                    self.save_screenshot()
                elif msg.wParam == HOTKEY_START_STOP:
                    if self.running:
                        self.stop()
                    else:
                        self.start()
        self.root.after(100, self._poll_hotkeys)

    def _dock_to_game_right(self) -> None:
        if not self.dock_right.get() or self.window_info is None:
            return
        _, top, right, _ = self.window_info.rect
        panel_width = self.root.winfo_width() or 380
        screen_width = self.root.winfo_screenwidth()
        x = min(max(0, right + 8), max(0, screen_width - panel_width))
        y = max(0, top)
        self.root.geometry(f"+{x}+{y}")

    def start(self) -> None:
        if self.running:
            return
        if self.capture_backend is None:
            self.refresh_window()
        if self.capture_backend is None or self.screen_backend is None:
            self.hint_var.set("启动失败：没有找到游戏窗口。")
            return
        self.running = True
        self.hint_var.set("开始识别。")
        self._tick()

    def stop(self) -> None:
        self.running = False
        if self.after_job is not None:
            self.root.after_cancel(self.after_job)
            self.after_job = None
        self.hint_var.set("已停止。")

    def focus_game(self) -> None:
        if self.capture_backend is None:
            self.refresh_window()
        if self.capture_backend is None:
            self.hint_var.set("没有可切换的游戏窗口。")
            return
        try:
            self.capture_backend.bring_to_front()
            self.hint_var.set("已尝试切到游戏窗口。")
        except Exception as exc:
            self.hint_var.set(f"切换失败：{exc}")

    def _tick(self) -> None:
        if not self.running:
            return

        try:
            if self.capture_backend is None or self.screen_backend is None:
                raise RuntimeError("截图后端未初始化")

            self.window_info = self.capture_backend.get_info()
            self._dock_to_game_right()
            is_foreground = self.capture_backend.is_foreground()
            self.foreground_var.set("游戏在前台" if is_foreground else "已被其他窗口遮挡")

            if not is_foreground:
                self.raw_text.delete("1.0", "end")
                self.raw_text.insert(
                    "1.0",
                    json.dumps(
                        {
                            "warning": "当前前台不是游戏窗口，screen 模式会截到 VSCode/浏览器等遮挡内容。",
                            "action": "点击“切到游戏”，并保证游戏区域不要被其他窗口挡住。",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                self.hint_var.set("当前前台不是游戏窗口，已暂停识别。可直接按 F8 保存上一帧截图。")
                self.after_job = self.root.after(500, self._tick)
                return

            if self.capture_mode.get() == "screen":
                frame = self.screen_backend.capture()
            else:
                frame = self.capture_backend.capture(self.capture_mode.get())
            self.current_frame = frame

            battle_state = self.pipeline.battle_detector.detect(frame)
            configured = bool(battle_state["configured"])
            in_battle = bool(battle_state["in_battle"])

            if configured and in_battle:
                snapshot = self.pipeline.analyze(frame)
                self.battle_var.set("战斗中")
                self.energy_var.set(str(snapshot.current_energy.value))
                self.damage_var.set(str(snapshot.latest_damage.value))
                self.avatar_var.set(str(snapshot.enemy_avatar.value))
                self.element_var.set(str(snapshot.enemy_elements.value))
                self.raw_text.delete("1.0", "end")
                self.raw_text.insert("1.0", json.dumps(snapshot.raw, ensure_ascii=False, indent=2))
                interval = 200
            else:
                self.battle_var.set("待机")
                self.energy_var.set("-")
                self.damage_var.set("-")
                self.avatar_var.set("-")
                self.element_var.set("-")
                self.raw_text.delete("1.0", "end")
                self.raw_text.insert(
                    "1.0",
                    json.dumps(
                        {
                            "battle": battle_state,
                            "tip": "先准备 battle/left 和 battle/right 模板，战斗检测才会自动工作。",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                interval = 1000

        except Exception as exc:
            self.hint_var.set(f"截图失败：{exc}")
            interval = 1500

        self.after_job = self.root.after(interval, self._tick)

    def save_screenshot(self) -> None:
        if self.current_frame is None:
            self.hint_var.set("当前没有可保存的截图。")
            return
        filename = f"capture_{time.strftime('%Y%m%d_%H%M%S')}.png"
        if imwrite_unicode(filename, self.current_frame):
            self.hint_var.set(f"截图已保存：{filename}")
        else:
            self.hint_var.set("截图保存失败。")

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self._unregister_hotkeys()


if __name__ == "__main__":
    LiveAssistantApp().run()
