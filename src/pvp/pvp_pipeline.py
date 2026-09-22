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
import sys
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


def _bundled_tesseract() -> Optional[Path]:
    """PyInstaller 打包环境下随包分发的 tesseract"""
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "tesseract" / "tesseract.exe"
        if bundled.exists():
            return bundled
    return None


def _ensure_tesseract() -> bool:
    import shutil
    import pytesseract
    if getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract") != "tesseract":
        return True
    bundled = _bundled_tesseract()
    if bundled:
        pytesseract.pytesseract.tesseract_cmd = str(bundled)
        return True
    if shutil.which("tesseract"):
        return True
    if _TESSERACT_PATH.exists():
        pytesseract.pytesseract.tesseract_cmd = str(_TESSERACT_PATH)
        return True
    return False


def ocr_number(crop: np.ndarray, percent: bool = False) -> Optional[str]:
    """数字识别(RapidOCR)。返回如 '100%' / '123/456' 或 None"""
    from src.utils.ocr_engine import read_combined
    if crop.size == 0:
        return None
    text, _ = read_combined(crop)
    if not text:
        return None
    text = text.replace(" ", "")
    if not sum(ch.isdigit() for ch in text):
        return None
    if percent:
        return text if re.search(r"\d{1,3}\s*%", text) else None
    m = re.search(r"\d+(?:/\d+)?", text)
    return m.group(0) if m else None


def ocr_name(crop: np.ndarray, pet_list: list[str]) -> tuple[Optional[str], float, str]:
    """中文精灵名识别(RapidOCR) + 名单模糊纠错"""
    from src.utils.ocr_engine import read_best
    text, score = read_best(crop)
    if not text:
        return None, 0.0, ""
    cleaned = "".join(ch for ch in text if ("\u4e00" <= ch <= "\u9fff") or ch.isalnum())
    matched = _fuzzy_match(cleaned, pet_list)
    value = matched or cleaned or None
    return value, min(1.0, score), text


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


