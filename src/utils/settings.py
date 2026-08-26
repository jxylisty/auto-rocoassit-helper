# -*- coding: utf-8 -*-
"""settings.yaml 统一配置读取入口

所有模块需要读全局配置时都用这里,避免各自散落读文件。
文件不存在或解析失败时返回空配置,由调用方用默认值兜底。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "data" / "config" / "settings.yaml"

_lock = threading.Lock()
_cache: dict | None = None


def load_settings(force: bool = False) -> dict:
    """读取(并缓存)settings.yaml,失败返回空 dict"""
    global _cache
    with _lock:
        if _cache is None or force:
            try:
                import yaml
                _cache = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8")) or {}
            except Exception:
                _cache = {}
        return _cache


def get(path: str, default: Any = None) -> Any:
    """按点路径取配置值,例如 get('gui.width', 1150)"""
    node: Any = load_settings()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def invalidate() -> None:
    """配置中心保存 settings.yaml 后调用,下次读取重新加载"""
    global _cache
    with _lock:
        _cache = None
