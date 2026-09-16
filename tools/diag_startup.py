"""
启动诊断: 逐步打印每个初始化阶段, 定位 main.py 在不同终端下卡死/崩溃的确切位置

用法(在出问题的那个终端里跑):
    python tools/diag_startup.py
"""
import sys
import time
import faulthandler

faulthandler.enable()

def step(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

step("0. python = " + sys.executable)
step("1. 开始 import webview")
import webview
step(f"   webview {getattr(webview, '__version__', '?')} ok")

step("2. 开始 import cv2")
import cv2
step(f"   cv2 {cv2.__version__} ok")

step("3. 开始 import numpy/mss/interception")
import numpy as np
import mss
import interception
step("   numpy/mss/interception ok")

step("4. interception.auto_capture_devices()")
interception.auto_capture_devices()
step("   设备捕获 ok")

step("5. 开始 import AppBridge(含 BallSlotWatcher/BattleEngine)")
sys.path.insert(0, ".")
from src.gui.bridge import AppBridge, Api
step("   import ok")

step("6. AppBridge() 初始化中…")
bridge = AppBridge()
step("   AppBridge ok")

step("7. webview.create_window")
window = webview.create_window("诊断窗口", "data:text/html,<h1>diag ok</h1>",
                               js_api=Api(bridge), width=400, height=300)
step("   create_window ok")

step("8. webview.start() — 若窗口弹出且本行之后无输出, 说明 start 后窗口被立即关闭")
webview.start()
step(f"9. webview.start() 已返回 (正常退出流程)")
