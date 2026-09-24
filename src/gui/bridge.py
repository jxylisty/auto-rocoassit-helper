"""大前端桥接层 —— 瘦门面。

原 4700+ 行已按职责拆分为 Mix-in(见各 bridge_*.py), 本文件只保留:
- bridge_common.py  模块级常量与配置注册表(路径/CONFIG_FILES/DEV_MODE/TOOLS)
- AppBridge         继承拼装各 Mix-in, 仅负责 __init__ 组件组装
- Api               PyWebview js_api 薄转发层

Mix-in 一览:
  bridge_widget    窗口生命周期/悬浮窗定位与状态/热键/状态推送
  bridge_auth      账户登录/卡密验证/在线更新
  bridge_daily     日常任务与调度
  bridge_runtime   关闭与日志/模式协调/丢球配置/模式与总状态
  bridge_game      游戏窗口与启动
  bridge_vision    视觉调试/ROI 工坊与模板/实时识别
  bridge_pvp       战斗引擎/PVP 采集与主循环/状态沿消费
  bridge_pvp_data  PVP 查询计算/背包/历史
  bridge_settings  引擎与 AI 设置/配置中心
  bridge_tools     工具箱
"""

from src.gui.bridge_common import PROJECT_ROOT, CONFIG_DIR, SCREENSHOT_DIR, WEB_DIR, STUDIO_DIR, CONFIG_FILES, CONFIG_SCHEMA, CONFIG_PAIRS, DEV_MODE, TOOLS
import queue
import threading
from pathlib import Path
from src.gui.updater import AutoUpdater, check_update, apply_update, updater_status
from auto_throw_ball import AutoThrowBall

from src.gui.bridge_widget import WidgetMixin
from src.gui.bridge_auth import AuthUpdateMixin
from src.gui.bridge_daily import DailyMixin
from src.gui.bridge_runtime import RuntimeMixin
from src.gui.bridge_game import GameMixin
from src.gui.bridge_vision import VisionMixin
from src.gui.bridge_pvp import PvpEngineMixin
from src.gui.bridge_pvp_data import PvpDataMixin
from src.gui.bridge_settings import SettingsMixin
from src.gui.bridge_tools import ToolsMixin


