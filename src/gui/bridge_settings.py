"""AppBridge Mix-in —— 引擎与 AI 设置读写 / 配置中心"""

import json
from src.gui.bridge_common import CONFIG_DIR, CONFIG_FILES, DEV_MODE


class SettingsMixin:

    @staticmethod
    def _parse_engine_params(params: dict) -> dict:
        """前端参数 -> 引擎 override(只认白名单键)"""
        overrides = {}
        try:
            if params.get("catch_hp") is not None:
                overrides["catch_hp"] = max(1, min(60, int(params["catch_hp"])))
            if params.get("open_ball_key"):
                overrides["open_ball_key"] = str(params["open_ball_key"]).strip().lower()[:3]
            if params.get("ball_slot_key"):
                slot = str(params["ball_slot_key"]).strip()
                if slot in {"1", "2", "3", "4", "5", "6"}:
                    overrides["ball_slot_key"] = slot
            if params.get("skills"):
                skills = [s.strip() for s in str(params["skills"]).replace("，", ",").split(",") if s.strip()]
                if skills:
                    overrides["skills"] = skills[:6]
            if params.get("skill_mode") in ("cycle", "sequence"):
                overrides["skill_mode"] = params["skill_mode"]
            if params.get("patrol_enabled") is not None:
                overrides["patrol_enabled"] = bool(params["patrol_enabled"])
            if params.get("patrol_move_key"):
                key = str(params["patrol_move_key"]).strip().lower()[:3]
                if key:
                    overrides["patrol_move_key"] = key
            if params.get("patrol_turn_mode") in ("keys", "mouse"):
                overrides["patrol_turn_mode"] = params["patrol_turn_mode"]
        except (TypeError, ValueError):
            pass
        return overrides

    def _save_engine_settings(self, params: dict):
        """把引擎参数写回 settings.yaml 的 battle 段"""
        try:
            import yaml
            from src.utils.settings import SETTINGS_PATH, invalidate
            data = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8")) or {}
            battle = data.setdefault("battle", {})
            if params.get("catch_hp") is not None:
                battle["catch_hp"] = max(1, min(60, int(params["catch_hp"])))
            if params.get("open_ball_key"):
                battle["open_ball_key"] = str(params["open_ball_key"]).strip().lower()
            if params.get("ball_slot_key"):
                battle["ball_slot_key"] = str(params["ball_slot_key"]).strip()
            if params.get("skills"):
                skills = [s.strip() for s in str(params["skills"]).replace("，", ",").split(",") if s.strip()]
                if skills:
                    battle["skills"] = skills[:6]
            if params.get("skill_mode") in ("cycle", "sequence"):
                battle["skill_mode"] = params["skill_mode"]
            patrol = data.setdefault("patrol", {})
            if params.get("patrol_enabled") is not None:
                patrol["enabled"] = bool(params["patrol_enabled"])
            if params.get("patrol_move_key"):
                patrol["move_key"] = str(params["patrol_move_key"]).strip().lower()
            if params.get("patrol_turn_mode") in ("keys", "mouse"):
                patrol["turn_mode"] = params["patrol_turn_mode"]
            # AI 全局设置 (Key/模型)
            ai = data.setdefault("ai", {})
            if "ai_base_url" in params:
                ai["base_url"] = str(params["ai_base_url"]).strip() or ""
            if "ai_api_key" in params:
                ai["api_key"] = str(params["ai_api_key"]).strip() or ""
            if "ai_model" in params:
                ai["model"] = str(params["ai_model"]).strip() or ""
            if "ai_vision_model" in params:
                ai["vision_model"] = str(params["ai_vision_model"]).strip() or ""
            SETTINGS_PATH.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            invalidate()
            self._enqueue_log("引擎参数已保存到 settings.yaml", "info")
        except Exception as e:
            self._enqueue_log(f"保存引擎参数失败: {e}", "error")

    def engine_get_settings(self) -> dict:
        """读取 settings.yaml 中的挂机引擎与巡逻参数"""
        try:
            import yaml
            from src.utils.settings import SETTINGS_PATH
            if not SETTINGS_PATH.exists():
                return {"success": True, "settings": {}}
            data = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8")) or {}
            battle = data.get("battle", {})
            patrol = data.get("patrol", {})
            ai = data.get("ai", {})
            raw_skills = battle.get("skills", ["1"])
            skills_str = ",".join(str(s) for s in raw_skills) if isinstance(raw_skills, list) else str(raw_skills)
            settings = {
                "catch_hp": battle.get("catch_hp", 50),
                "skills": skills_str,
                "open_ball_key": battle.get("open_ball_key", "w"),
                "ball_slot_key": str(battle.get("ball_slot_key", "1")),
                "patrol_enabled": patrol.get("enabled", True),
                "patrol_move_key": patrol.get("move_key", "w"),
                "patrol_turn_mode": patrol.get("turn_mode", "mouse"),
                "ai_base_url": ai.get("base_url", ""),
                "ai_api_key": ai.get("api_key", ""),
                "ai_model": ai.get("model", ""),
                "ai_vision_model": ai.get("vision_model", ""),
            }
            return {"success": True, "settings": settings}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def engine_save_settings(self, params: dict) -> dict:
        """将前端调整的挂机引擎参数自动保存到 settings.yaml"""
        if not params:
            return {"success": False, "message": "参数为空"}
        self._last_engine_params = params
        self._save_engine_settings(params)
        return {"success": True}

    # ========================================
    # 5.5 AI 视觉识别设置 (状态栏识图)
    # ========================================

    def ai_vision_get_settings(self) -> dict:
        from src.gui.ai_vision import load_config
        return {"success": True, "settings": load_config()}

    def ai_vision_save_settings(self, params: dict) -> dict:
        from src.gui import ai_vision
        if not isinstance(params, dict) or not params:
            return {"success": False, "message": "参数为空"}
        cfg = ai_vision.load_config()
        if "enabled" in params:
            cfg["enabled"] = bool(params["enabled"])
        if "base_url" in params:
            cfg["base_url"] = str(params["base_url"]).strip()
        if "api_key" in params:
            cfg["api_key"] = str(params["api_key"]).strip()
        if "model" in params:
            cfg["model"] = str(params["model"]).strip()
        if "prompt" in params:
            cfg["prompt"] = str(params["prompt"])
        if "interval_s" in params:
            try:
                cfg["interval_s"] = max(3, min(600, int(float(params["interval_s"]))))
            except Exception:
                pass
        if "template" in params:
            cfg["template"] = str(params["template"]).strip()
        # AI 决策配置字段(持久化到同一个 json, 由 ai_decision.py 读取)
        decision_fields = ["ai_decision_enabled", "ai_decision_base_url",
                          "ai_decision_api_key", "ai_decision_model",
                          "ai_decision_interval_s"]
        for k in decision_fields:
            if k in params:
                cfg[k] = params[k]
        ai_vision.save_config(cfg)
        self._enqueue_log("AI 视觉识别配置已保存", "info")
        return {"success": True, "settings": cfg}

    def ai_vision_test(self) -> dict:
        """截一帧游戏画面, 按状态栏 ROI 裁图发给多模态 AI, 返回识别结果"""
        from src.pvp.roi_template import load_template, resolve_rois
        try:
            info, frame = self._capture_frame()
        except Exception as e:
            return {"success": False, "message": str(e)}
        try:
            from src.gui import ai_vision
            cfg = ai_vision.load_config()
            tpl = load_template(cfg.get("template") or "pvp状态")
            if not tpl or not tpl.get("rois"):
                return {"success": False,
                        "message": f"ROI 模板「{cfg.get('template') or 'pvp状态'}」不存在或没有框位, 请先在视觉工坊框状态栏"}
            rois = resolve_rois(cfg.get("template") or "pvp状态",
                                frame.shape[1], frame.shape[0])
            crops = ai_vision.crop_frame_to_jpeg_b64(frame, rois or [])
            if not crops:
                return {"success": False, "message": "状态栏裁图失败, 请检查模板框位"}
            result = ai_vision.ask_vision(cfg, crops)
            if not result.get("ok"):
                self._enqueue_log(f"AI 识别失败: {result.get('error')}", "error")
                return {"success": False, "message": result.get("error", "AI 识别失败")}
            self._enqueue_log(f"AI 识别完成({result.get('elapsed')}s): {result.get('text', '')[:60]}", "success")
            return {"success": True, "text": result.get("text", ""),
                    "elapsed": result.get("elapsed"),
                    "crops": [{"id": c["id"], "image": c["data_url"]} for c in crops]}
        except Exception as e:
            return {"success": False, "message": f"AI 识别异常: {e}"}

    # ========================================
    # 5.6 AI 陪玩伙伴设置 (对局弹幕伙伴)
    # ========================================

    def ai_companion_get_settings(self) -> dict:
        from src.gui.ai_companion import load_config
        return {"success": True, "settings": load_config()}

    def ai_companion_save_settings(self, params: dict) -> dict:
        from src.gui import ai_companion
        if not isinstance(params, dict) or not params:
            return {"success": False, "message": "参数为空"}
        cfg = ai_companion.load_config()
        if "enabled" in params:
            cfg["enabled"] = bool(params["enabled"])
            self._ai_companion_enabled = cfg["enabled"]
        if "base_url" in params:
            cfg["base_url"] = str(params["base_url"]).strip()
        if "api_key" in params:
            cfg["api_key"] = str(params["api_key"]).strip()
        if "model" in params:
            cfg["model"] = str(params["model"]).strip()
        if "persona" in params:
            p = str(params["persona"]).strip()
            if p in ai_companion.PERSONAS or not p:
                cfg["persona"] = p or "tsundere"
            else:
                cfg["persona"] = p   # 允许手写人设 id
        if "custom_persona" in params:
            cfg["custom_persona"] = str(params["custom_persona"])
        if "interval_min" in params:
            try:
                cfg["interval_min"] = max(5, min(600, int(float(params["interval_min"]))))
            except Exception:
                pass
        ai_companion.save_config(cfg)
        self._enqueue_log("AI 陪玩伙伴配置已保存", "info")
        return {"success": True, "settings": cfg}

    # ========================================
    # 5.7 AI 自玩操作 (MCP 动作注入)
    # ========================================

    _PVP_ACT_DELAY = 0.3  # 动作间默认间隔(秒), MCP 可调


    # ========================================
    # 4. 配置中心 API
    # ========================================

    def config_load(self, name: str) -> dict:
        """读取配置并解析为对象 (前端视觉调试台加载 roi_config 用; JSON/YAML 均可)"""
        try:
            path = CONFIG_DIR / name
            if not path.exists():
                return {"success": False, "message": f"配置不存在: {name}", "data": None}
            content = path.read_text(encoding="utf-8")
            if name.endswith(".yaml") or name.endswith(".yml"):
                import yaml
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "message": str(e), "data": None}

    def config_list(self) -> dict:
        items = []
        for name, meta in CONFIG_FILES.items():
            path = CONFIG_DIR / name
            items.append({
                "name": name,
                "title": meta.get("title", name),
                "icon": meta.get("icon", "📄"),
                "type": meta["type"],
                "desc": meta["desc"],
                "page_hint": meta.get("page_hint", ""),
                "gui_page": meta.get("gui_page", ""),
                "fields": meta.get("fields", []),
                "exists": path.exists(),
                "size": path.stat().st_size if path.exists() else 0,
            })
        return {"success": True, "files": items}

    def config_read(self, name: str) -> dict:
        if not DEV_MODE:
            return {"success": False, "message": "配置文件编辑仅开发者模式可用"}
        if name not in CONFIG_FILES:
            return {"success": False, "message": f"未知配置: {name}"}
        path = CONFIG_DIR / name
        if not path.exists():
            return {"success": True, "content": "", "empty": True}
        try:
            return {"success": True, "content": path.read_text(encoding="utf-8")}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def config_save(self, name: str, content: str) -> dict:
        if not DEV_MODE:
            return {"success": False, "message": "配置文件编辑仅开发者模式可用"}
        if name not in CONFIG_FILES:
            return {"success": False, "message": f"未知配置: {name}"}
        meta = CONFIG_FILES[name]
        try:
            if meta["type"] == "json":
                json.loads(content)
            elif meta["type"] == "yaml":
                import yaml
                yaml.safe_load(content)
        except Exception as e:
            return {"success": False, "message": f"格式语法错误,未保存: {e}"}

        path = CONFIG_DIR / name
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except Exception as e:
            return {"success": False, "message": str(e)}

        self._enqueue_log(f"配置已保存: {name}", "success")

        # ROI 配置保存后,实时识别下一帧起用新坐标
        if name == "roi_config.json":
            self._live_pipeline = None
            self._enqueue_log("ROI 已更新,实时识别将从下一帧使用新坐标", "info")

        # settings.yaml 保存后刷新统一配置缓存
        if name == "settings.yaml":
            try:
                from src.utils.settings import invalidate
                invalidate()
                self._enqueue_log("全局配置缓存已刷新", "info")
            except Exception as e:
                self._enqueue_log(f"刷新配置缓存失败: {e}", "error")

        # 丢球配置保存后立即应用到运行中的工具
        if name == "throw_ball_config.json":
            try:
                data = json.loads(content)
                self.tool.update_config(data)
                self._enqueue_log("丢球工具配置已热加载", "info")
            except Exception as e:
                self._enqueue_log(f"热更新丢球工具配置失败: {e}", "warning")

        return {"success": True}

    def config_reset_default(self, name: str) -> dict:
        """恢复指定配置文件的默认推荐配置"""
        if not DEV_MODE:
            return {"success": False, "message": "配置文件编辑仅开发者模式可用"}
        if name not in CONFIG_FILES:
            return {"success": False, "message": f"未知配置: {name}"}

        defaults = {
            "throw_ball_config.json": json.dumps({
                "normal_min": 0.35,
                "normal_max": 0.5,
                "bomber_charge_min": 0.3,
                "bomber_charge_max": 0.5,
                "bomber_hover_min": 2.0,
                "bomber_hover_max": 2.2,
                "skill_min": 1.0,
                "skill_max": 2.0,
                "stop_after_count": 0,
                "stop_after_minutes": 0,
                "exit_on_battle": True,
            }, indent=2, ensure_ascii=False),
            "settings.yaml": (
                "capture:\n"
                "  fps: 30\n"
                "  region:\n"
                "    left: 0\n"
                "    top: 0\n"
                "    width: 1920\n"
                "    height: 1080\n"
                "battle:\n"
                "  catch_hp: 50\n"
                "  open_ball_key: w\n"
                "  ball_slot_key: '1'\n"
                "  ball_ui_wait: 0.8\n"
                "  ball_cooldown: 3.0\n"
                "  flee_hp: 8\n"
                "  flee_key: ''\n"
                "  skills:\n"
                "  - '1'\n"
                "  skill_interval_min: 1.2\n"
                "  skill_interval_max: 2.0\n"
                "  battle_timeout: 240\n"
                "  max_balls_per_battle: 30\n"
                "patrol:\n"
                "  enabled: true\n"
                "  move_key: w\n"
                "  move_min: 1.5\n"
                "  move_max: 3.0\n"
                "  turn_mode: mouse\n"
                "  turn_chance: 0.35\n"
                "  stuck_limit: 6\n"
                "fsm:\n"
                "  battle_timeout: 300\n"
                "  wait_timeout: 60\n"
                "gui:\n"
                "  width: 1150\n"
                "  height: 780\n"
                "  theme: dark\n"
            ),
            "roi_config.json": json.dumps({
                "enemy_name": {"left": 0.5281, "top": 0.0528, "width": 0.1349, "height": 0.0389, "label": "精灵名称"},
                "enemy_elements": {"left": 0.6698, "top": 0.0528, "width": 0.0271, "height": 0.0389, "label": "属性"},
                "enemy_hp": {"left": 0.7042, "top": 0.0611, "width": 0.0594, "height": 0.0306, "label": "敌方血量"},
                "battle_left_indicator": {"left": 0.0323, "top": 0.0343, "width": 0.0469, "height": 0.0435, "label": "左角标"},
                "battle_right_indicator": {"left": 0.9208, "top": 0.0343, "width": 0.0469, "height": 0.0435, "label": "右角标"}
            }, indent=2, ensure_ascii=False),
        }

        if name not in defaults:
            return {"success": False, "message": f"该配置文件暂无内置重置模板"}

        content = defaults[name]
        res = self.config_save(name, content)
        if res.get("success"):
            return {"success": True, "content": content}
        return res

        # 丢球配置保存后立即应用到运行中的工具
        if name == "throw_ball_config.json":
            try:
                data = json.loads(content)
                for key, value in self._validate_throw_params(data).items():
                    setattr(self.tool, key, value)
                self._enqueue_log("丢球延迟已热应用到当前工具实例", "info")
            except Exception as e:
                self._enqueue_log(f"热应用丢球配置失败: {e}", "error")
        return {"success": True}
