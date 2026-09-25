"""AppBridge Mix-in —— 进程关闭与日志推送 / 模式切换协调 / 丢球配置 / 应用模式与总状态"""

import json
import os
import queue
import threading
import time
from pathlib import Path
from src.gui.bridge_common import CONFIG_DIR, CONFIG_SCHEMA, CONFIG_PAIRS, DEV_MODE


class RuntimeMixin:


    def close(self):
        """窗口关闭时自动持久化所有配置并清理资源"""
        self._stop_event.set()
        self.local_api_stop()
        try:
            self.updater.stop()
        except Exception:
            pass
        self._live_running = False

        # 自动保存丢球延时配置
        try:
            self._save_throw_config()
        except Exception:
            pass

        # 自动保存挂机引擎配置
        if hasattr(self, "_last_engine_params") and self._last_engine_params:
            try:
                self._save_engine_settings(self._last_engine_params)
            except Exception:
                pass

        # 关闭抓图线程和 FastCapture
        if self._fast_cap:
            self._fast_cap.close()
            self._fast_cap = None
        try:
            self._collector_stop.set()
        except Exception:
            pass
        try:
            self.engine.stop("窗口关闭")
        except Exception:
            pass
        try:
            self.tool.stop_all()
        except Exception:
            pass
        for tool_id in list(self._tool_procs):
            self._kill_tool(tool_id)
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass

        # 兜底强退: keyboard/RapidOCR 等库的线程可能残留导致进程僵死,
        # 残留实例会锁 WebView2 用户数据目录 → 下次启动随机失败(现象就是"时好时坏")
        def _force_exit():
            time.sleep(0.5)   # 给 pywebview 一点收尾时间
            os._exit(0)
        threading.Thread(target=_force_exit, daemon=True).start()

    shutdown = close

    # ========================================
    # 日志推送
    # ========================================

    def _enqueue_log(self, message, level="info"):
        self._log_queue.put((str(message), level))

    def _start_log_pusher(self):
        if self._pusher_thread and self._pusher_thread.is_alive():
            return

        def _pusher_loop():
            while not self._stop_event.is_set():
                try:
                    message, level = self._log_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if not self._window:
                    continue
                try:
                    js = f"addLog({json.dumps(message, ensure_ascii=False)}, {json.dumps(level)})"
                    self._window.evaluate_js(js)
                except Exception:
                    pass

        self._pusher_thread = threading.Thread(target=_pusher_loop, daemon=True, name="LogPusher")
        self._pusher_thread.start()


    # ========================================
    # 1. 丢球工具 API
    # ========================================

    def toggle_normal(self) -> dict:
        will_start = not self.tool.running
        auto_stopped = self._stop_conflicting_modes("throw") if will_start else []
        running = self.tool.toggle()
        if running:
            self.auto_minimize_and_show_widget()
        return {"success": True, "running": running, "auto_stopped": auto_stopped}

    def toggle_bomber(self) -> dict:
        will_start = not self.tool.bomber_running
        auto_stopped = self._stop_conflicting_modes("throw") if will_start else []
        running = self.tool.toggle_bomber()
        if running:
            self.auto_minimize_and_show_widget()
        return {"success": True, "running": running, "auto_stopped": auto_stopped}

    def toggle_skill(self) -> dict:
        will_start = not self.tool.skill_running
        auto_stopped = self._stop_conflicting_modes("throw") if will_start else []
        running = self.tool.toggle_skill()
        if running:
            self.auto_minimize_and_show_widget()
        return {"success": True, "running": running, "auto_stopped": auto_stopped}

    # 模式互斥: 丢球(三种模式可共存) / 挂机引擎 / PVP识别 三组之间互斥
    # 启动任一组时自动停止其它组,返回被停止的组名列表供前端 Toast 提示
    def _stop_conflicting_modes(self, starter: str) -> list:
        stopped = []
        if starter != "throw":
            running_names = [name for flag, name in (
                (self.tool.running, "普通丢球"),
                (self.tool.bomber_running, "轰炸机模式"),
                (self.tool.skill_running, "自动技能"),
            ) if flag]
            if running_names:
                self.tool.stop_all()
                stopped.append("丢球助手(" + "+".join(running_names) + ")")
        if starter != "engine" and self.engine.running:
            self.engine.stop("新模式启动,自动停止")
            stopped.append("挂机引擎")
        if starter != "pvp" and self._pvp_running:
            self._pvp_running = False
            stopped.append("PVP识别")
        for name in stopped:
            self._enqueue_log(f"模式互斥: 已自动停止 {name}", "warning")
        return stopped

    def stop_all(self) -> dict:
        self.tool.stop_all()
        if self.engine.running:
            self.engine.stop("全部停止")
        if getattr(self, "_pvp_running", False):
            # 静默杀 PVP 曾导致"RKPP 引擎无声消失"(全部停止/异色联动路径无日志)
            self._pvp_running = False
            self._enqueue_log("PVP 识别已停止(全部停止/联动触发)", "warning")
        return {"success": True}

    def get_app_mode(self) -> dict:
        """前端启动时询问运行模式,用户版据此隐藏开发者功能入口"""
        return {"success": True, "dev": DEV_MODE}

    def update_config(self, params: dict) -> dict:
        params = params or {}
        cleaned = self._validate_throw_params(params)
        if "exit_on_battle" in params:
            self.tool.exit_on_battle = bool(params["exit_on_battle"])
            cleaned["exit_on_battle"] = self.tool.exit_on_battle

        if not cleaned:
            return {"success": False, "message": "没有有效参数"}

        for key, value in cleaned.items():
            if key != "exit_on_battle":
                setattr(self.tool, key, value)
        self._save_throw_config()
        self._enqueue_log(f"丢球延迟配置已更新: {cleaned}", "success")
        return {"success": True, "config": self._get_throw_config()}

    @staticmethod
    def _validate_throw_params(params: dict) -> dict:
        cleaned = {}
        for key, (lo, hi) in CONFIG_SCHEMA.items():
            if key not in params:
                continue
            try:
                value = round(float(params[key]), 2)
            except (TypeError, ValueError):
                continue
            cleaned[key] = max(lo, min(hi, value))
        for min_key, max_key in CONFIG_PAIRS:
            if min_key in cleaned and max_key in cleaned:
                if cleaned[min_key] > cleaned[max_key]:
                    cleaned[min_key] = cleaned[max_key]
        return cleaned

    def _get_throw_config(self) -> dict:
        cfg = {key: getattr(self.tool, key) for key in CONFIG_SCHEMA}
        cfg["exit_on_battle"] = getattr(self.tool, "exit_on_battle", True)
        return cfg

    def _throw_config_path(self) -> Path:
        return CONFIG_DIR / "throw_ball_config.json"

    def _load_throw_config(self):
        path = self._throw_config_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in self._validate_throw_params(data).items():
                setattr(self.tool, key, value)
            self._enqueue_log("已加载丢球延迟配置", "info")
        except Exception as e:
            self._enqueue_log(f"加载丢球配置失败: {e}", "error")

    def _save_throw_config(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            data = {k: round(v, 2) for k, v in self._get_throw_config().items()}
            self._throw_config_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self._enqueue_log(f"保存丢球配置失败: {e}", "error")


    def mode_get(self) -> dict:
        return {"success": True, "mode": self.mode_ctrl.current_mode,
                "label": self.mode_ctrl.mode_label}

    def mode_switch(self, mode: str) -> dict:
        return self.mode_ctrl.switch_to(mode)

    # ========================================
    # 5. 状态轮询 + 任务栏数据
    # ========================================

    def get_state(self) -> dict:
        try:
            game_active = self.tool.is_game_window_active()
        except Exception:
            game_active = False

        tasks = []
        if self.tool.running:
            tasks.append({"id": "normal", "name": "普通丢球",
                          "detail": f"已丢 {self.tool.normal_count} 球"})
        if self.tool.bomber_running:
            tasks.append({"id": "bomber", "name": "轰炸机",
                          "detail": f"已丢 {self.tool.bomber_count} 球"})
        if self.tool.skill_running:
            tasks.append({"id": "skill", "name": "自动技能",
                          "detail": f"已按 {self.tool.skill_count} 次"})
        if self._live_running:
            tasks.append({"id": "live", "name": "实时识别",
                          "detail": f"每 {self._live_interval}s"})
        if self.engine.running:
            state_names = {"waiting": "等战斗", "fighting": "战斗中",
                           "throwing": "丢球", "paused": "暂停"}
            tasks.append({"id": "engine", "name": "战斗引擎" + ("(模拟)" if self.engine.dry_run else ""),
                          "detail": f"{state_names.get(self.engine.state, self.engine.state)} {self.engine.state_detail}"})
        for tool_id, info in list(self._tool_procs.items()):
            if info["proc"].poll() is None:
                tasks.append({"id": f"tool:{tool_id}", "name": info["name"],
                              "detail": f"PID {info['proc'].pid}"})
            else:
                self._tool_procs.pop(tool_id, None)

        return {
            "game_active": game_active,
            "normal_running": self.tool.running,
            "bomber_running": self.tool.bomber_running,
            "skill_running": self.tool.skill_running,
            "normal_count": self.tool.normal_count,
            "bomber_count": self.tool.bomber_count,
            "skill_count": self.tool.skill_count,
            "config": self._get_throw_config(),
            "throw_run": {
                "running": bool(self.tool.running or self.tool.bomber_running),
                "elapsed": (time.time() - self.tool._run_started_at)
                           if (self.tool.running or self.tool.bomber_running)
                           and getattr(self.tool, "_run_started_at", 0) else 0,
                "thrown": (self.tool.normal_count - getattr(self.tool, "_run_start_count", 0))
                          + (self.tool.bomber_count - getattr(self.tool, "_bomber_run_start_count", 0)),
                "quota_count": self.tool.stop_after_count,
                "quota_minutes": self.tool.stop_after_minutes,
            },
            "ball_inventory": (self.ball_watcher.status() if getattr(self, "ball_watcher", None)
                               else {"enabled": False, "mode": "-", "samples": 0,
                                     "updated_at": "", "slots": []}),
            "tasks": tasks,
            "companion_enabled": (
                getattr(self, "_ai_companion", None) is not None
                and getattr(self, "_ai_companion_enabled", False)
            ),
            "update_hint": getattr(self, "_update_hint", None),
        }
