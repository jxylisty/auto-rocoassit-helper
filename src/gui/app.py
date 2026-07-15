# -*- coding: utf-8 -*-
"""
GUI应用 - pywebview 前端界面
"""

import webview
from typing import Optional


class GUIApp:
    """GUI应用"""

    def __init__(self, title: str = "洛克王国 PVP 助手", width: int = 800, height: int = 600):
        self.title = title
        self.width = width
        self.height = height
        self.window: Optional[webview.Window] = None

    def start(self):
        """启动GUI"""
        self.window = webview.create_window(
            self.title,
            html=self._get_html(),
            width=self.width,
            height=self.height
        )
        webview.start()

    def _get_html(self) -> str:
        """获取HTML内容"""
        return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>洛克王国 PVP 助手</title>
    <style>
        body {
            font-family: 'Microsoft YaHei', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            margin: 0;
            padding: 20px;
        }
        h1 { color: #00d4ff; text-align: center; }
        .panel {
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
            padding: 20px;
            margin: 10px 0;
        }
        .btn {
            background: #00d4ff;
            border: none;
            padding: 10px 30px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            margin: 5px;
        }
        .btn:hover { background: #00a8cc; }
        .status { color: #4ade80; }
    </style>
</head>
<body>
    <h1>🎮 洛克王国 PVP 助手</h1>
    <div class="panel">
        <h3>状态</h3>
        <p>当前状态: <span class="status" id="status">待机</span></p>
    </div>
    <div class="panel">
        <h3>快捷操作</h3>
        <button class="btn" onclick="startBattle()">开始战斗</button>
        <button class="btn" onclick="stopBattle()">停止</button>
    </div>
    <script>
        function startBattle() {
            document.getElementById('status').textContent = '战斗中...';
        }
        function stopBattle() {
            document.getElementById('status').textContent = '已停止';
        }
    </script>
</body>
</html>
"""


__all__ = ['GUIApp']