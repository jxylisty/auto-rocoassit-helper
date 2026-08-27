# -*- coding: utf-8 -*-
"""
PVP 实时识别管线 — 双引擎 OCR + 快速截图

架构:
  1. FastCapture 后台线程持续抓取最新帧
  2. 中文区域 (精灵名/技能名) → PaddleOCR PP-OCRv4 批量合成图识别
  3. 数字区域 (血量/能量/PP) → Tesseract OcrNumberReader (照抄挂机引擎)
  4. 敌方血条 → 色彩积分 (0ms，无需 OCR)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PROJECT_ROOT / "data" / "config" / "roi_templates"
DEFAULT_TEMPLATE = TEMPLATE_DIR / "PVP标准模板.json"

# ---- 数字 OCR (照抄挂机引擎 OcrNumberReader) ----
_TESSERACT_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
TESSDATA_DIR = PROJECT_ROOT / "data" / "models" / "tessdata"


def _ensure_tesseract() -> bool:
    import shutil
    import pytesseract
    if getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract") != "tesseract":
        return True
    if shutil.which("tesseract"):
        return True
    if _TESSERACT_PATH.exists():
        pytesseract.pytesseract.tesseract_cmd = str(_TESSERACT_PATH)
        return True
    return False


def ocr_number(crop: np.ndarray, percent: bool = False) -> Optional[str]:
    """Tesseract 数字识别 (照抄挂机引擎 OcrNumberReader.read())"""
    import pytesseract
    if not _ensure_tesseract():
        return None
    if crop.size == 0:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    _, bright = cv2.threshold(big, 180, 255, cv2.THRESH_BINARY)
    _, otsu = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    whitelist = "0123456789%/" if percent else "0123456789/"
    config = f'--psm 7 --tessdata-dir "{TESSDATA_DIR}" -c tessedit_char_whitelist={whitelist}'
    text = ""
    for candidate in (bright, cv2.bitwise_not(bright), otsu, cv2.bitwise_not(otsu)):
        try:
            result = pytesseract.image_to_string(candidate, config=config).strip()
        except Exception:
            continue
        if sum(ch.isdigit() for ch in result) > sum(ch.isdigit() for ch in text):
            text = result
        if percent and re.search(r"\d{1,3}\s*%", text):
            break
    return text.replace(" ", "") or None


def ocr_name(crop: np.ndarray, pet_list: list[str]) -> tuple[Optional[str], float, str]:
    """Tesseract 中文精灵名识别 (照抄挂机引擎 OcrNameReader.read())"""
    import pytesseract
    if not _ensure_tesseract() or not TESSDATA_DIR.exists():
        return None, 0.0, ""

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, None, fx=3.5, fy=3.5, interpolation=cv2.INTER_CUBIC)
    _, bright = cv2.threshold(big, 180, 255, cv2.THRESH_BINARY)
    _, bright2 = cv2.threshold(big, 150, 255, cv2.THRESH_BINARY)
    _, otsu = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    config = f'--psm 7 --tessdata-dir "{TESSDATA_DIR}"'
    best_text, best_conf = "", -1.0
    for candidate in (bright, bright2, otsu, cv2.bitwise_not(bright), cv2.bitwise_not(otsu)):
        try:
            data = pytesseract.image_to_data(
                candidate, lang="chi_sim", config=config, output_type=pytesseract.Output.DICT)
        except Exception:
            continue
        words = [(t.strip(), float(c)) for t, c in zip(data["text"], data["conf"]) if t.strip()]
        if not words:
            continue
        text = "".join(w for w, _ in words)
        conf = sum(wc * len(w) for w, wc in words) / max(1, len(text))
        if conf > best_conf:
            best_text, best_conf = text, conf
        # 早退: 已命中精灵名单
        cleaned = "".join(ch for ch in text if ("\u4e00" <= ch <= "\u9fff") or ch.isalnum())
        if _fuzzy_match(cleaned, pet_list):
            best_text = text
            break

    cleaned = "".join(ch for ch in best_text if ("\u4e00" <= ch <= "\u9fff") or ch.isalnum())
    matched = _fuzzy_match(cleaned, pet_list)
    value = matched or cleaned or None
    conf = min(1.0, max(0.0, best_conf / 100.0))
    return value, conf, best_text


def _fuzzy_match(name: str, pet_list: list[str]) -> Optional[str]:
    """编辑距离模糊匹配精灵名"""
    if not name or not pet_list:
        return None
    if name in pet_list:
        return name

    def levenshtein(a: str, b: str) -> int:
        if len(a) < len(b):
            a, b = b, a
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]

    best, best_dist = None, 10 ** 9
    for pet in pet_list:
        if abs(len(pet) - len(name)) > 2:
            continue
        dist = levenshtein(name, pet)
        if dist < best_dist:
            best, best_dist = pet, dist
    if best is not None and best_dist <= max(1, len(name) // 3 + (1 if len(name) >= 4 else 0)):
        return best
    return None


# ---- 敌方血条色彩积分 (0ms, 无需 OCR) ----
def enemy_hp_color_ratio(crop: np.ndarray) -> float:
    """计算敌方血条绿色/黄色像素的水平占比 → 血量百分比"""
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # 绿色 + 黄色掩膜 (H: 30-90)
    mask_green = cv2.inRange(hsv, (30, 40, 40), (90, 255, 255))
    total = crop.shape[1]
    if total == 0:
        return 0.0
    # 按列统计：每列是否有绿色像素
    col_has_color = np.any(mask_green > 0, axis=0)
    ratio = float(np.sum(col_has_color)) / total
    return round(min(1.0, max(0.0, ratio)), 2)


# ---- PaddleOCR 批量识别 ----
_paddleocr_instance = None


def _get_paddleocr():
    global _paddleocr_instance
    if _paddleocr_instance is not None:
        return _paddleocr_instance
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('MKL_NUM_THREADS', '1')
    os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
    from paddleocr import PaddleOCR
    _paddleocr_instance = PaddleOCR(
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
    return _paddleocr_instance


def ocr_batch_chinese(crops: list[tuple[str, np.ndarray]]) -> dict[str, str]:
    """PaddleOCR 批量识别中文（合成一张图，一次 predict）"""
    if not crops:
        return {}
    ocr = _get_paddleocr()

    # 合成图：竖排拼接所有 ROI，中间加分隔线
    pad = 10
    total_h = sum(c.shape[0] + pad for _, c in crops) + pad
    max_w = max(c.shape[1] for _, c in crops) + pad * 2
    composite = np.zeros((total_h, max_w, 3), dtype=np.uint8)

    y_offsets = []
    y = pad
    for _, c in crops:
        h, w = c.shape[:2]
        composite[y:y + h, pad:pad + w] = c
        y_offsets.append((y, y + h))
        y += h + pad

    # 一次 OCR
    res = ocr.predict(composite)
    if not res or not res[0]:
        return {rid: "" for rid, _ in crops}

    rec_texts = res[0].get('rec_texts', [])
    rec_polys = res[0].get('rec_polys', [])

    # 按 y 位置分配回各个 ROI
    results = {rid: "" for rid, _ in crops}
    for text, poly in zip(rec_texts, rec_polys):
        if poly is None or len(poly) == 0:
            continue
        cy = float(np.mean([p[1] for p in poly]))
        for i, (rid, _) in enumerate(crops):
            if y_offsets[i][0] <= cy <= y_offsets[i][1]:
                results[rid] = results[rid] + text
                break

    return results


# ---- 主管线 ----
@dataclass
class PvpResult:
    """PVP 识别结果"""
    player_name: str = ""
    player_name_conf: float = 0.0
    player_hp: str = ""  # 如 "326/326"
    player_hp_val: int = 0
    player_hp_max: int = 0
    enemy_name: str = ""
    enemy_name_conf: float = 0.0
    enemy_hp_pct: float = 0.0  # 0.0-1.0
    enemy_hp_color: float = 0.0  # 色彩积分值
    skills: list[str] = field(default_factory=lambda: ["", "", "", ""])
    energy: str = ""
    energy_val: int = 0
    in_battle: bool = False
    errors: list[str] = field(default_factory=list)


class PvpPipeline:
    """PVP 实时识别管线"""

    def __init__(self, template_path: Path = DEFAULT_TEMPLATE):
        self.template_path = template_path
        self._rois: dict = {}
        self._pet_list: list[str] = []
        self._load_template()
        self._load_pet_list()

    def _load_template(self):
        if not self.template_path.exists():
            return
        data = json.loads(self.template_path.read_text(encoding="utf-8"))
        for roi in data.get("rois", []):
            self._rois[roi["id"]] = {
                "rx": roi["rx"], "ry": roi["ry"],
                "rw": roi["rw"], "rh": roi["rh"],
                "label": roi.get("label", roi["id"]),
            }

    def _load_pet_list(self):
        pet_names_path = PROJECT_ROOT / "data" / "config" / "pet_names.txt"
        if pet_names_path.exists():
            self._pet_list = [line.strip() for line in
                            pet_names_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _crop(self, frame: np.ndarray, roi_id: str) -> Optional[np.ndarray]:
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

    def analyze(self, frame: np.ndarray) -> PvpResult:
        """分析一帧，返回 PvpResult"""
        result = PvpResult()

        # ---- 1. 敌方血条: 色彩积分 (0ms, 无需 OCR) ----
        enemy_hp_crop = self._crop(frame, "敌方血条")
        if enemy_hp_crop is not None:
            result.enemy_hp_color = enemy_hp_color_ratio(enemy_hp_crop)

        # ---- 2. 所有区域: PaddleOCR 批量合成一张图识别 ----
        all_crops = []
        for roi_id in ["我方精灵名", "敌方精灵名", "我方血条", "敌方血条",
                       "技能1", "技能2", "技能3", "技能4", "剩余能量"]:
            crop = self._crop(frame, roi_id)
            if crop is not None:
                pad = max(10, min(crop.shape[0], crop.shape[1]) // 2)
                padded = cv2.copyMakeBorder(crop, pad, pad, pad, pad,
                                            cv2.BORDER_CONSTANT, value=(0, 0, 0))
                all_crops.append((roi_id, padded))

        if all_crops:
            try:
                ocr_results = ocr_batch_chinese(all_crops)
            except Exception as e:
                result.errors.append(f"PaddleOCR: {e}")
                ocr_results = {}

            # ---- 精灵名模糊匹配 ----
            for roi_id in ["我方精灵名", "敌方精灵名"]:
                raw = ocr_results.get(roi_id, "")
                if raw:
                    cleaned = "".join(ch for ch in raw
                                     if ("\u4e00" <= ch <= "\u9fff") or ch.isalnum())
                    matched = _fuzzy_match(cleaned, self._pet_list)
                    if roi_id == "我方精灵名":
                        result.player_name = matched or cleaned
                        result.player_name_conf = 0.9 if matched else 0.3
                    else:
                        result.enemy_name = matched or cleaned
                        result.enemy_name_conf = 0.9 if matched else 0.3

            # ---- 技能名 ----
            for i, roi_id in enumerate(["技能1", "技能2", "技能3", "技能4"]):
                result.skills[i] = ocr_results.get(roi_id, "")

            # ---- 数字: 从 PaddleOCR 结果中提取 ----
            hp_raw = ocr_results.get("我方血条", "")
            if hp_raw:
                m = re.search(r"(\d+)\s*/\s*(\d+)", hp_raw)
                if m:
                    result.player_hp = f"{m.group(1)}/{m.group(2)}"
                    result.player_hp_val = int(m.group(1))
                    result.player_hp_max = int(m.group(2))

            energy_raw = ocr_results.get("剩余能量", "")
            if energy_raw:
                result.energy = energy_raw
                m = re.search(r"(\d+)", energy_raw)
                if m:
                    result.energy_val = int(m.group(1))

            enemy_pct_raw = ocr_results.get("敌方血条", "")
            if enemy_pct_raw:
                m = re.search(r"(\d+)\s*%", enemy_pct_raw)
                if m:
                    result.enemy_hp_pct = int(m.group(1)) / 100.0

        # ---- 3. 战斗状态判断 ----
        result.in_battle = (result.player_name != "" or result.enemy_name != "" or
                           result.player_hp != "")

        return result

    def to_dict(self, result: PvpResult) -> dict:
        return {
            "player": {
                "name": result.player_name,
                "name_conf": result.player_name_conf,
                "hp": result.player_hp,
                "hp_val": result.player_hp_val,
                "hp_max": result.player_hp_max,
                "skills": result.skills,
                "energy": result.energy,
                "energy_val": result.energy_val,
            },
            "enemy": {
                "name": result.enemy_name,
                "name_conf": result.enemy_name_conf,
                "hp_pct": result.enemy_hp_pct,
                "hp_color": result.enemy_hp_color,
            },
            "in_battle": result.in_battle,
            "errors": result.errors,
        }


# 全局单例
_pipeline: Optional[PvpPipeline] = None


def get_pipeline() -> PvpPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = PvpPipeline()
    return _pipeline