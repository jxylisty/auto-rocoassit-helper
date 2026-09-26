# -*- coding: utf-8 -*-
"""丢球助手业务服务 (Throw Service)

负责：
1. 自动丢球核心控制 (普通丢球 / 轰炸机 / 技能连按)
2. 丢球延迟与参数配置的校验与持久化 (data/config/throw_ball_config.json)
3. 状态查询 (运行中状态、已丢球数等)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, Any

from auto_throw_ball import AutoThrowBall

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "data" / "config"
CONFIG_FILE = CONFIG_DIR / "throw_ball_config.json"

CONFIG_SCHEMA = {
    "normal_delay_min": (0.05, 5.0),
    "normal_delay_max": (0.05, 5.0),
    "space_delay_min": (0.05, 5.0),
    "space_delay_max": (0.05, 5.0),
    "bomber_loop_interval": (0.05, 5.0),
    "bomber_ball_key": (1, 9),
    "skill_loop_interval": (0.05, 10.0),
}

CONFIG_PAIRS = [
    ("normal_delay_min", "normal_delay_max"),
    ("space_delay_min", "space_delay_max"),
]


class ThrowService:
    def __init__(self, on_log: Callable[[str, str], None] | None = None):
        self.on_log = on_log or (lambda msg, lvl: None)
        self.tool = AutoThrowBall(on_log=self.on_log)
        self.load_config()

    def log(self, message: str, level: str = "info"):
        self.on_log(message, level)

    def load_config(self):
        if not CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for key, value in self._validate_params(data).items():
                setattr(self.tool, key, value)
            self.log("已加载丢球延迟配置", "info")
        except Exception as e:
            self.log(f"加载丢球配置失败: {e}", "error")

    def save_config(self) -> dict:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            cfg = self.get_config()
            data = {k: round(v, 2) if isinstance(v, float) else v for k, v in cfg.items()}
            CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"success": True}
        except Exception as e:
            self.log(f"保存丢球配置失败: {e}", "error")
            return {"success": False, "message": str(e)}

    def get_config(self) -> dict:
        cfg = {key: getattr(self.tool, key, 0) for key in CONFIG_SCHEMA}
        cfg["exit_on_battle"] = getattr(self.tool, "exit_on_battle", True)
        return cfg

    def update_config(self, params: dict) -> dict:
        params = params or {}
        cleaned = self._validate_params(params)
        if "exit_on_battle" in params:
            self.tool.exit_on_battle = bool(params["exit_on_battle"])
            cleaned["exit_on_battle"] = self.tool.exit_on_battle

        if not cleaned:
            return {"success": False, "message": "没有有效参数"}

        for key, value in cleaned.items():
            if key != "exit_on_battle":
                setattr(self.tool, key, value)
        self.save_config()
        self.log(f"丢球延迟配置已更新: {cleaned}", "success")
        return {"success": True, "config": self.get_config()}

    @staticmethod
    def _validate_params(params: dict) -> dict:
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

    def toggle_normal(self) -> dict:
        running = self.tool.toggle_normal()
        return {"success": True, "running": running}

    def toggle_bomber(self) -> dict:
        running = self.tool.toggle_bomber()
        return {"success": True, "running": running}

    def toggle_skill(self) -> dict:
        running = self.tool.toggle_skill()
        return {"success": True, "running": running}

    def stop_all(self) -> dict:
        self.tool.stop_all()
        return {"success": True}

    def get_status(self) -> dict:
        return {
            "running": self.tool.running,
            "bomber_running": getattr(self.tool, "bomber_running", False),
            "skill_running": getattr(self.tool, "skill_running", False),
            "normal_count": getattr(self.tool, "normal_count", 0),
            "bomber_count": getattr(self.tool, "bomber_count", 0),
        }