class AppBridge(
    WidgetMixin, AuthUpdateMixin, DailyMixin, RuntimeMixin, GameMixin,
    VisionMixin, PvpEngineMixin, PvpDataMixin, SettingsMixin, ToolsMixin,
):
    """大前端前后端桥梁"""

    def __init__(self):
        # C 扩展预热: 在任何后台线程启动之前完成首次导入, 消除
        # "线程内首次 import win32ui 撞上 keyboard 初始化的 GC" 导致的
        # access violation 随机闪退(启动日志 6 次转储同一签名)。
        # 这里再兜一次, 任何入口(含独立工具/ROI 工坊)走 AppBridge 都被保护。
        try:
            from src.gui.window_sizing import prewarm_c_extensions
            prewarm_c_extensions()
        except Exception:
            pass

        self._window = None
        self._log_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._pusher_thread = None
        # 自动更新器: 后台静默检查 GitHub 新版本(仅提示, 不自动改文件)
        self._update_hint_sent = None
        self.updater = AutoUpdater(on_update_available=self._notify_update_available)

        # 丢球核心工具
        self.tool = AutoThrowBall(on_log=self._enqueue_log)
        self.tool._frame_provider = self._capture_frame
        # 日常任务执行器(MAA 式): 复用截图管线与全停体系
        try:
            from src.tasks.daily_runner import DailyRunner
            self.daily = DailyRunner(self._capture_frame, self._enqueue_log,
                                     launch_cb=self.game_launch)
        except Exception:
            self.daily = None
        # 快捷键 F4/F9/F10 直接调 tool 内部方法, 绕过 GUI 入口的互斥逻辑,
        # 用钩子补上: 快捷键启动丢球组前自动停止挂机引擎/PVP识别
        self.tool.conflict_hook = lambda: self._stop_conflicting_modes("throw")
        self._load_throw_config()

        # 咕噜球监视(战斗前 1 号位, 蓄力窗口异步采样; ROI/模板缺失时自动禁用)
        try:
            from src.perception.ball_watcher import BallSlotWatcher
            self.ball_watcher = BallSlotWatcher(
                frame_provider=self._capture_frame, on_log=self._enqueue_log)
            if self.ball_watcher.enabled:
                self.tool.attach_ball_watcher(self.ball_watcher)
        except Exception as e:
            self.ball_watcher = None
            self._enqueue_log(f"咕噜球监视初始化失败(不影响丢球): {e}", "warning")

        # 视觉调试状态
        self._last_shot_path: Path | None = None  # 最近一次保存的截图
        self._last_frame = None                    # 最近一次识别用的帧(numpy)
        self._pvp_float_visible = False    # F2 显示状态(同一窗口)

        # 实时识别
        self._live_running = False
        self._live_thread = None
        self._live_interval = 0.15                  # 秒
        self._live_pipeline = None
        self._live_black_warned = False
        self._live_last_frame = None               # 帧差检测缓存
        self._fast_cap = None                      # FastCapture 单例
        self._live_max_width = 960                 # 实时预览画质(fast=960/hd=1440/full=0原尺寸)

        # 战斗引擎
        from src.states.battle_engine import BattleEngine
        self.engine = BattleEngine(
            frame_provider=self._live_capture_frame,
            on_log=self._enqueue_log,
            dry_run=False)

        # 异色全停回调: 引擎发现异色时联动停所有其它任务(丢球助手等)
        self.engine._stop_all_cb = lambda reason: self.stop_all()

        # PVP 悬浮窗
        self._pvp_float_window = None
        self._pvp_float_visible = False
        self._pvp_float_loaded = False

        # 观察模式: 挂机悬浮窗的被动战情监视(引擎/工具都没跑时才工作)
        self._watch = None            # {in_battle, enemy_name, enemy_hp}
        self._watch_pipeline = None
        self._watch_started = threading.Event()
        self._last_widget_pos = None  # 悬浮窗物理像素落点(show 后重钉)

        # PVP 实时识别引擎
        self._pvp_running = False
        self._pvp_thread = None
        self._pvp_interval = 0.5  # 秒，每 500ms 识别一帧

        # AI 决策缓存(由 /recommend 端点异步更新)
        self._ai_recommendation: dict | None = None
        self._ai_decision_lock = threading.Lock()

        # 模式控制器 (Step 3: 生命周期隔离)
        from src.states.mode_controller import ModeController
        self.mode_ctrl = ModeController()

        # 工具子进程: id -> {"proc", "name"}
        self._tool_procs: dict[str, dict] = {}


