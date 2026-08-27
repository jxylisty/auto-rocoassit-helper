# -*- coding: utf-8 -*-
"""ROI 模板系统 — 归一化坐标，支持多分辨率自适应

数据格式:
{
  "name": "PVP标准模板",
  "base_resolution": [1920, 1080],
  "rois": [
    {"id": "enemy_name", "label": "敌方名称", "tag": "enemy_team",
     "color": "#f87171", "rx": 0.05, "ry": 0.10, "rw": 0.15, "rh": 0.04}
  ]
}

动态映射: x = rx * frame_w, y = ry * frame_h
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "data" / "config" / "roi_templates"
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "._- ").strip().replace(" ", "_")


def list_templates() -> List[Dict[str, Any]]:
    """列出所有模板"""
    result = []
    for f in sorted(TEMPLATE_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({
                "name": data.get("name", f.stem),
                "filename": f.name,
                "base_resolution": data.get("base_resolution", [1920, 1080]),
                "roi_count": len(data.get("rois", [])),
                "tags": list(set(r.get("tag", "") for r in data.get("rois", []))),
            })
        except Exception:
            pass
    return result


def save_template(name: str, base_resolution: List[int], rois: List[Dict]) -> Dict[str, Any]:
    """保存模板"""
    filename = _sanitize_filename(name) + ".json"
    data = {
        "name": name,
        "base_resolution": base_resolution,
        "rois": rois,
    }
    (TEMPLATE_DIR / filename).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"success": True, "filename": filename}


def load_template(name: str) -> Optional[Dict[str, Any]]:
    """加载模板"""
    filename = _sanitize_filename(name) + ".json"
    path = TEMPLATE_DIR / filename
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def export_template(name: str) -> Optional[str]:
    """导出模板为 JSON 字符串"""
    data = load_template(name)
    if data is None:
        return None
    return json.dumps(data, ensure_ascii=False, indent=2)


def import_template(json_str: str) -> Dict[str, Any]:
    """从 JSON 字符串导入模板"""
    data = json.loads(json_str)
    name = data.get("name", "imported")
    base_resolution = data.get("base_resolution", [1920, 1080])
    rois = data.get("rois", [])
    return save_template(name, base_resolution, rois)


def delete_template(name: str) -> Dict[str, Any]:
    """删除模板"""
    filename = _sanitize_filename(name) + ".json"
    path = TEMPLATE_DIR / filename
    if path.exists():
        path.unlink()
        return {"success": True}
    return {"success": False, "message": "模板不存在"}


def resolve_rois(template_name: str, frame_w: int, frame_h: int,
                 tag_filter: List[str] = None) -> List[Dict[str, Any]]:
    """加载模板并映射到实际像素坐标"""
    data = load_template(template_name)
    if not data:
        return []

    base_w, base_h = data.get("base_resolution", [1920, 1080])
    rois = []
    for r in data.get("rois", []):
        if tag_filter and r.get("tag", "") not in tag_filter:
            continue
        rois.append({
            "id": r.get("id", ""),
            "label": r.get("label", ""),
            "tag": r.get("tag", ""),
            "color": r.get("color", "#6366f1"),
            "x": int(r.get("rx", 0) * frame_w),
            "y": int(r.get("ry", 0) * frame_h),
            "w": int(r.get("rw", 0) * frame_w),
            "h": int(r.get("rh", 0) * frame_h),
            "rx": r.get("rx", 0),
            "ry": r.get("ry", 0),
            "rw": r.get("rw", 0),
            "rh": r.get("rh", 0),
        })
    return rois


# 预设模板
PVP_DEFAULT_TEMPLATE = {
    "name": "PVP标准模板",
    "base_resolution": [1920, 1080],
    "rois": [
        {"id": "enemy_name", "label": "敌方名称", "tag": "enemy_team",
         "color": "#f87171", "rx": 0.02, "ry": 0.12, "rw": 0.12, "rh": 0.03},
        {"id": "enemy_elements", "label": "敌方属性", "tag": "enemy_team",
         "color": "#fbbf24", "rx": 0.02, "ry": 0.16, "rw": 0.08, "rh": 0.03},
        {"id": "enemy_hp", "label": "敌方血量", "tag": "enemy_team",
         "color": "#4ade80", "rx": 0.02, "ry": 0.20, "rw": 0.10, "rh": 0.03},
        {"id": "battle_left", "label": "战斗图标·左", "tag": "battle_hud",
         "color": "#a78bfa", "rx": 0.02, "ry": 0.85, "rw": 0.06, "rh": 0.06},
        {"id": "battle_right", "label": "战斗图标·右", "tag": "battle_hud",
         "color": "#f472b6", "rx": 0.88, "ry": 0.85, "rw": 0.06, "rh": 0.06},
    ],
}


def ensure_default_template():
    """确保默认模板存在"""
    if not load_template("PVP标准模板"):
        save_template("PVP标准模板",
                       PVP_DEFAULT_TEMPLATE["base_resolution"],
                       PVP_DEFAULT_TEMPLATE["rois"])


def get_scaled_roi(roi_id: str, current_width: int, current_height: int,
                   template_name: str = None) -> Optional[Dict[str, int]]:
    """获取单个 ROI 在当前分辨率下的像素坐标

    若尺寸等于基准分辨率，返回 rect_abs；否则用 rect_norm 动态缩放。
    """
    data = load_template(template_name) if template_name else None
    if not data:
        return None
    base_w, base_h = data.get("base_resolution", [1920, 1080])
    for r in data.get("rois", []):
        if r.get("id") != roi_id:
            continue
        rx, ry, rw, rh = r.get("rx", 0), r.get("ry", 0), r.get("rw", 0), r.get("rh", 0)
        return {
            "x": int(rx * current_width),
            "y": int(ry * current_height),
            "w": int(rw * current_width),
            "h": int(rh * current_height),
        }
    return None


def set_active_template(template_name: str, mode: str = "pvp") -> Dict[str, Any]:
    """将模板设为指定模式的活跃模板，写入 settings.yaml"""
    import yaml
    from pathlib import Path
    settings_path = Path(__file__).resolve().parents[2] / "data" / "config" / "settings.yaml"
    try:
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    if "roi" not in data:
        data["roi"] = {}
    data["roi"][f"{mode}_template"] = template_name
    settings_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"success": True, "mode": mode, "template": template_name}


# 模块加载时创建默认模板
ensure_default_template()