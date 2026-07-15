# -*- coding: utf-8 -*-
"""Tkinter-based template crop tool for screenshots."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import cv2
from PIL import Image, ImageTk

from src.utils.image_io import imread_unicode, imwrite_unicode


CATEGORY_MAP = {
    "digit": Path("data/vision/digits"),
    "element": Path("data/vision/elements"),
    "avatar": Path("data/vision/avatars"),
    "battle_left": Path("data/vision/battle/left"),
    "battle_right": Path("data/vision/battle/right"),
    "sample": Path("data/vision/exports"),
}


class CropTool:
    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path
        self.frame = imread_unicode(image_path)
        if self.frame is None:
            raise SystemExit(f"无法读取截图: {image_path}")

        self.image_rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        self.image = Image.fromarray(self.image_rgb)
        self.image_width, self.image_height = self.image.size

        self.root = tk.Tk()
        self.root.title(f"模板裁剪工具 - {image_path.name}")
        self.root.geometry("1200x760")

        self.category_var = tk.StringVar(value="sample")
        self.status_var = tk.StringVar(value="拖拽鼠标框选区域，然后点击“保存当前框选”。")
        self.scale = 1.0
        self.start_x = 0.0
        self.start_y = 0.0
        self.rect_id = None
        self.current_box: tuple[int, int, int, int] | None = None
        self.saved_count = 0

        self._build_ui()
        self._render_image()

    def _build_ui(self) -> None:
        toolbar = tk.Frame(self.root)
        toolbar.pack(fill="x", padx=8, pady=8)

        ttk.Label(toolbar, text="类别").pack(side="left")
        ttk.Combobox(
            toolbar,
            textvariable=self.category_var,
            values=tuple(CATEGORY_MAP.keys()),
            width=16,
            state="readonly",
        ).pack(side="left", padx=(6, 12))

        ttk.Button(toolbar, text="保存当前框选", command=self.save_selection).pack(side="left", padx=4)
        ttk.Button(toolbar, text="清除框选", command=self.clear_selection).pack(side="left", padx=4)
        ttk.Button(toolbar, text="放大", command=lambda: self._zoom(1.25)).pack(side="left", padx=4)
        ttk.Button(toolbar, text="缩小", command=lambda: self._zoom(0.8)).pack(side="left", padx=4)
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="left", padx=12)

        container = tk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.canvas = tk.Canvas(container, bg="black", cursor="cross")
        self.canvas.pack(side="left", fill="both", expand=True)

        y_scroll = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        y_scroll.pack(side="right", fill="y")
        x_scroll = ttk.Scrollbar(self.root, orient="horizontal", command=self.canvas.xview)
        x_scroll.pack(fill="x", padx=8, pady=(0, 8))

        self.canvas.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

    def _render_image(self) -> None:
        width = max(1, int(self.image_width * self.scale))
        height = max(1, int(self.image_height * self.scale))
        resized = self.image.resize((width, height))
        self.tk_image = ImageTk.PhotoImage(resized)

        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.tk_image, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self.rect_id = None
        self.current_box = None

    def _zoom(self, factor: float) -> None:
        self.scale = max(0.2, min(4.0, self.scale * factor))
        self._render_image()
        self.status_var.set(f"当前缩放: {self.scale:.2f}x")

    def on_press(self, event) -> None:
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            self.start_x,
            self.start_y,
            outline="#00ff66",
            width=2,
        )

    def on_drag(self, event) -> None:
        if self.rect_id is None:
            return
        current_x = self.canvas.canvasx(event.x)
        current_y = self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, current_x, current_y)

    def on_release(self, event) -> None:
        if self.rect_id is None:
            return
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)
        x1 = int(min(self.start_x, end_x) / self.scale)
        y1 = int(min(self.start_y, end_y) / self.scale)
        x2 = int(max(self.start_x, end_x) / self.scale)
        y2 = int(max(self.start_y, end_y) / self.scale)
        if x2 - x1 < 2 or y2 - y1 < 2:
            self.current_box = None
            self.status_var.set("框选过小，请重新选择。")
            return
        self.current_box = (x1, y1, x2, y2)
        self.status_var.set(f"当前框选: ({x1}, {y1}) -> ({x2}, {y2})")

    def clear_selection(self) -> None:
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
        self.current_box = None
        self.status_var.set("已清除框选。")

    def save_selection(self) -> None:
        if self.current_box is None:
            messagebox.showwarning("未框选", "请先拖拽框选一个区域。")
            return

        category = self.category_var.get()
        default_name = f"{self.image_path.stem}_{category}_{self.saved_count + 1}"
        save_name = simpledialog.askstring(
            "保存模板",
            "输入文件名（不带扩展名）:",
            initialvalue=default_name,
            parent=self.root,
        )
        if not save_name:
            return

        x1, y1, x2, y2 = self.current_box
        crop = self.frame[y1:y2, x1:x2].copy()
        target = CATEGORY_MAP[category] / f"{save_name}.png"

        if not imwrite_unicode(target, crop):
            messagebox.showerror("保存失败", f"无法保存到: {target}")
            return

        self.saved_count += 1
        self.status_var.set(f"已保存: {target}")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("用法: python crop_template_tool.py <image_path>")

    CropTool(Path(sys.argv[1])).run()


if __name__ == "__main__":
    main()
