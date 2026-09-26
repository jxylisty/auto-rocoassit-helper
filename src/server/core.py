# -*- coding: utf-8 -*-
"""后端核心服务管理器 (Core Server Manager)

本模块作为前后端解耦的核心调度器：
1. 托管无界面的 AppBridge 与 Api 业务实例；
2. 接管后台日志队列，通过 WebSocket (ws_manager) 实时广播给所有已连接的 Web 客户端；
3. 提供统一的 RPC 派发入口 invoke_rpc()；
4. 优雅停机支持：在终端按 Ctrl+C 时安全终止各后台引擎、释放驱动与抓包句柄。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from src.gui.bridge import AppBridge, Api
from src.server.ws_manager import ws_manager

logger = logging.getLogger("server.core")


class CoreServerManager:
    def __init__(self):
        self.bridge = AppBridge()
        self.api = Api(self.bridge)
        self.bridge.set_api(self.api)

        # 禁用旧的单线程 LocalApiServer，避免 17365 端口冲突
        # 新架构的 FastAPI app 会直接原生接管这些端点
        self.bridge.local_api_start = lambda: None

        # 挂接快捷键支持 (开发环境下快捷键依然有效)
        try:
            self.bridge.enable_hotkeys()
        except Exception as e:
            logger.warning(f"快捷键初始化异常 (不影响核心 API): {e}")

        self._stop_event = threading.Event()
        self._log_pusher_thread: threading.Thread | None = None

        # 启动日志监听线程
        self._start_ws_log_pusher()

    def _start_ws_log_pusher(self):
        """将 bridge._log_queue 中的日志抽取并通过 WebSocket 广播"""
        def _loop():
            while not self._stop_event.is_set():
                try:
                    message, level = self.bridge._log_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                # 打印到当前运行终端控制台 (安全编码防 GBK 崩溃)
                try:
                    print(f"[{level.upper()}] {message}")
                except Exception:
                    try:
                        safe_msg = str(message).encode("gbk", errors="replace").decode("gbk")
                        print(f"[{level.upper()}] {safe_msg}")
                    except Exception:
                        pass

                # 广播给浏览器前端
                ws_manager.broadcast_log(message, level)

        self._log_pusher_thread = threading.Thread(
            target=_loop, daemon=True, name="WsLogPusher"
        )
        self._log_pusher_thread.start()

    def invoke_rpc(self, method_name: str, args: list | None = None) -> Any:
        """调用 Api 暴露的方法并返回结果"""
        args = args or []
        target = getattr(self.api, method_name, None)
        if target is None:
            # 兼容：如果 Api 上没有，尝试从 bridge 直接调用
            target = getattr(self.bridge, method_name, None)

        if target is None or not callable(target):
            # 对纯客户端窗口行为（如置顶、移动、调尺寸等），在 Web 解耦模式下做优雅静默处理
            if method_name in ("minimize_window", "move_window_by", "window_move_by",
                               "window_resize_by", "window_resize_to", "window_close",
                               "set_on_top", "widget_resize", "pvp_float_resize",
                               "ai_widget_resize", "move_ai_window_by"):
                return {"success": True, "notice": f"{method_name} ignored in browser mode"}

            logger.warning(f"未知或不可调用的 RPC 方法: {method_name}")
            return {"success": False, "message": f"Method '{method_name}' not found"}

        try:
            res = target(*args)
            return res
        except TypeError as e:
            logger.error(f"RPC 参数匹配失败 [{method_name}]: {e}")
            return {"success": False, "message": f"Invalid arguments for {method_name}: {e}"}
        except Exception as e:
            logger.error(f"RPC 执行出错 [{method_name}]: {e}", exc_info=True)
            return {"success": False, "message": str(e)}

    def shutdown(self):
        """优雅关闭所有子任务与驱动句柄"""
        logger.info("正在关闭后端服务核心资源...")
        self._stop_event.set()
        try:
            self.bridge.stop_all()
        except Exception:
            pass
        try:
            self.bridge.close()
        except Exception:
            pass
        logger.info("核心资源已全部释放")


# 全局单例
core_mgr: CoreServerManager | None = None


def get_core() -> CoreServerManager:
    global core_mgr
    if core_mgr is None:
        core_mgr = CoreServerManager()
    return core_mgr
