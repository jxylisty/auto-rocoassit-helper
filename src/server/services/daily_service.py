# -*- coding: utf-8 -*-
"""日常任务业务服务 (Daily Service)

负责：
1. MAA 式日常流水线任务的配置读取、保存与执行
2. 花种挑战配置读写与执行 (data/config/flower_challenge.json)
3. 遭遇图鉴数据聚合 (基于 SQLite 战报库)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "data" / "config"
FLOWER_CONFIG = CONFIG_DIR / "flower_challenge.json"


class DailyService:
    def __init__(self, capture_frame_cb: Callable[[], Any] | None = None,
                 on_log: Callable[[str, str], None] | None = None,
                 game_launch_cb: Callable[[], Any] | None = None):
        self.on_log = on_log or (lambda msg, lvl: None)
        self.capture_frame_cb = capture_frame_cb
        self.game_launch_cb = game_launch_cb

        try:
            from src.tasks.daily_runner import DailyRunner
            self.daily = DailyRunner(
                frame_provider=self.capture_frame_cb,
                on_log=self.on_log,
                launch_cb=self.game_launch_cb
            )
        except Exception as e:
            self.daily = None
            self.on_log(f"日常任务执行器初始化失败: {e}", "warning")

    def daily_list(self) -> dict:
        return self.daily.list_tasks() if self.daily else {"success": False, "tasks": []}

    def daily_save(self, tasks: list) -> dict:
        return self.daily.save_tasks(tasks or []) if self.daily else {"success": False}

    def daily_run(self, task_id: str) -> dict:
        if not self.daily:
            return {"success": False, "message": "日常执行器不可用"}
        return self.daily.start_task(task_id)

    def daily_run_queue(self, task_ids: list) -> dict:
        if not self.daily:
            return {"success": False, "message": "日常执行器不可用"}
        return self.daily.start_queue(task_ids)

    def daily_stop(self) -> dict:
        if self.daily:
            self.daily.stop()
        return {"success": True}

    def daily_status(self) -> dict:
        return self.daily.get_status() if self.daily else {"success": False}

    # ==================== 花种挑战 ====================

    def flower_config_load(self) -> dict:
        if not FLOWER_CONFIG.exists():
            return {"success": True, "data": {"target_flower": 1, "battles_target": 3, "flower_count_override": 0}}
        try:
            data = json.loads(FLOWER_CONFIG.read_text(encoding="utf-8"))
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def flower_config_save(self, params: dict) -> dict:
        try:
            data = {}
            if FLOWER_CONFIG.exists():
                try:
                    data = json.loads(FLOWER_CONFIG.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            if "target_flower" in params:
                data["target_flower"] = int(params["target_flower"])
            if "battles_target" in params:
                data["battles_target"] = int(params["battles_target"])
            if "flower_count_override" in params:
                data["flower_count_override"] = int(params["flower_count_override"])
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            FLOWER_CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ==================== 图鉴收集册 ====================

    def pokedex_data(self) -> dict:
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
                match_result = (row["result"] or "").upper()
                for p in enemy_pets:
                    name = p.get("name", "").strip()
                    if not name or name == "未知":
                        continue
                    if name not in pets:
                        pets[name] = {"seen": 0, "win": 0, "loss": 0, "first_seen": row["match_time"], "last_seen": row["match_time"]}
                    pets[name]["seen"] += 1
                    pets[name]["last_seen"] = row["match_time"]
                    if match_result == "WIN":
                        pets[name]["win"] += 1
                    elif match_result == "LOSS":
                        pets[name]["loss"] += 1
            return {"success": True, "total_unique": len(pets), "pets": pets}
        except Exception as e:
            return {"success": False, "message": str(e)}
