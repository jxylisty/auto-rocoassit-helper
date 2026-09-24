# -*- coding: utf-8 -*-
"""主窗口尺寸计算与 C 扩展预热(启动竞态修复)。

本模块解决两类"看起来像玄学"的启东期问题, 细节见 docs/AI_EDITING_LESSONS.md:

1. 启动随机闪退(access violation, 无报错框)
   后台线程首次 import C 扩展(win32ui 等)与主线程 keyboard 初始化触发的 GC 撞车。
   解法: prewarm_c_extensions() 在任何线程启动前单线程导入一遍。

2. 窗口尺寸在不同 DPI 缩放机器上忽大忽小/超出屏幕
   pywebview 创建窗口时的 width/height 要经过 WinForms/WinForms-Dpi 的换算,
   且换算结果取决于"进程何时变成 DPI 感知", 不可预测。
   解法: 只用物理像素思考 —— physical_metrics() 把工作区归一到物理像素,
   窗口显示后用 SetWindowPos 按物理像素精确定尺(apply_window_size_physical)。
"""

from __future__ import annotations

import ctypes
import threading
import time


def _u32():
    """独立 user32 句柄: 不受其它模块对 ctypes.windll.user32 的全局 argtypes 影响"""
    try:
        return ctypes.WinDLL("user32")
    except Exception:
        return ctypes.windll.user32


def _gdi32():
    try:
        return ctypes.WinDLL("gdi32")
    except Exception:
        return ctypes.windll.gdi32


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


# ============================================================
# 1. C 扩展预热(消除启动竞态)
# ============================================================

_PREWARM_MODULES = (
    # pywin32: window_capture.py 第 13 行 import win32ui 是崩溃转储里的死亡现场
    "win32ui", "win32gui", "win32con", "win32api", "win32process",
    # 图像栈: 同样体积大、初始化重
    "cv2", "numpy",
    # 本项目自己的截图模块(导入时还有 enable_dpi_awareness 的副作用)
    "src.capture.window_capture",
    "src.capture.fast_capture",
)

_prewarmed = False


def prewarm_c_extensions(verbose: bool = False) -> None:
    """在任何后台线程启动之前调用, 单线程把重 C 扩展先导入一遍。

    必须早于 set_window()/enable_hotkeys() —— 这两个分别启动后台识别线程和
    keyboard 初始化(GC 风暴), 它们并发时的首次导入就是崩溃根因。
    """
    global _prewarmed
    if _prewarmed:
        return
    _prewarmed = True

    import importlib
    for mod in _PREWARM_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as e:      # 缺库/缺驱动不能阻塞启动
            if verbose:
                print(f"[预热] {mod} 导入失败(可忽略): {e}")


# ============================================================
# 2. 物理像素工作区(与进程 DPI 感知状态无关)
# ============================================================

def physical_metrics():
    """返回 (work_l, work_t, work_r, work_b, scale), 全部物理像素。

    原理: GetSystemMetrics(SM_CXSCREEN) 在 DPI 不感知的进程里返回逻辑宽,
    而 GetDeviceCaps(DESKTOPHORZRES) 永远返回物理宽, 两者之比即缩放。
    这样无论进程何时变成 DPI 感知, 结果都一致。
    """
    u, g = _u32(), _gdi32()
    scale = 1.0
    try:
        hdc = g.CreateDCW("DISPLAY", None, None, None)
        try:
            phys_w = g.GetDeviceCaps(hdc, 118)      # DESKTOPHORZRES
        finally:
            try:
                g.DeleteDC(hdc)
            except Exception:
                pass
        sm_w = u.GetSystemMetrics(0) or phys_w
        if sm_w and phys_w:
            scale = phys_w / float(sm_w)
    except Exception:
        pass

    r = _RECT()
    try:
        if not u.SystemParametersInfoW(48, 0, ctypes.byref(r), 0):   # SPI_GETWORKAREA
            raise OSError("SPI_GETWORKAREA failed")
    except Exception:
        return 0, 0, 1920, 1040, 1.0

    return (int(r.left * scale), int(r.top * scale),
            int(r.right * scale), int(r.bottom * scale), scale)


