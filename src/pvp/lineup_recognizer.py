# -*- coding: utf-8 -*-
"""lineup_recognizer — 战前阵容识别 (PVP 对战模板)

在战前陈列阶段(双方 6v6 阵容展示屏)识别我方和敌方的完整精灵阵容。
双通道: 头像模板匹配(ORB) → OCR 名字兜底。

用法:
    recognizer = LineupRecognizer()
    result = recognizer.recognize(frame)
    # result = {"player_lineup": [...], "enemy_lineup": [...], "conf": 0.xx}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from src.pvp.pvp_pipeline import _fuzzy_match as _fuzzy_match_impl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PROJECT_ROOT / "data" / "config" / "roi_templates"
LINEUP_TEMPLATE = TEMPLATE_DIR / "PVP对战模板.json"

# 槽位命名(左列玩家, 右列敌方)
SLOT_IDS = [f"我方阵容{i}" for i in range(1, 7)] + [f"敌方阵容{i}" for i in range(1, 7)]


class LineupRecognizer:
    """战前阵容识别器 — 只对新帧调用, 不含帧缓存(由 pipeline 管理)"""

    def __init__(self):
        self._rois: dict[str, dict] = {}
        self._avatar_lib: object | None = None
        self._avatar_tried = False
        self._load_template()

    def _load_template(self):
        if not LINEUP_TEMPLATE.exists():
            return
        data = json.loads(LINEUP_TEMPLATE.read_text(encoding="utf-8"))
        for roi in data.get("rois", []):
            rid = str(roi.get("id", ""))
            if rid in SLOT_IDS:
                self._rois[rid] = {
                    "rx": roi["rx"], "ry": roi["ry"],
                    "rw": roi["rw"], "rh": roi["rh"],
                }

    def _get_avatar_lib(self):
        if self._avatar_lib is None and not self._avatar_tried:
            self._avatar_tried = True
            try:
                import sys as _sys
                lib_dir = PROJECT_ROOT / "src" / "pvp" / "lib"
                for pth in (str(lib_dir), str(PROJECT_ROOT)):
                    if pth not in _sys.path:
                        _sys.path.insert(0, pth)
                from pvp_lib import PvpTemplateLibrary  # noqa
                lib = PvpTemplateLibrary()
                lib.load()
                if lib.status().get("n_templates", 0) > 0:
                    self._avatar_lib = lib
            except Exception:
                pass

    def _crop(self, frame: np.ndarray, roi_id: str) -> np.ndarray | None:
        box = self._rois.get(roi_id)
        if not box:
            return None
        fh, fw = frame.shape[:2]
        x = int(box["rx"] * fw)
        y = int(box["ry"] * fh)
        w = max(1, int(box["rw"] * fw))
        h = max(1, int(box["rh"] * fh))
        if x + w > fw or y + h > fh or x < 0 or y < 0:
            return None
        return frame[y:y + h, x:x + w]

    def is_lineup_screen(self, frame: np.ndarray) -> bool:
        """粗略判定是否在战前阵容/选首发界面: 检查左侧阵容大区有内容"""
        fh, fw = frame.shape[:2]
        # 左侧我方阵容大区: 有内容即可(选首发屏右侧可能没有完整敌方列表)
        rx, ry, rw, rh = 0.0549, 0.1931, 0.1741, 0.5034
        x, y = int(rx * fw), int(ry * fh)
        w, h = int(rw * fw), int(rh * fh)
        crop = frame[y:y + h, x:x + w]
        if crop.size == 0:
            return False
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mean_brightness = float(gray.mean())
        # 阵容区应该有内容(不是纯黑/纯白), 亮度在 30~220 之间
        if mean_brightness < 30 or mean_brightness > 220:
            return False
        # 必须有足够的边缘密度(有多个精灵行)
        edges = cv2.Canny(gray, 50, 150)
        edge_ratio = float(np.sum(edges > 0)) / edges.size * 100
        if edge_ratio < 3.0:
            return False
        return True

    def recognize(self, frame: np.ndarray) -> dict:
        """识别阵容 — 遍历 12 个槽位, 头像匹配 → OCR 兜底
        
        返回:
            {"player_lineup": ["名1",...,"名6"],      # 未知为 None
             "enemy_lineup":  ["名1",...,"名6"],
             "confidence": 0.0~1.0,                    # 平均识别置信度
             "done": True}
        """
        from src.utils.ocr_engine import read_combined, read_best
        from src.pvp.pvp_pipeline import preprocess_text_roi

        self._get_avatar_lib()
        result = {"player_lineup": [], "enemy_lineup": [],
                  "confidence": 0.0, "done": False}

        all_confs = []
        for rid in SLOT_IDS:
            crop = self._crop(frame, rid)
            if crop is None or crop.size == 0:
                result["player_lineup" if "我方" in rid else "enemy_lineup"].append(None)
                continue

            name = None
            conf = 0.0

            # 1. 头像 ORB 匹配(左半作为头像区域)
            if self._avatar_lib is not None:
                g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                if float(g.std()) >= 35 and (int(g.max()) - int(g.min())) >= 120:
                    acw = max(40, int(crop.shape[1] * 0.35))
                    avatar_crop = crop[:, :acw]
                    if avatar_crop.size > 0:
                        try:
                            hits = self._avatar_lib.match(avatar_crop, n_top=1)
                            if hits and hits[0].get("confidence") in ("high", "medium") \
                               and float(hits[0].get("margin", 0)) >= 0.25:
                                name = hits[0]["name"]
                                conf = 0.85 if hits[0]["confidence"] == "high" else 0.65
                        except Exception:
                            pass

            # 2. OCR 兜底 — 全文本提取精灵名字
            if not name:
                try:
                    # 名字区域: 从槽位 15% 到右端(头像约15%, 名字紧随其后)
                    name_start = int(crop.shape[1] * 0.15)
                    name_crop = crop[:, name_start:]
                    if name_crop.size == 0:
                        name_crop = crop

                    # 放大+增强预处理(小尺寸ROI必须)
                    if name_crop.shape[0] < 60 or name_crop.shape[1] < 120:
                        name_crop = preprocess_text_roi(name_crop, scale=3)

                    # 读全文本 — read_combined + read_best 双通道互补
                    full_text, _ = read_combined(name_crop)
                    best_text, best_score = read_best(name_crop)

                    # 策略: 从中文字符序列中找匹配
                    import re as _re
                    ocr_names = []
                    seen = set()
                    for txt in [full_text or "", best_text or ""]:
                        for chunk in _re.findall(r"[\u4e00-\u9fff]{2,}", txt):
                            if chunk not in seen:
                                ocr_names.append(chunk)
                                seen.add(chunk)

                    pet_list = self._get_pet_list()
                    for candidate in ocr_names:
                        matched = _smart_name_match(candidate, pet_list)
                        if matched:
                            name = matched
                            conf = 0.75 if matched == candidate else 0.5
                            break
                    if not name and ocr_names:
                        name = ocr_names[0]
                        conf = 0.2
                except Exception:
                    pass

            key = "player_lineup" if "我方" in rid else "enemy_lineup"
            result[key].append(name)
            all_confs.append(conf)

        result["confidence"] = round(float(np.mean(all_confs)) if all_confs else 0.0, 2)
        result["done"] = True
        return result

    @staticmethod
    def _get_pet_list() -> list[str]:
        pet_names_path = PROJECT_ROOT / "data" / "config" / "pet_names.txt"
        if pet_names_path.exists():
            return [line.strip() for line in
                    pet_names_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
        return []


def _smart_name_match(raw: str, pet_list: list[str]) -> str | None:
    """智能名字匹配：精确 > 前缀 > 包含 > 编辑距离"""
    if not raw or not pet_list:
        return None
    
    # 1. 精确匹配
    if raw in pet_list:
        return raw
    
    # 2. 前缀匹配(OCR 短名是某精灵名的前缀)
    prefixes = [p for p in pet_list if p.startswith(raw)]
    if prefixes:
        return sorted(prefixes, key=len)[0]  # 最短的
    
    # 3. 包含匹配(OCR 短名包含在某精灵名中)
    contains = [p for p in pet_list if raw in p]
    if contains:
        return sorted(contains, key=len)[0]
    
    # 4. 编辑距离(从 pvp_pipeline 复用)
    return _fuzzy_match_impl(raw, pet_list)