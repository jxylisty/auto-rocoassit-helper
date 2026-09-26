# -*- coding: utf-8 -*-
"""FastAPI 服务应用入口 (App)

提供：
1. 静态前端资源托管 (让浏览器直接访问 http://127.0.0.1:17365 即可打开完整控制台)
2. 快捷子页面路由 (/float 挂机悬浮窗, /pvp_float PVP推演窗)
3. 统一 RPC 接口 POST /api/rpc/{method}
4. WebSocket 双工实时流 /ws
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.server.core import get_core
from src.server.ws_manager import ws_manager

# 路径常量
WEB_DIR = Path(__file__).resolve().parent.parent / "gui" / "web"

app = FastAPI(
    title="洛克王国 PVP 助手 · 核心服务",
    version="2.0.0",
    docs_url="/docs",
    redoc_url=None
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)
    # 初始化核心业务单例
    get_core()


@app.on_event("shutdown")
async def on_shutdown():
    core = get_core()
    core.shutdown()


# ==================== RPC 统一转发 ====================

class RpcRequest(BaseModel):
    args: List[Any] = []


@app.post("/api/rpc/{method}")
async def handle_rpc(method: str, req: RpcRequest = None):
    args = req.args if req else []
    core = get_core()
    res = core.invoke_rpc(method, args)
    return res


@app.get("/api/health")
@app.get("/health")
async def handle_health():
    core = get_core()
    return {"ok": True, "status": "ok", "app": "lkwg_pvp_server", "pvp_running": getattr(core.bridge, "_pvp_running", False)}


# ==================== MCP AI 陪玩兼容端点 ====================

@app.get("/snapshot")
async def handle_snapshot():
    core = get_core()
    return core.bridge.local_pvp_snapshot()


@app.get("/rules")
async def handle_rules():
    from src.gui.local_api import build_rules_pack
    return build_rules_pack()


@app.get("/search")
async def handle_search_endpoint(request: Request):
    from src.gui.local_api import handle_search
    core = get_core()
    params = dict(request.query_params)
    return handle_search(core.bridge, params)


@app.get("/history")
async def handle_history_endpoint(request: Request):
    from src.gui.local_api import handle_history
    core = get_core()
    params = dict(request.query_params)
    return handle_history(core.bridge, params)


@app.get("/rounds")
async def handle_rounds_endpoint(request: Request):
    from src.gui.local_api import handle_rounds
    params = dict(request.query_params)
    return handle_rounds(params)


@app.get("/round")
async def handle_round_detail_endpoint(request: Request):
    from src.gui.local_api import handle_round_detail
    params = dict(request.query_params)
    return handle_round_detail(params)


@app.post("/analyze")
async def handle_analyze_endpoint(request: Request):
    from src.gui.local_api import handle_analyze
    core = get_core()
    try:
        body = await request.json()
    except Exception:
        body = {}
    return handle_analyze(core.bridge, body)


@app.post("/act")
async def handle_act_endpoint(request: Request):
    from src.gui.local_api import handle_act
    core = get_core()
    try:
        body = await request.json()
    except Exception:
        body = {}
    return handle_act(core.bridge, body)


@app.post("/comment")
async def handle_comment_endpoint(request: Request):
    from src.gui.local_api import handle_comment
    core = get_core()
    try:
        body = await request.json()
    except Exception:
        body = {}
    return handle_comment(core.bridge, body)


@app.post("/recommend")
async def handle_recommend_endpoint():
    from src.gui.local_api import handle_recommend
    core = get_core()
    return handle_recommend(core.bridge)


# ==================== WebSocket 实时双工 ====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # 保持连接，并接收前端发送的交互指令
            data = await websocket.receive_text()
            # 目前前端主要是被动接收日志，预留将来扩展
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# ==================== 快捷单页路由 ====================

@app.get("/")
async def serve_index():
    index_file = WEB_DIR / "index.html"
    return FileResponse(index_file)


@app.get("/float")
async def serve_float():
    float_file = WEB_DIR / "float_console.html"
    return FileResponse(float_file)


@app.get("/pvp_float")
async def serve_pvp_float():
    pvp_file = WEB_DIR / "pvp_float_overlay.html"
    return FileResponse(pvp_file)


# ==================== 静态资源挂载 ====================
# 挂载 assets / favicon.ico 等静态文件
app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")

@app.get("/favicon.ico")
async def favicon():
    fav = WEB_DIR / "favicon.ico"
    if fav.exists():
        return FileResponse(fav)
    return JSONResponse(status_code=404, content={"detail": "not found"})
