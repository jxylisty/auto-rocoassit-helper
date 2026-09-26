# -*- coding: utf-8 -*-
"""WebSocket 实时推送管理器

负责管理前端 Web 客户端的长连接，实现全双工事件广播：
- 后台日志推送 (addLog)
- 实时战斗状态更新 (state / pvp_update)
- 异色报警 / 回合刷新通知
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Set
from fastapi import WebSocket

logger = logging.getLogger("server.ws")


class WebSocketManager:
    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)
        logger.info(f"WebSocket 客户端已连接 (当前在线: {len(self._connections)})")

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)
        logger.info(f"WebSocket 客户端已断开 (当前在线: {len(self._connections)})")

    async def broadcast(self, message_dict: dict):
        if not self._connections:
            return
        payload = json.dumps(message_dict, ensure_ascii=False)
        disconnected = set()
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.add(ws)
        for dead_ws in disconnected:
            self._connections.discard(dead_ws)

    def broadcast_threadsafe(self, message_dict: dict):
        """供后台工作线程调用的安全广播方法"""
        if self._loop and self._loop.is_running() and self._connections:
            asyncio.run_coroutine_threadsafe(self.broadcast(message_dict), self._loop)

    def broadcast_log(self, message: str, level: str = "info"):
        self.broadcast_threadsafe({
            "type": "log",
            "message": str(message),
            "level": level
        })

    def broadcast_state(self, state: dict):
        self.broadcast_threadsafe({
            "type": "state",
            "state": state
        })

    def broadcast_pvp_update(self, data: dict):
        self.broadcast_threadsafe({
            "type": "pvp_update",
            "data": data
        })


# 全局单例
ws_manager = WebSocketManager()
