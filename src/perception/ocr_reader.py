"""Concrete readers for damage, energy, avatar and element recognition."""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

from src.ocr.base import BaseReader, ROI, RecognitionResult
from .template_matcher import (
    best_template_match,
    load_grayscale_templates,
    preprocess_digit_roi,
    rank_template_matches,
    split_digit_boxes,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = PROJECT_ROOT / "data" / "vision"

_TESSERACT_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
TESSDATA_DIR = PROJECT_ROOT / "data" / "models" / "tessdata"  # chi_sim 中文语言包所在


def _ensure_tesseract() -> bool:
    """确认 tesseract 可用;默认安装路径不在 PATH 时手动指定"""
    import shutil

    import pytesseract
    if getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract") != "tesseract":
        return True  # 已指定过
    if shutil.which("tesseract"):
        return True
    if _TESSERACT_PATH.exists():
        pytesseract.pytesseract.tesseract_cmd = str(_TESSERACT_PATH)
        return True
    return False


class OcrNumberReader(BaseReader[int]):
    """Tesseract OCR 数字识别(血量百分比等 HUD 数字,支持 85%、123/456 格式)"""

    reader_name = "ocr_number"

    def __init__(self, roi: ROI, upscale: float = 3.0, percent: bool = False):
        super().__init__(roi)
        self.upscale = upscale
        self.percent = percent

    def read(self, frame: np.ndarray) -> RecognitionResult[int]:
        if not _ensure_tesseract():
            return RecognitionResult(
                reader_name=self.reader_name, value=None, confidence=0.0,
                roi_name=self.roi.name, debug={"reason": "tesseract 未安装"})

        import pytesseract

        cropped = self.roi.crop(frame)
        if cropped.size == 0:
            return RecognitionResult(
                reader_name=self.reader_name, value=None, confidence=0.0,
                roi_name=self.roi.name)

        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        big = cv2.resize(gray, None, fx=self.upscale, fy=self.upscale,
                         interpolation=cv2.INTER_CUBIC)

        # 游戏 HUD 数字为亮字+深色描边:固定亮度截断(只留亮像素)效果最稳,
        # OTSU 作为兜底;正反相都试,取数字字符最多的一版
        _, bright = cv2.threshold(big, 180, 255, cv2.THRESH_BINARY)
        _, otsu = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidates = (bright, cv2.bitwise_not(bright), otsu, cv2.bitwise_not(otsu))

        whitelist = "0123456789%/" if self.percent else "0123456789/"
        config = f'--psm 7 --tessdata-dir "{TESSDATA_DIR}" -c tessedit_char_whitelist={whitelist}'
        text = ""
        # 白字黑底/黑字白底都试;百分比模式出结果即早退(省时)
        for candidate in (bright, cv2.bitwise_not(bright), otsu, cv2.bitwise_not(otsu)):
            try:
                result = pytesseract.image_to_string(candidate, config=config).strip()
            except Exception:
                continue
            if sum(ch.isdigit() for ch in result) > sum(ch.isdigit() for ch in text):
                text = result
            if self.percent and re.search(r"\d{1,3}\s*%", text):
                break
        text = text.replace(" ", "")

        if self.percent:
            # 百分比模式必须带 %,避免把非血量数字误读进来
            match = re.match(r"^(\d{1,3})\s*%", text)
        else:
            match = re.match(r"^(\d+)(?:/(\d+))?", text)
        if not match:
            return RecognitionResult(
                reader_name=self.reader_name, value=None, confidence=0.0,
                roi_name=self.roi.name, debug={"raw": text})

        value = int(match.group(1))
        confidence = min(1.0, sum(ch.isdigit() for ch in text) / max(1, len(text)))
        return RecognitionResult(
            reader_name=self.reader_name, value=value, confidence=confidence,
            roi_name=self.roi.name,
            candidates=[{"value": value, "percent": self.percent}],
            debug={"raw": text})


def make_number_reader(roi: ROI) -> BaseReader[int]:
    """数字读取出厂:优先 OCR,不可用时退回模板匹配"""
    if _ensure_tesseract():
        return OcrNumberReader(roi)
    return DigitSequenceReader(roi)


class OcrNameReader(BaseReader[str]):
    """OCR 识别敌方精灵名(中文,chi_sim 语言包 + 全精灵名单模糊纠错)"""

    reader_name = "ocr_name"
    PET_LIST_PATH = PROJECT_ROOT / "data" / "config" / "pet_names.txt"

    _pet_list: list[str] | None = None

    def __init__(self, roi: ROI, upscale: float = 3.5):
        super().__init__(roi)
        self.upscale = upscale

    @classmethod
    def _load_pets(cls) -> list[str]:
        if cls._pet_list is None:
            try:
                text = cls.PET_LIST_PATH.read_text(encoding="utf-8")
                cls._pet_list = [line.strip() for line in text.splitlines() if line.strip()]
            except Exception:
                cls._pet_list = []
        return cls._pet_list

    @classmethod
    def _correct_with_pet_list(cls, name: str):
        """用全精灵名单纠错:完全命中直接用;编辑距离足够近取最近名;否则 None"""
        if not name:
            return None, None
        pets = cls._load_pets()
        if not pets:
            return None, None
        if name in pets:
            return name, 1.0

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
        for pet in pets:
            if abs(len(pet) - len(name)) > 2:
                continue
            dist = levenshtein(name, pet)
            if dist < best_dist:
                best, best_dist = pet, dist
        # 允许的容错:名字越长容错越多,最多错 2 个字
        if best is not None and best_dist <= max(1, len(name) // 3 + (1 if len(name) >= 4 else 0)):
            ratio = 1.0 - best_dist / max(len(name), len(best))
            return best, round(ratio, 2)
        return None, None

    def read(self, frame: np.ndarray) -> RecognitionResult[str]:
        if not _ensure_tesseract() or not TESSDATA_DIR.exists():
            return RecognitionResult(
                reader_name=self.reader_name, value=None, confidence=0.0,
                roi_name=self.roi.name, debug={"reason": "tesseract/chi_sim 不可用"})

        import pytesseract

        cropped = self.roi.crop(frame)
        if cropped.size == 0:
            return RecognitionResult(
                reader_name=self.reader_name, value=None, confidence=0.0,
                roi_name=self.roi.name)

        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        big = cv2.resize(gray, None, fx=self.upscale, fy=self.upscale,
                         interpolation=cv2.INTER_CUBIC)
        _, bright = cv2.threshold(big, 180, 255, cv2.THRESH_BINARY)
        _, bright2 = cv2.threshold(big, 150, 255, cv2.THRESH_BINARY)
        _, otsu = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        config = f'--psm 7 --tessdata-dir "{TESSDATA_DIR}"'
        best_text, best_conf = "", -1.0
        for candidate in (bright, bright2, otsu,
                          cv2.bitwise_not(bright), cv2.bitwise_not(otsu)):
            try:
                data = pytesseract.image_to_data(
                    candidate, lang="chi_sim", config=config,
                    output_type=pytesseract.Output.DICT)
            except Exception:
                continue
            words = [(t.strip(), float(c)) for t, c in zip(data["text"], data["conf"])
                     if t.strip()]
            if not words:
                continue
            text = "".join(w for w, _ in words)
            conf = sum(wc * len(w) for w, wc in words) / max(1, len(text))
            if conf > best_conf:
                best_text, best_conf = text, conf
            # 早退:某种预处理已能命中精灵名单,不再试后面的(省大头耗时)
            corrected, _ = self._correct_with_pet_list(self._clean(text))
            if corrected:
                best_text, best_conf = text, max(conf, best_conf)
                break

        cleaned = self._clean(best_text)
        corrected, ratio = self._correct_with_pet_list(cleaned)
        value = corrected or (cleaned or None)
        debug = {"raw": best_text, "ocr_conf": round(best_conf, 1),
                 "corrected": corrected is not None, "ratio": round(ratio, 2) if ratio else None}
        confidence = min(1.0, max(0.0, best_conf / 100.0))
        return RecognitionResult(
            reader_name=self.reader_name, value=value, confidence=confidence,
            roi_name=self.roi.name, debug=debug)

    @staticmethod
    def _clean(text: str) -> str:
        """只保留中文/字母/数字,去除 OCR 噪点(性别符号、括号等)"""
        return "".join(ch for ch in text if ("\u4e00" <= ch <= "\u9fff") or ch.isalnum())


class DigitSequenceReader(BaseReader[int]):
    """Template-based digit reader for stable HUD numbers."""

    reader_name = "digit_sequence"

    def __init__(self, roi: ROI, template_dir: Path, min_score: float = 0.6):
        super().__init__(roi)
        self.templates = load_grayscale_templates(template_dir)
        self.min_score = min_score

    def read(self, frame: np.ndarray) -> RecognitionResult[int]:
        cropped = self.roi.crop(frame)
        binary = preprocess_digit_roi(cropped)
        boxes = split_digit_boxes(binary)
        digits: list[str] = []
        candidates: list[dict[str, float | str]] = []

        for x, y, w, h in boxes:
            roi_image = binary[y : y + h, x : x + w]
            name, score = best_template_match(roi_image, self.templates, threshold=self.min_score)
            if name is None or not name.isdigit():
                continue
            digits.append(name)
            candidates.append({"digit": name, "score": score, "box": (x, y, w, h)})

        value = int("".join(digits)) if digits else None
        confidence = min((float(item["score"]) for item in candidates), default=0.0)
        return RecognitionResult(
            reader_name=self.reader_name,
            value=value,
            confidence=confidence,
            roi_name=self.roi.name,
            candidates=candidates,
            debug={"box_count": len(boxes)},
        )


class DamageReader(DigitSequenceReader):
    reader_name = "damage_reader"

    def __init__(self, roi: ROI):
        super().__init__(roi, ASSET_ROOT / "digits")


class EnergyReader(DigitSequenceReader):
    reader_name = "energy_reader"

    def __init__(self, roi: ROI):
        super().__init__(roi, ASSET_ROOT / "digits")


class AvatarMatcher(BaseReader[str]):
    """Top-k avatar candidate matcher."""

    reader_name = "avatar_matcher"

    def __init__(self, roi: ROI):
        super().__init__(roi)
        self.templates = load_grayscale_templates(ASSET_ROOT / "avatars")

    def read(self, frame: np.ndarray) -> RecognitionResult[str]:
        cropped = self.roi.crop(frame)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        ranked = rank_template_matches(gray, self.templates, top_k=5)
        best = ranked[0] if ranked else {"name": None, "score": 0.0}
        return RecognitionResult(
            reader_name=self.reader_name,
            value=best["name"],
            confidence=float(best["score"]),
            roi_name=self.roi.name,
            candidates=ranked,
        )


class ElementMatcher(BaseReader[list[str]]):
    """Attribute icon matcher. Supports one or two element guesses."""

    reader_name = "element_matcher"

    def __init__(self, roi: ROI):
        super().__init__(roi)
        self.templates = load_grayscale_templates(ASSET_ROOT / "elements")

    def read(self, frame: np.ndarray) -> RecognitionResult[list[str]]:
        cropped = self.roi.crop(frame)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        ranked = rank_template_matches(gray, self.templates, top_k=4)
        selected = [str(item["name"]) for item in ranked if float(item["score"]) >= 0.65][:2]
        confidence = float(ranked[0]["score"]) if ranked else 0.0
        return RecognitionResult(
            reader_name=self.reader_name,
            value=selected or None,
            confidence=confidence,
            roi_name=self.roi.name,
            candidates=ranked,
        )
