# -*- coding: utf-8 -*-
"""
背包咕噜球盘点扫描器

用户在视觉调试台框好「背包.json」:
- roi_1: 网格 (0,0) 格(第一列第一行的球图标+数量)
- roi_2: 网格 (1,1) 对角格 → 由两格中心差值得出列步长 dx / 行步长 dy
- 背包整体ocr: 背包网格总区域(扫描在此范围内进行, 越界即停)

扫描: 按网格逐格模板匹配(识球种) + 数字 OCR(数量), 输出 {球: 数量} 清单。
两次盘点做减法 → 各球实际消耗。版本更新球变多导致翻页的问题: 网格按区域边界自动
扩行, 单屏仍放不下的翻页扫描留待实际验证后追加。
"""
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np

from src.perception.ball_watcher import BallTemplateMatcher, BallSlotWatcher
from src.utils.ocr_engine import read_combined

ROI_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "pvp" / "data"
BAG_ROI_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "config" / "roi_templates" / "背包.json"
BAG_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "config" / "bag_inventory.json"

COUNT_ROI_SPLIT = 0.70   # 格子下部 30% 为数量数字条带


BAG_OPEN_DEBOUNCE = 4.0   # 背包打开防抖(秒): 防连点/重复触发


def load_bag_button_roi() -> Optional[tuple]:
    """背包按钮 ROI (背包.json 的「背包按钮」) → (rx, ry, rw, rh)"""
    try:
        data = json.loads(BAG_ROI_PATH.read_text(encoding="utf-8"))
        for r in data.get("rois", []):
            rid = str(r.get("id", "")) + str(r.get("label", ""))
            if "背包按钮" in rid or "bag_button" in rid.lower() or ("背包" in rid and "按钮" in rid):
                return (r["rx"], r["ry"], r["rw"], r["rh"])
    except Exception:
        pass
    return None


def load_bag_filter_roi() -> Optional[tuple]:
    """咕噜球筛选按钮 ROI (背包.json 的「咕噜球筛选」) → (rx, ry, rw, rh)"""
    try:
        data = json.loads(BAG_ROI_PATH.read_text(encoding="utf-8"))
        for r in data.get("rois", []):
            rid = str(r.get("id", "")) + str(r.get("label", ""))
            if "筛选" in rid or "filter" in rid.lower():
                return (r["rx"], r["ry"], r["rw"], r["rh"])
    except Exception:
        pass
    return None


def _force_foreground(hwnd: int, attempts: int = 3) -> bool:
    """可靠地把游戏窗口拉到前台并拿到键盘焦点。
    pywebview API 跑在后台线程, 直接 SetForegroundWindow 常被 Windows 拒绝
    (后台进程无置前权) → 先 AttachThreadInput 借前台线程的输入状态再切, 重试多次。
    返回是否真的成为前台窗口。"""
    import time as _t
    import win32gui
    import win32process
    import win32api
    try:
        cur_tid, _ = win32process.GetWindowThreadProcessId(
            win32gui.GetForegroundWindow())
        dst_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:
        return False
    for i in range(attempts):
        try:
            if win32gui.GetForegroundWindow() == hwnd:
                return True
            # Esc 关掉可能打开着的游戏菜单(半透明遮罩会挡点击), 再置前
            if i > 0:
                try:
                    win32api.keybd_event(0x1B, 0, 0, 0)      # Esc down
                    win32api.keybd_event(0x1B, 0, 2, 0)      # Esc up
                    _t.sleep(0.4)
                except Exception:
                    pass
            attached = False
            try:
                if cur_tid != dst_tid:
                    attached = win32process.AttachThreadInput(cur_tid, dst_tid, True)
                win32gui.SetForegroundWindow(hwnd)
                win32gui.BringWindowToTop(hwnd)
            finally:
                if attached:
                    try:
                        win32process.AttachThreadInput(cur_tid, dst_tid, False)
                    except Exception:
                        pass
            _t.sleep(0.5)
        except Exception:
            _t.sleep(0.4)
    return win32gui.GetForegroundWindow() == hwnd


