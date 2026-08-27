# -*- coding: utf-8 -*-
"""
大前端桥接层 AppBridge

五个部分:
1. 丢球工具   —— 包装 AutoThrowBall,延迟参数实时可调
2. 视觉调试   —— 游戏窗口截图预览 + 识别管线结果(纯读屏,无键鼠操作)
3. 工具箱     —— 子进程启动 tools/ 独立工具,CLI 输出回流日志
4. 配置中心   —— settings.yaml / roi_config.json / throw_ball_config.json 读写校验
5. 任务注册表 —— 底部任务栏数据源(正在运行的模式/工具)

设计原则: 暴露给 JS 的方法只做轻量操作,耗时动作在后台线程/子进程。
"""

import base64
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auto_throw_ball import AutoThrowBall  # noqa: E402

# ========================================
# 配置中心: 可编辑文件注册表
# ========================================

CONFIG_DIR = PROJECT_ROOT / "data" / "config"
CONFIG_FILES = {
    "settings.yaml": {
        "type": "yaml",
        "desc": "全局设置（截图参数 / FSM 超时 / 预留项）",
    },
    "roi_config.json": {
        "type": "json",
        "desc": "识别区域 ROI（归一化坐标，视觉调试台叠加框同源）",
    },
    "throw_ball_config.json": {
        "type": "json",
        "desc": "丢球延迟参数（丢球助手页滑杆自动写入）",
    },
}

# 每个丢球延迟参数的合法范围（秒）
CONFIG_SCHEMA = {
    "normal_min":        (0.1, 3.0),
    "normal_max":        (0.1, 3.0),
    "bomber_charge_min": (0.05, 2.0),
    "bomber_charge_max": (0.05, 2.0),
    "bomber_hover_min":  (0.3, 8.0),
    "bomber_hover_max":  (0.3, 8.0),
    "skill_min":         (0.2, 10.0),
    "skill_max":         (0.2, 10.0),
}
CONFIG_PAIRS = [
    ("normal_min", "normal_max"),
    ("bomber_charge_min", "bomber_charge_max"),
    ("bomber_hover_min", "bomber_hover_max"),
    ("skill_min", "skill_max"),
]

# ========================================
# 工具箱: 可启动工具注册表
# ========================================
# arg 策略:
#   none  —— 无参数直接跑
#   shot  —— 先自动截一张游戏画面到 data/screenshots 再作为参数传入
#   last  —— 优先用最近一次调试台截图,其次用 data/screenshots 最新文件

TOOLS = [
    {"id": "snip", "name": "手动框选截图", "script": "tools/snip_capture.py",
     "gui": True, "arg": "none", "desc": "全屏拖拽框选任意区域,保存后自动打开裁剪工具(推荐做模板用)"},
    {"id": "crop", "name": "模板裁剪工具", "script": "tools/crop_template_tool.py",
     "gui": True, "arg": "shot", "desc": "自动截取游戏窗口并打开裁剪器(依赖窗口截图,失败时请用框选截图)"},
    {"id": "envcheck", "name": "截图环境诊断", "script": "tools/check_capture_env.py",
     "gui": False, "arg": "none", "desc": "检查窗口截图能力,诊断输出到日志"},
    {"id": "demovision", "name": "视觉管线演示", "script": "tools/demo_vision_pipeline.py",
     "gui": False, "arg": "last", "desc": "对最近截图跑完整识别,JSON 结果输出到日志"},
    {"id": "roiexport", "name": "ROI 切片导出", "script": "tools/export_roi_samples.py",
     "gui": False, "arg": "last", "desc": "按 ROI 配置把最近截图切成小图批量导出"},
    {"id": "clicker", "name": "鼠标连点器", "script": "tools/auto_click_macro.py",
     "gui": True, "arg": "none", "desc": "独立小窗,F6 取坐标 / F7 开关 / F10 急停（全局热键）"},
]
SCREENSHOT_DIR = PROJECT_ROOT / "data" / "screenshots"


