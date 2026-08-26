# -*- coding: utf-8 -*-
"""
洛克王国 PVP 助手 - 启动入口

Usage:
    python main.py              # 启动大前端控制台（推荐用 Anaconda 环境）
    python main.py --throw      # 启动自动扔球工具（无界面，纯快捷键）
"""

import sys
import argparse
import webview
from pathlib import Path


def get_html_path() -> Path:
    """获取 HTML 文件路径"""
    html_path = Path(__file__).parent / "src" / "gui" / "web" / "index.html"

    if not html_path.exists():
        print(f"错误: HTML 文件不存在: {html_path}")
        sys.exit(1)

    return html_path


def start_gui():
    """启动大前端控制台 + 悬浮状态窗"""
    from src.gui.bridge import AppBridge, Api
    from src.utils.settings import get as cfg

    bridge = AppBridge()
    api = Api(bridge)

    web_dir = get_html_path().parent

    window = webview.create_window(
        title='洛克王国 · PVP 助手控制台',
        url=get_html_path().as_uri(),
        js_api=api,
        width=cfg('gui.width', 1150),
        height=cfg('gui.height', 780),
        min_size=(960, 620),
        resizable=True,
        text_select=True
    )

    # 悬浮状态窗: 置顶无边框小窗,初始隐藏,F2/界面按钮唤出
    widget = webview.create_window(
        title='状态',
        url=(web_dir / "widget.html").as_uri(),
        js_api=api,
        width=280,
        height=216,
        resizable=False,
        frameless=True,
        easy_drag=True,
        on_top=True,
        hidden=True,
    )

    bridge.set_window(window)
    bridge.set_widget_window(widget)

    # PVP 对战悬浮窗: 置顶无边框,初始隐藏,PVP 页面按钮+F12 唤出
    pvp_float = webview.create_window(
        title='PVP',
        url=(web_dir / "pvp_float_overlay.html").as_uri(),
        js_api=api,
        width=260,
        height=320,
        resizable=False,
        frameless=True,
        easy_drag=True,
        on_top=True,
        hidden=True,
    )
    bridge.set_pvp_float_window(pvp_float)

    window.events.closed += bridge.shutdown

    # 全局快捷键 F4/F9/F10 丢球 / F2 悬浮窗 / F8 截图 / F11 急停
    bridge.enable_hotkeys()

    webview.start()


def start_throw_tool():
    """启动无界面的自动扔球工具（快捷键模式）"""
    from auto_throw_ball import AutoThrowBall

    print("=" * 50)
    print("洛克王国 - 自动丢球工具（无界面模式）")
    print("=" * 50)

    tool = AutoThrowBall()
    tool.start()


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='洛克王国 PVP 助手')
    parser.add_argument('--throw', action='store_true', help='启动自动丢球工具（无界面）')

    args = parser.parse_args()

    if args.throw:
        start_throw_tool()
    else:
        start_gui()


if __name__ == '__main__':
    main()
