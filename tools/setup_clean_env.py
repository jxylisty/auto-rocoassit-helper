# -*- coding: utf-8 -*-
"""
创建/修复干净打包环境(实际体积优化,非压缩)

用法:
    python tools/setup_clean_env.py                # 创建 .venv-clean
    python tools/setup_clean_env.py .venv          # 修复/重建指定环境(如废弃的 .venv)
"""

import subprocess
import sys
import venv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = PROJECT_ROOT / (sys.argv[1] if len(sys.argv) > 1 else ".venv-clean")

# 运行必需(与 anaconda base 对比砍掉了: paddle/tensorflow/torch/mss/BetterCam/
# pytesseract/opencv-full 等全部无关项)
DEPENDENCIES = [
    "numpy==1.26.4",                    # 锁定与全部库兼容的版本
    "opencv-python-headless==4.11.0.86",  # 无 GUI 层,省几十 MB
    "pillow",
    "pywebview==6.1",
    "pythonnet",
    "keyboard",
    "interception-python",
    "pywin32",
    "PyYAML",
    "rapidocr-onnxruntime",
    "onnxruntime==1.17.3",              # 最新版在本机 DLL 初始化失败,锁 1.17.3
    "pyautogui",                        # 工具箱连点器用
    "pytest",
    "pyinstaller",
]


def run(cmd: list, title: str):
    print(f"\n>>> {title}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-1500:])
        print(result.stderr[-1500:])
        raise SystemExit(f"失败: {title}")
    print("OK")


def main() -> None:
    if not VENV_DIR.exists():
        print("创建 venv ...")
        venv.create(VENV_DIR, with_pip=True)
    py = VENV_DIR / "Scripts" / "python.exe"

    # 清理历史污染源: 旧 .venv 里把 Anaconda site-packages 挂进来的 .pth
    for pth in VENV_DIR.glob("Lib/site-packages/_base_site_packages.pth*"):
        pth.unlink()
        print(f"已移除污染源: {pth.name}")

    run([str(py), "-m", "pip", "install", "--upgrade", "pip", "--quiet"], "升级 pip")
    # 强制重装 numpy/cv2(修复可能损坏的包元数据,如 numpy._globals 报错)
    run([str(py), "-m", "pip", "install", "--force-reinstall", "--no-deps",
         "numpy==1.26.4", "opencv-python-headless==4.11.0.86", "--quiet",
         "--cache-dir", str(PROJECT_ROOT / ".pip-cache")], "重装 numpy/opencv 修复元数据")
    # 分两批: 先主体,再锁 onnxruntime 版本(rapidocr 默认拉的版本 DLL 初始化失败)
    main_deps = [d for d in DEPENDENCIES if not d.startswith("onnxruntime")
                 and not d.startswith(("numpy", "opencv"))]
    run([str(py), "-m", "pip", "install", *main_deps, "--quiet",
         "--cache-dir", str(PROJECT_ROOT / ".pip-cache")], "安装主体依赖")
    run([str(py), "-m", "pip", "install", "onnxruntime==1.17.3", "--force-reinstall",
         "--no-deps", "--quiet", "--cache-dir", str(PROJECT_ROOT / ".pip-cache")],
        "锁定 onnxruntime 1.17.3")

    # ---- 验证全部关键导入 ----
    verify = (
        "import numpy, cv2, webview, keyboard, yaml, PIL, clr, "
        "rapidocr_onnxruntime, onnxruntime, interception, "
        "win32gui, pyautogui, PyInstaller\n"
        "print('clean venv 全部导入 OK |', 'numpy', numpy.__version__, "
        "'| cv2', cv2.__version__, '| onnxruntime', onnxruntime.__version__)"
    )
    run([str(py), "-c", verify], "验证导入")

    size = sum(f.stat().st_size for f in VENV_DIR.rglob("*") if f.is_file()) / 1e6
    print(f"\n完成: {VENV_DIR}  ({size:.0f} MB)")
    print(f"打包命令: {py} tools/build_main_app.py")


if __name__ == "__main__":
    main()
