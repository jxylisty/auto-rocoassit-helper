# -*- coding: utf-8 -*-
"""花种挑战自动化(日常获得 · 第一项)

流程(由 DailyRunner 的 flower_challenge 动作驱动, 也可独立调用):
  1. F3 打开日常获得 → 延时 1s → 点击花种框(打开命定花种面板)
  2. OCR 花种名称 + 过期时间: 第 4 行过期时间与其余一致 → 4 个命定花种, 否则 3 个
  3. 直接点击目标花种行的「传送按钮」(用户框了第 1、3 行两个传送框, 线性推算全部行)
  4. 等地图加载(默认 1.5s, 传送点离花种很近) → OCR「识别挑战」区域等"挑战"字样
     (偶尔没直接怼脸就短按 W 蹭一步)
  5. 切精灵(数字键 1~6, 用户配置) → 按 F 进入挑战
  6. 战斗: 按技能序列分段轮换(如 31,112,222), BattleDetector 判在战斗中持续施放
  7. Boss 死 → 自动进丢球界面 → 按 1(默认免费球) → 等 5s 捕捉动画
  8. 点一下屏幕 → OCR「再次挑战按钮」出现 → 点击 → 计数, 进入下一场
  9. 达到用户设定场数后结束

全程约束:
  - 游戏窗口保持置前(启动/传送后/每场开始前都拉一次前台)
  - 输入全部走 Interception 内核级硬件模拟(human_input / MouseController)
  - 操作间隔用指数分布随机延迟(human_input.wait_exp), 防统计检测
"""
import json
import re
import time
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "data" / "config"
CONFIG_FILE = CONFIG_DIR / "flower_challenge.json"

# 花种名称行 ROI 的 id 前缀(用户标注命名不统一: 花种名称1/花种名称二/花种名称3/花中名称4)
NAME_ROI_PREFIXES = ("花种名称", "花中名称")


