# -*- coding: utf-8 -*-
"""
打包 PVP 数据采集器为独立可执行程序(给没有 Python 环境的电脑用)

用法:
    python tools/build_collector.py            # 构建到 dist/PVP数据采集器/
    python tools/build_collector.py --clean    # 先清空构建缓存

产物:
    dist/PVP数据采集器/PVP数据采集器.exe        # 双击即用
    dist/PVP数据采集器/output/                  # 素材输出目录(运行时生成)

依赖说明:
    - 只打包 Tesseract(数字/名字 OCR),不打包 PaddleOCR(体积差 1GB+)
    - Tesseract 运行时从 C:\\Program Files\\Tesseract-OCR 复制(本机已装)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESSERACT_SRC = Path(r"C:\Program Files\Tesseract-OCR")
DIST_DIR = PROJECT_ROOT / "dist" / "PVP数据采集器"


def main() -> None:
    if "--clean" in sys.argv:
        for d in ("build", PROJECT_ROOT / "dist"):
            p = PROJECT_ROOT / d
            if p.exists():
                shutil.rmtree(p)
                print(f"已清空 {p}")

    # ---- 1. 预备随包资源到临时 staging 目录 ----
    staging = PROJECT_ROOT / "build" / "_collector_staging"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "resources").mkdir(parents=True)
    (staging / "data" / "config").mkdir(parents=True)
    (staging / "tessdata").mkdir(parents=True)
    (staging / "tesseract").mkdir(parents=True)

    # ROI 模板 + 精灵名单
    shutil.copy2(PROJECT_ROOT / "data/config/roi_templates/PVP标准模板.json",
                 staging / "resources" / "PVP标准模板.json")
    shutil.copy2(PROJECT_ROOT / "data/config/pet_names.txt",
                 staging / "data" / "config" / "pet_names.txt")

    # PVP 引擎数据 JSON(src/pvp/__init__ 导入链需要,只要 json 不带图片资产)
    pvp_data_dst = staging / "src" / "pvp" / "data"
    pvp_data_dst.mkdir(parents=True)
    for j in (PROJECT_ROOT / "src/pvp/data").glob("*.json"):
        shutil.copy2(j, pvp_data_dst / j.name)

    # 语言包(中文 44MB + 英文)
    for f in ("chi_sim.traineddata", "eng.traineddata"):
        src = PROJECT_ROOT / "data/models/tessdata" / f
        if src.exists():
            shutil.copy2(src, staging / "tessdata" / f)

    # Tesseract 运行时: 只要 tesseract.exe + dll(训练工具 exe 一个 40MB+,全砍)
    if not TESSERACT_SRC.exists():
        raise SystemExit(f"本机未安装 Tesseract: {TESSERACT_SRC}")
    for f in TESSERACT_SRC.iterdir():
        if f.name == "tesseract.exe" or f.suffix.lower() == ".dll":
            shutil.copy2(f, staging / "tesseract" / f.name)

    print("资源 staging 完成:", staging)

    # ---- 2. PyInstaller 构建 ----
    exe_src = PROJECT_ROOT / "tools" / "pvp_data_collector.py"
    icon_file = PROJECT_ROOT / "data" / "assets" / "icons" / "app_icon.ico"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", name,
        *(["--icon", str(icon_file)] if icon_file.exists() else []),
        "--noconfirm",
        "--console",
        "--onedir",
        "--distpath", str(PROJECT_ROOT / "dist"),
        "--workpath", str(PROJECT_ROOT / "build"),
        "--specpath", str(PROJECT_ROOT / "build"),
        "--add-data", f"{staging / 'resources'};resources",
        "--add-data", f"{staging / 'data'};data",
        "--add-data", f"{staging / 'src'};src",
        "--add-data", f"{staging / 'tessdata'};tessdata",
        "--add-data", f"{staging / 'tesseract'};tesseract",
        "--hidden-import", "keyboard",
        "--hidden-import", "pytesseract",
        # 采集器不用任何 GUI 库;Anaconda 里 PyQt5/PySide6 并存,PyInstaller 拒绝双 Qt
        "--exclude-module", "PyQt5",
        "--exclude-module", "PySide6",
        "--exclude-module", "PySide2",
        "--exclude-module", "PyQt6",
        "--exclude-module", "tkinter",
        # Anaconda 里的重型库被静态分析连带拖入,采集器一概不用
        "--exclude-module", "tensorflow",
        "--exclude-module", "torch",
        "--exclude-module", "torchvision",
        "--exclude-module", "torchaudio",
        "--exclude-module", "paddle",
        "--exclude-module", "paddleocr",
        "--exclude-module", "ultralytics",
        "--exclude-module", "playwright",
        "--exclude-module", "llvmlite",
        "--exclude-module", "numba",
        "--exclude-module", "botocore",
        "--exclude-module", "boto3",
        "--exclude-module", "panel",
        "--exclude-module", "bokeh",
        "--exclude-module", "pygame",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pandas",
        "--exclude-module", "sklearn",
        "--exclude-module", "scipy",
        "--collect-submodules", "src.pvp.data_collector",
        "--paths", str(PROJECT_ROOT),
        str(exe_src),
    ]
    print("执行:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))

    # ---- 3. 验证产物 ----
    exe = DIST_DIR / f"{name}.exe"
    if not exe.exists():
        raise SystemExit("构建失败: 未找到 exe")
    checks = {
        "tessdata/chi_sim.traineddata": DIST_DIR / "_internal" / "tessdata" / "chi_sim.traineddata",
        "tesseract/tesseract.exe": DIST_DIR / "_internal" / "tesseract" / "tesseract.exe",
        "resources/PVP标准模板.json": DIST_DIR / "_internal" / "resources" / "PVP标准模板.json",
        "data/config/pet_names.txt": DIST_DIR / "_internal" / "data" / "config" / "pet_names.txt",
    }
    print("\n=== 产物检查 ===")
    ok = True
    for label, p in checks.items():
        exists = p.exists()
        ok = ok and exists
        print(f"  {'✅' if exists else '❌'} {label}")
    print(f"\n{'✅ 构建成功' if ok else '❌ 构建不完整'}")

    # ---- 4. 去重: PyInstaller 把 libtesseract-5.dll 又复制到 _internal 根(97MB) ----
    dup = DIST_DIR / "_internal" / "libtesseract-5.dll"
    if dup.exists():
        dup.unlink()
        print("已移除重复的 libtesseract-5.dll (tesseract/ 内有正身)")

    # ---- 5. 使用说明 + 打 zip 分发包 ----
    readme_src = PROJECT_ROOT / "tools" / "collector_使用说明.txt"
    if readme_src.exists():
        shutil.copy2(readme_src, DIST_DIR / "使用说明.txt")
    import time as _t
    zip_path = DIST_DIR.parent / f"{DIST_DIR.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Compress-Archive -Path '{DIST_DIR}\\*' -DestinationPath '{zip_path}' -CompressionLevel Optimal"],
        capture_output=True, text=True)
    if zip_path.exists():
        mb = zip_path.stat().st_size / 1e6
        print(f"✅ 分发包: {zip_path}  ({mb:.0f} MB)")
    else:
        print("zip 打包失败:", result.stderr[-300:])
    print(f"可执行: {exe}")
    size_mb = sum(f.stat().st_size for f in DIST_DIR.rglob('*') if f.is_file()) / 1e6
    print(f"目录大小: {size_mb:.0f} MB  (整个 PVP数据采集器 文件夹打包发给朋友)")


if __name__ == "__main__":
    main()
