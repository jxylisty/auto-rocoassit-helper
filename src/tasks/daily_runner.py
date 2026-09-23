# -*- coding: utf-8 -*-
"""
日常任务执行器 (MAA 式任务清单)

设计:
- 任务 = 有序步骤列表; 步骤 = {name, action, target, extra}
  action:
    - template_click : 模板匹配等待出现 → 拟人点击 (target=模板名, extra={timeout, region})
    - key            : 按键 (target=键名) — 执行前自动把游戏窗口置前, 防止按键打到别的窗口
    - click_ratio    : 按屏幕比例坐标点击 (target=[rx, ry])
    - wait_template  : 等模板出现(不点击), 用于确认页面到位
    - wait_seconds   : 等待 N 秒 (extra={seconds})
    - ocr_assert     : OCR 全屏文字须包含关键词 (target=关键词), 失败可重试
    - ocr_click_text : OCR 找到关键词位置 → 拟人点击其中心 (target=关键词)
    - flower_challenge: 花种挑战全自动(日常获得), 配置见 data/config/flower_challenge.json
    - game_launch      : 无 UAC 打开 WeGame → OCR 模拟点击「启动」→ 等游戏窗口出现
- 步骤失败默认中止任务(可 extra.on_fail="skip" 跳过)
- 全程使用 human_input 拟人节奏 + MouseController 点击
- 可被 stop_event 打断; 与引擎互斥由 bridge 层保证
"""
import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "data" / "config"
TASKS_FILE = CONFIG_DIR / "daily_tasks.json"
TEMPLATE_DIR = PROJECT_ROOT / "data" / "config" / "roi_templates"