# ---- 小尺寸 ROI 放大预处理 (解决 17px 高度读字问题) ----
def preprocess_text_roi(crop: np.ndarray, scale: int = 3) -> np.ndarray:
    """放大 + 对比度增强小尺寸文字区域"""
    if crop is None or crop.size == 0:
        return crop
    h, w = crop.shape[:2]
    resized = cv2.resize(crop, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    if len(resized.shape) == 3:
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    else:
        gray = resized
    enhanced = cv2.normalize(gray, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)


# ---- 敌方血条色彩积分 (0ms, 无需 OCR) ----
def enemy_hp_color_ratio(crop: np.ndarray) -> float:
    """计算敌方血条绿色/黄色/红色像素的水平占比 → 血量百分比"""
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # 精确绿色范围 (H: 35-85, 高饱和)
    mask_green = cv2.inRange(hsv, np.array([35, 70, 70]), np.array([85, 255, 255]))
    # 黄色范围 (H: 18-34)
    mask_yellow = cv2.inRange(hsv, np.array([18, 70, 70]), np.array([34, 255, 255]))
    # 红色范围 (H: 0-10 或 170-180)
    mask_red = cv2.inRange(hsv, np.array([0, 70, 70]), np.array([10, 255, 255]))
    mask_red2 = cv2.inRange(hsv, np.array([170, 70, 70]), np.array([180, 255, 255]))
    combined = mask_green | mask_yellow | mask_red | mask_red2

    col_sums = np.sum(combined, axis=0)
    active_cols = np.count_nonzero(col_sums > 0)
    total_cols = crop.shape[1]
    if total_cols == 0:
        return 0.0

    raw_ratio = active_cols / total_cols
    # 补偿血条左右内边距（通常各占 1~2%）
    adjusted = min(1.0, max(0.0, (raw_ratio - 0.02) / 0.96))
    return round(adjusted, 2)


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
    """批量识别中文(RapidOCR 合成一张图,一次调用)"""
    from src.utils.ocr_engine import get_ocr
    if not crops:
        return {}

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

    results = {rid: "" for rid, _ in crops}
    try:
        res, _ = get_ocr()(composite)
    except Exception as e:
        print(f"[PvpPipeline] RapidOCR 批量识别异常: {e}")
        return results
    if not res:
        return results

    # 按 y 中心分配回各个 ROI
    for box, text, _score in res:
        if box is None or len(box) == 0:
            continue
        cy = float(np.mean([p[1] for p in box]))
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
    enemy_name_via_avatar: bool = False   # 名字来自头像兜底/交叉覆盖(非 OCR 直读)
    player_name_via_avatar: bool = False
    enemy_hp_pct: float = 0.0  # 0.0-1.0
    enemy_hp_color: float = 0.0  # 色彩积分值
    skills: list[str] = field(default_factory=lambda: ["", "", "", ""])
    energy: str = ""
    energy_val: int = 0
    in_battle: bool = False
    errors: list[str] = field(default_factory=list)


class PvpPipeline:
    """PVP 实时识别管线 — 帧差跳帧 + 批量 OCR"""

    def __init__(self, template_path: Path = DEFAULT_TEMPLATE):
        self.template_path = template_path
        self._rois: dict = {}
        self._pet_list: list[str] = []
        self._load_template()
        self._load_pet_list()
        # 帧差跳帧缓存
        self._last_combined_hash: float | None = None
        self._cached_result: PvpResult | None = None
        # 头像模板库(懒加载: 导入失败/库为空时静默降级, 只走 OCR)
        self._avatar_lib: object | None = None
        self._avatar_tried = False
        # 聚能图标模板(in_battle 判定用): 战斗界面左下角聚能按钮, PVP/PVE 都有
        self._charge_tmpl: np.ndarray | None = None
        self._charge_tried = False

    def _charge_icon_present(self, frame: np.ndarray) -> bool:
        """战斗界面标志判定: 左下角聚能按钮模板匹配(PVP/PVE 都有该按钮)。
        模板未就绪/匹配异常时返回 False(不影响 OCR 兜底)。"""
        try:
            if self._charge_tmpl is None:
                if self._charge_tried:
                    return False
                self._charge_tried = True
                tmpl_path = PROJECT_ROOT / "data" / "config" / "roi_templates" / "聚能图标.png"
                if not tmpl_path.exists():
                    return False
                self._charge_tmpl = cv2.imdecode(
                    np.fromfile(str(tmpl_path), dtype=np.uint8), cv2.IMREAD_COLOR)
                if self._charge_tmpl is None:
                    return False
            # 聚能按钮固定在左下角 — 只搜左下 1/4 区域, 提速且防远处相似物
            fh, fw = frame.shape[:2]
            roi = frame[fh // 2:, :fw // 2]
            th, tw = self._charge_tmpl.shape[:2]
            if roi.shape[0] < th or roi.shape[1] < tw:
                return False
            res = cv2.matchTemplate(roi, self._charge_tmpl, cv2.TM_CCOEFF_NORMED)
            _, maxv, _, _ = cv2.minMaxLoc(res)
            return maxv >= 0.72
        except Exception:
            return False

    def _match_avatars(self, frame: np.ndarray) -> dict:
        """头像模板匹配兜底: 裁 我方/敌方精灵头像 ROI → PvpTemplateLibrary.match。
        库未加载/加载失败/ROI 缺失时返回空 dict(不阻塞主识别链)。"""
        out: dict = {}
        if self._avatar_lib is None:
            if self._avatar_tried:
                return out
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
            except Exception as e:
                self._avatar_err = str(e)   # 仅记录一次, 不阻塞主链
                return out
        for side, roi_id in (("player", "我方精灵头像"), ("enemy", "敌方精灵头像")):
            crop = self._crop(frame, roi_id)
            if crop is None or crop.size == 0:
                continue
            # 质量闸: ROI 被聊窗/弹层盖住时是低对比灰碎片, 模板匹配必瞎配
            # (实测定界: 清晰头像 std≈70/动态范围≈250, 被盖碎片 std≈18/范围≈84)
            g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            if float(g.std()) < 35 or (int(g.max()) - int(g.min())) < 120:
                continue
            try:
                hits = self._avatar_lib.match(crop, n_top=1)
            except Exception:
                continue
            # margin 闸: 第一名不显著领先第二名时是"一堆同模型精灵并列",
            # (如鸭吉吉/音速犬/霹雳迪迪同模型, raw 差 <0.1%) — 采纳必错, 宁可空名
            if hits and hits[0].get("confidence") in ("high", "medium")                     and float(hits[0].get("margin", 0)) >= 0.25:
                out[side] = hits[0]
        return out

    @staticmethod
    def _calc_hash(img: np.ndarray) -> float:
        """快速图像哈希：缩放到 16x16 取均值（< 1ms）"""
        if img is None or img.size == 0:
            return 0.0
        small = cv2.resize(img, (16, 16))
        return float(np.mean(small))

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

    def _build_composite(self, frame: np.ndarray) -> tuple[np.ndarray, list[tuple[str, np.ndarray]]] | None:
        """构建合成图(仅用于哈希) + 返回 padded crops(用于 OCR)"""
        all_crops: list[tuple[str, np.ndarray]] = []
        for roi_id in ["我方精灵名", "敌方精灵名", "我方血条", "敌方血条",
                       "技能1", "技能2", "技能3", "技能4", "剩余能量"]:
            crop = self._crop(frame, roi_id)
            if crop is not None:
                if crop.shape[0] < 30 or crop.shape[1] < 80:
                    crop = preprocess_text_roi(crop, scale=3)
                pad = max(10, min(crop.shape[0], crop.shape[1]) // 2)
                padded = cv2.copyMakeBorder(crop, pad, pad, pad, pad,
                                            cv2.BORDER_CONSTANT, value=(0, 0, 0))
                all_crops.append((roi_id, padded))

        if not all_crops:
            return None

        pad = 10
        total_h = sum(c.shape[0] + pad for _, c in all_crops) + pad
        max_w = max(c.shape[1] for _, c in all_crops) + pad * 2
        composite = np.zeros((total_h, max_w, 3), dtype=np.uint8)
        y = pad
        for _, c in all_crops:
            h, w = c.shape[:2]
            composite[y:y + h, pad:pad + w] = c
            y += h + pad

        return composite, all_crops

    def analyze(self, frame: np.ndarray) -> PvpResult:
        """分析一帧，返回 PvpResult。帧差跳帧：静止画面直接返回缓存 (0ms)"""
        result = PvpResult()

        # ---- 0. 敌方血条: 色彩积分 (0ms, 无需 OCR) ----
        enemy_hp_crop = self._crop(frame, "敌方血条")
        if enemy_hp_crop is not None:
            result.enemy_hp_color = enemy_hp_color_ratio(enemy_hp_crop)

        # ---- 1. 构建合成图 + 帧差跳帧 ----
        built = self._build_composite(frame)
        if built is None:
            return result

        composite, all_crops = built
        current_hash = self._calc_hash(composite)

        # 帧差 < 1.5 → 画面静止，直接返回缓存
        if (self._last_combined_hash is not None and
                self._cached_result is not None and
                abs(current_hash - self._last_combined_hash) < 1.5):
            # 更新色彩积分（只有这个不受 OCR 缓存影响）
            cached = self._cached_result
            cached.enemy_hp_color = result.enemy_hp_color
            return cached

        self._last_combined_hash = current_hash

        # ---- 2. PaddleOCR 批量识别 ----
        try:
            ocr_results = ocr_batch_chinese(all_crops)
        except Exception as e:
            result.errors.append(f"PaddleOCR: {e}")
            ocr_results = {}

        # ---- 3. 精灵名模糊匹配 ----
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

        # ---- 3.4 头像交叉验证(防恶意改名): 部分玩家把精灵命名成别的精灵的名字,
        # OCR 会自信读出假名(conf 0.9)。头像不会说谎 — 名字与头像冲突时头像赢。
        # 头像 unavailable(未收录/低质/低margin) 时保留 OCR 结果(此时无从证伪)。
        avatar_hits = self._match_avatars(frame)
        for side in ("player", "enemy"):
            hit = avatar_hits.get(side)
            if not hit:
                continue
            r = result.player_name if side == "player" else result.enemy_name
            conf = result.player_name_conf if side == "player" else result.enemy_name_conf
            if r and conf >= 0.9 and r != hit["name"]:
                # OCR 高置信名 vs 头像命中名冲突 → 改名欺诈嫌疑, 头像优先
                if side == "player":
                    result.player_name = hit["name"]
                    result.player_name_conf = 0.75 if hit["confidence"] == "high" else 0.5
                    result.player_name_via_avatar = True
                else:
                    result.enemy_name = hit["name"]
                    result.enemy_name_conf = 0.75 if hit["confidence"] == "high" else 0.5
                    result.enemy_name_via_avatar = True
                result.errors.append(
                    f"{'我方' if side == 'player' else '敌方'}名字与头像冲突 "
                    f"(OCR'{r}' → 头像'{hit['name']}', 疑似改名)")

        # ---- 3.5 头像兜底: 名字 OCR 失败/低置信时用精灵头像模板匹配 ----
        # (3.4 已跑过匹配, 此处直接复用结果)
        for side in ("player", "enemy"):
            hit = avatar_hits.get(side)
            if not hit:
                continue
            conf = result.player_name_conf if side == "player" else result.enemy_name_conf
            if conf < 0.5:
                if side == "player":
                    result.player_name = hit["name"]
                    result.player_name_conf = 0.75 if hit["confidence"] == "high" else 0.5
                    result.player_name_via_avatar = True
                    result.errors.append(f"我方名字走头像兜底: {hit['name']}({hit['confidence']})")
                else:
                    result.enemy_name = hit["name"]
                    result.enemy_name_conf = 0.75 if hit["confidence"] == "high" else 0.5
                    result.enemy_name_via_avatar = True
                    result.errors.append(f"敌方名字走头像兜底: {hit['name']}({hit['confidence']})")

        # ---- 4. 技能名 ----
        for i, roi_id in enumerate(["技能1", "技能2", "技能3", "技能4"]):
            result.skills[i] = ocr_results.get(roi_id, "")

        # ---- 5. 数字提取 ----
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

        # in_battle 判据(三选一, 防单点失效):
        # 1. 聚能图标(战斗界面标志) — 但放大招时会消失, 不能单用
        # 2. 我方名字高置信(≥0.9 词库模糊命中) + 我方血量数字同时在场
        #    (菜单/野外误 OCR 出"精灵名"通常无血量数字伴随, 双条件可滤)
        # 3. 敌方血条色条存在(非零) + 敌方名条 OCR 有字
        charge_seen = self._charge_icon_present(frame)
        self_hud = (result.player_hp != "" and result.player_name_conf >= 0.9)
        enemy_hud = (result.enemy_hp_color > 0.0 and bool(result.enemy_name))
        result.in_battle = charge_seen or self_hud or enemy_hud
        if not result.in_battle:
            # 非战斗态: 清空精灵名/技能识别 — 防地图/菜单 UI 文字被当成精灵名
            # 混进换宠检测与推演("乱识别精灵名"的根治)
            result.player_name = ""
            result.enemy_name = ""
            result.player_name_conf = 0.0
            result.enemy_name_conf = 0.0
            result.skills = ["", "", "", ""]

        # 缓存结果
        self._cached_result = result
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
                "name_via_avatar": result.player_name_via_avatar,
                "energy": result.energy,
                "energy_val": result.energy_val,
            },
            "enemy": {
                "name": result.enemy_name,
                "name_conf": result.enemy_name_conf,
                # 名字来自头像(而非 OCR 直读): 可能是改名精灵的真实身份, 前端可加标记
                "name_via_avatar": result.enemy_name_via_avatar,
                "hp_pct": result.enemy_hp_pct,
                "hp_color": result.enemy_hp_color,
                # 敌方 HUD 可信度: 血条色为 0 且名字低置信 → 大概率被弹窗/聊窗遮挡,
                # 前端据此显示"敌方疑似被遮挡", 不把 hp=0 当真值渲染
                "occluded": (result.enemy_hp_color <= 0.0
                             and result.enemy_name_conf < 0.9),
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