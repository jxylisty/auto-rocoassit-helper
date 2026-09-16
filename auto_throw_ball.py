# -*- coding: utf-8 -*-
"""
洛克王国 - 自动丢球工具
使用 interception 内核级硬件模拟，拟人化蓄力延迟

所有延迟参数均为实例属性，可在运行中动态调整（GUI / 外部调用）。
命令行运行: python auto_throw_ball.py
"""

import random
import time
import threading
import keyboard
import interception
import ctypes
from ctypes import wintypes

# Windows API 定义
user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.restype = ctypes.c_int

class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wintypes.HWND

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

# 目标窗口信息
TARGET_WINDOW_TITLE = "洛克王国：世界"
TARGET_WINDOW_CLASS = "UnrealWindow"


class AutoThrowBall:
    """自动扔球工具"""

    def __init__(self, on_log=None):
        # 日志回调（GUI 注入），为 None 时仅 print
        self.on_log = on_log

        # 自动捕获设备
        try:
            interception.auto_capture_devices()
            self._log("Interception 设备初始化完成", "success")
        except Exception as e:
            self._log(f"Interception 初始化失败: {e}", "error")

        # 可调延迟参数（秒），GUI 可运行中修改
        self.normal_min = 0.5          # 普通模式蓄力下限
        self.normal_max = 0.8          # 普通模式蓄力上限
        self.bomber_charge_min = 0.3   # 轰炸机蓄力下限
        self.bomber_charge_max = 0.5   # 轰炸机蓄力上限
        self.bomber_hover_min = 2.0    # 悬浮按键间隔下限
        self.bomber_hover_max = 2.2    # 悬浮按键间隔上限
        self.skill_min = 1.0           # 技能按键间隔下限
        self.skill_max = 2.0           # 技能按键间隔上限

        # 自动停止条件（0 = 不限制；达到任一条件自动停止普通/轰炸丢球）
        self.stop_after_minutes = 0    # 运行时长上限(分钟)
        self.stop_after_count = 0      # 本次运行丢球次数上限(点击计数)

        # 计数器（GUI 展示用）
        self.normal_count = 0
        self.bomber_count = 0
        self.skill_count = 0

        # 状态控制（普通模式）
        self.running = False
        self.thread = None

        # 状态控制（轰炸机模式）
        self.bomber_running = False
        self.bomber_thread = None

        # 状态控制（技能模式）
        self.skill_running = False
        self.skill_thread = None

        # 遭遇战斗检测（极速 BattleDetector 策略，绝不阻塞丢球）
        self.exit_on_battle = True     # 是否在遭遇战斗时自动退出丢球
        self.on_battle_detected = None # 遭遇战斗回调函数 cb(snap)
        self.current_state = "stopped" # stopped / throwing / fleeing / fled / paused
        self.state_detail = ""
        self.enemy_name = None
        self.enemy_hp = None
        self.battles_escaped = 0
        self._battle_detector = None   # 极速 BattleDetector 实例 (<1ms)
        self._fast_cap = None          # FastCapture 实例
        self._last_battle_check = 0.0  # 战斗检测节流时间戳
        self._frame_provider = None    # 外部注入的截图提供器 (如 AppBridge)

        # 状态提示防刷屏
        self._inactive_warned = False
        self._mouse_outside_warned = False

        # 本次运行基准(自动停止条件用)
        self._run_started_at = 0.0     # 模式启动时间戳
        self._run_start_count = 0      # 启动时的累计计数(用于算本次增量)
        self._bomber_run_start_count = 0  # 轰炸机启动时的累计计数

        # 咕噜球监视(战斗前 1 号位, 蓄力窗口异步采样, 由 bridge 注入)
        self.ball_watcher = None
        # 模式互斥钩子(bridge 注入): 快捷键启动丢球组前, 自动停止互斥的挂机引擎/PVP识别
        self.conflict_hook = None
        # 战斗监视(异步自动逃跑): 丢球循环只读 in_battle 标志, 检测在独立线程
        self.in_battle = False
        self._charging = False
        self._battle_watch_thread = None
        self._last_frame = None

    def _log(self, message, level="info"):
        """输出日志：print + 可选回调"""
        print(message)
        if self.on_log:
            try:
                self.on_log(message, level)
            except Exception:
                pass

    def get_game_hwnd(self) -> int:
        """获取游戏窗口句柄"""
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if TARGET_WINDOW_TITLE in buf.value:
                    return hwnd

        hwnd = user32.FindWindowW(TARGET_WINDOW_CLASS, None)
        if hwnd:
            return hwnd
        hwnd = user32.FindWindowW(None, TARGET_WINDOW_TITLE)
        if hwnd:
            return hwnd
        return 0

    def is_game_window_active(self) -> bool:
        """检查游戏窗口是否在最前面（纯查询，无副作用）"""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return False

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)

        return TARGET_WINDOW_TITLE in buffer.value

    def is_mouse_in_game_window(self) -> bool:
        """
        检查鼠标光标当前是否位于游戏窗口矩形边界内
        防止游戏在前台但鼠标误移出窗外（多屏/任务栏等）时发生外部误点击
        （只做纯物理边界判定，不因 3D 模式锁定光标或悬浮窗产生误判）
        """
        game_hwnd = self.get_game_hwnd()
        if not game_hwnd:
            return False

        pt = POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return True
        rect = RECT()
        if not user32.GetWindowRect(game_hwnd, ctypes.byref(rect)):
            return True
        return (rect.left <= pt.x < rect.right and rect.top <= pt.y < rect.bottom)

    def _check_active_or_warn(self) -> bool:
        """检查窗口前台状态及鼠标光标位置，非前台或光标移出时暂停并提示"""
        if not self.is_game_window_active():
            if not self._inactive_warned:
                self._inactive_warned = True
                self._log("游戏窗口不在最前面，暂停执行…", "warning")
            return False

        if self._inactive_warned:
            self._inactive_warned = False
            self._log("游戏窗口已回到前台，继续执行", "success")

        # 检查鼠标光标是否在游戏窗口物理矩形内
        if not self.is_mouse_in_game_window():
            if not self._mouse_outside_warned:
                self._mouse_outside_warned = True
                self._log("⚠️ 鼠标光标已移出游戏窗口范围，暂停丢球以防误触…", "warning")
            return False

        if self._mouse_outside_warned:
            self._mouse_outside_warned = False
            self._log("✅ 鼠标光标已回到游戏窗口内，恢复自动丢球", "success")

        return True

    def get_humanized_delay(self):
        """普通模式蓄力延迟（正态分布，截断在 normal_min ~ normal_max）"""
        return self.get_delay_zt(self.normal_min, self.normal_max)

    def get_delay_zt(self, l, r):
        """
        生成正态分布延迟

        均值: (l+r)/2
        标准差: 由 l/r 推导
        范围: l - r 秒
        """
        mean = (l + r) / 2
        std = (r ** 2 + l ** 2 - mean ** 2) ** 0.5
        delay = random.gauss(mean, std)
        delay = max(l, delay)
        delay = min(r, delay)
        return delay

    def mouse_down(self):
        """模拟鼠标按下"""
        interception.mouse_down(button='left')

    def mouse_up(self):
        """模拟鼠标松开"""
        interception.mouse_up(button='left')

    def throw_ball(self):
        """执行单次扔球动作"""
        self.mouse_down()
        self._charging = True
        if self.ball_watcher:
            self.ball_watcher.notify_charging()   # 通知球槽监视线程采样(异步,不阻塞蓄力)
        time.sleep(self.get_humanized_delay())
        self.mouse_up()
        self._charging = False

    def _run_conflict_hook(self):
        """启动丢球组任一模式前调用(bridge 注入): 自动停止互斥的挂机引擎/PVP识别"""
        if self.conflict_hook:
            try:
                self.conflict_hook()
            except Exception as e:
                self._log(f"互斥钩子执行失败: {e}", "warning")

    def attach_ball_watcher(self, watcher) -> bool:
        """注入咕噜球监视线程(bridge 初始化时调用)"""
        self.ball_watcher = watcher
        return watcher.attach(on_stop_request=self._stop_for_ball_watch)

    def _stop_for_ball_watch(self, reason: str):
        """球槽监视判定(空球/贵重球)触发的停止"""
        stopped = []
        if self.running:
            self.running = False
            stopped.append("普通丢球")
        if self.bomber_running:
            self.bomber_running = False
            stopped.append("轰炸机")
        if stopped:
            self.current_state = "stopped"
            self.state_detail = f"已自动停止({reason})"
            self._log(f"🏁 [咕噜球监视] {reason}: 已停止 {'+'.join(stopped)}", "warning")

    def _grab_game_frame(self):
        """抓取一帧游戏画面(检测/监视共用)"""
        if self._frame_provider:
            _, frame = self._frame_provider()
            return frame
        from src.capture.window_capture import find_window
        info = find_window(class_name="UnrealWindow") or find_window()
        if not info or info.width < 50 or info.height < 50:
            return None
        if self._fast_cap is None:
            from src.capture.fast_capture import FastCapture
            self._fast_cap = FastCapture()
        left, top, right, bottom = info.rect
        return self._fast_cap.capture(rect=(left, top, right - left, bottom - top))

    def _detect_battle_frame(self, frame) -> bool:
        """对一帧画面做战斗角标判定(模板匹配 <2ms)"""
        if frame is None or frame.size == 0 or float(frame[::8, ::8].std()) < 3.0:
            return False
        if self._battle_detector is None:
            from src.perception.battle_detector import BattleDetector
            from src.perception.vision_pipeline import load_roi_config
            rois = load_roi_config()
            self._battle_detector = BattleDetector(
                rois.get("battle_left_indicator"),
                rois.get("battle_right_indicator")
            )
        res = self._battle_detector.detect(frame)
        return bool(res.get("in_battle"))

    def _announce_battle(self, frame):
        """入战广播: 读一次敌方名字血量 + 日志 + 回调"""
        self.current_state = "fleeing"
        self.state_detail = "遭遇战斗！正在自动逃跑…"
        enemy_name = "遭遇精灵"
        enemy_hp = 100
        try:
            from src.perception.ocr_reader import OcrNameReader, OcrNumberReader
            from src.perception.vision_pipeline import load_roi_config
            rois = load_roi_config()
            name_reader = OcrNameReader(rois["enemy_name"])
            r_name = name_reader.read(frame)
            if r_name and r_name.value:
                enemy_name = r_name.value
            hp_reader = OcrNumberReader(rois["enemy_hp"], percent=True)
            r_hp = hp_reader.read(frame)
            if r_hp and r_hp.value is not None:
                enemy_hp = r_hp.value
        except Exception:
            pass
        self.enemy_name = enemy_name
        self.enemy_hp = enemy_hp
        hp_str = f"{enemy_hp}%" if enemy_hp is not None else "?"
        self._log(f"⚔️ [遭遇战斗] 检测到进入对战画面！(敌方: {enemy_name}, 血量: {hp_str})", "warning")
        if self.on_battle_detected:
            try:
                self.on_battle_detected({"enemy_name": enemy_name, "enemy_hp": enemy_hp})
            except Exception:
                pass

    def _battle_watch_loop(self):
        """独立战斗监视线程: 每 0.35s 采样判定, 丢球循环只读 in_battle 标志,
        键鼠时序与视觉检测完全解耦(检测卡顿不再拖慢丢球)"""
        while self.running or self.bomber_running or self.skill_running:
            if not self.exit_on_battle:
                time.sleep(0.5)
                continue
            frame = self._grab_game_frame()
            try:
                in_battle = self._detect_battle_frame(frame)
            except Exception:
                in_battle = False
            self._last_frame = frame

            if in_battle:
                self.in_battle = True
                try:
                    self._announce_battle(frame if frame is not None else self._grab_game_frame())
                except Exception:
                    pass
                # 等当前蓄力动作收尾(mouse_up 落地), 最多 1s, 避免逃跑按键和丢球按键混叠
                deadline = time.time() + 1.0
                while self._charging and time.time() < deadline:
                    time.sleep(0.02)
                try:
                    self.flee_battle()
                except Exception as e:
                    self._log(f"逃跑流程异常: {e}", "error")
                self.in_battle = False
                time.sleep(0.5)   # 逃跑后缓冲, 避免确认框残影误判
            else:
                self.in_battle = False
                time.sleep(0.35)

    def _ensure_battle_watcher(self):
        """任一模式运行时确保监视线程存活(空闲时线程自退出)"""
        t = getattr(self, "_battle_watch_thread", None)
        if not (t and t.is_alive()):
            self._battle_watch_thread = threading.Thread(
                target=self._battle_watch_loop, daemon=True, name="BattleWatch")
            self._battle_watch_thread.start()

    def check_battle_encounter(self) -> bool:
        """兼容保留: 同步检测一次(旧调用点已全部迁移到 in_battle 标志)"""
        if not self.exit_on_battle:
            return False
        now = time.time()
        if now - self._last_battle_check < 0.4:
            return False
        self._last_battle_check = now
        try:
            frame = self._grab_game_frame()
            if self._detect_battle_frame(frame):
                self._announce_battle(frame)
                self.flee_battle()
                return True
        except Exception:
            pass
        return False

    def flee_battle(self) -> bool:
        """
        遭遇战斗自动逃跑流程：
        1. 确保游戏窗口获得前台焦点
        2. 按单次 Esc 键呼出逃跑确认菜单（严防多次连续按 Esc 导致误关弹窗）
        3. 延时 0.35s 等待弹窗 UI 动画完全展开
        4. 精准读取 逃跑模板.json 中「逃跑_确定框」的中心坐标
        5. 多驱动通道（OS光标 + Interception + Win32消息）精准物理点击「是」
        6. 延时确认脱离战斗并回到大世界
        """
        import ctypes
        import win32gui, win32con
        import interception
        from src.driver import human_input
        from src.capture.window_capture import find_window
        from pathlib import Path

        self.current_state = "fleeing"
        self.state_detail = "按下 Esc 呼出逃跑菜单…"
        self._log("⚔️ [自动逃跑] 正在执行逃跑：按下 Esc 呼出逃跑菜单…", "info")

        # 1. 获取当前游戏窗口物理位置并置顶激活
        info = find_window(class_name="UnrealWindow") or find_window()
        if not info or info.width < 50 or info.height < 50:
            self._log("❌ [自动逃跑] 未找到游戏窗口", "error")
            return False

        game_hwnd = info.hwnd
        if game_hwnd:
            try:
                win32gui.SetForegroundWindow(game_hwnd)
                time.sleep(0.05)
            except Exception:
                pass

        left, top, right, bottom = info.rect
        w, h = right - left, bottom - top

        # 2. 按单次 Esc 键呼出逃跑确认弹窗
        human_input.press("esc")
        # 弹窗动画展开等待
        time.sleep(0.35)

        # 3. 确定框坐标 (默认基于 逃跑模板.json 的基准归一化坐标)
        # 逃跑_确定框 ("是"): rx: 0.5421, ry: 0.7758, rw: 0.0763, rh: 0.0378
        btn_rx, btn_ry, btn_rw, btn_rh = 0.5421, 0.7758, 0.0763, 0.0378

        # 尝试读取最新的逃跑模板配置
        tmpl_file = Path(__file__).resolve().parent / "data" / "config" / "roi_templates" / "逃跑模板.json"
        if tmpl_file.exists():
            try:
                import json
                tmpl_data = json.loads(tmpl_file.read_text(encoding="utf-8"))
                for roi in tmpl_data.get("rois", []):
                    if "确定" in roi.get("id", "") or "确定" in roi.get("label", "") or "是" in roi.get("label", ""):
                        btn_rx, btn_ry, btn_rw, btn_rh = roi["rx"], roi["ry"], roi["rw"], roi["rh"]
            except Exception:
                pass

        # 4. 计算并点击确定按钮「是」
        target_x = left + int((btn_rx + btn_rw / 2.0) * w)
        target_y = top + int((btn_ry + btn_rh / 2.0) * h)

        self._log(f"🖱️ [自动逃跑] 点击「是」退出按钮: 屏幕坐标 ({target_x}, {target_y})", "info")
        self.state_detail = "点击「是」确认退出战斗…"

        # 100% 纯 Interception 内核级驱动硬件模拟（杜绝使用易被反作弊检测的 Win32 PostMessage/mouse_event）
        try:
            interception.move_to(target_x, target_y)
            time.sleep(0.08)
            interception.mouse_down(button="left")
            time.sleep(0.09)
            interception.mouse_up(button="left")
        except Exception as e:
            self._log(f"⚠️ [自动逃跑] 驱动点击异常: {e}", "warning")

        # 5. 等待退出战斗过渡动画完成
        time.sleep(0.8)
        self.battles_escaped += 1
        self.current_state = "fled"
        self.state_detail = f"已成功脱离战斗 (累计逃跑 {self.battles_escaped} 次)"
        self.enemy_name = None
        self.enemy_hp = None
        self._log("🎉 [自动逃跑] 逃跑指令已执行完成，成功脱离战斗！", "success")
        return True

    def _hit_stop_limit(self, mode: str) -> bool:
        """
        检查定时/定量自动停止条件(仅普通丢球与轰炸机)。
        达到任一条件时停止对应模式、写日志并返回 True;0 表示不限制。
        计数为点击计数:球界面打开时每次点击≈丢出一颗球,未开界面的空点会计入。
        """
        if mode == "normal":
            active, count, start = self.running, self.normal_count, self._run_start_count
        else:
            active, count, start = self.bomber_running, self.bomber_count, self._bomber_run_start_count

        if not active:
            return False

        reason = None
        if self.stop_after_count > 0 and (count - start) >= self.stop_after_count:
            reason = f"达到设定丢球次数 {self.stop_after_count}"
        elif self.stop_after_minutes > 0 and (time.time() - self._run_started_at) >= self.stop_after_minutes * 60:
            reason = f"达到设定时限 {self.stop_after_minutes} 分钟"

        if reason:
            if mode == "normal":
                self.running = False
                label = "普通丢球"
            else:
                self.bomber_running = False
                label = "轰炸机"
            self.current_state = "stopped"
            self.state_detail = f"{label}已自动停止({reason})"
            self._log(f"🏁 [自动停止] {label}: {reason}, 本轮共 {count - start} 次", "success")
            return True
        return False

    def throw_loop(self):
        """持续扔球循环"""
        while self.running:
            if self._hit_stop_limit("normal"):
                break
            if self._check_active_or_warn():
                if self.in_battle:
                    self.running = False
                    self._log("[遭遇战斗] 已自动停止普通丢球模式", "warning")
                    break
                self.throw_ball()
                self.normal_count += 1
                self.current_state = "throwing"
                self.state_detail = f"普通丢球: 已丢 {self.normal_count} 球"
            time.sleep(0.1)

    def toggle(self):
        """切换普通模式运行状态"""
        if self.running:
            self.running = False
            self.current_state = "stopped"
            self.state_detail = "已停止"
            self._log("[停止] 自动扔球已关闭", "warning")
            return False
        else:
            self._run_conflict_hook()
            self._ensure_battle_watcher()
            self.running = True
            self._run_started_at = time.time()
            self._run_start_count = self.normal_count
            self.current_state = "throwing"
            self.state_detail = f"普通丢球: 已丢 {self.normal_count} 球"
            self._inactive_warned = False
            self._mouse_outside_warned = False
            if self.ball_watcher:
                self.ball_watcher.reset_run()
            self.thread = threading.Thread(target=self.throw_loop, daemon=True)
            self.thread.start()
            self._log("[开始] 自动扔球已启动", "success")
            return True

    def bomber_loop(self):
        """
        轰炸机丢球循环 - 悬浮+轰炸模式

        1. 空格双击起飞
        2. 每 hover_min~hover_max 秒按一次空格保持高度
        3. 持续蓄力丢球（charge_min~charge_max 秒）
        """
        from src.driver import human_input
        self._log("[轰炸机] 双击空格起飞！", "info")
        human_input.press('space')
        time.sleep(0.05)
        human_input.press('space')
        time.sleep(0.3)

        last_hover_time = time.time()

        while self.bomber_running:
            if self._hit_stop_limit("bomber"):
                break
            if not self._check_active_or_warn():
                time.sleep(0.1)
                continue

            if self.in_battle:
                self.bomber_running = False
                self._log("[遭遇战斗] 已自动停止轰炸机丢球模式", "warning")
                break

            current_time = time.time()

            # 按悬浮间隔按空格保持高度
            hover_interval = self.get_delay_zt(self.bomber_hover_min, self.bomber_hover_max)
            if current_time - last_hover_time >= hover_interval:
                human_input.press('space')
                last_hover_time = current_time

            time.sleep(0.05)

            # 快速蓄力丢球
            interception.mouse_down(button='left')
            self._charging = True
            if self.ball_watcher:
                self.ball_watcher.notify_charging()   # 通知球槽监视线程采样(异步)
            time.sleep(self.get_delay_zt(self.bomber_charge_min, self.bomber_charge_max))
            interception.mouse_up(button='left')
            self._charging = False
            self.bomber_count += 1
            self.current_state = "throwing"
            self.state_detail = f"轰炸机: 已丢 {self.bomber_count} 球"

    def toggle_bomber(self):
        """切换轰炸机模式运行状态"""
        if self.bomber_running:
            self.bomber_running = False
            self.current_state = "stopped"
            self.state_detail = "已停止"
            self._log("[停止] 轰炸机丢球已关闭", "warning")
            return False
        else:
            self._run_conflict_hook()
            self._ensure_battle_watcher()
            self.bomber_running = True
            self._run_started_at = time.time()
            self._bomber_run_start_count = self.bomber_count
            self.current_state = "throwing"
            self.state_detail = f"轰炸机: 已丢 {self.bomber_count} 球"
            self._inactive_warned = False
            self._mouse_outside_warned = False
            if self.ball_watcher:
                self.ball_watcher.reset_run()
            self.bomber_thread = threading.Thread(target=self.bomber_loop, daemon=True)
            self.bomber_thread.start()
            self._log("[开始] 轰炸机丢球已启动", "success")
            return True

    def skill_loop(self):
        """
        技能循环 - 自动按技能

        交替按数字 3 / 字母 X，间隔 skill_min ~ skill_max 秒
        """
        self._log("[技能] 自动技能已启动（交替按 3 和 X）", "info")
        from src.driver import human_input

        while self.skill_running:
            if not self._check_active_or_warn():
                time.sleep(0.1)
                continue

            if self.in_battle:
                self.skill_running = False
                self._log("[遭遇战斗] 已自动停止自动技能模式", "warning")
                break

            human_input.press('3')
            self.skill_count += 1
            self.current_state = "throwing"
            self.state_detail = f"自动技能: 已按 {self.skill_count} 次"
            time.sleep(self.get_delay_zt(self.skill_min, self.skill_max))

            if not self.skill_running:
                break

            if self.in_battle:
                self.skill_running = False
                self._log("[遭遇战斗] 已自动停止自动技能模式", "warning")
                break

            human_input.press('x')
            self.skill_count += 1
            self.current_state = "throwing"
            self.state_detail = f"自动技能: 已按 {self.skill_count} 次"
            time.sleep(self.get_delay_zt(self.skill_min, self.skill_max))

    def toggle_skill(self):
        """切换技能模式运行状态"""
        if self.skill_running:
            self.skill_running = False
            self.current_state = "stopped"
            self.state_detail = "已停止"
            self._log("[停止] 自动技能已关闭", "warning")
            return False
        else:
            self._run_conflict_hook()
            self._ensure_battle_watcher()
            self.skill_running = True
            self.current_state = "throwing"
            self.state_detail = f"自动技能: 已按 {self.skill_count} 次"
            self._inactive_warned = False
            self._mouse_outside_warned = False
            self.skill_thread = threading.Thread(target=self.skill_loop, daemon=True)
            self.skill_thread.start()
            self._log("[开始] 自动技能已启动", "success")
            return True

    def stop_all(self):
        """停止全部模式"""
        was_running = self.running or self.bomber_running or self.skill_running
        self.running = False
        self.bomber_running = False
        self.skill_running = False
        self.current_state = "stopped"
        self.state_detail = "已停止"
        if was_running:
            self._log("已停止全部模式", "warning")

    def register_hotkeys(self):
        """注册模式切换快捷键(不阻塞)"""
        keyboard.add_hotkey('f4', self.toggle)
        keyboard.add_hotkey('f9', self.toggle_bomber)
        keyboard.add_hotkey('f10', self.toggle_skill)
        self._log("快捷键已注册: F4 普通丢球 / F9 轰炸机 / F10 技能", "info")

    def start(self):
        """命令行模式：注册快捷键并等待 ESC 退出"""
        print("=" * 50)
        print("洛克王国 - 自动丢球工具")
        print("=" * 50)
        print("按 F4 开始/停止普通扔球")
        print("按 F9 开始/停止轰炸机扔球（悬浮+轰炸）")
        print("按 F10 开始/停止自动技能（交替按3和X）")
        print("按 ESC 退出")
        print("=" * 50)

        self.register_hotkeys()
        keyboard.wait('esc')
        self.stop_all()
        print("已退出")


if __name__ == "__main__":
    tool = AutoThrowBall()
    tool.start()
