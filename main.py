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
        width=cfg('gui.width', 1320),
        height=cfg('gui.height', 860),
        min_size=(1080, 720),
        resizable=True,
        text_select=True,
        frameless=True  # 自绘标题栏: 置顶/最小化/关闭在界面内
    )

    # 悬浮控制台: 置顶无边框小窗(挂机+PVP 双标签),初始隐藏,F2/界面按钮唤出
    widget = webview.create_window(
        title='状态',
        url=(web_dir / "float_console.html").as_uri(),
        js_api=api,
        width=340,
        height=335,
        resizable=False,
        frameless=True,
        easy_drag=False,
        on_top=True,
        hidden=True,
    )

    bridge.set_window(window)
    bridge.set_widget_window(widget)
    bridge.set_pvp_float_window(widget)  # 合并悬浮窗: PVP 推演推送同窗

    window.events.closed += bridge.shutdown

    # 全局快捷键 F4/F9/F10 丢球 / F2 悬浮窗 / F8 截图 / F11 急停
    bridge.enable_hotkeys()

    # 自动更新: 后台静默检查 GitHub main 分支新版本
    bridge.start_update_watcher()

    webview.start()


def start_throw_tool():
    """启动无界面的自动扔球工具（快捷键模式）"""
    from auto_throw_ball import AutoThrowBall

    print("=" * 50)
    print("洛克王国 - 自动丢球工具（无界面模式）")
    print("=" * 50)

    tool = AutoThrowBall()
    tool.start()


# 单实例互斥锁: 防残留进程锁住 WebView2 用户目录导致下次启动随机失败(时好时坏)
_mutex_handle = None


def _acquire_single_instance():
    """命名互斥锁, 进程退出/崩溃时自动释放, 不存在陈旧锁文件问题"""
    global _mutex_handle
    import ctypes
    kernel32 = ctypes.windll.kernel32
    _mutex_handle = kernel32.CreateMutexW(None, False, "LKW_PVP_Assistant_SingleInstance")
    return kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS


def _init_startup_log():
    """启动日志落盘: 所有 stdout 同时写 data/logs/startup.log, 崩溃可追溯"""
    import sys as _sys
    from pathlib import Path as _Path
    log_dir = _Path(__file__).parent / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    f = open(log_dir / "startup.log", "a", encoding="utf-8")
    f.write(f"\n===== 启动 {__import__('time').strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    f.flush()

    class _Tee:
        def __init__(self, orig):
            self.orig = orig
        def write(self, s):
            self.orig.write(s)
            f.write(s)
            f.flush()
        def flush(self):
            self.orig.flush()
            f.flush()

    _sys.stdout = _Tee(_sys.stdout)
    _sys.stderr = _Tee(_sys.stderr)
    import faulthandler
    faulthandler.enable(file=f)


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='洛克王国 PVP 助手')
    parser.add_argument('--throw', action='store_true', help='启动自动丢球工具（无界面）')

    args = parser.parse_args()

    if not args.throw:
        _init_startup_log()
        if not _acquire_single_instance():
            print("⚠ 检测到已有实例在运行——如果上一窗口已关闭但还报此错,"
                  "请到任务管理器结束残留的 python.exe 后重试")
            sys.exit(1)

    if args.throw:
        start_throw_tool()
    else:
        start_gui()


if __name__ == '__main__':
    main()
