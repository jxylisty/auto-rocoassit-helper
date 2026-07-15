# -*- coding: utf-8 -*-
"""Small Windows auto-click macro with global hotkeys.

Hotkeys:
  F6  - capture current mouse position
  F7  - start / stop clicking
  F10 - emergency stop and exit

PyAutoGUI's failsafe is enabled: move the mouse to the top-left corner to abort.
"""

from __future__ import annotations

import ctypes
import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pyautogui
import win32con


CONFIG_PATH = Path(__file__).with_name("auto_click_macro_config.json")
HOTKEY_CAPTURE_POS = 1
HOTKEY_TOGGLE = 2
HOTKEY_EXIT = 3
WM_HOTKEY = 0x0312


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_size_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


class AutoClickMacro:
    def __init__(self) -> None:
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0

        self.root = tk.Tk()
        self.root.title("Auto Click Macro")
        self.root.geometry("360x270+120+120")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        self.running = False
        self.after_job: str | None = None

        x, y = pyautogui.position()
        self.x_var = tk.StringVar(value=str(x))
        self.y_var = tk.StringVar(value=str(y))
        self.interval_var = tk.StringVar(value="500")
        self.burst_var = tk.StringVar(value="1")
        self.button_var = tk.StringVar(value="left")
        self.status_var = tk.StringVar(value="Ready. F6 set pos, F7 start/stop, F10 exit.")

        self._load_config()
        self._build_ui()
        self._register_hotkeys()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(80, self._poll_hotkeys)

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)

        pad = {"padx": 12, "pady": 5}
        ttk.Label(self.root, text="Target X").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(self.root, textvariable=self.x_var, width=16).grid(row=0, column=1, sticky="ew", **pad)

        ttk.Label(self.root, text="Target Y").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(self.root, textvariable=self.y_var, width=16).grid(row=1, column=1, sticky="ew", **pad)

        ttk.Label(self.root, text="Interval ms").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(self.root, textvariable=self.interval_var, width=16).grid(row=2, column=1, sticky="ew", **pad)

        ttk.Label(self.root, text="Clicks each tick").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(self.root, textvariable=self.burst_var, width=16).grid(row=3, column=1, sticky="ew", **pad)

        ttk.Label(self.root, text="Button").grid(row=4, column=0, sticky="w", **pad)
        ttk.Combobox(
            self.root,
            textvariable=self.button_var,
            values=("left", "right", "middle"),
            state="readonly",
            width=14,
        ).grid(row=4, column=1, sticky="ew", **pad)

        controls = ttk.Frame(self.root)
        controls.grid(row=5, column=0, columnspan=2, sticky="ew", padx=12, pady=(8, 4))
        controls.grid_columnconfigure((0, 1, 2), weight=1)
        ttk.Button(controls, text="Set Pos (F6)", command=self.capture_position).grid(row=0, column=0, sticky="ew", padx=3)
        ttk.Button(controls, text="Start/Stop (F7)", command=self.toggle).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(controls, text="Exit (F10)", command=self.close).grid(row=0, column=2, sticky="ew", padx=3)

        ttk.Label(
            self.root,
            text="Emergency: move mouse to top-left corner, or press F10.",
            foreground="#666666",
            wraplength=330,
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 2))

        ttk.Label(self.root, textvariable=self.status_var, wraplength=330).grid(
            row=7, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 10)
        )

    def _load_config(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return

        for var_name, key in (
            ("x_var", "x"),
            ("y_var", "y"),
            ("interval_var", "interval_ms"),
            ("burst_var", "burst"),
            ("button_var", "button"),
        ):
            value = data.get(key)
            if value is not None:
                getattr(self, var_name).set(str(value))

    def _save_config(self) -> None:
        data = {
            "x": self.x_var.get(),
            "y": self.y_var.get(),
            "interval_ms": self.interval_var.get(),
            "burst": self.burst_var.get(),
            "button": self.button_var.get(),
        }
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _register_hotkeys(self) -> None:
        user32 = ctypes.windll.user32
        ok_capture = user32.RegisterHotKey(None, HOTKEY_CAPTURE_POS, 0, win32con.VK_F6)
        ok_toggle = user32.RegisterHotKey(None, HOTKEY_TOGGLE, 0, win32con.VK_F7)
        ok_exit = user32.RegisterHotKey(None, HOTKEY_EXIT, 0, win32con.VK_F10)
        if not (ok_capture and ok_toggle and ok_exit):
            self.status_var.set("Some hotkeys failed to register. Try closing apps using F6/F7/F10.")

    def _unregister_hotkeys(self) -> None:
        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(None, HOTKEY_CAPTURE_POS)
        user32.UnregisterHotKey(None, HOTKEY_TOGGLE)
        user32.UnregisterHotKey(None, HOTKEY_EXIT)

    def _poll_hotkeys(self) -> None:
        msg = MSG()
        user32 = ctypes.windll.user32
        while user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, 1):
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_CAPTURE_POS:
                    self.capture_position()
                elif msg.wParam == HOTKEY_TOGGLE:
                    self.toggle()
                elif msg.wParam == HOTKEY_EXIT:
                    self.close()
                    return
        self.root.after(80, self._poll_hotkeys)

    def capture_position(self) -> None:
        x, y = pyautogui.position()
        self.x_var.set(str(x))
        self.y_var.set(str(y))
        self._save_config()
        self.status_var.set(f"Position set to ({x}, {y}).")

    def toggle(self) -> None:
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        try:
            self._read_settings()
        except ValueError as exc:
            self.status_var.set(str(exc))
            return

        self.running = True
        self._save_config()
        self.status_var.set("Running. Press F7 to stop.")
        self._click_once()

    def stop(self) -> None:
        self.running = False
        if self.after_job is not None:
            self.root.after_cancel(self.after_job)
            self.after_job = None
        self.status_var.set("Stopped.")

    def _read_settings(self) -> tuple[int, int, int, int, str]:
        try:
            x = int(self.x_var.get())
            y = int(self.y_var.get())
            interval_ms = int(self.interval_var.get())
            burst = int(self.burst_var.get())
        except ValueError as exc:
            raise ValueError("X, Y, interval, and clicks must be whole numbers.") from exc

        if interval_ms < 20:
            raise ValueError("Interval must be at least 20 ms.")
        if burst < 1:
            raise ValueError("Clicks each tick must be at least 1.")
        if self.button_var.get() not in {"left", "right", "middle"}:
            raise ValueError("Button must be left, right, or middle.")
        return x, y, interval_ms, burst, self.button_var.get()

    def _click_once(self) -> None:
        if not self.running:
            return

        try:
            x, y, interval_ms, burst, button = self._read_settings()
            pyautogui.click(x=x, y=y, clicks=burst, interval=0.03, button=button)
            self.after_job = self.root.after(interval_ms, self._click_once)
        except pyautogui.FailSafeException:
            self.stop()
            self.status_var.set("Failsafe triggered. Mouse reached top-left corner.")
        except Exception as exc:
            self.stop()
            self.status_var.set(f"Stopped: {exc}")

    def close(self) -> None:
        self.stop()
        self._save_config()
        self._unregister_hotkeys()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    AutoClickMacro().run()