def compute_main_window_size(cap_w: int | None = None, cap_h: int | None = None,
                             ratio_w: float = 0.96, ratio_h: float = 0.94):
    """算主窗口目标尺寸(物理像素), 返回 (w, h, workarea)。

    默认吃掉工作区的 96% x 94%: 观感大气、内容看得全, 又留出任务栏/边缘余量。
    cap_w/cap_h 是 settings.yaml 里的逻辑像素上限(会乘缩放折算成物理), 只做收缩。
    """
    wa_l, wa_t, wa_r, wa_b, scale = physical_metrics()
    wa_w, wa_h = max(1, wa_r - wa_l), max(1, wa_b - wa_t)

    tw, th = int(wa_w * ratio_w), int(wa_h * ratio_h)
    if cap_w and cap_w > 0:
        tw = min(tw, int(cap_w * scale))
    if cap_h and cap_h > 0:
        th = min(th, int(cap_h * scale))

    # 下限按缩放折算(高分屏上不至于太窄), 且绝不超屏
    tw = max(int(900 * scale), min(tw, wa_w))
    th = max(int(600 * scale), min(th, wa_h))
    return tw, th, (wa_l, wa_t, wa_r, wa_b)


# ============================================================
# 3. 显示后按物理像素精确定尺并居中
# ============================================================

def setup_app_user_model_id(app_id: str = "lkwg.pvp.assistant") -> None:
    """设置显式 AppUserModelID，使 Windows 任务栏将本窗口视为独立应用而非通用 python.exe"""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(str(app_id))
    except Exception:
        pass


def apply_window_icon(hwnd: int, icon_path: str | None = None) -> None:
    """向指定 HWND 发送 WM_SETICON 消息设置大图标与小图标 (任务栏 + Alt-Tab + 窗口左上角)"""
    if not hwnd:
        return
    try:
        from pathlib import Path
        if not icon_path:
            p = Path(__file__).resolve().parents[2] / "data" / "assets" / "icons" / "app_icon.ico"
            if not p.exists():
                return
            icon_path = str(p)
        else:
            p = Path(icon_path)
            if not p.exists():
                return
            icon_path = str(p)

        u32 = _u32()
        LR_LOADFROMFILE = 0x0010
        IMAGE_ICON = 1
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        # 载入 16x16 (小图标/标题栏/任务栏小视图) 和 32x32/48x48 (大图标/Alt-Tab/任务栏缩略图)
        h_icon_sm = u32.LoadImageW(None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        h_icon_lg = u32.LoadImageW(None, icon_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)

        if h_icon_sm:
            u32.SendMessageW(ctypes.c_void_p(hwnd), WM_SETICON, ICON_SMALL, ctypes.c_void_p(h_icon_sm))
        if h_icon_lg:
            u32.SendMessageW(ctypes.c_void_p(hwnd), WM_SETICON, ICON_BIG, ctypes.c_void_p(h_icon_lg))
    except Exception:
        pass


def apply_window_size_physical(window, phys_w: int, phys_h: int,
                              workarea=None, delay: float = 0.15) -> None:
    """等窗口就绪后按物理像素定尺居中, 并设置独立 App 图标, 然后显示(不闪)。

    关键: 建窗时必须传 hidden=True。pywebview 创建期的 width/height 会被 WinForms
    按当前 DPI 做一次倍率换算(实测 1.39~1.47, 且取决于进程何时变成 DPI 感知),
    而隐藏窗口没有这个副作用 —— 所以流程是"隐藏建窗 → SetWindowPos 物理定尺 → show",
    用户第一眼看到的就是正确尺寸, 不会先闪一个大/小窗口再跳。

    window 若不是 hidden 建的(旧调用方), 退化为"定尺后再显示"同样不闪。
    """
    if workarea is None:
        wa_l, wa_t, wa_r, wa_b, _ = physical_metrics()
    else:
        wa_l, wa_t, wa_r, wa_b = workarea

    def _job():
        hwnd = 0
        for _ in range(150):        # 最多等 ~15s
            try:
                hwnd = int(window.native.Handle.ToInt32())
            except Exception:
                hwnd = 0
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            try:
                window.show()
            except Exception:
                pass
            return

        # 为窗口应用原生应用图标 (任务栏 + Alt-Tab + 窗口管理)
        apply_window_icon(hwnd)

        if delay > 0:
            time.sleep(delay)
        try:
            SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
            pw = min(int(phys_w), wa_r - wa_l)
            ph = min(int(phys_h), wa_b - wa_t)
            x = wa_l + max(0, (wa_r - wa_l - pw) // 2)
            y = wa_t + max(0, (wa_b - wa_t - ph) // 2)
            _u32().SetWindowPos(ctypes.c_void_p(hwnd), None, int(x), int(y),
                                int(pw), int(ph),
                                SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            pass
        try:
            window.show()
        except Exception:
            pass

    threading.Thread(target=_job, daemon=True, name="WinSize").start()

