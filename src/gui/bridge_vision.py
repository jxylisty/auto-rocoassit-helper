"""AppBridge Mix-in —— 视觉调试 / ROI 工坊 / ROI 模板库 / 实时识别"""

import base64
import json
import threading
import time
from pathlib import Path
from src.gui.bridge_common import SCREENSHOT_DIR, STUDIO_DIR


class VisionMixin:

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
        """截图一帧游戏画面(FastCapture 单例持久化, ~3-5ms)"""
        info = self._find_game_window()
        if not info:
            raise RuntimeError("未找到「洛克王国」窗口,请确认游戏已启动")
        left, top, right, bottom = info.rect
        w, h = right - left, bottom - top
        if w < 50 or h < 50:
            raise RuntimeError("游戏窗口过小或最小化")
        fc = self._get_fast_capture()
        frame = fc.capture(rect=(left, top, w, h))
        if frame is None or frame.size == 0:
            raise RuntimeError("截图失败")
        return info, frame

    @staticmethod
    def _frame_to_jpeg_dataurl(frame, max_width: int = None) -> str:
        """编码 JPEG 为 base64 dataurl; 实时识别用 max_width=960 压缩,单次截图用原尺寸"""
        from src.capture.fast_capture import FastCapture
        return FastCapture.encode_jpeg(frame, max_width=max_width, quality=75)

    def vision_capture(self, front: bool = True, source: str = "main") -> dict:
        """截取游戏画面预览。
        front=True: 先把游戏窗口置前并等 1 秒再截(避免截到遮挡/失焦画面);
        source: 调用来源('main' 主控台视觉调试 / 'studio' ROI 工坊), 仅用于日志定位"""
        try:
            if front:
                try:
                    self._focus_game_window()
                except Exception:
                    pass
                import time as _t
                _t.sleep(1.0)   # 等窗口切换与渲染稳定
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

    def vision_analyze(self, front: bool = True, source: str = "main") -> dict:
        """截图 + 跑完整识别管线 (front/source 含义同 vision_capture)"""
        try:
            if front:
                try:
                    self._focus_game_window()
                except Exception:
                    pass
                import time as _t
                _t.sleep(1.0)
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

    def vision_ocr_preview(self, rois: dict = None) -> dict:
        """RapidOCR 批量识别: 逐个 ROI 裁切后独立识别(替代重载慢的 PaddleOCR)。
        首调用时 RapidOCR 懒加载(~1s)，之后复用无额外内存消耗。"""
        import cv2, numpy as np
        from src.perception.ocr_reader import OcrNameReader
        from src.utils.ocr_engine import read_combined as _ocr_read

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

        pet_list = OcrNameReader._load_pets() if hasattr(OcrNameReader, '_load_pets') else []

        results = {}
        for roi_id, box in roi_data.items():
            if not box or not box.get("width"):
                continue
            x = int(box["left"] * fw) if "left" in box else int(float(box.get("rx", 0)) * fw)
            y = int(box["top"] * fh) if "top" in box else int(float(box.get("ry", 0)) * fh)
            w = int(box["width"] * fw)
            h = int(box["height"] * fh)
            if w <= 0 or h <= 0:
                continue
            crop = frame[y:y+h, x:x+w]
            is_number = any(kw in roi_id.lower() for kw in ("hp", "血", "energy", "能量", "power"))
            label = box.get("label", roi_id)

            joined, conf = "", 0.0
            if crop.size > 0:
                text, score = _ocr_read(crop)
                if text:
                    joined, conf = text, round(score, 2)

            if is_number:
                joined = ''.join(ch for ch in joined if ch.isdigit() or ch in '%/')
            elif joined and pet_list:
                cleaned = OcrNameReader._clean(joined) if hasattr(OcrNameReader, '_clean') else joined
                matched = OcrNameReader._correct_with_pet_list(cleaned) if cleaned and hasattr(OcrNameReader, '_correct_with_pet_list') else None
                if matched:
                    joined = matched[0]

            results[roi_id] = {
                "text": joined or "?", "conf": conf,
                "raw": joined, "corrected": bool(matched and matched[0]),
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

    def vision_live_quality(self, quality: str = "fast") -> dict:
        """实时预览画质切换: fast=960 / hd=1440 / full=原尺寸 (下一帧生效)"""
        mapping = {"fast": 960, "hd": 1440, "full": 0}
        q = str(quality or "fast").lower()
        if q not in mapping:
            return {"success": False, "message": f"未知画质: {quality} (可选 fast/hd/full)"}
        self._live_max_width = mapping[q]
        self._enqueue_log(f"实时预览画质已切换: {q}", "info")
        return {"success": True, "quality": q, "max_width": self._live_max_width}

    # ========================================
    # ROI 标注工坊 (独立大窗, 与主控台共用同一 Api 单例)
    # ========================================

    def roi_studio_open(self) -> dict:
        """打开 ROI 标注工坊独立窗 (运行时创建, 共用 Api 单例)"""
        import webview
        # 子窗口被用户点 X 关闭后, pywebview 会把 Window 从内部注册表移除,
        # 残留引用调 show() 静默无效 → 用 closed 事件标志判断存活
        if getattr(self, "_studio_window", None):
            if getattr(self._studio_window, "_lkw_closed", False):
                self._studio_window = None
            else:
                try:
                    self._studio_window.show()
                    return {"success": True}
                except Exception:
                    self._studio_window = None
        web_dir = STUDIO_DIR
        url = (web_dir / "roi_studio.html").as_uri()
        try:
            win = webview.create_window(
                title='ROI 标注工坊', url=url, js_api=self._api,
                width=1280, height=820, min_size=(960, 640),
                resizable=True, on_top=False)
            win.events.closed += lambda: setattr(win, "_lkw_closed", True)
            self._studio_window = win
        except Exception as e:
            return {"success": False, "message": f"创建工坊窗口失败: {e}"}
        self._enqueue_log("ROI 标注工坊已打开", "info")
        return {"success": True}

    def roi_studio_state(self) -> dict:
        """工坊窗初始化数据: 最近一帧截图 + 当前 ROI + 模板列表"""
        out = {"success": True, "roi": {}, "templates": [], "image": None}
        try:
            from src.pvp.roi_template import list_templates
            out["templates"] = list_templates()
        except Exception:
            pass
        try:
            cfg = Path(__file__).resolve().parents[2] / "data" / "config" / "roi_config.json"
            if cfg.exists():
                out["roi"] = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            pass
        if self._last_frame is not None:
            try:
                out["image"] = self._frame_to_jpeg_dataurl(self._last_frame)
                hh, ww = self._last_frame.shape[:2]
                out["width"], out["height"] = ww, hh
            except Exception:
                pass
        return out

    def roi_studio_save(self, name: str, base_resolution: list, rois: list) -> dict:
        """工坊原子保存: 模板落盘 + 运行时 roi_config 同步 + 主窗推送"""
        from src.pvp.roi_template import save_template
        res = save_template(name, base_resolution, rois)
        if not res.get("success"):
            return res
        synced = False
        try:
            # 运行时同步: 模板(rx/ry/rw/rh 归一化) → roi_config.json
            # 视觉管线消费格式: {"left","top","width","height"}
            from src.pvp.roi_template import load_template
            data = load_template(name)
            rois_map = {}
            for r in (data or {}).get("rois", []):
                rid = r.get("id", "")
                if not rid:
                    continue
                rois_map[rid] = {"left": float(r.get("rx", 0)), "top": float(r.get("ry", 0)),
                                 "width": float(r.get("rw", 0)), "height": float(r.get("rh", 0))}
            if rois_map:
                cfg_path = Path(__file__).resolve().parents[2] / "data" / "config" / "roi_config.json"
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                old = {}
                if cfg_path.exists():
                    try:
                        old = json.loads(cfg_path.read_text(encoding="utf-8"))
                    except Exception:
                        old = {}
                old.update(rois_map)
                tmp = cfg_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(cfg_path)
                synced = True
        except Exception as e:
            self._enqueue_log(f"roi_config 运行时同步失败: {e}", "warning")
        # 推送主窗更新 currentRoi (前端格式同为 left/top/width/height)
        try:
            if self._window:
                self._window.evaluate_js(
                    "window.onRoiStudioSaved && window.onRoiStudioSaved("
                    + json.dumps({"name": name, "roi": rois_map}, ensure_ascii=False) + ")")
        except Exception:
            pass
        self._enqueue_log(f"ROI 模板已保存: {name} (同步={synced})", "success")
        res["synced"] = synced
        return res


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

                # 遮挡防护: 控制台叠在游戏上方时截到的是控制台画面 → 自动最小化
                try:
                    self._guard_console_occlusion(info.rect, info.hwnd)
                except Exception:
                    pass

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
                    "image": self._frame_to_jpeg_dataurl(
                        frame, max_width=self._live_max_width or None),  # 画质可调
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
