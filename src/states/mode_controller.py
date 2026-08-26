# -*- coding: utf-8 -*-
"""模式控制器 — 统一管理挂机/丢球/PVP 模式的生命周期与浮窗"""

import threading
from typing import Optional, Dict, Any, Callable, List


class ModeController:
    """模式状态机：激活/切换/清理
    
    模式定义:
        idle  → 无浮窗, 无线程
        afk   → F2 挂机窗, 点击循环 + 战斗引擎
        throw → 无浮窗, 丢球子模块
        pvp   → F12 PVP窗, 视觉分析流水线
    """

    MODES = {
        "idle": {"label": "空闲", "float_windows": [], "threads": []},
        "afk": {"label": "挂机引擎", "float_windows": ["widget"],
                "threads": ["engine", "clicker"]},
        "throw": {"label": "丢球助手", "float_windows": [],
                   "threads": ["throw_ball"]},
        "pvp": {"label": "PVP对战", "float_windows": ["pvp_float"],
                "threads": ["vision", "recognizer"]},
    }

    def __init__(self):
        self._current_mode = "idle"
        self._threads: Dict[str, threading.Thread] = {}
        self._stop_events: Dict[str, threading.Event] = {}
        self._float_visible: Dict[str, bool] = {}
        self._on_mode_change: List[Callable] = []
        self._lock = threading.Lock()

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @property
    def mode_label(self) -> str:
        return self.MODES.get(self._current_mode, {}).get("label", "未知")

    def on_mode_change(self, callback: Callable):
        """注册模式切换回调"""
        self._on_mode_change.append(callback)

    def switch_to(self, mode: str) -> Dict[str, Any]:
        """切换到指定模式"""
        if mode not in self.MODES:
            return {"success": False, "message": f"未知模式: {mode}"}

        with self._lock:
            if mode == self._current_mode:
                return {"success": True, "message": f"已在 {self.MODES[mode]['label']} 模式"}

            old_mode = self._current_mode
            self._current_mode = mode

            # 停止旧模式的线程
            self._stop_threads(old_mode)

            # 通知回调
            for cb in self._on_mode_change:
                try:
                    cb(old_mode, mode)
                except Exception:
                    pass

            return {"success": True, "message": f"已切换到 {self.MODES[mode]['label']}",
                    "from": old_mode, "to": mode}

    def get_float_window(self, window_name: str) -> Optional[str]:
        """获取当前模式应激活的浮窗"""
        mode_info = self.MODES.get(self._current_mode, {})
        windows = mode_info.get("float_windows", [])
        return window_name if window_name in windows else None

    def should_run_thread(self, thread_name: str) -> bool:
        """判断线程是否应在当前模式运行"""
        mode_info = self.MODES.get(self._current_mode, {})
        return thread_name in mode_info.get("threads", [])

    def start_thread(self, name: str, target: Callable, daemon: bool = True):
        """启动模式线程（自动管理生命周期）"""
        if not self.should_run_thread(name):
            return
        self._stop_events[name] = threading.Event()
        t = threading.Thread(target=target, args=(self._stop_events[name],),
                             daemon=daemon, name=f"mode_{name}")
        self._threads[name] = t
        t.start()

    def stop_thread(self, name: str):
        """停止指定线程"""
        ev = self._stop_events.get(name)
        if ev:
            ev.set()
        t = self._threads.pop(name, None)
        if t and t.is_alive():
            t.join(timeout=2.0)

    def _stop_threads(self, mode: str):
        """停止某模式的所有线程"""
        mode_info = self.MODES.get(mode, {})
        for name in mode_info.get("threads", []):
            self.stop_thread(name)

    def stop_all(self):
        """停止所有线程"""
        for name in list(self._threads.keys()):
            self.stop_thread(name)

    def set_float_visible(self, window_name: str, visible: bool):
        self._float_visible[window_name] = visible

    def get_float_visible(self, window_name: str) -> bool:
        return self._float_visible.get(window_name, False)