def open_bag_click(button_roi: tuple = None, filter_roi: tuple = None) -> bool:
    """游戏获得焦点 → 按 Esc 呼出菜单 → 点击「背包按钮」 → 点击「咕噜球筛选」。
    坐标换算: 窗口rect + 归一化中心 → 屏幕坐标。
    注意顺序: 必须先给游戏键盘焦点, 否则 Esc 会打到别的窗口。"""
    import time as _t
    from src.driver import human_input
    from src.capture.window_capture import find_window
    import interception
    import win32gui

    info = find_window(class_name="UnrealWindow") or find_window()
    if not info or info.width < 50 or info.height < 50:
        return False

    # 1. 游戏窗口置顶激活(关键: 没焦点 Esc 无效; 失败则整链不执行, 避免空扫)
    if not _force_foreground(info.hwnd):
        return False

    left, top, right, bottom = info.rect
    w, h = right - left, bottom - top

    if button_roi is None:
        button_roi = load_bag_button_roi()
    if not button_roi:
        return False

    rx, ry, rw, rh = button_roi
    target_x = left + int((rx + rw / 2.0) * w)
    target_y = top + int((ry + rh / 2.0) * h)

    def _click(x: int, y: int):
        """内核级单击(拟人节奏)"""
        interception.move_to(x, y)
        _t.sleep(0.08)
        interception.mouse_down(button="left")
        _t.sleep(0.09)
        interception.mouse_up(button="left")

    # 2. Esc 呼出菜单 → 点背包按钮 (带一次重试: 菜单动画慢时首次点击常落空)
    for attempt in range(2):
        human_input.press("esc")      # 呼出菜单
        _t.sleep(0.8 if attempt == 0 else 1.2)   # 等菜单动画(重试时给更久)
        _click(target_x, target_y)
        _t.sleep(1.4)                 # 等背包界面打开(渲染网格)
        # 打开确认: 截一帧看「背包按钮 ROI」区域是否已被背包界面替换
        try:
            from src.capture.window_capture import find_window as _fw
            info2 = _fw(class_name="UnrealWindow") or _fw()
            if info2:
                from src.capture.fast_capture import FastCapture
                fc = FastCapture()
                frame = fc.capture(rect=info2.rect)
                if frame is not None and frame.size and _bag_ui_visible(frame, info2):
                    break
        except Exception:
            pass
        if attempt == 0:
            _t.sleep(0.5)  # 未确认打开, 稍候重试整条链

    # 3. 自动点击「咕噜球筛选」Tab (若配置)
    if filter_roi is None:
        filter_roi = load_bag_filter_roi()
    if filter_roi:
        fx, fy, fw, fh = filter_roi
        filter_x = left + int((fx + fw / 2.0) * w)
        filter_y = top + int((fy + fh / 2.0) * h)
        _click(filter_x, filter_y)
        _t.sleep(0.5)                 # 等待筛选切换/网格刷新

    return True


def _bag_ui_visible(frame, info) -> bool:
    """判断背包界面是否已打开(打开确认信号):
    「背包按钮」屏幕位置的颜色与菜单态差异大 → 菜单已关闭/被界面覆盖。
    简化判据: Esc 菜单是半透明遮罩, 打开菜单时该点亮度明显低于主界面亮色按钮;
    背包界面打开后按钮区域被背包面板覆盖。任一状态均视为"菜单已推进"。"""
    try:
        import numpy as np
        roi = load_bag_button_roi()
        if not roi:
            return True   # 无法判定时不阻塞主链
        rx, ry, rw, rh = roi
        h, w = frame.shape[:2]
        patch = frame[int(ry * h):int((ry + rh) * h),
                      int(rx * w):int((rx + rw) * w)]
        if patch.size == 0:
            return True
        mean = float(np.mean(patch))
        # 菜单开着时该按钮在半透明暗遮罩下, 均值低; 菜单关闭(点击成功)后该点恢复亮色
        return mean > 90
    except Exception:
        return True


