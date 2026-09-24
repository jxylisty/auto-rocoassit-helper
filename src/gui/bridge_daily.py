"""AppBridge Mix-in —— 日常任务与调度器"""

import json
import threading
import time
from src.gui.bridge_common import CONFIG_DIR


class DailyMixin:


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
        try:
            self.daily._ran_once = False   # 单任务也做初始界面衔接校验
        except Exception:
            pass
        return self.daily.start_task(task_id)

    def daily_run_queue(self, task_ids) -> dict:
        """一键执行: MAA 式流水线(按清单顺序串行)。
        启动前把游戏窗口强制置顶(用户要求), 否则按键/点击全打到控制台。"""
        gate = self._auth_gate()
        if gate:
            return gate
        if not self.daily:
            return {"success": False, "message": "日常执行器不可用"}
        try:
            if self.engine.running:
                self.engine.stop("启动日常任务")
        except Exception:
            pass
        try:
            self._pvp_running = False
        except Exception:
            pass
        try:
            self.daily._ran_once = False
        except Exception:
            pass
        # 启动即置顶游戏(异步不阻塞 JS 返回; runner 内部每步还有兜底置前)
        def _front_job():
            try:
                self.daily._ensure_game_front()
            except Exception:
                pass
        threading.Thread(target=_front_job, daemon=True).start()
        return self.daily.start_queue(task_ids)

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
