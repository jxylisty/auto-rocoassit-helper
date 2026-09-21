# -*- coding: utf-8 -*-
"""
冻结环境(打包 exe)启动器

职责(按顺序):
1. 管理员提权(挂机键鼠 + 全局热键 + 驱动安装都需要)
2. 首次运行:把只读资源里的 data/ 复制到 exe 旁边(可写的用户数据目录)
3. 重定向各模块的可写路径常量 → exe/data
4. 检查/安装 Interception 内核驱动(丢球挂机依赖)
5. 启动 pywebview 控制台
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
from pathlib import Path


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _elevate():
    """以管理员重新启动自己"""
    params = " ".join(f'"{a}"' for a in sys.argv)
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    if ret > 32:
        sys.exit(0)
    # 用户拒绝提权 → 以普通权限继续(挂机功能将不可用)
    print("未获得管理员权限,挂机/热键功能将不可用,仅可使用识别类功能")


def _driver_available() -> bool:
    """用 pyinterception 库本身探测(与实际运行行为100%一致)"""
    try:
        import interception
        from interception.interception import Interception
        ctx = Interception()
        ok = bool(ctx.valid)
        ctx.destroy()
        return ok
    except Exception:
        return False


def _install_driver(installer: Path) -> str:
    """运行官方命令行安装器,返回人类可读结论"""
    try:
        result = subprocess.run([str(installer)], capture_output=True, text=True, timeout=30)
        out = (result.stdout or "") + (result.stderr or "")
    except Exception as e:
        return f"安装器执行失败: {e}"
    if _driver_available():
        return "Interception 驱动已就绪"
    if "restart" in out.lower() or "重启" in out:
        return "驱动已安装,需要重启电脑后生效"
    return f"驱动安装器输出: {out.strip()[:200] or '(无输出)'}"


def _boot_error(exc: Exception):
    """无控制台模式下启动失败的兜底: 写日志文件 + 弹窗"""
    try:
        log = Path(sys.executable).parent / "boot_error.log"
        log.write_text(str(exc), encoding="utf-8")
        ctypes.windll.user32.MessageBoxW(
            None, f"启动失败,详情见:\n{log}\n\n{exc}", "洛克王国助手", 0x10)
    except Exception:
        pass


def main() -> None:
    smoke = "--smoke" in sys.argv  # 自测模式: 不提权/不装驱动/窗口自动关闭
    if getattr(sys, "frozen", False):
        try:
            _run_frozen(smoke)
        except Exception as exc:
            # --noconsole 模式没有控制台,启动异常必须落到文件并弹窗
            import traceback
            detail = traceback.format_exc()
            print(detail)
            _boot_error(detail)
            raise


def _run_frozen(smoke: bool) -> None:
    if True:
        exe_root = Path(sys.executable).parent
        base = Path(sys._MEIPASS)
        if smoke:
            print("[SMOKE] 自测模式: 跳过提权与驱动安装")
        elif not _is_admin():
            _elevate()
        # ---- 1. 首次运行: 复制 data/ 到 exe 旁边 ----
        app_data = exe_root / "data"
        if not app_data.exists() and (base / "data").exists():
            shutil.copytree(base / "data", app_data)
        app_data.mkdir(parents=True, exist_ok=True)

        # ---- 2. 重定向各模块可写路径 ----
        import src.utils.settings as _settings
        _settings.PROJECT_ROOT = exe_root
        _settings.SETTINGS_PATH = exe_root / "data" / "config" / "settings.yaml"
        _settings.invalidate()

        import src.perception.vision_pipeline as _vp
        _vp.PROJECT_ROOT = exe_root
        _vp.DEFAULT_ROI_CONFIG = exe_root / "data" / "config" / "roi_config.json"

        import src.perception.ocr_reader as _ocr
        _ocr.PROJECT_ROOT = exe_root
        _ocr.ASSET_ROOT = exe_root / "data" / "vision"

        import src.perception.battle_detector as _bd
        _bd.PROJECT_ROOT = exe_root
        _bd.ASSET_ROOT = exe_root / "data" / "vision" / "battle"

        import src.pvp.pvp_pipeline as _pp
        _pp.PROJECT_ROOT = exe_root
        _pp.TEMPLATE_DIR = exe_root / "data" / "config" / "roi_templates"
        _pp.DEFAULT_TEMPLATE = _pp.TEMPLATE_DIR / "PVP标准模板.json"
        _pp.TESSDATA_DIR = base / "tessdata"  # 语言包保持只读随包
        _pp._APP_ENTRY_PATCHED = True  # 标记已修正路径,data_collector 等模块不再覆盖

        import src.pvp.roi_template as _rt
        _rt.TEMPLATE_DIR = exe_root / "data" / "config" / "roi_templates"

        import src.pvp.history_db as _hdb
        _hdb.DATA_DIR = exe_root / "data"
        _hdb.DB_PATH = exe_root / "data" / "history.db"

        import src.pvp.data_collector as _dc
        _dc.BASE = exe_root

        import src.gui.bridge as _bridge
        _bridge.PROJECT_ROOT = exe_root
        _bridge.CONFIG_DIR = exe_root / "data" / "config"
        _bridge.SCREENSHOT_DIR = exe_root / "data" / "screenshots"
        _bridge.WEB_DIR = base / "web"  # ROI 工坊等前端资源随包在 _MEIPASS/web

        import src.gui.auth as _auth
        _auth.AUTH_FILE = exe_root / "data" / "config" / "auth.json"

        # ---- 3. Interception 驱动 ----
        driver_note = "--smoke 测试跳过驱动检查"
        if not smoke:
            if not _driver_available():
                installer = base / "interception" / "install-interception.exe"
                if installer.exists():
                    driver_note = _install_driver(installer)
                    if not _driver_available():
                        driver_note += "(安装后需重启电脑一次,重启后本程序即可正常挂机)"
                else:
                    driver_note = "驱动安装器缺失,挂机/丢球功能不可用"
            else:
                driver_note = "Interception 驱动已就绪"

        # ---- 4. 启动控制台 ----
        from src.gui.bridge import AppBridge, Api
        import webview

        bridge = AppBridge()
        api = Api(bridge)
        bridge.set_api(api)  # ROI 工坊运行时创建独立窗需共用同一 Api 单例
        if driver_note:
            bridge._enqueue_log(f"驱动状态: {driver_note}", "warning" if "需重启" in driver_note or "不可用" in driver_note else "info")

        # 窗口尺寸自适应（与 main.py 一致: 物理像素计算 + 定尺后显示）
        from src.gui.window_sizing import (prewarm_c_extensions,
                                          compute_main_window_size,
                                          apply_window_size_physical)
        prewarm_c_extensions()   # 必须早于后面任何线程启动(防启动竞态闪退)
        phys_w, phys_h, _wa = compute_main_window_size()

        web_dir = base / "web"

        window = webview.create_window(
            title='洛克王国 · PVP 助手控制台',
            url=(web_dir / "index.html").as_uri(),
            js_api=api,
            width=1280, height=860,
            min_size=(880, 560),
            resizable=True,
            text_select=True,
            frameless=True,
            hidden=True,     # 定尺后再显示, 防闪大窗
            easy_drag=False)

        apply_window_size_physical(window, phys_w, phys_h, _wa)

        # 悬浮控制台: 与源码版一致(实测冻结版 WebView2 也能创建第二个窗口,
        # 之前误以为不支持而降级成 None, 会导致 set_pvp_float_window(None) 崩溃)
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
            hidden=True)

        bridge.set_window(window)
        bridge.set_widget_window(widget)
        bridge.set_pvp_float_window(widget)  # 合并悬浮窗: PVP 推演推送同窗
        window.events.closed += bridge.shutdown
        bridge.enable_hotkeys()

        if smoke:
            # 自测: 10 秒后自动关闭(给预热+建窗+定尺留足时间)
            import threading as _th
            _th.Timer(10.0, lambda: window.destroy()).start()
        webview.start()


if __name__ == "__main__":
    main()
