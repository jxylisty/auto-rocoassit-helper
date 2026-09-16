# -*- coding: utf-8 -*-
"""
PVP 数据采集器 —— 为精灵头像/名牌模板训练收集素材

自动模式(每2秒):
  - 检测敌方血条色彩积分 → 判定是否在战斗
  - 敌方名字 OCR 命中精灵名单 → 保存头像裁剪 + 名牌裁剪(按名字去重)
  - 名字 OCR 失败 → 保存整帧 + 名牌裁剪到 ocr_fail(30秒限流) ← 训练素材最重要来源
手动: F7 保存当前整帧(战备阶段我方阵容等任何想留的画面)

输出结构(output/ 下):
  enemy_avatar/   敌方头像裁剪  文件名=识别出的精灵名
  enemy_nameplate/ 敌方名牌裁剪
  ocr_fail/       OCR失败帧(整图+裁剪, 成对)
  manual/         手动截图
  manifest.jsonl  每张图的元数据(时间/识别结果/置信度)

打包后独立运行,不需要安装 Python。
"""

from __future__ import annotations

import base64
import ctypes
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


def _resolve_base() -> Path:
    """源码运行=项目根;PyInstaller 打包=解包目录(_MEIPASS)"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


BASE = _resolve_base()
if not getattr(sys, "frozen", False):
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))

from src.capture.window_capture import find_window  # noqa: E402
from src.pvp import pvp_pipeline as pp  # noqa: E402

# 打包环境的资源路径解析。
# 注意: 本体打包(app_entry)已把 pp.* 指到 exe/data,这里不覆盖;
# 只在独立采集器包(布局为 _MEIPASS/resources)下才需要本模块自行指路。
if getattr(sys, "frozen", False) and not getattr(pp, "_APP_ENTRY_PATCHED", False):
    pp.PROJECT_ROOT = BASE
    standalone_template = BASE / "resources" / "PVP标准模板.json"
    if standalone_template.exists():
        pp.DEFAULT_TEMPLATE = standalone_template
    standalone_tessdata = BASE / "tessdata"
    if standalone_tessdata.exists():
        pp.TESSDATA_DIR = standalone_tessdata


def resolve_template_path() -> Path:
    """按存在性依次回退,兼容两种打包布局与源码运行"""
    candidates = [
        pp.DEFAULT_TEMPLATE,
        BASE / "resources" / "PVP标准模板.json",
        BASE / "data" / "config" / "roi_templates" / "PVP标准模板.json",
        BASE / "data" / "config" / "roi_config.json",
    ]
    for c in candidates:
        try:
            if c and Path(c).exists():
                return Path(c)
        except Exception:
            continue
    return Path(candidates[-1])


class PvpDataCollector:
    """自动+手动 PVP 数据采集"""

    def __init__(self, output_dir: Path | None = None):
        self.output = output_dir or (Path.cwd() / "output")
        for sub in ("enemy_avatar", "enemy_nameplate", "ocr_fail", "manual"):
            (self.output / sub).mkdir(parents=True, exist_ok=True)
        self.manifest = self.output / "manifest.jsonl"

        self.template = self._load_rois()
        self.pet_list = self._load_pet_list()
        self._collected_names: set[str] = set()
        self._last_fail_save = 0.0
        self._last_fail_hash = None
        self.stats = {"auto_saved": 0, "fail_saved": 0, "manual_saved": 0, "battles_seen": set()}

    # ---------- 资源 ----------

    @staticmethod
    def _load_rois() -> dict:
        path = resolve_template_path()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        base_w, base_h = data["base_resolution"]
        return {r["id"]: dict(r, base_w=base_w, base_h=base_h) for r in data["rois"]}

    @staticmethod
    def _load_pet_list() -> list[str]:
        path = pp.PROJECT_ROOT / "data" / "config" / "pet_names.txt"
        if path.exists():
            return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return []

    # ---------- 截取 ----------

    def capture(self):
        """截取游戏窗口当前画面,失败返回 None"""
        info = find_window(class_name="UnrealWindow")
        if not info or info.width < 300:
            return None
        if ctypes.windll.user32.IsIconic(info.hwnd):
            return None
        from PIL import ImageGrab
        left, top, right, bottom = info.rect
        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
        frame = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
        if float(frame.std()) < 3.0:
            return None  # 全黑(窗口被遮挡/最小化)
        return frame

    def crop_roi(self, frame: np.ndarray, roi_id: str):
        roi = self.template.get(roi_id)
        if not roi or "rw" not in roi:
            return None
        h, w = frame.shape[:2]
        x, y = int(roi["rx"] * w), int(roi["ry"] * h)
        cw, ch = int(roi["rw"] * w), int(roi["rh"] * h)
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(w, x + cw), min(h, y + ch)
        if x2 - x1 < 4 or y2 - y1 < 4:
            return None
        return frame[y1:y2, x1:x2].copy()

    # ---------- 判定 ----------

    def check_battle(self, frame: np.ndarray):
        """返回 (in_battle: bool, enemy_name: str|None, conf: float)"""
        # 敌方血条色彩积分
        bar = self.crop_roi(frame, "敌方血条")
        if bar is None or float(pp.enemy_hp_color_ratio(bar)) < 0.02:
            return False, None, 0.0

        name_crop = self.crop_roi(frame, "敌方精灵名")
        if name_crop is None:
            return True, None, 0.0
        name, conf, _raw = pp.ocr_name(name_crop, self.pet_list)
        return True, name, conf

    # ---------- 保存 ----------

    def _save(self, folder: str, name: str, image: np.ndarray, meta: dict) -> str:
        path = self.output / folder / f"{name}.png"
        ok = cv2.imencode(".png", image)[1]
        ok.tofile(str(path))
        meta.update({"file": str(path.relative_to(self.output)), "time": datetime.now().isoformat(timespec="seconds")})
        with open(self.manifest, "a", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        return str(path)

    def save_manual(self, reason: str = "手动") -> str | None:
        frame = self.capture()
        if frame is None:
            return None
        ts = datetime.now().strftime("%H%M%S")
        path = self._save("manual", f"manual_{ts}", frame, {"type": "manual", "reason": reason})
        self.stats["manual_saved"] += 1
        return path

    def auto_collect(self) -> str:
        """自动采集一轮,返回状态描述"""
        frame = self.capture()
        if frame is None:
            return "游戏窗口不可见"
        in_battle, name, conf = self.check_battle(frame)
        if not in_battle:
            return "未在战斗"

        if name and conf >= 0.5:
            if name in self._collected_names:
                return f"战斗中({name},已收过)"
            # 新精灵: 存头像 + 名牌
            avatar = self.crop_roi(frame, "敌方精灵头像")
            plate = self.crop_roi(frame, "敌方精灵名")
            ts = datetime.now().strftime("%H%M%S")
            if avatar is not None:
                self._save("enemy_avatar", f"{name}_{ts}", avatar,
                           {"type": "enemy_avatar", "ocr": name, "conf": round(conf, 2)})
            if plate is not None:
                self._save("enemy_nameplate", f"{name}_{ts}", plate,
                           {"type": "enemy_nameplate", "ocr": name, "conf": round(conf, 2)})
            self._collected_names.add(name)
            self.stats["auto_saved"] += 1
            self.stats["battles_seen"].add(name)
            return f"✓ 已采集 {name}"
        else:
            # OCR 失败: 整帧 + 名牌成对保存(30s 限流 + 名牌哈希去重)
            now = time.time()
            plate = self.crop_roi(frame, "敌方精灵名")
            plate_hash = hash(plate.tobytes()) if plate is not None else None
            if now - self._last_fail_save < 30 or plate_hash == self._last_fail_hash:
                return "战斗中(名字OCR失败,限流中)"
            ts = datetime.now().strftime("%m%d_%H%M%S")
            self._save("ocr_fail", f"fail_{ts}_full", frame,
                       {"type": "ocr_fail_full", "ocr": name, "conf": round(conf, 2)})
            if plate is not None:
                self._save("ocr_fail", f"fail_{ts}_plate", plate,
                           {"type": "ocr_fail_plate", "ocr": name, "conf": round(conf, 2)})
            self._last_fail_save = now
            self._last_fail_hash = plate_hash
            self.stats["fail_saved"] += 1
            return "⚠ 名字OCR失败,已保存失败样本"

    def summary(self) -> str:
        s = self.stats
        return (f"自动采集 {s['auto_saved']} 只 | 失败样本 {s['fail_saved']} 组 | "
                f"手动 {s['manual_saved']} 张 | 遇到精灵 {len(s['battles_seen'])} 种")
