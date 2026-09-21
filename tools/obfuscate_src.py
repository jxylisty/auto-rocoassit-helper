# -*- coding: utf-8 -*-
"""
PyArmor 混淆 src/ 全部源码(试用版: 大文件 32KB 上限, 超限文件自动回退)

用法:
    python tools/obfuscate_src.py            # 混淆到 build/_obf_out/
    python tools/obfuscate_src.py --clean    # 先清空输出目录

产物:
    build/_obf_out/               # 与 src/ 同构的混淆树 + pyarmor_runtime_000000/
    build/_obf_out/_fallback.txt  # 回退用原文件的清单(供打包脚本核对)

说明:
    - 试用版限制: 不能用 --mix-str, 单文件 >32KB 混淆失败(自动回退原文件)
    - 试用版授权有冷却: 报 out of license 时等几分钟重跑即可
    - 混淆文件不可读不可反编译; 正式版可加 --mix-str/--restrict 提升强度
    - build_main_app.py 在 LKW_OBFUSCATE=1 时自动接入本脚本产物
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "build" / "_obf_out"
RUNTIME_PKG = "pyarmor_runtime_000000"


def main() -> None:
    if "--clean" in sys.argv and OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)

    src_root = PROJECT_ROOT / "src"
    entry = PROJECT_ROOT / "tools" / "app_entry.py"
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)

    print(">>> PyArmor 混淆 src/ + app_entry.py ...")
    # 试用版单文件 32KB 上限, 超限文件会中止整轮 → 先剔除, 之后回退原文件
    LIM = 30_000
    skipped = [p for p in src_root.rglob("*.py") if p.stat().st_size > LIM]
    for p in skipped:
        print(f"  跳过(超试用版大小): {p.relative_to(PROJECT_ROOT)}")
    # 临时镜像: build/_obf_src_mirror/src/<rel> — 目录名含 src 层,
    # pyarmor 按此结构输出, 保证混淆树里有 src/ 包前缀(入口 import src.xxx 需要)
    mirror = PROJECT_ROOT / "build" / "_obf_src_mirror"
    if mirror.exists():
        shutil.rmtree(mirror)
    for py in src_root.rglob("*.py"):
        if py in skipped:
            continue
        dst = mirror / "src" / py.relative_to(src_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(py, dst)
    # src/pvp/data/*.json 运行时按 __file__ 相对定位, 一并镜像
    data_dst = mirror / "src" / "pvp" / "data"
    data_dst.mkdir(parents=True, exist_ok=True)
    for j in (src_root / "pvp" / "data").glob("*.json"):
        shutil.copy2(j, data_dst / j.name)

    cmd = [
        "pyarmor", "gen", "--recursive",
        "--output", str(OUT_DIR),
        str(mirror), str(entry),
    ]
    r = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    # 试用版对超限文件报 ERROR 但其余文件照常输出, 不视为整体失败
    (OUT_DIR / "_pyarmor_log.txt").write_text(r.stdout + "\n" + r.stderr,
                                              encoding="utf-8")
    print((r.stdout + r.stderr)[-600:])
    if "out of license" in (r.stderr or "") and "obfuscated" not in r.stdout:
        raise SystemExit("PyArmor 授权不可用(可能有冷却), 稍等几分钟重跑")

    # ---- 布局归位: pyarmor 以 mirror 名为包根输出(_obf_src_mirror/xxx),
    # 提升其内容到输出根, 再落回退文件 ----
    mirror_out = OUT_DIR / "_obf_src_mirror"
    if mirror_out.exists():
        for child in mirror_out.iterdir():
            dst = OUT_DIR / child.name
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            shutil.move(str(child), str(dst))
        shutil.rmtree(mirror_out)

    # pyarmor 只输出 .py; 镜像里的资源(json)手动带上(运行时按 __file__ 相对定位)
    for res in mirror.rglob("*"):
        if res.is_file() and res.suffix.lower() in {".json", ".txt"}:
            rel = res.relative_to(mirror)
            dst = OUT_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(res, dst)

    # ---- 回退: 混淆输出里缺失的文件用原文件补齐(PROJECT_ROOT 相对路径) ----
    fallback = []
    for py in list(src_root.rglob("*.py")) + [entry]:
        rel = py.relative_to(PROJECT_ROOT)
        if not (OUT_DIR / rel).exists():
            (OUT_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(py, OUT_DIR / rel)
            fallback.append(rel.as_posix())

    # __init__.py 恢复原样(混淆它对包导入链无收益, 徒增风险)
    for init in OUT_DIR.rglob("__init__.py"):
        rel = init.relative_to(OUT_DIR)
        orig = PROJECT_ROOT / rel
        if orig.exists():
            shutil.copy2(orig, init)

    (OUT_DIR / "_fallback.txt").write_text("\n".join(fallback), encoding="utf-8")
    obf_cnt = sum(1 for p in OUT_DIR.rglob("*.py")
                  if p.read_text(encoding="utf-8", errors="ignore").lstrip().startswith("# Pyarmor"))
    print(f"混淆完成: {OUT_DIR}")
    print(f"  混淆 {obf_cnt} 个 | 回退原文件 {len(fallback)} 个:")
    for f in fallback:
        print(f"  - {f}")
    if not (OUT_DIR / RUNTIME_PKG).exists():
        raise SystemExit("运行时包缺失, 混淆产物不可用")


if __name__ == "__main__":
    main()