class DailyRunner:
    def __init__(self, frame_provider: Callable, log_cb: Optional[Callable] = None,
                 launch_cb: Optional[Callable] = None):
        self._frame_provider = frame_provider
        self._log_cb = log_cb or (lambda msg, level="info": None)
        self._launch_cb = launch_cb  # 启动游戏回调(bridge.game_launch, 计划任务+模拟点击)
        self._stop_event = threading.Event()
        self._thread = None
        self.running = False
        self._queue_running = False  # 流水线执行中(防单任务插队)
        self.state = {"running": False, "task": "", "step": "", "step_index": 0,
                      "total_steps": 0, "ok": 0, "fail": 0, "detail": ""}

    # ---------- 公共接口 ----------
    def list_tasks(self) -> dict:
        return {"success": True, "tasks": self._load_tasks()}

    def save_tasks(self, tasks: list) -> dict:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"success": True}

    def start_task(self, task_id: str) -> dict:
        if self.running or self._queue_running:
            return {"success": False, "message": "已有日常任务在运行"}
        tasks = self._load_tasks()
        task = next((t for t in tasks if t.get("id") == task_id), None)
        if not task:
            return {"success": False, "message": "任务不存在: " + str(task_id)}
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_task, args=(task,), daemon=True, name="daily-runner")
        self._thread.start()
        return {"success": True}

    def start_queue(self, task_ids) -> dict:
        """MAA 式流水线: 按传入顺序串行执行多个任务(一键执行勾选项)"""
        ids = [str(i) for i in (task_ids or []) if str(i).strip()]
        if not ids:
            return {"success": False, "message": "队列为空"}
        if self.running or self._queue_running:
            return {"success": False, "message": "已有日常任务在运行"}
        tasks = self._load_tasks()
        queue = []
        for tid in ids:
            t = next((x for x in tasks if x.get("id") == tid), None)
            if t:
                queue.append(t)
        if not queue:
            return {"success": False, "message": "勾选的任务均不存在"}
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_queue, args=(queue,),
                                        daemon=True, name="daily-queue")
        self._thread.start()
        return {"success": True, "total": len(queue)}

    def _run_queue(self, queue: list):
        """串行执行任务队列; 单个任务失败只中止该任务, 继续下一个; 手动停止全停。
        任务与任务之间: 延迟 + 等待回到初始界面(衔接校验), 防止上一任务的
        弹窗/子页面残留导致下一任务第一步就点错。"""
        self._queue_running = True
        total = len(queue)
        try:
            for idx, task in enumerate(queue, 1):
                if self._stop_event.is_set():
                    break
                self._log(f"[日常] 流水线 {idx}/{total}: {task.get('name')}", "info")
                self._run_task(task, queue_index=idx, queue_total=total)
                if idx < total and not self._stop_event.is_set():
                    # 任务间延迟(默认 2.5s, 可被 stop 打断) + 初始界面校验在
                    # _run_task 开头做(那里能拿到下一任务上下文)
                    if self._stop_event.wait(2.5):
                        break
        finally:
            self._queue_running = False
            self.state["running"] = False
            self.state["detail"] = self.state.get("detail") or "流水线结束"

    def stop(self):
        self._stop_event.set()

    def get_status(self) -> dict:
        return {"success": True, **self.state}

    # ---------- 内部 ----------
    def _load_tasks(self):
        try:
            return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _log(self, msg, level="info"):
        self._log_cb(msg, level)

    # ---------- 初始界面衔接校验 ----------
    INITIAL_SCREEN_JSON = "判断是否处于初始界面.json"
    INITIAL_SCREEN_REF = "判断是否处于初始界面.png"   # ROI 区域参考图(自动采集)

    def _initial_screen_roi(self) -> Optional[tuple]:
        """读初始界面模板 JSON 里「识别标志」ROI → (rx, ry, rw, rh)"""
        try:
            data = json.loads((TEMPLATE_DIR / self.INITIAL_SCREEN_JSON).read_text(encoding="utf-8"))
            for r in data.get("rois", []):
                rid = str(r.get("id", "")) + str(r.get("label", ""))
                if "识别" in rid or "标志" in rid or "初始" in rid:
                    return (r["rx"], r["ry"], r["rw"], r["rh"])
            rois = data.get("rois", [])
            if rois:
                r = rois[0]
                return (r["rx"], r["ry"], r["rw"], r["rh"])
        except Exception:
            pass
        return None

    def _initial_screen_match(self, frame, ref_img) -> float:
        """ROI 区域图案与参考图相似度 (0~1)。ref_img 为 ROI 区域的裁剪参考图。"""
        import cv2
        roi = self._initial_screen_roi()
        if not roi:
            return 0.0
        rx, ry, rw, rh = roi
        h, w = frame.shape[:2]
        crop = frame[int(ry * h):int((ry + rh) * h), int(rx * w):int((rx + rw) * w)]
        if crop.size == 0 or ref_img.size == 0:
            return 0.0
        # 参考图缩放到当前裁剪尺寸(窗口大小可能变过), 灰度归一后模板匹配
        ref = cv2.resize(ref_img, (crop.shape[1], crop.shape[0]),
                         interpolation=cv2.INTER_AREA)
        g1 = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
        try:
            res = cv2.matchTemplate(g1, g2, cv2.TM_CCOEFF_NORMED)
            return float(res.max()) if res.size else 0.0
        except Exception:
            return 0.0

    def _wait_initial_screen(self, timeout: float = 25.0) -> bool:
        """等待游戏回到初始(主)界面 — 任务与任务之间的衔接校验(用户要求)。
        用「判断是否处于初始界面」模板 JSON 的「识别标志」ROI:
        - 参考图不存在 → 自动采集当前 ROI 区域存为 PNG(首次自学习);
        - 参考图存在 → 每次比对该位置图案是否与参考一致(一致=回到初始界面)。
        未配置 ROI 时退化为画面静止判据。返回是否确认到达初始界面。"""
        import cv2
        import numpy as np
        ref_path = TEMPLATE_DIR / self.INITIAL_SCREEN_REF
        ref_img = cv2.imread(str(ref_path), cv2.IMREAD_COLOR) if ref_path.exists() else None
        has_roi = self._initial_screen_roi() is not None

        deadline = time.time() + timeout
        self._ensure_game_front()
        if self._stop_event.wait(1.0):
            return False
        while time.time() < deadline:
            if self._stop_event.is_set():
                return False
            try:
                _, frame = self._frame_provider()
                if frame is not None and frame.size:
                    if ref_img is None and has_roi:
                        # 首次运行: 当前画面采集参考图(用户点一键执行时游戏应在初始界面)
                        roi = self._initial_screen_roi()
                        rx, ry, rw, rh = roi
                        h, w = frame.shape[:2]
                        crop = frame[int(ry * h):int((ry + rh) * h),
                                     int(rx * w):int((rx + rw) * w)]
                        if crop.size:
                            try:
                                from src.utils.image_io import imwrite_unicode
                                if imwrite_unicode(ref_path, crop):
                                    ref_img = crop
                                    self._log("[日常] 已自动采集初始界面参考图: "
                                              + self.INITIAL_SCREEN_REF, "success")
                            except Exception:
                                pass
                    if ref_img is not None and has_roi:
                        score = self._initial_screen_match(frame, ref_img)
                        if score >= self._threshold():
                            self._log(f"[日常] 已回到初始界面 (图案匹配 {score:.2f})", "success")
                            return True
                    elif not has_roi:
                        # 无 ROI: 画面静止判据(相隔 1.2s 两帧几乎一致 → 界面稳定)
                        if self._stop_event.wait(1.2):
                            return False
                        _, f2 = self._frame_provider()
                        if f2 is not None and f2.size and f2.shape == frame.shape:
                            diff = cv2.absdiff(
                                cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                                cv2.cvtColor(f2, cv2.COLOR_BGR2GRAY))
                            still = float(np.mean(diff < 12))
                            if still >= 0.92:
                                self._log(f"[日常] 画面已稳定, 视为初始界面 ({still:.2f})", "success")
                                return True
            except Exception:
                pass
            self._stop_event.wait(1.0)
        self._log("[日常] 等待初始界面超时(继续下一任务, 可能落在非主界面)", "warning")
        return False

    def _run_task(self, task: dict, queue_index: int = 0, queue_total: int = 0):
        self.running = True
        steps = task.get("steps", [])
        repeats = max(1, int(task.get("repeat", 1) or 1))
        round_gap = float(task.get("round_gap", 1.2) or 1.2)
        total = len(steps) * repeats
        self.state = {"running": True, "task": task.get("name", task_id_name(task)),
                      "step": "", "step_index": 0, "total_steps": total, "ok": 0, "fail": 0, "detail": "",
                      "queue_index": queue_index, "queue_total": queue_total}
        self._log(f"[日常] 开始任务: {task.get('name')} ({len(steps)} 步 x {repeats} 轮)", "success")
        # 开跑前强制把游戏拉到前台+焦点(用户要求: 一键执行后游戏必须在前台,
        # 否则后续 key/click_ratio 步骤全打到别的窗口)
        self._ensure_game_front()
        if self._stop_event.wait(0.6):
            return
        # 任务衔接校验: 上一任务结束后界面可能停在任意弹窗/子页面,
        # 先等回到初始界面再执行本任务
        if queue_index > 0 or getattr(self, "_ran_once", False):
            self._wait_initial_screen()
        self._ran_once = True
        done = 0
        try:
            for rnd in range(repeats):
                if repeats > 1:
                    self._log(f"[日常] 第 {rnd + 1}/{repeats} 轮", "info")
                for i, step in enumerate(steps):
                    if self._stop_event.is_set():
                        self._log("[日常] 已手动停止", "warning")
                        return
                    name = step.get("name") or step.get("action", "?")
                    self.state["step"] = name
                    self.state["step_index"] = done + 1
                    try:
                        self._do_step(step)
                        self.state["ok"] += 1
                        self._log(f"[日常] {done + 1}/{total} {name} 完成", "info")
                    except StepSkipped:
                        self.state["ok"] += 1
                        self._log(f"[日常] {done + 1}/{total} {name} 跳过(未命中,允许)", "warning")
                    except Exception as e:
                        self.state["fail"] += 1
                        self._log(f"[日常] {done + 1}/{total} {name} 失败: {e}", "error")
                        if str(e) == "__STOP__":
                            return
                        if step.get("extra", {}).get("on_fail") != "skip":
                            self._log("[日常] 步骤失败, 任务中止", "error")
                            self.state["detail"] = f"任务失败: {name} ({e})"
                            return
                    done += 1
                    self._pause()
                if rnd < repeats - 1:
                    if self._stop_event.wait(round_gap):
                        return
        finally:
            self.running = False
            self.state["running"] = False
            self.state["detail"] = f"完成 {self.state['ok']}/{total}"
            self._log(f"[日常] 任务结束: {task.get('name')} (成功 {self.state['ok']} / 失败 {self.state['fail']})",
                      "success" if self.state["fail"] == 0 else "warning")

    def _pause(self):
        import random
        t = 0.5 + random.random() * 0.7
        if self._stop_event.wait(t):
            raise RuntimeError("__STOP__")

    # ---------- 步骤实现 ----------
    def _ensure_game_front(self):
        """游戏窗口置前+焦点(点击/按键动作的前置条件)。
        AttachThreadInput 借前台线程输入状态再切, 后台线程直接 SetForegroundWindow
        常被 Windows 前台锁拒绝。失败仅记日志不阻塞(下一步截图/点击会再触发)。"""
        try:
            import win32gui
            import win32process
            from src.capture.window_capture import WindowCapture, find_window
            info = find_window(class_name="UnrealWindow") or find_window()
            if info is None:
                self._log("[日常] 未找到游戏窗口, 跳过置前", "warning")
                return
            if win32gui.GetForegroundWindow() == info.hwnd:
                return
            WindowCapture(info.hwnd).bring_to_front()
            self._stop_event.wait(0.4)
            if win32gui.GetForegroundWindow() != info.hwnd:
                cur_tid, _ = win32process.GetWindowThreadProcessId(
                    win32gui.GetForegroundWindow())
                dst_tid, _ = win32process.GetWindowThreadProcessId(info.hwnd)
                attached = False
                try:
                    attached = win32process.AttachThreadInput(cur_tid, dst_tid, True)
                    win32gui.SetForegroundWindow(info.hwnd)
                    win32gui.BringWindowToTop(info.hwnd)
                finally:
                    if attached:
                        try:
                            win32process.AttachThreadInput(cur_tid, dst_tid, False)
                        except Exception:
                            pass
                self._stop_event.wait(0.3)
            if win32gui.GetForegroundWindow() == info.hwnd:
                self._log("[日常] 游戏窗口已置前", "info")
            else:
                self._log("[日常] 游戏窗口置前失败, 按键/点击可能无效", "warning")
        except Exception as e:
            self._log(f"[日常] 置前异常: {e}", "warning")

    def _frame(self):
        # roi_click/click_ratio/key 等动作依赖屏幕坐标与焦点 → 截图前统一置前
        self._ensure_game_front()
        info, frame = self._frame_provider()
        if frame is None or frame.size == 0:
            raise RuntimeError("截图失败(游戏未前台?)")
        return info, frame

    def _do_step(self, step: dict):
        action = step.get("action")
        target = step.get("target")
        extra = step.get("extra", {}) or {}
        timeout = float(extra.get("timeout", 10))
        interval = float(extra.get("interval", 0.8))

        if action == "wait_seconds":
            if self._stop_event.wait(float(extra.get("seconds", 2))):
                raise RuntimeError("__STOP__")
            return

        deadline = time.time() + timeout
        if action in ("template_click", "wait_template"):
            while True:
                if self._stop_event.is_set():
                    raise RuntimeError("__STOP__")
                info, frame = self._frame()
                hit = self._find_template(frame, target)
                if hit:
                    if action == "wait_template":
                        return
                    _, (mx, my), (th, tw) = hit
                    fh, fw = frame.shape[:2]
                    self._click_ratio(info, (mx + tw / 2) / fw, (my + th / 2) / fh)
                    return
                if time.time() > deadline:
                    if extra.get("on_fail") == "skip":
                        raise StepSkipped()
                    raise RuntimeError(f"模板未出现: {target}")
                self._stop_event.wait(interval)

        if action == "click_ratio":
            info, _ = self._frame()
            self._click_ratio(info, *(target or [0.5, 0.5]))
            return

        if action == "key":
            # key 依赖游戏键盘焦点: 控制台在前台时按 h/e 会打到控制台或别的窗口
            # (用户实机反馈"按某个键直接就没用了"), 故每次按键前强制置前一次
            self._ensure_game_front()
            from src.driver import human_input
            human_input.press(str(target))
            return

        if action == "roi_click":
            # 点击用户在工坊标注的 ROI 中心(模板 json 的 rois, 归一化坐标)
            # target=ROI id 或 [模板名, ROI id]; extra.retry 等待出现重试次数
            _roi_click_center(self, target, extra)
            return

        if action == "roi_ocr_pick":
            # 孵蛋选球: OCR 球名条带, 按期望类型(普通/高级)点第一个命中的球格
            # target=期望球名列表(任一命中即可), extra.template=模板文件名
            _roi_ocr_pick(self, target, extra)
            return

        if action in ("ocr_assert", "ocr_click_text"):
            from src.utils.ocr_engine import read_texts, read_combined
            while True:
                if self._stop_event.is_set():
                    raise RuntimeError("__STOP__")
                info, frame = self._frame()
                if action == "ocr_assert":
                    text, _ = read_combined(frame)
                    if text and str(target) in str(text):
                        return
                else:
                    # ocr_click_text: 按文字实际位置点击, 不再盲点屏幕中心(0.5,0.5)
                    import numpy as np
                    items = read_texts(frame)
                    hit = next((it for it in items if str(target) in str(it["text"])), None)
                    if hit and hit.get("box"):
                        # 取文字框中心坐标(帧坐标), 换算到窗口绝对屏幕坐标
                        box = hit["box"]
                        cx = int(np.mean([p[0] for p in box]))
                        cy = int(np.mean([p[1] for p in box]))
                        sx = info.rect[0] + cx
                        sy = info.rect[1] + cy
                        from src.driver.mouse_controller import MouseController
                        mouse = MouseController()
                        mouse.move_to(sx, sy)
                        import time as _t
                        _t.sleep(0.15)
                        mouse.click('left', 0.06 + 0.05 * (_t.time() % 1))
                        return
                if time.time() > deadline:
                    if extra.get("on_fail") == "skip":
                        raise StepSkipped()
                    raise RuntimeError(f"OCR 未命中: {target}")
                self._stop_event.wait(interval)

        if action == "game_launch":
            if not self._launch_cb:
                raise RuntimeError("启动回调未注入(bridge 未接 game_launch)")
            result = self._launch_cb()
            # 兼容两种回调返回: bool(成功与否) 或 dict({success, message, ...})
            ok = result if isinstance(result, bool) else bool((result or {}).get("success", True))
            msg = "" if isinstance(result, bool) else str((result or {}).get("message", ""))
            if not ok:
                raise RuntimeError(msg or "WeGame 拉起失败")
            # 等游戏窗口/进程出现(最长 300s), 出现即任务完成
            from src.capture.window_capture import find_window
            wait_cfg = 300 if isinstance(result, bool) else float((result or {}).get("wait_window") or 300)
            deadline = time.time() + wait_cfg
            while time.time() < deadline:
                if self._stop_event.is_set():
                    raise RuntimeError("__STOP__")
                try:
                    if find_window(class_name="UnrealWindow"):
                        self._log("游戏窗口已出现, 启动完成", "success")
                        return
                    r2 = subprocess.run(["tasklist"], capture_output=True,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if "洛克王国" in r2.stdout.decode("gbk", errors="replace"):
                        self._log("游戏进程已出现(加载中)", "success")
                        return
                except Exception:
                    pass
                self._stop_event.wait(2)
            raise RuntimeError("等待游戏窗口超时(WeGame 内自动点击可能未命中, 请手动启动)")

        if action == "flower_challenge":
            from src.tasks.flower_challenge import FlowerChallenge
            fc = FlowerChallenge(self._frame_provider, self._log_cb, self._stop_event)
            result = fc.run()
            if result.get("stopped"):
                raise RuntimeError("__STOP__")  # 手动停止: 走运行器的正常停止路径, 不计失败
            if not result.get("success"):
                raise RuntimeError(result.get("message", "花种挑战失败"))
            return

        raise RuntimeError("未知动作: " + str(action))

    def _normalize_templates(self, target):
        """target 可为单个模板名或模板名列表(3D 场景多角度模板, 任一命中即可)"""
        names = [str(t) for t in target] if isinstance(target, (list, tuple)) else [str(target)]
        paths = []
        for n in names:
            p = self._resolve_template(n)
            if p:
                paths.append(p)
        return paths

    def _find_template(self, frame, target):
        """多模板匹配: 返回 (score, (x,y), (th,tw)) 或 None"""
        import cv2
        best = None
        for p in self._normalize_templates(target):
            tmpl = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if tmpl is None:
                continue
            if frame.shape[0] < tmpl.shape[0] or frame.shape[1] < tmpl.shape[1]:
                continue
            res = cv2.matchTemplate(frame, tmpl, cv2.TM_CCOEFF_NORMED)
            _, maxv, _, maxloc = cv2.minMaxLoc(res)
            if maxv >= self._threshold() and (best is None or maxv > best[0]):
                best = (maxv, maxloc, tmpl.shape[:2])
        return best

    def _resolve_template(self, name: str):
        from pathlib import Path as _P
        candidates = list(TEMPLATE_DIR.glob(name)) if any(ch in name for ch in "*?") else [TEMPLATE_DIR / name]
        for c in candidates:
            if c.exists():
                return c
        # 兼容模板库目录
        alt = _P(r"D:\洛克王国ai\lkwgai_pvp_assistant\data\templates")
        for c2 in (alt.glob(name) if any(ch in name for ch in "*?") else [alt / name]):
            if c2.exists():
                return c2
        return None

    def _threshold(self) -> float:
        try:
            from src.utils.config import cfg_get
            return float(cfg_get("daily.match_threshold", 0.82))
        except Exception:
            return 0.82

    def _click_ratio(self, info, rx: float, ry: float):
        """按屏幕比例坐标拟人点击(基于窗口信息换算)"""
        import time as _t
        from src.driver.mouse_controller import MouseController
        x = info.rect[0] + int(info.width * float(rx))
        y = info.rect[1] + int(info.height * float(ry))
        mouse = MouseController()
        mouse.move_to(x, y)
        _t.sleep(0.15)
        mouse.click('left', 0.06 + 0.05 * (_t.time() % 1))


class StepSkipped(Exception):
    pass


# ============================================
# ROI 标注动作 (模板 json 的 rois, 归一化坐标)
# ============================================

def _load_roi_from_templates(roi_id: str, template_name: str = None):
    """从 roi_templates 的 json 里找 ROI(id 或 label 匹配), 返回 (rx, ry, rw, rh)。
    template_name 指定文件名(不含 .json); 不指定则全目录搜索第一个命中的。"""
    import json
    from pathlib import Path
    tdir = PROJECT_ROOT / "data" / "config" / "roi_templates"
    files = [tdir / f"{template_name}.json"] if template_name else sorted(tdir.glob("*.json"))
    for f in files:
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for r in data.get("rois", []):
            rid = str(r.get("id", ""))
            label = str(r.get("label", ""))
            if rid == roi_id or label == roi_id:
                return (float(r.get("rx", 0)), float(r.get("ry", 0)),
                        float(r.get("rw", 0)), float(r.get("rh", 0)))
    return None


def _roi_click_center(runner, target, extra: dict):
    """roi_click 动作: 点击标注 ROI 的中心 (Interception 硬件级)。
    target: "ROI名" 或 ["模板文件名", "ROI名"]; extra.retry=未出现等待重试次数"""
    import time as _t
    from src.driver.mouse_controller import MouseController
    template = None
    roi_id = str(target)
    if isinstance(target, (list, tuple)) and len(target) >= 2:
        template, roi_id = str(target[0]), str(target[1])
    retries = int(extra.get("retry", 0))
    gap = float(extra.get("retry_gap", 1.0))
    for attempt in range(max(1, retries + 1)):
        roi = _load_roi_from_templates(roi_id, template)
        if roi is None:
            raise RuntimeError(f"缺少 ROI「{roi_id}」(模板 {template or '任意'}), 请在工坊标注后保存")
        info, _ = runner._frame()
        rx, ry, rw, rh = roi
        x = info.rect[0] + int(info.width * (rx + rw / 2))
        y = info.rect[1] + int(info.height * (ry + rh / 2))
        mouse = MouseController()
        mouse.move_to(x, y)
        _t.sleep(0.15)
        mouse.click('left', 0.06 + 0.05 * (_t.time() % 1))
        if attempt < retries:
            runner._stop_event.wait(gap)


def _roi_ocr_pick(runner, target, extra: dict):
    """roi_ocr_pick 动作(咕噜球契约孵蛋选球):
    模板里 ROI id 以「球N」命名的格子 = 候选球名条带(整格 OCR, 不再切下部 30% —
    标注的球格子本身就只有 30~42px 高, 切完只剩字迹残段导致 OCR 必败);
    点第一个名字命中期望列表的球。target=期望球名列表或单个球名。
    extra.poll_secs: 面板可能还在展开, 最多轮询这么久(默认 6s, 0 帧差轮询)。
    全 miss 时把每格 OCR 原文打进日志, 便于对标注。"""
    import time as _t
    import json as _json
    from src.driver.mouse_controller import MouseController
    from src.utils.ocr_engine import read_combined

    template = str(extra.get("template") or "咕噜球契约孵蛋")
    wants = [str(w) for w in target] if isinstance(target, (list, tuple)) else [str(target)]
    tfile = PROJECT_ROOT / "data" / "config" / "roi_templates" / f"{template}.json"
    if not tfile.exists():
        raise RuntimeError(f"缺少模板 {template}.json")
    data = _json.loads(tfile.read_text(encoding="utf-8"))
    balls = sorted([r for r in data.get("rois", [])
                    if str(r.get("id", "")).startswith("球")],
                   key=lambda r: (float(r.get("ry", 0)), float(r.get("rx", 0))))
    if not balls:
        raise RuntimeError(f"模板 {template} 里没有「球N」格子 ROI")

    poll_deadline = _t.time() + float(extra.get("poll_secs", 6))
    picked = None
    last_texts = []
    info = None
    while picked is None:
        info, frame = runner._frame()
        fh, fw = frame.shape[:2]
        last_texts = []
        for r in balls:
            rx, ry, rw, rh = (float(r.get("rx", 0)), float(r.get("ry", 0)),
                              float(r.get("rw", 0)), float(r.get("rh", 0)))
            # 全格 OCR: 球N ROI 即球名条带本身, 不再裁剪
            x0, x1 = int(rx * fw), int((rx + rw) * fw)
            y0, y1 = int(ry * fh), int((ry + rh) * fh)
            crop = frame[max(0, y0):min(fh, y1), max(0, x0):min(fw, x1)]
            if crop.size == 0:
                last_texts.append((r.get("id"), "(空)"))
                continue
            text, _ = read_combined(crop)
            name = str(text or "").strip()
            last_texts.append((r.get("id"), name or "(未读出)"))
            if name and any(w in name for w in wants):
                picked = r
                runner._log(f"OCR 命中期望球: '{name}' ({r.get('id')})", "info")
                break
        if picked is not None or _t.time() >= poll_deadline:
            break
        if runner._stop_event.wait(0.8):
            raise RuntimeError("__STOP__")

    if picked is None:
        detail = ", ".join(f"{rid}='{t}'" for rid, t in last_texts)
        raise RuntimeError(f"OCR 未找到期望球 {wants} (逐格原文: {detail})")
    x = info.rect[0] + int(info.width * (float(picked["rx"]) + float(picked["rw"]) / 2))
    y = info.rect[1] + int(info.height * (float(picked["ry"]) + float(picked["rh"]) / 2))
    mouse = MouseController()
    mouse.move_to(x, y)
    _t.sleep(0.15)
    mouse.click('left', 0.06 + 0.05 * (_t.time() % 1))


def task_id_name(task: dict):
    return task.get("id", "task")
