# -*- coding: utf-8 -*-
"""检查本轮加固涉及的全部 Python 文件语法完整性 (只输出文件名 + OK/BAD)"""
import py_compile

FILES = [
    r"D:\洛克王国ai\lkwgai_pvp_assistant\src\gui\auth_core.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\src\gui\auth.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\seadata.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\pet_loader.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\skill_loader.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\type_chart.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\pvp_rules.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\src\gui\bridge.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\tools\app_entry.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\tools\seal_assets.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\tools\build_hardened.py",
    r"D:\洛克王国ai\lkwgai_pvp_assistant\tools\test_hardening_smoke.py",
]

bad = 0
for f in FILES:
    name = f.rsplit("\\", 1)[-1]
    try:
        py_compile.compile(f, doraise=True)
        print("OK  ", name)
    except Exception as e:
        bad += 1
        msg = str(e).encode("ascii", "replace").decode()
        print("BAD ", name, "->", msg[:120])
print("SUMMARY:", "ALL_OK" if bad == 0 else f"{bad}_BROKEN")