def load_bag_layout() -> Optional[dict]:
    """读取 背包.json → {anchor(中心cx,cy), cell_w, cell_h, dx, dy, region(l,t,r,b)}"""
    try:
        data = json.loads(BAG_ROI_PATH.read_text(encoding="utf-8"))
        rois = {str(r.get("id")): r for r in data.get("rois", [])}
        region = rois.get("背包整体ocr") or rois.get("背包整体")
        if not region:
            for r in data.get("rois", []):
                rid = str(r.get("id", "")) + str(r.get("label", ""))
                if "整体" in rid or "ocr" in rid.lower():
                    region = r
                    break
        if not region:
            return None

        # 锚点寻找: 优先按 label 或 id 精确匹配 roi_1 和 roi_2
        r1, r2 = None, None
        for r in data.get("rois", []):
            label = str(r.get("label", ""))
            rid = str(r.get("id", ""))
            if label == "roi_1" or rid in ("roi_1", "123"):
                r1 = r
            elif label == "roi_2" or rid == "roi_2":
                r2 = r

        # 兜底: 排除特殊ROI(按钮/筛选/整体/ocr/tab)后排序
        if not (r1 and r2):
            def _special(r):
                rid = str(r.get("id", "")) + str(r.get("label", ""))
                return any(k in rid for k in ("按钮", "筛选", "整体", "ocr", "tab", "button", "filter"))
            cells = [r for r in data.get("rois", []) if not _special(r)]
            cells.sort(key=lambda r: (r["ry"], r["rx"]))
            if len(cells) >= 2:
                r1, r2 = cells[0], cells[1]

        if not (r1 and r2):
            return None

        cx1, cy1 = r1["rx"] + r1["rw"] / 2, r1["ry"] + r1["rh"] / 2
        cx2, cy2 = r2["rx"] + r2["rw"] / 2, r2["ry"] + r2["rh"] / 2
        dx, dy = cx2 - cx1, cy2 - cy1
        if dx <= 0 or dy <= 0:
            return None

        return {
            "cx": cx1, "cy": cy1,
            "cell_w": r1["rw"], "cell_h": r1["rh"],
            "dx": dx, "dy": dy,
            "region": (region["rx"], region["ry"], region["rx"] + region["rw"], region["ry"] + region["rh"]),
        }
    except Exception:
        return None


def _grid_cells(layout: dict):
    """按 dx/dy 生成区域内的全部格子 (col, row, cx, cy)"""
    rx1, ry1, rx2, ry2 = layout["region"]
    cw, ch = layout["cell_w"], layout["cell_h"]
    cols = int((rx2 - rx1 - cw) / layout["dx"]) + 1 if layout["dx"] > 0 else 1
    rows = int((ry2 - ry1 - ch) / layout["dy"]) + 1 if layout["dy"] > 0 else 1
    cols, rows = max(1, min(cols, 12)), max(1, min(rows, 14))
    for r in range(rows):
        for c in range(cols):
            cx = layout["cx"] + c * layout["dx"]
            cy = layout["cy"] + r * layout["dy"]
            if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
                yield c, r, cx, cy


