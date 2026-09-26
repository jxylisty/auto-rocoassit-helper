# -*- coding: utf-8 -*-
"""PVP 对战助手领域服务 (PVP Service)

继承成熟的 PvpDataMixin，提供：
1. 精灵与技能档案库的模糊检索与预设加载
2. PVP 伤害公式推演、全技能穿透分析与能力值面板计算 (calc_all_skills 等)
3. 天梯战报数据库管理与 ELO 胜率统计
4. 纯控制台下运行，剥离任何 GUI 窗口依赖
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Any

from src.gui.bridge_pvp_data import PvpDataMixin

logger = logging.getLogger("server.pvp")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class PvpService(PvpDataMixin):
    def __init__(self, on_log: Callable[[str, str], None] | None = None,
                 frame_provider: Callable[[], Any] | None = None):
        self.on_log = on_log or (lambda msg, lvl: None)
        self.frame_provider = frame_provider
        self._PVP_ACT_DELAY = 0.3

        # 战斗引擎
        try:
            from src.states.battle_engine import BattleEngine
            self.engine = BattleEngine(
                frame_provider=self.frame_provider,
                on_log=self.on_log,
                dry_run=False
            )
        except Exception as e:
            self.engine = None
            self.on_log(f"战斗引擎初始化失败: {e}", "warning")

        # PVP 实时引擎状态
        self._pvp_running = False
        self._pvp_thread = None
        self._pvp_source = "ocr"  # "ocr" 或 "capture"
        self._collector = None
        self._collector_thread = None
        self._collector_stop = threading.Event()

    def log(self, message: str, level: str = "info"):
        self.on_log(message, level)

    # ==================== PVP 引擎与采集控制 ====================

    def pvp_engine_start(self, source: str = "ocr") -> dict:
        self._pvp_source = source
        self._pvp_running = True
        self.log(f"PVP 识别引擎已启动 (数据源: {source})", "success")
        return {"success": True, "running": True, "source": source}

    def pvp_engine_stop(self) -> dict:
        self._pvp_running = False
        self.log("PVP 识别引擎已停止", "info")
        return {"success": True, "running": False}

    def pvp_engine_status(self) -> dict:
        return {
            "running": self._pvp_running,
            "source": self._pvp_source
        }

    def pvp_collector_start(self) -> dict:
        try:
            from src.pvp.data_collector import PvpDataCollector
            self._collector = PvpDataCollector(output_dir=PROJECT_ROOT / "output")
            self._collector_stop.clear()
            self.log("PVP 数据采集器已启动", "success")
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def pvp_collector_stop(self) -> dict:
        self._collector_stop.set()
        self.log("PVP 数据采集器已停止", "info")
        return {"success": True}

    def pvp_collector_status(self) -> dict:
        running = bool(self._collector and not self._collector_stop.is_set())
        return {"success": True, "running": running}

    def pvp_collector_manual(self) -> dict:
        if not self._collector:
            try:
                from src.pvp.data_collector import PvpDataCollector
                self._collector = PvpDataCollector(output_dir=PROJECT_ROOT / "output")
            except Exception as e:
                return {"success": False, "message": str(e)}
        try:
            res = self._collector.collect_once()
            return {"success": True, "result": res}
        except Exception as e:
            return {"success": False, "message": str(e)}
