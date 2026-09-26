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
    # 悬浮控制台改为惰性创建: 启动不再建 hidden 窗(根治"启动黑框"——
    # pywebview 对 hidden 窗的 Opacity 技巧对跨进程 WebView2 无效, 会残留
    # 一块永不绘制的黑色表面), 首次 F2/F12/启动任务时才建, 出生即可见。
    # 页面地址与 Api 单例先注入 bridge, 见 bridge_widget.ensure_widget_window。
    bridge.set_window(window)
    bridge.set_widget_url((web_dir / "float_console.html").as_uri())
    bridge.set_widget_window(None)
    bridge.set_pvp_float_window(None)

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

    # 启动看门狗(独立进程): WebView2 初始化偶发挂起时, 主进程 Python 线程
    # 会被一起饿死("无报错但窗口永不出现", 日志戛然而止), 进程内看门狗
    # 永远没机会触发 — 只有进程外的看门狗还能行动。
    if not getattr(sys, "frozen", False):
        import os as _os
        import subprocess as _sp
        _sp.Popen([sys.executable, str(Path(__file__).resolve()),
                   "--boot-watchdog", str(_os.getpid())],
                  cwd=str(Path(__file__).parent),
                  creationflags=0x08000000)   # CREATE_NO_WINDOW

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


def _kill_ghost_processes():
    """只清理本应用的残留进程, 不碰机器上其他 python / WebView2 应用。

    旧实现 taskkill /IM python.exe 是全机器扫射: 会连坐常驻的豆包桥
    (pythonw bridge.py)、server.py、上下文挂件等无关进程。
    匹配规则: python* 命令行含 main.py(本项目启动方式); msedgewebview2 的
    用户数据目录含 pywebview(pywebview 默认 %APPDATA%\\pywebview, 仅本应用使用)。
    """
    import os as _os
    import subprocess
    own_pid = _os.getpid()
    script = (
        "$own = " + str(own_pid) + " ; "
        "$targets = Get-CimInstance Win32_Process | Where-Object { "
        "$_.ProcessId -ne $own -and ( "
        "($_.Name -in @('python.exe','pythonw.exe') -and \"$($_.CommandLine)\" -match 'main\\.py') -or "
        "($_.Name -eq 'msedgewebview2.exe' -and \"$($_.CommandLine)\" -match 'pywebview') ) } ; "
        "if (-not $targets) { Write-Output '没有发现本应用的残留进程。' } ; "
        "foreach ($p in @($targets)) { "
        "$cl = \"$($p.CommandLine)\" ; "
        "Write-Output ('已结束: PID ' + $p.ProcessId + '  ' + $p.Name + '  ' + $cl.Substring(0, [Math]::Min(90, $cl.Length))) ; "
        "Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    r = subprocess.run(['powershell', '-NoProfile', '-Command', script],
                       capture_output=True, text=True, errors='replace')
    print(r.stdout.strip() or "清理完成, 重新启动即可。")
    if r.returncode != 0 and r.stderr.strip():
        print("清理脚本出错:", r.stderr.strip()[:300])
    print("重新启动即可: python main.py")


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
    # 终端可见的提示: 崩溃转储(faulthandler)只写文件不进终端, 出问题先看这里
    print(f"[启动日志] 本次输出与崩溃转储同写: {log_dir / 'startup.log'}")
    import faulthandler
    faulthandler.enable(file=f)


def _boot_watchdog_child(parent_pid: int) -> None:
    """独立进程看门狗: 45s 内主窗口不可见 → 终止挂死实例 + 弹窗提示。

    主进程 WebView2 初始化偶发挂起时, 其内部线程全部停摆(日志戛然而止),
    只有进程外的看门狗还能行动。窗口可见或父进程自行退出时本进程静默退出。
    """
    import ctypes
    import time
    user32 = ctypes.windll.user32
    title = "洛克王国 · PVP 助手控制台"
    deadline = time.time() + 45
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, title)
        if hwnd and user32.IsWindowVisible(hwnd):
            return                      # 启动正常
        if not _pid_alive(parent_pid):
            return                      # 父进程已自行退出(正常关闭/用户处理)
        time.sleep(0.5)
    # 超时: 写日志 → 终止挂死实例 → 弹窗
    try:
        log_dir = Path(__file__).parent / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "boot_watchdog.log").write_text(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} 主窗口 45 秒未出现, 已终止挂起实例 "
            f"PID={parent_pid}", encoding="utf-8")
    except Exception:
        pass
    # 直接 TerminateProcess: 子进程里再拉 taskkill 子子进程偶发静默失败
    killed = False
    try:
        PROCESS_TERMINATE = 0x0001
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(parent_pid))
        if h:
            killed = bool(kernel32.TerminateProcess(h, 1))
            kernel32.CloseHandle(h)
    except Exception:
        pass
    try:
        with open(log_dir / "boot_watchdog.log", "a", encoding="utf-8") as f:
            result_text = "成功" if killed else "失败(需手动 taskkill)"
            f.write(f" → terminate {result_text}\n")
    except Exception:
        pass
    try:
        user32.MessageBoxW(
            None, "窗口 45 秒未出现(WebView2 偶发挂起), 挂起实例已自动终止, 请重新启动; 若连续出现先执行: python main.py --kill-ghosts",
            "启动看门狗", 0x30)
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    import ctypes
    SYNCHRONIZE = 0x00100000
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not h:
        return False
    kernel32.CloseHandle(h)
    return True


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='洛克王国 PVP 助手')
    parser.add_argument('--throw', action='store_true', help='启动自动丢球工具（无界面）')
    parser.add_argument('--kill-ghosts', action='store_true', help='强制终止所有残留进程后退出')
    parser.add_argument('--boot-watchdog', type=int, default=0, metavar='PID',
                        help='内部: 独立进程看门狗, 监视指定 PID 的主窗口可见性')

    args = parser.parse_args()

    if args.boot_watchdog:
        _boot_watchdog_child(args.boot_watchdog)
        return

    if args.kill_ghosts:
        _kill_ghost_processes()
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