class Api:
    """pywebview 自动把此类方法暴露给前端 JavaScript"""

    def __init__(self, bridge: AppBridge):
        self._bridge = bridge

    # 账户登录/卡密 (前端侧栏激活入口依赖这三个 API)
    def auth_status(self):
        return self._bridge.auth_status()

    def auth_activate(self, code):
        return self._bridge.auth_activate(code)

    def auth_logout(self):
        return self._bridge.auth_logout()

    # 运行模式
    def get_app_mode(self):
        return self._bridge.get_app_mode()

    # 丢球
    def toggle_normal(self):
        return self._bridge.toggle_normal()

    def toggle_bomber(self):
        return self._bridge.toggle_bomber()

    def toggle_skill(self):
        return self._bridge.toggle_skill()

    def stop_all(self):
        return self._bridge.stop_all()

    def update_config(self, params):
        return self._bridge.update_config(params)

    # 视觉
    def vision_status(self):
        return self._bridge.vision_status()

    def vision_capture(self, front: bool = True, source: str = "main"):
        return self._bridge.vision_capture(front, source)

    def vision_analyze(self, front: bool = True, source: str = "main"):
        return self._bridge.vision_analyze(front, source)

    def vision_ocr_preview(self, rois=None):
        return self._bridge.vision_ocr_preview(rois)

    def vision_save_shot(self):
        return self._bridge.vision_save_shot()

    def vision_live_start(self):
        return self._bridge.vision_live_start()

    def vision_live_stop(self):
        return self._bridge.vision_live_stop()

    def vision_live_quality(self, quality: str = "fast"):
        return self._bridge.vision_live_quality(quality)

    # ROI 标注工坊
    def roi_studio_open(self):
        return self._bridge.roi_studio_open()

    def roi_studio_state(self):
        return self._bridge.roi_studio_state()

    def roi_studio_save(self, name, base_resolution, rois):
        return self._bridge.roi_studio_save(name, base_resolution, rois)

    # 配置中心
    def config_load(self, name):
        return self._bridge.config_load(name)

    # 战斗引擎
    def engine_start(self, dry_run=False, params=None):
        return self._bridge.engine_start(dry_run, params)

    def engine_stop(self):
        return self._bridge.engine_stop()

    def engine_status(self):
        return self._bridge.engine_status()

    def engine_get_settings(self):
        return self._bridge.engine_get_settings()

    def engine_save_settings(self, params):
        return self._bridge.engine_save_settings(params)

    # AI 视觉识别
    def ai_vision_get_settings(self):
        return self._bridge.ai_vision_get_settings()

    def ai_vision_save_settings(self, params):
        return self._bridge.ai_vision_save_settings(params)

    def ai_vision_test(self):
        return self._bridge.ai_vision_test()

    # AI 陪玩伙伴
    def ai_companion_get_settings(self):
        return self._bridge.ai_companion_get_settings()

    def ai_companion_save_settings(self, params):
        return self._bridge.ai_companion_save_settings(params)

    # AI 自玩操作
    def pvp_act(self, action, delay=None):
        return self._bridge.pvp_act(action, delay)

    # 工具箱
    def tools_list(self):
        return self._bridge.tools_list()

    def tool_start(self, tool_id):
        return self._bridge.tool_start(tool_id)

    def tool_stop(self, tool_id):
        return self._bridge.tool_stop(tool_id)

    # 配置中心
    def config_list(self):
        return self._bridge.config_list()

    def config_read(self, name):
        return self._bridge.config_read(name)

    def config_save(self, name, content):
        return self._bridge.config_save(name, content)

    def config_reset_default(self, name):
        return self._bridge.config_reset_default(name)

    def roi_template_list(self):
        return self._bridge.roi_template_list()

    def roi_template_save(self, name, base_resolution, rois):
        return self._bridge.roi_template_save(name, base_resolution, rois)

    def roi_template_load(self, name):
        return self._bridge.roi_template_load(name)

    def roi_template_export(self, name):
        return self._bridge.roi_template_export(name)

    def roi_template_import(self, json_str):
        return self._bridge.roi_template_import(json_str)

    def roi_template_delete(self, name):
        return self._bridge.roi_template_delete(name)

    def roi_template_set_active(self, name, mode="pvp"):
        return self._bridge.roi_template_set_active(name, mode)

    def roi_export_crop(self, rect, save_name=None):
        return self._bridge.roi_export_crop(rect, save_name)

    def mode_get(self):
        return self._bridge.mode_get()

    def mode_switch(self, mode):
        return self._bridge.mode_switch(mode)

    # 状态
    def get_state(self):
        return self._bridge.get_state()

    def set_on_top(self, enabled):
        return self._bridge.set_on_top(enabled)

    def widget_toggle(self):
        return self._bridge.widget_toggle()

    def minimize_window(self):
        return self._bridge.minimize_window()

    def move_window_by(self, dx, dy):
        return self._bridge.move_window_by(dx, dy)
    def window_move_by(self, dx, dy):
        return self._bridge.window_move_by(dx, dy)

    def window_resize_by(self, dw, dh):
        return self._bridge.window_resize_by(dw, dh)
    def window_get_size(self):
        return self._bridge.window_get_size()

    def window_resize_to(self, width, height):
        return self._bridge.window_resize_to(width, height)


    def window_close(self):
        return self._bridge.window_close()
    def update_check(self):
        return self._bridge.update_check()

    def update_apply(self):
        return self._bridge.update_apply()

    def update_status(self):
        return self._bridge.update_status()

    def pokedex_data(self):
        return self._bridge.pokedex_data()
    def daily_list(self):
        return self._bridge.daily_list()

    def daily_save(self, tasks):
        return self._bridge.daily_save(tasks)

    def daily_run(self, task_id):
        return self._bridge.daily_run(task_id)

    def daily_run_queue(self, task_ids):
        return self._bridge.daily_run_queue(task_ids)

    def daily_stop(self):
        return self._bridge.daily_stop()

    def daily_status(self):
        return self._bridge.daily_status()


    def schedule_set(self, enabled, hh=19, mm=0, duration_min=120, mode="engine"):
        return self._bridge.schedule_set(enabled, hh, mm, duration_min, mode)

    def schedule_get(self):
        return self._bridge.schedule_get()



    def bag_scan(self):
        return self._bridge.bag_scan()

    def bag_open(self):
        return self._bridge.bag_open()

    def bag_open_and_scan(self):
        return self._bridge.bag_open_and_scan()

    def widget_resize(self, width=340, height=335):
        return self._bridge.widget_resize(width, height)

    def pvp_float_resize(self, width=360, height=540):
        return self._bridge.pvp_float_resize(width, height)

    # PVP 对战助手
    def pvp_search_pets(self, query=""):
        return self._bridge.pvp_search_pets(query)

    def pvp_get_pet(self, seq, title=None):
        return self._bridge.pvp_get_pet(seq, title)

    def pvp_search_skills(self, query=""):
        return self._bridge.pvp_search_skills(query)

    def pvp_calc_vs(self, atk_seq, def_seq, skill_name, atk_ivs=None, def_ivs=None):
        return self._bridge.pvp_calc_vs(atk_seq, def_seq, skill_name, atk_ivs, def_ivs)

    def pvp_get_all_pets(self):
        return self._bridge.pvp_get_all_pets()

    def pvp_get_all_skills(self):
        return self._bridge.pvp_get_all_skills()

    def pvp_calc_quick(self, atk_val, def_val, power, skill_type="物攻", skill_attr="普通", atk_attrs=None, def_attrs=None):
        return self._bridge.pvp_calc_quick(atk_val, def_val, power, skill_type, skill_attr, atk_attrs, def_attrs)

    def pvp_calc_panels(self, seq, high_ivs=None, iv_value=10, nature_up=None, nature_down=None):
        return self._bridge.pvp_calc_panels(seq, high_ivs, iv_value, nature_up, nature_down)

    def pvp_get_pet_skills_full(self, seq):
        return self._bridge.pvp_get_pet_skills_full(seq)

    def pvp_get_pet_preset(self, seq):
        return self._bridge.pvp_get_pet_preset(seq)

    def pvp_recognize(self):
        return self._bridge.pvp_recognize()

    def pvp_calc_all_skills(self, atk_seq, def_seq, atk_high_ivs=None, atk_iv_value=10, def_high_ivs=None, def_iv_value=10, atk_nature_up=None, atk_nature_down=None, def_nature_up=None, def_nature_down=None):
        return self._bridge.pvp_calc_all_skills(atk_seq, def_seq, atk_high_ivs, atk_iv_value, def_high_ivs, def_iv_value, atk_nature_up, atk_nature_down, def_nature_up, def_nature_down)

    def pvp_float_toggle(self):
        return self._bridge.pvp_float_toggle()

    def pvp_float_update(self, data):
        return self._bridge.pvp_float_update(data)

    def pvp_get_asset(self, asset_type, key):
        return self._bridge.pvp_get_asset(asset_type, key)

    def pvp_engine_start(self):
        return self._bridge.pvp_engine_start()

    def pvp_engine_stop(self):
        return self._bridge.pvp_engine_stop()

    def pvp_engine_status(self):
        return self._bridge.pvp_engine_status()

    def pvp_collector_start(self):
        return self._bridge.pvp_collector_start()

    def pvp_collector_stop(self):
        return self._bridge.pvp_collector_stop()

    def pvp_collector_status(self):
        return self._bridge.pvp_collector_status()

    def pvp_collector_manual(self):
        return self._bridge.pvp_collector_manual()

    # 官方资源自动同步
    def resource_sync(self):
        return self._bridge.resource_sync()

    def resource_get_stats(self):
        return self._bridge.resource_get_stats()

    # 天梯战报与 ELO 分析
    def pvp_get_history(self, limit=50, offset=0, filter_result="ALL"):
        return self._bridge.pvp_get_history(limit, offset, filter_result)

    def pvp_get_history_stats(self):
        return self._bridge.pvp_get_history_stats()

    def pvp_record_match(self, match_data):
        return self._bridge.pvp_record_match(match_data)

    def pvp_clear_history(self):
        return self._bridge.pvp_clear_history()

    def pvp_generate_mock_history(self, count=15):
        return self._bridge.pvp_generate_mock_history(count)


__all__ = ['AppBridge', 'Api']