class FlowerChallenge:
    DEFAULTS = {
        "target_flower": 1,        # 打第几个花种(1~4, 超过实际命定数会报错)
        "battle_count": 5,         # 战斗几场(再次挑战循环计数)
        "switch_pet_key": "1",     # 进挑战前切精灵的数字键(1~6)
        "skill_sequence": "31,112,222",  # 每场技能按键序列, 逗号分段轮换, 每段=一串数字键
        "ball_key": "1",           # 丢球界面球槽键(1=默认免费球)
        "map_load_wait": 1.5,      # 点传送后地图加载等待(秒, 传送点离花种很近 1~2s 见挑战)
        "capture_wait": 5.0,       # 丢球后捕捉动画等待(秒)
        "walk_seconds": 1.5,       # OCR 未见到挑战时, 短按 W 蹭一步的时长(秒)
        "challenge_timeout": 60,   # 等"挑战"按钮出现的总超时(秒)
        "exp_mean": 0.8,           # 指数分布延迟均值(秒)
        "flower_count_override": 0,  # 0=自动 OCR 判断 3/4; >0 强制指定命定花种数量
        "click_after_capture": [0.5, 0.35],  # 捕捉动画后点一下屏幕的位置(比例)
        "teleport_rows": [1, 2],   # 两个传送框 ROI 对应的花种行号(用户框了第 1、2 行)
        "confirm_teleport": False, # 点行传送按钮后是否还需点「点击地图传送按钮」确认
    }

    def __init__(self, frame_provider: Callable, log_cb: Optional[Callable] = None,
                 stop_event=None):
        self._frame_provider = frame_provider
        self._log_cb = log_cb or (lambda msg, level="info": None)
        self._stop_event = stop_event
        self._rois = None          # 懒加载 load_roi_config()
        self._detector = None      # 懒加载 BattleDetector

    # ---------- 配置 ----------
    @classmethod
    def load_config(cls) -> dict:
        cfg = dict(cls.DEFAULTS)
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in cls.DEFAULTS})
        except Exception:
            pass
        return cfg

    @classmethod
    def save_config(cls, params: dict) -> dict:
        cfg = cls.load_config()
        try:
            cfg["target_flower"] = max(1, min(4, int(params.get("target_flower", cfg["target_flower"]))))
            cfg["battle_count"] = max(1, min(99, int(params.get("battle_count", cfg["battle_count"]))))
            cfg["switch_pet_key"] = str(params.get("switch_pet_key", cfg["switch_pet_key"]))[:1] or "1"
            cfg["skill_sequence"] = str(params.get("skill_sequence", cfg["skill_sequence"]))[:60]
            cfg["ball_key"] = str(params.get("ball_key", cfg["ball_key"]))[:1] or "1"
            for k in ("map_load_wait", "capture_wait", "walk_seconds", "challenge_timeout", "exp_mean"):
                cfg[k] = max(0.5, min(120.0, float(params.get(k, cfg[k]))))
            cfg["flower_count_override"] = max(0, min(4, int(params.get("flower_count_override", 0) or 0)))
            tr = params.get("teleport_rows", cfg.get("teleport_rows") or [1, 3])
            if isinstance(tr, str):
                tr = [int(x) for x in re.findall(r"\d+", tr)]
            tr = [int(tr[0]), int(tr[1])]
            if tr[0] == tr[1] or not all(1 <= x <= 6 for x in tr):
                raise ValueError("teleport_rows 两行序号必须不同且在 1~6")
            cfg["teleport_rows"] = tr
            cfg["confirm_teleport"] = bool(params.get("confirm_teleport", cfg.get("confirm_teleport", False)))
        except Exception as e:
            return {"success": False, "message": f"参数不合法: {e}"}
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"success": True, "data": cfg}

    # ---------- 基础设施 ----------
    def _log(self, msg, level="info"):
        self._log_cb("[花种] " + msg, level)

    def _stopped(self) -> bool:
        return self._stop_event is not None and self._stop_event.is_set()

    def _wait(self, seconds: float):
        """可打断的固定等待"""
        if self._stop_event is not None:
            self._stop_event.wait(seconds)
        else:
            time.sleep(seconds)
        if self._stopped():
            raise RuntimeError("__STOP__")

    def _exp(self, mean: float = None):
        """指数分布拟人间隔"""
        from src.driver import human_input
        human_input.wait_exp(mean if mean else self._cfg["exp_mean"], self._stop_event)
        if self._stopped():
            raise RuntimeError("__STOP__")

    def _frame(self):
        # 点击类动作依赖屏幕坐标 → 每次截图前确保游戏在前台且持有焦点
        # (否则 Interception 点击/按键会落到别的窗口)
        try:
            self._ensure_front()
        except Exception:
            pass
        info, frame = self._frame_provider()
        if frame is None or frame.size == 0:
            raise RuntimeError("截图失败(游戏未前台?)")
        return info, frame

    def _ensure_front(self):
        """游戏窗口置前(用户要求全程前台)"""
        try:
            from src.capture.window_capture import WindowCapture, find_window
            info = find_window(class_name="UnrealWindow")
            if info is not None:
                WindowCapture(info.hwnd).bring_to_front()
                self._wait(0.5)
        except Exception as e:
            self._log(f"置前失败(继续): {e}", "warning")

    def _rois_map(self):
        if self._rois is None:
            from src.perception.vision_pipeline import load_roi_config
            self._rois = load_roi_config()
        return self._rois

    def _roi(self, name: str):
        roi = self._rois_map().get(name)
        if roi is None:
            raise RuntimeError(f"缺少 ROI「{name}」, 请在视觉调试台标注后保存")
        return roi

    def _click_roi(self, roi_name: str):
        """点击 ROI 中心(Interception 硬件级)"""
        from src.driver.mouse_controller import MouseController
        info, _ = self._frame()
        roi = self._roi(roi_name)
        x = info.rect[0] + int(info.width * (roi.left + roi.width / 2))
        y = info.rect[1] + int(info.height * (roi.top + roi.height / 2))
        mouse = MouseController()
        mouse.move_to(x, y)
        time.sleep(0.12 + 0.10 * (time.time() % 1))
        mouse.click('left', 0.05 + 0.05 * (time.time() % 1))

    def _ocr_roi(self, roi_name: str, frame=None):
        """OCR 单个 ROI, 返回 (text, score)"""
        from src.utils.ocr_engine import read_combined
        if frame is None:
            _, frame = self._frame()
        return read_combined(self._roi(roi_name).crop(frame))

    def _press(self, key: str):
        from src.driver import human_input
        human_input.press(str(key))

    def _ensure_detector(self):
        if self._detector is None:
            from src.perception.battle_detector import BattleDetector
            rois = self._rois_map()
            self._detector = BattleDetector(
                rois.get("battle_left_indicator"), rois.get("battle_right_indicator"))
            if not (self._detector.left_templates or self._detector.right_templates):
                self._log("战斗角标模板缺失, 战斗结束判定不可靠", "warning")
        return self._detector

    def _in_battle(self, frame=None) -> bool:
        """战斗角标判定(复用挂机引擎的 BattleDetector)。
        注意: 异常/截图失败会返回 False, 所以判定脱战必须走 _battle_gone 双重确认"""
        try:
            det = self._ensure_detector()
            if frame is None:
                _, frame = self._frame()
            return bool(det.detect(frame).get("in_battle"))
        except Exception:
            return False

    def _detect_raw(self, frame=None):
        """角标原始分数(丢球界面判定用: 左角标分 < 0.55 = 弹出), 异常返回 None"""
        try:
            det = self._ensure_detector()
            if frame is None:
                _, frame = self._frame()
            return det.detect(frame)
        except Exception:
            return None

    def _battle_gone(self, checks: int = 2) -> bool:
        """连续 N 次判定脱战才确认, 防瞬时截图失败误判提前收手"""
        for i in range(checks):
            if self._in_battle():
                return False
            if i < checks - 1:
                self._stop_event_wait_small(0.35)
        return True

    # ---------- 主流程 ----------
    def run(self) -> dict:
        self._cfg = self.load_config()
        battles_target = int(self._cfg["battle_count"])
        self._log(f"开始: 目标花种#{self._cfg['target_flower']} · 计划 {battles_target} 场 · "
                  f"技能序列[{self._cfg['skill_sequence']}] · 指数延迟均值 {self._cfg['exp_mean']}s", "success")
        try:
            self._phase_entry()
            battles_done = self._phase_battles(battles_target)
            self._log(f"全部完成: 共 {battles_done}/{battles_target} 场", "success")
            return {"success": True, "battles": battles_done, "target": battles_target,
                    "message": f"花种挑战完成 {battles_done}/{battles_target} 场"}
        except RuntimeError as e:
            if str(e) == "__STOP__":
                self._log("已手动停止", "warning")
                return {"success": False, "message": "已手动停止", "stopped": True}
            self._log(f"失败: {e}", "error")
            return {"success": False, "message": str(e)}
        except Exception as e:
            self._log(f"异常: {e}", "error")
            return {"success": False, "message": str(e)}

    def _phase_entry(self):
        """F3 → 点花种框 → OCR 判定命定花种数 → 点目标行传送按钮 → 等地图加载"""
        cfg = self._cfg
        self._ensure_front()
        self._log("按 F3 打开日常获得, 1 秒后点花种框")
        self._press("f3")
        self._wait(1.0)
        self._exp()
        self._click_roi("花种框")
        self._exp(1.2)

        # 判定命定花种数量(3 或 4)
        count = self._detect_flower_count()
        target = int(cfg["target_flower"])
        if target > count:
            raise RuntimeError(f"目标花种 #{target} 超出当前命定数量({count}), 请改小或检查面板")
        self._log(f"命定花种 {count} 个, 选择第 {target} 个: {self._flower_names().get(target, '?')}")

        # 直接点该行的传送按钮(两个传送框线性推算), 可选二次确认
        self._click_flower_teleport(target)
        if cfg.get("confirm_teleport"):
            self._exp()
            self._click_roi("点击地图传送按钮")
        self._log(f"已点传送, 等地图加载 {cfg['map_load_wait']}s")
        self._wait(float(cfg["map_load_wait"]))
        self._ensure_front()

    def _click_flower_teleport(self, target: int):
        """点目标花种行的传送按钮。

        用户只框了两个传送框(teleport_rows 指定它们是第几行, 默认第 1、2 行),
        按线性关系推算全部行的按钮纵向位置, x 取第一个传送框中心。"""
        rois = sorted([r for r in self._rois_map().values()
                       if r.name.startswith("传送框") and r.width > 0.001],
                      key=lambda r: r.top)
        if len(rois) < 2:
            raise RuntimeError("需要两个传送框 ROI(传送框/传送框二)才能推算各行按钮位置")
        idx1, idx2 = (int(x) for x in (self._cfg.get("teleport_rows") or [1, 3]))
        r1, r2 = rois[0], rois[1]
        pitch = (r2.top - r1.top) / (idx2 - idx1)
        top = r1.top + (target - idx1) * pitch
        if not (0.0 <= top <= 1.0) or target > 4:
            raise RuntimeError(f"第 {target} 行传送按钮位置推算越界(top={top:.3f})")
        self._log(f"传送按钮推算: 行{idx1}@{r1.top:.3f} 行{idx2}@{r2.top:.3f} "
                  f"→ 行{target}@{top:.3f}")
        info, _ = self._frame()
        from src.driver.mouse_controller import MouseController
        x = info.rect[0] + int(info.width * (r1.left + r1.width / 2))
        y = info.rect[1] + int(info.height * (top + r1.height / 2))
        mouse = MouseController()
        mouse.move_to(x, y)
        time.sleep(0.12 + 0.10 * (time.time() % 1))
        mouse.click('left', 0.05 + 0.05 * (time.time() % 1))

    def _detect_flower_count(self) -> int:
        """第 4 行过期时间与其余一致 → 4 个命定花种, 否则 3 个(用户规则)"""
        override = int(self._cfg.get("flower_count_override") or 0)
        if override:
            return override
        try:
            _, frame = self._frame()
            ref_text, ref_score = self._ocr_roi("花种剩余时间", frame)
            fourth_text, fourth_score = self._ocr_roi("判断几个命定花中", frame)
            digits = lambda s: re.sub(r"\D", "", str(s or ""))
            same_expiry = bool(digits(ref_text)) and digits(ref_text) == digits(fourth_text)
            # 兜底: 第 4 行名字区有字也视为 4 个
            name4 = None
            names = self._flower_name_rois()
            if len(names) >= 4:
                from src.utils.ocr_engine import read_best
                name4, _ = read_best(names[4][1].crop(frame))
            count = 4 if (same_expiry or (name4 and name4.strip())) else 3
            self._log(f"OCR 判定: 参考过期[{ref_text}] 第4行过期[{fourth_text}] "
                      f"第4行名[{name4}] → {count} 个命定花种", "info")
            return count
        except Exception as e:
            self._log(f"花种数量判定失败, 按 3 个处理: {e}", "warning")
            return 3

    def _flower_name_rois(self):
        """按画面纵向顺序收集花种名称行 ROI → [(序号, ROI), ...] (1-based)"""
        rois = [(r.name, r) for r in self._rois_map().values()
                if r.name.startswith(NAME_ROI_PREFIXES) and r.width > 0.001]
        rois.sort(key=lambda p: p[1].top)
        return list(enumerate(rois, start=1))

    def _flower_names(self) -> dict:
        """OCR 各行花种名称 → {序号: 文本}"""
        result = {}
        try:
            _, frame = self._frame()
            from src.utils.ocr_engine import read_best
            for idx, (_, roi) in self._flower_name_rois():
                text, _ = read_best(roi.crop(frame))
                result[idx] = (text or "").strip()
        except Exception:
            pass
        return result

    def _phase_battles(self, battles_target: int) -> int:
        cfg = self._cfg
        segments = self._parse_skills(cfg["skill_sequence"])
        battles_done = 0
        while battles_done < battles_target:
            if self._stopped():
                raise RuntimeError("__STOP__")
            self._ensure_front()
            if battles_done == 0:
                # 第一场: 走到花种面前 → 切精灵 → F 进挑战
                self._log(f"第 1/{battles_target} 场: 等 W 撞花种 → 挑战按钮")
                self._walk_to_challenge()
                self._exp()
                self._press(cfg["switch_pet_key"])
                self._exp()
                self._press("f")
                self._log(f"已切精灵[{cfg['switch_pet_key']}]并按 F 进挑战, 等进入战斗")
            else:
                # 后续场: 上一场结尾已点「再次挑战」, 直接等战斗开始
                self._log(f"第 {battles_done + 1}/{battles_target} 场: 等再次挑战进入战斗")
            self._wait_battle(True, timeout=30, what="进入战斗")
            refights = 0
            while True:
                self._fight(segments)
                state = self._wait_post_battle(20)
                if state == "ball":
                    break
                refights += 1
                if refights >= 3:
                    raise RuntimeError("战斗状态反复进出, 放弃本场")
                self._log("角标重新出现(战斗未打完), 继续施放技能", "warning")
            self._log(f"第 {battles_done + 1} 场战斗结束, 进丢球界面")
            is_last = (battles_done + 1 >= battles_target)
            self._phase_capture_and_again(click_again=not is_last)
            battles_done += 1
            self._log(f"进度: {battles_done}/{battles_target} 场", "success")
            if not is_last:
                self._exp(2.0)
        return battles_done

    def _wait_post_battle(self, timeout: float = 20.0) -> str:
        """战斗收尾等待: 角标消失后等丢球界面弹出(左角标分 < 0.55, 与挂机引擎同判据)。
        返回 'ball'(丢球界面就绪/超时兜底) 或 'refight'(角标又出现, 战斗没打完)"""
        deadline = time.time() + timeout
        while True:
            if self._stopped():
                raise RuntimeError("__STOP__")
            d = self._detect_raw()
            if d and d.get("configured"):
                if d.get("in_battle"):
                    return "refight"
                if float(d.get("left_score") or 0) < 0.55:
                    return "ball"
            if time.time() > deadline:
                self._log("等丢球界面超时, 按固定节奏继续", "warning")
                return "ball"
            self._stop_event_wait_small(0.5)

    def _phase_capture_and_again(self, click_again: bool = True):
        """丢球(免费球) → 等捕捉动画 → 点屏幕 → 点再次挑战"""
        cfg = self._cfg
        self._press(cfg["ball_key"])          # 丢球界面已在 _wait_post_battle 确认弹出
        self._log(f"已按[{cfg['ball_key']}]丢免费球, 等捕捉动画 {cfg['capture_wait']}s")
        self._wait(float(cfg["capture_wait"]))
        click_pos = cfg.get("click_after_capture") or [0.5, 0.35]
        info, _ = self._frame()
        from src.driver.mouse_controller import MouseController
        mouse = MouseController()
        mouse.move_to(info.rect[0] + int(info.width * float(click_pos[0])),
                      info.rect[1] + int(info.height * float(click_pos[1])))
        time.sleep(0.15)
        mouse.click('left', 0.07)
        self._exp()
        if not click_again:
            self._log("已是最后一场, 不再点再次挑战")
            return
        # OCR 等「再次挑战」出现 → 点击; 期间若已自动进入下一场战斗则不点
        self._roi("再次挑战按钮")  # 缺 ROI 快速失败(避免轮询里空转到超时)
        deadline = time.time() + 15
        while True:
            if self._stopped():
                raise RuntimeError("__STOP__")
            if self._in_battle():
                self._log("已回到战斗(下一场自动开始?), 跳过点再次挑战")
                return
            try:
                text, _ = self._ocr_roi("再次挑战按钮")
            except Exception:
                text = None  # 瞬时截图失败等, 继续轮询到超时
            if text and ("再次" in str(text) or "挑战" in str(text)):
                self._log(f"OCR 命中「再次挑战」({text}), 点击")
                break
            if time.time() > deadline:
                self._log(f"再次挑战 OCR 超时(最后读到[{text}]), 按标注位置直接点", "warning")
                break
            self._stop_event_wait_small()
        self._exp()
        self._click_roi("再次挑战按钮")

    def _walk_to_challenge(self):
        """等挑战按钮显现: 先 OCR 看(传送点很近通常直接可见), 没有才短按 W 蹭一步"""
        cfg = self._cfg
        deadline = time.time() + float(cfg["challenge_timeout"])
        self._roi("识别挑战")  # 缺 ROI 快速失败(避免轮询里空转到超时)
        from src.driver import human_input
        polls = 0
        while True:
            if self._stopped():
                raise RuntimeError("__STOP__")
            try:
                text, score = self._ocr_roi("识别挑战")
            except Exception:
                text = None  # 瞬时截图失败等, 继续轮询到超时
            if text and "挑战" in str(text):
                self._log(f"挑战按钮已显现(第 {polls} 次查看): [{text}]")
                return
            if time.time() > deadline:
                raise RuntimeError(f"等待挑战按钮超时({cfg['challenge_timeout']}s), 最后 OCR=[{text}]")
            polls += 1
            if polls % 2 == 0:
                # 两次没看到 → 短按 W 往前蹭一步
                human_input.key_down("w")
                try:
                    self._wait(float(cfg["walk_seconds"]))
                finally:
                    human_input.key_up("w")
                self._log(f"挑战未显现, 已 W 蹭一步(OCR=[{text}])")
            self._exp()

    def _wait_battle(self, want: bool, timeout: float, what: str):
        deadline = time.time() + timeout
        while True:
            if self._stopped():
                raise RuntimeError("__STOP__")
            if self._in_battle() == want:
                return
            if time.time() > deadline:
                raise RuntimeError(f"等待{what}超时({timeout}s)")
            self._stop_event_wait_small()

    def _fight(self, segments):
        """战斗中按技能序列分段轮换; 连续确认脱战(boss 死)才返回"""
        if not segments:
            segments = [["1"]]
        seg_idx = 0
        guard = 0
        while True:
            if self._stopped():
                raise RuntimeError("__STOP__")
            guard += 1
            if guard > 60:
                raise RuntimeError("战斗超时(60 段技能未结束)")
            for key in segments[seg_idx % len(segments)]:
                if self._battle_gone():
                    return
                self._press(key)
                self._exp()
            seg_idx += 1
            self._exp(1.2)

    @staticmethod
    def _parse_skills(seq: str):
        """'31,112,222' → [['3','1'], ['1','1','2'], ['2','2','2']]"""
        out = []
        for part in str(seq or "").replace("，", ",").split(","):
            keys = [ch for ch in part.strip() if ch.strip()]
            if keys:
                out.append(keys)
        return out

    def _stop_event_wait_small(self, t: float = 0.4):
        if self._stop_event is not None:
            self._stop_event.wait(t)
        else:
            time.sleep(t)
        if self._stopped():
            raise RuntimeError("__STOP__")