class BagScanner:
    """背包盘点器(无线程, 由 bridge 按需调用)"""

    def __init__(self):
        self.layout = load_bag_layout()
        self.present_threshold = 0.35
        # 排除名单: 官方数据未收录的新球(如灰色新球 999999)或指定排除的球种
        self.excluded_ball_ids = {"999999", "100283", "exclude_new_gray"}
        # 背包盘点面向全量球池(不受战中 active_balls 限制), 优先使用游戏内渲染模板 (ingame)
        self.matcher = BallTemplateMatcher(active_balls=None, prefer="ingame")
        self.matcher.present_threshold = self.present_threshold

    def available(self) -> bool:
        return bool(self.layout and self.matcher.refs)

    def grid_size(self) -> dict:
        """当前 ROI 推导的网格行列数"""
        if not self.layout:
            return {"cols": 0, "rows": 0}
        rx1, ry1, rx2, ry2 = self.layout["region"]
        cw, ch = self.layout["cell_w"], self.layout["cell_h"]
        cols = int((rx2 - rx1 - cw) / self.layout["dx"]) + 1 if self.layout["dx"] > 0 else 1
        rows = int((ry2 - ry1 - ch) / self.layout["dy"]) + 1 if self.layout["dy"] > 0 else 1
        return {"cols": max(1, min(cols, 12)), "rows": max(1, min(rows, 14))}

    def _read_cell_count(self, num_crop: np.ndarray) -> Optional[int]:
        """读取卡片底部数量条带的数字 (带 padding、自适应重试与字符纠错)"""
        if num_crop is None or num_crop.size == 0:
            return None
        # 1. 基础识别 (8px padding)
        padded = cv2.copyMakeBorder(num_crop, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=[30, 30, 30])
        text, _ = read_combined(padded)

        # 2. 自适应重试: 若未识别到有效数字, 尝试 1.5x 放大
        if not text or not re.search(r"\d+", text):
            resized = cv2.resize(num_crop, (0, 0), fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
            p2 = cv2.copyMakeBorder(resized, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=[30, 30, 30])
            text2, _ = read_combined(p2)
            if text2 and re.search(r"\d+", text2):
                text = text2

        if not text:
            return None

        # 3. 规范化与字符纠错 (如 x1431, x3z->32, XZ->2)
        raw = text.replace(" ", "").replace("，", "").replace(",", "")
        num_part = raw.lower().split("x", 1)[1] if "x" in raw.lower() else raw
        num_part = num_part.replace("z", "2").replace("o", "0").replace("s", "5")
        m = re.search(r"\d+", num_part)
        return int(m.group(0)) if m else None

    def scan(self, frame) -> List[dict]:
        """网格扫描: 卡片有效性检查 → 球型模板匹配 → 底部数字条带 OCR"""
        if not self.available() or frame is None or frame.size == 0:
            return []
        h, w = frame.shape[:2]
        cw, ch = self.layout["cell_w"], self.layout["cell_h"]
        items = []

        for c, r, cx, cy in _grid_cells(self.layout):
            left, top = cx - cw / 2, cy - ch / 2
            x0, y0 = int(left * w), int(top * h)
            x1, y1 = int((left + cw) * w), int((top + ch) * h)
            cell = frame[y0:y1, x0:x1]
            if cell.size == 0:
                continue

            # 1. 卡片存在性检查: 过滤透光的透明游戏背景空位, 根治彩色背景误报
            bot = cell[int(cell.shape[0] * 0.75):int(cell.shape[0] * 0.95), :]
            dark_ratio = np.mean(np.all(bot < 60, axis=-1)) if bot.size else 0.0
            top_part = cell[:int(cell.shape[0] * 0.4), :]
            bright_ratio = np.mean(np.all(top_part > 180, axis=-1)) if top_part.size else 0.0

            if dark_ratio < 0.25 and bright_ratio < 0.20:
                # 该格子是背景空位(非球卡片)
                continue

            # 2. 球型模板匹配 (匹配卡片上半部 72% 纯球体区域)
            m = self.matcher.match_frame_rect(frame, (left, top, cw, ch * 0.72))
            if not m["present"] or m["score"] < self.present_threshold:
                continue

            # 排除未收录/指定的未知新球 (如官方未更新的灰色新球)
            if (m["ball_id"] in self.excluded_ball_ids
                    or "未知" in str(m["ball_name"])
                    or "exclude" in str(m["ball_id"]).lower()):
                continue

            # 3. 底部数字条带 OCR
            num_crop = cell[int(cell.shape[0] * COUNT_ROI_SPLIT):, :]
            count = self._read_cell_count(num_crop)

            items.append({
                "col": c,
                "row": r,
                "ball_id": m["ball_id"],
                "ball_name": m["ball_name"],
                "count": count,
                "score": m["score"],
            })

        return items

    @staticmethod
    def aggregate(items: List[dict]) -> Dict[str, dict]:
        """格子列表 → {ball_id: {name, count(合计), cells}}"""
        agg: Dict[str, dict] = {}
        for it in items:
            bid = it["ball_id"]
            e = agg.setdefault(bid, {"name": it["ball_name"], "count": 0, "cells": 0})
            e["cells"] += 1
            if it["count"] is not None:
                e["count"] += it["count"]
        return agg

    def scan_and_diff(self, frame) -> dict:
        """盘点 + 与上次快照做减法 → {totals, consumed, updated_at}"""
        items = self.scan(frame)
        totals = self.aggregate(items)
        prev = self._load_snapshot().get("totals", {})
        consumed = {}
        for bid, e in totals.items():
            before = prev.get(bid, {}).get("count")
            if before is not None and e["count"] < before:
                consumed[bid] = {"name": e["name"], "before": before, "after": e["count"],
                                 "used": before - e["count"]}
        for bid, pe in prev.items():
            if bid not in totals and pe.get("count"):
                consumed[bid] = {"name": pe["name"], "before": pe["count"], "after": 0,
                                 "used": pe["count"]}
        self._save_snapshot(totals)
        return {"items": items, "totals": totals, "consumed": consumed,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    @staticmethod
    def _load_snapshot() -> dict:
        try:
            if BAG_SNAPSHOT_PATH.exists():
                return json.loads(BAG_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_snapshot(self, totals: dict):
        try:
            BAG_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
            BAG_SNAPSHOT_PATH.write_text(json.dumps({
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "totals": totals,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
