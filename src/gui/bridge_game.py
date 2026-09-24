"""AppBridge Mix-in —— 游戏窗口查找与遮挡守卫 / 游戏启动(含 WeGame 自动点击)"""

import json
import os
import subprocess
import time
from src.gui.bridge_common import CONFIG_DIR


class GameMixin:

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
    def _console_covers_game(game_hwnd, game_rect) -> bool:
        """控制台是否真的盖在游戏上面(Z 序判断, 不是矩形相交)。
        算法: 从游戏窗口沿 Z 序往上走, 枚举位于其上方的可见窗口;
        若存在本进程的"洛克王国"控制台窗口与游戏矩形相交且盖在其上 → 遮挡。
        旧版只比矩形相交(全屏窗口永远相交), 控制台在游戏后面也误报 → 引擎
        不停最小化控制台, 用户完全无法看日志(20260922 实机反馈)。"""
        try:
            import os
            import win32gui
            import win32process

            own_pid = os.getpid()
            gl, gt, gr, gb = game_rect
            # EnumWindows 返回顺序即 Z 序(顶层在前): 只关心排在游戏前面的窗口
            above = []
            seen_game = False

            def _cb(hwnd, _):
                nonlocal seen_game
                if hwnd == game_hwnd:
                    seen_game = True
                    return
                if seen_game:            # 游戏之后的(更底层)不再关心
                    return
                if not win32gui.IsWindowVisible(hwnd):
                    return
                if win32gui.GetWindowLong(hwnd, -20) & 0x80:  # GWL_EXSTYLE & WS_EX_TOOLWINDOW(悬浮窗)
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                title = win32gui.GetWindowText(hwnd)
                if pid == own_pid and "洛克王国" in title:
                    above.append(win32gui.GetWindowRect(hwnd))

            win32gui.EnumWindows(_cb, None)
            for (cl, ct, cr, cb_) in above:
                if cl < gr and cr > gl and ct < gb and cb_ > gt:
                    return True
            return False
        except Exception:
            return False

    def _guard_console_occlusion(self, game_rect, game_hwnd=None) -> bool:
        """识别引擎的遮挡防护: 控制台真盖在游戏上面时 mss 截到的是控制台画面。
        Z 序判定(见 _console_covers_game), 只有真遮挡才最小化控制台并记一次性日志;
        用户主动把控制台拖到游戏前面看日志 → 会提示一次; 控制台在后面时永不打扰。"""
        try:
            covered = bool(game_hwnd) and self._console_covers_game(game_hwnd, game_rect)
            if not covered:
                if getattr(self, "_occlusion_guarded", False):
                    self._occlusion_guarded = False
                return False
            if not getattr(self, "_occlusion_guarded", False):
                self._occlusion_guarded = True
                self._enqueue_log("⚠ 控制台盖在游戏上方, 引擎截到的是控制台画面 — 已自动最小化(看完日志把控制台拖到旁边即可)", "warning")
                try:
                    if self._window:
                        self._window.minimize()
                except Exception:
                    pass
            return True
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
