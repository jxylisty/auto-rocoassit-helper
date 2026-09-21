# -*- coding: utf-8 -*-
"""pvp_mcp_server — 洛克王国 PVP 陪玩 MCP 服务器 (stdio, 纯标准库)

让 AI 客户端(ZCode/Claude Desktop/Cline 等)通过 MCP 协议获取实时对局数据、
查询 PVP 规则、做伤害推演, 从而辅助玩家对战。

架构:
    AI 客户端 ──stdio(JSON-RPC)── 本文件 ──HTTP── 主程序(127.0.0.1:17365)

接入配置(以 ZCode 为例):
    {
      "mcpServers": {
        "lkw-pvp": {
          "command": "D:/anaconda/python.exe",
          "args": ["D:/洛克王国ai/lkwgai_pvp_assistant/tools/pvp_mcp_server.py"]
        }
      }
    }

MCP 协议(2024-11-05 规范)最小实现: initialize / tools/list / tools/call。
stdio 帧格式: 每行一个 JSON(换行分隔, MCP 默认)。
"""
from __future__ import annotations

import json
import sys
import urllib.request

LOCAL_API = "http://127.0.0.1:17365"

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "lkw-pvp-companion", "version": "1.0.0"}


# ---------------- HTTP 调用主程序 ----------------

def api_get(path: str) -> dict:
    try:
        with urllib.request.urlopen(f"{LOCAL_API}{path}", timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"无法连接洛克王国助手({e}) — 请确认主程序已启动"}


def api_post(path: str, body: dict) -> dict:
    try:
        req = urllib.request.Request(
            f"{LOCAL_API}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"无法连接洛克王国助手({e}) — 请确认主程序已启动"}


# ---------------- MCP 工具定义与实现 ----------------

TOOLS = [
    {
        "name": "pvp_snapshot",
        "description": (
            "获取洛克王国 PVP 当前对局的实时快照。返回: 双方在场精灵名/属性/血量、"
            "我方能量、双方技能伤害推演(dmg_min/max/克制倍率/是否斩杀)、敌方威胁技能、"
            "速度差与先手结论、愿力冲击推演。in_battle=false 表示当前不在对战画面"
            "(可稍后重试)。识别引擎需在悬浮窗或主控台启动。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "pvp_rules",
        "description": (
            "获取洛克王国 PVP 完整规则知识包: 固定等级/星级/个体值规则/性格修正/"
            "克制倍率口径/伤害公式/先手判定规则/完整18系克制表。"
            "辅助对战前应先调用一次建立规则心智。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "pvp_analyze_matchup",
        "description": (
            "精算指定攻防双方精灵的完整对局推演: 双方面板 + 攻方全部技能伤害"
            "(按克制排序) + 先手结论 + 愿力冲击应对。atk/def 传精灵 seq 编号"
            "(先用 pvp_search 查)。可选 IV 配置与性格。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "atk": {"type": "integer", "description": "攻方精灵 seq"},
                "def": {"type": "integer", "description": "守方精灵 seq"},
                "atk_iv_value": {"type": "integer", "description": "攻方单项IV(0-10, 默认10)"},
                "def_iv_value": {"type": "integer", "description": "守方单项IV(0-10, 默认10)"},
            },
            "required": ["atk", "def"],
        },
    },
    {
        "name": "pvp_search",
        "description": "按名字模糊搜索精灵(仅 PVP 可用的最终形态)与技能, 返回 seq/名称/属性等",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "搜索关键词"},
                "kind": {"type": "string", "enum": ["pet", "skill", "all"], "description": "搜索类型, 默认 all"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "pvp_history",
        "description": "查询近期 PVP 战报历史(时间/结果/双方队伍), 可用于分析对手风格",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "条数, 默认10"}},
            "required": [],
        },
    },
]


def tool_call(name: str, args: dict) -> dict:
    if name == "pvp_snapshot":
        return api_get("/snapshot")
    if name == "pvp_rules":
        return api_get("/rules")
    if name == "pvp_analyze_matchup":
        return api_post("/analyze", args)
    if name == "pvp_search":
        return api_get(f"/search?q={urllib.request.quote(args.get('q', ''))}"
                       f"&kind={args.get('kind', 'all')}")
    if name == "pvp_history":
        return api_get(f"/history?limit={int(args.get('limit') or 10)}")
    return {"error": f"未知工具: {name}"}


# ---------------- MCP JSON-RPC stdio 循环 ----------------

def _resp(msg_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(msg: dict) -> dict | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    # 通知(无 id): 不回包
    if msg_id is None:
        return None

    if method == "initialize":
        return _resp(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _resp(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        name = str(params.get("name", ""))
        args = params.get("arguments") or {}
        result = tool_call(name, args)
        text = json.dumps(result, ensure_ascii=False, indent=1)
        return _resp(msg_id, {
            "content": [{"type": "text", "text": text}],
            "isError": "error" in result,
        })
    if method == "ping":
        return _resp(msg_id, {})
    return _err(msg_id, -32601, f"未知方法: {method}")


def main() -> None:
    # Windows 下强制 UTF-8 + 无缓冲(逐行读, flush 写)
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        try:
            resp = handle(msg)
        except Exception as e:
            resp = _err(msg.get("id"), -32603, f"内部错误: {e}")
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
