# -*- coding: utf-8 -*-
"""
洛克王国 PVP 助手 - 启动入口

Usage:
    python main.py              # 启动大前端控制台（推荐用 Anaconda 环境）
    python main.py --throw      # 启动自动扔球工具（无界面，纯快捷键）
"""

import sys
import argparse
import signal
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
    from src.gui.window_sizing import (prewarm_c_extensions,
                                       compute_main_window_size,
                                       apply_window_size_physical,
                                       setup_app_user_model_id,
                                       apply_window_icon)

    # 1. 显式 AppUserModelID: 将任务栏图标从默认 python.exe 剥离为专属独立应用
    setup_app_user_model_id("lkwg.pvp.assistant")

    # 预热 C 扩展: 必须在桥接层启动后台线程之前(消除启动随机闪退竞态)
    prewarm_c_extensions(verbose=True)

    from src.gui.bridge import AppBridge, Api
    from src.utils.settings import get as cfg

    bridge = AppBridge()
    api = Api(bridge)
    bridge.set_api(api)  # 独立窗(ROI 工坊)运行时创建时共用同一 Api 单例

    web_dir = get_html_path().parent

    # 窗口尺寸自适应: 吃满工作区(大气、内容看得全), 兼容任意分辨率与显示缩放。
    # hidden 建窗 → 显示前按物理像素定尺 → show, 避免先闪一个大/小窗口
    # (创建期 width/height 的 DPI 换算倍率不可控, 见 window_sizing 模块注释)
    _cap_w = int(cfg('gui.width', 0) or 0)
    _cap_h = int(cfg('gui.height', 0) or 0)
    phys_w, phys_h, _wa = compute_main_window_size(_cap_w, _cap_h)

    window = webview.create_window(
        title='洛克王国 · PVP 助手控制台',
        url=get_html_path().as_uri(),
        js_api=api,
        width=1280,
        height=860,
        min_size=(880, 560),  # 下限: 小屏笔记本按比例缩窗后不被顶溢
        resizable=True,
        text_select=True,
        frameless=True,  # 自绘标题栏: 置顶/最小化/关闭在界面内
        hidden=True,     # 显示前由 apply_window_size_physical 定尺(防闪大窗)
        # easy_drag 默认 True 时 pywebview 会全局劫持 mousedown 拖动整窗,
        # 视觉调试台拖框选 ROI 会被窗口位移吞掉(框不了),必须关掉,
        # 标题栏拖拽由 .pywebview-drag-region(tbDragZone)接管
        easy_drag=False
    )
    # 悬浮控制台：置顶无边框小窗 (挂机+PVP 双标签),初始隐藏,F2/界面按钮唤出
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
    bridge.set_pvp_float_window(widget)  # 合并悬浮窗：PVP 推演推送同窗

    window.events.closed += bridge.shutdown

    # 显示后按物理像素精确定尺+居中(创建期的 width/height 会被 pywebview 按
    # 进程 DPI 感知时机做不确定的缩放, 这里覆盖成确定值)
    apply_window_size_physical(window, phys_w, phys_h, _wa)

    # 全局快捷键 F4/F9/F10 丢球 / F2 悬浮窗 / F8 截图 / F11 急停
    bridge.enable_hotkeys()

    # 自动更新: 后台静默检查 GitHub main 分支新版本
    bridge.start_update_watcher()
    # 卡密登录态: 后台静默校验(用户版; 开发者版直接放行)
    bridge.start_auth_verify()

# 启动看门狗: WebView2 偶发挂起(残留进程占用用户数据目录等)表现为
    # "无报错但窗口永不出现"。20s 未 shown → 写诊断日志 + 弹窗, 不再无声卡死。
    def _boot_watchdog():
        import time as _t
        for _ in range(40):          # 20s 内每 0.5s 查一次
            _t.sleep(0.5)
            try:
                if window.width > 10 and window.height > 10:
                    return
            except Exception:
                pass
        try:
            detail = ("窗口 20 秒未就绪 — 多为 WebView2 运行时挂起。\n"
                      "常见原因: 上次实例/WebView2 进程残留。\n"
                      "处理: 任务管理器结束所有 python.exe 与 msedgewebview2.exe 后重试。")
            log_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
            (log_dir / "data" / "logs").mkdir(parents=True, exist_ok=True)
            (log_dir / "data" / "logs" / "boot_watchdog.log").write_text(
                f"{_t.strftime('%Y-%m-%d %H:%M:%S')} {detail}", encoding="utf-8")
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, detail, "启动看门狗", 0x30)
        except Exception:
            pass
    import threading as _th
    _th.Thread(target=_boot_watchdog, daemon=True).start()

    # 信号处理: VSCode 终端终止 → 强制杀进程(webview 消息循环吞 Ctrl+C)
    _cleanup_once = [False]
    def _force_exit(sig=None, frame=None):
        if _cleanup_once[0]:
            return
        _cleanup_once[0] = True
        try:
            global _mutex_handle
            import ctypes
            if _mutex_handle:
                ctypes.windll.kernel32.CloseHandle(_mutex_handle)
                _mutex_handle = None
        except Exception:
            pass
        print("\n正在退出...")
        import os as _os
        _os._exit(0)
    signal.signal(signal.SIGINT, _force_exit)
    signal.signal(signal.SIGTERM, _force_exit)

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
    parser.add_argument('--kill-ghosts', action='store_true', help='强制终止所有残留进程后退出')

    args = parser.parse_args()

    if args.kill_ghosts:
        import subprocess
        for name in ('python.exe', 'pythonw.exe', 'msedgewebview2.exe'):
            subprocess.run(['taskkill', '/F', '/IM', name], capture_output=True)
        print("已清理所有残留进程, 重新启动即可。")
        sys.exit(0)

    if not args.throw:
        _init_startup_log()
        if not _acquire_single_instance():
            print("⚠ 检测到已有实例在运行——如果上一窗口已关闭但还报此错,"
                  "请到任务管理器结束残留的 python.exe 后重试\n"
                  "  快捷清理: python main.py --kill-ghosts")
            sys.exit(1)

    if args.throw:
        start_throw_tool()
    else:
        start_gui()


if __name__ == '__main__':
    main()
