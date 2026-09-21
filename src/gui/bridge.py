# -*- coding: utf-8 -*-
"""
大前端桥接层 AppBridge

五个部分:
1. 丢球工具   —— 包装 AutoThrowBall,延迟参数实时可调
2. 视觉调试   —— 游戏窗口截图预览 + 识别管线结果(纯读屏,无键鼠操作)
3. 工具箱     —— 子进程启动 tools/ 独立工具,CLI 输出回流日志
4. 配置中心   —— settings.yaml / roi_config.json / throw_ball_config.json 读写校验
5. 任务注册表 —— 底部任务栏数据源(正在运行的模式/工具)

设计原则: 暴露给 JS 的方法只做轻量操作,耗时动作在后台线程/子进程。
"""

import base64
import json
import os
import queue
import subprocess
import sys
import threading
from src.gui.updater import AutoUpdater, check_update, apply_update, updater_status
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 前端资源目录: 源码=src/gui/web; 冻结版由 app_entry 重定向到 sys._MEIPASS/web
WEB_DIR = Path(__file__).resolve().parent / "web"

from auto_throw_ball import AutoThrowBall  # noqa: E402

# ========================================
# 配置中心: 可编辑文件注册表
# ========================================

CONFIG_DIR = PROJECT_ROOT / "data" / "config"
CONFIG_FILES = {
    "throw_ball_config.json": {
        "title": "丢球与按键延时",
        "icon": "⚾",
        "type": "json",
        "desc": "普通丢球/轰炸机/技能按键延迟与遭遇战斗退出开关（丢球助手页面滑杆自动写入）",
        "page_hint": "丢球助手",
        "gui_page": "throw",
        "fields": [
            {"key": "normal_min / normal_max", "name": "普通蓄力时间", "desc": "普通丢球单次鼠标左键蓄力时间范围（秒），推荐 0.35s ~ 0.5s"},
            {"key": "bomber_charge_min / bomber_charge_max", "name": "轰炸机蓄力时间", "desc": "轰炸机模式丢球鼠标左键蓄力时间范围（秒），推荐 0.3s ~ 0.5s"},
            {"key": "bomber_hover_min / bomber_hover_max", "name": "悬浮按空格间隔", "desc": "轰炸机模式保持飞行高度的空格按键间隔（秒），推荐 2.0s ~ 2.2s"},
            {"key": "skill_min / skill_max", "name": "技能释放间隔", "desc": "自动技能模式交替按 3 与 X 键的时间间隔（秒），推荐 1.0s ~ 2.0s"},
            {"key": "exit_on_battle", "name": "遭遇战斗自动退出", "desc": "是否在检测到遭遇战斗画面时立即自动停止丢球与按键（true/false）"}
        ]
    },
    "settings.yaml": {
        "title": "挂机引擎与全局设置",
        "icon": "⚔️",
        "type": "yaml",
        "desc": "挂机战斗策略、技能轮换、巡逻走动与全局超时设置（挂机引擎页面表单自动写入）",
        "page_hint": "挂机引擎",
        "gui_page": "engine",
        "fields": [
            {"key": "battle.catch_hp", "name": "捕获血线阈值", "desc": "敌方血量百分比小于等于此数值时自动按键丢球（默认 50%）"},
            {"key": "battle.open_ball_key", "name": "打开丢球界面键", "desc": "战斗中用于呼出丢球界面的键盘按键（默认 w）"},
            {"key": "battle.ball_slot_key", "name": "球槽按键", "desc": "丢球界面中对应球槽的数字键（默认 1）"},
            {"key": "battle.skills", "name": "技能轮换列表", "desc": "未到丢球血线时按顺序释放的技能按键列表（如 [\"1\"]）"},
            {"key": "patrol.enabled", "name": "巡逻找怪开关", "desc": "战斗间隙是否自动走动找怪（true/false）"},
            {"key": "patrol.move_key", "name": "巡逻走动键", "desc": "巡逻时持续按住的键盘走动键（默认 w）"},
            {"key": "patrol.turn_mode", "name": "巡逻转向方式", "desc": "mouse 为鼠标平滑转动镜头，keys 为 A/D 键侧移转向"}
        ]
    },
    "roi_config.json": {
        "title": "画面识别区域 (ROI)",
        "icon": "📐",
        "type": "json",
        "desc": "战斗中精灵名、血量、属性图标所在屏幕归一化百分比坐标（视觉调试台拖框标注同源）",
        "page_hint": "视觉调试台",
        "gui_page": "vision",
        "fields": [
            {"key": "enemy_name", "name": "敌方精灵名称区域", "desc": "对战 HUD 上方敌方精灵名字所在的坐标矩形 {left, top, width, height}"},
            {"key": "enemy_hp", "name": "敌方血量百分比区域", "desc": "敌方血条旁百分比数字（如 100%）所在的坐标矩形"},
            {"key": "enemy_elements", "name": "敌方属性图标区域", "desc": "敌方属性主图标所在区域"},
            {"key": "battle_left / battle_right", "name": "战斗判定角标", "desc": "用于模板匹配判断是否在战斗中的 UI 角标区域"}
        ]
    },
    "pet_names.txt": {
        "title": "精灵名称词库",
        "icon": "📖",
        "type": "txt",
        "desc": "OCR 精灵名识别纠错词库，每行一个精灵名。游戏出新精灵时可在此另起一行添加",
        "page_hint": "词库字典",
        "gui_page": "",
        "fields": [
            {"key": "每行一个精灵名称", "name": "精灵词条", "desc": "包含迪莫、喵喵、火神等 600+ 常见精灵全称。OCR 模糊识别时会优先在此名单中寻找最相似匹配。"}
        ]
    },
}

# 每个丢球延迟参数的合法范围（秒）
CONFIG_SCHEMA = {
    "normal_min":        (0.1, 3.0),
    "normal_max":        (0.1, 3.0),
    "bomber_charge_min": (0.05, 2.0),
    "bomber_charge_max": (0.05, 2.0),
    "bomber_hover_min":  (0.3, 8.0),
    "bomber_hover_max":  (0.3, 8.0),
    "skill_min":         (0.2, 10.0),
    "skill_max":         (0.2, 10.0),
    "stop_after_count":  (0, 99999),
    "stop_after_minutes": (0, 720),
}
CONFIG_PAIRS = [
    ("normal_min", "normal_max"),
    ("bomber_charge_min", "bomber_charge_max"),
    ("bomber_hover_min", "bomber_hover_max"),
    ("skill_min", "skill_max"),
]

# ========================================
# 运行模式: 源码运行默认开发者版; PyInstaller 打包强制用户版。
# 安全: 打包版不接受 LKW_DEV_MODE 环境变量(否则用户设 =1 即可白嫖付费功能);
# 开发者要预览用户版体验, 在源码运行时设 LKW_DEV_MODE=0。
# ========================================
if getattr(sys, "frozen", False):
    DEV_MODE = False
else:
    _env_dev = os.environ.get("LKW_DEV_MODE")
    DEV_MODE = (_env_dev != "0")

# ========================================
# 工具箱: 可启动工具注册表
# ========================================

TOOLS = [
    {"id": "snip", "name": "手动框选截图", "script": "tools/snip_capture.py",
     "gui": True, "arg": "none", "category": "visual", "tag": "GUI 标注",
     "desc": "全屏暗化拖拽框选任意区域，保存后自动打开裁剪工具（制作角标模板首选）"},
    {"id": "crop", "name": "模板裁剪工具", "script": "tools/crop_template_tool.py",
     "gui": True, "arg": "shot", "category": "visual", "tag": "GUI 标注",
     "desc": "自动截取游戏窗口并打开裁剪器（可视化裁剪并保存左右角标模板）"},
    {"id": "clicker", "name": "鼠标连点器", "script": "tools/auto_click_macro.py",
     "gui": True, "arg": "none", "category": "helper", "tag": "独立小窗",
     "desc": "独立置顶小窗连点器，F6 取坐标 / F7 开关 / F10 急停（全局热键）"},
    {"id": "envcheck", "name": "截图环境诊断", "script": "tools/check_capture_env.py",
     "gui": False, "arg": "none", "category": "diag", "tag": "环境诊断",
     "desc": "检查 Windows 窗口句柄获取能力与截图权限，诊断输出到运行日志"},
    {"id": "demovision", "name": "视觉管线测试", "script": "tools/demo_vision_pipeline.py",
     "gui": False, "arg": "last", "category": "diag", "tag": "管线自检",
     "desc": "对最新游戏画面测试 OCR 与战斗角标匹配，检测识别是否正常"},
    {"id": "roiexport", "name": "ROI 切片导出", "script": "tools/export_roi_samples.py",
     "gui": False, "arg": "last", "category": "diag", "tag": "切片导出",
     "desc": "按 ROI 配置把最近游戏画面切成小图批量导出到 data/vision/exports"},
    {"id": "diag_hp", "name": "血量 OCR 诊断", "script": "tools/diag_hp.py",
     "gui": False, "arg": "last", "category": "diag", "tag": "OCR 诊断",
     "desc": "截取敌方血量区域并打印 4 种二值化阈值与 Tesseract 识别细节"},
    {"id": "test_pvp", "name": "PVP 引擎自检", "script": "tools/test_pvp_full.py",
     "gui": False, "arg": "none", "category": "diag", "tag": "PVP 自检",
     "desc": "全量测试 PVP 伤害计算、属性克制倍率与精灵/技能数据库完整性"},
]
SCREENSHOT_DIR = PROJECT_ROOT / "data" / "screenshots"


