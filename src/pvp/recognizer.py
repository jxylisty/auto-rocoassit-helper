# -*- coding: utf-8 -*-
"""
PVP 精灵识别封装 — 封装 pvp_lib 识别功能，提供 Python API
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

# 注入 lib 目录到 sys.path
LIB_DIR = Path(__file__).resolve().parent / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

# 设置模板库目录
import os
os.environ.setdefault("PVP_LIB_DIR", str(LIB_DIR / "output" / "pvp_lib"))

from pvp_lib import PvpLib  # noqa: E402


class PvpRecognizer:
    """PVP 精灵识别器"""

    def __init__(self):
        self._lib = PvpLib()

    @property
    def status(self) -> dict:
        """获取模板库状态"""
        return self._lib.status()

    def recognize_image(self, image_path: str, force_image: bool = False) -> List[Dict[str, Any]]:
        """
        识别单张截图中的精灵
        
        返回: [{"name": "迪莫", "seq": 1, "confidence": 0.95, "method": "ocr", ...}, ...]
        """
        results = self._lib.recognize(image_path, force_image=force_image)
        return results

    def recognize_from_frame(self, frame, force_image: bool = False) -> List[Dict[str, Any]]:
        """
        从 numpy 数组（OpenCV 图像）识别精灵
        
        frame: numpy.ndarray (BGR)
        """
        import tempfile
        import cv2

        tmp_path = Path(tempfile.gettempdir()) / f"pvp_recognize_{hash(frame.tobytes()) & 0xFFFFFFFF}.png"
        cv2.imwrite(str(tmp_path), frame)
        try:
            return self.recognize_image(str(tmp_path), force_image=force_image)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def ingest(self, path: str) -> dict:
        """
        入库：从截图目录/单张图片中提取精灵头像并入库
        
        返回: {"added": 5, "skipped": 3, "total": 202}
        """
        return self._lib.ingest(path)

    def eval(self) -> dict:
        """留一法自测"""
        return self._lib.eval()


# 全局单例
_recognizer: Optional[PvpRecognizer] = None


def get_recognizer() -> PvpRecognizer:
    """获取全局识别器实例"""
    global _recognizer
    if _recognizer is None:
        _recognizer = PvpRecognizer()
    return _recognizer


def recognize_pvp_pets(image_path: str, force_image: bool = False) -> List[Dict[str, Any]]:
    """快捷方法：识别 PVP 截图中的精灵"""
    return get_recognizer().recognize_image(image_path, force_image=force_image)


def ingest_pvp_templates(path: str) -> dict:
    """快捷方法：入库 PVP 模板"""
    return get_recognizer().ingest(path)


def get_pvp_lib_status() -> dict:
    """快捷方法：获取模板库状态"""
    return get_recognizer().status