class AppBridge:
    """大前端前后端桥梁"""

    def __init__(self):
        self._window = None
        self._log_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._pusher_thread = None

        # 丢球核心工具
        self.tool = AutoThrowBall(on_log=self._enqueue_log)
        self._load_throw_config()

        # 视觉调试状态
        self._last_shot_path: Path | None = None  # 最近一次保存的截图
        self._last_frame = None                    # 最近一次识别用的帧(numpy)
        self._paddleocr = None                     # PaddleOCR 实例（懒加载）

        # 实时识别
        self._live_running = False
        self._live_thread = None
        self._live_interval = 0.15                  # 秒
        self._live_pipeline = None
        self._live_black_warned = False
        self._live_last_frame = None               # 帧差检测缓存
        self._fast_cap = None                      # FastCapture 单例

        # 战斗引擎
        from src.states.battle_engine import BattleEngine
        self.engine = BattleEngine(
            frame_provider=self._live_capture_frame,
            on_log=self._enqueue_log,
            dry_run=False)

        # PVP 悬浮窗
        self._pvp_float_window = None
        self._pvp_float_visible = False
        self._pvp_float_loaded = False

        # 模式控制器 (Step 3: 生命周期隔离)
        from src.states.mode_controller import ModeController
        self.mode_ctrl = ModeController()

        # 工具子进程: id -> {"proc", "name"}
        self._tool_procs: dict[str, dict] = {}

    # ========================================
    # 生命周期
    # ========================================

    def set_window(self, window):
        self._window = window
        self._start_log_pusher()

    def set_widget_window(self, window):
        """设置悬浮状态窗引用(初始隐藏,由用户/热键唤出)"""
        self._widget = window
        self._widget_visible = False

    def set_on_top(self, enabled: bool) -> dict:
        """控制台窗口置顶开关(悬浮在游戏上方查看,不抢游戏焦点)"""
        if not self._window:
            return {"success": False, "message": "窗口未就绪"}
        try:
            self._window.on_top(bool(enabled))
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ========================================
    # 悬浮状态窗
    # ========================================

    def widget_toggle(self) -> dict:
        """显示/隐藏悬浮状态窗"""
        if not getattr(self, "_widget", None):
            return {"success": False, "message": "悬浮窗未创建"}
        try:
            if self._widget_visible:
                self._widget.hide()
                self._widget_visible = False
            else:
                self._widget.show()
                self._widget_visible = True
            return {"success": True, "visible": self._widget_visible}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def widget_resize(self, height: int) -> dict:
        """悬浮窗折叠/展开时调整窗口高度"""
        if not getattr(self, "_widget", None):
            return {"success": False}
        try:
            h = max(36, min(400, int(height)))
            self._widget.resize(280, h)
            return {"success": True}
        except Exception:
            return {"success": False}

    def enable_hotkeys(self):
        """注册全局快捷键"""
        try:
            self.tool.register_hotkeys()
        except Exception as e:
            self._enqueue_log(f"快捷键注册失败: {e}", "error")
        try:
            import keyboard
            keyboard.add_hotkey('f2', self._hotkey_widget)
            keyboard.add_hotkey('f8', self._hotkey_snip)
            keyboard.add_hotkey('f11', self._emergency_stop)
            keyboard.add_hotkey('f12', self._hotkey_pvp_float)
            self._enqueue_log("快捷键: F2悬浮窗/F8截图/F11急停/F12 PVP悬浮窗", "info")
        except Exception as e:
            self._enqueue_log(f"快捷键注册失败: {e}", "error")

    def _hotkey_widget(self):
        """F2: 切换挂机悬浮窗 → 切换至 afk 模式"""
        self.mode_ctrl.switch_to("afk")
        self.widget_toggle()

    def _hotkey_pvp_float(self):
        """F12: 切换 PVP 悬浮窗 → 切换至 pvp 模式"""
        if self.mode_ctrl.current_mode != "pvp":
            self.mode_ctrl.switch_to("pvp")
        self.pvp_float_toggle()

    def _emergency_stop(self):
        """F11 全局急停:战斗引擎 + 全部丢球模式 + 实时识别"""
        self._enqueue_log("!! F11 全局急停 !!", "error")
        try:
            self.engine.stop("F11 急停")
        except Exception:
            pass
        try:
            self.tool.stop_all()
        except Exception:
            pass
        self._live_running = False
        try:
            self._window.evaluate_js("setLiveUI(false); refreshState();")
        except Exception:
            pass

    def _hotkey_snip(self):
        """F8: 打开手动框选截图工具(截屏幕可见区域,不依赖窗口句柄)"""
        threading.Thread(target=self._snip_flow, daemon=True).start()

    def _snip_flow(self, save_only: bool = False):
        script = PROJECT_ROOT / "tools" / "snip_capture.py"
        cmd = [sys.executable, str(script)] + (["--save-only"] if save_only else [])
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE)
            self._enqueue_log(f"框选截图工具已打开(PID {proc.pid}),拖拽框选后自动保存并打开裁剪工具", "info")
        except Exception as e:
            self._enqueue_log(f"打开截图工具失败: {e}", "error")

    def shutdown(self):
        self._stop_event.set()
        self._live_running = False
        # 关闭抓图线程和 FastCapture
        if self._fast_cap:
            self._fast_cap.close()
            self._fast_cap = None
        try:
            self.engine.stop("窗口关闭")
        except Exception:
            pass
        try:
            self.tool.stop_all()
        except Exception:
            pass
        for tool_id in list(self._tool_procs):
            self._kill_tool(tool_id)
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass

    # ========================================
    # 日志推送
    # ========================================

    def _enqueue_log(self, message, level="info"):
        self._log_queue.put((str(message), level))

    def _start_log_pusher(self):
        if self._pusher_thread and self._pusher_thread.is_alive():
            return

        def _pusher_loop():
            while not self._stop_event.is_set():
                try:
                    message, level = self._log_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if not self._window:
                    continue
                try:
                    js = f"addLog({json.dumps(message, ensure_ascii=False)}, {json.dumps(level)})"
                    self._window.evaluate_js(js)
                except Exception:
                    pass

        self._pusher_thread = threading.Thread(target=_pusher_loop, daemon=True, name="LogPusher")
        self._pusher_thread.start()

    # ========================================
    # 1. 丢球工具 API
    # ========================================

    def toggle_normal(self) -> dict:
        return {"success": True, "running": self.tool.toggle()}

    def toggle_bomber(self) -> dict:
        return {"success": True, "running": self.tool.toggle_bomber()}

    def toggle_skill(self) -> dict:
        return {"success": True, "running": self.tool.toggle_skill()}

    def stop_all(self) -> dict:
        self.tool.stop_all()
        return {"success": True}

    def update_config(self, params: dict) -> dict:
        cleaned = self._validate_throw_params(params or {})
        if not cleaned:
            return {"success": False, "message": "没有有效参数"}
        for key, value in cleaned.items():
            setattr(self.tool, key, value)
        self._save_throw_config()
        self._enqueue_log(f"丢球延迟已更新: {cleaned}", "success")
        return {"success": True, "config": self._get_throw_config()}

    @staticmethod
    def _validate_throw_params(params: dict) -> dict:
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

    def _get_throw_config(self) -> dict:
        return {key: getattr(self.tool, key) for key in CONFIG_SCHEMA}

    def _throw_config_path(self) -> Path:
        return CONFIG_DIR / "throw_ball_config.json"

    def _load_throw_config(self):
        path = self._throw_config_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in self._validate_throw_params(data).items():
                setattr(self.tool, key, value)
            self._enqueue_log("已加载丢球延迟配置", "info")
        except Exception as e:
            self._enqueue_log(f"加载丢球配置失败: {e}", "error")

    def _save_throw_config(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            data = {k: round(v, 2) for k, v in self._get_throw_config().items()}
            self._throw_config_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self._enqueue_log(f"保存丢球配置失败: {e}", "error")

    # ========================================
    # 2. 视觉调试 API（只读屏,不做任何键鼠操作）
    # ========================================

    def _find_game_window(self):
        from src.capture.window_capture import find_window
        # 优先按游戏窗口类精确匹配;控制台标题同样含"洛克王国",靠类名+进程排除避免误抓
        info = find_window(class_name="UnrealWindow")
        if info is None:
            info = find_window()
        return info

    @staticmethod
    def _console_overlaps_game(game_rect) -> bool:
        """检查控制台自身窗口是否遮挡了游戏窗口(遮挡时 BitBlt 会截到黑图)"""
        try:
            import os
            import win32gui
            import win32process

            own_pid = os.getpid()
            rects = []

            def _cb(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == own_pid and "洛克王国" in win32gui.GetWindowText(hwnd):
                    rects.append(win32gui.GetWindowRect(hwnd))

            win32gui.EnumWindows(_cb, 0)
            if not rects:
                return False
            cl, ct, cr, cb_ = rects[0]
            gl, gt, gr, gb = game_rect
            return cl < gr and cr > gl and ct < gb and cb_ > gt
        except Exception:
            return False

    def vision_status(self) -> dict:
        """游戏窗口检测（不截图）"""
        try:
            info = self._find_game_window()
        except Exception as e:
            return {"success": False, "message": str(e)}
        if not info:
            return {"success": False, "message": "未找到「洛克王国」窗口"}
        return {"success": True, "title": info.title,
                "width": info.width, "height": info.height}

    def _capture_frame(self):
        """截图一帧游戏画面(mss,禁用BitBlt)"""
        import cv2, numpy as np, mss
        info = self._find_game_window()
        if not info:
            raise RuntimeError("未找到「洛克王国」窗口,请确认游戏已启动")
        left, top, right, bottom = info.rect
        if right - left < 50 or bottom - top < 50:
            raise RuntimeError("游戏窗口过小或最小化")
        with mss.mss() as sct:
            monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
            img = sct.grab(monitor)
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_BGRA2BGR)
        if frame is None or frame.size == 0:
            raise RuntimeError("截图失败")
        return info, frame

    @staticmethod
    def _frame_to_jpeg_dataurl(frame, max_width: int = None) -> str:
        """编码 JPEG 为 base64 dataurl; 实时识别用 max_width=960 压缩,单次截图用原尺寸"""
        from src.capture.fast_capture import FastCapture
        return FastCapture.encode_jpeg(frame, max_width=max_width, quality=75)

    def vision_capture(self) -> dict:
        """截取游戏画面预览"""
        try:
            info, frame = self._capture_frame()
        except Exception as e:
            self._enqueue_log(f"截图失败: {e}", "error")
            return {"success": False, "message": str(e)}
        self._last_frame = frame
        self._enqueue_log(f"已截图 {info.width}x{info.height}（{info.title}）", "success")
        try:
            image = self._frame_to_jpeg_dataurl(frame)
        except Exception as e:
            self._enqueue_log(f"图像编码失败: {e}", "error")
            return {"success": False, "message": f"编码失败: {e}"}
        return {"success": True, "image": image,
                "width": info.width, "height": info.height, "title": info.title}

    def vision_analyze(self) -> dict:
        """截图 + 跑完整识别管线"""
        try:
            info, frame = self._capture_frame()
        except Exception as e:
            self._enqueue_log(f"截图失败: {e}", "error")
            return {"success": False, "message": str(e)}
        self._last_frame = frame

        from src.perception.vision_pipeline import VisionPipeline, DEFAULT_ROI_CONFIG
        try:
            pipeline = VisionPipeline()
            result = pipeline.analyze(frame).to_dict()
        except Exception as e:
            self._enqueue_log(f"识别失败: {e}", "error")
            return {"success": False, "message": f"识别失败: {e}"}

        roi = {}
        try:
            roi = json.loads(DEFAULT_ROI_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass

        battle = result.get("battle") or {}
        self._enqueue_log(
            f"识别完成: 战斗={battle.get('in_battle')} 敌方血量={result.get('enemy_hp')}% "
            f"精灵={result.get('enemy_name')} 属性={result.get('enemy_elements')}", "info")
        return {"success": True, "image": self._frame_to_jpeg_dataurl(frame),  # 单次截图用原尺寸
                "width": info.width, "height": info.height,
                "result": result, "roi": roi}

    def _get_paddleocr(self):
        if self._paddleocr is not None:
            return self._paddleocr
        # 修复 Windows 上 libifcoremd.dll MKL 线程冲突崩溃
        import os
        os.environ.setdefault('OMP_NUM_THREADS', '1')
        os.environ.setdefault('MKL_NUM_THREADS', '1')
        os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
        from paddleocr import PaddleOCR
        try:
            self._paddleocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang='ch',
                ocr_version='PP-OCRv4',
                text_det_limit_side_len=64,
                text_det_thresh=0.1,
                text_det_box_thresh=0.2,
                text_det_unclip_ratio=1.8,
            )
        except Exception:
            # v4 不可用时回退到默认 server 模型
            self._paddleocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang='ch',
                text_det_limit_side_len=64,
                text_det_thresh=0.1,
                text_det_box_thresh=0.2,
                text_det_unclip_ratio=1.8,
            )
        return self._paddleocr

    def vision_ocr_preview(self, rois: dict = None) -> dict:
        """PaddleOCR 批量识别：所有 ROI 拼成一张图，一次 OCR 调用"""
        import cv2, numpy as np
        from src.perception.ocr_reader import OcrNameReader

        if self._last_frame is None:
            try:
                _, self._last_frame = self._capture_frame()
            except Exception as e:
                return {"success": False, "message": str(e)}
        frame = self._last_frame
        fh, fw = frame.shape[:2]

        roi_data = rois or {}
        if not roi_data:
            try:
                roi_data = json.loads(DEFAULT_ROI_CONFIG.read_text(encoding="utf-8"))
            except Exception:
                pass

        try:
            ocr = self._get_paddleocr()
        except Exception as e:
            return {"success": False, "message": f"PaddleOCR 初始化失败: {e}"}

        pet_list = OcrNameReader._load_pets() if hasattr(OcrNameReader, '_load_pets') else []

        # --- 第一阶段：收集所有 ROI 裁剪，拼成一张合成图 ---
        crops = []  # [(roi_id, crop, y_offset, label, is_number)]
        roi_order = []
        total_h = 0
        for roi_id, box in roi_data.items():
            if not box or not box.get("width"):
                continue
            x = int(box["left"] * fw)
            y = int(box["top"] * fh)
            w = int(box["width"] * fw)
            h = int(box["height"] * fh)
            if w <= 0 or h <= 0:
                continue
            crop = frame[y:y+h, x:x+w]
            pad = max(10, min(h, w) // 2)
            padded = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            ph, pw = padded.shape[:2]
            is_number = any(kw in roi_id.lower() for kw in ("hp", "血", "energy", "能量", "power"))
            label = roi_data[roi_id].get("label", roi_id) if isinstance(roi_data[roi_id], dict) else roi_id
            roi_order.append(roi_id)
            crops.append((roi_id, padded, total_h, total_h + ph, label, is_number))
            total_h += ph + 4  # 4px 分隔

        if not crops:
            return {"success": True, "results": {}, "roi": roi_data}

        # 创建合成图
        max_w = max(c[1].shape[1] for c in crops)
        composite = np.zeros((total_h, max_w, 3), dtype=np.uint8)
        for roi_id, crop_img, y0, y1, _, _ in crops:
            composite[y0:y0 + crop_img.shape[0], :crop_img.shape[1]] = crop_img

        # --- 第二阶段：一次 OCR 识别整张合成图 ---
        try:
            res = ocr.predict(composite)
            all_texts = res[0].get('rec_texts', []) if res and res[0] else []
            all_scores = res[0].get('rec_scores', []) if res and res[0] else []
            all_boxes = res[0].get('rec_boxes', []) if res and res[0] else []
        except Exception:
            all_texts, all_scores, all_boxes = [], [], []

        # --- 第三阶段：按 y 位置映射回各 ROI ---
        results = {}
        for roi_id, _, y0, y1, label, is_number in crops:
            # 收集落在该 ROI 范围内的识别结果
            roi_texts = []
            roi_scores = []
            for ti, (text, score) in enumerate(zip(all_texts, all_scores)):
                if ti < len(all_boxes) and len(all_boxes[ti]) >= 1:
                    cy = (all_boxes[ti][0][1] + all_boxes[ti][-1][1]) / 2
                    if y0 <= cy <= y1:
                        roi_texts.append(text)
                        roi_scores.append(score)

            joined = ''.join(roi_texts)
            conf = round(sum(roi_scores) / len(roi_scores), 2) if roi_scores else 0.0

            if is_number:
                joined = ''.join(ch for ch in joined if ch.isdigit() or ch in '%/')

            corrected = False
            if not is_number and joined and pet_list and hasattr(OcrNameReader, '_correct_with_pet_list'):
                cleaned = OcrNameReader._clean(joined) if hasattr(OcrNameReader, '_clean') else joined
                if cleaned:
                    matched = OcrNameReader._correct_with_pet_list(cleaned)
                    if matched and matched[0]:
                        joined = matched[0]
                        corrected = True

            results[roi_id] = {
                "text": joined or "?", "conf": conf,
                "raw": joined, "corrected": corrected,
                "label": label, "is_number": is_number,
            }

        return {"success": True, "results": results, "roi": roi_data}

    # ========================================
    # 实时识别(调试台开关,循环: 截屏可见区域 → 识别 → 推送前端)
    # ========================================

    def vision_live_start(self) -> dict:
        if self._live_running:
            return {"success": True, "message": "已在运行"}
        self._live_running = True
        self._live_black_warned = False
        self._live_pipeline = None  # 每次启动重建(加载最新模板)
        self._live_last_frame = None
        self._live_thread = threading.Thread(target=self._live_loop, daemon=True, name="VisionLive")
        self._live_thread.start()
        self._enqueue_log(f"实时识别已启动(每 {self._live_interval}s 一帧)", "success")
        return {"success": True}

    def vision_live_stop(self) -> dict:
        self._live_running = False
        self._live_last_frame = None
        # 停止后台抓图线程
        if self._fast_cap:
            self._fast_cap.stop_worker()
            self._enqueue_log("后台抓图线程已停止", "info")
        self._enqueue_log("实时识别已停止", "warning")
        return {"success": True}

    # ========================================
    # 战斗引擎 API
    # ========================================

    def engine_start(self, dry_run: bool = False, params: dict | None = None) -> dict:
        if self.engine.running:
            return {"success": False, "message": "引擎已在运行"}
        overrides = self._parse_engine_params(params or {})
        self.engine.dry_run = bool(dry_run)
        ok = self.engine.start(overrides or None)
        if ok and params:
            # 参数同步持久化到 settings.yaml
            self._save_engine_settings(params)
        return {"success": ok}

    def engine_stop(self) -> dict:
        self.engine.stop()
        return {"success": True}

    def engine_status(self) -> dict:
        return self.engine.get_status()

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
            patrol = data.setdefault("patrol", {})
            if params.get("patrol_enabled") is not None:
                patrol["enabled"] = bool(params["patrol_enabled"])
            if params.get("patrol_move_key"):
                patrol["move_key"] = str(params["patrol_move_key"]).strip().lower()
            if params.get("patrol_turn_mode") in ("keys", "mouse"):
                patrol["turn_mode"] = params["patrol_turn_mode"]
            SETTINGS_PATH.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            invalidate()
            self._enqueue_log("引擎参数已保存到 settings.yaml", "info")
        except Exception as e:
            self._enqueue_log(f"保存引擎参数失败: {e}", "error")

    # ========================================
    # 6. PVP 对战助手 API
    # ========================================

    def set_pvp_float_window(self, window):
        """设置 PVP 对战悬浮窗引用"""
        self._pvp_float_window = window
        # 悬浮窗加载完成后标记
        window.events.loaded += lambda: setattr(self, '_pvp_float_loaded', True)

    def pvp_search_pets(self, query: str = "") -> dict:
        from src.pvp import search_pets, get_all_pet_names
        if not query or not query.strip():
            names = get_all_pet_names()
            return {"success": True, "pets": [
                {"name": n, "seq": i + 1} for i, n in enumerate(names[:50])]}
        results = search_pets(query.strip(), limit=30)
        return {"success": True, "pets": [{
            "seq": r["seq"], "name": r["name"], "title": r.get("title", r["name"]),
            "types": r["types"],
        } for r in results]}

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
        from src.pvp import get_all_pet_names
        names = get_all_pet_names()
        return {"success": True, "pets": [
            {"name": n, "seq": i + 1} for i, n in enumerate(names)]}

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

        # 排序：克制→普通→抵抗→状态，同组内伤害降序
        def _sort_key(r):
            if not r["isDamage"]: return (3, 0)
            m = r["attrMultiplier"]
            if m >= 2: return (0, -r["maxDamage"])
            if m >= 1: return (1, -r["maxDamage"])
            return (2, -r["maxDamage"])
        results.sort(key=_sort_key)

        return {"success": True, "atkPanels": atk_panels, "defPanels": def_panels,
                "atkRace": atk_race, "defRace": def_race, "atkTypes": atk_types,
                "defTypes": def_types, "atkName": atk_pet.get("name", "") if atk_pet else "",
                "defName": def_pet.get("name", "") if def_pet else "",
                "skills": results,
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
                cwd=str(lib_dir)
            )
            if result.returncode != 0:
                return {"success": False, "message": f"识别失败: {result.stderr[:200]}"}

            data = _json.loads(result.stdout) if result.stdout.strip() else {}
            pets = data.get("pets", data.get("results", []))
            return {"success": True, "pets": pets, "file": str(tmp)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def pvp_float_toggle(self) -> dict:
        if not getattr(self, "_pvp_float_window", None):
            return {"success": False, "message": "PVP悬浮窗未创建"}
        try:
            if self._pvp_float_visible:
                self._pvp_float_window.hide()
                self._pvp_float_visible = False
            else:
                self._pvp_float_window.show()
                self._pvp_float_visible = True
                # 等待窗口加载完成再接受 JS 调用
                import time
                time.sleep(0.3)
            return {"success": True, "visible": self._pvp_float_visible}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def pvp_float_update(self, data: dict) -> dict:
        if not getattr(self, "_pvp_float_window", None):
            return {"success": False, "message": "PVP悬浮窗未创建"}
        if not self._pvp_float_visible:
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

    def _get_fast_capture(self):
        """获取/创建 FastCapture 单例"""
        if self._fast_cap is None:
            from src.capture.fast_capture import FastCapture
            self._fast_cap = FastCapture()
        return self._fast_cap

    def _live_capture_frame(self):
        """通过 FastCapture 单例截屏（mss, ~15ms）"""
        import cv2, numpy as np
        info = self._find_game_window()
        if not info:
            raise RuntimeError("未找到「洛克王国」窗口")
        left, top, right, bottom = info.rect
        if right - left < 50 or bottom - top < 50:
            raise RuntimeError("游戏窗口过小或最小化")
        fc = self._get_fast_capture()
        frame = fc.capture(rect=(left, top, right - left, bottom - top))
        if frame is None or frame.size == 0:
            raise RuntimeError("截图失败")
        if float(frame.std()) < 3.0:
            raise RuntimeError("画面全黑: 游戏未在前台渲染,请点一下游戏窗口")
        return info, frame

    def _live_loop(self):
        import json as _json
        import numpy as np
        from src.perception.vision_pipeline import VisionPipeline, DEFAULT_ROI_CONFIG

        try:
            roi = _json.loads(DEFAULT_ROI_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            roi = {}

        # 启动后台抓图线程
        info = self._find_game_window()
        if info:
            left, top, right, bottom = info.rect
            fc = self._get_fast_capture()
            fc.start_worker((left, top, right - left, bottom - top), fps=30)
            self._enqueue_log("后台抓图线程已启动 (30 FPS)", "info")

        while self._live_running and not self._stop_event.is_set():
            try:
                # 从后台线程取最新帧（丢帧机制，无堆积）
                fc = self._get_fast_capture()
                frame = fc.get_latest_frame()
                if frame is None:
                    # 后台线程未就绪，同步截一次
                    info, frame = self._live_capture_frame()
                else:
                    info = self._find_game_window()
                    if not info:
                        raise RuntimeError("未找到「洛克王国」窗口")
                if frame is None:
                    self._stop_event.wait(self._live_interval)
                    continue
                self._live_black_warned = False

                # 帧差检测：像素均值差 < 5 则跳过识别
                try:
                    if self._live_last_frame is not None and frame is not None:
                        diff = float(np.abs(
                            frame.astype(np.int16)[::4, ::4] -
                            self._live_last_frame.astype(np.int16)[::4, ::4]
                        ).mean())
                        if diff < 5.0:
                            self._stop_event.wait(self._live_interval)
                            continue
                except Exception:
                    pass  # 帧差失败不阻塞，继续识别
                if frame is not None:
                    self._live_last_frame = frame.copy()

                if frame is None:
                    self._stop_event.wait(self._live_interval)
                    continue
                if self._live_pipeline is None:
                    self._live_pipeline = VisionPipeline()
                try:
                    result = self._live_pipeline.analyze(frame).to_dict()
                except Exception as e:
                    self._enqueue_log(f"识别异常: {e}", "warning")
                    self._stop_event.wait(self._live_interval)
                    continue
                payload = {
                    "image": self._frame_to_jpeg_dataurl(frame, max_width=960),  # 实时预览压缩
                    "width": info.width, "height": info.height,
                    "result": result, "roi": roi,
                }
                if self._window:
                    self._window.evaluate_js(
                        f"updateLiveResult({_json.dumps(payload, ensure_ascii=False)})")
            except RuntimeError as e:
                msg = str(e)
                if "全黑" in msg and not self._live_black_warned:
                    self._live_black_warned = True
                    self._enqueue_log(f"实时识别: {msg}(保持游戏前台即可恢复)", "warning")
                elif "未找到" in msg and not self._live_black_warned:
                    self._live_black_warned = True
                    self._enqueue_log(f"实时识别: {msg}", "warning")
            except Exception as e:
                self._enqueue_log(f"实时识别异常: {e}", "error")
            self._stop_event.wait(self._live_interval)

    def vision_save_shot(self) -> dict:
        """截图保存到 data/screenshots（供裁剪工具/演示脚本使用）"""
        try:
            info, frame = self._capture_frame()
        except Exception as e:
            return {"success": False, "message": str(e)}
        try:
            from src.utils.image_io import imwrite_unicode
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = SCREENSHOT_DIR / time.strftime("shot_%Y%m%d_%H%M%S.png")
            # 必须用 imwrite_unicode:项目路径含中文,cv2.imwrite 在部分进程下会静默失败
            if not imwrite_unicode(path, frame):
                raise RuntimeError(f"图像编码或写入失败: {path}")
            self._last_shot_path = path
            self._enqueue_log(f"截图已保存: {path.name}", "success")
            return {"success": True, "path": path.name, "full_path": str(path)}
        except Exception as e:
            self._enqueue_log(f"保存截图失败: {e}", "error")
            return {"success": False, "message": str(e)}

    # ========================================
    # 3. 工具箱 API
    # ========================================

    def tools_list(self) -> dict:
        items = []
        for t in TOOLS:
            proc = self._tool_procs.get(t["id"])
            running = bool(proc and proc["proc"].poll() is None)
            if not running and proc:
                self._tool_procs.pop(t["id"], None)
            items.append({"id": t["id"], "name": t["name"], "desc": t["desc"],
                          "gui": t["gui"], "running": running})
        return {"success": True, "tools": items}

    def tool_start(self, tool_id: str) -> dict:
        tool = next((t for t in TOOLS if t["id"] == tool_id), None)
        if not tool:
            return {"success": False, "message": f"未知工具: {tool_id}"}
        proc_info = self._tool_procs.get(tool_id)
        if proc_info and proc_info["proc"].poll() is None:
            return {"success": False, "message": f"{tool['name']} 已在运行"}

        # 按策略准备参数
        args: list[str] = []
        if tool["arg"] == "shot":
            shot = self.vision_save_shot()
            if not shot.get("success"):
                return {"success": False,
                        "message": f"自动截图失败,无法启动: {shot.get('message')}"}
            args.append(str(self._last_shot_path))
        elif tool["arg"] == "last":
            path = self._resolve_last_screenshot()
            if not path:
                return {"success": False,
                        "message": "没有可用截图,请先在视觉调试台保存一张"}
            args.append(str(path))
            self._enqueue_log(f"{tool['name']} 使用截图: {path.name}", "info")

        script = PROJECT_ROOT / tool["script"]
        if not script.exists():
            return {"success": False, "message": f"脚本不存在: {script}"}

        cmd = [sys.executable, str(script)] + args
        try:
            if tool["gui"]:
                proc = subprocess.Popen(
                    cmd, cwd=str(PROJECT_ROOT),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                proc = subprocess.Popen(
                    cmd, cwd=str(PROJECT_ROOT),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                threading.Thread(target=self._pump_tool_output,
                                 args=(proc, tool["name"]), daemon=True).start()
        except Exception as e:
            self._enqueue_log(f"启动 {tool['name']} 失败: {e}", "error")
            return {"success": False, "message": str(e)}

        self._tool_procs[tool_id] = {"proc": proc, "name": tool["name"]}
        self._enqueue_log(f"已启动 {tool['name']} (PID {proc.pid})", "success")
        return {"success": True, "pid": proc.pid}

    def tool_stop(self, tool_id: str) -> dict:
        tool = next((t for t in TOOLS if t["id"] == tool_id), None)
        name = tool["name"] if tool else tool_id
        if tool_id not in self._tool_procs:
            return {"success": False, "message": f"{name} 未在运行"}
        self._kill_tool(tool_id)
        self._enqueue_log(f"已停止 {name}", "warning")
        return {"success": True}

    def _kill_tool(self, tool_id: str):
        info = self._tool_procs.pop(tool_id, None)
        if not info:
            return
        proc = info["proc"]
        if proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                proc.terminate()

    def _pump_tool_output(self, proc: subprocess.Popen, name: str):
        """把 CLI 工具的 stdout 回流到日志"""
        try:
            for raw in iter(proc.stdout.readline, b""):
                if not raw:
                    break
                text = raw.decode("utf-8", "ignore") or raw.decode("gbk", "ignore")
                self._enqueue_log(f"[{name}] {text.rstrip()}", "info")
        except Exception:
            pass
        finally:
            code = proc.poll()
            self._enqueue_log(f"[{name}] 进程结束 (code {code})", "info")

    def _resolve_last_screenshot(self) -> Path | None:
        if self._last_shot_path and self._last_shot_path.exists():
            return self._last_shot_path
        if SCREENSHOT_DIR.exists():
            pngs = sorted(SCREENSHOT_DIR.glob("*.png"))
            if pngs:
                return pngs[-1]
        return None

    # ========================================
    # 4. 配置中心 API
    # ========================================

    def config_list(self) -> dict:
        items = []
        for name, meta in CONFIG_FILES.items():
            path = CONFIG_DIR / name
            items.append({"name": name, "type": meta["type"],
                          "desc": meta["desc"], "exists": path.exists(),
                          "size": path.stat().st_size if path.exists() else 0})
        return {"success": True, "files": items}

    def config_read(self, name: str) -> dict:
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
        if name not in CONFIG_FILES:
            return {"success": False, "message": f"未知配置: {name}"}
        meta = CONFIG_FILES[name]
        try:
            if meta["type"] == "json":
                json.loads(content)
            else:
                import yaml
                yaml.safe_load(content)
        except Exception as e:
            return {"success": False, "message": f"格式错误,未保存: {e}"}

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
                for key, value in self._validate_throw_params(data).items():
                    setattr(self.tool, key, value)
                self._enqueue_log("丢球延迟已热应用到当前工具实例", "info")
            except Exception as e:
                self._enqueue_log(f"热应用丢球配置失败: {e}", "error")
        return {"success": True}

    # ========================================
    # ROI 模板管理 (Step 1: 多ROI + 归一化坐标)
    # ========================================
    def roi_template_list(self) -> dict:
        from src.pvp.roi_template import list_templates
        return {"success": True, "templates": list_templates()}

    def roi_template_save(self, name: str, base_resolution: list, rois: list) -> dict:
        from src.pvp.roi_template import save_template
        return save_template(name, base_resolution, rois)

    def roi_template_load(self, name: str) -> dict:
        from src.pvp.roi_template import load_template
        data = load_template(name)
        if data is None:
            return {"success": False, "message": f"模板 '{name}' 不存在"}
        return {"success": True, "template": data}

    def roi_template_export(self, name: str) -> dict:
        from src.pvp.roi_template import export_template
        data = export_template(name)
        if data is None:
            return {"success": False, "message": f"模板 '{name}' 不存在"}
        return {"success": True, "json": data}

    def roi_template_import(self, json_str: str) -> dict:
        from src.pvp.roi_template import import_template
        return import_template(json_str)

    def roi_template_delete(self, name: str) -> dict:
        from src.pvp.roi_template import delete_template
        return delete_template(name)

    def roi_template_set_active(self, name: str, mode: str = "pvp") -> dict:
        from src.pvp.roi_template import set_active_template
        return set_active_template(name, mode)

    def roi_export_crop(self, rect: list, save_name: str = None) -> dict:
        """根据像素区域 [x,y,w,h] 裁剪当前帧保存为 PNG"""
        from pathlib import Path
        import cv2
        if self._last_frame is None:
            return {"success": False, "message": "请先截图或启动实时识别"}
        x, y, w, h = map(int, rect)
        hh, ww = self._last_frame.shape[:2]
        x = max(0, min(x, ww - 1)); y = max(0, min(y, hh - 1))
        w = min(w, ww - x); h = min(h, hh - y)
        if w <= 0 or h <= 0:
            return {"success": False, "message": "裁剪区域无效"}
        crop = self._last_frame[y:y + h, x:x + w]
        save_name = save_name or f"roi_crop_{x}_{y}_{w}x{h}.png"
        out_dir = Path(__file__).resolve().parents[2] / "data" / "vision" / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / save_name
        cv2.imwrite(str(out_path), crop)
        return {"success": True, "path": str(out_path), "size": [w, h]}

    def mode_get(self) -> dict:
        return {"success": True, "mode": self.mode_ctrl.current_mode,
                "label": self.mode_ctrl.mode_label}

    def mode_switch(self, mode: str) -> dict:
        return self.mode_ctrl.switch_to(mode)

    # ========================================
    # 5. 状态轮询 + 任务栏数据
    # ========================================

    def get_state(self) -> dict:
        try:
            game_active = self.tool.is_game_window_active()
        except Exception:
            game_active = False

        tasks = []
        if self.tool.running:
            tasks.append({"id": "normal", "name": "普通丢球",
                          "detail": f"已丢 {self.tool.normal_count} 球"})
        if self.tool.bomber_running:
            tasks.append({"id": "bomber", "name": "轰炸机",
                          "detail": f"已丢 {self.tool.bomber_count} 球"})
        if self.tool.skill_running:
            tasks.append({"id": "skill", "name": "自动技能",
                          "detail": f"已按 {self.tool.skill_count} 次"})
        if self._live_running:
            tasks.append({"id": "live", "name": "实时识别",
                          "detail": f"每 {self._live_interval}s"})
        if self.engine.running:
            state_names = {"waiting": "等战斗", "fighting": "战斗中",
                           "throwing": "丢球", "paused": "暂停"}
            tasks.append({"id": "engine", "name": "战斗引擎" + ("(模拟)" if self.engine.dry_run else ""),
                          "detail": f"{state_names.get(self.engine.state, self.engine.state)} {self.engine.state_detail}"})
        for tool_id, info in list(self._tool_procs.items()):
            if info["proc"].poll() is None:
                tasks.append({"id": f"tool:{tool_id}", "name": info["name"],
                              "detail": f"PID {info['proc'].pid}"})
            else:
                self._tool_procs.pop(tool_id, None)

        return {
            "game_active": game_active,
            "normal_running": self.tool.running,
            "bomber_running": self.tool.bomber_running,
            "skill_running": self.tool.skill_running,
            "normal_count": self.tool.normal_count,
            "bomber_count": self.tool.bomber_count,
            "skill_count": self.tool.skill_count,
            "config": self._get_throw_config(),
            "tasks": tasks,
        }


class Api:
    """pywebview 自动把此类方法暴露给前端 JavaScript"""

    def __init__(self, bridge: AppBridge):
        self._bridge = bridge

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

    def vision_capture(self):
        return self._bridge.vision_capture()

    def vision_analyze(self):
        return self._bridge.vision_analyze()

    def vision_ocr_preview(self, rois=None):
        return self._bridge.vision_ocr_preview(rois)

    def vision_save_shot(self):
        return self._bridge.vision_save_shot()

    def vision_live_start(self):
        return self._bridge.vision_live_start()

    def vision_live_stop(self):
        return self._bridge.vision_live_stop()

    # 战斗引擎
    def engine_start(self, dry_run=False, params=None):
        return self._bridge.engine_start(dry_run, params)

    def engine_stop(self):
        return self._bridge.engine_stop()

    def engine_status(self):
        return self._bridge.engine_status()

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

    def widget_resize(self, height):
        return self._bridge.widget_resize(height)

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


__all__ = ['AppBridge', 'Api']
