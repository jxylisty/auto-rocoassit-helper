# -*- coding: utf-8 -*-
"""洛克王国 PVP 助手 - 前后端解耦独立服务启动入口

Usage:
    python server_main.py                 # 启动服务并在默认浏览器打开主控制台
    python server_main.py --app-mode      # 以 Edge 独立桌面应用窗口模式启动 (无地址栏)
    python server_main.py --no-browser    # 纯后台服务模式 (不自动打开浏览器)
    python server_main.py --port 17365    # 指定端口
"""

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# 针对 Windows 控制台容错配置，消除 GBK 编码报错
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """检查指定端口是否已被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def open_client_window(url: str, app_mode: bool = False):
    """在浏览器或以独立 App 模式打开前端"""
    time.sleep(1.0)  # 等待 uvicorn 启动就绪
    if app_mode:
        # 尝试寻找 msedge.exe 以 --app 模式启动独立小窗
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        edge_bin = next((p for p in edge_paths if Path(p).exists()), None)
        if edge_bin:
            try:
                subprocess.Popen([edge_bin, f"--app={url}", "--window-size=1280,860"])
                return
            except Exception:
                pass
    # 默认浏览器打开
    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description="洛克王国 PVP 助手 · 前后端解耦独立服务")
    parser.add_argument("--port", type=int, default=17365, help="服务监听端口 (默认: 17365)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="服务监听地址 (默认: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="启动时不自动打开浏览器")
    parser.add_argument("--app-mode", action="store_true", help="使用 Edge 独立应用小窗模式运行")

    args = parser.parse_args()

    port = args.port
    host = args.host
    base_url = f"http://{host}:{port}"

    print("=" * 60)
    print("  [洛克王国 PVP 助手] 前后端解耦核心服务 (v2.0)")
    print("=" * 60)

    # 1. 端口检查
    if is_port_in_use(port, host):
        print(f"[!] 端口 {port} 已被占用！")
        print(f"    可能已有实例在运行，可直接访问: {base_url}")
        print("    若需强制重启，请先结束占用端口的进程。")
        sys.exit(1)

    print(f"[*] 主控制台界面:      {base_url}/")
    print(f"[*] 挂机悬浮战况:      {base_url}/float")
    print(f"[*] PVP实时推演:       {base_url}/pvp_float")
    print(f"[*] 交互式 API 文档:   {base_url}/docs")
    print("-" * 60)
    print("[*] 提示: 无 GUI 消息循环阻碍，终端随时按 Ctrl+C 可毫秒级干净退出。")
    print("=" * 60)

    # 2. 自动启动前端展现
    if not args.no_browser:
        threading.Thread(
            target=open_client_window,
            args=(base_url, args.app_mode),
            daemon=True
        ).start()

    # 3. 启动 Uvicorn Web 服务
    import uvicorn
    try:
        uvicorn.run(
            "src.server.app:app",
            host=host,
            port=port,
            log_level="info",
            access_log=False  # 避免频繁轮询刷屏
        )
    except KeyboardInterrupt:
        print("\n[!] 收到中断信号，服务正在退出...")
    finally:
        print("[OK] 洛克王国 PVP 助手核心服务已完全停止。")


if __name__ == "__main__":
    main()
