"""AppBridge Mix-in —— 战斗引擎 / PVP 采集与观察 / 状态沿消费 / PVP 主循环 / 本地对战 API"""

import json
import sys
import threading
import time
from pathlib import Path
from src.gui.bridge_common import PROJECT_ROOT, DEV_MODE


class PvpEngineMixin:

    # ========================================
    # 战斗引擎 API
    # ========================================

    def engine_start(self, dry_run: bool = False, params: dict | None = None) -> dict:
        if self.engine.running:
            return {"success": False, "message": "引擎已在运行"}
        gate = self._auth_gate()
        if gate:
            return gate
        auto_stopped = self._stop_conflicting_modes("engine")
        overrides = self._parse_engine_params(params or {})
        self.engine.dry_run = bool(dry_run)
        ok = self.engine.start(overrides or None)
        if ok:
            self.auto_minimize_and_show_widget()
            if params:
                # 参数同步持久化到 settings.yaml
                self._save_engine_settings(params)
        return {"success": ok, "auto_stopped": auto_stopped}

    def engine_stop(self) -> dict:
        self.engine.stop()
        return {"success": True}

    # ========================================
    # PVP 数据采集器(本体集成版)
    # ========================================

    def pvp_collector_start(self) -> dict:
        """启动自动采集线程(每2秒一轮,输出到项目 output/)"""
        if not DEV_MODE:
            return {"success": False, "message": "数据采集仅开发者模式可用"}
        if getattr(self, "_collector_thread", None) and self._collector_thread.is_alive():
            return {"success": False, "message": "采集器已在运行"}
        try:
            from src.pvp.data_collector import PvpDataCollector
            self._collector = PvpDataCollector(output_dir=PROJECT_ROOT / "output")
        except Exception as e:
            return {"success": False, "message": f"初始化失败: {e}"}
        self._collector_stop = threading.Event()
        self._collector_thread = threading.Thread(
            target=self._collector_loop, daemon=True, name="PvpCollector")
        self._collector_thread.start()
        self._enqueue_log("PVP 数据采集器已启动(输出 output/)", "success")
        return {"success": True}

    def _collector_loop(self):
        last_status = ""
        while not self._collector_stop.is_set():
            try:
                status = self._collector.auto_collect()
                # 只在"有产出/状态变化"时写日志,避免刷屏
                if status != last_status and ("已采集" in status or "失败" in status or "不可见" in status):
                    self._enqueue_log(f"[采集] {status}", "info")
                last_status = status
            except Exception as e:
                self._enqueue_log(f"[采集] 异常: {e}", "error")
            self._collector_stop.wait(2.0)

    def pvp_collector_stop(self) -> dict:
        if not getattr(self, "_collector_stop", None):
            return {"success": True, "message": "未在运行"}
        self._collector_stop.set()
        summary = self._collector.summary()
        self._enqueue_log(f"PVP 数据采集器已停止: {summary}", "warning")
        return {"success": True, "summary": summary}

    def pvp_collector_status(self) -> dict:
        running = bool(getattr(self, "_collector_thread", None) and self._collector_thread.is_alive())
        stats = getattr(self, "_collector", None).stats if running else {}
        return {
            "running": running,
            "auto_saved": stats.get("auto_saved", 0),
            "fail_saved": stats.get("fail_saved", 0),
            "manual_saved": stats.get("manual_saved", 0),
            "pets": len(stats.get("battles_seen", ())),
        }

    def pvp_collector_manual(self) -> dict:
        """手动截图一张(战备阶段等)"""
        if not getattr(self, "_collector", None):
            try:
                from src.pvp.data_collector import PvpDataCollector
                self._collector = PvpDataCollector(output_dir=PROJECT_ROOT / "output")
            except Exception as e:
                return {"success": False, "message": str(e)}
        try:
            path = self._collector.save_manual("界面手动")
            if path:
                self._enqueue_log(f"[采集] 已保存 {Path(path).name}", "success")
                return {"success": True, "path": path}
            return {"success": False, "message": "游戏窗口不可见"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def engine_status(self) -> dict:
        """获取悬浮窗战情状态（聚合挂机引擎与自动丢球助手）"""
        if self.engine.running:
            return self.engine.get_status()

        # 如果当前是普通丢球/轰炸机/自动技能在运行
        tool = self.tool
        is_tool_running = tool.running or tool.bomber_running or tool.skill_running
        if is_tool_running:
            state = getattr(tool, "current_state", "throwing")
            detail = getattr(tool, "state_detail", "")
            if not detail:
                if tool.running:
                    detail = f"普通丢球: 已丢 {tool.normal_count} 球"
                elif tool.bomber_running:
                    detail = f"轰炸机: 已丢 {tool.bomber_count} 球"
                elif tool.skill_running:
                    detail = f"自动技能: 已按 {tool.skill_count} 次"

            return {
                "running": True,
                "dry_run": False,
                "mode_type": "tool",
                "state": state,
                "detail": detail,
                "battles_done": getattr(tool, "battles_escaped", 0),
                "catch_attempts": tool.normal_count + tool.bomber_count,
                "catches": 0,
                "skills_used": tool.skill_count,
                "catch_hp": None,
                "enemy_name": getattr(tool, "enemy_name", None),
                "enemy_hp": getattr(tool, "enemy_hp", None),
                "shiny_alert": (self.engine.get_status() or {}).get("shiny_alert"),
            }

        # 默认返回基础状态
        st = self.engine.get_status()
        if getattr(tool, "battles_escaped", 0) > 0 and st.get("battles_done", 0) == 0:
            st["battles_done"] = tool.battles_escaped
        # 观察模式战情(引擎/工具都没跑时,悬浮窗也能看到当前战斗)
        w = getattr(self, "_watch", None)
        if w and w.get("in_battle"):
            st["enemy_name"] = w.get("enemy_name")
            st["enemy_hp"] = w.get("enemy_hp")
            st["watching"] = True
        return st

    # ========================================
    # 观察模式(被动监视战斗,喂给挂机悬浮窗)
    # ========================================

    def _watch_loop(self):
        """引擎/工具空闲时,每 2.5 秒轻量识别一帧,更新观察战情。

        首次检测到战斗时做一次全量识别拿精灵名,之后走轻量(只读血量)。
        """
        from src.perception.vision_pipeline import VisionPipeline

        while not self._stop_event.is_set():
            try:
                # 引擎/工具/PVP实时/调试台实时任一在跑 → 让位,不做重复识别
                busy = (self.engine.running or self._pvp_running
                        or self._live_running or self.tool.running
                        or self.tool.bomber_running or self.tool.skill_running)
                if busy:
                    self._watch = None
                    if self._stop_event.wait(2.0):
                        break
                    continue

                info, frame = self._live_capture_frame()
                if self._watch_pipeline is None:
                    self._watch_pipeline = VisionPipeline()

                if self._watch_started.is_set():
                    snap = self._watch_pipeline.analyze(frame, light=True)
                else:
                    snap = self._watch_pipeline.analyze(frame, light=False)

                battle = snap.raw.get("battle", {})
                if not battle.get("in_battle"):
                    if self._watch_started.is_set():
                        self._watch = None
                        self._watch_started.clear()
                    if self._stop_event.wait(2.5):
                        break
                    continue

                if not self._watch_started.is_set():
                    # 刚进战斗: 全量识别拿名字
                    full = self._watch_pipeline.analyze(frame, light=False)
                    name = full.enemy_name.value
                    hp = full.enemy_hp.value if full.enemy_hp.value is not None else snap.enemy_hp.value
                    self._watch_started.set()
                else:
                    name = getattr(self, "_watch_name", None)
                    hp = snap.enemy_hp.value

                self._watch = {"in_battle": True, "enemy_name": name, "enemy_hp": hp}
                if name:
                    self._watch_name = name
            except Exception:
                pass  # 窗口不可见等静默重试
            if self._stop_event.wait(2.5):
                break

    def _start_watch_loop(self):
        if not getattr(self, "_watch_thread", None) or not self._watch_thread.is_alive():
            self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True, name="BattleWatch")
            self._watch_thread.start()

    # ========================================
    # PVP 实时识别引擎
    # ========================================

    def _round_logger_tick(self, data: dict, result) -> None:
        """回合日志: in_battle 状态切换开/关对局文件, 每帧 diff 事件落盘"""
        logger = getattr(self, "_round_logger", None)
        if logger is None:
            from src.pvp.round_logger import RoundLogger
            logger = RoundLogger()
            self._round_logger = logger
        if result.in_battle:
            if logger._closed or not logger.file:
                logger.start_match(result.player_name or "", result.enemy_name or "")
                self._enqueue_log(f"[回合日志] 开局: {logger.match_id}", "info")
            # 抓包数据源带权威回合号(0x131A); OCR 的 PvpResult 无该字段, getattr 得 0 → 不生效
            set_round = getattr(logger, "set_authoritative_round", None)
            round_no = getattr(result, "round_no", 0) or 0
            if set_round and round_no > 0:
                set_round(round_no, getattr(self, "_pvp_source", "capture"))
            logger.update(data)
        else:
            if not logger._closed:
                out = logger.close_match(final_snapshot=data)
                if out:
                    rec = out.get("recorded")
                    self._enqueue_log(
                        f"[回合日志] 收尾 {out['duration_sec']}s"
                        + (f", 自动记录战报: {rec}" if rec else "(无胜负判定, 未写战报)"),
                        "info")

    def _merge_ocr_skill_bar(self, result, pipeline) -> None:
        """抓包源(rkpp)下: 我方技能栏 = 槽位ID→wiki权威名 为主, OCR 兜底。

        2026-09-26 真机对局实锤: 包内启发式名与真实技能组 4/4 全错(串成
        别的宠的技能), 而槽位ID→wiki名 3/4 精确命中玩家实际技能组。
        优先级: 槽位ID 的 校准表→wiki 解析名 → OCR(帧读) → 上一帧缓存。
        4 槽 wiki 名全齐时直接跳过截图 OCR(省每帧最多 3s 的 RapidOCR,
        技能栏也不再依赖游戏窗口可见)。OCR 读数仅用于补 wiki 缺口并写入
        校准表; 新一局开局(battle_start)清缓存。
        """
        if getattr(result, "battle_start", False):
            self._ocr_skill_cache = None
        bar_entries = sorted(
            (getattr(result, "_rkpp_bar_entries", None) or []),
            key=lambda e: (e.get("pos") if isinstance(e.get("pos"), int) else 99))

        # 1) 槽位 ID → 校准表/wiki 权威名(无需截图)
        from src.pvp.skill_ids import resolve_skill_name as _rsn
        from src.pvp.skill_calibration import record as cal_record
        wiki_by_pos: dict = {}
        gap_pairs: dict = {}
        for ent in bar_entries:
            pos = ent.get("pos")
            sid = ent.get("skill_id")
            if not sid or not isinstance(pos, int) or not (1 <= pos <= 4):
                continue
            nm = _rsn(sid)
            if nm:
                wiki_by_pos[pos] = nm

        # 2) 有缺口才截图 OCR(读 HUD 槽位名兜底, 顺带补校准表)
        ocr_skills: list = []
        if len(wiki_by_pos) < 4:
            info = self._find_game_window()
            if info:
                left, top, right, bottom = info.rect
                w, h = right - left, bottom - top
                if w >= 50 and h >= 50:
                    frame = self._get_fast_capture().capture(rect=(left, top, w, h))
                    if frame is not None and frame.size > 0:
                        ocr_skills = pipeline.read_skill_bar(frame)
                        for ent in bar_entries:
                            pos = ent.get("pos")
                            sid = ent.get("skill_id")
                            if not sid or not isinstance(pos, int) or not (1 <= pos <= 4):
                                continue
                            if sid in wiki_by_pos or str(sid) in wiki_by_pos:
                                continue
                            ocr_nm = ocr_skills[pos - 1] if pos - 1 < len(ocr_skills) else ""
                            if ocr_nm:
                                gap_pairs[str(sid)] = ocr_nm
                        if gap_pairs:
                            try:
                                changed = cal_record(gap_pairs, source="ocr_slot")
                                if changed:
                                    self._enqueue_log(
                                        "[技能校准] wiki 缺口补齐: " +
                                        ", ".join(f"{c['id']}={c['name']}" for c in changed[:4]),
                                        "info")
                            except Exception:
                                pass

        # 3) 逐槽合成: wiki 权威名 → 本帧 OCR → 上一帧缓存 → 空
        cache = getattr(self, "_ocr_skill_cache", None)
        merged = []
        for i in range(4):
            wiki_nm = wiki_by_pos.get(i + 1, "")
            ocr_nm = ocr_skills[i] if i < len(ocr_skills) else ""
            if wiki_nm:
                merged.append(wiki_nm)
            elif ocr_nm:
                merged.append(ocr_nm)
            elif cache and i < len(cache) and cache[i]:
                merged.append(cache[i])
            else:
                merged.append("")
        if not any(merged):
            self._apply_ocr_skill_cache(result)
            return
        self._ocr_skill_cache = merged
        result.skills = list(merged)

        # ===== 能量: 包内无此数据 → ROI OCR(每 3 帧一次), 读不到沿用上次 =====
        self._energy_tick = getattr(self, "_energy_tick", 0) + 1
        if self._energy_tick % 3 == 1:
            try:
                import re as _re
                info = self._find_game_window()
                if info:
                    left, top, right, bottom = info.rect
                    w, h = right - left, bottom - top
                    if w >= 50 and h >= 50:
                        frame2 = self._get_fast_capture().capture(rect=(left, top, w, h))
                        if frame2 is not None and frame2.size > 0:
                            crop = pipeline._crop(frame2, "剩余能量")
                            if crop is not None and crop.size > 0:
                                from src.pvp.pvp_pipeline import preprocess_text_roi, ocr_number
                                if crop.shape[0] < 30:
                                    crop = preprocess_text_roi(crop, scale=3)
                                val = ocr_number(crop)
                                if val:
                                    m = _re.search(r"(\d+)", val)
                                    if m:
                                        self._energy_val_cache = int(m.group(1))
            except Exception:
                pass
        cached_energy = getattr(self, "_energy_val_cache", None)
        if cached_energy is not None:
            result.energy = str(cached_energy)
            result.energy_val = cached_energy

    def _apply_ocr_skill_cache(self, result) -> None:
        """OCR 本帧失败时，沿用上一帧成功的技能栏（防闪没）。"""
        cache = getattr(self, "_ocr_skill_cache", None)
        if cache and getattr(result, "in_battle", False):
            result.skills = list(cache)

    def _enrich_result(self, data: dict, result) -> None:
        """识别结果附加伤害推演字段(calc_skills/enemy_threats/速度/愿力)。
        _pvp_loop 与本地 API /snapshot 共用; 精灵数据未就绪/名字未识别时写 calc_error。"""
        try:
            from src.pvp.pet_loader import get_pet_by_name
            from src.pvp.skill_loader import get_skill
            from src.pvp.damage_calculator import (
                calculate_all_panels, calculate_damage_full,
                calculate_world_speed_range, calculate_resonance_impact_damages)

            self_pet = get_pet_by_name(result.player_name)
            enemy_pet = get_pet_by_name(result.enemy_name)
            if not (self_pet and enemy_pet):
                data["calc_error"] = "精灵数据未就绪或名字未识别"
                return

            # 自动流派推导: 物攻高用物攻, 魔攻高用魔攻
            race = self_pet.get("race", {})
            prefer = "mattack" if race.get("mattack", 0) > race.get("attack", 0) else "attack"
            self_panel = calculate_all_panels(self_pet.get("race", {}))
            enemy_panel = calculate_all_panels(enemy_pet.get("race", {}))
            speed_diff = self_panel["speed"] - enemy_panel["speed"]

            # 我方技能伤害(OCR 出的 4 个技能逐个推演)
            calc_skills = []
            for sk_name in result.skills:
                sk = get_skill(sk_name) or {}
                sk_type = sk.get("type", "物攻")
                sk_attr = sk.get("attr", "普")
                sk_power = float(sk.get("power", 0)) if sk.get("power") else 0
                if sk_power > 0 and sk_type in ("物攻", "魔攻"):
                    dmg = calculate_damage_full(
                        attacker_panel=self_panel, defender_panel=enemy_panel,
                        skill_power=sk_power, skill_type=sk_type, skill_attr=sk_attr,
                        attacker_attrs=self_pet.get("types", []),
                        defender_attrs=enemy_pet.get("types", []),
                    )
                    enemy_est_hp = int(enemy_panel["hp"] * result.enemy_hp_pct)
                    dmg_min = dmg["damage"]
                    dmg_max = round(dmg["damage"] * 1.15)
                    is_kill = enemy_est_hp > 0 and dmg_min >= enemy_est_hp
                    calc_skills.append({
                        "name": sk_name, "power": int(sk_power),
                        "type": sk_type, "attr": sk_attr,
                        "dmg_min": dmg_min, "dmg_max": dmg_max,
                        "mult": dmg["attrMultiplier"],
                        "is_kill": is_kill,
                    })
                else:
                    calc_skills.append({"name": sk_name, "power": 0, "type": "变化",
                                        "dmg_min": 0, "dmg_max": 0, "mult": 1, "is_kill": False})

            # 敌方威胁预测: 与主控台 pvp_calc_all_skills 同一套玩家筛选规则 —
            # 1) 按敌方种族值高项只选匹配的物攻/魔攻技能(双刀全显示)
            # 2) 排除「升龙咆哮」 3) 威力<=60 的攻击技能剔除(龙系豁免)
            enemy_race = enemy_pet.get("race", {})
            try:
                e_pa = int(enemy_race.get("attack", 0) or 0)
            except (TypeError, ValueError):
                e_pa = 0
            try:
                e_ma = int(enemy_race.get("mattack", 0) or 0)
            except (TypeError, ValueError):
                e_ma = 0
            e_allowed = ("物攻", "魔攻") if e_pa == e_ma else (("物攻",) if e_pa > e_ma else ("魔攻",))

            enemy_skills_raw = enemy_pet.get("skills", [])   # 全量, 筛选规则会收紧
            enemy_skills = [s["name"] if isinstance(s, dict) else s for s in enemy_skills_raw]
            enemy_threats = []
            for esk_name in enemy_skills:
                esk = get_skill(esk_name) or {}
                try:
                    esk_power = float(esk.get("power", 0)) if esk.get("power") else 0
                except (TypeError, ValueError):
                    esk_power = 0
                esk_type = esk.get("type", "")
                esk_attr = (esk.get("attr") or "").rstrip("系")
                if esk_name == "升龙咆哮":
                    continue
                if not (esk_power > 0 and esk_type in e_allowed):
                    continue
                if esk_power <= 60 and esk_attr != "龙":
                    continue
                edmg = calculate_damage_full(
                    attacker_panel=enemy_panel, defender_panel=self_panel,
                    skill_power=esk_power, skill_type=esk_type,
                    skill_attr=esk.get("attr", "普"),
                    attacker_attrs=enemy_pet.get("types", []),
                    defender_attrs=self_pet.get("types", []),
                )
                is_lethal = result.player_hp_val > 0 and edmg["damage"] >= result.player_hp_val
                enemy_threats.append({
                    "name": esk_name, "power": int(esk_power),
                    "dmg_min": edmg["damage"],
                    "dmg_max": round(edmg["damage"] * 1.15),
                    "is_lethal": is_lethal,
                    "tags": esk.get("tags", []),
                })
            # 按伤害降序取前 4
            enemy_threats.sort(key=lambda t: -t["dmg_min"])
            enemy_threats = enemy_threats[:4]

            # 敌方《洛克王国：世界》真实速度极值区间(对齐点击头像显示的区间)
            enemy_race_speed = float(enemy_pet.get("race", {}).get("speed", 0))
            enemy_speed_range = calculate_world_speed_range(enemy_race_speed)

            # 愿力冲击暗手伤害推演
            resonance_data = calculate_resonance_impact_damages(
                enemy_panel=enemy_panel,
                self_panel=self_panel,
                enemy_types=enemy_pet.get("types", []),
                self_types=self_pet.get("types", []),
                self_current_hp=result.player_hp_val,
            )

            data["speed_diff"] = int(speed_diff)
            data["enemy_speed_range"] = enemy_speed_range
            data["calc_skills"] = calc_skills
            data["enemy_threats"] = enemy_threats
            data["resonance_impact"] = resonance_data
            data["calc_done"] = True
        except Exception as e:
            data["calc_error"] = str(e)


    # ---- PVP 状态沿消费: 自动截图存档 + 战斗头像自动入库 ----
    def _pvp_save_screenshot(self, frame, sub: str, tag: str) -> None:
        """帧存档到 data/screenshots/<sub>/, md5 前缀去重 + 目录限额."""
        import cv2
        import hashlib
        from src.pvp.pvp_pipeline import PROJECT_ROOT
        out_dir = PROJECT_ROOT / "data" / "screenshots" / sub
        out_dir.mkdir(parents=True, exist_ok=True)
        md5 = hashlib.md5(frame.tobytes()).hexdigest()[:8]
        # 文件名含 md5 前 8 位 → 重启后仍可去重
        if any(md5 in p.name for p in out_dir.glob("*.png")):
            return
        files = list(out_dir.glob("*.png"))
        if len(files) >= 200:   # 限额: 截图只是素材存档, 超额删最旧
            try:
                oldest = min(files, key=lambda p: p.stat().st_mtime)
                oldest.unlink()
            except Exception:
                pass
        fname = f"{time.strftime('%Y%m%d_%H%M%S')}_{tag}_{md5}.png"
        ok, buf = cv2.imencode(".png", frame)   # imencode+tofile 兼容中文路径
        if ok:
            buf.tofile(str(out_dir / fname))

    def _pvp_auto_ingest(self, frame, result, pipeline) -> None:
        """战斗帧头像自动入库(后台线程): OCR≥0.9 验名的头像 ROI 直接入库.

        优先复用管线已加载的模板库实例(特性缓存实时生效); 库为空时
        管线侧保持 None, 此处自建并回填, 让首批自动模板立刻可用。
        """
        from src.pvp.pvp_pipeline import PROJECT_ROOT
        lib = getattr(pipeline, "_avatar_lib", None)
        if lib is None:
            lib = getattr(self, "_pvp_auto_lib", None)
            if lib is None:
                try:
                    import sys as _sys
                    lib_dir = PROJECT_ROOT / "src" / "pvp" / "lib"
                    for pth in (str(lib_dir), str(PROJECT_ROOT)):
                        if pth not in _sys.path:
                            _sys.path.insert(0, pth)
                    from pvp_lib import PvpTemplateLibrary
                    lib = PvpTemplateLibrary()
                    lib.load()
                except Exception:
                    lib = None
                self._pvp_auto_lib = lib
            if lib is not None:
                try:
                    pipeline._avatar_lib = lib
                except Exception:
                    pass
        if lib is None:
            return
        added = 0
        for roi_id, name, conf in (
                ("我方精灵头像", result.player_name, result.player_name_conf),
                ("敌方精灵头像", result.enemy_name, result.enemy_name_conf)):
            if not name or conf < 0.9:
                continue   # 未过词库模糊命中验名 → 交给 add_template 内部再验
            crop = pipeline._crop(frame, roi_id)
            if crop is None or crop.size == 0:
                continue
            try:
                if lib.add_template(name, crop, src="battle_auto"):
                    added += 1
            except Exception:
                continue
        if added:
            self._enqueue_log(
                f"📸 战斗帧自动入库 {added} 个头像模板 "
                f"(总计 {len(getattr(lib, 'entries', []))})", "info")

    def _handle_pvp_edges(self, frame, result, pipeline) -> None:
        """状态沿消费(边沿触发, 常规帧仅两次 getattr 即返回):
        - 进战斗沿: 战斗帧存档 pvp_battle/; 本局后续帧 OCR 高置信时头像自动入库(每局一次)
        - 阵容识别沿: 战备屏存档 pvp_lineup/ (仅存档不自动入库:
          pair_pvp_rows 的行布局不适配战斗帧, 误入库会造坏模板)
        - 脱战斗沿: 无动作 (阵容会话缓存已在管线内清理)
        """
        try:
            in_battle = getattr(result, "in_battle", False)
            if not in_battle and not getattr(result, "lineup_new", False):
                return
            if getattr(result, "battle_start", False):
                try:
                    self._pvp_save_screenshot(frame, "pvp_battle", "battle")
                except Exception:
                    pass
                self._pvp_ingest_done = False
            if getattr(result, "lineup_new", False):
                try:
                    self._pvp_save_screenshot(frame, "pvp_lineup", "lineup")
                except Exception:
                    pass
            if (in_battle and not getattr(self, "_pvp_ingest_done", True)
                    and (getattr(result, "player_name_conf", 0) >= 0.9
                         or getattr(result, "enemy_name_conf", 0) >= 0.9)):
                self._pvp_ingest_done = True
                threading.Thread(
                    target=self._pvp_auto_ingest, args=(frame, result, pipeline),
                    daemon=True).start()
        except Exception:
            pass


    def _pvp_loop(self, gen: int = 0):
        """后台线程: 截图 → 识别 → 伤害计算 → 推送悬浮窗。

        gen = 启动代数: 快速 停止→启动 时, 旧线程可能仍卡在单轮 OCR 里
        (join 超时返回), 若只看 _pvp_running 标志会与新线程双循环并行
        推送。每轮检查代数, 过代即退。"""
        import time as _time
        import cv2, numpy as np
        from src.pvp.pvp_pipeline import get_pipeline
        from src.pvp.pet_loader import get_pet_by_name
        from src.pvp.skill_loader import get_skill
        from src.pvp.damage_calculator import calculate_all_panels, calculate_damage_full
        from src.pvp.type_chart import get_attr_multiplier

        pipeline = get_pipeline()
        self._pipeline = pipeline

        # 数据源: "ocr"(默认) / "capture"(自研抓包) / "rkpp"(RKPP 解码后端)。
        # 抓包源跳过截图与 OCR, 由适配器产出同构快照, 下游代码零改动。
        source = getattr(self, "_pvp_source", "ocr")
        capture_adapter = None
        rkpp_client = None
        if source == "capture":
            from src.capture.snapshot_adapter import get_capture_adapter
            capture_adapter = get_capture_adapter()
            self._capture_adapter = capture_adapter
            capture_adapter.reset()
            # 启动抓包子系统(后台线程, 只读旁路)
            self._start_capture_subsystem()
        elif source == "rkpp":
            # RKPP 解码后端: 拉起 opencode-server 子进程(自动抓握手 key),
            # 再订阅其 /events 实时流, 翻译成同构快照。
            self._start_rkpp_subsystem()
            rkpp_client = getattr(self, "_rkpp_client", None)

        while self._pvp_running and gen == getattr(self, "_pvp_loop_gen", gen):
            t0 = _time.perf_counter()
            try:
                if source == "capture":
                    # 抓包源: 无截图、无 OCR, 直接从抓包状态机取快照
                    result = capture_adapter.analyze()
                    data = capture_adapter.to_dict(result)
                    pipeline._cached_result = result  # 供 local_pvp_snapshot 读取
                    self._push_capture_snapshot(result, data)
                    elapsed = _time.perf_counter() - t0
                    _time.sleep(max(0.05, self._pvp_interval - elapsed))
                    continue

                if source == "rkpp":
                    if rkpp_client is None:
                        _time.sleep(self._pvp_interval)
                        continue
                    # 断流自愈: 服务端(opencode-server)崩溃后事件流会静默中断,
                    # 表现为"进入战斗完全没反应"。检测到断连 → 整套重启子系统。
                    if not rkpp_client.is_connected():
                        self._rkpp_fail_count = getattr(self, "_rkpp_fail_count", 0) + 1
                        if self._rkpp_fail_count >= 10:      # 连续 ~5s 断连
                            self._rkpp_fail_count = 0
                            print("[RKPP] 事件流断连, 自动重启解码后端…", flush=True)
                            self._enqueue_log("[RKPP] 事件流断连, 自动重启解码后端…", "warning")
                            self._stop_rkpp_subsystem()
                            self._start_rkpp_subsystem()
                            rkpp_client = getattr(self, "_rkpp_client", None)
                            if rkpp_client is None:
                                _time.sleep(self._pvp_interval)
                                continue
                        else:
                            _time.sleep(self._pvp_interval)
                            continue
                    else:
                        self._rkpp_fail_count = 0
                    self._rkpp_tick_n = getattr(self, "_rkpp_tick_n", 0) + 1
                    result = rkpp_client.analyze()
                    if self._rkpp_tick_n % 20 == 1:
                        print(f"[引擎] rkpp 心跳: 连接={rkpp_client.is_connected()} "
                              f"战斗中={result.in_battle} 回合={getattr(result, 'round_no', 0)}", flush=True)
                    # 我方技能栏: OCR 优先(准确率高), 抓包结果兜底。
                    # 仅在战斗态截图识别；窗口找不到/截图失败则保留抓包技能栏。
                    if result.in_battle:
                        try:
                            self._merge_ocr_skill_bar(result, pipeline)
                        except Exception:
                            pass
                    data = rkpp_client.to_dict(result)
                    pipeline._cached_result = result
                    self._push_capture_snapshot(result, data)
                    elapsed = _time.perf_counter() - t0
                    _time.sleep(max(0.05, self._pvp_interval - elapsed))
                    continue

                # 1. 截图 (FastCapture 单例, ~3-5ms)
                info = self._find_game_window()
                if not info:
                    _time.sleep(self._pvp_interval)
                    continue
                left, top, right, bottom = info.rect
                w, h = right - left, bottom - top
                if w < 50 or h < 50:
                    _time.sleep(self._pvp_interval)
                    continue

                fc = self._get_fast_capture()
                frame = fc.capture(rect=(left, top, w, h))
                if frame is None or frame.size == 0:
                    _time.sleep(self._pvp_interval)
                    continue
                self._last_frame = frame

                # 1.5 遮挡防护: 控制台叠在游戏上方时截到的是控制台画面 → 自动最小化
                self._guard_console_occlusion(info.rect, info.hwnd)

                # 2. 识别
                result = pipeline.analyze(frame)
                # 2.1 状态沿消费: 自动截图存档 + 战斗头像自动入库(边沿触发)
                self._handle_pvp_edges(frame, result, pipeline)
                data = pipeline.to_dict(result)
                player = data.get("player", {})
                enemy = data.get("enemy", {})

                # 3. 伤害推演(计算块抽为 _enrich_result, 本地 API /snapshot 共用)
                if result.in_battle:
                    self._enrich_result(data, result)

                # 4. 推送悬浮窗(含 AI 决策缓存)
                if result.in_battle:
                    with self._ai_decision_lock:
                        if self._ai_recommendation:
                            data["ai_advice"] = self._ai_recommendation
                if self._pvp_float_window and self._pvp_float_visible and self._pvp_float_loaded:
                    self._pvp_float_window.evaluate_js(
                        f"updatePVPData({json.dumps(data, ensure_ascii=False)})"
                    )

                # 4.2 回合日志: 进战斗开局 / 每帧 diff 事件 / 脱战斗收尾写战报
                try:
                    self._round_logger_tick(data, result)
                except Exception:
                    pass

                # 4.8 自动刷新 AI 决策(约每 2s 触发一次)
                if result.in_battle:
                    _now = _time.time()
                    _last = getattr(self, "_last_ai_decision_ts", 0.0)
                    if _now - _last >= 8.0:
                        self._last_ai_decision_ts = _now
                        try:
                            from src.gui.ai_decision import get_decision
                            _decision = get_decision(data)
                            with self._ai_decision_lock:
                                self._ai_recommendation = _decision
                        except Exception:
                            pass

                # 4.5 同步双方精灵到主控台「PVP 实时对战」详细查询页
                if result.in_battle and result.player_name and result.enemy_name                         and self._window and self._pvp_running:
                    pair = (result.player_name, result.enemy_name)
                    if pair != getattr(self, "_last_synced_pair", None):
                        self._last_synced_pair = pair
                        try:
                            self._window.evaluate_js(
                                "syncPvpFromFloat("
                                + json.dumps(result.player_name, ensure_ascii=False) + ","
                                + json.dumps(result.enemy_name, ensure_ascii=False) + ")")
                        except Exception:
                            pass

                # 5. 日志
                if result.in_battle:
                    dmg_hint = ""
                    if data.get("calc_skills"):
                        kills = [s["name"] for s in data["calc_skills"] if s.get("is_kill")]
                        if kills:
                            dmg_hint = f" 🔥必杀:{','.join(kills)}"
                    self._enqueue_log(
                        f"⚔️ 我方:{result.player_name}({result.player_hp}) "
                        f"敌方:{result.enemy_name}({result.enemy_hp_pct:.0%}) "
                        f"技能:{result.skills[0] if result.skills else '-'}{dmg_hint}",
                        "info")

            except Exception as e:
                self._enqueue_log(f"PVP 识别异常: {e}", "error")

            elapsed = _time.perf_counter() - t0
            sleep_time = max(0.05, self._pvp_interval - elapsed)
            _time.sleep(sleep_time)


    # ========================================
    # 抓包数据源(只读旁路, 与 OCR 并行; 默认不启用)
    # ========================================

    def _start_capture_subsystem(self) -> None:
        """启动抓包子系统: PacketCaptureEngine 后台抓包 → BattleListener →
        CaptureSnapshotAdapter。已启动则复用。失败只记日志, 不阻断主循环。"""
        if getattr(self, "_capture_engine", None) is not None:
            return
        try:
            from src.capture.packet_capture import PacketCaptureEngine
            from src.capture.battle_listener import BattleListener
            from src.capture.snapshot_adapter import get_capture_adapter

            adapter = get_capture_adapter()

            def _on_record(rec: dict) -> None:
                adapter.ingest(rec)

            listener = BattleListener(dump_enabled=True, verbose=False)
            listener.on_record = _on_record
            listener.start("bridge")

            engine = PacketCaptureEngine(
                iface=getattr(self, "_capture_iface", None),
                port=getattr(self, "_capture_port", 8195),
                on_frame=listener,
                preset_key=getattr(self, "_capture_key", None),
                verbose=False,
            )
            import threading
            self._capture_listener = listener
            self._capture_engine = engine
            self._capture_thread = threading.Thread(
                target=engine.run, kwargs={"seconds": 0},
                daemon=True, name="PvpCapture")
            self._capture_thread.start()
            self._enqueue_log("抓包子系统已启动(同构数据源)", "success")
        except Exception as e:
            self._enqueue_log(f"抓包子系统启动失败: {e}", "error")

    def _stop_capture_subsystem(self) -> None:
        engine = getattr(self, "_capture_engine", None)
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass
            self._capture_engine = None
        listener = getattr(self, "_capture_listener", None)
        if listener is not None:
            try:
                listener.close()
            except Exception:
                pass
            self._capture_listener = None

    # ---- RKPP 解码后端(独立进程 + HTTP 订阅, 遵守 AGPL-3.0-only) ----

    def _rkpp_paths(self):
        """定位 RKPP 项目目录与入口脚本。可用 self._rkpp_dir 覆盖。"""
        import os
        from pathlib import Path
        candidates = []
        override = getattr(self, "_rkpp_dir", None)
        if override:
            candidates.append(Path(override))
        # 约定: 与项目同级(工作目录父目录)的 rkpp_ref
        proj_root = Path(__file__).resolve().parents[2]
        candidates.append(proj_root.parent / "rkpp_ref")
        candidates.append(proj_root / "rkpp_ref")
        for d in candidates:
            script = d / "rkpp_live_tools.py"
            if script.exists():
                return d, script
        return None, None

    def _start_rkpp_subsystem(self) -> None:
        """拉起 RKPP opencode-server 子进程并订阅其 /events 流。

        流程:
          1. 定位 rkpp_ref/rkpp_live_tools.py;
          2. 若未预置 key(账号级可复用), 先跑 capture-key 抓 0x1002 握手 key;
          3. 后台启动 opencode-server(HTTP relay, 默认 8765);
          4. 等 relay 就绪后, 用 RkppEventClient 订阅 /events。
        任一步失败只记日志, 不阻断主循环。"""
        if getattr(self, "_rkpp_client", None) is not None:
            return
        try:
            import subprocess
            import sys
            import threading

            rkpp_dir, script = self._rkpp_paths()
            if script is None:
                self._enqueue_log(
                    "RKPP 未找到: 请把 RKPP 项目放到本项目同级目录 rkpp_ref/", "error")
                return

            iface = getattr(self, "_capture_iface", None)
            port = getattr(self, "_capture_port", 8195)
            relay_port = getattr(self, "_rkpp_relay_port", 8765)
            # RKPP 自身用全局 Key/latest.key 存取握手 key(账号级可复用)。
            # capture-key 抓到后会自动写入该文件, opencode-server 启动时自动加载,
            # 因此本项目无需手动读写 key 文件、也无需 --key 传参。
            latest_key = rkpp_dir / "Key" / "latest.key"

            # 1) 若无可用 key, 先跑 capture-key(内部会写全局 Key/latest.key)
            if not latest_key.exists():
                self._enqueue_log("RKPP 首次使用: 正在抓握手 key(请点「进入世界」)...", "info")
                cap_cmd = [sys.executable, str(script), "capture-key", "--port", str(port)]
                if iface:
                    cap_cmd += ["--iface", iface]
                try:
                    subprocess.run(cap_cmd, cwd=str(rkpp_dir), timeout=90, check=False)
                except Exception as e:
                    self._enqueue_log(f"RKPP 抓 key 超时/失败: {e}", "error")
                if latest_key.exists():
                    self._enqueue_log("RKPP 握手 key 已获取(write 至 Key/latest.key)", "success")
                else:
                    self._enqueue_log("RKPP 未抓到 key: 将继续运行, 等游戏内重新握手", "warning")

            # 1.5) 清理残留 opencode-server: 上次进程被强杀时子进程会变孤儿,
            # 占着 relay 端口(8765)让新实例 bind 失败且无任何报错(stdout=DEVNULL),
            # 表现就是"订阅成功但永远没数据"。
            try:
                ps_cmd = (
                    "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
                    "Where-Object { \"$(($_.CommandLine))\" -match 'opencode-server' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                               capture_output=True, timeout=15)
            except Exception:
                pass

            # 2) 启动 opencode-server(HTTP relay); 未指定 --key 时自动加载 Key/latest.key
            cmd = [sys.executable, str(script), "opencode-server",
                   "--port", str(port),
                   "--relay-host", "127.0.0.1", "--relay-port", str(relay_port)]
            if iface:
                cmd += ["--iface", iface]
            key = getattr(self, "_capture_key", None)
            if key:
                cmd += ["--key", key]
            self._enqueue_log(f"启动 RKPP 解码后端: {' '.join(cmd)}", "info")
            # 输出落盘: 服务端崩溃原因可追溯(此前 DEVNULL 吞掉一切, 崩了无从排查)
            server_log = Path(PROJECT_ROOT) / "data" / "logs" / "rkpp_server.log"
            server_log.parent.mkdir(parents=True, exist_ok=True)
            server_log_f = open(server_log, "ab")
            banner = "===== opencode-server 启动 " + time.strftime('%Y-%m-%d %H:%M:%S') + " ====="
            server_log_f.write(("\n" + banner + "\n").encode())
            server_log_f.flush()
            proc = subprocess.Popen(
                cmd, cwd=str(rkpp_dir),
                stdout=server_log_f, stderr=server_log_f)
            self._rkpp_proc = proc
            self._rkpp_server_log_f = server_log_f

            # 3) 订阅 /events(等 relay 就绪)
            from src.capture.rkpp_client import get_rkpp_client
            client = get_rkpp_client(
                f"http://127.0.0.1:{relay_port}",
                logger=lambda m: self._enqueue_log(m, "error"))
            client.reset()
            for _ in range(40):
                if client.is_connected():
                    break
                threading.Event().wait(0.25)
            client.start()
            self._rkpp_client = client
            self._enqueue_log("RKPP 事件流已订阅(/events)", "success")
        except Exception as e:
            self._enqueue_log(f"RKPP 子系统启动失败: {e}", "error")

    def _stop_rkpp_subsystem(self) -> None:
        client = getattr(self, "_rkpp_client", None)
        if client is not None:
            try:
                client.stop()
            except Exception:
                pass
            self._rkpp_client = None
        proc = getattr(self, "_rkpp_proc", None)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._rkpp_proc = None

    def _push_capture_snapshot(self, result, data: dict) -> None:
        """抓包快照 → 伤害推演 / 悬浮窗 / 回合日志 / AI 缓存。
        _handle_pvp_edges 与 lineup 同步是 OCR 专属, 此处不调用。"""
        if result.in_battle:
            self._enrich_result(data, result)
            with self._ai_decision_lock:
                if self._ai_recommendation:
                    data["ai_advice"] = self._ai_recommendation
        if self._pvp_float_window and self._pvp_float_visible and self._pvp_float_loaded:
            self._pvp_float_window.evaluate_js(
                f"updatePVPData({json.dumps(data, ensure_ascii=False)})"
            )
        try:
            self._round_logger_tick(data, result)
        except Exception:
            pass
        if result.in_battle:
            import time as _time
            _now = _time.time()
            _last = getattr(self, "_last_ai_decision_ts", 0.0)
            if _now - _last >= 8.0:
                self._last_ai_decision_ts = _now
                try:
                    from src.gui.ai_decision import get_decision
                    _decision = get_decision(data)
                    with self._ai_decision_lock:
                        self._ai_recommendation = _decision
                except Exception:
                    pass

    def pvp_engine_start(self, source: str = "") -> dict:
        """启动 PVP 实时识别引擎。source: "ocr" / "capture"(自研抓包) / "rkpp"。

        source 缺省(悬浮窗启动按钮等无参调用方)时沿用上一次的数据源 ——
        此前硬默认 "ocr", 用户选了 rkpp 后一按悬浮窗启动键就被无声降级成
        OCR(实测 2026-09-25 晚), 是"我没切但它变成 OCR"的元凶之一。"""
        gate = self._auth_gate()
        if gate:
            return gate
        if self._pvp_running:
            label = {"capture": "抓包", "rkpp": "RKPP 解码"}.get(self._pvp_source, "OCR")
            return {"success": True, "running": True,
                    "source": self._pvp_source,
                    "message": f"PVP 引擎已在运行(数据源: {label})"}
        auto_stopped = self._stop_conflicting_modes("pvp")
        src = str(source or "").lower()
        if src not in ("capture", "rkpp", "ocr"):
            src = getattr(self, "_pvp_source", "") or "ocr"
        self._pvp_source = src
        import threading
        self._pvp_running = True
        self._pvp_loop_gen = getattr(self, "_pvp_loop_gen", 0) + 1
        cur_gen = self._pvp_loop_gen
        self._pvp_thread = threading.Thread(target=self._pvp_loop, kwargs={"gen": cur_gen},
                                            daemon=True, name="PvpEngine")
        self._pvp_thread.start()
        label = {"capture": "抓包", "rkpp": "RKPP 解码"}.get(self._pvp_source, "OCR")
        print(f"[引擎] 启动 数据源={self._pvp_source}", flush=True)
        self._enqueue_log(f"PVP 实时识别引擎已启动 (数据源: {label})", "success")
        return {"success": True, "auto_stopped": auto_stopped, "source": self._pvp_source}

    def pvp_engine_stop(self) -> dict:
        """停止 PVP 实时识别引擎"""
        self._pvp_running = False
        if self._pvp_thread:
            self._pvp_thread.join(timeout=2.0)
            self._pvp_thread = None
        self._stop_capture_subsystem()
        self._stop_rkpp_subsystem()
        print("[引擎] 停止", flush=True)
        self._enqueue_log("PVP 引擎已停止", "info")
        return {"success": True}

    def pvp_engine_status(self) -> dict:
        return {"running": self._pvp_running, "float_visible": self._pvp_float_visible,
                "source": getattr(self, "_pvp_source", "ocr")}

    # ========================================
    # 本地 API 桥 (AI 陪玩 MCP 数据源)
    # ========================================

    def local_pvp_snapshot(self) -> dict:
        """实时对局快照: 最新识别缓存 + 伤害推演字段(MCP /snapshot 数据源)。
        引擎未运行/无识别缓存时返回 in_battle=False 的空壳(不报错, AI 可轮询等待)。"""
        data = {"in_battle": False, "pvp_engine_running": bool(self._pvp_running)}
        pipeline = getattr(self, "_pipeline", None)
        result = getattr(pipeline, "_cached_result", None) if pipeline else None
        if result is None:
            return data
        try:
            from src.pvp.pvp_pipeline import get_pipeline
            data = get_pipeline().to_dict(result)
        except Exception:
            return data
        if getattr(result, "in_battle", False):
            self._enrich_result(data, result)
            # 手牌/心数/回合摘要(回合日志聚合, 供 AI 做终局与换宠决策)
            try:
                logger = getattr(self, "_round_logger", None)
                if logger and not logger._closed:
                    data["hands"] = logger.hands_summary(
                        current_enemy=(data.get("enemy") or {}).get("name", ""))
            except Exception:
                pass
            # 能量线推演: 本回合可放技能 / 聚能后下回合可放 / 距愿力还差几点
            try:
                data["energy_plan"] = self._energy_plan(data)
            except Exception:
                pass
            # AI 战术建议(缓存, 由 /recommend 端点或后台定时刷新)
            with self._ai_decision_lock:
                if self._ai_recommendation:
                    data["ai_advice"] = self._ai_recommendation
        elif getattr(result, "lineup_done", False):
            # 非战斗态但已识别阵容: 透出阵容供 AI 预读
            data["player_lineup"] = result.player_lineup
            data["enemy_lineup"] = result.enemy_lineup
            data["lineup_done"] = True
        return data

    @staticmethod
    def _energy_plan(data: dict) -> dict:
        """我方能量线: 基于当前能量与技能消耗, 推演本回合/聚能后/两回合后的可选动作。
        聚能=+5 不攻击; 愿力冲击固定 2 能耗 80 威。"""
        player = data.get("player") or {}
        energy = int(player.get("energy_val") or 0)
        from src.pvp.skill_loader import get_skill
        consume_map = {}
        for sk_name in (player.get("skills") or []):
            if not sk_name:
                continue
            sk = get_skill(sk_name) or {}
            try:
                consume_map[sk_name] = int(float(sk.get("consume") or 0))
            except (TypeError, ValueError):
                consume_map[sk_name] = 0
        resonance_cost = 2

        def _affordable(e: int) -> list:
            return [n for n, c in consume_map.items() if c <= e]

        plan = {
            "energy_now": energy,
            "this_turn_skills": _affordable(energy),
            "can_resonance_now": energy >= resonance_cost,
            "after_charge_energy": energy + 5,
            "after_charge_skills": _affordable(energy + 5),
            "charge_then_resonance_next_turn": (energy + 5) >= resonance_cost,
            "deficit_to_resonance": max(0, resonance_cost - energy),
        }
        return plan

    def push_ai_comment(self, text: str, mood: str = "normal") -> bool:
        """AI 陪玩评论 → 悬浮窗弹幕条 (evaluate_js)"""
        import html as _html
        text = _html.escape(str(text)[:120])
        mood = str(mood)[:16]
        js = f"pushAiComment({json.dumps(text, ensure_ascii=False)}, {json.dumps(mood, ensure_ascii=False)})"
        widget = getattr(self, "_pvp_float_window", None)
        if not widget:
            return False
        try:
            widget.evaluate_js(js)
            return True
        except Exception:
            return False


    def local_api_start(self):
        """启动本机 HTTP 桥 + AI 陪玩线程(端口占用/配置缺失均静默降级)"""
        if getattr(self, "_local_api", None):
            return
        try:
            from src.gui.local_api import LocalApiServer
            self._local_api = LocalApiServer(self)
            self._local_api.start()
        except Exception:
            self._local_api = None
        try:
            from src.gui.ai_companion import AiCompanion
            self._ai_companion = AiCompanion(self)
            self._ai_companion.start()
        except Exception:
            self._ai_companion = None

    def local_api_stop(self):
        server = getattr(self, "_local_api", None)
        if server:
            server.stop()
            self._local_api = None
        companion = getattr(self, "_ai_companion", None)
        if companion:
            companion.stop()
            self._ai_companion = None
