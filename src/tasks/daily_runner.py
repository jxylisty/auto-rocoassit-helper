# -*- coding: utf-8 -*-
"""
日常任务执行器 (MAA 式任务清单)

设计:
- 任务 = 有序步骤列表; 步骤 = {name, action, target, extra}
  action:
    - template_click : 模板匹配等待出现 → 拟人点击 (target=模板名, extra={timeout, region})
    - key            : 按键 (target=键名)
    - click_ratio    : 按屏幕比例坐标点击 (target=[rx, ry])
    - wait_template  : 等模板出现(不点击), 用于确认页面到位
    - wait_seconds   : 等待 N 秒 (extra={seconds})
    - ocr_assert     : OCR 全屏文字须包含关键词 (target=关键词), 失败可重试
    - ocr_click_text : OCR 找到关键词位置 → 拟人点击其中心 (target=关键词)
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
    def __init__(self, frame_provider: Callable, log_cb: Optional[Callable] = None):
        self._frame_provider = frame_provider
        self._log_cb = log_cb or (lambda msg, level="info": None)
        self._stop_event = threading.Event()
        self._thread = None
        self.running = False
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
        if self.running:
            return {"success": False, "message": "已有日常任务在运行"}
        tasks = self._load_tasks()
        task = next((t for t in tasks if t.get("id") == task_id), None)
        if not task:
            return {"success": False, "message": "任务不存在: " + str(task_id)}
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_task, args=(task,), daemon=True, name="daily-runner")
        self._thread.start()
        return {"success": True}

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

    def _run_task(self, task: dict):
        self.running = True
        steps = task.get("steps", [])
        repeats = max(1, int(task.get("repeat", 1) or 1))
        round_gap = float(task.get("round_gap", 1.2) or 1.2)
        total = len(steps) * repeats
        self.state = {"running": True, "task": task.get("name", task_id_name(task)),
                      "step": "", "step_index": 0, "total_steps": total, "ok": 0, "fail": 0, "detail": ""}
        self._log(f"[日常] 开始任务: {task.get('name')} ({len(steps)} 步 x {repeats} 轮)", "success")
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
    def _frame(self):
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
            from src.driver import human_input
            human_input.press(str(target))
            return

        if action in ("ocr_assert", "ocr_click_text"):
            from src.utils.ocr_engine import read_combined
            while True:
                if self._stop_event.is_set():
                    raise RuntimeError("__STOP__")
                _, frame = self._frame()
                text, _ = read_combined(frame)
                if text and str(target) in str(text):
                    if action == "ocr_assert":
                        return
                    # OCR 点击: 粗定位——按文字行位置计算 y, x 取屏幕中心偏移
                    info, frame2 = self._frame()
                    h, w = frame2.shape[:2]
                    self._click_ratio(info, 0.5, 0.5)
                    return
                if time.time() > deadline:
                    if extra.get("on_fail") == "skip":
                        raise StepSkipped()
                    raise RuntimeError(f"OCR 未命中: {target}")
                self._stop_event.wait(interval)

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
        x = info.x + int(info.width * float(rx))
        y = info.y + int(info.height * float(ry))
        mouse = MouseController()
        mouse.move_to(x, y)
        _t.sleep(0.15)
        mouse.click('left', 0.06 + 0.05 * (_t.time() % 1))


class StepSkipped(Exception):
    pass


def task_id_name(task: dict):
    return task.get("id", "task")
