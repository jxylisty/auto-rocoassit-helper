"""AppBridge Mix-in —— PVP 行动 / 悬浮窗控制 / 背包扫描 / 宠物技能查询与计算 / 资源同步 / 对战历史"""

import base64
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from src.gui.bridge_common import PROJECT_ROOT, SCREENSHOT_DIR


class PvpDataMixin:

    def pvp_act(self, action: str, delay: float = None) -> dict:
        """执行一条 PVP 操作命令 (AI 自玩用, MCP /local_api 调用)

        action 支持 (大小写不敏感):
          skill1~4           → 按数字键 1~4 出招
          energize           → 按 X 聚能(变化类操作, +5 能量)
          switch_1~6         → 按 E 打开换宠列表 → 数字 1~6 选宠 → Space 确认
          resonance          → 按 Q 打开共鸣背包 → 数字 1 选中 → 按 1 出招(愿力冲击)
        delay: 动作间基础间隔(秒), 默认 0.3
        """
        import time
        from src.driver import human_input

        a = (action or "").strip().lower()
        d = float(delay) if delay is not None else self._PVP_ACT_DELAY

        if a.startswith("skill"):
            n = a.replace("skill", "").strip()
            if n in ("1", "2", "3", "4"):
                human_input.press(n)
                return {"ok": True, "action": a, "key": n}

        if a == "energize":
            human_input.press("x")
            return {"ok": True, "action": a, "key": "x"}

        if a.startswith("switch_"):
            n = a.replace("switch_", "").strip()
            if n in ("1", "2", "3", "4", "5", "6"):
                human_input.press("e")
                time.sleep(d)
                human_input.press(n)
                time.sleep(max(0.05, d * 0.3))
                human_input.press("space")
                return {"ok": True, "action": a, "key": f"e → {n} → space",
                        "note": f"切换到第{n}个位置精灵"}

        if a == "resonance":
            # Q 打开共鸣背包 → 1 选中愿力冲击 → 按 1 出招
            human_input.press("q")
            time.sleep(d)
            human_input.press("1")
            time.sleep(max(0.05, d * 0.3))
            human_input.press("1")  # 按技能 1 释放愿力冲击
            return {"ok": True, "action": a, "keys": "q → 1 → 1",
                    "note": "共鸣愿力冲击"}

        return {"ok": False, "error": f"不支持的操作: {action}",
                "hint": "支持: skill1~4 / energize / switch_1~6 / resonance"}

    # ========================================
    # 6. PVP 对战助手 API
    # ========================================

    def set_pvp_float_window(self, window):
        """设置 PVP 对战悬浮窗引用 + 防自截

        window 允许为 None(打包版降级为"主窗口内浮层", 不需要独立窗口),
        此时只记录空引用, 后续 pvp_float_* 会各自返回"未创建"。
        """
        self._pvp_float_window = window
        if window is None:
            self._pvp_float_loaded = False
            return
        try:
            window.events.loaded += lambda: setattr(self, '_pvp_float_loaded', True)
        except Exception:
            pass
        # 防自截: Windows 10 2004+ WDA_EXCLUDEFROMCAPTURE (调试期间临时关闭)
        # (pywebview 6.x 没有 native_handle, 句柄要从 .native.Handle 取, 否则整段静默失效)
        def _exclude_from_capture():
            try:
                import ctypes
                hwnd = self._native_hwnd(window)
                if hwnd:
                    ctypes.windll.user32.SetWindowDisplayAffinity(int(hwnd), 0x00000000)
            except Exception:
                pass
        try:
            window.events.loaded += _exclude_from_capture
        except Exception:
            _exclude_from_capture()

    def pvp_search_pets(self, query: str = "") -> dict:
        from src.pvp import search_pets, get_all_pets_list
        if not query or not query.strip():
            pets = get_all_pets_list(pvp_filter=True)
            return {"success": True, "pets": pets[:50]}
        # PVP 选宠只提供高级形态(最终形态)及变体高级形态, I阶/II阶基础形态不可选
        results = search_pets(query.strip(), limit=30, pvp_filter=True)
        return {"success": True, "pets": [{
            "seq": r["seq"], "name": r["name"], "title": r.get("title", r["name"]),
            "types": r["types"],
        } for r in results]}

    def _save_bag_debug_shot(self, frame, tag: str = "bag_scan") -> str:
        """盘点现场截图落盘(供分析 ROI 对齐), 返回文件名"""
        try:
            import time as _t
            from src.utils.image_io import imwrite_unicode
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = SCREENSHOT_DIR / f"{tag}_{_t.strftime('%Y%m%d_%H%M%S')}.png"
            if imwrite_unicode(path, frame):
                self._enqueue_log(f"盘点现场截图已保存: {path.name}", "info")
                return path.name
        except Exception:
            pass
        return ""

    def _ensure_game_front_logged(self) -> bool:
        """把游戏窗口置前并验证(背包盘点/日常任务共用)。
        逻辑同 DailyRunner._ensure_game_front: bring_to_front → 验证 →
        AttachThreadInput 借前台线程输入状态再切 → 再验证。"""
        try:
            import win32gui
            import win32process
            from src.capture.window_capture import WindowCapture, find_window
            info = find_window(class_name="UnrealWindow") or find_window()
            if info is None:
                self._enqueue_log("未找到游戏窗口, 无法置顶", "warning")
                return False
            if win32gui.GetForegroundWindow() == info.hwnd:
                return True
            WindowCapture(info.hwnd).bring_to_front()
            time.sleep(0.4)
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
                time.sleep(0.3)
            ok = win32gui.GetForegroundWindow() == info.hwnd
            if ok:
                self._enqueue_log("游戏窗口已置顶", "info")
            else:
                self._enqueue_log("游戏窗口置顶失败, 截图/点击可能不准", "warning")
            return ok
        except Exception as e:
            self._enqueue_log(f"置顶异常: {e}", "warning")
            return False

    def bag_scan(self) -> dict:
        """背包盘点: 置顶游戏 → 抓一帧画面, 按网格识别球种+数量, 与上次快照做减法"""
        try:
            from src.perception.bag_scanner import BagScanner
            scanner = BagScanner()
            if not scanner.available():
                return {"success": False, "message": "背包 ROI 未配置(需要 背包.json 的 roi_1/roi_2/背包整体ocr)"}
            # mss 是屏幕级抓图: 游戏被遮挡时截到的是遮挡窗口, 先置顶再截
            self._ensure_game_front_logged()
            time.sleep(0.5)   # 等渲染稳定, 避免抓到窗口切换过渡帧
            info, frame = self._capture_frame()
            res = scanner.scan_and_diff(frame)
            res["success"] = True
            res["debug_shot"] = self._save_bag_debug_shot(frame)
            g = scanner.grid_size()
            res["grid"] = {"cols": g["cols"], "rows": g["rows"],
                           "cells": g["cols"] * g["rows"]}
            return res
        except Exception as e:
            return {"success": False, "message": str(e)}

    def bag_open(self) -> dict:
        """置顶游戏 → Esc → 点击背包按钮 → 打开确认 → 确认后才点咕噜球筛选
        (内核级, 4秒防抖)。打开失败返回明确错误, 不静默吞掉。"""
        try:
            from src.perception.bag_scanner import open_bag_click, BAG_OPEN_DEBOUNCE
            now = time.time()
            if now - getattr(self, "_bag_open_last", 0.0) < BAG_OPEN_DEBOUNCE:
                return {"success": False, "message": "背包打开过于频繁(防抖), 请稍候"}
            self._bag_open_last = now
            # Esc 只在游戏有焦点时有效: 先置顶(点击链依赖游戏在前台)
            self._ensure_game_front_logged()
            time.sleep(0.4)
            ok = open_bag_click()
            if not ok:
                return {"success": False,
                        "message": "打开背包失败: 菜单→背包按钮点击链未能打开背包界面, 请手动打开背包后用「直接盘点」"}
            return {"success": True, "message": "已打开背包"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def bag_open_and_scan(self) -> dict:
        """打开背包(含重试+打开确认) → 盘点 → 返回结果。
        打开失败时直接报错返回, 不在错误界面上空扫(根治'识别出一堆乱球')"""
        opened = self.bag_open()
        if not opened.get("success"):
            return {"success": False,
                    "message": opened.get("message") or "打开背包失败, 请手动打开背包后再试"}
        res = self.bag_scan()
        if res.get("success"):
            res["bag_opened"] = True
        return res

    def pvp_get_pet(self, seq: int, title: str = None) -> dict:
        from src.pvp import get_pet_by_seq
        seq = int(seq)
        pet = get_pet_by_seq(seq, title=title)
        if not pet:
            return {"success": False, "message": f"精灵 #{seq} 不存在"}
        return {"success": True, "pet": pet}

    def pvp_search_skills(self, query: str = "") -> dict:
        from src.pvp import search_skills
        if not query or not query.strip():
            return {"success": True, "skills": []}
        results = search_skills(query.strip(), limit=30)
        return {"success": True, "skills": [{
            "name": r["name"], "type": r["type"], "attr": r["attr"],
            "power": r["power"], "consume": r["consume"],
        } for r in results]}

    def pvp_calc_vs(self, atk_seq: int, def_seq: int, skill_name: str,
                    atk_ivs: dict | None = None, def_ivs: dict | None = None) -> dict:
        from src.pvp import calc_pet_vs_pet
        atk_ivs = atk_ivs or {}
        def_ivs = def_ivs or {}
        result = calc_pet_vs_pet(int(atk_seq), int(def_seq), str(skill_name),
                                 attacker_ivs=atk_ivs, defender_ivs=def_ivs)
        if not result:
            return {"success": False, "message": "计算失败，请检查精灵和技能是否存在"}
        return {"success": True, **result}

    def pvp_get_all_pets(self) -> dict:
        from src.pvp import get_all_pets_list
        return {"success": True, "pets": get_all_pets_list()}

    def pvp_get_all_skills(self) -> dict:
        from src.pvp import get_all_skill_names
        names = get_all_skill_names()
        return {"success": True, "skills": [{"name": n} for n in names]}

    def pvp_calc_quick(self, atk_val: int, def_val: int, power: int,
                       skill_type: str = "物攻", skill_attr: str = "普通",
                       atk_attrs: list = None, def_attrs: list = None) -> dict:
        """快速伤害计算（不选精灵，直接输入数值）"""
        from src.pvp import get_attr_multiplier, normalize_attr
        atk_attrs = atk_attrs or ["普通"]
        def_attrs = def_attrs or ["普通"]
        atk_attrs = [normalize_attr(a) for a in atk_attrs]
        def_attrs = [normalize_attr(a) for a in def_attrs]

        # 属性倍率
        attr_mult = get_attr_multiplier(skill_attr, def_attrs)
        # 本系加成
        same_type = 1.25 if skill_attr in atk_attrs else 1.0
        # 伤害公式
        damage = round((atk_val / def_val) * 0.9 * power * same_type * attr_mult, 1)

        return {
            "success": True,
            "damage": damage,
            "atkUsed": atk_val,
            "defUsed": def_val,
            "sameTypeBonus": same_type,
            "attrMultiplier": attr_mult,
            "hits": 1,
        }

    def pvp_calc_panels(self, seq: int, high_ivs: list = None, iv_value: int = 10,
                        nature_up: str = None, nature_down: str = None) -> dict:
        """计算精灵面板：3项高IV + 性格修正"""
        from src.pvp.damage_calculator import calculate_all_panels
        from src.pvp.pet_loader import get_pet_race
        race = get_pet_race(int(seq))
        if not race:
            return {"success": False, "message": f"精灵 #{seq} 不存在"}
        high_ivs = high_ivs or ["attack", "mattack", "speed"]
        ivs = {}
        for stat in ["hp", "attack", "mattack", "defense", "mdefense", "speed"]:
            ivs[stat] = int(iv_value) if stat in high_ivs else 0
        panels = calculate_all_panels(race, ivs, nature_up=nature_up, nature_down=nature_down)
        return {"success": True, "panels": panels, "race": race}

    def pvp_get_pet_skills_full(self, seq: int) -> dict:
        """获取精灵全部技能（含完整数据）"""
        from src.pvp.pet_loader import get_pet_by_seq
        from src.pvp.skill_loader import get_skill
        pet = get_pet_by_seq(int(seq))
        if not pet:
            return {"success": False, "message": f"精灵 #{seq} 不存在"}
        skill_items = pet.get("skills") or []
        skills = []
        for s in skill_items:
            skill = get_skill(s["name"])
            if skill:
                skills.append({"name": s["name"], "level": s.get("level", "?"),
                               "type": skill.get("type", "?"), "attr": skill.get("attr", "?"),
                               "power": skill.get("power", "0"), "consume": skill.get("consume", "0"),
                               "describe": skill.get("describe", "")})
        return {"success": True, "skills": skills, "petName": pet.get("name", ""),
                "petTypes": pet.get("types", [])}

    def pvp_get_pet_preset(self, seq: int) -> dict:
        """智能预设（与 app 的 buildOpponentFullConfig 一致）：
        主攻项 + 速度 + HP，性格 主攻+/副攻-"""
        from src.pvp.pet_loader import get_pet_race
        race = get_pet_race(int(seq))
        if not race:
            return {"success": False, "message": f"精灵 #{seq} 不存在"}
        atk = race.get("attack", 0)
        matk = race.get("mattack", 0)
        prefer = "mattack" if matk >= atk else "attack"
        nature_up = "魔攻" if prefer == "mattack" else "攻击"
        nature_down = "攻击" if prefer == "mattack" else "魔攻"
        return {"success": True,
                "high_ivs": [prefer, "speed", "hp"],
                "iv_value": 10, "nature_up": nature_up,
                "nature_down": nature_down, "race": race}

    def pvp_calc_all_skills(self, atk_seq: int, def_seq: int,
                            atk_high_ivs: list = None, atk_iv_value: int = 10,
                            def_high_ivs: list = None, def_iv_value: int = 10,
                            atk_nature_up: str = None, atk_nature_down: str = None,
                            def_nature_up: str = None, def_nature_down: str = None) -> dict:
        """对防御方计算攻击方全部技能的伤害，按克制排序"""
        from src.pvp.damage_calculator import calculate_all_panels, calculate_damage_full
        from src.pvp.pet_loader import get_pet_race, get_pet_by_seq, get_pet_types
        from src.pvp.skill_loader import get_skill
        from src.pvp.type_chart import get_attr_multiplier, normalize_attr
        from src.pvp.pvp_rules import DAMAGE

        atk_seq, def_seq = int(atk_seq), int(def_seq)
        atk_race = get_pet_race(atk_seq)
        def_race = get_pet_race(def_seq)
        if not atk_race or not def_race:
            return {"success": False, "message": "精灵不存在"}

        atk_pet = get_pet_by_seq(atk_seq)
        def_pet = get_pet_by_seq(def_seq)
        atk_high_ivs = atk_high_ivs or ["attack", "mattack", "speed"]
        def_high_ivs = def_high_ivs or ["attack", "mattack", "speed"]

        def _build_ivs(high_ivs, val):
            ivs = {}
            for s in ["hp", "attack", "mattack", "defense", "mdefense", "speed"]:
                ivs[s] = int(val) if s in high_ivs else 0
            return ivs

        atk_panels = calculate_all_panels(atk_race, _build_ivs(atk_high_ivs, atk_iv_value),
                                          nature_up=atk_nature_up, nature_down=atk_nature_down)
        def_panels = calculate_all_panels(def_race, _build_ivs(def_high_ivs, def_iv_value),
                                          nature_up=def_nature_up, nature_down=def_nature_down)

        atk_types = get_pet_types(atk_seq)
        def_types = get_pet_types(def_seq)
        pet_skills = (atk_pet.get("skills") or []) if atk_pet else []

        results = []
        for s in pet_skills:
            sk = get_skill(s["name"])
            if not sk:
                continue
            stype = str(sk.get("type", "")).strip()
            sattr = str(sk.get("attr", "")).replace("系", "").strip()
            spower = int(sk.get("power", 0)) if str(sk.get("power", "0")).isdigit() else 0
            is_dmg = stype in ("物攻", "魔攻")

            if not is_dmg:
                results.append({"name": s["name"], "type": stype, "attr": sattr,
                                "power": 0, "consume": sk.get("consume", "?"),
                                "isDamage": False, "attrMultiplier": 0,
                                "minDamage": 0, "maxDamage": 0, "level": s.get("level", "?")})
                continue

            attr_mult = get_attr_multiplier(sattr, def_types)
            same_type = DAMAGE["sameTypeBonus"] if normalize_attr(sattr) in [normalize_attr(t) for t in atk_types] else 1.0

            # MIN: atk_level=0, MAX: atk_level=+3
            dmin = calculate_damage_full(atk_panels, def_panels, spower, stype, sattr,
                                         atk_types, def_types, atk_level=0)
            dmax = calculate_damage_full(atk_panels, def_panels, spower, stype, sattr,
                                         atk_types, def_types, atk_level=3)
            results.append({"name": s["name"], "type": stype, "attr": sattr,
                            "power": spower, "consume": sk.get("consume", "?"),
                            "isDamage": True, "attrMultiplier": attr_mult,
                            "minDamage": round(dmin["damage"], 1),
                            "maxDamage": round(dmax["damage"], 1),
                            "sameTypeBonus": same_type, "level": s.get("level", "?")})

        # ---- 玩家自定义筛选 ----
        # 1) 排除「升龙咆哮」 2) 威力<=60 的攻击技能剔除(龙系豁免)
        # 3) 按种族物攻/魔攻只显示匹配类型的攻击技能(双刀全显示)
        try:
            pa = int(atk_race.get("attack", 0) or 0)
        except (TypeError, ValueError):
            pa = 0
        try:
            ma = int(atk_race.get("mattack", 0) or 0)
        except (TypeError, ValueError):
            ma = 0
        allowed_types = ("物攻", "魔攻") if pa == ma else             (("物攻",) if pa > ma else ("魔攻",))

        def _keep(r):
            if r["name"] == "升龙咆哮":
                return False
            if not r["isDamage"]:
                return True  # 状态/变化技能保留
            if r["power"] <= 60 and r["attr"] != "龙":
                return False
            return r["type"] in allowed_types

        results = [r for r in results if _keep(r)]

        # 排序：克制→普通→抵抗→状态，同组内伤害降序
        def _sort_key(r):
            if not r["isDamage"]: return (3, 0)
            m = r["attrMultiplier"]
            if m >= 2: return (0, -r["maxDamage"])
            if m >= 1: return (1, -r["maxDamage"])
            return (2, -r["maxDamage"])
        results.sort(key=_sort_key)

        from src.pvp.damage_calculator import calculate_resonance_impact_damages
        resonance_data = calculate_resonance_impact_damages(
            enemy_panel=def_panels,
            self_panel=atk_panels,
            enemy_types=def_types,
            self_types=atk_types,
            self_current_hp=int(atk_panels.get("hp", 450))
        )

        return {"success": True, "atkPanels": atk_panels, "defPanels": def_panels,
                "atkRace": atk_race, "defRace": def_race, "atkTypes": atk_types,
                "defTypes": def_types, "atkName": atk_pet.get("name", "") if atk_pet else "",
                "defName": def_pet.get("name", "") if def_pet else "",
                "skills": results,
                "resonance_impact": resonance_data,
                "mySpeed": round(atk_panels.get("speed", 0)),
                "enemySpeed": round(def_panels.get("speed", 0)),
                "speedResult": "我方先手" if atk_panels.get("speed", 0) > def_panels.get("speed", 0) else (
                    "敌方先手" if atk_panels.get("speed", 0) < def_panels.get("speed", 0) else "速度相同")}

    def pvp_recognize(self) -> dict:
        """捕获游戏画面 → 识别精灵列表（OCR+图像）
        默认裁剪游戏窗口左侧 40%（PVP 精灵列表区域）"""
        import tempfile, subprocess, json as _json
        try:
            # 1. 截图
            info = self._find_game_window()
            if not info:
                return {"success": False, "message": "未找到游戏窗口"}
            left, top, right, bottom = info.rect
            w, h = right - left, bottom - top
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(left, top, right, bottom))

            # 2. 裁剪左侧（PVP 精灵列表区域，默认左 40%）
            crop_left = 0
            crop_right = int(w * 0.4)
            img = img.crop((crop_left, 0, crop_right, h))

            tmp = Path(tempfile.gettempdir()) / "pvp_capture.png"
            img.save(str(tmp))

            # 3. 识别
            lib_dir = PROJECT_ROOT / "src" / "pvp" / "lib"
            result = subprocess.run(
                [sys.executable, str(lib_dir / "pvp_lib.py"), "recognize", str(tmp)],
                capture_output=True, text=True, timeout=120,
                cwd=str(lib_dir),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            if result.returncode != 0:
                return {"success": False, "message": f"识别失败: {result.stderr[:200]}"}

            data = _json.loads(result.stdout) if result.stdout.strip() else {}
            pets = data.get("pets", data.get("results", []))
            return {"success": True, "pets": pets, "file": str(tmp)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def resource_sync(self) -> dict:
        """从官方 API 一键同步最新图鉴/技能数据与立绘图标 (真下载, 全量约几分钟)。
        后台线程执行: 前端立即返回启动成功, 进度通过日志抽屉实时回流;
        完成后再推送一条汇总日志。重复点击防抖。"""
        try:
            if getattr(self, "_resource_syncing", False):
                return {"success": False, "message": "同步正在进行中, 请勿重复触发"}
            self._resource_syncing = True

            def _finish(res):
                self._resource_syncing = False
                if res.get("success"):
                    self._enqueue_log("✅ " + str(res.get("message", "资源同步完成")), "success")
                else:
                    self._enqueue_log("❌ 资源同步失败: " + str(res.get("message", "")), "error")

            def _worker():
                from src.pvp.resource_updater import ResourceUpdater
                updater = ResourceUpdater(
                    on_progress=lambda msg, p: self._enqueue_log(msg, "info"))
                try:
                    res = updater.sync()
                except Exception as e:
                    res = {"success": False, "message": str(e)}
                _finish(res)

            threading.Thread(target=_worker, daemon=True, name="ResourceSync").start()
            self._enqueue_log("🚀 官方资源同步已启动: 全量图鉴/技能/立绘下载中, 进度见日志…", "info")
            return {"success": True,
                    "message": "同步已启动(后台执行), 进度请在日志抽屉查看",
                    "async": True}
        except Exception as e:
            self._resource_syncing = False
            self._enqueue_log(f"资源同步失败: {e}", "error")
            return {"success": False, "message": str(e)}

    def resource_get_stats(self) -> dict:
        """获取当前本地收录的官方图鉴与图标统计"""
        try:
            web_img = PROJECT_ROOT / "src" / "gui" / "web" / "assets" / "img"
            pet_count = len(list((web_img / "pets").glob("*.webp"))) if (web_img / "pets").exists() else 0
            skill_count = len(list((web_img / "skills").glob("*.webp"))) if (web_img / "skills").exists() else 0
            icon_count = len(list((web_img / "icons").glob("*.webp"))) if (web_img / "icons").exists() else 0
            return {
                "success": True,
                "stats": {
                    "pets": pet_count,
                    "skills": skill_count,
                    "icons": icon_count,
                }
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    def pvp_float_toggle(self) -> dict:
        """显示合并悬浮窗并切到 PVP 标签(与挂机悬浮窗同一窗口)"""
        gate = self._auth_gate()
        if gate:
            return gate
        if not getattr(self, "_pvp_float_window", None):
            return {"success": False, "message": "PVP悬浮窗未创建"}
        try:
            result = self.widget_toggle()
            visible = bool(result.get("visible"))
            # 推送闸门与 widget 显隐状态同步(此前 _pvp_float_visible 从未置 True,
            # 引擎识别正常但数据永远不推悬浮窗)
            self._pvp_float_visible = visible
            if visible:
                try:
                    self._pvp_float_window.evaluate_js('switchTab("pvp")')
                except Exception:
                    pass
            return {"success": True, "visible": visible}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def pvp_float_update(self, data: dict) -> dict:
        if not getattr(self, "_pvp_float_window", None):
            return {"success": False, "message": "PVP悬浮窗未创建"}
        if not getattr(self, "_widget_visible", False):
            return {"success": False, "message": "悬浮窗未打开"}
        if not getattr(self, "_pvp_float_loaded", False):
            return {"success": False, "message": "悬浮窗加载中，请稍后"}
        try:
            js = f"updatePVPData({json.dumps(data, ensure_ascii=False)})"
            self._pvp_float_window.evaluate_js(js)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def pvp_get_asset(self, asset_type: str, key: str) -> dict:
        """返回任意素材的 base64 编码
        asset_type: 'pet' | 'skill' | 'trait' | 'icon'
        key: 精灵序号(如'1') | 技能名 | 特性序号 | 属性英文名(如'fire')
        """
        import base64

        assets_dir = PROJECT_ROOT / "src" / "pvp" / "data" / "assets"
        index_map = {"pet": "pet_index.json", "skill": "skill_index.json", "icon": "icon_map.json"}

        if asset_type == "pet":
            idx_path = assets_dir / "pet_index.json"
            if not idx_path.exists():
                return {"success": False, "message": "精灵头像索引不存在"}
            with open(idx_path, "r", encoding="utf-8") as f:
                pet_idx = json.load(f)
            filename = pet_idx.get(str(int(key)))
            if not filename:
                return {"success": False, "message": f"精灵 #{key} 无头像"}
            img_path = assets_dir / "pets" / filename

        elif asset_type == "skill":
            idx_path = assets_dir / "skill_index.json"
            if not idx_path.exists():
                return {"success": False, "message": "技能图标索引不存在"}
            with open(idx_path, "r", encoding="utf-8") as f:
                skill_idx = json.load(f)
            filename = skill_idx.get(key)
            if not filename:
                return {"success": False, "message": f"技能 '{key}' 无图标"}
            img_path = assets_dir / "skills" / filename

        elif asset_type == "trait":
            img_path = assets_dir / "traits" / f"{key}.webp"
            if not img_path.exists():
                return {"success": False, "message": f"特性 #{key} 无图标"}

        elif asset_type == "icon":
            img_path = assets_dir / "icons" / f"{key}.webp"
            if not img_path.exists():
                return {"success": False, "message": f"属性图标 '{key}' 不存在"}

        else:
            return {"success": False, "message": f"未知素材类型: {asset_type}"}

        if not img_path.exists():
            return {"success": False, "message": f"素材文件不存在"}

        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")

        return {"success": True, "image": f"data:image/webp;base64,{b64}", "filename": img_path.name}


    # ========================================
    # 7. 天梯战报与 ELO 分析 API
    # ========================================

    def pvp_get_history(self, limit: int = 50, offset: int = 0, filter_result: str = "ALL") -> dict:
        """分页获取天梯历史战报"""
        from src.pvp.history_db import get_history_db
        db = get_history_db()
        history = db.get_history(limit=int(limit), offset=int(offset), filter_result=str(filter_result))
        return {"success": True, "history": history}

    def pvp_get_history_stats(self) -> dict:
        """获取大盘统计和 ELO 克制遭遇分析"""
        from src.pvp.history_db import get_history_db
        db = get_history_db()
        stats = db.get_summary_stats()
        elo = db.get_elo_counter_stats()
        return {"success": True, "stats": stats, "elo": elo}

    def pvp_record_match(self, match_data: dict) -> dict:
        """手动或自动沉淀一笔战报"""
        from src.pvp.history_db import get_history_db
        db = get_history_db()
        row_id = db.record_match(
            result=match_data.get("result", "WIN"),
            my_team=match_data.get("my_team", []),
            enemy_team=match_data.get("enemy_team", []),
            duration_sec=int(match_data.get("duration_sec", 0)),
            rank_tier=match_data.get("rank_tier", "天梯排位"),
            is_crush=match_data.get("is_crush"),
            notes=match_data.get("notes", "")
        )
        return {"success": True, "id": row_id}

    def pvp_clear_history(self) -> dict:
        """清空历史战报"""
        from src.pvp.history_db import get_history_db
        get_history_db().clear_all()
        return {"success": True}

    def pvp_generate_mock_history(self, count: int = 15) -> dict:
        """生成演示战报"""
        from src.pvp.history_db import get_history_db
        get_history_db().generate_mock_data(int(count))
        return {"success": True}
