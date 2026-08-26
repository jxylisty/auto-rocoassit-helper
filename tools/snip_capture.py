# -*- coding: utf-8 -*-
"""手动框选截图工具

全屏冻结画面 → 拖拽框选区域 → 保存 PNG → 默认自动打开模板裁剪工具。
截图来源是屏幕可见内容,不依赖窗口句柄/前台状态,游戏在屏幕上看得见就能截。

用法:
    python tools/snip_capture.py             # 框选 → 保存 → 打开裁剪工具
    python tools/snip_capture.py --save-only # 只截图保存,不打开裁剪工具
快捷键: 大前端运行时按 F8
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tkinter as tk
from PIL import Image, ImageGrab, ImageTk

from src.capture.window_capture import enable_dpi_awareness

SAVE_DIR = PROJECT_ROOT / "data" / "screenshots"
CROP_TOOL = PROJECT_ROOT / "tools" / "crop_template_tool.py"


def _virtual_screen_rect():
    """整个虚拟桌面(含多显示器)的绝对坐标矩形"""
    import win32api
    import win32con
    x = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    y = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    return x, y, w, h


class SnipTool:
    def __init__(self, open_crop: bool = True) -> None:
        self.open_crop = open_crop
        enable_dpi_awareness()

        # 先冻结全屏(覆盖层显示前抓取)
        vx, vy, vw, vh = _virtual_screen_rect()
        self.origin = (vx, vy)
        self.shot = ImageGrab.grab(all_screens=True, bbox=(vx, vy, vx + vw, vy + vh))
        # 变暗背景,突出框选区域
        dark = Image.new("RGB", self.shot.size, (0, 0, 0))
        self.dimmed = Image.blend(self.shot, dark, 0.45)

        self.root = tk.Tk()
        self.root.withdraw()
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self.win.attributes("-topmost", True)
        self.win.configure(cursor="crosshair")

        self.tk_img = ImageTk.PhotoImage(self.dimmed)
        self.canvas = tk.Canvas(self.win, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")

        self.rect_id = None
        self.label_id = None
        self.start_x = self.start_y = 0
        self.box = None  # (x1, y1, x2, y2) 图像坐标

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.win.bind("<Escape>", lambda e: self._close())

        tip = "拖拽框选截图区域(图像坐标原点为屏幕左上角),ESC 取消"
        self.canvas.create_text(16, 12, text=tip, fill="#7dd3fc", anchor="nw",
                                font=("Microsoft YaHei", 12, "bold"))

    # ---------- 交互 ----------

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id, self.label_id)
        self.rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#22d3ee", width=2)

    def on_drag(self, event):
        if not self.rect_id:
            return
        x1, y1 = min(self.start_x, event.x), min(self.start_y, event.y)
        x2, y2 = max(self.start_x, event.x), max(self.start_y, event.y)
        self.canvas.coords(self.rect_id, x1, y1, x2, y2)
        if self.label_id:
            self.canvas.delete(self.label_id)
        self.label_id = self.canvas.create_text(
            x1 + 4, y1 - 14, anchor="nw", fill="#22d3ee",
            font=("Consolas", 11, "bold"),
            text=f"{x2 - x1} x {y2 - y1}  ({x1},{y1})")

    def on_release(self, event):
        if not self.rect_id:
            return
        x1, y1 = min(self.start_x, event.x), min(self.start_y, event.y)
        x2, y2 = max(self.start_x, event.x), max(self.start_y, event.y)
        self._close()
        if x2 - x1 < 4 or y2 - y1 < 4:
            print("框选过小,已取消")
            return
        self._save(x1, y1, x2, y2)

    # ---------- 保存 ----------

    def _save(self, x1, y1, x2, y2):
        crop = self.shot.crop((x1, y1, x2, y2))
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        path = SAVE_DIR / time.strftime("snip_%Y%m%d_%H%M%S.png")
        try:
            crop.save(path)  # PIL 原生支持中文路径
        except Exception as e:
            print(f"保存失败: {path} ({e})")
            return
        # 图像坐标换算回屏幕绝对坐标(供参考/调试)
        print(f"已保存: {path}")
        print(f"屏幕区域: ({self.origin[0] + x1}, {self.origin[1] + y1}) -> "
              f"({self.origin[0] + x2}, {self.origin[1] + y2})")

        if self.open_crop:
            subprocess.Popen(
                [sys.executable, str(CROP_TOOL), str(path)],
                cwd=str(PROJECT_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE)

    def _close(self):
        self.win.destroy()
        self.root.quit()

    def run(self):
        self.root.mainloop()


def main() -> None:
    open_crop = "--save-only" not in sys.argv
    SnipTool(open_crop=open_crop).run()


if __name__ == "__main__":
    main()
