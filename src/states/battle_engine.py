# -*- coding: utf-8 -*-
"""
战斗引擎 - 自动战斗闭环(IDLE等待 → 战斗循环 → 低血丢球 → 循环)

策略(固定+可配置):
1. 血量识别失败 → 容忍等待(连续失败过多才报警)
2. 敌方血量 ≤ 捕获血线 → 蓄力丢球
3. 敌方血量 ≤ 逃跑血线 且配置了逃跑键 → 逃跑
4. 其余 → 轮流按技能键
5. 单场超时 / 丢球次数上限 → 安全停止

安全设计:
- 仅当游戏窗口在前台时才执行键鼠操作(防止切出去乱按)
- dry_run 模式只识别+日志决策,不执行任何键鼠(用于安全验证)
"""

from __future__ import annotations

import random
import threading
import time
from typing import Callable, Optional

from src.utils.settings import get as cfg_get


class BattleEngine:
    """自动战斗引擎(独立线程运行)"""

    def __init__(self, frame_provider: Callable, on_log: Optional[Callable] = None,
                 dry_run: bool = False):
        """
        Args:
            frame_provider: () -> (info, frame) 截帧函数(由 GUI 注入,屏幕区域截取)
            on_log: 日志回调 (message, level)
            dry_run: 只决策不执行键鼠
        """
        self._frame_provider = frame_provider
        self._log_cb = on_log or (lambda msg, level="info": print(msg))
        self.dry_run = dry_run

        # 策略参数(启动时从 settings.yaml 读取,可被 override 覆盖)
        self.catch_hp = 5           # 游戏锁血 1%,稍放宽覆盖识别抖动
        self.flee_hp = 8
        self.flee_key = ""          # 为空则不启用逃跑
        self.skills = ["1", "2", "3", "4"]
        self.skill_interval = (1.2, 2.0)
        self.open_ball_key = "w"    # 打开丢球界面的键
        self.ball_slot_key = "1"    # 球槽键(1-6,用户自选丢哪种球)
        self.ball_ui_confirm = True # 是否视觉确认丢球界面已打开
        self.ball_ui_wait = 0.8     # 按 W 后等界面出现(秒)
        self.ball_cooldown = 3.0    # 丢球后等待结果动画(秒)
        self.battle_timeout = 240
        self.max_balls = 30
        self.max_hp_miss = 12       # 连续血量识别失败容忍帧数

        # 运行状态
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 统计与当前状态(GUI 展示)
        self.state = "stopped"      # stopped / waiting / fighting / throwing / paused
        self.state_detail = ""
        self.battles_done = 0
        self.catch_attempts = 0     # 丢球次数
        self.catches = 0            # 丢过球后战斗结束的场次数(视为捕获成功)
        self.skills_used = 0

        # 战斗内状态
        self._in_battle = False
        self._battle_start = 0.0
        self._balls_this_battle = 0
        self._hp_miss_count = 0
        self._skill_index = 0
        self._enemy_name = ""          # 当前敌方精灵名
        self._enemy_hp = None          # 当前敌方血量%
        self._battle_detector = None  # 丢球界面判定用的角标检测器(懒加载)
        self._streak_hash = None      # 巡逻卡住检测: 连续相同的画面哈希计数
        self._stuck_count = 0

    # ========================================
    # 生命周期
    # ========================================

    def load_strategy(self):
        """从 settings.yaml 读取策略参数"""
        self.catch_hp = cfg_get("battle.catch_hp", self.catch_hp)
        self.flee_hp = cfg_get("battle.flee_hp", self.flee_hp)
        self.flee_key = cfg_get("battle.flee_key", "") or ""
        skills = cfg_get("battle.skills", self.skills)
        if isinstance(skills, list) and skills:
            self.skills = [str(s) for s in skills]
        self.skill_interval = (cfg_get("battle.skill_interval_min", self.skill_interval[0]),
                               cfg_get("battle.skill_interval_max", self.skill_interval[1]))
        self.ball_cooldown = cfg_get("battle.ball_cooldown", self.ball_cooldown)
        self.open_ball_key = str(cfg_get("battle.open_ball_key", self.open_ball_key) or "w")
        self.ball_slot_key = str(cfg_get("battle.ball_slot_key", self.ball_slot_key) or "1")
        self.ball_ui_wait = float(cfg_get("battle.ball_ui_wait", self.ball_ui_wait))
        self.battle_timeout = cfg_get("battle.battle_timeout", self.battle_timeout)
        self.max_balls = cfg_get("battle.max_balls_per_battle", self.max_balls)

        # 巡逻找怪参数
        self.patrol_enabled = bool(cfg_get("patrol.enabled", True))
        self.patrol_move_key = str(cfg_get("patrol.move_key", "w") or "w")
        self.patrol_move_min = float(cfg_get("patrol.move_min", 1.5))
        self.patrol_move_max = float(cfg_get("patrol.move_max", 3.0))
        self.patrol_turn_mode = str(cfg_get("patrol.turn_mode", "mouse") or "keys")  # keys/mouse
        self.patrol_turn_chance = float(cfg_get("patrol.turn_chance", 0.35))
        self.patrol_stuck_limit = int(cfg_get("patrol.stuck_limit", 6))  # 连续N段画面无变化=卡住

    def start(self, overrides: Optional[dict] = None):
        if self._running:
            return False
        self.load_strategy()
        for key, value in (overrides or {}).items():
            if hasattr(self, key):
                setattr(self, key, value)
        self._running = True
        self._stop_event.clear()
        self._reset_battle()
        self.battles_done = 0
        self.catch_attempts = 0
        self.catches = 0
        self.skills_used = 0
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BattleEngine")
        self._thread.start()
        mode = "【模拟模式】" if self.dry_run else ""
        self._log(f"战斗引擎已启动 {mode}策略: 血量≤{self.catch_hp}%时 按{self.open_ball_key}开界面→"
                  f"按{self.ball_slot_key}丢球; 技能轮换 {'→'.join(self.skills)}", "success")
        return True

    def stop(self, reason: str = "手动停止"):
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        self.state = "stopped"
        self.state_detail = ""
        self._log(f"战斗引擎已停止({reason}) 本轮: 战斗{self.battles_done}场 丢球{self.catch_attempts}次 捕获{self.catches}只",
                  "warning")

    @property
    def running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "dry_run": self.dry_run,
            "state": self.state,
            "detail": self.state_detail,
            "battles_done": self.battles_done,
            "catch_attempts": self.catch_attempts,
            "catches": self.catches,
            "skills_used": self.skills_used,
            "catch_hp": self.catch_hp,
            "enemy_name": self._enemy_name,
            "enemy_hp": self._enemy_hp,
        }

    # ========================================
    # 主循环
    # ========================================

    def _log(self, msg, level="info"):
        self._log_cb(msg, level)

    def _reset_battle(self):
        self._in_battle = False
        self._balls_this_battle = 0
        self._hp_miss_count = 0
        self._skill_index = 0

    def _loop(self):
        from src.perception import VisionPipeline
        pipeline = VisionPipeline()

        while self._running and not self._stop_event.is_set():
            try:
                info, frame = self._frame_provider()
            except Exception as e:
                self.state = "paused"
                self.state_detail = str(e)[:40]
                self._log(f"战斗引擎暂停: {e}", "warning")
                if self._stop_event.wait(2.0):
                    break
                continue

            try:
                snap = pipeline.analyze(frame, light=True)
            except Exception as e:
                self._log(f"识别异常: {e}", "error")
                if self._stop_event.wait(1.5):
                    break
                continue

            in_battle = bool(snap.raw.get("battle", {}).get("in_battle"))
            hp = snap.enemy_hp.value

            # ---- 战斗结束判定 ----
            if not in_battle:
                if self._in_battle:
                    self._on_battle_end()
                self.state = "waiting"
                self.state_detail = "巡逻找怪" if self.patrol_enabled else "等待进入战斗"
                if self.patrol_enabled:
                    self._patrol_segment(pipeline)
                else:
                    self._stop_event.wait(1.0)
                continue

            # ---- 进入战斗(全量识别一次,拿精灵名用于日志) ----
            if not self._in_battle:
                self._in_battle = True
                self._battle_start = time.time()
                self._balls_this_battle = 0
                self._hp_miss_count = 0
                try:
                    full = pipeline.analyze(frame, light=False)
                    name = full.enemy_name.value or "?"
                    hp = full.enemy_hp.value if hp is None else hp
                    self._enemy_name = name
                    self._enemy_hp = hp
                except Exception:
                    name = "?"
                    self._enemy_name = ""
                    self._enemy_hp = None
                self._log(f"进入战斗: {name}(血量{hp if hp is not None else '?'}%)", "success")

            # ---- 超时保护 ----
            if time.time() - self._battle_start > self.battle_timeout:
                self._log(f"单场战斗超时({self.battle_timeout}s),停止引擎", "error")
                self.stop("战斗超时")
                break

            # ---- 血量识别失败容忍 ----
            if hp is None:
                self._hp_miss_count += 1
                self.state = "fighting"
                self.state_detail = f"血量识别失败 {self._hp_miss_count}/{self.max_hp_miss}"
                if self._hp_miss_count >= self.max_hp_miss:
                    self._log("连续血量识别失败过多,本场先按技能推进一步", "warning")
                    self._act_skill()
                self._stop_event.wait(1.0)
                continue
            self._hp_miss_count = 0
            self._enemy_hp = hp

            # ---- 策略决策 ----
            self.state_detail = f"敌方血量 {hp}%"

            if hp <= self.flee_hp and self.flee_key:
                self._act_flee()
            elif hp <= self.catch_hp:
                if self._balls_this_battle >= self.max_balls:
                    self._log(f"本场丢球已达上限({self.max_balls}),停止引擎", "warning")
                    self.stop("丢球上限")
                    break
                self._act_throw_ball()
            else:
                self._act_skill()

    def _on_battle_end(self):
        self.battles_done += 1
        caught = self._balls_this_battle > 0
        if caught:
            self.catches += 1
        self._log(f"战斗结束(第{self.battles_done}场) {'疑似捕获成功' if caught else '未丢球'}", "success")
        self._enemy_name = ""
        self._enemy_hp = None
        self._reset_battle()

    # ========================================
    # 巡逻找怪(战斗间隙随机走动)
    # ========================================

    def _frame_hash(self, frame) -> str:
        """巡逻卡住检测用的粗粒度画面哈希(16x9 缩略灰度)"""
        import cv2
        small = cv2.resize(frame, (16, 9))
        return hash(small.tobytes())

    def _patrol_segment(self, pipeline):
        """走一段路:按住走动键随机时长,期间每0.3s检测一次是否进战斗。

        检测到战斗立即松开所有键;画面长时间无变化(撞墙/卡住)执行脱困。
        """
        import random as _r

        duration = _r.uniform(self.patrol_move_min, self.patrol_move_max)
        turn = _r.random() < self.patrol_turn_chance
        turn_key = _r.choice(("a", "d"))

        if self.dry_run:
            self._log(f"[模拟] 巡逻: 按住{self.patrol_move_key} {duration:.1f}s"
                      f"{' + 转向' + turn_key if turn else ''}", "info")
            self._stop_event.wait(min(duration, 1.0))
            return

        import interception
        from src.driver import human_input

        # 卡住检测: 对比本段起点画面
        try:
            _, start_frame = self._frame_provider()
            start_hash = self._frame_hash(start_frame)
            if start_hash == self._streak_hash:
                self._stuck_count += 1
            else:
                self._streak_hash = start_hash
                self._stuck_count = 0
        except Exception:
            start_hash = None

        if self._stuck_count >= self.patrol_stuck_limit:
            self._log(f"画面连续{self._stuck_count}段无变化,疑似卡住,执行脱困", "warning")
            self._escape_stuck()
            self._stuck_count = 0
            return

        try:
            if turn:
                # 先转向再走;鼠标转向走拟人多段曲线
                if self.patrol_turn_mode == "mouse":
                    dx = _r.choice((-1, 1)) * _r.randint(200, 600)
                    human_input.move_relative(dx, 0)
                    self._stop_event.wait(_r.uniform(0.1, 0.3))
                else:
                    human_input.key_down(turn_key)
                    self._stop_event.wait(_r.uniform(0.3, 0.8))
                    human_input.key_up(turn_key)
            human_input.key_down(self.patrol_move_key)
            # 分片按住,每片之间检查是否进战斗
            elapsed = 0.0
            while elapsed < duration and self._running and not self._stop_event.is_set():
                self._stop_event.wait(0.3)
                elapsed += 0.3
                if elapsed >= 0.6 and self._battle_spotted(pipeline):
                    self.state_detail = "发现战斗!"
                    break
        finally:
            try:
                from src.driver import human_input
                human_input.key_up(self.patrol_move_key)
            except Exception:
                pass

    def _battle_spotted(self, pipeline) -> bool:
        """巡逻途中的轻量战斗检测"""
        try:
            _, frame = self._frame_provider()
            snap = pipeline.analyze(frame, light=True)
            return bool(snap.raw.get("battle", {}).get("in_battle"))
        except Exception:
            return False

    def _escape_stuck(self):
        """脱困:后退 + 大幅拟人转向"""
        import random as _r
        from src.driver import human_input
        try:
            human_input.key_down("s")
            self._stop_event.wait(1.0)
            human_input.key_up("s")
            dx = _r.choice((-1, 1)) * _r.randint(500, 1000)
            if self.patrol_turn_mode == "mouse":
                human_input.move_relative(dx, 0)
                self._stop_event.wait(0.3)
            else:
                turn = "a" if dx > 0 else "d"
                human_input.key_down(turn)
                self._stop_event.wait(1.2)
                human_input.key_up(turn)
        except Exception:
            pass

    # ========================================
    # 动作执行(dry_run 只记日志)
    # ========================================

    def _check_foreground(self) -> bool:
        """游戏必须在前台才能执行键鼠(防误操作其他窗口)"""
        if self.dry_run:
            return True
        try:
            from src.capture.window_capture import get_foreground_hwnd, find_window
            info = find_window(class_name="UnrealWindow")
            return bool(info) and get_foreground_hwnd() == info.hwnd
        except Exception:
            return False

    def _act_skill(self):
        # 技能轮换为主,偶尔重复/跳过,避免严格周期性
        import random as _r
        if _r.random() < 0.10 and self._skill_index > 0:
            pass  # 重复上一个技能
        else:
            self._skill_index += 1
            if _r.random() < 0.10:
                self._skill_index += 1  # 跳过一个
        key = self.skills[(self._skill_index - 1) % len(self.skills)]
        self.state = "fighting"
        if self.dry_run:
            self._log(f"[模拟] 按技能 {key}", "info")
        else:
            if not self._check_foreground():
                self.state = "paused"
                self.state_detail = "游戏不在前台,暂停操作"
                self._stop_event.wait(1.0)
                return
            from src.driver import human_input
            human_input.press(key)
            self.skills_used += 1
        self._stop_event.wait(random.uniform(*self.skill_interval))

    def _act_throw_ball(self):
        """丢球流程: 按 W 开界面 → 确认左角标消失(界面已开) → 按球槽键 → 按空格丢出。

        游戏机制: 丢球界面打开时只隐藏左下角战斗角标(右下角仍在);
        选球后需按空格才会真正丢出。捕捉失败仍在战斗中,
        外层循环检测到 hp 仍≤捕获线会再次进入本流程。
        """
        self._balls_this_battle += 1
        self.catch_attempts += 1
        self.state = "throwing"
        self.state_detail = f"丢球(第{self._balls_this_battle}球)"

        if self.dry_run:
            self._log(f"[模拟] 按{self.open_ball_key}开界面(左角标消失确认) → "
                      f"按{self.ball_slot_key}选球 → 按空格丢出(第{self._balls_this_battle}球)", "info")
            self._stop_event.wait(self.ball_cooldown)
            return

        if not self._check_foreground():
            self.state = "paused"
            self.state_detail = "游戏不在前台,暂停操作"
            self._stop_event.wait(1.0)
            return

        import interception
        from src.driver import human_input
        opened = False
        for attempt in range(3):
            human_input.press(self.open_ball_key)
            self._stop_event.wait(self.ball_ui_wait)
            if self._ball_ui_open():
                opened = True
                break
            self._log(f"左角标未消失(界面可能没打开),重试 {self.open_ball_key}({attempt + 1}/3)", "warning")

        if not opened:
            self._log("丢球界面打不开,本场放弃丢球(改为技能输出)", "error")
            self._balls_this_battle = self.max_balls  # 阻止继续丢球
            return

        human_input.press(self.ball_slot_key)
        self._stop_event.wait(0.3)
        human_input.press("space")   # 选球后按空格才会丢出
        self._log(f"已丢球(第{self._balls_this_battle}球,槽位{self.ball_slot_key})", "info")
        self._stop_event.wait(self.ball_cooldown)

    def _ball_ui_open(self) -> bool:
        """丢球界面打开的判定: 左下战斗角标消失。

        游戏机制: 丢球界面显示时只隐藏左侧角标,右侧仍在。
        左角标匹配分显著低于阈值即视为界面已打开。
        """
        try:
            if self._battle_detector is None:
                from src.perception.battle_detector import BattleDetector
                from src.perception.vision_pipeline import load_roi_config
                rois = load_roi_config()
                self._battle_detector = BattleDetector(
                    rois["battle_left_indicator"], rois["battle_right_indicator"])
            _, frame = self._frame_provider()
            result = self._battle_detector.detect(frame)
            return float(result["left_score"]) < 0.55
        except Exception:
            return False

    def _act_flee(self):
        if self.dry_run:
            self._log(f"[模拟] 逃跑({self.flee_key})", "warning")
        else:
            if not self._check_foreground():
                self._stop_event.wait(1.0)
                return
            import interception
            self._log(f"执行逃跑({self.flee_key})", "warning")
            interception.press(self.flee_key)
        self._stop_event.wait(2.0)


__all__ = ['BattleEngine']
