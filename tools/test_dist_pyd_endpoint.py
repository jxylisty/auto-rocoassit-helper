# -*- coding: utf-8 -*-
"""终验: dist 里的 auth_core.pyd 指向新域名"""
import sys
sys.path.insert(0, r"D:\洛克王国ai\lkwgai_pvp_assistant\dist\洛克王国助手\_internal")
# 让 dist 的 pyd 优先于开发目录: 直接以 src.gui 包形态加载
import importlib.util
import types

# 先屏蔽开发目录, 只用 dist _internal
sys.path = [p for p in sys.path if "lkwgai_pvp_assistant" not in p]
sys.path.insert(0, r"D:\洛克王国ai\lkwgai_pvp_assistant\dist\洛克王国助手\_internal")

pkg = types.ModuleType("src"); pkg.__path__ = []
gui = types.ModuleType("src.gui"); gui.__path__ = [r"D:\洛克王国ai\lkwgai_pvp_assistant\dist\洛克王国助手\_internal\src\gui"]
pkg.gui = gui
sys.modules["src"] = pkg
sys.modules["src.gui"] = gui

spec = importlib.util.spec_from_file_location(
    "src.gui.auth_core",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\dist\洛克王国助手\_internal\src\gui\auth_core.pyd")
m = importlib.util.module_from_spec(spec)
sys.modules["src.gui.auth_core"] = m
spec.loader.exec_module(m)

print("dist pyd main:", m.builtin_api_base())
print("dist pyd fallbacks:", m.builtin_api_fallbacks())
print("DIST_PYD_OK")
