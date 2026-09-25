"""AppBridge Mix-in —— 窗口生命周期 / 悬浮窗定位与状态 / 全局热键 / 状态推送"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from src.gui.bridge_common import PROJECT_ROOT, CONFIG_DIR

# 悬浮窗惰性创建的全局锁: 防止热键/界面按钮/任务自动弹出并发建出两个窗
_WIDGET_CREATE_LOCK = threading.Lock()


class WidgetMixin:

    # ========================================
    # 生命周期
    # ========================================

    def set_window(self, window):
        self._window = window
        self._start_log_pusher()
        self._start_watch_loop()  # 观察模式: 悬浮窗的被动战情监视

    def set_widget_window(self, window):
        """设置悬浮状态窗引用; 传 None = 惰性模式(首次唤出时才真正建窗)。

        为什么不再启动即建 hidden 窗: pywebview 对 hidden 窗用 Opacity
        Show/Hide 技巧规避启动闪烁, 但 WebView2 是跨进程 airspace, 该技巧
        在部分机器上失效 —— 创建位置会残留一块永不绘制的黑色表面(启动黑框),
        且之后 show() 也无法让它画出内容。改为惰性创建 + 出生即可见。
        """
        self._widget = window
        self._widget_visible = False
        self._last_widget_pos = None   # 物理像素落点(show 后重新钉回用)
        self._widget_show_gen = 0      # show 请求代数: 丢弃过期的延迟 show
        self._widget_loaded_evt = threading.Event()
        self._widget_url = getattr(self, "_widget_url", None)
        if window is not None:
            self._bind_widget_events(window)

    def set_widget_url(self, uri: str):
        """惰性创建所需的悬浮窗页面地址(main.py/app_entry.py 启动时注入)"""
        self._widget_url = uri

    def _bind_widget_events(self, window):
        """loaded 门禁 + 关闭自愈(Alt+F4 后下次唤出自动重建)"""
        try:
            window.events.loaded += lambda: self._widget_loaded_evt.set()
        except Exception:
            pass

        def _on_closed():
            self._widget = None
            self._widget_visible = False
            self._pvp_float_visible = False
            self._widget_loaded_evt = threading.Event()
            try:
                self.set_pvp_float_window(None)
            except Exception:
                pass
        try:
            window.events.closed += _on_closed
        except Exception:
            pass

    def ensure_widget_window(self):
        """首次唤出时才创建悬浮窗; 已存在则直接返回。

        创建即可见(出生即渲染, 走与主窗口相同的正常路径): 首次打开有
        <1s 的主题深色→内容过渡(background_color 兜底), 换取彻底消灭
        hidden 建窗的幽灵黑框。创建后立即按记忆位置钉位。
        """
        if getattr(self, "_widget", None) is not None:
            return self._widget
        with _WIDGET_CREATE_LOCK:
            print("[悬浮窗] 惰性创建开始", flush=True)
            if getattr(self, "_widget", None) is not None:
                return self._widget
            import webview
            self._widget_show_gen = 0
            self._widget_loaded_evt = threading.Event()
            url = self._widget_url or (
                Path(PROJECT_ROOT) / "src" / "gui" / "web" / "float_console.html"
            ).as_uri()
            try:
                win = webview.create_window(
                    title='状态',
                    url=url,
                    js_api=self._api,
                    width=340,
                    height=335,
                    resizable=False,
                    frameless=True,
                    easy_drag=False,
                    on_top=True,
                    background_color='#0a0e1a',
                )
            except Exception as e:
                print(f"[悬浮窗] 创建失败: {e}", flush=True)
                self._enqueue_log(f"悬浮窗创建失败: {e}", "error")
                return None
            self._widget = win
            self._bind_widget_events(win)
            try:
                self.set_pvp_float_window(win)   # 合并悬浮窗: PVP 推演推送同窗
            except Exception:
                pass
            # 立即钉到记忆位置(创建默认位在主屏左上角, 必须马上搬走)
            try:
                self._place_widget()
            except Exception:
                pass
            self._enqueue_log("悬浮窗已创建(惰性, 首次唤出)")
            return win

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
        """显示/隐藏悬浮状态窗(首次唤出时惰性建窗)"""
        try:
            print(f"[悬浮窗] toggle: visible={self._widget_visible}", flush=True)
            if self._widget_visible and getattr(self, "_widget", None):
                # 作废尚在等待的延迟 show, 再隐藏
                self._widget_show_gen += 1
                self._widget.hide()
                self._widget_visible = False
                self._pvp_float_visible = False
            else:
                if not self.ensure_widget_window():
                    return {"success": False, "message": "悬浮窗创建失败"}
                self._show_widget_when_ready(refocus_game_after=True)
                self._enqueue_log(f"[DEBUG] Widget window shown, visible={self._widget_visible}", "info")
            return {"success": True, "visible": self._widget_visible}
        except Exception as e:
            self._enqueue_log(f"[ERROR] widget_toggle error: {e}", "error")
            import traceback
            self._enqueue_log(traceback.format_exc(), "error")
            return {"success": False, "message": str(e)}

    def _show_widget_when_ready(self, minimize_main_after=False, refocus_game_after=False):
        """show 悬浮窗的统一入口: 页面未 loaded 时先等(≤3s)再 show。

        WebView2 对隐藏窗口挂起渲染合成, 过早 show 只会露出一整块未绘制的
        深色空窗(启动黑框)。loaded 事件已到则立即弹; 没到则后台线程等待,
        期间用户再次切换显隐(代数变化)时放弃这次过期 show。
        """
        self._widget_show_gen = getattr(self, "_widget_show_gen", 0) + 1
        gen = self._widget_show_gen
        ready = getattr(self, "_widget_loaded_evt", None)
        if ready is None or ready.is_set():
            self._show_widget_common(minimize_main_after, refocus_game_after)
            return

        def _waiter():
            ready.wait(3.0)          # 页面异常时最多等 3s, 不无限卡住唤出
            if gen != getattr(self, "_widget_show_gen", gen):
                return
            try:
                self._show_widget_common(minimize_main_after, refocus_game_after)
            except Exception:
                pass
        threading.Thread(target=_waiter, daemon=True, name="WidgetShowGate").start()

    def _show_widget_common(self, minimize_main_after=False, refocus_game_after=False):
        """place → show → 钉位置 → 立即按内容校准尺寸; widget_toggle / 自动弹出共用"""
        self._place_widget()
        self._widget.show()
        self._widget_visible = True
        self._pvp_float_visible = True   # 同一窗口: 显示时 PVP 推送闸门同步开
        # show() 会 Activate 并可能重置位置, 显示后按物理像素再钉一次
        self._ensure_widget_on_screen()
        self._reassert_widget_pos()
        # 立即按当前内容校准尺寸(旧实现等 0.6s, 其间窗口偏大露出深色边)
        try:
            self._widget.evaluate_js("if (typeof syncSize === 'function') syncSize()")
        except Exception:
            pass
        # 前端 syncSize 会改窗口尺寸(高度变化可能溢出下边界), 稍后再自愈一次
        try:
            threading.Timer(0.6, self._on_widget_sized).start()
        except Exception:
            pass
        if minimize_main_after:
            try:
                self._window.minimize()
            except Exception:
                pass
            self._refocus_game_window_async(0.1)
        elif refocus_game_after:
            # show 会 Activate 抢走游戏焦点, 手动唤出(F2)后必须交还, 且必须在 show 之后
            self._refocus_game_window_async(0.15)

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
                # 等 loaded 再 show(消除启动黑框), show 后才最小化主窗/还焦点给游戏
                self._show_widget_when_ready(minimize_main_after=True)
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
        # 标记拖拽中(供 widget_resize 跳过), 300ms 无移动自动过期
        self._widget_dragging = True
        self._widget_drag_until = time.time() + 0.3
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
        # 拖拽中跳过 resize: resize 触发 WebView2 重排并与拖拽 SetWindowPos 抢渲染(闪烁)
        if getattr(self, "_widget_dragging", False) and time.time() < getattr(self, "_widget_drag_until", 0):
            return {"success": False, "message": "拖拽中,跳过 resize"}
        try:
            safe_w = max(280, min(620, int(width)))
            # 1400: PVP 全展开(VS看板+推演+威胁+星陨+AI聊天)内容高度可超 1000,
            # 旧上限 900 会把内容压缩重叠("展开挤在一起")
            safe_h = max(36, min(1400, int(height)))
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
