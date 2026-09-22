# -*- coding: utf-8 -*-
"""
打包完整本体(挂机+丢球+PVP+数据采集)为独立可执行程序

⚠️ 2026-09 起对外分发请改用加固版构建链: tools/build_hardened.py
   (一键完成数据加密 + Cython 编译 + 打包 + 产物检查)。本脚本产物不含
   加密数据与全新 auth_core, 仅用于本地快速验证, 请勿直接分发。

用法:
    python tools/build_main_app.py            # 构建到 dist/洛克王国助手/
产物:
    dist/洛克王国助手/洛克王国助手.exe          # 双击启动(自动提权)
    dist/洛克王国助手/使用说明.txt
    dist/洛克王国助手/洛克王国助手.zip          # 直接发给朋友的压缩包

说明:
    - 首次运行会自动把 data/ 复制到 exe 旁边作为可写用户数据
    - Interception 驱动首次运行自动安装(需重启一次生效)
    - LKW_OBFUSCATE=1 时先用 PyArmor 混淆源码再打包(防破解, 见 tools/obfuscate_src.py)
    - PaddleOCR 不打包(体积 +1GB),PVP 实时识别中文降级,其余功能完整
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESSERACT_SRC = Path(r"C:\Program Files\Tesseract-OCR")
INTERCEPTION_INSTALLER = PROJECT_ROOT / "build" / "_interception" / "lib" / "Interception" / "command line installer" / "install-interception.exe"
# 目录名可由命令行指定(旧目录被占用时换新名重打)
NAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "洛克王国助手"
DIST_DIR = PROJECT_ROOT / "dist" / NAME


def main() -> None:
    if not INTERCEPTION_INSTALLER.exists():
        raise SystemExit("缺少 Interception 安装器,请先运行采集器构建或手动下载 Interception.zip 解压到 build/_interception/lib")

    # ---- 1. 只读资源 staging ----
    staging = PROJECT_ROOT / "build" / "_mainapp_staging"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "data" / "config" / "roi_templates").mkdir(parents=True)
    (staging / "tessdata").mkdir(parents=True)
    (staging / "tesseract").mkdir(parents=True)
    (staging / "interception").mkdir(parents=True)

    # data/: 用户可写数据主副本(首次运行复制到 exe 旁)
    def _copy_tree(src: Path, dst: Path, skip_dirs: tuple = ()):
        if not src.exists():
            return
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.db", "output")
                        if skip_dirs else None)

    _copy_tree(PROJECT_ROOT / "data" / "config", staging / "data" / "config")
    _copy_tree(PROJECT_ROOT / "data" / "vision", staging / "data" / "vision")
    # 语言包/Tesseract 已退役:OCR 全线换 RapidOCR(随 venv 打包,无需外部文件)
    # PVP 引擎数据 JSON
    pvp_data_dst = staging / "src" / "pvp" / "data"
    pvp_data_dst.mkdir(parents=True)
    for j in (PROJECT_ROOT / "src/pvp/data").glob("*.json"):
        shutil.copy2(j, pvp_data_dst / j.name)
    # Interception 驱动安装器
    shutil.copy2(INTERCEPTION_INSTALLER, staging / "interception" / "install-interception.exe")
    print("资源 staging 完成")

    # ---- 2. 可选: PyArmor 混淆(LKW_OBFUSCATE=1) ----
    obfuscate = os.environ.get("LKW_OBFUSCATE") == "1"
    src_for_pack = PROJECT_ROOT          # 默认: 原始源码树
    if obfuscate:
        subprocess.run([sys.executable, str(PROJECT_ROOT / "tools/obfuscate_src.py")],
                       check=True, cwd=str(PROJECT_ROOT))
        src_for_pack = PROJECT_ROOT / "build" / "_obf_out"

    # ---- 3. PyInstaller ----
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--noconfirm",
        "--noconsole",  # 隐藏黑窗口;启动异常由 app_entry 写 boot_error.log + 弹窗
        "--onedir",
        "--distpath", str(PROJECT_ROOT / "dist"),
        "--workpath", str(PROJECT_ROOT / "build"),
        "--specpath", str(PROJECT_ROOT / "build"),
        "--add-data", f"{staging / 'data'};data",
        "--add-data", f"{staging / 'src' / 'pvp' / 'data'};src/pvp/data",
        "--add-data", f"{staging / 'interception'};interception",
        "--add-data", f"{PROJECT_ROOT / 'src/gui/web'};web",
        "--add-data", f"{PROJECT_ROOT / 'src/gui/studio'};studio",
        *(["--add-data", f"{src_for_pack / 'pyarmor_runtime_000000'};pyarmor_runtime_000000",
           "--add-data", f"{src_for_pack / 'src'};src"]
          if obfuscate else []),
        "--hidden-import", "keyboard",
        "--hidden-import", "webview",
        *([f"--hidden-import={h}" for h in (
            # pywin32 等子模块: 混淆代码里的 import 对静态分析不可见
            "win32ui", "win32gui", "win32con", "win32api", "pywintypes",
            "pythoncom", "yaml",
        )] if obfuscate else []),
        # bridge 从项目根导入 auto_throw_ball(超试用上限只能原文件);
        # 放 _internal 根, 与 bridge 的 sys.path 定位(PROJECT_ROOT=上两级)一致
        *(["--add-data", f"{PROJECT_ROOT / 'auto_throw_ball.py'};."] if obfuscate else []),
        "--collect-all", "webview",
        "--collect-all", "rapidocr_onnxruntime",  # 含 .onnx 模型文件,缺了 OCR 会挂
        "--collect-all", "onnxruntime",
        "--exclude-module", "PyQt5", "--exclude-module", "PySide6",
        "--exclude-module", "PySide2", "--exclude-module", "PyQt6",
        "--exclude-module", "tkinter",
        "--exclude-module", "tensorflow", "--exclude-module", "torch",
        "--exclude-module", "torchvision", "--exclude-module", "torchaudio",
        "--exclude-module", "paddle", "--exclude-module", "paddleocr",
        "--exclude-module", "ultralytics",
        "--exclude-module", "playwright", "--exclude-module", "llvmlite",
        "--exclude-module", "numba", "--exclude-module", "botocore",
        "--exclude-module", "boto3", "--exclude-module", "panel",
        "--exclude-module", "bokeh", "--exclude-module", "pygame",
        "--exclude-module", "matplotlib", "--exclude-module", "pandas",
        "--exclude-module", "sklearn", "--exclude-module", "scipy",
        "--paths", str(src_for_pack),
        str(src_for_pack / "app_entry.py" if obfuscate
            else PROJECT_ROOT / "tools/app_entry.py"),
    ]
    print("执行 PyInstaller...")
    subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))

    # ---- 3. 修正启动入口名 + 去重 dll + 使用说明 ----
    exe_src = DIST_DIR / f"app_entry.exe"
    exe_dst = DIST_DIR / f"{NAME}.exe"
    if exe_src.exists():
        exe_src.rename(exe_dst)
    dup = DIST_DIR / "_internal" / "libtesseract-5.dll"
    if dup.exists():
        dup.unlink()
    readme = PROJECT_ROOT / "tools" / "本体_使用说明.txt"
    if readme.exists():
        shutil.copy2(readme, DIST_DIR / "使用说明.txt")

    # ---- 4. 产物检查 + zip ----
    checks = {
        "主程序": exe_dst,
        "驱动安装器": DIST_DIR / "_internal" / "interception" / "install-interception.exe",
        "前端页面": DIST_DIR / "_internal" / "web" / "index.html",
        "ROI模板": DIST_DIR / "_internal" / "data" / "config" / "roi_templates" / "PVP标准模板.json",
        "精灵名单": DIST_DIR / "_internal" / "data" / "config" / "pet_names.txt",
        "战斗角标模板": DIST_DIR / "_internal" / "data" / "vision" / "battle",
        "RapidOCR模型": DIST_DIR / "_internal" / "rapidocr_onnxruntime",
    }
    print("\n=== 产物检查 ===")
    ok = True
    for label, p in checks.items():
        exists = p.exists()
        ok = ok and exists
        print(f"  {'✅' if exists else '❌'} {label}")

    zip_path = DIST_DIR.parent / f"{NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Compress-Archive -Path '{DIST_DIR}\\*' -DestinationPath '{zip_path}' -CompressionLevel Optimal"],
        capture_output=True, text=True)
    if zip_path.exists():
        print(f"\n✅ 分发包: {zip_path}  ({zip_path.stat().st_size / 1e6:.0f} MB)")
    print(f"目录: {DIST_DIR}  ({sum(f.stat().st_size for f in DIST_DIR.rglob('*') if f.is_file()) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
