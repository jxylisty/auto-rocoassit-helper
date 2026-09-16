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
        self.skill_mode = "cycle"   # cycle=按间隔轮换 / sequence=按序列依次施放
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
        self.shiny_count = 0        # 异色精灵检测计数
        self.balls_used_total = 0   # 挂机期间实际消耗球数(选中球数量差值)
        self._ball_count_last = None
        self._ball_count_reader = None
        self._shiny_this_battle = False
        self._shiny_alert = None          # 异色警报: {name, hp, ts, screenshot} 或 None
        self._stop_all_cb = None          # 由 bridge 注入: 异色时全面停止其它任务
        self.catches = 0            # 丢过球后战斗结束的场次数(视为捕获成功)
        self.skills_used = 0

        # 战斗内状态
        self._in_battle = False
        self._battle_start = 0.0
        self._balls_this_battle = 0
        self._hp_miss_count = 0
        self._skill_index = 0
        self._seq_pos = 0  # 序列模式游标
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
        # 战斗内球型识别切球: 安全球名单(命中即直接丢) + 严格模式(切不到安全球就放弃)
        self.safe_ball_ids = set(cfg_get("battle.safe_ball_ids", ["100003", "540801"]))   # 默认高级咕噜球
        self.strict_safe = bool(cfg_get("battle.strict_safe", False))
        # 异色检测: 命中提示文本时计数; shiny_stop=True 自动停止引擎让你手动捕捉
        self.shiny_stop = bool(cfg_get("battle.shiny_stop", True))
        self._ball_matcher = None
        self._battle_ball_rois = None
        self.flee_hp = cfg_get("battle.flee_hp", self.flee_hp)
        self.flee_key = cfg_get("battle.flee_key", "") or ""
        skills = cfg_get("battle.skills", self.skills)
        if isinstance(skills, list) and skills:
            self.skills = [str(s) for s in skills]
        self.skill_mode = str(cfg_get("battle.skill_mode", "cycle") or "cycle")
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
        try:
            _dm = (overrides or {}).pop("duration_minutes", None)
            if _dm:
                self.battle_timeout = max(300, int(_dm) * 60)
        except Exception:
            pass
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
        self._shiny_alert = None


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
            "shiny_count": self.shiny_count,
            "balls_used_total": self.balls_used_total,
            "catches": self.catches,
            "skills_used": self.skills_used,
            "catch_hp": self.catch_hp,
            "enemy_name": self._enemy_name,
            "enemy_hp": self._enemy_hp,
            "shiny_alert": self._shiny_alert,
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
        self._seq_pos = 0
        self._shiny_this_battle = False

    # ---- 异色精灵检测 ----

    def _shiny_check_async(self):
        """进战斗后延迟 1.5s(等提示文本出现)对整帧做一次 OCR 关键词扫描。
        游戏机制: 出异色时屏幕会出现「出现异色精灵」类文本提示。

        发现异色后的动作(决定权全部交还玩家):
        1. 立即全面停止(引擎+丢球助手全部停, 等价 stop_all)
        2. 自动截一张游戏画面存 data/screenshots/ 作识别存证
        3. 置 _shiny_alert 状态 → 悬浮窗/主控台弹横幅提示玩家
        不做任何换球/捕捉动作。

        机制备注: 异色只在进入战斗(挂机引擎链路)时出现;
        本场对异色精灵造成的伤害超过其血条 100% 时, 游戏会将血量强制回落到 10%。
        """
        def _job():
            if self._stop_event.wait(1.5):
                return
            try:
                from src.utils.ocr_engine import read_combined
                info, frame = self._frame_provider()
                if frame is None or frame.size == 0:
                    return
                text, score = read_combined(frame)
                if text and "异色" in str(text):
                    if self._shiny_this_battle:
                        return   # 本场已计过
                    self._shiny_this_battle = True
                    self.shiny_count += 1

                    # 存证截图(失败不影响全停)
                    shot_name = ""
                    try:
                        from src.utils.image_io import imwrite_unicode
                        import time as _t
                        from pathlib import Path as _P
                        shot_dir = _P(__file__).resolve().parents[2] / "data" / "screenshots"
                        shot_dir.mkdir(parents=True, exist_ok=True)
                        shot_path = shot_dir / ("shiny_" + _t.strftime("%Y%m%d_%H%M%S") + ".png")
                        if imwrite_unicode(shot_path, frame):
                            shot_name = shot_path.name
                    except Exception:
                        pass

                    # 状态外发: 悬浮窗/主控台横幅
                    self._shiny_alert = {
                        "name": self._enemy_name or "?",
                        "hp": self._enemy_hp,
                        "ts": time.strftime("%H:%M:%S"),
                        "screenshot": shot_name,
                        "count": self.shiny_count,
                    }

                    self._log(f"★ [异色] 发现异色精灵({self._enemy_name or '?'})！已全面停止, 请手动捕捉。"
                              f"机制提示: 打超100%血量会回落至10%。"
                              f"{'存证: ' + shot_name if shot_name else ''}(累计 {self.shiny_count} 只)", "success")

                    # 全面停止: 本引擎 + 通知 bridge 停其它所有任务
                    self.stop("发现异色精灵·全停交还玩家")
                    try:
                        if self._stop_all_cb:
                            self._stop_all_cb("发现异色精灵")
                    except Exception:
                        pass
            except Exception:
                pass
        threading.Thread(target=_job, daemon=True, name="ShinyCheck").start()

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
                if not self._shiny_this_battle:
                    self._shiny_check_async()   # 异色提示文本扫描(后台,每场一次)

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


    def _act_skill_sequence(self):
        """固定序列模式: 按用户给的键序依次施放。

        释放标识: 技能施放时游戏会隐藏左下角战斗角标(逃跑按钮所在);
        等角标消失(施放成功)→再出现(界面恢复)→才施放序列中的下一个。
        """
        import random as _r
        from src.driver import human_input

        if not self.skills:
            return
        key = self.skills[self._seq_pos % len(self.skills)]
        self.state = "fighting"
        self.state_detail = f"序列技能 {key}(第{self._seq_pos + 1}步)"

        if self.dry_run:
            self._log(f"[模拟] 序列施放技能 {key}", "info")
        else:
            if not self._check_foreground():
                self.state = "paused"
                self.state_detail = "游戏不在前台,暂停操作"
                self._stop_event.wait(1.0)
                return
            human_input.press(key)
            self.skills_used += 1

            # 等待角标消失(确认技能已释放)
            if not self._wait_indicator(lambda s: s < 0.55, timeout=12.0):
                self._log(f"未检测到技能释放标志(角标未消失),继续下一步", "warning")
            # 等待角标恢复(界面回到可选技能状态)
            self._wait_indicator(lambda s: s >= 0.55, timeout=12.0)

        self._seq_pos += 1
        self._stop_event.wait(_r.uniform(0.4, 0.9))

    def _wait_indicator(self, cond, timeout: float) -> bool:
        """等待左角标匹配分数满足条件,超时返回 False"""
        import time as _t
        if self._battle_detector is None:
            from src.perception.battle_detector import BattleDetector
            from src.perception.vision_pipeline import load_roi_config
            rois = load_roi_config()
            self._battle_detector = BattleDetector(
                rois["battle_left_indicator"], rois["battle_right_indicator"])
        deadline = _t.time() + timeout
        while _t.time() < deadline and self._running and not self._stop_event.is_set():
            try:
                _, frame = self._frame_provider()
                result = self._battle_detector.detect(frame)
                if cond(float(result["left_score"])):
                    return True
            except Exception:
                pass
            if self._stop_event.wait(0.2):
                break
        return False

    def _act_skill(self):
        if self.skill_mode == "sequence":
            self._act_skill_sequence()
            return
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
        """丢球流程: 按 W 开界面 → 确认左角标消失(界面已开) → 识别当前选中的球 →
        (贵重球则滚轮切换到安全球) → 按空格丢出。

        游戏机制: 丢球界面打开时只隐藏左下角战斗角标(右下角仍在);
        选球后需按空格才会真正丢出。捕捉失败仍在战斗中,
        外层循环检测到 hp 仍≤捕获线会再次进入本流程。

        球型识别: 界面打开后用「进入战斗后咕噜球1」ROI 识别当前选中的球,
        命中贵重球名单时用内核级滚轮(interception.scroll)切换, 直到安全球。
        识别不可用(无模板/无ROI)时回退旧的槽位键流程。
        """
        self._balls_this_battle += 1
        self.catch_attempts += 1
        self.state = "throwing"
        self.state_detail = f"丢球(第{self._balls_this_battle}球)"

        if self.dry_run:
            self._log(f"[模拟] 按{self.open_ball_key}开界面(左角标消失确认) → "
                      f"识别球型+滚轮切球 → 按空格丢出(第{self._balls_this_battle}球)", "info")
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

        # 球型识别 + 滚轮切球(替代盲按槽位键, 防止丢出贵重球)
        selected = self._select_safe_ball()
        if selected is not None:
            ball_id, ball_name = selected
            self._stop_event.wait(0.3)
            human_input.press("space")   # 选球后按空格才会丢出
            self._log(f"已丢球(第{self._balls_this_battle}球, 球型:{ball_name})", "info")
            self._stop_event.wait(self.ball_cooldown)
            return

        # 回退: 识别不可用时按原槽位键流程
        human_input.press(self.ball_slot_key)
        self._stop_event.wait(0.3)
        human_input.press("space")   # 选球后按空格才会丢出
        self._log(f"已丢球(第{self._balls_this_battle}球,槽位{self.ball_slot_key},识别不可用回退)", "info")
        self._stop_event.wait(self.ball_cooldown)

    # ---- 战斗内球型识别与滚轮切球 ----

    def _ensure_ball_matcher(self) -> bool:
        """懒加载球模板匹配器与战斗内球槽 ROI; 不可用返回 False"""
        if getattr(self, "_ball_matcher", None) is not None:
            return True
        try:
            from src.perception.ball_watcher import BallSlotWatcher, BallTemplateMatcher
            cfg = BallSlotWatcher._load_config()
            active = set(cfg.get("active_balls") or []) or None
            self._ball_matcher = BallTemplateMatcher(active, cfg.get("prefer", "official"))
            self._battle_ball_rois = BallSlotWatcher._load_postbattle_rects()
            return bool(self._ball_matcher.refs and self._battle_ball_rois)
        except Exception:
            return False

    def _identify_selected_ball(self, frame):
        """识别丢球界面当前选中的球(取「进入战斗后咕噜球1」) → (ball_id, ball_name) 或 None"""
        if not self._ensure_ball_matcher():
            return None
        roi = self._battle_ball_rois.get(1)
        if roi is None or frame is None or frame.size == 0:
            return None
        r = self._ball_matcher.match_frame_rect(frame, roi)
        if r["present"] and r["ball_id"]:
            return (r["ball_id"], r["ball_name"])
        return None

    def _select_safe_ball(self):
        """确认当前选中球安全; 贵重球则内核级滚轮切换, 最多 6 轮。
        返回 (ball_id, ball_name) 表示可以丢; None 表示识别不可用(走旧流程)。
        未知球型(模板未覆盖)按可丢处理, strict_safe=True 时才拦截。"""
        try:
            frame = self._frame_provider()
        except Exception:
            frame = None
        selected = self._identify_selected_ball(frame)
        if selected is None:
            return None   # 识别不可用 → 旧流程

        # 数量统计: 读当前选中球的库存数字, 与上次差值累计为引擎实际消耗
        try:
            from src.perception.ocr_reader import OcrNumberReader
            from src.ocr.base import ROI
            if getattr(self, "_ball_count_reader", None) is None:
                rx, ry, rw, rh = self._battle_ball_rois[1]
                self._ball_count_reader = OcrNumberReader(
                    ROI(name="battle_ball_count", left=rx, top=ry + rh * 0.5,
                        width=rw, height=rh * 0.5), percent=False)
            rr = self._ball_count_reader.read(frame)
            if rr and rr.value is not None:
                cur = int(rr.value)
                prev = getattr(self, "_ball_count_last", None)
                if prev is not None and cur < prev:
                    self.balls_used_total = getattr(self, "balls_used_total", 0) + (prev - cur)
                    self._log(f"🏀 [引擎用球] {prev} → {cur}, 挂机累计消耗 {self.balls_used_total} 颗", "info")
                self._ball_count_last = cur
        except Exception:
            pass

        import interception
        for attempt in range(6):
            ball_id, ball_name = selected
            if ball_id in self.safe_ball_ids:
                if attempt:
                    self._log(f"🎯 滚轮切球完成: 当前 {ball_name}(安全)", "success")
                return selected
            self._log(f"💎 当前选中 {ball_name} 在贵重球名单, 滚轮切换 ({attempt + 1}/6)", "warning")
            interception.scroll('down')
            self._stop_event.wait(0.5)
            try:
                frame = self._frame_provider()
            except Exception:
                frame = None
            new_selected = self._identify_selected_ball(frame)
            if new_selected is None:
                return None   # 切换后识别不到(界面异常), 走旧流程兜底
            if new_selected == selected:
                self._log("滚轮滚动后选择未变化(可能到队尾), 停止切换", "warning")
                break
            selected = new_selected

        # 6 轮未找到安全球
        if selected[0] not in self.safe_ball_ids and not self.strict_safe:
            self._log(f"未切到名单内安全球, 按非严格模式丢弃 {selected[1]}", "warning")
            return selected
        self._log("未切到安全球且严格模式开启, 本轮放弃丢球", "error")
        self._balls_this_battle = self.max_balls   # 阻止继续丢球
        return None

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
