"""High-level frame analysis pipeline."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import numpy as np

from .battle_detector import BattleDetector
from src.analysis.battle_state import BattleStateSnapshot
from src.ocr.base import ROI, RecognitionResult
from .ocr_reader import ElementMatcher, OcrNameReader, OcrNumberReader


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROI_CONFIG = PROJECT_ROOT / "data" / "config" / "roi_config.json"


def load_roi_config(path: Path = DEFAULT_ROI_CONFIG) -> dict[str, ROI]:
    config = json.loads(path.read_text(encoding="utf-8"))
    return {name: ROI(name=name, **values) for name, values in config.items()}


def locate_hp_anchor(frame: np.ndarray) -> tuple[int, int] | None:
    """在画面右上区域全量搜索 "NN%" 血量文字,返回其中心像素坐标(浮动名牌的锚点)。

    敌方名牌位置随战斗/视角漂移,固定 ROI 追不住;血量百分比是名牌上
    最独特的文字,用它做锚点把整套名牌框平移过去。
    """
    import cv2

    from .ocr_reader import _ensure_tesseract
    if not _ensure_tesseract():
        return None
    import pytesseract

    fh, fw = frame.shape[:2]
    x0, y0 = int(fw * 0.55), 0
    region = frame[y0:int(fh * 0.35), x0:fw]
    if region.size == 0:
        return None
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    _, bright = cv2.threshold(big, 180, 255, cv2.THRESH_BINARY)

    config = "--psm 11 -c tessedit_char_whitelist=0123456789%"
    try:
        data = pytesseract.image_to_data(
            bright, config=config, output_type=pytesseract.Output.DICT)
    except Exception:
        return None

    for text, conf, left, top, width, height in zip(
            data["text"], data["conf"], data["left"], data["top"],
            data["width"], data["height"]):
        t = text.strip()
        if not t or float(conf) < 40:
            continue
        if re.fullmatch(r"\d{1,3}%", t):
            cx = x0 + (left + width / 2) / 2.0
            cy = y0 + (top + height / 2) / 2.0
            return int(cx), int(cy)
    return None


class VisionPipeline:
    """Runs all frame readers and merges their outputs.

    识别范围: 战斗检测 / 敌方精灵名(OCR+名单纠错) / 敌方属性(最多双属性) / 敌方血量百分比(OCR)。
    名牌框支持锚点追踪: 每帧先定位 "NN%",再按校准时的相对布局整体平移。
    """

    def __init__(self, roi_config_path: Path = DEFAULT_ROI_CONFIG):
        rois = load_roi_config(roi_config_path)
        self.rois = rois
        self.name_reader = OcrNameReader(rois["enemy_name"])
        self.element_matcher = ElementMatcher(rois["enemy_elements"])
        self.battle_detector = BattleDetector(
            rois.get("battle_left_indicator"),
            rois.get("battle_right_indicator"),
        )
        self.enemy_hp_reader = OcrNumberReader(rois["enemy_hp"], percent=True)
        # 锚点扫描较贵(全区域OCR),结果缓存、每3帧重算一次
        self._anchor_shift = None
        self._anchor_age = 99

    def _shifted_rois(self, frame: np.ndarray) -> dict[str, ROI]:
        """若锚点与校准时血量框位置不一致,把名牌三框整体平移到锚点处"""
        if self._anchor_age < 2 and self._anchor_shift is not None:
            self._anchor_age += 1
            dx, dy = self._anchor_shift
        else:
            anchor = locate_hp_anchor(frame)
            if anchor is None:
                self._anchor_shift = None
                self._anchor_age = 0
                return self.rois
            fh, fw = frame.shape[:2]
            hp = self.rois["enemy_hp"]
            hx = (hp.left + hp.width / 2) * fw
            hy = (hp.top + hp.height / 2) * fh
            dx = (anchor[0] - hx) / fw
            dy = (anchor[1] - hy) / fh
            self._anchor_shift = (dx, dy)
            self._anchor_age = 0
            if abs(dx) < 0.005 and abs(dy) < 0.005:
                return self.rois

        shifted = dict(self.rois)
        for key in ("enemy_name", "enemy_elements", "enemy_hp"):
            roi = self.rois[key]
            shifted[key] = replace(
                roi,
                left=max(0.0, min(1.0 - roi.width, roi.left + dx)),
                top=max(0.0, min(1.0 - roi.height, roi.top + dy)),
            )
        return shifted

    def analyze(self, frame: np.ndarray, light: bool = False) -> BattleStateSnapshot:
        """识别一帧。

        light=True 为战斗引擎循环用的轻量模式: 跳过精灵名 OCR(中文大模型很慢),
        只读角标+血量; 进战斗瞬间由调用方做一次全量识别拿名字。
        """
        rois = self._shifted_rois(frame)

        hp_reader = (self.enemy_hp_reader if rois is self.rois
                     else OcrNumberReader(rois["enemy_hp"], percent=True))

        if light:
            name = RecognitionResult(
                reader_name="ocr_name", value=None, confidence=0.0,
                roi_name="enemy_name", debug={"skipped": "light"})
        else:
            name_reader = (self.name_reader if rois is self.rois
                           else OcrNameReader(rois["enemy_name"]))
            name = name_reader.read(frame)

        elements = RecognitionResult(
            reader_name="element_matcher", value=None, confidence=0.0,
            roi_name="enemy_elements", debug={"disabled": True})
        enemy_hp = hp_reader.read(frame)

        battle = self.battle_detector.detect(frame)
        if not battle.get("in_battle"):
            # 角标不可见(丢球界面打开时只隐藏左角标,右角标仍在;
            # 极端情况下全隐藏) → 用名牌兜底: 血量%可读 或 名字命中名单
            name_hit = bool(enemy_hp.value is not None or name.debug.get("corrected"))
            if name_hit:
                battle = dict(battle, in_battle=True, via_nameplate=True)

        return BattleStateSnapshot(
            enemy_name=name,
            enemy_elements=elements,
            enemy_hp=enemy_hp,
            raw={
                "battle": battle,
                "name_raw": name.debug.get("raw"),
                "element_candidates": elements.candidates,
                "hp_raw": enemy_hp.debug.get("raw"),
                "plate_shifted": rois is not self.rois,
            },
        )
