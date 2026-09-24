# -*- coding: utf-8 -*-
"""ai_vision — AI 视觉识别配置与调用 (状态栏截图 → 多模态模型识图)

定位: 玩家在 ROI 工坊框好状态栏模板(pvp状态.json)后, 暂时用多模态 AI
直接"看"状态栏截图读出状态/印记, 替代尚未做的模板匹配识别。
只读辅助: 只截状态栏 ROI、只返回识别结果, 绝不点击/按键。

配置: data/config/ai_vision.json
    {
      "enabled": false,                    # 总开关(管线是否调用)
      "base_url": "http://127.0.0.1:7868/v1",
      "api_key": "DoubaoAPI",
      "model": "doubao/vision-express",
      "prompt": "...",                     # 识图提示词(留空用内置)
      "interval_s": 10,                    # 管线两次识别最小间隔(秒)
      "template": "pvp状态"                # ROI 模板名(状态框来源)
    }

调用方: pvp 管线 / bridge(手动测试)。API 不可达/超时返回带错误的 dict,
绝不抛异常打断识别引擎。
"""
from __future__ import annotations

import base64
import json
import time
import urllib.request
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parents[2] / "data" / "config" / "ai_vision.json"

DEFAULTS = {
    "enabled": False,
    "base_url": "http://127.0.0.1:7868/v1",
    "api_key": "DoubaoAPI",
    "model": "doubao/vision-express",
    "prompt": "",
    "interval_s": 10,
    "template": "pvp状态",
}

DEFAULT_PROMPT = (
    "这是洛克王国PVP对战中截取的状态栏截图。请识别其中的精灵状态/印记"
    "(如燃烧、冻结、中毒、麻痹、睡眠、恐惧、寄生、护盾、强化/弱化印记等), "
    "以简洁 JSON 返回, 不要输出多余文字: "
    '{"statuses": ["状态名", ...], "marks": ["印记名", ...], "raw": "画面原文"}'
)

# 管线节流: 每个框位独立记录上次识别时刻
_last_call_ts: dict = {}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except Exception:
        pass
    return cfg


def save_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def throttle_ok(key: str, interval_s: float) -> bool:
    """管线节流: 同一框位 interval_s 内只识别一次(手动测试不受限)"""
    now = time.time()
    if now - _last_call_ts.get(key, 0.0) < max(1.0, float(interval_s or 0)):
        return False
    _last_call_ts[key] = now
    return True


def crop_frame_to_jpeg_b64(frame, rois: list) -> list:
    """按 ROI 像素框(frame 为 numpy BGR 数组)裁图并编码 JPEG base64

    rois: [{"id","x","y","w","h"}]; 返回 [{"id", "data_url"}]
    """
    import cv2
    h, w = frame.shape[:2]
    out = []
    for r in rois:
        x = max(0, min(int(r.get("x", 0)), w - 1))
        y = max(0, min(int(r.get("y", 0)), h - 1))
        cw = max(4, min(int(r.get("w", 0)), w - x))
        ch = max(4, min(int(r.get("h", 0)), h - y))
        crop = frame[y:y + ch, x:x + cw]
        ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            out.append({
                "id": r.get("id", "roi"),
                "data_url": "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode(),
            })
    return out


def ask_vision(cfg: dict, crops: list, timeout: int = 45) -> dict:
    """把状态栏裁图发给多模态模型

    crops: crop_frame_to_jpeg_b64 的返回值 [{id, data_url}]
    返回: {"ok": True, "text": 模型回答, "elapsed": 秒} 或 {"ok": False, "error": ...}
    """
    if not crops:
        return {"ok": False, "error": "没有可识别的裁图"}
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "未配置 API 地址"}

    t0 = time.time()
    content = [{"type": "text",
                "text": (cfg.get("prompt") or "").strip() or DEFAULT_PROMPT}]
    for c in crops:
        content.append({"type": "text", "text": f"[框位: {c['id']}]"})
        content.append({"type": "image_url", "image_url": {"url": c["data_url"]}})
    body = {
        "model": cfg.get("model") or "doubao/vision-express",
        "messages": [{"role": "user", "content": content}],
    }
    try:
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {cfg.get('api_key') or 'none'}"},
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        text = str((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if not text:
            return {"ok": False, "error": "模型返回为空"}
        return {"ok": True, "text": text, "elapsed": round(time.time() - t0, 1)}
    except Exception as e:
        return {"ok": False, "error": str(e), "elapsed": round(time.time() - t0, 1)}