class AppBridge:
    """大前端前后端桥梁"""

    def __init__(self):
        # C 扩展预热: 在任何后台线程启动之前完成首次导入, 消除
        # "线程内首次 import win32ui 撞上 keyboard 初始化的 GC" 导致的
        # access violation 随机闪退(启动日志 6 次转储同一签名)。
        # 这里再兜一次, 任何入口(含独立工具/ROI 工坊)走 AppBridge 都被保护。
        try:
            from src.gui.window_sizing import prewarm_c_extensions
            prewarm_c_extensions()
        except Exception:
            pass

        self._window = None
        self._log_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._pusher_thread = None
        # 自动更新器: 后台静默检查 GitHub 新版本(仅提示, 不自动改文件)
        self._update_hint_sent = None
        self.updater = AutoUpdater(on_update_available=self._notify_update_available)

        # 丢球核心工具
        self.tool = AutoThrowBall(on_log=self._enqueue_log)
        self.tool._frame_provider = self._capture_frame
        # 日常任务执行器(MAA 式): 复用截图管线与全停体系
        try:
            from src.tasks.daily_runner import DailyRunner
            self.daily = DailyRunner(self._capture_frame, self._enqueue_log,
                                     launch_cb=self.game_launch)
        except Exception:
            self.daily = None
        # 快捷键 F4/F9/F10 直接调 tool 内部方法, 绕过 GUI 入口的互斥逻辑,
        # 用钩子补上: 快捷键启动丢球组前自动停止挂机引擎/PVP识别
        self.tool.conflict_hook = lambda: self._stop_conflicting_modes("throw")
        self._load_throw_config()

        # 咕噜球监视(战斗前 1 号位, 蓄力窗口异步采样; ROI/模板缺失时自动禁用)
        try:
            from src.perception.ball_watcher import BallSlotWatcher
            self.ball_watcher = BallSlotWatcher(
                frame_provider=self._capture_frame, on_log=self._enqueue_log)
            if self.ball_watcher.enabled:
                self.tool.attach_ball_watcher(self.ball_watcher)
        except Exception as e:
            self.ball_watcher = None
            self._enqueue_log(f"咕噜球监视初始化失败(不影响丢球): {e}", "warning")

        # 视觉调试状态
        self._last_shot_path: Path | None = None  # 最近一次保存的截图
        self._last_frame = None                    # 最近一次识别用的帧(numpy)
        self._paddleocr = None                     # PaddleOCR 实例（懒加载）

        # 实时识别
        self._live_running = False
        self._live_thread = None
        self._live_interval = 0.15                  # 秒
        self._live_pipeline = None
        self._live_black_warned = False
        self._live_last_frame = None               # 帧差检测缓存
        self._fast_cap = None                      # FastCapture 单例
        self._live_max_width = 960                 # 实时预览画质(fast=960/hd=1440/full=0原尺寸)

        # 战斗引擎
        from src.states.battle_engine import BattleEngine
        self.engine = BattleEngine(
            frame_provider=self._live_capture_frame,
            on_log=self._enqueue_log,
            dry_run=False)

        # 异色全停回调: 引擎发现异色时联动停所有其它任务(丢球助手等)
        self.engine._stop_all_cb = lambda reason: self.stop_all()

        # PVP 悬浮窗
        self._pvp_float_window = None
        self._pvp_float_visible = False
        self._pvp_float_loaded = False

        # 观察模式: 挂机悬浮窗的被动战情监视(引擎/工具都没跑时才工作)
        self._watch = None            # {in_battle, enemy_name, enemy_hp}
        self._watch_pipeline = None
        self._watch_started = threading.Event()
        self._last_widget_pos = None  # 悬浮窗物理像素落点(show 后重钉)

        # PVP 实时识别引擎
        self._pvp_running = False
        self._pvp_thread = None
        self._pvp_interval = 0.5  # 秒，每 500ms 识别一帧

        # 模式控制器 (Step 3: 生命周期隔离)
        from src.states.mode_controller import ModeController
        self.mode_ctrl = ModeController()

        # 工具子进程: id -> {"proc", "name"}
        self._tool_procs: dict[str, dict] = {}

    # ========================================
    # 生命周期
    # ========================================

    def set_window(self, window):
        self._window = window
        self._start_log_pusher()
        self._start_watch_loop()  # 观察模式: 悬浮窗的被动战情监视

    def set_widget_window(self, window):
        """设置悬浮状态窗引用(初始隐藏,由用户/热键唤出); 允许 None(降级为无悬浮窗)"""
        self._widget = window
        self._widget_visible = False
        self._last_widget_pos = None   # 物理像素落点(show 后重新钉回用)


    def set_api(self, api):
        """注入 Api 转发层单例，供运行时创建的独立窗 (ROI 工坊) 共用"""
        self._api = api

    def set_on_top(self, enabled: bool) -> dict:
        """控制台窗口置顶开关(悬浮在游戏上方查看,不抢游戏焦点)
        兼容 pywebview 4.x(方法调用) 与 6.x(on_top 为属性,setter 生效)"""
        if not self._window:
            return {"success": False, "message": "窗口未就绪"}
        try:
            prop = type(self._window).on_top
            if isinstance(prop, property):
                self._window.on_top = bool(enabled)   # 6.x: 属性 setter
            else:
                self._window.on_top(bool(enabled))    # 4.x/5.x: 方法调用
            ok = True
            try:
                ok = bool(self._window.on_top) == bool(enabled) or not isinstance(prop, property)
            except Exception:
                pass
            return {"success": ok, "on_top": bool(enabled)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ========================================
    # 悬浮状态窗
    # ========================================

    def widget_toggle(self) -> dict:
        """显示/隐藏悬浮状态窗"""
        if not getattr(self, "_widget", None):
            return {"success": False, "message": "悬浮窗未创建"}
        try:
            if self._widget_visible:
                self._widget.hide()
                self._widget_visible = False
            else:
                last_pos = self._last_widget_pos
                self._place_widget()
                self._widget.show()
                self._widget_visible = True
                # show() 会 Activate 并可能重置位置, 显示后按物理像素再钉一次
                self._ensure_widget_on_screen()
                self._reassert_widget_pos()
                try:
                    x = self._widget.x
                    y = self._widget.y
                    w = self._widget.width
                    h = self._widget.height
                    self._enqueue_log(f"[DEBUG] Widget window position: x={x}, y={y}, w={w}, h={h}", "info")
                    self._enqueue_log(f"[DEBUG] Widget is on_top: {getattr(self._widget, 'on_top', None)}", "info")
                except Exception as e:
                    self._enqueue_log(f"[DEBUG] Failed to get widget position: {e}", "warning")
                self._enqueue_log(f"[DEBUG] Widget window shown, visible={self._widget_visible}", "info")
                # 显示后按当前内容(含记忆的折叠状态)校准尺寸
                try:
                    self._widget.evaluate_js("if (typeof syncSize === 'function') syncSize()")
                except Exception:
                    pass
                # 前端 syncSize 会改窗口尺寸(高度变化可能溢出下边界), 稍后再自愈一次
                try:
                    threading.Timer(0.6, self._on_widget_sized).start()
                except Exception:
                    pass
                self._refocus_game_window_async()
            return {"success": True, "visible": self._widget_visible}
        except Exception as e:
            self._enqueue_log(f"[ERROR] widget_toggle error: {e}", "error")
            import traceback
            self._enqueue_log(traceback.format_exc(), "error")
            return {"success": False, "message": str(e)}

    def _reassert_widget_pos(self):
        """按上次落点再钉一次(show() 之后调用, 防 Activate 复位)"""
        pos = getattr(self, "_last_widget_pos", None)
        if not pos:
            return
        self._set_widget_pos(*self._clamp_widget_pos(*pos))

    def _on_widget_sized(self):
        """前端校准尺寸之后的收尾: 记录新落点并保证仍在屏内"""
        r = self._window_rect(self._widget_hwnd())
        if r:
            self._last_widget_pos = (int(r[0]), int(r[1]))
        self._ensure_widget_on_screen()

    def _focus_game_window(self):
        """将 Windows 激活焦点与输入捕获无缝交还给游戏窗口，确保 3D 视角不脱离"""
        try:
            game_hwnd = self.tool.get_game_hwnd()
            if game_hwnd:
                import win32gui
                win32gui.SetForegroundWindow(game_hwnd)
        except Exception:
            pass

    def _refocus_game_window_async(self, delay: float = 0.08):
        """异步延迟交还游戏焦点，防止 pywebview 窗口动画争抢激活"""
        def _job():
            import time
            time.sleep(delay)
            self._focus_game_window()
        threading.Thread(target=_job, daemon=True).start()

    # ---------- 悬浮窗定位: 物理像素工具 ----------
    # 重要单位约定(pywebview winforms 后端):
    #   move(x, y)      入参是 CSS/逻辑像素, 后端内部会再乘一次显示缩放 → 物理像素
    #   resize(w, h)    入参已是物理像素, 后端原样透传给 SetWindowPos
    # 而 _monitor_workarea()/find_window()/GetWindowRect 拿到的都是物理像素。
    # 两者直接混用会被二次放大推出屏幕(150% 缩放下 2075 → 3112), 故绝对定位
    # 一律走 SetWindowPos 直传物理像素, 不经过 move()。

    @staticmethod
    def _native_hwnd(window):
        """取 pywebview 窗口的原生句柄(6.x 用 .native, 旧版可能有 native_handle)"""
        try:
            h = getattr(window, "native_handle", None)
            if h:
                return int(h)
        except Exception:
            pass
        try:
            native = getattr(window, "native", None)
            if native is None:
                return 0
            h = native.Handle
            return int(h.ToInt32()) if hasattr(h, "ToInt32") else int(h)
        except Exception:
            return 0

    def _widget_hwnd(self) -> int:
        return self._native_hwnd(getattr(self, "_widget", None))

    @staticmethod
    def _u32():
        """独立的 user32 句柄: argtypes 与 ctypes.windll.user32 不共享。

        auto_throw_ball 给 windll.user32 的若干函数设过全局 argtypes(如 GetWindowRect
        要求传它自建的 RECT), 直接复用会让本文件的调用抛 ArgumentError。
        """
        try:
            import ctypes
            return ctypes.WinDLL("user32")
        except Exception:
            import ctypes
            return ctypes.windll.user32

    @classmethod
    def _window_rect(cls, hwnd: int):
        """原生窗口矩形 (left, top, right, bottom)。

        优先走 pywin32(不经过 ctypes, 不受上述 argtypes 污染影响);
        退回独立 WinDLL 实例调用, 不去改全局签名。
        """
        if not hwnd:
            return None
        try:
            import win32gui
            l, t, r, b = win32gui.GetWindowRect(int(hwnd))
            if r - l > 0 and b - t > 0:
                return int(l), int(t), int(r), int(b)
        except Exception:
            pass
        try:
            import ctypes

            class _RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            r = _RECT()
            if cls._u32().GetWindowRect(ctypes.c_void_p(int(hwnd)), ctypes.byref(r)):
                if r.right - r.left > 0 and r.bottom - r.top > 0:
                    return int(r.left), int(r.top), int(r.right), int(r.bottom)
        except Exception:
            pass
        return None

    @staticmethod
    def _scale_for_hwnd(hwnd: int) -> float:
        """窗口所在显示器的缩放比(物理 = CSS × 该值), 多屏各自取自己的"""
        import ctypes
        if hwnd:
            try:
                dpi = ctypes.windll.user32.GetDpiForWindow(int(hwnd))
                if dpi:
                    return dpi / 96.0
            except Exception:
                pass
        try:
            s = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
            return s if s > 0 else 1.0
        except Exception:
            return 1.0

    def _set_widget_pos(self, x, y) -> bool:
        """把悬浮窗钉到物理像素 (x, y): 优先 SetWindowPos 直传, 回退 move() 前先除回缩放"""
        x, y = int(x), int(y)
        hwnd = self._widget_hwnd()
        if hwnd:
            try:
                import ctypes
                SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
                self._u32().SetWindowPos(
                    ctypes.c_void_p(int(hwnd)), None, x, y, 0, 0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                return True
            except Exception:
                pass
        try:
            s = float(getattr(getattr(self._widget, "native", None), "scale_factor", 1) or 1)
            s = s if s > 0 else 1.0
            self._widget.move(int(round(x / s)), int(round(y / s)))
            return True
        except Exception:
            return False

    def _clamp_widget_pos(self, x, y, workarea=None):
        """夹取到工作区内, 保证整个窗口可见(挡掉任何来源的越界坐标)

        工作区与窗口尺寸都取物理像素(窗口尺寸走 _widget_physical_size),
        不能混用 pywebview 的逻辑 width/height, 否则夹取值本身就会偏。
        workarea 缺省用游戏所在屏; 传 _nearest_workarea() 可按窗口当前所在屏夹取。
        """
        try:
            wa_l, wa_t, wa_r, wa_b = workarea or self._monitor_workarea()
            ww, wh = self._widget_physical_size()
            return (int(min(max(x, wa_l), max(wa_l, wa_r - ww))),
                    int(min(max(y, wa_t), max(wa_t, wa_b - wh))))
        except Exception:
            return int(x), int(y)

    @staticmethod
    def _all_workareas():
        """所有显示器的工作区列表 [(l, t, r, b), ...] (物理像素)"""
        out = []
        try:
            import win32api
            for hmon, _, _ in win32api.EnumDisplayMonitors():
                try:
                    info = win32api.GetMonitorInfo(hmon)
                    r = info.get("Work") or info.get("Monitor")
                    if r:
                        out.append((int(r[0]), int(r[1]), int(r[2]), int(r[3])))
                except Exception:
                    continue
        except Exception:
            pass
        if out:
            return out
        # 退回主屏工作区
        try:
            import ctypes

            class _RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            r = _RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(r), 0):
                return [(int(r.left), int(r.top), int(r.right), int(r.bottom))]
        except Exception:
            pass
        return [(0, 0, 1920, 1040)]

    def _nearest_workarea(self, x, y):
        """离点 (x, y) 最近的显示器工作区(物理像素), 多屏下按窗口实际所在屏夹取"""
        areas = self._all_workareas()
        if not areas:
            return self._monitor_workarea()
        best, best_d = areas[0], None
        for (l, t, r, b) in areas:
            # 矩形内距离为 0(优先完全包含该点的屏), 否则取最近边距离
            dx = 0 if l <= x <= r else min(abs(x - l), abs(x - r))
            dy = 0 if t <= y <= b else min(abs(y - t), abs(y - b))
            d = dx * dx + dy * dy
            if best_d is None or d < best_d:
                best, best_d = (l, t, r, b), d
        return best

    def _is_pos_reachable(self, x, y) -> bool:
        """点 (x, y) 是否落在任一显示器工作区内"""
        for (l, t, r, b) in self._all_workareas():
            if l <= x <= r and t <= y <= b:
                return True
        return False

    def _ensure_widget_on_screen(self):
        """自愈(自动路径专用): 越界就钉回, 要求窗口**完整**可见。

        按窗口当前所在屏夹取, 多屏下不会把用户拖到副屏的窗口拽回游戏所在屏。
        与拖拽路径的宽松策略不同: 那是用户主动摆放, 只要标题条可抓就放行;
        这里是程序自动定位, 必须保证内容不被切掉。
        """
        r = self._window_rect(self._widget_hwnd())
        if not r:
            return
        try:
            l, t, rr, bb = r
            wa = self._nearest_workarea(l, t)
            wa_l, wa_t, wa_r, wa_b = wa
            if l >= wa_l and t >= wa_t and rr <= wa_r and bb <= wa_b:
                return
            nx, ny = self._clamp_widget_pos(l, t, wa)
            if (nx, ny) != (l, t):
                self._set_widget_pos(nx, ny)
                self._last_widget_pos = (int(nx), int(ny))
                self._enqueue_log(
                    f"悬浮窗越界 ({l},{t}) → 已复位 ({nx},{ny})", "warning")
        except Exception:
            pass

    def _monitor_workarea(self):
        """工作区 (left, top, right, bottom): 优先游戏窗口所在显示器(多显示器: 游戏在哪屏,
        悬浮窗就该落在哪屏的空闲侧), 找不到游戏则兜底主屏工作区"""
        import ctypes

        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                        ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]

        user32 = ctypes.windll.user32
        try:
            hwnd = self.tool.get_game_hwnd()
            if hwnd:
                hmon = user32.MonitorFromWindow(hwnd, 2)   # MONITOR_DEFAULTTONEAREST
                info = _MONITORINFO()
                info.cbSize = ctypes.sizeof(_MONITORINFO)
                if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                    r = info.rcWork
                    return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
        try:
            wa = _RECT()
            # SPI_GETWORKAREA: 主屏工作区(去掉任务栏)
            if user32.SystemParametersInfoW(48, 0, ctypes.byref(wa), 0):
                return wa.left, wa.top, wa.right, wa.bottom
        except Exception:
            pass
        return 0, 0, 1920, 1040

    def _compute_widget_position(self):
        """计算悬浮窗默认落点(物理像素): 不遮挡游戏优先, 游戏近乎全屏则贴游戏所在屏右缘垂直居中"""
        try:
            wa_l, wa_t, wa_r, wa_b = self._monitor_workarea()
            wa_w, wa_h = wa_r - wa_l, wa_b - wa_t

            # _monitor_workarea/find_window 都是物理像素, 窗口尺寸同样按物理取
            ww, wh = self._widget_physical_size()
            margin = 8

            game = None
            try:
                from src.capture.window_capture import find_window
                game = find_window(class_name="UnrealWindow")
            except Exception:
                pass

            # 最小化的游戏窗口坐标是 (-32000,-32000), 直接参与计算会把悬浮窗
            # 甩到几万像素外(磁贴化的"看不见"), 必须当作没有游戏
            if game is not None:
                try:
                    import win32gui
                    if win32gui.IsIconic(int(game.hwnd)):
                        game = None
                except Exception:
                    pass
                if game is not None:
                    gl, gt, gr, gb = game.rect
                    if (gl <= -10000 or gt <= -10000 or gr <= -10000 or gb <= -10000
                            or game.width <= 0 or game.height <= 0):
                        game = None

            # 游戏近乎全屏(占工作区 85% 以上) → 直接贴屏幕右缘垂直居中
            is_fullscreen = game is None or (
                game.width >= wa_w * 0.85 and game.height >= wa_h * 0.85)

            def _clamp(x, y):
                return self._clamp_widget_pos(int(x), int(y))

            if not is_fullscreen and game:
                gl, gt, gr, gb = game.rect
                # 游戏右侧的空隙(且游戏本身要在工作区附近, 否则落点不可信)
                x = gr + margin
                if (x + ww <= wa_r - margin and gr > wa_l - ww
                        and gr < wa_r + ww):
                    y = max(wa_t + margin, min(gt, wa_b - wh - margin))
                    return _clamp(x, y)
                # 次选: 游戏左侧的空隙
                x = gl - margin - ww
                if (x >= wa_l + margin and gl >= wa_l - ww
                        and gl < wa_r + ww):
                    y = max(wa_t + margin, min(gt, wa_b - wh - margin))
                    return _clamp(x, y)

            # 兜底: 屏幕最右缘,垂直居中
            x = wa_r - ww - margin
            y = wa_t + (wa_h - wh) // 2
            return _clamp(x, y)
        except Exception:
            return None

    def _widget_physical_size(self):
        """悬浮窗当前尺寸(物理像素): 优先读真实窗口矩形, 退回 pywebview 逻辑尺寸 × 缩放"""
        r = self._window_rect(self._widget_hwnd())
        if r:
            w, h = r[2] - r[0], r[3] - r[1]
            if w > 0 and h > 0:
                return int(w), int(h)
        try:
            s = self._scale_for_hwnd(self._widget_hwnd())
            w = int(getattr(self._widget, "width", 340) or 340)
            h = int(getattr(self._widget, "height", 335) or 335)
            return int(w * s), int(h * s)
        except Exception:
            return 340, 335

    def _place_widget(self):
        """显示悬浮窗前统一入口: 优先恢复上次拖放位置, 否则计算默认落点。

        两者都是物理像素, 且一律经 _clamp_widget_pos 夹到工作区内 —— 历史脏坐标
        (曾被 DPI 二次放大的值)不会再让窗口飞到屏幕外。
        """
        pos = None
        try:
            saved = self._load_widget_state().get("pos")
            if (isinstance(saved, (list, tuple)) and len(saved) == 2):
                pos = (int(saved[0]), int(saved[1]))
        except Exception:
            pos = None
        if pos is None:
            pos = self._compute_widget_position()
        else:
            fixed = self._clamp_widget_pos(*pos)
            if fixed != pos:
                # 历史脏坐标(旧版本按逻辑像素写入/曾被二次放大): 夹正后回写, 免得起一次夹一次
                try:
                    self._save_widget_state(pos=[int(fixed[0]), int(fixed[1])])
                except Exception:
                    pass
                self._enqueue_log(
                    f"悬浮窗保存位置 {pos} 已越界 → 修正为 {fixed}", "warning")
            pos = fixed
        if pos:
            self._enqueue_log(f"[DEBUG] 悬浮窗落点: x={pos[0]}, y={pos[1]}", "info")
            if self._set_widget_pos(*pos):
                self._last_widget_pos = (int(pos[0]), int(pos[1]))
                return
        # 兜底: 工作区内左上角偏移(同样走物理像素, 避免被二次缩放推出屏幕)
        fallback = self._clamp_widget_pos(50, 50)
        self._set_widget_pos(*fallback)
        self._last_widget_pos = (int(fallback[0]), int(fallback[1]))


    def auto_minimize_and_show_widget(self):
        """挂机/丢球启动时：自动弹出悬浮窗、最小化主界面，并将焦点交还给 3D 游戏窗口"""
        try:
            if getattr(self, "_widget", None):
                self._place_widget()   # 之前直接 show(), 窗口总落在创建默认位(主屏左上角)
                self._widget.show()
                self._widget_visible = True
                # show() 会 Activate 并可能重置位置, 显示后按物理像素再钉一次
                self._ensure_widget_on_screen()
                self._reassert_widget_pos()
                try:
                    threading.Timer(0.6, self._on_widget_sized).start()
                except Exception:
                    pass
                try:
                    x = self._widget.x
                    y = self._widget.y
                    w = self._widget.width
                    h = self._widget.height
                    self._enqueue_log(f"[DEBUG] Widget window position: x={x}, y={y}, w={w}, h={h}", "info")
                    self._enqueue_log(f"[DEBUG] Widget is on_top: {getattr(self._widget, 'on_top', None)}", "info")
                except Exception as e:
                    self._enqueue_log(f"[DEBUG] Failed to get widget position: {e}", "warning")
                self._enqueue_log(f"[DEBUG] Widget window shown, visible={self._widget_visible}", "info")
        except Exception:
            pass
        try:
            if getattr(self, "_window", None):
                self._window.minimize()
        except Exception:
            pass
        self._refocus_game_window_async(0.1)

    def minimize_window(self) -> dict:
        """最小化主窗口并交还游戏焦点"""
        try:
            if getattr(self, "_window", None):
                self._window.minimize()
                self._refocus_game_window_async(0.08)
                return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}
        return {"success": False, "message": "主窗口未就绪"}

    def window_move_by(self, dx: int, dy: int) -> dict:
        """主窗口按增量移动(自绘标题栏拖拽, 与悬浮窗拖拽同机制)"""
        if not getattr(self, "_window", None):
            return {"success": False, "message": "窗口未就绪"}
        try:
            x = int(self._window.x or 0)
            y = int(self._window.y or 0)
            self._window.move(x + int(dx), y + int(dy))
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def window_get_size(self) -> dict:
        """读取主窗口当前尺寸(缩放手柄手势起点用, 每次手势只读一次)"""
        if not getattr(self, "_window", None):
            return {"success": False, "message": "窗口未就绪"}
        try:
            return {"success": True,
                    "width": int(self._window.width or 1320),
                    "height": int(self._window.height or 860)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def window_resize_to(self, width: int, height: int) -> dict:
        """主窗口缩放到绝对尺寸(左上角锚定, 绝对协议避免读改竞争抖动)"""
        if not getattr(self, "_window", None):
            return {"success": False, "message": "窗口未就绪"}
        try:
            nw = max(1080, min(3840, int(width)))
            nh = max(720, min(2160, int(height)))
            try:
                from webview.window import FixPoint
                fp = FixPoint.NORTH | FixPoint.WEST
            except Exception:
                fp = 3  # NORTH | WEST
            self._window.resize(nw, nh, fp)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def window_resize_by(self, dw: int, dh: int) -> dict:
        """主窗口按增量调整尺寸(右下角手柄), 左上角锚定, 限制在 min_size 范围"""
        if not getattr(self, "_window", None):
            return {"success": False, "message": "窗口未就绪"}
        try:
            w = int(self._window.width or 1320)
            h = int(self._window.height or 860)
            nw = max(1080, min(3840, w + int(dw)))
            nh = max(720, min(2160, h + int(dh)))
            try:
                from webview.window import FixPoint
                fp = FixPoint.NORTH | FixPoint.WEST
            except Exception:
                fp = 3  # NORTH | WEST
            self._window.resize(nw, nh, fp)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def window_close(self) -> dict:
        """关闭主窗口(走 closed 事件 -> shutdown 持久化, 与系统关闭按钮同路径)"""
        if not getattr(self, "_window", None):
            return {"success": False, "message": "窗口未就绪"}
        try:
            self._window.destroy()
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def move_window_by(self, dx: int, dy: int) -> dict:
        """按增量移动悬浮窗(自研拖拽后端,不依赖窗口焦点), 并节流记住拖放位置

        单位: 前端 e.screenX 是 CSS 像素, 位移需乘缩放才是物理像素位移;
        当前坐标一律读真实窗口矩形(物理), 避免与逻辑坐标混算。
        """
        if not getattr(self, "_widget", None):
            return {"success": False}
        try:
            ww, wh = self._widget_physical_size()
            cx, cy = self._widget_physical_topleft()
            s = self._scale_for_hwnd(self._widget_hwnd())
            nx = cx + int(round(int(dx) * s))
            ny = cy + int(round(int(dy) * s))
            # 按目标点所在屏夹取(多屏下可正常跨屏拖), 并保证标题条留在屏内可抓
            wa_l, wa_t, wa_r, wa_b = self._nearest_workarea(nx, ny)
            nx = max(wa_l - ww + 80, min(int(nx), wa_r - 80))
            ny = max(wa_t, min(int(ny), wa_b - 40))
            self._set_widget_pos(nx, ny)
            self._last_widget_pos = (int(nx), int(ny))
            # 记住拖放位置(拖动中 rAF 高频调用, 节流写盘)
            now = time.time()
            if now - getattr(self, "_last_pos_save", 0.0) > 1.5:
                self._last_pos_save = now
                self._save_widget_state(pos=[int(nx), int(ny)])
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _widget_physical_topleft(self):
        """悬浮窗左上角物理坐标(读真实矩形, 失败退回 pywebview 逻辑值×缩放)"""
        r = self._window_rect(self._widget_hwnd())
        if r:
            return int(r[0]), int(r[1])
        try:
            s = self._scale_for_hwnd(self._widget_hwnd())
            return int((self._widget.x or 0) * s), int((self._widget.y or 0) * s)
        except Exception:
            return 0, 0

    # ---------- 悬浮窗状态持久化(折叠/位置) ----------

    def _load_widget_state(self) -> dict:
        try:
            f = CONFIG_DIR / "widget_state.json"
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_widget_state(self, **kwargs):
        """读改写合并保存(折叠/位置互不覆盖)"""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            st = self._load_widget_state()
            st.update(kwargs)
            (CONFIG_DIR / "widget_state.json").write_text(
                json.dumps(st), encoding="utf-8")
        except Exception:
            pass

    def widget_get_state(self) -> dict:
        """悬浮窗持久化状态(折叠偏好/位置等)"""
        st = self._load_widget_state()
        return st if st else {"folded": False}

    def widget_set_folded(self, folded: bool) -> dict:
        """记住折叠偏好(合并保存, 不再覆盖位置)"""
        self._save_widget_state(folded=bool(folded))
        return {"success": True}

    def widget_resize(self, width: int = 340, height: int = 335) -> dict:
        """安全调整悬浮状态窗尺寸 (前端按内容真实物理像素传入)"""
        if not getattr(self, "_widget", None):
            return {"success": False, "message": "悬浮窗未创建"}
        # 关键: pywebview 的 resize 会把隐藏窗口强制显示出来,
        # 未显示时跳过,由 widget_toggle 在 show 后再触发前端校准
        if not getattr(self, "_widget_visible", False):
            return {"success": False, "message": "悬浮窗未显示,跳过 resize"}
        try:
            safe_w = max(280, min(600, int(width)))
            safe_h = max(36, min(900, int(height)))
            self._widget.resize(safe_w, safe_h)
            return {"success": True, "width": safe_w, "height": safe_h}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # PVP 悬浮窗的 set_pvp_float_window / pvp_float_toggle 见下方完整实现
    # (此处旧版 stub 已删除,避免静默覆盖)

    def pvp_float_resize(self, width: int = 280, height: int = 350) -> dict:
        """安全调整 PVP 悬浮窗尺寸 (前端按内容真实物理像素传入)"""
        if not getattr(self, "_pvp_float_window", None):
            return {"success": False, "message": "PVP 悬浮窗未创建"}
        try:
            safe_w = max(240, min(800, int(width)))
            safe_h = max(36, min(1400, int(height)))
            self._pvp_float_window.resize(safe_w, safe_h)
            return {"success": True, "width": safe_w, "height": safe_h}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def enable_hotkeys(self):
        """注册全局快捷键 + 启动本机 API 桥(AI 陪玩 MCP 数据源)"""
        try:
            self.tool.register_hotkeys()
        except Exception as e:
            self._enqueue_log(f"快捷键注册失败: {e}", "error")
        self.local_api_start()
        try:
            import keyboard
            keyboard.add_hotkey('f2', self._hotkey_widget)
            keyboard.add_hotkey('f8', self._hotkey_snip)
            keyboard.add_hotkey('f11', self._emergency_stop)
            keyboard.add_hotkey('f12', self._hotkey_pvp_float)
            self._enqueue_log("快捷键: F2悬浮窗/F8截图/F11急停/F12 PVP悬浮窗", "info")
        except Exception as e:
            self._enqueue_log(f"快捷键注册失败: {e}", "error")

    def _hotkey_widget(self):
        """F2: 纯浮窗显隐切换(不碰模式状态机,避免已显示窗口被意外隐藏)"""
        self.widget_toggle()

    def _hotkey_pvp_float(self):
        """F12: 纯浮窗显隐切换; pvp_float_toggle 会在显示时自动切到 PVP 标签"""
        self.pvp_float_toggle()

    def _emergency_stop(self):
        """F11 全局急停:战斗引擎 + 全部丢球模式 + 实时识别"""
        self._enqueue_log("!! F11 全局急停 !!", "error")
        try:
            self.engine.stop("F11 急停")
        except Exception:
            pass
        try:
            self.tool.stop_all()
        except Exception:
            pass
        self._live_running = False
        try:
            self._window.evaluate_js("setLiveUI(false); refreshState();")
        except Exception:
            pass

    def _hotkey_snip(self):
        """F8: 打开手动框选截图工具(截屏幕可见区域,不依赖窗口句柄)"""
        threading.Thread(target=self._snip_flow, daemon=True).start()

    def _snip_flow(self, save_only: bool = False):
        script = PROJECT_ROOT / "tools" / "snip_capture.py"
        cmd = [sys.executable, str(script)] + (["--save-only"] if save_only else [])
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE)
            self._enqueue_log(f"框选截图工具已打开(PID {proc.pid}),拖拽框选后自动保存并打开裁剪工具", "info")
        except Exception as e:
            self._enqueue_log(f"打开截图工具失败: {e}", "error")

    # ========================================
    # 状态推送循环（后台线程,每 200ms 刷新状态）
    # ========================================

    def _state_push_loop(self):
        while not self._stop_event.is_set():
            time.sleep(0.2)
            try:
                state = self.get_state()
                js = f"window.onStateUpdate && window.onStateUpdate({json.dumps(state)});"
                if self._widget and self._widget_visible:
                    try:
                        self._widget.evaluate_js(js)
                    except Exception:
                        pass
                if self._window:
                    try:
                        self._window.evaluate_js(js)
                    except Exception:
                        pass
            except Exception:
                pass

    def start_update_watcher(self):
        """启动后台版本检查(仅源码运行模式)"""
        try:
            self.updater.start()
        except Exception:
            pass


    # ---------- 账户登录/卡密验证 ----------
    def _auth_gate(self) -> dict | None:
        """付费功能统一鉴权守卫。返回 None=放行; dict=拒绝响应。
        开发者版放行; 用户版需已激活且未过期 + 核心数据密钥就绪。
        (UI 锁幕只是引导, 这里是硬闸)"""
        if DEV_MODE:
            return None
        try:
            from src.gui import auth
            st = auth.status()
            if not st.get("authorized"):
                return {"ok": False, "auth_required": True,
                        "message": "该功能需要激活卡密后使用(侧边栏点击激活)"}
            from src.pvp import seadata
            if seadata.has_sealed_data() and not seadata.is_ready():
                return {"ok": False, "auth_required": True,
                        "message": "核心数据未就绪, 请联网启动一次完成授权校验"}
            return None
        except Exception:
            return {"ok": False, "auth_required": True, "message": "登录态检查失败"}

    def auth_status(self) -> dict:
        from src.gui import auth
        st = auth.status()
        st["dev_mode"] = DEV_MODE
        if DEV_MODE:
            st["authorized"] = True      # 开发者版放行, 不锁任何功能
            st["nickname"] = st.get("nickname") or "开发者"
        return st

    def auth_activate(self, code) -> dict:
        if DEV_MODE:
            return {"ok": True, "message": "开发者模式无需激活", "dev": True}
        from src.gui import auth
        res = auth.activate(str(code or ""))
        if res.get("ok"):
            self._push_auth_state()
            self._enqueue_log(f"激活成功: {res.get('nickname')}", "success")
        else:
            self._enqueue_log(f"激活失败: {res.get('message')}", "error")
        return res

    def auth_logout(self) -> dict:
        from src.gui import auth
        auth.deactivate()
        self._push_auth_state()
        self._enqueue_log("已退出登录", "info")
        return {"ok": True}

    def auth_verify_remote(self) -> dict:
        """启动静默校验(后台线程调), 结果推送前端"""
        if DEV_MODE:
            return self.auth_status()
        from src.gui import auth
        res = auth.verify_remote()
        self._push_auth_state()
        if res.get("authorized"):
            days = res.get("expires_at")
            if days:
                left = max(0, (int(days) - int(time.time() * 1000)) // 86400000)
                if left <= 3:
                    self._enqueue_log(f"卡密剩余 {left} 天, 请及时续期", "warning")
        elif res.get("reason") == "revoked":
            self._enqueue_log("卡密已被吊销, 已退出登录", "error")
            self._on_auth_denied("revoked")
        elif res.get("reason") == "expired":
            self._on_auth_denied("expired")
        return res

    def _push_auth_state(self):
        """登录态推送到前端(侧边栏登录区刷新)"""
        if self._window is None:
            return
        try:
            st = self.auth_status()
            self._window.evaluate_js(
                "window.onAuthUpdate && window.onAuthUpdate("
                + json.dumps(st, ensure_ascii=False) + ")")
        except Exception:
            pass

    def start_auth_verify(self):
        """启动静默校验 + 运行中心跳(每 15 分钟一次, 吊销/过期实时生效)"""
        def _job():
            time.sleep(2.5)
            while True:
                try:
                    self.auth_verify_remote()
                except Exception:
                    pass
                self._stop_event.wait(900)  # 15 分钟
        threading.Thread(target=_job, daemon=True, name="AuthVerify").start()

    def _on_auth_denied(self, reason: str):
        """云端复验失败 (吊销/过期): 停掉全部任务并提示"""
        try:
            self.engine.stop(f"授权{ {'revoked': '已吊销', 'expired': '已过期'}.get(reason, '失效') }")
        except Exception:
            pass
        try:
            self.daily_stop()
        except Exception:
            pass
        try:
            self._pvp_running = False
        except Exception:
            pass
        self._enqueue_log("授权已失效，相关功能已停止。请重新激活或续费。", "warning")

    def start_state_push(self):
        t = threading.Thread(target=self._state_push_loop, daemon=True)
        t.start()

    # ========================================
    # 自动更新 (GitHub main 分支通道)
    # ========================================
    def _notify_update_available(self, info: dict):
        """后台检查发现新版本: 记录状态, 前端轮询 get_state 时顺带带上"""
        try:
            self._update_hint = {
                "has_update": True,
                "remote_commit": info.get("remote_commit", ""),
                "new_count": info.get("new_count", 0),
                "new_commits": (info.get("new_commits") or [])[:8],
            }
        except Exception:
            pass

    _update_hint = None

    def update_check(self) -> dict:
        """立即检查更新(前端点击触发)"""
        return check_update()

    def update_apply(self) -> dict:
        """执行更新: 自动停止所有键鼠任务 -> 保护 data/ -> git pull -> 可回滚"""
        return apply_update(stop_tasks_fn=self.stop_all)

    def update_status(self) -> dict:
        return updater_status()
    def pokedex_data(self):
        return self._bridge.pokedex_data()

    def daily_list(self):
        return self._bridge.daily_list()

    def daily_save(self, tasks):
        return self._bridge.daily_save(tasks)

    def daily_run(self, task_id):
        return self._bridge.daily_run(task_id)

    def daily_stop(self):
        return self._bridge.daily_stop()

    def daily_status(self):
        return self._bridge.daily_status()


    def schedule_set(self, enabled, hh=19, mm=0, duration_min=120, mode="engine"):
        return self._bridge.schedule_set(enabled, hh, mm, duration_min, mode)

    def schedule_get(self):
        return self._bridge.schedule_get()


    # ========================================
    # 图鉴收集册 + 预约挂机 (V4.6)
    # ========================================
    # ========================================
    # 日常任务 (V4.7 · MAA 式)
    # ========================================
    def daily_list(self) -> dict:
        return self.daily.list_tasks() if self.daily else {"success": False, "tasks": []}

    def daily_save(self, tasks) -> dict:
        return self.daily.save_tasks(tasks or []) if self.daily else {"success": False}

    def daily_run(self, task_id) -> dict:
        gate = self._auth_gate()
        if gate:
            return gate
        if not self.daily:
            return {"success": False, "message": "日常执行器不可用"}
        # 与引擎互斥: 启动日常前全停其它任务
        try:
            if self.engine.running:
                self.engine.stop("启动日常任务")
        except Exception:
            pass
        try:
            self._pvp_running = False
        except Exception:
            pass
        return self.daily.start_task(task_id)

    def daily_stop(self) -> dict:
        if self.daily:
            self.daily.stop()
        return {"success": True}

    def daily_status(self) -> dict:
        return self.daily.get_status() if self.daily else {"success": False}

    def pokedex_data(self) -> dict:
        """遭遇图鉴: 基于 PVP 战报库聚合(遭遇次数/胜负/首遇/最近), 头像由前端按名字映射"""
        try:
            from src.pvp.history_db import get_history_db
            db = get_history_db()
            with db._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT match_time, result, enemy_team FROM pvp_matches ORDER BY id ASC")
                rows = cursor.fetchall()
            pets = {}
            for row in rows:
                try:
                    enemy_pets = json.loads(row["enemy_team"]) if row["enemy_team"] else []
                except Exception:
                    continue
                is_win = (row["result"] == "WIN")
                t = row["match_time"] or ""
                for p in enemy_pets:
                    name = (p.get("name") or "").strip()
                    if not name or name == "未知":
                        continue
                    st = pets.setdefault(name, {
                        "name": name, "encounters": 0, "wins": 0,
                        "first_seen": t, "last_seen": t,
                    })
                    st["encounters"] += 1
                    if is_win:
                        st["wins"] += 1
                    if t and t > st["last_seen"]:
                        st["last_seen"] = t
            return {"success": True, "pets": list(pets.values())}
        except Exception as e:
            return {"success": False, "message": str(e), "pets": []}

    def schedule_set(self, enabled: bool, hh: int = 19, mm: int = 0,
                     duration_min: int = 120, mode: str = "engine") -> dict:
        """预约挂机: 到点后检查游戏窗口前台, 前台才启动(绝不碰 WeGame 启动链路)"""
        try:
            self._schedule = {
                "enabled": bool(enabled), "hh": int(hh), "mm": int(mm),
                "duration_min": max(5, min(720, int(duration_min))), "mode": mode,
            }
            if enabled and not getattr(self, "_schedule_thread", None):
                self._schedule_stop = threading.Event()
                self._schedule_thread = threading.Thread(
                    target=self._schedule_loop, args=(self._schedule_stop,), daemon=True, name="afk-scheduler")
                self._schedule_thread.start()
            elif not enabled and getattr(self, "_schedule_stop", None):
                self._schedule_stop.set()
                self._schedule_thread = None
            self._save_schedule()
            return {"success": True, "schedule": self._schedule}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def schedule_get(self) -> dict:
        if not hasattr(self, "_schedule"):
            self._load_schedule()
        return {"success": True, "schedule": getattr(self, "_schedule", None)}

    def _load_schedule(self):
        try:
            f = CONFIG_DIR / "schedule.json"
            if f.exists():
                self._schedule = json.loads(f.read_text(encoding="utf-8"))
            else:
                self._schedule = None
        except Exception:
            self._schedule = None
        if self._schedule and self._schedule.get("enabled") and not getattr(self, "_schedule_thread", None):
            self._schedule_stop = threading.Event()
            self._schedule_thread = threading.Thread(
                target=self._schedule_loop, args=(self._schedule_stop,), daemon=True, name="afk-scheduler")
            self._schedule_thread.start()

    def _save_schedule(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            (CONFIG_DIR / "schedule.json").write_text(
                json.dumps(self._schedule, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _schedule_loop(self, stop_event):
        """每天到点: 游戏前台→自动启动; 不在前台→记日志跳过"""
        while not stop_event.is_set():
            sch = getattr(self, "_schedule", None)
            if not sch or not sch.get("enabled"):
                break
            now = time.localtime()
            target = (sch["hh"] * 60 + sch["mm"])
            cur = now.tm_hour * 60 + now.tm_min
            if cur == target and now.tm_sec < 55:
                # 触发窗口(每分钟一查, 秒<55 防止重复触发)
                key = time.strftime("%Y%m%d")
                if getattr(self, "_last_schedule_fire", "") != key:
                    self._last_schedule_fire = key
                    self._schedule_fire(sch)
            stop_event.wait(20)
        # 恢复后重入(由 schedule_set 重建线程)

    def _schedule_fire(self, sch):
        try:
            info = self._find_game_window()
            if not info:
                self._enqueue_log("预约挂机: 游戏窗口不在前台, 本次跳过(不代启游戏)", "warning")
                return
            dur = sch.get("duration_min", 120)
            if sch.get("mode") == "throw":
                self.tool.start_normal(duration_minutes=dur) if hasattr(self.tool, "start_normal") else None
                if not hasattr(self.tool, "start_normal"):
                    self._enqueue_log("预约挂机: 丢球模式接口不可用", "error")
                    return
                mode_txt = "丢球助手"
            else:
                self.engine.start({"duration_minutes": dur})
                mode_txt = "挂机引擎"
            self._enqueue_log(f"预约挂机已触发: {mode_txt} · 时长 {dur} 分钟", "success")
        except Exception as e:
            self._enqueue_log(f"预约挂机触发异常: {e}", "error")


    def close(self):
        """窗口关闭时自动持久化所有配置并清理资源"""
        self._stop_event.set()
        self.local_api_stop()
        try:
            self.updater.stop()
        except Exception:
            pass
        self._live_running = False

        # 自动保存丢球延时配置
        try:
            self._save_throw_config()
        except Exception:
            pass

        # 自动保存挂机引擎配置
        if hasattr(self, "_last_engine_params") and self._last_engine_params:
            try:
                self._save_engine_settings(self._last_engine_params)
            except Exception:
                pass

        # 关闭抓图线程和 FastCapture
        if self._fast_cap:
            self._fast_cap.close()
            self._fast_cap = None
        try:
            self._collector_stop.set()
        except Exception:
            pass
        try:
            self.engine.stop("窗口关闭")
        except Exception:
            pass
        try:
            self.tool.stop_all()
        except Exception:
            pass
        for tool_id in list(self._tool_procs):
            self._kill_tool(tool_id)
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass

        # 兜底强退: keyboard/RapidOCR 等库的线程可能残留导致进程僵死,
        # 残留实例会锁 WebView2 用户数据目录 → 下次启动随机失败(现象就是"时好时坏")
        def _force_exit():
            time.sleep(0.5)   # 给 pywebview 一点收尾时间
            os._exit(0)
        threading.Thread(target=_force_exit, daemon=True).start()

    shutdown = close

    # ========================================
    # 日志推送
    # ========================================

    def _enqueue_log(self, message, level="info"):
        self._log_queue.put((str(message), level))

    def _start_log_pusher(self):
        if self._pusher_thread and self._pusher_thread.is_alive():
            return

        def _pusher_loop():
            while not self._stop_event.is_set():
                try:
                    message, level = self._log_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if not self._window:
                    continue
                try:
                    js = f"addLog({json.dumps(message, ensure_ascii=False)}, {json.dumps(level)})"
                    self._window.evaluate_js(js)
                except Exception:
                    pass

        self._pusher_thread = threading.Thread(target=_pusher_loop, daemon=True, name="LogPusher")
        self._pusher_thread.start()

    # ========================================
    # 1. 丢球工具 API
    # ========================================

    def toggle_normal(self) -> dict:
        will_start = not self.tool.running
        auto_stopped = self._stop_conflicting_modes("throw") if will_start else []
        running = self.tool.toggle()
        if running:
            self.auto_minimize_and_show_widget()
        return {"success": True, "running": running, "auto_stopped": auto_stopped}

    def toggle_bomber(self) -> dict:
        will_start = not self.tool.bomber_running
        auto_stopped = self._stop_conflicting_modes("throw") if will_start else []
        running = self.tool.toggle_bomber()
        if running:
            self.auto_minimize_and_show_widget()
        return {"success": True, "running": running, "auto_stopped": auto_stopped}

    def toggle_skill(self) -> dict:
        will_start = not self.tool.skill_running
        auto_stopped = self._stop_conflicting_modes("throw") if will_start else []
        running = self.tool.toggle_skill()
        if running:
            self.auto_minimize_and_show_widget()
        return {"success": True, "running": running, "auto_stopped": auto_stopped}

    # 模式互斥: 丢球(三种模式可共存) / 挂机引擎 / PVP识别 三组之间互斥
    # 启动任一组时自动停止其它组,返回被停止的组名列表供前端 Toast 提示
    def _stop_conflicting_modes(self, starter: str) -> list:
        stopped = []
        if starter != "throw":
            running_names = [name for flag, name in (
                (self.tool.running, "普通丢球"),
                (self.tool.bomber_running, "轰炸机模式"),
                (self.tool.skill_running, "自动技能"),
            ) if flag]
            if running_names:
                self.tool.stop_all()
                stopped.append("丢球助手(" + "+".join(running_names) + ")")
        if starter != "engine" and self.engine.running:
            self.engine.stop("新模式启动,自动停止")
            stopped.append("挂机引擎")
        if starter != "pvp" and self._pvp_running:
            self._pvp_running = False
            stopped.append("PVP识别")
        for name in stopped:
            self._enqueue_log(f"模式互斥: 已自动停止 {name}", "warning")
        return stopped

    def stop_all(self) -> dict:
        self.tool.stop_all()
        if self.engine.running:
            self.engine.stop("全部停止")
        self._pvp_running = False
        return {"success": True}

    def get_app_mode(self) -> dict:
        """前端启动时询问运行模式,用户版据此隐藏开发者功能入口"""
        return {"success": True, "dev": DEV_MODE}

    def update_config(self, params: dict) -> dict:
        params = params or {}
        cleaned = self._validate_throw_params(params)
        if "exit_on_battle" in params:
            self.tool.exit_on_battle = bool(params["exit_on_battle"])
            cleaned["exit_on_battle"] = self.tool.exit_on_battle

        if not cleaned:
            return {"success": False, "message": "没有有效参数"}

        for key, value in cleaned.items():
            if key != "exit_on_battle":
                setattr(self.tool, key, value)
        self._save_throw_config()
        self._enqueue_log(f"丢球延迟配置已更新: {cleaned}", "success")
        return {"success": True, "config": self._get_throw_config()}

    @staticmethod
    def _validate_throw_params(params: dict) -> dict:
        cleaned = {}
        for key, (lo, hi) in CONFIG_SCHEMA.items():
            if key not in params:
                continue
            try:
                value = round(float(params[key]), 2)
            except (TypeError, ValueError):
                continue
            cleaned[key] = max(lo, min(hi, value))
        for min_key, max_key in CONFIG_PAIRS:
            if min_key in cleaned and max_key in cleaned:
                if cleaned[min_key] > cleaned[max_key]:
                    cleaned[min_key] = cleaned[max_key]
        return cleaned

    def _get_throw_config(self) -> dict:
        cfg = {key: getattr(self.tool, key) for key in CONFIG_SCHEMA}
        cfg["exit_on_battle"] = getattr(self.tool, "exit_on_battle", True)
        return cfg

    def _throw_config_path(self) -> Path:
        return CONFIG_DIR / "throw_ball_config.json"

    def _load_throw_config(self):
        path = self._throw_config_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in self._validate_throw_params(data).items():
                setattr(self.tool, key, value)
            self._enqueue_log("已加载丢球延迟配置", "info")
        except Exception as e:
            self._enqueue_log(f"加载丢球配置失败: {e}", "error")

    def _save_throw_config(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            data = {k: round(v, 2) for k, v in self._get_throw_config().items()}
            self._throw_config_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self._enqueue_log(f"保存丢球配置失败: {e}", "error")

    # ========================================
    # 2. 视觉调试 API（只读屏,不做任何键鼠操作）
    # ========================================

    def _find_game_window(self):
        from src.capture.window_capture import find_window
        # 优先按游戏窗口类精确匹配;控制台标题同样含"洛克王国",靠类名+进程排除避免误抓
        info = find_window(class_name="UnrealWindow")
        if info is None:
            info = find_window()
        if info is not None:
            # 窗口被最小化时坐标会偏移到屏幕外(-32000, -32000), 无法截图
            try:
                import win32gui, win32con
                if win32gui.IsIconic(info.hwnd):
                    win32gui.ShowWindow(info.hwnd, win32con.SW_RESTORE)
                    info = find_window(class_name="UnrealWindow") or find_window()
            except Exception:
                pass
            # 坐标异常时也尝试恢复
            if info and (info.rect[0] < -30000 or info.rect[1] < -30000):
                try:
                    import win32gui, win32con
                    win32gui.ShowWindow(info.hwnd, win32con.SW_RESTORE)
                    info = find_window(class_name="UnrealWindow") or find_window()
                except Exception:
                    pass
        return info

    @staticmethod
    def _console_overlaps_game(game_rect) -> bool:
        """检查控制台自身窗口是否遮挡了游戏窗口(遮挡时 BitBlt 会截到黑图)"""
        try:
            import os
            import win32gui
            import win32process

            own_pid = os.getpid()
            rects = []

            def _cb(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == own_pid and "洛克王国" in win32gui.GetWindowText(hwnd):
                    rects.append(win32gui.GetWindowRect(hwnd))

            win32gui.EnumWindows(_cb, 0)
            if not rects:
                return False
            cl, ct, cr, cb_ = rects[0]
            gl, gt, gr, gb = game_rect
            return cl < gr and cr > gl and ct < gb and cb_ > gt
        except Exception:
            return False

    # ========================================
    # WeGame 拉起游戏 (game_launch 日常动作的实现)
    # ========================================

    def game_launch(self) -> dict:
        """无 UAC 拉起 WeGame 并尝试启动洛克王国。
        链路: 计划任务 LKW_WeGameLaunch(提权启动 wegame.exe)
             → 等 WeGame 窗口 → 计划任务 LKW_WeGameFocus 置顶窗口
             → auto_click=true 时 OCR 定位「启动」按钮模拟点击
             → 等游戏窗口(UnrealWindow)出现(最长 wait_window 秒)。
        配置: data/config/game_launch.json"""
        import subprocess
        import time as _t
        cfg_path = CONFIG_DIR / "game_launch.json"
        cfg = {}
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        task_name = cfg.get("task_name", "LKW_WeGameLaunch")
        focus_task = cfg.get("task_focus_name", "LKW_WeGameFocus")
        appid = str(cfg.get("appid", "2002304"))
        wait_window = int(cfg.get("wait_window", 300))
        auto_click = bool(cfg.get("auto_click", True))

        def _win32_popen_schtasks(action: str, args: list) -> subprocess.Popen:
            # CREATE_NO_WINDOW: 不闪黑框
            return subprocess.Popen(
                ["schtasks", action, *args],
                creationflags=0x08000000, close_fds=True)

        # 1. 计划任务启动 WeGame(提权, 无 UAC 弹窗)
        self._enqueue_log(f"[启动游戏] 计划任务 {task_name} 拉起 WeGame...", "info")
        proc = _win32_popen_schtasks("/run", ["/tn", task_name])
        proc.wait(timeout=15)

        # 2. 等 WeGame 主窗口出现(Title 含 WeGame), 最长 wegame_wait 秒
        wegame_wait = int(cfg.get("wegame_wait", 45))
        from src.capture.window_capture import find_window
        wegame_deadline = _t.time() + wegame_wait
        while _t.time() < wegame_deadline:
            if self._stop_event.is_set():
                return {"success": False, "message": "已停止"}
            try:
                if find_window(title_matcher=lambda t: "WeGame" in t,
                               exclude_own_process=True):
                    break
            except Exception:
                pass
            _t.sleep(1)
        else:
            return {"success": False, "message": f"等待 {wegame_wait}s 未出现 WeGame 窗口"}

        self._enqueue_log("WeGame 已启动, 置顶窗口...", "info")
        # 3. 置顶 WeGame(计划任务上下文运行, 才能对提权窗口 SetWindowPos)
        _win32_popen_schtasks("/run", ["/tn", focus_task])

        # 4. OCR 定位「启动」按钮并模拟点击(auto_click=true)
        if auto_click:
            ok = self._wegame_auto_click(appid)
            if not ok:
                self._enqueue_log("[启动游戏] OCR 未命中「启动」按钮, 请在 WeGame 界面手动点启动", "warning")

        # 5. 等游戏窗口出现
        self._enqueue_log(f"[启动游戏] 等待游戏窗口出现(最长 {wait_window}s)...", "info")
        game_deadline = _t.time() + wait_window
        while _t.time() < game_deadline:
            if self._stop_event.is_set():
                return {"success": False, "message": "已停止"}
            try:
                if find_window(class_name="UnrealWindow"):
                    self._enqueue_log("[启动游戏] 游戏窗口已出现", "success")
                    return {"success": True, "message": "游戏已启动"}
            except Exception:
                pass
            _t.sleep(2)
        return {"success": False, "message": f"等待 {wait_window}s 未出现游戏窗口"}

    def _wegame_auto_click(self, appid: str, max_clicks: int = 3) -> bool:
        """WeGame 界面 OCR 找「启 动」按钮并点击(需已置顶)。返回是否命中。"""
        import time as _t
        from src.capture.window_capture import find_window
        from src.utils.ocr_engine import read_best
        from src.driver.mouse_controller import MouseController
        btn_streak = 0
        clicked = False
        deadline = _t.time() + 45
        mouse = MouseController()
        while _t.time() < deadline and not clicked:
            if self._stop_event.is_set():
                return False
            info = find_window(title_matcher=lambda t: "WeGame" in t,
                               exclude_own_process=True)
            if not info:
                _t.sleep(2)
                continue
            from src.capture.fast_capture import FastCapture
            fc = FastCapture()
            frame = fc.capture(rect=info.rect)
            if frame is None or frame.size == 0:
                _t.sleep(2)
                continue
            text, boxes = read_best(frame)
            if not text:
                _t.sleep(2)
                continue
            # OCR 找「启动」文本框(WeGame 大按钮, 可能写作"启动"/"启 动")
            fh, fw = frame.shape[:2]
            hit = None
            for line in (boxes or []):
                txt = str(line[1][0] if isinstance(line, (list, tuple)) and len(line) >= 2 else line)
                clean = txt.replace(" ", "")
                if "启动" in clean or "开始游戏" in clean:
                    box = line[0] if isinstance(line, (list, tuple)) else None
                    if box:
                        xs = [p[0] for p in box]; ys = [p[1] for p in box]
                        cx = (min(xs) + max(xs)) / 2 / fw
                        cy = (min(ys) + max(ys)) / 2 / fh
                        hit = (cx, cy)
                        break
            if hit:
                btn_streak += 1
                # 连续 2 次同位置命中才点(防 OCR 误认别的文字)
                if btn_streak >= 2:
                    x = info.rect[0] + int(info.width * hit[0])
                    y = info.rect[1] + int(info.height * hit[1])
                    mouse.move_to(x, y)
                    _t.sleep(0.15)
                    mouse.click('left', 0.06)
                    clicked = True
                    self._enqueue_log("[启动游戏] 已点击「启动」按钮", "info")
            else:
                btn_streak = 0
                _t.sleep(2)
        return clicked

    def vision_status(self) -> dict:
        """游戏窗口检测（不截图）"""
        try:
            info = self._find_game_window()
        except Exception as e:
            return {"success": False, "message": str(e)}
        if not info:
            return {"success": False, "message": "未找到「洛克王国」窗口"}
        return {"success": True, "title": info.title,
                "width": info.width, "height": info.height}

    def _capture_frame(self):
        """截图一帧游戏画面(FastCapture 单例持久化, ~3-5ms)"""
        info = self._find_game_window()
        if not info:
            raise RuntimeError("未找到「洛克王国」窗口,请确认游戏已启动")
        left, top, right, bottom = info.rect
        w, h = right - left, bottom - top
        if w < 50 or h < 50:
            raise RuntimeError("游戏窗口过小或最小化")
        fc = self._get_fast_capture()
        frame = fc.capture(rect=(left, top, w, h))
        if frame is None or frame.size == 0:
            raise RuntimeError("截图失败")
        return info, frame

    @staticmethod
    def _frame_to_jpeg_dataurl(frame, max_width: int = None) -> str:
        """编码 JPEG 为 base64 dataurl; 实时识别用 max_width=960 压缩,单次截图用原尺寸"""
        from src.capture.fast_capture import FastCapture
        return FastCapture.encode_jpeg(frame, max_width=max_width, quality=75)

    def vision_capture(self, front: bool = True, source: str = "main") -> dict:
        """截取游戏画面预览。
        front=True: 先把游戏窗口置前并等 1 秒再截(避免截到遮挡/失焦画面);
        source: 调用来源('main' 主控台视觉调试 / 'studio' ROI 工坊), 仅用于日志定位"""
        try:
            if front:
                try:
                    self._focus_game_window()
                except Exception:
                    pass
                import time as _t
                _t.sleep(1.0)   # 等窗口切换与渲染稳定
            info, frame = self._capture_frame()
        except Exception as e:
            self._enqueue_log(f"截图失败: {e}", "error")
            return {"success": False, "message": str(e)}
        self._last_frame = frame
        self._enqueue_log(f"已截图 {info.width}x{info.height}（{info.title}）", "success")
        try:
            image = self._frame_to_jpeg_dataurl(frame)
        except Exception as e:
            self._enqueue_log(f"图像编码失败: {e}", "error")
            return {"success": False, "message": f"编码失败: {e}"}
        return {"success": True, "image": image,
                "width": info.width, "height": info.height, "title": info.title}

    def vision_analyze(self, front: bool = True, source: str = "main") -> dict:
        """截图 + 跑完整识别管线 (front/source 含义同 vision_capture)"""
        try:
            if front:
                try:
                    self._focus_game_window()
                except Exception:
                    pass
                import time as _t
                _t.sleep(1.0)
            info, frame = self._capture_frame()
        except Exception as e:
            self._enqueue_log(f"截图失败: {e}", "error")
            return {"success": False, "message": str(e)}
        self._last_frame = frame

        from src.perception.vision_pipeline import VisionPipeline, DEFAULT_ROI_CONFIG
        try:
            pipeline = VisionPipeline()
            result = pipeline.analyze(frame).to_dict()
        except Exception as e:
            self._enqueue_log(f"识别失败: {e}", "error")
            return {"success": False, "message": f"识别失败: {e}"}

        roi = {}
        try:
            roi = json.loads(DEFAULT_ROI_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass

        battle = result.get("battle") or {}
        self._enqueue_log(
            f"识别完成: 战斗={battle.get('in_battle')} 敌方血量={result.get('enemy_hp')}% "
            f"精灵={result.get('enemy_name')} 属性={result.get('enemy_elements')}", "info")
        return {"success": True, "image": self._frame_to_jpeg_dataurl(frame),  # 单次截图用原尺寸
                "width": info.width, "height": info.height,
                "result": result, "roi": roi}

    def _get_paddleocr(self):
        if self._paddleocr is not None:
            return self._paddleocr
        # 修复 Windows 上 libifcoremd.dll MKL 线程冲突崩溃
        import os
        os.environ.setdefault('OMP_NUM_THREADS', '1')
        os.environ.setdefault('MKL_NUM_THREADS', '1')
        os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
        from paddleocr import PaddleOCR
        try:
            self._paddleocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang='ch',
                ocr_version='PP-OCRv4',
                text_det_limit_side_len=64,
                text_det_thresh=0.1,
                text_det_box_thresh=0.2,
                text_det_unclip_ratio=1.8,
            )
        except Exception:
            # v4 不可用时回退到默认 server 模型
            self._paddleocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang='ch',
                text_det_limit_side_len=64,
                text_det_thresh=0.1,
                text_det_box_thresh=0.2,
                text_det_unclip_ratio=1.8,
            )
        return self._paddleocr

    def vision_ocr_preview(self, rois: dict = None) -> dict:
        """PaddleOCR 批量识别：所有 ROI 拼成一张图，一次 OCR 调用"""
        import cv2, numpy as np
        from src.perception.ocr_reader import OcrNameReader

        if self._last_frame is None:
            try:
                _, self._last_frame = self._capture_frame()
            except Exception as e:
                return {"success": False, "message": str(e)}
        frame = self._last_frame
        fh, fw = frame.shape[:2]

        roi_data = rois or {}
        if not roi_data:
            try:
                roi_data = json.loads(DEFAULT_ROI_CONFIG.read_text(encoding="utf-8"))
            except Exception:
                pass

        try:
            ocr = self._get_paddleocr()
        except Exception as e:
            return {"success": False, "message": f"PaddleOCR 初始化失败: {e}"}

        pet_list = OcrNameReader._load_pets() if hasattr(OcrNameReader, '_load_pets') else []

        # --- 第一阶段：收集所有 ROI 裁剪，拼成一张合成图 ---
        crops = []  # [(roi_id, crop, y_offset, label, is_number)]
        roi_order = []
        total_h = 0
        for roi_id, box in roi_data.items():
            if not box or not box.get("width"):
                continue
            x = int(box["left"] * fw)
            y = int(box["top"] * fh)
            w = int(box["width"] * fw)
            h = int(box["height"] * fh)
            if w <= 0 or h <= 0:
                continue
            crop = frame[y:y+h, x:x+w]
            pad = max(10, min(h, w) // 2)
            padded = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            ph, pw = padded.shape[:2]
            is_number = any(kw in roi_id.lower() for kw in ("hp", "血", "energy", "能量", "power"))
            label = roi_data[roi_id].get("label", roi_id) if isinstance(roi_data[roi_id], dict) else roi_id
            roi_order.append(roi_id)
            crops.append((roi_id, padded, total_h, total_h + ph, label, is_number))
            total_h += ph + 4  # 4px 分隔

        if not crops:
            return {"success": True, "results": {}, "roi": roi_data}

        # 创建合成图
        max_w = max(c[1].shape[1] for c in crops)
        composite = np.zeros((total_h, max_w, 3), dtype=np.uint8)
        for roi_id, crop_img, y0, y1, _, _ in crops:
            composite[y0:y0 + crop_img.shape[0], :crop_img.shape[1]] = crop_img

        # --- 第二阶段：一次 OCR 识别整张合成图 ---
        try:
            res = ocr.predict(composite)
            all_texts = res[0].get('rec_texts', []) if res and res[0] else []
            all_scores = res[0].get('rec_scores', []) if res and res[0] else []
            all_boxes = res[0].get('rec_boxes', []) if res and res[0] else []
        except Exception:
            all_texts, all_scores, all_boxes = [], [], []

        # --- 第三阶段：按 y 位置映射回各 ROI ---
        results = {}
        for roi_id, _, y0, y1, label, is_number in crops:
            # 收集落在该 ROI 范围内的识别结果
            roi_texts = []
            roi_scores = []
            for ti, (text, score) in enumerate(zip(all_texts, all_scores)):
                if ti < len(all_boxes) and len(all_boxes[ti]) >= 1:
                    cy = (all_boxes[ti][0][1] + all_boxes[ti][-1][1]) / 2
                    if y0 <= cy <= y1:
                        roi_texts.append(text)
                        roi_scores.append(score)

            joined = ''.join(roi_texts)
            conf = round(sum(roi_scores) / len(roi_scores), 2) if roi_scores else 0.0

            if is_number:
                joined = ''.join(ch for ch in joined if ch.isdigit() or ch in '%/')

            corrected = False
            if not is_number and joined and pet_list and hasattr(OcrNameReader, '_correct_with_pet_list'):
                cleaned = OcrNameReader._clean(joined) if hasattr(OcrNameReader, '_clean') else joined
                if cleaned:
                    matched = OcrNameReader._correct_with_pet_list(cleaned)
                    if matched and matched[0]:
                        joined = matched[0]
                        corrected = True

            results[roi_id] = {
                "text": joined or "?", "conf": conf,
                "raw": joined, "corrected": corrected,
                "label": label, "is_number": is_number,
            }

        return {"success": True, "results": results, "roi": roi_data}

    # ========================================
    # 实时识别(调试台开关,循环: 截屏可见区域 → 识别 → 推送前端)
    # ========================================

    def vision_live_start(self) -> dict:
        if self._live_running:
            return {"success": True, "message": "已在运行"}
        self._live_running = True
        self._live_black_warned = False
        self._live_pipeline = None  # 每次启动重建(加载最新模板)
        self._live_last_frame = None
        self._live_thread = threading.Thread(target=self._live_loop, daemon=True, name="VisionLive")
        self._live_thread.start()
        self._enqueue_log(f"实时识别已启动(每 {self._live_interval}s 一帧)", "success")
        return {"success": True}

    def vision_live_stop(self) -> dict:
        self._live_running = False
        self._live_last_frame = None
        # 停止后台抓图线程
        if self._fast_cap:
            self._fast_cap.stop_worker()
            self._enqueue_log("后台抓图线程已停止", "info")
        self._enqueue_log("实时识别已停止", "warning")
        return {"success": True}

    def vision_live_quality(self, quality: str = "fast") -> dict:
        """实时预览画质切换: fast=960 / hd=1440 / full=原尺寸 (下一帧生效)"""
        mapping = {"fast": 960, "hd": 1440, "full": 0}
        q = str(quality or "fast").lower()
        if q not in mapping:
            return {"success": False, "message": f"未知画质: {quality} (可选 fast/hd/full)"}
        self._live_max_width = mapping[q]
        self._enqueue_log(f"实时预览画质已切换: {q}", "info")
        return {"success": True, "quality": q, "max_width": self._live_max_width}

    # ========================================
    # ROI 标注工坊 (独立大窗, 与主控台共用同一 Api 单例)
    # ========================================

    def roi_studio_open(self) -> dict:
        """打开 ROI 标注工坊独立窗 (运行时创建, 共用 Api 单例)"""
        import webview
        # 子窗口被用户点 X 关闭后, pywebview 会把 Window 从内部注册表移除,
        # 残留引用调 show() 静默无效 → 用 closed 事件标志判断存活
        if getattr(self, "_studio_window", None):
            if getattr(self._studio_window, "_lkw_closed", False):
                self._studio_window = None
            else:
                try:
                    self._studio_window.show()
                    return {"success": True}
                except Exception:
                    self._studio_window = None
        web_dir = WEB_DIR
        url = (web_dir / "roi_studio.html").as_uri()
        try:
            win = webview.create_window(
                title='ROI 标注工坊', url=url, js_api=self._api,
                width=1280, height=820, min_size=(960, 640),
                resizable=True, on_top=False)
            win.events.closed += lambda: setattr(win, "_lkw_closed", True)
            self._studio_window = win
        except Exception as e:
            return {"success": False, "message": f"创建工坊窗口失败: {e}"}
        self._enqueue_log("ROI 标注工坊已打开", "info")
        return {"success": True}

    def roi_studio_state(self) -> dict:
        """工坊窗初始化数据: 最近一帧截图 + 当前 ROI + 模板列表"""
        out = {"success": True, "roi": {}, "templates": [], "image": None}
        try:
            from src.pvp.roi_template import list_templates
            out["templates"] = list_templates()
        except Exception:
            pass
        try:
            cfg = Path(__file__).resolve().parents[2] / "data" / "config" / "roi_config.json"
            if cfg.exists():
                out["roi"] = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            pass
        if self._last_frame is not None:
            try:
                out["image"] = self._frame_to_jpeg_dataurl(self._last_frame)
                hh, ww = self._last_frame.shape[:2]
                out["width"], out["height"] = ww, hh
            except Exception:
                pass
        return out

    def roi_studio_save(self, name: str, base_resolution: list, rois: list) -> dict:
        """工坊原子保存: 模板落盘 + 运行时 roi_config 同步 + 主窗推送"""
        from src.pvp.roi_template import save_template
        res = save_template(name, base_resolution, rois)
        if not res.get("success"):
            return res
        synced = False
        try:
            # 运行时同步: 模板(rx/ry/rw/rh 归一化) → roi_config.json
            # 视觉管线消费格式: {"left","top","width","height"}
            from src.pvp.roi_template import load_template
            data = load_template(name)
            rois_map = {}
            for r in (data or {}).get("rois", []):
                rid = r.get("id", "")
                if not rid:
                    continue
                rois_map[rid] = {"left": float(r.get("rx", 0)), "top": float(r.get("ry", 0)),
                                 "width": float(r.get("rw", 0)), "height": float(r.get("rh", 0))}
            if rois_map:
                cfg_path = Path(__file__).resolve().parents[2] / "data" / "config" / "roi_config.json"
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                old = {}
                if cfg_path.exists():
                    try:
                        old = json.loads(cfg_path.read_text(encoding="utf-8"))
                    except Exception:
                        old = {}
                old.update(rois_map)
                tmp = cfg_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(cfg_path)
                synced = True
        except Exception as e:
            self._enqueue_log(f"roi_config 运行时同步失败: {e}", "warning")
        # 推送主窗更新 currentRoi (前端格式同为 left/top/width/height)
        try:
            if self._window:
                self._window.evaluate_js(
                    "window.onRoiStudioSaved && window.onRoiStudioSaved("
                    + json.dumps({"name": name, "roi": rois_map}, ensure_ascii=False) + ")")
        except Exception:
            pass
        self._enqueue_log(f"ROI 模板已保存: {name} (同步={synced})", "success")
        res["synced"] = synced
        return res

    # ========================================
    # 战斗引擎 API
    # ========================================

    def engine_start(self, dry_run: bool = False, params: dict | None = None) -> dict:
        if self.engine.running:
            return {"success": False, "message": "引擎已在运行"}
        gate = self._auth_gate()
        if gate:
            return gate
        auto_stopped = self._stop_conflicting_modes("engine")
        overrides = self._parse_engine_params(params or {})
        self.engine.dry_run = bool(dry_run)
        ok = self.engine.start(overrides or None)
        if ok:
            self.auto_minimize_and_show_widget()
            if params:
                # 参数同步持久化到 settings.yaml
                self._save_engine_settings(params)
        return {"success": ok, "auto_stopped": auto_stopped}

    def engine_stop(self) -> dict:
        self.engine.stop()
        return {"success": True}

    # ========================================
    # PVP 数据采集器(本体集成版)
    # ========================================

    def pvp_collector_start(self) -> dict:
        """启动自动采集线程(每2秒一轮,输出到项目 output/)"""
        if not DEV_MODE:
            return {"success": False, "message": "数据采集仅开发者模式可用"}
        if getattr(self, "_collector_thread", None) and self._collector_thread.is_alive():
            return {"success": False, "message": "采集器已在运行"}
        try:
            from src.pvp.data_collector import PvpDataCollector
            self._collector = PvpDataCollector(output_dir=PROJECT_ROOT / "output")
        except Exception as e:
            return {"success": False, "message": f"初始化失败: {e}"}
        self._collector_stop = threading.Event()
        self._collector_thread = threading.Thread(
            target=self._collector_loop, daemon=True, name="PvpCollector")
        self._collector_thread.start()
        self._enqueue_log("PVP 数据采集器已启动(输出 output/)", "success")
        return {"success": True}

    def _collector_loop(self):
        last_status = ""
        while not self._collector_stop.is_set():
            try:
                status = self._collector.auto_collect()
                # 只在"有产出/状态变化"时写日志,避免刷屏
                if status != last_status and ("已采集" in status or "失败" in status or "不可见" in status):
                    self._enqueue_log(f"[采集] {status}", "info")
                last_status = status
            except Exception as e:
                self._enqueue_log(f"[采集] 异常: {e}", "error")
            self._collector_stop.wait(2.0)

    def pvp_collector_stop(self) -> dict:
        if not getattr(self, "_collector_stop", None):
            return {"success": True, "message": "未在运行"}
        self._collector_stop.set()
        summary = self._collector.summary()
        self._enqueue_log(f"PVP 数据采集器已停止: {summary}", "warning")
        return {"success": True, "summary": summary}

    def pvp_collector_status(self) -> dict:
        running = bool(getattr(self, "_collector_thread", None) and self._collector_thread.is_alive())
        stats = getattr(self, "_collector", None).stats if running else {}
        return {
            "running": running,
            "auto_saved": stats.get("auto_saved", 0),
            "fail_saved": stats.get("fail_saved", 0),
            "manual_saved": stats.get("manual_saved", 0),
            "pets": len(stats.get("battles_seen", ())),
        }

    def pvp_collector_manual(self) -> dict:
        """手动截图一张(战备阶段等)"""
        if not getattr(self, "_collector", None):
            try:
                from src.pvp.data_collector import PvpDataCollector
                self._collector = PvpDataCollector(output_dir=PROJECT_ROOT / "output")
            except Exception as e:
                return {"success": False, "message": str(e)}
        try:
            path = self._collector.save_manual("界面手动")
            if path:
                self._enqueue_log(f"[采集] 已保存 {Path(path).name}", "success")
                return {"success": True, "path": path}
            return {"success": False, "message": "游戏窗口不可见"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def engine_status(self) -> dict:
        """获取悬浮窗战情状态（聚合挂机引擎与自动丢球助手）"""
        if self.engine.running:
            return self.engine.get_status()

        # 如果当前是普通丢球/轰炸机/自动技能在运行
        tool = self.tool
        is_tool_running = tool.running or tool.bomber_running or tool.skill_running
        if is_tool_running:
            state = getattr(tool, "current_state", "throwing")
            detail = getattr(tool, "state_detail", "")
            if not detail:
                if tool.running:
                    detail = f"普通丢球: 已丢 {tool.normal_count} 球"
                elif tool.bomber_running:
                    detail = f"轰炸机: 已丢 {tool.bomber_count} 球"
                elif tool.skill_running:
                    detail = f"自动技能: 已按 {tool.skill_count} 次"

            return {
                "running": True,
                "dry_run": False,
                "mode_type": "tool",
                "state": state,
                "detail": detail,
                "battles_done": getattr(tool, "battles_escaped", 0),
                "catch_attempts": tool.normal_count + tool.bomber_count,
                "catches": 0,
                "skills_used": tool.skill_count,
                "catch_hp": None,
                "enemy_name": getattr(tool, "enemy_name", None),
                "enemy_hp": getattr(tool, "enemy_hp", None),
                "shiny_alert": (self.engine.get_status() or {}).get("shiny_alert"),
            }

        # 默认返回基础状态
        st = self.engine.get_status()
        if getattr(tool, "battles_escaped", 0) > 0 and st.get("battles_done", 0) == 0:
            st["battles_done"] = tool.battles_escaped
        # 观察模式战情(引擎/工具都没跑时,悬浮窗也能看到当前战斗)
        w = getattr(self, "_watch", None)
        if w and w.get("in_battle"):
            st["enemy_name"] = w.get("enemy_name")
            st["enemy_hp"] = w.get("enemy_hp")
            st["watching"] = True
        return st

    # ========================================
    # 观察模式(被动监视战斗,喂给挂机悬浮窗)
    # ========================================

    def _watch_loop(self):
        """引擎/工具空闲时,每 2.5 秒轻量识别一帧,更新观察战情。

        首次检测到战斗时做一次全量识别拿精灵名,之后走轻量(只读血量)。
        """
        from src.perception.vision_pipeline import VisionPipeline

        while not self._stop_event.is_set():
            try:
                # 引擎/工具/PVP实时/调试台实时任一在跑 → 让位,不做重复识别
                busy = (self.engine.running or self._pvp_running
                        or self._live_running or self.tool.running
                        or self.tool.bomber_running or self.tool.skill_running)
                if busy:
                    self._watch = None
                    if self._stop_event.wait(2.0):
                        break
                    continue

                info, frame = self._live_capture_frame()
                if self._watch_pipeline is None:
                    self._watch_pipeline = VisionPipeline()

                if self._watch_started.is_set():
                    snap = self._watch_pipeline.analyze(frame, light=True)
                else:
                    snap = self._watch_pipeline.analyze(frame, light=False)

                battle = snap.raw.get("battle", {})
                if not battle.get("in_battle"):
                    if self._watch_started.is_set():
                        self._watch = None
                        self._watch_started.clear()
                    if self._stop_event.wait(2.5):
                        break
                    continue

                if not self._watch_started.is_set():
                    # 刚进战斗: 全量识别拿名字
                    full = self._watch_pipeline.analyze(frame, light=False)
                    name = full.enemy_name.value
                    hp = full.enemy_hp.value if full.enemy_hp.value is not None else snap.enemy_hp.value
                    self._watch_started.set()
                else:
                    name = getattr(self, "_watch_name", None)
                    hp = snap.enemy_hp.value

                self._watch = {"in_battle": True, "enemy_name": name, "enemy_hp": hp}
                if name:
                    self._watch_name = name
            except Exception:
                pass  # 窗口不可见等静默重试
            if self._stop_event.wait(2.5):
                break

    def _start_watch_loop(self):
        if not getattr(self, "_watch_thread", None) or not self._watch_thread.is_alive():
            self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True, name="BattleWatch")
            self._watch_thread.start()

    # ========================================
    # PVP 实时识别引擎
    # ========================================

    def _enrich_result(self, data: dict, result) -> None:
        """识别结果附加伤害推演字段(calc_skills/enemy_threats/速度/愿力)。
        _pvp_loop 与本地 API /snapshot 共用; 精灵数据未就绪/名字未识别时写 calc_error。"""
        try:
            from src.pvp.pet_loader import get_pet_by_name
            from src.pvp.skill_loader import get_skill
            from src.pvp.damage_calculator import (
                calculate_all_panels, calculate_damage_full,
                calculate_world_speed_range, calculate_resonance_impact_damages)

            self_pet = get_pet_by_name(result.player_name)
            enemy_pet = get_pet_by_name(result.enemy_name)
            if not (self_pet and enemy_pet):
                data["calc_error"] = "精灵数据未就绪或名字未识别"
                return

            # 自动流派推导: 物攻高用物攻, 魔攻高用魔攻
            race = self_pet.get("race", {})
            prefer = "mattack" if race.get("mattack", 0) > race.get("attack", 0) else "attack"
            self_panel = calculate_all_panels(self_pet.get("race", {}))
            enemy_panel = calculate_all_panels(enemy_pet.get("race", {}))
            speed_diff = self_panel["speed"] - enemy_panel["speed"]

            # 我方技能伤害(OCR 出的 4 个技能逐个推演)
            calc_skills = []
            for sk_name in result.skills:
                sk = get_skill(sk_name) or {}
                sk_type = sk.get("type", "物攻")
                sk_attr = sk.get("attr", "普")
                sk_power = float(sk.get("power", 0)) if sk.get("power") else 0
                if sk_power > 0 and sk_type in ("物攻", "魔攻"):
                    dmg = calculate_damage_full(
                        attacker_panel=self_panel, defender_panel=enemy_panel,
                        skill_power=sk_power, skill_type=sk_type, skill_attr=sk_attr,
                        attacker_attrs=self_pet.get("types", []),
                        defender_attrs=enemy_pet.get("types", []),
                    )
                    enemy_est_hp = int(enemy_panel["hp"] * result.enemy_hp_pct)
                    dmg_min = dmg["damage"]
                    dmg_max = round(dmg["damage"] * 1.15)
                    is_kill = enemy_est_hp > 0 and dmg_min >= enemy_est_hp
                    calc_skills.append({
                        "name": sk_name, "power": int(sk_power),
                        "type": sk_type, "attr": sk_attr,
                        "dmg_min": dmg_min, "dmg_max": dmg_max,
                        "mult": dmg["attrMultiplier"],
                        "is_kill": is_kill,
                    })
                else:
                    calc_skills.append({"name": sk_name, "power": 0, "type": "变化",
                                        "dmg_min": 0, "dmg_max": 0, "mult": 1, "is_kill": False})

            # 敌方威胁(敌方技能库威力最高的 4 个)
            enemy_skills_raw = enemy_pet.get("skills", [])[:10]
            enemy_skills = [s["name"] if isinstance(s, dict) else s for s in enemy_skills_raw]
            enemy_threats = []
            for esk_name in enemy_skills:
                esk = get_skill(esk_name) or {}
                esk_power = float(esk.get("power", 0)) if esk.get("power") else 0
                esk_type = esk.get("type", "")
                if esk_power > 0 and esk_type in ("物攻", "魔攻"):
                    edmg = calculate_damage_full(
                        attacker_panel=enemy_panel, defender_panel=self_panel,
                        skill_power=esk_power, skill_type=esk_type,
                        skill_attr=esk.get("attr", "普"),
                        attacker_attrs=enemy_pet.get("types", []),
                        defender_attrs=self_pet.get("types", []),
                    )
                    is_lethal = result.player_hp_val > 0 and edmg["damage"] >= result.player_hp_val
                    enemy_threats.append({
                        "name": esk_name, "power": int(esk_power),
                        "dmg_min": edmg["damage"],
                        "dmg_max": round(edmg["damage"] * 1.15),
                        "is_lethal": is_lethal,
                        "tags": esk.get("tags", []),
                    })
                if len(enemy_threats) >= 4:
                    break

            # 敌方《洛克王国：世界》真实速度极值区间(对齐点击头像显示的区间)
            enemy_race_speed = float(enemy_pet.get("race", {}).get("speed", 0))
            enemy_speed_range = calculate_world_speed_range(enemy_race_speed)

            # 愿力冲击暗手伤害推演
            resonance_data = calculate_resonance_impact_damages(
                enemy_panel=enemy_panel,
                self_panel=self_panel,
                enemy_types=enemy_pet.get("types", []),
                self_types=self_pet.get("types", []),
                self_current_hp=result.player_hp_val,
            )

            data["speed_diff"] = int(speed_diff)
            data["enemy_speed_range"] = enemy_speed_range
            data["calc_skills"] = calc_skills
            data["enemy_threats"] = enemy_threats
            data["resonance_impact"] = resonance_data
            data["calc_done"] = True
        except Exception as e:
            data["calc_error"] = str(e)

    def _pvp_loop(self):
        """后台线程: 截图 → 识别 → 伤害计算 → 推送悬浮窗"""
        import time as _time
        import cv2, numpy as np
        from src.pvp.pvp_pipeline import get_pipeline
        from src.pvp.pet_loader import get_pet_by_name
        from src.pvp.skill_loader import get_skill
        from src.pvp.damage_calculator import calculate_all_panels, calculate_damage_full
        from src.pvp.type_chart import get_attr_multiplier

        pipeline = get_pipeline()
        self._pipeline = pipeline

        while self._pvp_running:
            t0 = _time.perf_counter()
            try:
                # 1. 截图 (FastCapture 单例, ~3-5ms)
                info = self._find_game_window()
                if not info:
                    _time.sleep(self._pvp_interval)
                    continue
                left, top, right, bottom = info.rect
                w, h = right - left, bottom - top
                if w < 50 or h < 50:
                    _time.sleep(self._pvp_interval)
                    continue

                fc = self._get_fast_capture()
                frame = fc.capture(rect=(left, top, w, h))
                if frame is None or frame.size == 0:
                    _time.sleep(self._pvp_interval)
                    continue
                self._last_frame = frame

                # 2. 识别
                result = pipeline.analyze(frame)
                data = pipeline.to_dict(result)
                player = data.get("player", {})
                enemy = data.get("enemy", {})

                # 3. 伤害推演(计算块抽为 _enrich_result, 本地 API /snapshot 共用)
                if result.in_battle:
                    self._enrich_result(data, result)

                # 4. 推送悬浮窗
                if self._pvp_float_window and self._pvp_float_visible and self._pvp_float_loaded:
                    self._pvp_float_window.evaluate_js(
                        f"updatePVPData({json.dumps(data, ensure_ascii=False)})"
                    )

                # 4.5 同步双方精灵到主控台「PVP 实时对战」详细查询页
                if result.in_battle and result.player_name and result.enemy_name                         and self._window and self._pvp_running:
                    pair = (result.player_name, result.enemy_name)
                    if pair != getattr(self, "_last_synced_pair", None):
                        self._last_synced_pair = pair
                        try:
                            self._window.evaluate_js(
                                "syncPvpFromFloat("
                                + json.dumps(result.player_name, ensure_ascii=False) + ","
                                + json.dumps(result.enemy_name, ensure_ascii=False) + ")")
                        except Exception:
                            pass

                # 5. 日志
                if result.in_battle:
                    dmg_hint = ""
                    if data.get("calc_skills"):
                        kills = [s["name"] for s in data["calc_skills"] if s.get("is_kill")]
                        if kills:
                            dmg_hint = f" 🔥必杀:{','.join(kills)}"
                    self._enqueue_log(
                        f"⚔️ 我方:{result.player_name}({result.player_hp}) "
                        f"敌方:{result.enemy_name}({result.enemy_hp_pct:.0%}) "
                        f"技能:{result.skills[0] if result.skills else '-'}{dmg_hint}",
                        "info")

            except Exception as e:
                self._enqueue_log(f"PVP 识别异常: {e}", "error")

            elapsed = _time.perf_counter() - t0
            sleep_time = max(0.05, self._pvp_interval - elapsed)
            _time.sleep(sleep_time)

    def pvp_engine_start(self) -> dict:
        """启动 PVP 实时识别引擎"""
        gate = self._auth_gate()
        if gate:
            return gate
        if self._pvp_running:
            return {"success": True, "message": "PVP 引擎已在运行"}
        auto_stopped = self._stop_conflicting_modes("pvp")
        import threading
        self._pvp_running = True
        self._pvp_thread = threading.Thread(target=self._pvp_loop, daemon=True, name="PvpEngine")
        self._pvp_thread.start()
        self._enqueue_log("PVP 实时识别引擎已启动", "success")
        return {"success": True, "auto_stopped": auto_stopped}

    def pvp_engine_stop(self) -> dict:
        """停止 PVP 实时识别引擎"""
        self._pvp_running = False
        if self._pvp_thread:
            self._pvp_thread.join(timeout=2.0)
            self._pvp_thread = None
        self._enqueue_log("PVP 引擎已停止", "info")
        return {"success": True}

    def pvp_engine_status(self) -> dict:
        return {"running": self._pvp_running, "float_visible": self._pvp_float_visible}

    # ========================================
    # 本地 API 桥 (AI 陪玩 MCP 数据源)
    # ========================================

    def local_pvp_snapshot(self) -> dict:
        """实时对局快照: 最新识别缓存 + 伤害推演字段(MCP /snapshot 数据源)。
        引擎未运行/无识别缓存时返回 in_battle=False 的空壳(不报错, AI 可轮询等待)。"""
        data = {"in_battle": False, "pvp_engine_running": bool(self._pvp_running)}
        pipeline = getattr(self, "_pipeline", None)
        result = getattr(pipeline, "_cached_result", None) if pipeline else None
        if result is None:
            return data
        try:
            from src.pvp.pvp_pipeline import get_pipeline
            data = get_pipeline().to_dict(result)
        except Exception:
            return data
        if getattr(result, "in_battle", False):
            self._enrich_result(data, result)
        return data

    def push_ai_comment(self, text: str, mood: str = "normal") -> bool:
        """AI 陪玩评论 → 悬浮窗弹幕条 (evaluate_js)"""
        import html as _html
        text = _html.escape(str(text)[:120])
        mood = str(mood)[:16]
        js = f"pushAiComment({json.dumps(text, ensure_ascii=False)}, {json.dumps(mood, ensure_ascii=False)})"
        widget = getattr(self, "_pvp_float_window", None)
        if not widget:
            return False
        try:
            widget.evaluate_js(js)
            return True
        except Exception:
            return False

    def local_api_start(self):
        """启动本机 HTTP 桥 + AI 陪玩线程(端口占用/配置缺失均静默降级)"""
        if getattr(self, "_local_api", None):
            return
        try:
            from src.gui.local_api import LocalApiServer
            self._local_api = LocalApiServer(self)
            self._local_api.start()
        except Exception:
            self._local_api = None
        try:
            from src.gui.ai_companion import AiCompanion
            self._ai_companion = AiCompanion(self)
            self._ai_companion.start()
        except Exception:
            self._ai_companion = None

    def local_api_stop(self):
        server = getattr(self, "_local_api", None)
        if server:
            server.stop()
            self._local_api = None
        companion = getattr(self, "_ai_companion", None)
        if companion:
            companion.stop()
            self._ai_companion = None

    @staticmethod
    def _parse_engine_params(params: dict) -> dict:
        """前端参数 -> 引擎 override(只认白名单键)"""
        overrides = {}
        try:
            if params.get("catch_hp") is not None:
                overrides["catch_hp"] = max(1, min(60, int(params["catch_hp"])))
            if params.get("open_ball_key"):
                overrides["open_ball_key"] = str(params["open_ball_key"]).strip().lower()[:3]
            if params.get("ball_slot_key"):
                slot = str(params["ball_slot_key"]).strip()
                if slot in {"1", "2", "3", "4", "5", "6"}:
                    overrides["ball_slot_key"] = slot
            if params.get("skills"):
                skills = [s.strip() for s in str(params["skills"]).replace("，", ",").split(",") if s.strip()]
                if skills:
                    overrides["skills"] = skills[:6]
            if params.get("skill_mode") in ("cycle", "sequence"):
                overrides["skill_mode"] = params["skill_mode"]
            if params.get("patrol_enabled") is not None:
                overrides["patrol_enabled"] = bool(params["patrol_enabled"])
            if params.get("patrol_move_key"):
                key = str(params["patrol_move_key"]).strip().lower()[:3]
                if key:
                    overrides["patrol_move_key"] = key
            if params.get("patrol_turn_mode") in ("keys", "mouse"):
                overrides["patrol_turn_mode"] = params["patrol_turn_mode"]
        except (TypeError, ValueError):
            pass
        return overrides

    def _save_engine_settings(self, params: dict):
        """把引擎参数写回 settings.yaml 的 battle 段"""
        try:
            import yaml
            from src.utils.settings import SETTINGS_PATH, invalidate
            data = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8")) or {}
            battle = data.setdefault("battle", {})
            if params.get("catch_hp") is not None:
                battle["catch_hp"] = max(1, min(60, int(params["catch_hp"])))
            if params.get("open_ball_key"):
                battle["open_ball_key"] = str(params["open_ball_key"]).strip().lower()
            if params.get("ball_slot_key"):
                battle["ball_slot_key"] = str(params["ball_slot_key"]).strip()
            if params.get("skills"):
                skills = [s.strip() for s in str(params["skills"]).replace("，", ",").split(",") if s.strip()]
                if skills:
                    battle["skills"] = skills[:6]
            if params.get("skill_mode") in ("cycle", "sequence"):
                battle["skill_mode"] = params["skill_mode"]
            patrol = data.setdefault("patrol", {})
            if params.get("patrol_enabled") is not None:
                patrol["enabled"] = bool(params["patrol_enabled"])
            if params.get("patrol_move_key"):
                patrol["move_key"] = str(params["patrol_move_key"]).strip().lower()
            if params.get("patrol_turn_mode") in ("keys", "mouse"):
                patrol["turn_mode"] = params["patrol_turn_mode"]
            SETTINGS_PATH.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            invalidate()
            self._enqueue_log("引擎参数已保存到 settings.yaml", "info")
        except Exception as e:
            self._enqueue_log(f"保存引擎参数失败: {e}", "error")

    def engine_get_settings(self) -> dict:
        """读取 settings.yaml 中的挂机引擎与巡逻参数"""
        try:
            import yaml
            from src.utils.settings import SETTINGS_PATH
            if not SETTINGS_PATH.exists():
                return {"success": True, "settings": {}}
            data = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8")) or {}
            battle = data.get("battle", {})
            patrol = data.get("patrol", {})
            raw_skills = battle.get("skills", ["1"])
            skills_str = ",".join(str(s) for s in raw_skills) if isinstance(raw_skills, list) else str(raw_skills)
            settings = {
                "catch_hp": battle.get("catch_hp", 50),
                "skills": skills_str,
                "open_ball_key": battle.get("open_ball_key", "w"),
                "ball_slot_key": str(battle.get("ball_slot_key", "1")),
                "patrol_enabled": patrol.get("enabled", True),
                "patrol_move_key": patrol.get("move_key", "w"),
                "patrol_turn_mode": patrol.get("turn_mode", "mouse"),
            }
            return {"success": True, "settings": settings}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def engine_save_settings(self, params: dict) -> dict:
        """将前端调整的挂机引擎参数自动保存到 settings.yaml"""
        if not params:
            return {"success": False, "message": "参数为空"}
        self._last_engine_params = params
        self._save_engine_settings(params)
        return {"success": True}

    # ========================================
    # 6. PVP 对战助手 API
    # ========================================

    def set_pvp_float_window(self, window):
        """设置 PVP 对战悬浮窗引用 + 防自截

        window 允许为 None(打包版降级为"主窗口内浮层", 不需要独立窗口),
        此时只记录空引用, 后续 pvp_float_* 会各自返回"未创建"。
        """
        self._pvp_float_window = window
        if window is None:
            self._pvp_float_loaded = False
            return
        try:
            window.events.loaded += lambda: setattr(self, '_pvp_float_loaded', True)
        except Exception:
            pass
        # 防自截: Windows 10 2004+ WDA_EXCLUDEFROMCAPTURE
        # (pywebview 6.x 没有 native_handle, 句柄要从 .native.Handle 取, 否则整段静默失效)
        def _exclude_from_capture():
            try:
                import ctypes
                hwnd = self._native_hwnd(window)
                if hwnd:
                    ctypes.windll.user32.SetWindowDisplayAffinity(int(hwnd), 0x00000011)
            except Exception:
                pass
        try:
            window.events.loaded += _exclude_from_capture
        except Exception:
            _exclude_from_capture()

    def pvp_search_pets(self, query: str = "") -> dict:
        from src.pvp import search_pets, get_all_pets_list
        if not query or not query.strip():
            pets = get_all_pets_list(pvp_filter=True)
            return {"success": True, "pets": pets[:50]}
        # PVP 选宠只提供高级形态(最终形态)及变体高级形态, I阶/II阶基础形态不可选
        results = search_pets(query.strip(), limit=30, pvp_filter=True)
        return {"success": True, "pets": [{
            "seq": r["seq"], "name": r["name"], "title": r.get("title", r["name"]),
            "types": r["types"],
        } for r in results]}

    def _save_bag_debug_shot(self, frame, tag: str = "bag_scan") -> str:
        """盘点现场截图落盘(供分析 ROI 对齐), 返回文件名"""
        try:
            import time as _t
            from src.utils.image_io import imwrite_unicode
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = SCREENSHOT_DIR / f"{tag}_{_t.strftime('%Y%m%d_%H%M%S')}.png"
            if imwrite_unicode(path, frame):
                self._enqueue_log(f"盘点现场截图已保存: {path.name}", "info")
                return path.name
        except Exception:
            pass
        return ""

    def bag_scan(self) -> dict:
        """背包盘点: 抓一帧游戏画面, 按网格识别球种+数量, 与上次快照做减法"""
        try:
            from src.perception.bag_scanner import BagScanner
            scanner = BagScanner()
            if not scanner.available():
                return {"success": False, "message": "背包 ROI 未配置(需要 背包.json 的 roi_1/roi_2/背包整体ocr)"}
            info, frame = self._capture_frame()
            res = scanner.scan_and_diff(frame)
            res["success"] = True
            res["debug_shot"] = self._save_bag_debug_shot(frame)
            g = scanner.grid_size()
            res["grid"] = {"cols": g["cols"], "rows": g["rows"],
                           "cells": g["cols"] * g["rows"]}
            return res
        except Exception as e:
            return {"success": False, "message": str(e)}

    def bag_open(self) -> dict:
        """置前游戏 → Esc → 点击背包按钮(内核级, 4秒防抖)。
        置前失败返回明确错误(由 _force_foreground 判定), 不静默吞掉。"""
        try:
            from src.perception.bag_scanner import open_bag_click, BAG_OPEN_DEBOUNCE
            now = time.time()
            if now - getattr(self, "_bag_open_last", 0.0) < BAG_OPEN_DEBOUNCE:
                return {"success": False, "message": "背包打开过于频繁(防抖), 请稍候"}
            self._bag_open_last = now
            ok = open_bag_click()
            if not ok:
                return {"success": False,
                        "message": "打开背包失败: 无法把游戏切到前台(Esc/点击需要游戏焦点), 请手动点一下游戏窗口后重试"}
            return {"success": True, "message": "已打开背包"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def bag_open_and_scan(self) -> dict:
        """置前游戏 → 打开背包(含重试+打开确认) → 盘点 → 返回结果。
        打开失败时直接报错返回, 不在错误界面上空扫(根治'识别出一堆乱球')"""
        opened = self.bag_open()
        if not opened.get("success"):
            return {"success": False,
                    "message": opened.get("message") or "无法置前游戏窗口, 请手动点一下游戏画面后再试"}
        res = self.bag_scan()
        if res.get("success"):
            res["bag_opened"] = True
        return res

    def pvp_get_pet(self, seq: int, title: str = None) -> dict:
        from src.pvp import get_pet_by_seq
        seq = int(seq)
        pet = get_pet_by_seq(seq, title=title)
        if not pet:
            return {"success": False, "message": f"精灵 #{seq} 不存在"}
        return {"success": True, "pet": pet}

    def pvp_search_skills(self, query: str = "") -> dict:
        from src.pvp import search_skills
        if not query or not query.strip():
            return {"success": True, "skills": []}
        results = search_skills(query.strip(), limit=30)
        return {"success": True, "skills": [{
            "name": r["name"], "type": r["type"], "attr": r["attr"],
            "power": r["power"], "consume": r["consume"],
        } for r in results]}

    def pvp_calc_vs(self, atk_seq: int, def_seq: int, skill_name: str,
                    atk_ivs: dict | None = None, def_ivs: dict | None = None) -> dict:
        from src.pvp import calc_pet_vs_pet
        atk_ivs = atk_ivs or {}
        def_ivs = def_ivs or {}
        result = calc_pet_vs_pet(int(atk_seq), int(def_seq), str(skill_name),
                                 attacker_ivs=atk_ivs, defender_ivs=def_ivs)
        if not result:
            return {"success": False, "message": "计算失败，请检查精灵和技能是否存在"}
        return {"success": True, **result}

    def pvp_get_all_pets(self) -> dict:
        from src.pvp import get_all_pets_list
        return {"success": True, "pets": get_all_pets_list()}

    def pvp_get_all_skills(self) -> dict:
        from src.pvp import get_all_skill_names
        names = get_all_skill_names()
        return {"success": True, "skills": [{"name": n} for n in names]}

    def pvp_calc_quick(self, atk_val: int, def_val: int, power: int,
                       skill_type: str = "物攻", skill_attr: str = "普通",
                       atk_attrs: list = None, def_attrs: list = None) -> dict:
        """快速伤害计算（不选精灵，直接输入数值）"""
        from src.pvp import get_attr_multiplier, normalize_attr
        atk_attrs = atk_attrs or ["普通"]
        def_attrs = def_attrs or ["普通"]
        atk_attrs = [normalize_attr(a) for a in atk_attrs]
        def_attrs = [normalize_attr(a) for a in def_attrs]

        # 属性倍率
        attr_mult = get_attr_multiplier(skill_attr, def_attrs)
        # 本系加成
        same_type = 1.25 if skill_attr in atk_attrs else 1.0
        # 伤害公式
        damage = round((atk_val / def_val) * 0.9 * power * same_type * attr_mult, 1)

        return {
            "success": True,
            "damage": damage,
            "atkUsed": atk_val,
            "defUsed": def_val,
            "sameTypeBonus": same_type,
            "attrMultiplier": attr_mult,
            "hits": 1,
        }

    def pvp_calc_panels(self, seq: int, high_ivs: list = None, iv_value: int = 10,
                        nature_up: str = None, nature_down: str = None) -> dict:
        """计算精灵面板：3项高IV + 性格修正"""
        from src.pvp.damage_calculator import calculate_all_panels
        from src.pvp.pet_loader import get_pet_race
        race = get_pet_race(int(seq))
        if not race:
            return {"success": False, "message": f"精灵 #{seq} 不存在"}
        high_ivs = high_ivs or ["attack", "mattack", "speed"]
        ivs = {}
        for stat in ["hp", "attack", "mattack", "defense", "mdefense", "speed"]:
            ivs[stat] = int(iv_value) if stat in high_ivs else 0
        panels = calculate_all_panels(race, ivs, nature_up=nature_up, nature_down=nature_down)
        return {"success": True, "panels": panels, "race": race}

    def pvp_get_pet_skills_full(self, seq: int) -> dict:
        """获取精灵全部技能（含完整数据）"""
        from src.pvp.pet_loader import get_pet_by_seq
        from src.pvp.skill_loader import get_skill
        pet = get_pet_by_seq(int(seq))
        if not pet:
            return {"success": False, "message": f"精灵 #{seq} 不存在"}
        skill_items = pet.get("skills") or []
        skills = []
        for s in skill_items:
            skill = get_skill(s["name"])
            if skill:
                skills.append({"name": s["name"], "level": s.get("level", "?"),
                               "type": skill.get("type", "?"), "attr": skill.get("attr", "?"),
                               "power": skill.get("power", "0"), "consume": skill.get("consume", "0"),
                               "describe": skill.get("describe", "")})
        return {"success": True, "skills": skills, "petName": pet.get("name", ""),
                "petTypes": pet.get("types", [])}

    def pvp_get_pet_preset(self, seq: int) -> dict:
        """智能预设（与 app 的 buildOpponentFullConfig 一致）：
        主攻项 + 速度 + HP，性格 主攻+/副攻-"""
        from src.pvp.pet_loader import get_pet_race
        race = get_pet_race(int(seq))
        if not race:
            return {"success": False, "message": f"精灵 #{seq} 不存在"}
        atk = race.get("attack", 0)
        matk = race.get("mattack", 0)
        prefer = "mattack" if matk >= atk else "attack"
        nature_up = "魔攻" if prefer == "mattack" else "攻击"
        nature_down = "攻击" if prefer == "mattack" else "魔攻"
        return {"success": True,
                "high_ivs": [prefer, "speed", "hp"],
                "iv_value": 10, "nature_up": nature_up,
                "nature_down": nature_down, "race": race}

    def pvp_calc_all_skills(self, atk_seq: int, def_seq: int,
                            atk_high_ivs: list = None, atk_iv_value: int = 10,
                            def_high_ivs: list = None, def_iv_value: int = 10,
                            atk_nature_up: str = None, atk_nature_down: str = None,
                            def_nature_up: str = None, def_nature_down: str = None) -> dict:
        """对防御方计算攻击方全部技能的伤害，按克制排序"""
        from src.pvp.damage_calculator import calculate_all_panels, calculate_damage_full
        from src.pvp.pet_loader import get_pet_race, get_pet_by_seq, get_pet_types
        from src.pvp.skill_loader import get_skill
        from src.pvp.type_chart import get_attr_multiplier, normalize_attr
        from src.pvp.pvp_rules import DAMAGE

        atk_seq, def_seq = int(atk_seq), int(def_seq)
        atk_race = get_pet_race(atk_seq)
        def_race = get_pet_race(def_seq)
        if not atk_race or not def_race:
            return {"success": False, "message": "精灵不存在"}

        atk_pet = get_pet_by_seq(atk_seq)
        def_pet = get_pet_by_seq(def_seq)
        atk_high_ivs = atk_high_ivs or ["attack", "mattack", "speed"]
        def_high_ivs = def_high_ivs or ["attack", "mattack", "speed"]

        def _build_ivs(high_ivs, val):
            ivs = {}
            for s in ["hp", "attack", "mattack", "defense", "mdefense", "speed"]:
                ivs[s] = int(val) if s in high_ivs else 0
            return ivs

        atk_panels = calculate_all_panels(atk_race, _build_ivs(atk_high_ivs, atk_iv_value),
                                          nature_up=atk_nature_up, nature_down=atk_nature_down)
        def_panels = calculate_all_panels(def_race, _build_ivs(def_high_ivs, def_iv_value),
                                          nature_up=def_nature_up, nature_down=def_nature_down)

        atk_types = get_pet_types(atk_seq)
        def_types = get_pet_types(def_seq)
        pet_skills = (atk_pet.get("skills") or []) if atk_pet else []

        results = []
        for s in pet_skills:
            sk = get_skill(s["name"])
            if not sk:
                continue
            stype = str(sk.get("type", "")).strip()
            sattr = str(sk.get("attr", "")).replace("系", "").strip()
            spower = int(sk.get("power", 0)) if str(sk.get("power", "0")).isdigit() else 0
            is_dmg = stype in ("物攻", "魔攻")

            if not is_dmg:
                results.append({"name": s["name"], "type": stype, "attr": sattr,
                                "power": 0, "consume": sk.get("consume", "?"),
                                "isDamage": False, "attrMultiplier": 0,
                                "minDamage": 0, "maxDamage": 0, "level": s.get("level", "?")})
                continue

            attr_mult = get_attr_multiplier(sattr, def_types)
            same_type = DAMAGE["sameTypeBonus"] if normalize_attr(sattr) in [normalize_attr(t) for t in atk_types] else 1.0

            # MIN: atk_level=0, MAX: atk_level=+3
            dmin = calculate_damage_full(atk_panels, def_panels, spower, stype, sattr,
                                         atk_types, def_types, atk_level=0)
            dmax = calculate_damage_full(atk_panels, def_panels, spower, stype, sattr,
                                         atk_types, def_types, atk_level=3)
            results.append({"name": s["name"], "type": stype, "attr": sattr,
                            "power": spower, "consume": sk.get("consume", "?"),
                            "isDamage": True, "attrMultiplier": attr_mult,
                            "minDamage": round(dmin["damage"], 1),
                            "maxDamage": round(dmax["damage"], 1),
                            "sameTypeBonus": same_type, "level": s.get("level", "?")})

        # ---- 玩家自定义筛选 ----
        # 1) 排除「升龙咆哮」 2) 威力<=60 的攻击技能剔除(龙系豁免)
        # 3) 按种族物攻/魔攻只显示匹配类型的攻击技能(双刀全显示)
        try:
            pa = int(atk_race.get("attack", 0) or 0)
        except (TypeError, ValueError):
            pa = 0
        try:
            ma = int(atk_race.get("mattack", 0) or 0)
        except (TypeError, ValueError):
            ma = 0
        allowed_types = ("物攻", "魔攻") if pa == ma else             (("物攻",) if pa > ma else ("魔攻",))

        def _keep(r):
            if r["name"] == "升龙咆哮":
                return False
            if not r["isDamage"]:
                return True  # 状态/变化技能保留
            if r["power"] <= 60 and r["attr"] != "龙":
                return False
            return r["type"] in allowed_types

        results = [r for r in results if _keep(r)]

        # 排序：克制→普通→抵抗→状态，同组内伤害降序
        def _sort_key(r):
            if not r["isDamage"]: return (3, 0)
            m = r["attrMultiplier"]
            if m >= 2: return (0, -r["maxDamage"])
            if m >= 1: return (1, -r["maxDamage"])
            return (2, -r["maxDamage"])
        results.sort(key=_sort_key)

        from src.pvp.damage_calculator import calculate_resonance_impact_damages
        resonance_data = calculate_resonance_impact_damages(
            enemy_panel=def_panels,
            self_panel=atk_panels,
            enemy_types=def_types,
            self_types=atk_types,
            self_current_hp=int(atk_panels.get("hp", 450))
        )

        return {"success": True, "atkPanels": atk_panels, "defPanels": def_panels,
                "atkRace": atk_race, "defRace": def_race, "atkTypes": atk_types,
                "defTypes": def_types, "atkName": atk_pet.get("name", "") if atk_pet else "",
                "defName": def_pet.get("name", "") if def_pet else "",
                "skills": results,
                "resonance_impact": resonance_data,
                "mySpeed": round(atk_panels.get("speed", 0)),
                "enemySpeed": round(def_panels.get("speed", 0)),
                "speedResult": "我方先手" if atk_panels.get("speed", 0) > def_panels.get("speed", 0) else (
                    "敌方先手" if atk_panels.get("speed", 0) < def_panels.get("speed", 0) else "速度相同")}

    def pvp_recognize(self) -> dict:
        """捕获游戏画面 → 识别精灵列表（OCR+图像）
        默认裁剪游戏窗口左侧 40%（PVP 精灵列表区域）"""
        import tempfile, subprocess, json as _json
        try:
            # 1. 截图
            info = self._find_game_window()
            if not info:
                return {"success": False, "message": "未找到游戏窗口"}
            left, top, right, bottom = info.rect
            w, h = right - left, bottom - top
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(left, top, right, bottom))

            # 2. 裁剪左侧（PVP 精灵列表区域，默认左 40%）
            crop_left = 0
            crop_right = int(w * 0.4)
            img = img.crop((crop_left, 0, crop_right, h))

            tmp = Path(tempfile.gettempdir()) / "pvp_capture.png"
            img.save(str(tmp))

            # 3. 识别
            lib_dir = PROJECT_ROOT / "src" / "pvp" / "lib"
            result = subprocess.run(
                [sys.executable, str(lib_dir / "pvp_lib.py"), "recognize", str(tmp)],
                capture_output=True, text=True, timeout=120,
                cwd=str(lib_dir)
            )
            if result.returncode != 0:
                return {"success": False, "message": f"识别失败: {result.stderr[:200]}"}

            data = _json.loads(result.stdout) if result.stdout.strip() else {}
            pets = data.get("pets", data.get("results", []))
            return {"success": True, "pets": pets, "file": str(tmp)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def resource_sync(self) -> dict:
        """从官方 API / 本地高清库一键同步最新图鉴与技能图标资源"""
        try:
            from src.pvp.resource_updater import ResourceUpdater
            updater = ResourceUpdater(on_progress=lambda msg, p: self._enqueue_log(msg, "info" if p < 1.0 else "success"))
            res = updater.sync()
            return res
        except Exception as e:
            self._enqueue_log(f"资源同步失败: {e}", "error")
            return {"success": False, "message": str(e)}

    def resource_get_stats(self) -> dict:
        """获取当前本地收录的官方图鉴与图标统计"""
        try:
            web_img = PROJECT_ROOT / "src" / "gui" / "web" / "assets" / "img"
            pet_count = len(list((web_img / "pets").glob("*.webp"))) if (web_img / "pets").exists() else 0
            skill_count = len(list((web_img / "skills").glob("*.webp"))) if (web_img / "skills").exists() else 0
            icon_count = len(list((web_img / "icons").glob("*.webp"))) if (web_img / "icons").exists() else 0
            return {
                "success": True,
                "stats": {
                    "pets": pet_count,
                    "skills": skill_count,
                    "icons": icon_count,
                }
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    def pvp_float_toggle(self) -> dict:
        """显示合并悬浮窗并切到 PVP 标签(与挂机悬浮窗同一窗口)"""
        gate = self._auth_gate()
        if gate:
            return gate
        if not getattr(self, "_pvp_float_window", None):
            return {"success": False, "message": "PVP悬浮窗未创建"}
        try:
            result = self.widget_toggle()
            if result.get("visible"):
                try:
                    self._pvp_float_window.evaluate_js('switchTab("pvp")')
                except Exception:
                    pass
            return {"success": True, "visible": result.get("visible", False)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def pvp_float_update(self, data: dict) -> dict:
        if not getattr(self, "_pvp_float_window", None):
            return {"success": False, "message": "PVP悬浮窗未创建"}
        if not getattr(self, "_widget_visible", False):
            return {"success": False, "message": "悬浮窗未打开"}
        if not getattr(self, "_pvp_float_loaded", False):
            return {"success": False, "message": "悬浮窗加载中，请稍后"}
        try:
            js = f"updatePVPData({json.dumps(data, ensure_ascii=False)})"
            self._pvp_float_window.evaluate_js(js)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def pvp_get_asset(self, asset_type: str, key: str) -> dict:
        """返回任意素材的 base64 编码
        asset_type: 'pet' | 'skill' | 'trait' | 'icon'
        key: 精灵序号(如'1') | 技能名 | 特性序号 | 属性英文名(如'fire')
        """
        import base64

        assets_dir = PROJECT_ROOT / "src" / "pvp" / "data" / "assets"
        index_map = {"pet": "pet_index.json", "skill": "skill_index.json", "icon": "icon_map.json"}

        if asset_type == "pet":
            idx_path = assets_dir / "pet_index.json"
            if not idx_path.exists():
                return {"success": False, "message": "精灵头像索引不存在"}
            with open(idx_path, "r", encoding="utf-8") as f:
                pet_idx = json.load(f)
            filename = pet_idx.get(str(int(key)))
            if not filename:
                return {"success": False, "message": f"精灵 #{key} 无头像"}
            img_path = assets_dir / "pets" / filename

        elif asset_type == "skill":
            idx_path = assets_dir / "skill_index.json"
            if not idx_path.exists():
                return {"success": False, "message": "技能图标索引不存在"}
            with open(idx_path, "r", encoding="utf-8") as f:
                skill_idx = json.load(f)
            filename = skill_idx.get(key)
            if not filename:
                return {"success": False, "message": f"技能 '{key}' 无图标"}
            img_path = assets_dir / "skills" / filename

        elif asset_type == "trait":
            img_path = assets_dir / "traits" / f"{key}.webp"
            if not img_path.exists():
                return {"success": False, "message": f"特性 #{key} 无图标"}

        elif asset_type == "icon":
            img_path = assets_dir / "icons" / f"{key}.webp"
            if not img_path.exists():
                return {"success": False, "message": f"属性图标 '{key}' 不存在"}

        else:
            return {"success": False, "message": f"未知素材类型: {asset_type}"}

        if not img_path.exists():
            return {"success": False, "message": f"素材文件不存在"}

        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")

        return {"success": True, "image": f"data:image/webp;base64,{b64}", "filename": img_path.name}

    def _get_fast_capture(self):
        """获取/创建 FastCapture 单例"""
        if self._fast_cap is None:
            from src.capture.fast_capture import FastCapture
            self._fast_cap = FastCapture()
        return self._fast_cap

    def _live_capture_frame(self):
        """通过 FastCapture 单例截屏（mss, ~15ms）"""
        import cv2, numpy as np
        info = self._find_game_window()
        if not info:
            raise RuntimeError("未找到「洛克王国」窗口")
        left, top, right, bottom = info.rect
        if right - left < 50 or bottom - top < 50:
            raise RuntimeError("游戏窗口过小或最小化")
        fc = self._get_fast_capture()
        frame = fc.capture(rect=(left, top, right - left, bottom - top))
        if frame is None or frame.size == 0:
            raise RuntimeError("截图失败")
        if float(frame.std()) < 3.0:
            raise RuntimeError("画面全黑: 游戏未在前台渲染,请点一下游戏窗口")
        return info, frame

    def _live_loop(self):
        import json as _json
        import numpy as np
        from src.perception.vision_pipeline import VisionPipeline, DEFAULT_ROI_CONFIG

        try:
            roi = _json.loads(DEFAULT_ROI_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            roi = {}

        # 启动后台抓图线程
        info = self._find_game_window()
        if info:
            left, top, right, bottom = info.rect
            fc = self._get_fast_capture()
            fc.start_worker((left, top, right - left, bottom - top), fps=30)
            self._enqueue_log("后台抓图线程已启动 (30 FPS)", "info")

        while self._live_running and not self._stop_event.is_set():
            try:
                # 从后台线程取最新帧（丢帧机制，无堆积）
                fc = self._get_fast_capture()
                frame = fc.get_latest_frame()
                if frame is None:
                    # 后台线程未就绪，同步截一次
                    info, frame = self._live_capture_frame()
                else:
                    info = self._find_game_window()
                    if not info:
                        raise RuntimeError("未找到「洛克王国」窗口")
                if frame is None:
                    self._stop_event.wait(self._live_interval)
                    continue
                self._live_black_warned = False

                # 帧差检测：像素均值差 < 5 则跳过识别
                try:
                    if self._live_last_frame is not None and frame is not None:
                        diff = float(np.abs(
                            frame.astype(np.int16)[::4, ::4] -
                            self._live_last_frame.astype(np.int16)[::4, ::4]
                        ).mean())
                        if diff < 5.0:
                            self._stop_event.wait(self._live_interval)
                            continue
                except Exception:
                    pass  # 帧差失败不阻塞，继续识别
                if frame is not None:
                    self._live_last_frame = frame.copy()

                if frame is None:
                    self._stop_event.wait(self._live_interval)
                    continue
                if self._live_pipeline is None:
                    self._live_pipeline = VisionPipeline()
                try:
                    result = self._live_pipeline.analyze(frame).to_dict()
                except Exception as e:
                    self._enqueue_log(f"识别异常: {e}", "warning")
                    self._stop_event.wait(self._live_interval)
                    continue
                payload = {
                    "image": self._frame_to_jpeg_dataurl(
                        frame, max_width=self._live_max_width or None),  # 画质可调
                    "width": info.width, "height": info.height,
                    "result": result, "roi": roi,
                }
                if self._window:
                    self._window.evaluate_js(
                        f"updateLiveResult({_json.dumps(payload, ensure_ascii=False)})")
            except RuntimeError as e:
                msg = str(e)
                if "全黑" in msg and not self._live_black_warned:
                    self._live_black_warned = True
                    self._enqueue_log(f"实时识别: {msg}(保持游戏前台即可恢复)", "warning")
                elif "未找到" in msg and not self._live_black_warned:
                    self._live_black_warned = True
                    self._enqueue_log(f"实时识别: {msg}", "warning")
            except Exception as e:
                self._enqueue_log(f"实时识别异常: {e}", "error")
            self._stop_event.wait(self._live_interval)

    def vision_save_shot(self) -> dict:
        """截图保存到 data/screenshots（供裁剪工具/演示脚本使用）"""
        try:
            info, frame = self._capture_frame()
        except Exception as e:
            return {"success": False, "message": str(e)}
        try:
            from src.utils.image_io import imwrite_unicode
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = SCREENSHOT_DIR / time.strftime("shot_%Y%m%d_%H%M%S.png")
            # 必须用 imwrite_unicode:项目路径含中文,cv2.imwrite 在部分进程下会静默失败
            if not imwrite_unicode(path, frame):
                raise RuntimeError(f"图像编码或写入失败: {path}")
            self._last_shot_path = path
            self._enqueue_log(f"截图已保存: {path.name}", "success")
            return {"success": True, "path": path.name, "full_path": str(path)}
        except Exception as e:
            self._enqueue_log(f"保存截图失败: {e}", "error")
            return {"success": False, "message": str(e)}

    # ========================================
    # 3. 工具箱 API
    # ========================================

    def tools_list(self) -> dict:
        items = []
        for t in TOOLS:
            # 用户版只保留辅助工具(连点器),标注/诊断类工具仅开发者模式可见
            if not DEV_MODE and t.get("category", "helper") != "helper":
                continue
            proc = self._tool_procs.get(t["id"])
            running = bool(proc and proc["proc"].poll() is None)
            if not running and proc:
                self._tool_procs.pop(t["id"], None)
            items.append({
                "id": t["id"],
                "name": t["name"],
                "desc": t["desc"],
                "gui": t["gui"],
                "category": t.get("category", "helper"),
                "tag": t.get("tag", "工具"),
                "running": running,
            })
        return {"success": True, "tools": items}

    def tool_start(self, tool_id: str) -> dict:
        tool = next((t for t in TOOLS if t["id"] == tool_id), None)
        if not tool:
            return {"success": False, "message": f"未知工具: {tool_id}"}
        if not DEV_MODE and tool.get("category", "helper") != "helper":
            return {"success": False, "message": f"{tool['name']} 仅开发者模式可用"}
        proc_info = self._tool_procs.get(tool_id)
        if proc_info and proc_info["proc"].poll() is None:
            return {"success": False, "message": f"{tool['name']} 已在运行"}

        # 按策略准备参数
        args: list[str] = []
        if tool["arg"] == "shot":
            shot = self.vision_save_shot()
            if not shot.get("success"):
                return {"success": False,
                        "message": f"自动截图失败,无法启动: {shot.get('message')}"}
            args.append(str(self._last_shot_path))
        elif tool["arg"] == "last":
            path = self._resolve_last_screenshot()
            if not path:
                # 尝试自动截一张
                shot = self.vision_save_shot()
                if shot.get("success"):
                    path = self._last_shot_path
            if not path or not path.exists():
                return {"success": False,
                        "message": "没有可用截图,请先在视觉调试台截图或保持游戏前台运行"}
            args.append(str(path))
            self._enqueue_log(f"{tool['name']} 使用截图: {path.name}", "info")

        script = PROJECT_ROOT / tool["script"]
        if not script.exists():
            return {"success": False, "message": f"脚本不存在: {script}"}

        cmd = [sys.executable, str(script)] + args
        try:
            if tool["gui"]:
                proc = subprocess.Popen(
                    cmd, cwd=str(PROJECT_ROOT),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                proc = subprocess.Popen(
                    cmd, cwd=str(PROJECT_ROOT),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                threading.Thread(target=self._pump_tool_output,
                                 args=(proc, tool["name"]), daemon=True).start()
        except Exception as e:
            self._enqueue_log(f"启动 {tool['name']} 失败: {e}", "error")
            return {"success": False, "message": str(e)}

        self._tool_procs[tool_id] = {"proc": proc, "name": tool["name"]}
        self._enqueue_log(f"已启动 {tool['name']} (PID {proc.pid})", "success")
        return {"success": True, "pid": proc.pid}

    def tool_stop(self, tool_id: str) -> dict:
        tool = next((t for t in TOOLS if t["id"] == tool_id), None)
        name = tool["name"] if tool else tool_id
        if tool_id not in self._tool_procs:
            return {"success": False, "message": f"{name} 未在运行"}
        self._kill_tool(tool_id)
        self._enqueue_log(f"已停止 {name}", "warning")
        return {"success": True}

    def _kill_tool(self, tool_id: str):
        info = self._tool_procs.pop(tool_id, None)
        if not info:
            return
        proc = info["proc"]
        if proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                proc.terminate()

    def _pump_tool_output(self, proc: subprocess.Popen, name: str):
        """把 CLI 工具的 stdout 回流到日志"""
        try:
            for raw in iter(proc.stdout.readline, b""):
                if not raw:
                    break
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("gbk", errors="replace")
                text = text.rstrip()
                if text:
                    self._enqueue_log(f"[{name}] {text}", "info")
        except Exception:
            pass
        finally:
            code = proc.poll()
            self._enqueue_log(f"[{name}] 进程结束 (code {code})", "info")

    def _resolve_last_screenshot(self) -> Path | None:
        if self._last_shot_path and self._last_shot_path.exists():
            return self._last_shot_path
        if SCREENSHOT_DIR.exists():
            pngs = sorted(SCREENSHOT_DIR.glob("*.png"))
            if pngs:
                return pngs[-1]
        return None

    # ========================================
    # 4. 配置中心 API
    # ========================================

    def config_load(self, name: str) -> dict:
        """读取配置并解析为对象 (前端视觉调试台加载 roi_config 用; JSON/YAML 均可)"""
        try:
            path = CONFIG_DIR / name
            if not path.exists():
                return {"success": False, "message": f"配置不存在: {name}", "data": None}
            content = path.read_text(encoding="utf-8")
            if name.endswith(".yaml") or name.endswith(".yml"):
                import yaml
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "message": str(e), "data": None}

    def config_list(self) -> dict:
        items = []
        for name, meta in CONFIG_FILES.items():
            path = CONFIG_DIR / name
            items.append({
                "name": name,
                "title": meta.get("title", name),
                "icon": meta.get("icon", "📄"),
                "type": meta["type"],
                "desc": meta["desc"],
                "page_hint": meta.get("page_hint", ""),
                "gui_page": meta.get("gui_page", ""),
                "fields": meta.get("fields", []),
                "exists": path.exists(),
                "size": path.stat().st_size if path.exists() else 0,
            })
        return {"success": True, "files": items}

    def config_read(self, name: str) -> dict:
        if not DEV_MODE:
            return {"success": False, "message": "配置文件编辑仅开发者模式可用"}
        if name not in CONFIG_FILES:
            return {"success": False, "message": f"未知配置: {name}"}
        path = CONFIG_DIR / name
        if not path.exists():
            return {"success": True, "content": "", "empty": True}
        try:
            return {"success": True, "content": path.read_text(encoding="utf-8")}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def config_save(self, name: str, content: str) -> dict:
        if not DEV_MODE:
            return {"success": False, "message": "配置文件编辑仅开发者模式可用"}
        if name not in CONFIG_FILES:
            return {"success": False, "message": f"未知配置: {name}"}
        meta = CONFIG_FILES[name]
        try:
            if meta["type"] == "json":
                json.loads(content)
            elif meta["type"] == "yaml":
                import yaml
                yaml.safe_load(content)
        except Exception as e:
            return {"success": False, "message": f"格式语法错误,未保存: {e}"}

        path = CONFIG_DIR / name
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except Exception as e:
            return {"success": False, "message": str(e)}

        self._enqueue_log(f"配置已保存: {name}", "success")

        # ROI 配置保存后,实时识别下一帧起用新坐标
        if name == "roi_config.json":
            self._live_pipeline = None
            self._enqueue_log("ROI 已更新,实时识别将从下一帧使用新坐标", "info")

        # settings.yaml 保存后刷新统一配置缓存
        if name == "settings.yaml":
            try:
                from src.utils.settings import invalidate
                invalidate()
                self._enqueue_log("全局配置缓存已刷新", "info")
            except Exception as e:
                self._enqueue_log(f"刷新配置缓存失败: {e}", "error")

        # 丢球配置保存后立即应用到运行中的工具
        if name == "throw_ball_config.json":
            try:
                data = json.loads(content)
                self.tool.update_config(data)
                self._enqueue_log("丢球工具配置已热加载", "info")
            except Exception as e:
                self._enqueue_log(f"热更新丢球工具配置失败: {e}", "warning")

        return {"success": True}

    def config_reset_default(self, name: str) -> dict:
        """恢复指定配置文件的默认推荐配置"""
        if not DEV_MODE:
            return {"success": False, "message": "配置文件编辑仅开发者模式可用"}
        if name not in CONFIG_FILES:
            return {"success": False, "message": f"未知配置: {name}"}

        defaults = {
            "throw_ball_config.json": json.dumps({
                "normal_min": 0.35,
                "normal_max": 0.5,
                "bomber_charge_min": 0.3,
                "bomber_charge_max": 0.5,
                "bomber_hover_min": 2.0,
                "bomber_hover_max": 2.2,
                "skill_min": 1.0,
                "skill_max": 2.0,
                "stop_after_count": 0,
                "stop_after_minutes": 0,
                "exit_on_battle": True,
            }, indent=2, ensure_ascii=False),
            "settings.yaml": (
                "capture:\n"
                "  fps: 30\n"
                "  region:\n"
                "    left: 0\n"
                "    top: 0\n"
                "    width: 1920\n"
                "    height: 1080\n"
                "battle:\n"
                "  catch_hp: 50\n"
                "  open_ball_key: w\n"
                "  ball_slot_key: '1'\n"
                "  ball_ui_wait: 0.8\n"
                "  ball_cooldown: 3.0\n"
                "  flee_hp: 8\n"
                "  flee_key: ''\n"
                "  skills:\n"
                "  - '1'\n"
                "  skill_interval_min: 1.2\n"
                "  skill_interval_max: 2.0\n"
                "  battle_timeout: 240\n"
                "  max_balls_per_battle: 30\n"
                "patrol:\n"
                "  enabled: true\n"
                "  move_key: w\n"
                "  move_min: 1.5\n"
                "  move_max: 3.0\n"
                "  turn_mode: mouse\n"
                "  turn_chance: 0.35\n"
                "  stuck_limit: 6\n"
                "fsm:\n"
                "  battle_timeout: 300\n"
                "  wait_timeout: 60\n"
                "gui:\n"
                "  width: 1150\n"
                "  height: 780\n"
                "  theme: dark\n"
            ),
            "roi_config.json": json.dumps({
                "enemy_name": {"left": 0.5281, "top": 0.0528, "width": 0.1349, "height": 0.0389, "label": "精灵名称"},
                "enemy_elements": {"left": 0.6698, "top": 0.0528, "width": 0.0271, "height": 0.0389, "label": "属性"},
                "enemy_hp": {"left": 0.7042, "top": 0.0611, "width": 0.0594, "height": 0.0306, "label": "敌方血量"},
                "battle_left_indicator": {"left": 0.0323, "top": 0.0343, "width": 0.0469, "height": 0.0435, "label": "左角标"},
                "battle_right_indicator": {"left": 0.9208, "top": 0.0343, "width": 0.0469, "height": 0.0435, "label": "右角标"}
            }, indent=2, ensure_ascii=False),
        }

        if name not in defaults:
            return {"success": False, "message": f"该配置文件暂无内置重置模板"}

        content = defaults[name]
        res = self.config_save(name, content)
        if res.get("success"):
            return {"success": True, "content": content}
        return res

        # 丢球配置保存后立即应用到运行中的工具
        if name == "throw_ball_config.json":
            try:
                data = json.loads(content)
                for key, value in self._validate_throw_params(data).items():
                    setattr(self.tool, key, value)
                self._enqueue_log("丢球延迟已热应用到当前工具实例", "info")
            except Exception as e:
                self._enqueue_log(f"热应用丢球配置失败: {e}", "error")
        return {"success": True}

    # ========================================
    # ROI 模板管理 (Step 1: 多ROI + 归一化坐标)
    # ========================================
    def roi_template_list(self) -> dict:
        from src.pvp.roi_template import list_templates
        return {"success": True, "templates": list_templates()}

    def roi_template_save(self, name: str, base_resolution: list, rois: list) -> dict:
        from src.pvp.roi_template import save_template
        return save_template(name, base_resolution, rois)

    def roi_template_load(self, name: str) -> dict:
        from src.pvp.roi_template import load_template
        data = load_template(name)
        if data is None:
            return {"success": False, "message": f"模板 '{name}' 不存在"}
        return {"success": True, "template": data}

    def roi_template_export(self, name: str) -> dict:
        from src.pvp.roi_template import export_template
        data = export_template(name)
        if data is None:
            return {"success": False, "message": f"模板 '{name}' 不存在"}
        return {"success": True, "json": data}

    def roi_template_import(self, json_str: str) -> dict:
        from src.pvp.roi_template import import_template
        return import_template(json_str)

    def roi_template_delete(self, name: str) -> dict:
        from src.pvp.roi_template import delete_template
        return delete_template(name)

    def roi_template_set_active(self, name: str, mode: str = "pvp") -> dict:
        from src.pvp.roi_template import set_active_template
        return set_active_template(name, mode)

    def roi_export_crop(self, rect: list, save_name: str = None) -> dict:
        """根据像素区域 [x,y,w,h] 裁剪当前帧保存为 PNG"""
        from pathlib import Path
        import cv2
        if self._last_frame is None:
            return {"success": False, "message": "请先截图或启动实时识别"}
        x, y, w, h = map(int, rect)
        hh, ww = self._last_frame.shape[:2]
        x = max(0, min(x, ww - 1)); y = max(0, min(y, hh - 1))
        w = min(w, ww - x); h = min(h, hh - y)
        if w <= 0 or h <= 0:
            return {"success": False, "message": "裁剪区域无效"}
        crop = self._last_frame[y:y + h, x:x + w]
        save_name = save_name or f"roi_crop_{x}_{y}_{w}x{h}.png"
        out_dir = Path(__file__).resolve().parents[2] / "data" / "vision" / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / save_name
        cv2.imwrite(str(out_path), crop)
        return {"success": True, "path": str(out_path), "size": [w, h]}

    def mode_get(self) -> dict:
        return {"success": True, "mode": self.mode_ctrl.current_mode,
                "label": self.mode_ctrl.mode_label}

    def mode_switch(self, mode: str) -> dict:
        return self.mode_ctrl.switch_to(mode)

    # ========================================
    # 5. 状态轮询 + 任务栏数据
    # ========================================

    def get_state(self) -> dict:
        try:
            game_active = self.tool.is_game_window_active()
        except Exception:
            game_active = False

        tasks = []
        if self.tool.running:
            tasks.append({"id": "normal", "name": "普通丢球",
                          "detail": f"已丢 {self.tool.normal_count} 球"})
        if self.tool.bomber_running:
            tasks.append({"id": "bomber", "name": "轰炸机",
                          "detail": f"已丢 {self.tool.bomber_count} 球"})
        if self.tool.skill_running:
            tasks.append({"id": "skill", "name": "自动技能",
                          "detail": f"已按 {self.tool.skill_count} 次"})
        if self._live_running:
            tasks.append({"id": "live", "name": "实时识别",
                          "detail": f"每 {self._live_interval}s"})
        if self.engine.running:
            state_names = {"waiting": "等战斗", "fighting": "战斗中",
                           "throwing": "丢球", "paused": "暂停"}
            tasks.append({"id": "engine", "name": "战斗引擎" + ("(模拟)" if self.engine.dry_run else ""),
                          "detail": f"{state_names.get(self.engine.state, self.engine.state)} {self.engine.state_detail}"})
        for tool_id, info in list(self._tool_procs.items()):
            if info["proc"].poll() is None:
                tasks.append({"id": f"tool:{tool_id}", "name": info["name"],
                              "detail": f"PID {info['proc'].pid}"})
            else:
                self._tool_procs.pop(tool_id, None)

        return {
            "game_active": game_active,
            "normal_running": self.tool.running,
            "bomber_running": self.tool.bomber_running,
            "skill_running": self.tool.skill_running,
            "normal_count": self.tool.normal_count,
            "bomber_count": self.tool.bomber_count,
            "skill_count": self.tool.skill_count,
            "config": self._get_throw_config(),
            "throw_run": {
                "running": bool(self.tool.running or self.tool.bomber_running),
                "elapsed": (time.time() - self.tool._run_started_at)
                           if (self.tool.running or self.tool.bomber_running)
                           and getattr(self.tool, "_run_started_at", 0) else 0,
                "thrown": (self.tool.normal_count - getattr(self.tool, "_run_start_count", 0))
                          + (self.tool.bomber_count - getattr(self.tool, "_bomber_run_start_count", 0)),
                "quota_count": self.tool.stop_after_count,
                "quota_minutes": self.tool.stop_after_minutes,
            },
            "ball_inventory": (self.ball_watcher.status() if getattr(self, "ball_watcher", None)
                               else {"enabled": False, "mode": "-", "samples": 0,
                                     "updated_at": "", "slots": []}),
            "tasks": tasks,
            "update_hint": getattr(self, "_update_hint", None),
        }

    # ========================================
    # 7. 天梯战报与 ELO 分析 API
    # ========================================

    def pvp_get_history(self, limit: int = 50, offset: int = 0, filter_result: str = "ALL") -> dict:
        """分页获取天梯历史战报"""
        from src.pvp.history_db import get_history_db
        db = get_history_db()
        history = db.get_history(limit=int(limit), offset=int(offset), filter_result=str(filter_result))
        return {"success": True, "history": history}

    def pvp_get_history_stats(self) -> dict:
        """获取大盘统计和 ELO 克制遭遇分析"""
        from src.pvp.history_db import get_history_db
        db = get_history_db()
        stats = db.get_summary_stats()
        elo = db.get_elo_counter_stats()
        return {"success": True, "stats": stats, "elo": elo}

    def pvp_record_match(self, match_data: dict) -> dict:
        """手动或自动沉淀一笔战报"""
        from src.pvp.history_db import get_history_db
        db = get_history_db()
        row_id = db.record_match(
            result=match_data.get("result", "WIN"),
            my_team=match_data.get("my_team", []),
            enemy_team=match_data.get("enemy_team", []),
            duration_sec=int(match_data.get("duration_sec", 0)),
            rank_tier=match_data.get("rank_tier", "天梯排位"),
            is_crush=match_data.get("is_crush"),
            notes=match_data.get("notes", "")
        )
        return {"success": True, "id": row_id}

    def pvp_clear_history(self) -> dict:
        """清空历史战报"""
        from src.pvp.history_db import get_history_db
        get_history_db().clear_all()
        return {"success": True}

    def pvp_generate_mock_history(self, count: int = 15) -> dict:
        """生成演示战报"""
        from src.pvp.history_db import get_history_db
        get_history_db().generate_mock_data(int(count))
        return {"success": True}


class Api:
    """pywebview 自动把此类方法暴露给前端 JavaScript"""

    def __init__(self, bridge: AppBridge):
        self._bridge = bridge

    # 账户登录/卡密 (前端侧栏激活入口依赖这三个 API)
    def auth_status(self):
        return self._bridge.auth_status()

    def auth_activate(self, code):
        return self._bridge.auth_activate(code)

    def auth_logout(self):
        return self._bridge.auth_logout()

    # 运行模式
    def get_app_mode(self):
        return self._bridge.get_app_mode()

    # 丢球
    def toggle_normal(self):
        return self._bridge.toggle_normal()

    def toggle_bomber(self):
        return self._bridge.toggle_bomber()

    def toggle_skill(self):
        return self._bridge.toggle_skill()

    def stop_all(self):
        return self._bridge.stop_all()

    def update_config(self, params):
        return self._bridge.update_config(params)

    # 视觉
    def vision_status(self):
        return self._bridge.vision_status()

    def vision_capture(self, front: bool = True, source: str = "main"):
        return self._bridge.vision_capture(front, source)

    def vision_analyze(self, front: bool = True, source: str = "main"):
        return self._bridge.vision_analyze(front, source)

    def vision_ocr_preview(self, rois=None):
        return self._bridge.vision_ocr_preview(rois)

    def vision_save_shot(self):
        return self._bridge.vision_save_shot()

    def vision_live_start(self):
        return self._bridge.vision_live_start()

    def vision_live_stop(self):
        return self._bridge.vision_live_stop()

    def vision_live_quality(self, quality: str = "fast"):
        return self._bridge.vision_live_quality(quality)

    # ROI 标注工坊
    def roi_studio_open(self):
        return self._bridge.roi_studio_open()

    def roi_studio_state(self):
        return self._bridge.roi_studio_state()

    def roi_studio_save(self, name, base_resolution, rois):
        return self._bridge.roi_studio_save(name, base_resolution, rois)

    # 配置中心
    def config_load(self, name):
        return self._bridge.config_load(name)

    # 战斗引擎
    def engine_start(self, dry_run=False, params=None):
        return self._bridge.engine_start(dry_run, params)

    def engine_stop(self):
        return self._bridge.engine_stop()

    def engine_status(self):
        return self._bridge.engine_status()

    def engine_get_settings(self):
        return self._bridge.engine_get_settings()

    def engine_save_settings(self, params):
        return self._bridge.engine_save_settings(params)

    # 工具箱
    def tools_list(self):
        return self._bridge.tools_list()

    def tool_start(self, tool_id):
        return self._bridge.tool_start(tool_id)

    def tool_stop(self, tool_id):
        return self._bridge.tool_stop(tool_id)

    # 配置中心
    def config_list(self):
        return self._bridge.config_list()

    def config_read(self, name):
        return self._bridge.config_read(name)

    def config_save(self, name, content):
        return self._bridge.config_save(name, content)

    def config_reset_default(self, name):
        return self._bridge.config_reset_default(name)

    def roi_template_list(self):
        return self._bridge.roi_template_list()

    def roi_template_save(self, name, base_resolution, rois):
        return self._bridge.roi_template_save(name, base_resolution, rois)

    def roi_template_load(self, name):
        return self._bridge.roi_template_load(name)

    def roi_template_export(self, name):
        return self._bridge.roi_template_export(name)

    def roi_template_import(self, json_str):
        return self._bridge.roi_template_import(json_str)

    def roi_template_delete(self, name):
        return self._bridge.roi_template_delete(name)

    def roi_template_set_active(self, name, mode="pvp"):
        return self._bridge.roi_template_set_active(name, mode)

    def roi_export_crop(self, rect, save_name=None):
        return self._bridge.roi_export_crop(rect, save_name)

    def mode_get(self):
        return self._bridge.mode_get()

    def mode_switch(self, mode):
        return self._bridge.mode_switch(mode)

    # 状态
    def get_state(self):
        return self._bridge.get_state()

    def set_on_top(self, enabled):
        return self._bridge.set_on_top(enabled)

    def widget_toggle(self):
        return self._bridge.widget_toggle()

    def minimize_window(self):
        return self._bridge.minimize_window()

    def move_window_by(self, dx, dy):
        return self._bridge.move_window_by(dx, dy)
    def window_move_by(self, dx, dy):
        return self._bridge.window_move_by(dx, dy)

    def window_resize_by(self, dw, dh):
        return self._bridge.window_resize_by(dw, dh)
    def window_get_size(self):
        return self._bridge.window_get_size()

    def window_resize_to(self, width, height):
        return self._bridge.window_resize_to(width, height)


    def window_close(self):
        return self._bridge.window_close()
    def update_check(self):
        return self._bridge.update_check()

    def update_apply(self):
        return self._bridge.update_apply()

    def update_status(self):
        return self._bridge.update_status()

    def pokedex_data(self):
        return self._bridge.pokedex_data()
    def daily_list(self):
        return self._bridge.daily_list()

    def daily_save(self, tasks):
        return self._bridge.daily_save(tasks)

    def daily_run(self, task_id):
        return self._bridge.daily_run(task_id)

    def daily_stop(self):
        return self._bridge.daily_stop()

    def daily_status(self):
        return self._bridge.daily_status()


    def schedule_set(self, enabled, hh=19, mm=0, duration_min=120, mode="engine"):
        return self._bridge.schedule_set(enabled, hh, mm, duration_min, mode)

    def schedule_get(self):
        return self._bridge.schedule_get()



    def bag_scan(self):
        return self._bridge.bag_scan()

    def bag_open(self):
        return self._bridge.bag_open()

    def bag_open_and_scan(self):
        return self._bridge.bag_open_and_scan()

    def widget_resize(self, width=340, height=335):
        return self._bridge.widget_resize(width, height)

    def pvp_float_resize(self, width=360, height=540):
        return self._bridge.pvp_float_resize(width, height)

    # PVP 对战助手
    def pvp_search_pets(self, query=""):
        return self._bridge.pvp_search_pets(query)

    def pvp_get_pet(self, seq, title=None):
        return self._bridge.pvp_get_pet(seq, title)

    def pvp_search_skills(self, query=""):
        return self._bridge.pvp_search_skills(query)

    def pvp_calc_vs(self, atk_seq, def_seq, skill_name, atk_ivs=None, def_ivs=None):
        return self._bridge.pvp_calc_vs(atk_seq, def_seq, skill_name, atk_ivs, def_ivs)

    def pvp_get_all_pets(self):
        return self._bridge.pvp_get_all_pets()

    def pvp_get_all_skills(self):
        return self._bridge.pvp_get_all_skills()

    def pvp_calc_quick(self, atk_val, def_val, power, skill_type="物攻", skill_attr="普通", atk_attrs=None, def_attrs=None):
        return self._bridge.pvp_calc_quick(atk_val, def_val, power, skill_type, skill_attr, atk_attrs, def_attrs)

    def pvp_calc_panels(self, seq, high_ivs=None, iv_value=10, nature_up=None, nature_down=None):
        return self._bridge.pvp_calc_panels(seq, high_ivs, iv_value, nature_up, nature_down)

    def pvp_get_pet_skills_full(self, seq):
        return self._bridge.pvp_get_pet_skills_full(seq)

    def pvp_get_pet_preset(self, seq):
        return self._bridge.pvp_get_pet_preset(seq)

    def pvp_recognize(self):
        return self._bridge.pvp_recognize()

    def pvp_calc_all_skills(self, atk_seq, def_seq, atk_high_ivs=None, atk_iv_value=10, def_high_ivs=None, def_iv_value=10, atk_nature_up=None, atk_nature_down=None, def_nature_up=None, def_nature_down=None):
        return self._bridge.pvp_calc_all_skills(atk_seq, def_seq, atk_high_ivs, atk_iv_value, def_high_ivs, def_iv_value, atk_nature_up, atk_nature_down, def_nature_up, def_nature_down)

    def pvp_float_toggle(self):
        return self._bridge.pvp_float_toggle()

    def pvp_float_update(self, data):
        return self._bridge.pvp_float_update(data)

    def pvp_get_asset(self, asset_type, key):
        return self._bridge.pvp_get_asset(asset_type, key)

    def pvp_engine_start(self):
        return self._bridge.pvp_engine_start()

    def pvp_engine_stop(self):
        return self._bridge.pvp_engine_stop()

    def pvp_engine_status(self):
        return self._bridge.pvp_engine_status()

    def pvp_collector_start(self):
        return self._bridge.pvp_collector_start()

    def pvp_collector_stop(self):
        return self._bridge.pvp_collector_stop()

    def pvp_collector_status(self):
        return self._bridge.pvp_collector_status()

    def pvp_collector_manual(self):
        return self._bridge.pvp_collector_manual()

    # 官方资源自动同步
    def resource_sync(self):
        return self._bridge.resource_sync()

    def resource_get_stats(self):
        return self._bridge.resource_get_stats()

    # 天梯战报与 ELO 分析
    def pvp_get_history(self, limit=50, offset=0, filter_result="ALL"):
        return self._bridge.pvp_get_history(limit, offset, filter_result)

    def pvp_get_history_stats(self):
        return self._bridge.pvp_get_history_stats()

    def pvp_record_match(self, match_data):
        return self._bridge.pvp_record_match(match_data)

    def pvp_clear_history(self):
        return self._bridge.pvp_clear_history()

    def pvp_generate_mock_history(self, count=15):
        return self._bridge.pvp_generate_mock_history(count)


__all__ = ['AppBridge', 'Api']
