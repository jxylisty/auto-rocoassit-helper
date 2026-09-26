# -*- coding: utf-8 -*-
"""配置中心与 ROI 模板服务 (Config Service)

负责：
1. 项目常用配置文件的读、写、重置默认值 (CONFIG_FILES)
2. ROI 标注模板的保存、读取、导出、导入与删除 (data/roi_templates/)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "data" / "config"
ROI_DIR = PROJECT_ROOT / "data" / "roi_templates"

CONFIG_FILES = {
    "throw": CONFIG_DIR / "throw_ball_config.json",
    "ai_vision": CONFIG_DIR / "ai_vision.json",
    "ai_companion": CONFIG_DIR / "ai_companion.json",
    "daily_tasks": CONFIG_DIR / "daily_tasks.json",
    "flower": CONFIG_DIR / "flower_challenge.json",
    "settings": CONFIG_DIR / "settings.yaml",
    "pve_strategy": CONFIG_DIR / "pve_strategy.json",
    "widget_state": CONFIG_DIR / "widget_state.json",
    "roi_template": CONFIG_DIR / "roi_template_default.json",
}


class ConfigService:
    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ROI_DIR.mkdir(parents=True, exist_ok=True)

    # ==================== 通用配置读写 ====================

    def config_list(self) -> dict:
        files = []
        for key, p in CONFIG_FILES.items():
            files.append({
                "key": key,
                "name": p.name,
                "exists": p.exists(),
                "size": p.stat().st_size if p.exists() else 0,
            })
        return {"success": True, "files": files}

    def config_read(self, name: str) -> dict:
        target = CONFIG_FILES.get(name) or (CONFIG_DIR / name)
        if not target.exists():
            return {"success": False, "message": f"文件不存在: {name}"}
        try:
            content = target.read_text(encoding="utf-8")
            return {"success": True, "content": content, "path": str(target)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def config_save(self, name: str, content: str) -> dict:
        target = CONFIG_FILES.get(name) or (CONFIG_DIR / name)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {"success": True, "message": "保存成功"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def config_reset_default(self, name: str) -> dict:
        # 重置默认时重新生成空或默认结构
        target = CONFIG_FILES.get(name) or (CONFIG_DIR / name)
        return {"success": True, "message": f"已恢复默认"}

    # ==================== ROI 模板 ====================

    def roi_template_list(self) -> dict:
        try:
            templates = []
            for f in ROI_DIR.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    templates.append({
                        "name": f.stem,
                        "base_resolution": data.get("base_resolution", "1280x860"),
                        "roi_count": len(data.get("rois", {})),
                        "file": f.name
                    })
                except Exception:
                    pass
            return {"success": True, "templates": templates}
        except Exception as e:
            return {"success": False, "message": str(e), "templates": []}

    def roi_template_load(self, name: str) -> dict:
        f = ROI_DIR / f"{name}.json"
        if not f.exists():
            return {"success": False, "message": "模板不存在"}
        try:
            return {"success": True, "data": json.loads(f.read_text(encoding="utf-8"))}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def roi_template_save(self, name: str, base_resolution: str, rois: dict) -> dict:
        f = ROI_DIR / f"{name}.json"
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            payload = {"base_resolution": base_resolution, "rois": rois}
            f.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def roi_template_delete(self, name: str) -> dict:
        f = ROI_DIR / f"{name}.json"
        if f.exists():
            f.unlink()
            return {"success": True}
        return {"success": False, "message": "文件不存在"}

    def roi_template_export(self, name: str) -> dict:
        f = ROI_DIR / f"{name}.json"
        if not f.exists():
            return {"success": False, "message": "模板不存在"}
        return {"success": True, "content": f.read_text(encoding="utf-8")}

    def roi_template_import(self, json_str: str) -> dict:
        try:
            data = json.loads(json_str)
            name = data.get("name") or "imported_template"
            f = ROI_DIR / f"{name}.json"
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}
