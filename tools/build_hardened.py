# -*- coding: utf-8 -*-
"""build_hardened.py — 加固版一键构建 (完整过程编排)

流程:
  [0/6] 环境自检: anaconda python + Cython + MSVC (cl.exe via vcvars64)
  [1/6] 密钥管理: 读取/生成 build/_hardened/keys.json (Ed25519 + DATA_SEED)
        - Ed25519 公钥 hex 自动写入 auth_core.py (公钥是公开锚点, 可入库)
        - 私钥/seed 只存本机 build/_hardened/, 与 Worker 环境变量保持同步 (人工)
  [2/6] Cython 编译: src/gui/auth_core.py → .pyd (MSVC x64, 机器码保护)
  [3/6] 数据加密: src/pvp/data/*.json → .bin (核心资产与 seed 绑定)
  [4/6] 冒烟测试: 导入 auth_core/seadata/auth, 本机 seed 解密数据
  [5/6] PyInstaller 打包 (加密数据 + pyd 随包)
  [6/6] 产物检查 + zip

用法:
    # 用 anaconda python 运行 (Cython 在该环境):
    D:/anaconda/python.exe tools/build_hardened.py            # 完整构建
    D:/anaconda/python.exe tools/build_hardened.py --skip-seal # 数据已加密过, 跳过
    D:/anaconda/python.exe tools/build_hardened.py --show-keys # 查看当前密钥(部署 Worker 用)
    D:/anaconda/python.exe tools/build_hardened.py --rotate    # 轮换密钥(旧分发包数据将不可读)

部署提醒 (每次 --rotate 后必须做):
    Cloudflare Worker → Settings → Variables:
      DATA_SEED           = keys.json 里的 data_seed
      ED25519_PRIVATE_KEY = keys.json 里的 ed25519_private_pkcs8
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HARD_DIR = PROJECT_ROOT / "build" / "_hardened"
KEYS_FILE = HARD_DIR / "keys.json"
CORE_PY = PROJECT_ROOT / "src" / "gui" / "auth_core.py"
PUBKEY_ANCHOR_BEGIN = "_ED25519_PUB_HEX = \""
PUBKEY_ANCHOR_END = "\""

VENV_PY = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def log(msg: str) -> None:
    print(msg, flush=True)


def find_msvc_vcvars() -> Path:
    for base in (Path(r"D:\vsstudio"), Path(r"C:\Program Files (x86)\Microsoft Visual Studio"),
                 Path(r"C:\Program Files\Microsoft Visual Studio")):
        cand = base / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if cand.exists():
            return cand
    raise SystemExit("未找到 vcvars64.bat (MSVC x64 编译环境), 请安装 Visual Studio C++ 工具集")


# ========================================
# [1] 密钥管理
# ========================================
def load_or_create_keys(rotate: bool = False) -> dict:
    if KEYS_FILE.exists() and not rotate:
        keys = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        log(f"[1/6] 密钥已存在: {KEYS_FILE}")
        return keys
    import secrets
    keys = {
        "data_seed": secrets.token_hex(32),
        "ed25519_private_pkcs8": "",   # node tools/gen_worker_keys.js 生成
        "ed25519_public_raw": "",
    }
    # 尝试用 node 生成 Ed25519 (有 node 就自动生成, 没有则提示人工)
    node = shutil.which("node")
    if node:
        try:
            r = subprocess.run([node, str(PROJECT_ROOT / "tools" / "gen_worker_keys.js")],
                               capture_output=True, text=True, timeout=30,
                               encoding="utf-8", errors="replace")
            out = (r.stdout or "")
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("ED25519_PRIVATE_KEY"):
                    keys["ed25519_private_pkcs8"] = line.split("=", 1)[1].strip()
                elif line.startswith("ED25519_PUBLIC_KEY"):
                    keys["ed25519_public_raw"] = line.split("=", 1)[1].strip()
        except Exception as e:
            log(f"  node 生成 Ed25519 失败 ({e}), 稍后可手动运行 tools/gen_worker_keys.js")
    HARD_DIR.mkdir(parents=True, exist_ok=True)
    KEYS_FILE.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    log(f"[1/6] 新密钥已生成: {KEYS_FILE} (rotate={rotate})")
    return keys


def write_pubkey_anchor(pub_hex: str) -> None:
    """把 Ed25519 公钥写入 auth_core.py 的锚点位置 (公钥是公开的, 可提交)"""
    src = CORE_PY.read_text(encoding="utf-8")
    anchor_line = f'{PUBKEY_ANCHOR_BEGIN}{pub_hex}{PUBKEY_ANCHOR_END}'
    new_src, n = [], 0
    for line in src.splitlines(keepends=True):
        if line.startswith(PUBKEY_ANCHOR_BEGIN):
            new_src.append(anchor_line + "\n")
            n += 1
        else:
            new_src.append(line)
    if n == 0:
        raise SystemExit("auth_core.py 中未找到 _ED25519_PUB_HEX 锚点")
    CORE_PY.write_text("".join(new_src), encoding="utf-8")
    log(f"  已把公钥锚点写入 auth_core.py ({'更新' if pub_hex else '清空'})")


def show_keys(keys: dict) -> None:
    log("\n===== 部署 Worker 所需密钥 (Cloudflare → Settings → Variables) =====")
    log(f"DATA_SEED           = {keys.get('data_seed', '')}")
    log(f"ED25519_PRIVATE_KEY = {keys.get('ed25519_private_pkcs8') or '(未生成: node tools/gen_worker_keys.js)'}")
    log(f"ED25519_PUBLIC_KEY  = {keys.get('ed25519_public_raw') or '(未生成)'}")
    log("(私钥/seed 只存本机 build/_hardened/keys.json, 不要提交进 git)\n")


# ========================================
# [2] Cython 编译 auth_core
# ========================================
def build_auth_core_pyd() -> None:
    vcvars = find_msvc_vcvars()
    build_dir = PROJECT_ROOT / "build" / "cython_auth"
    build_dir.mkdir(parents=True, exist_ok=True)
    core_py_rel = CORE_PY.relative_to(build_dir) if CORE_PY.is_relative_to(build_dir) else None

    # 把 auth_core.py 复制进 build 目录 (相对路径编译, 避免 MSVC 路径问题)
    src_copy = build_dir / "auth_core.py"
    shutil.copy2(CORE_PY, src_copy)

    setup_py = build_dir / "setup.py"
    setup_py.write_text('''
from setuptools import setup
from Cython.Build import cythonize

setup(
    ext_modules=cythonize(
        "auth_core.py",
        compiler_directives={'language_level': "3", 'binding': True},
        annotate=False
    ),
    script_args=['build_ext', '--inplace']
)
''', encoding='utf-8')

    log("[2/6] Cython 编译 auth_core.py (MSVC x64)...")
    # 用批处理文件规避 cmd /c 的引号解析问题; %~dp0 规避中文路径编码问题
    bat = build_dir / "_build_auth_core.cmd"
    bat.write_text(
        "@echo off\r\n"
        f'call "{vcvars}" >nul 2>&1\r\n'
        "cd /d %~dp0\r\n"
        f'"{sys.executable}" setup.py build_ext --inplace\r\n'
        "exit /b %ERRORLEVEL%\r\n",
        encoding="ascii")
    r = subprocess.run(["cmd", "/c", str(bat)], cwd=str(build_dir),
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        log(r.stdout[-3000:])
        log(r.stderr[-3000:])
        raise SystemExit("Cython 编译失败 (需要 MSVC x64 + Cython)")

    # 找产物 (auth_core.cp312-win_amd64.pyd)
    pyds = list(build_dir.glob("auth_core.*.pyd")) + list(build_dir.glob("auth_core.pyd"))
    if not pyds:
        raise SystemExit(f"编译完成但未找到 .pyd: {build_dir}")
    dst = PROJECT_ROOT / "src" / "gui" / "auth_core.pyd"
    shutil.copy2(pyds[0], dst)
    log(f"  ✓ {dst.name} ({dst.stat().st_size:,} B)")


# ========================================
# [3] 数据加密
# ========================================
def seal_data(seed: str, force: bool) -> None:
    log("[3/6] 加密核心数据 (json → bin)...")
    r = subprocess.run([sys.executable, str(PROJECT_ROOT / "tools" / "seal_assets.py"),
                        "--seed", seed] + (["--force"] if force else []),
                       cwd=str(PROJECT_ROOT))
    if r.returncode != 0:
        raise SystemExit("数据加密失败")


# ========================================
# [4] 冒烟测试
# ========================================
def smoke_test(seed: str) -> None:
    log("[4/6] 冒烟测试 (导入 + 本机 seed 解密)...")
    code = f'''
import sys, json, time
sys.path.insert(0, {str(PROJECT_ROOT)!r})

# auth_core (pyd 优先)
from src.gui import auth_core
hwid = auth_core.get_hwid()
assert hwid and len(hwid) == 32, "hwid 异常"
tok = auth_core._local_token(hwid, 123, "X")
assert len(tok) == 64
seed_key = auth_core.derive_key({seed!r})
assert len(seed_key) == 32
assert auth_core.builtin_api_base().startswith("https://")
now_ms = int(time.time() * 1000)
sig = auth_core._local_token(hwid, 9999999999999, "CODE")
st = auth_core.status(hwid, "CODE", "tok", 9999999999999, sig, now_ms)
assert st.get("authorized") is True, st

# seadata: dist 语义 (只有 .bin 时未授权必须拒绝) + 重载链
from src.pvp import seadata, pet_loader, skill_loader
n_before = len(pet_loader._PET_DETAIL)
seadata.set_key(seed_key)
assert len(pet_loader._PET_DETAIL) > 100, f"重载后 pet_detail 异常: {{len(pet_loader._PET_DETAIL)}}"
assert len(pet_loader._PET_SKILLS) > 100
assert len(skill_loader._SKILLS) > 100
assert pet_loader.get_pet_count() > 100
assert len(pet_loader._TITLE_TO_FORM) > 100
assert len(pet_loader._FINAL_ALLOWED) > 50

# seed_cache 往返
w = auth_core.wrap_cache_seed({seed!r}, hwid)
assert auth_core.unwrap_cache_seed(w, hwid) == {seed!r}
assert auth_core.unwrap_cache_seed(w, "other-machine") != {seed!r}

# auth.py 完整链
from src.gui import auth
s = auth.status()
assert "authorized" in s
print("SMOKE_OK: hwid=%s... pets=%d titles=%d skills=%d pubkey=%s" % (
    hwid[:8], len(pet_loader._PET_DETAIL), len(pet_loader._TITLE_TO_FORM),
    len(skill_loader._SKILLS), bool(auth_core.builtin_pubkey())))
'''
    r = subprocess.run([sys.executable, "-c", code], cwd=str(PROJECT_ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "SMOKE_OK" not in out:
        log(out[-4000:])
        raise SystemExit("冒烟测试失败")
    for line in out.splitlines():
        if "SMOKE_OK" in line:
            log("  ✓ " + line.strip())


# ========================================
# [5/6] PyInstaller 打包 (复用 build_main_app.py 的参数)
# ========================================
def pyinstaller_pack(name: str) -> None:
    log("[5/6] PyInstaller 打包...")
    staging = PROJECT_ROOT / "build" / "_mainapp_staging"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "data" / "config" / "roi_templates").mkdir(parents=True)
    (staging / "interception").mkdir(parents=True)

    def _copy_tree(src: Path, dst: Path):
        if src.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.db", "output"))

    _copy_tree(PROJECT_ROOT / "data" / "config", staging / "data" / "config")
    _copy_tree(PROJECT_ROOT / "data" / "vision", staging / "data" / "vision")

    # 加密后的 pvp 数据 (只剩 .bin + 未加密白名单)
    pvp_data_dst = staging / "src" / "pvp" / "data"
    pvp_data_dst.mkdir(parents=True)
    for f in (PROJECT_ROOT / "src/pvp/data").iterdir():
        if f.is_file():
            shutil.copy2(f, pvp_data_dst / f.name)

    # 防泄漏: 开发机的 auth.json (含真实卡密/token) 不能进分发包
    for leak in [(staging / "data" / "config" / "auth.json"),]:
        if leak.exists():
            leak.unlink()
            log(f"  ⚠ 已从 staging 剔除 {leak.name} (开发机凭据不入包)")

    interceptor = PROJECT_ROOT / "build" / "_interception" / "lib" / "Interception" / "command line installer" / "install-interception.exe"
    if interceptor.exists():
        shutil.copy2(interceptor, staging / "interception" / "install-interception.exe")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", name, "--noconfirm", "--noconsole", "--onedir",
        "--distpath", str(PROJECT_ROOT / "dist"),
        "--workpath", str(PROJECT_ROOT / "build"),
        "--specpath", str(PROJECT_ROOT / "build"),
        "--add-data", f"{staging / 'data'};data",
        "--add-data", f"{pvp_data_dst};src/pvp/data",
        "--add-data", f"{staging / 'interception'};interception",
        "--add-data", f"{PROJECT_ROOT / 'src/gui/web'};web",
        "--hidden-import", "keyboard", "--hidden-import", "webview",
        "--collect-all", "webview",
        "--collect-all", "rapidocr_onnxruntime",
        "--collect-all", "onnxruntime",
        "--exclude-module", "PyQt5", "--exclude-module", "PySide6",
        "--exclude-module", "PySide2", "--exclude-module", "PyQt6",
        "--exclude-module", "tkinter",
        "--exclude-module", "tensorflow", "--exclude-module", "torch",
        "--exclude-module", "torchvision", "--exclude-module", "torchaudio",
        "--exclude-module", "paddle", "--exclude-module", "paddleocr",
        "--exclude-module", "ultralytics", "--exclude-module", "playwright",
        "--exclude-module", "llvmlite", "--exclude-module", "numba",
        "--exclude-module", "botocore", "--exclude-module", "boto3",
        "--exclude-module", "panel", "--exclude-module", "bokeh",
        "--exclude-module", "pygame", "--exclude-module", "matplotlib",
        "--exclude-module", "pandas", "--exclude-module", "sklearn",
        "--exclude-module", "scipy",
        "--paths", str(PROJECT_ROOT),
        str(PROJECT_ROOT / "tools/app_entry.py"),
    ]
    r = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if r.returncode != 0:
        raise SystemExit("PyInstaller 打包失败")

    dist_dir = PROJECT_ROOT / "dist" / name
    exe_src = dist_dir / "app_entry.exe"
    exe_dst = dist_dir / f"{name}.exe"
    if exe_src.exists():
        exe_src.rename(exe_dst)
    readme = PROJECT_ROOT / "tools" / "本体_使用说明.txt"
    if readme.exists():
        shutil.copy2(readme, dist_dir / "使用说明.txt")


# ========================================
# [6] 产物检查 + zip
# ========================================
def verify_and_zip(name: str) -> None:
    log("[6/6] 产物检查...")
    dist_dir = PROJECT_ROOT / "dist" / name
    checks = {
        "主程序": dist_dir / f"{name}.exe",
        "授权核心(pyd)": dist_dir / "_internal" / "src" / "gui" / "auth_core.pyd",
        "加密数据(pet_skills.bin)": dist_dir / "_internal" / "src" / "pvp" / "data" / "pet_skills.bin",
        "加密数据(pet_detail.bin)": dist_dir / "_internal" / "src" / "pvp" / "data" / "pet_detail.bin",
        "明文pet_skills.json (应不存在)": dist_dir / "_internal" / "src" / "pvp" / "data" / "pet_skills.json",
        "明文pet_detail.json (应不存在)": dist_dir / "_internal" / "src" / "pvp" / "data" / "pet_detail.json",
        "开发机auth.json (应不存在)": dist_dir / "_internal" / "data" / "config" / "auth.json",
        "公开数据(type_chart.json)": dist_dir / "_internal" / "src" / "pvp" / "data" / "type_chart.json",
        "驱动安装器": dist_dir / "_internal" / "interception" / "install-interception.exe",
        "前端页面": dist_dir / "_internal" / "web" / "index.html",
        "RapidOCR模型": dist_dir / "_internal" / "rapidocr_onnxruntime",
    }
    ok = True
    for label, p in checks.items():
        if "应不存在" in label:
            good = not p.exists()
        else:
            good = p.exists()
        ok = ok and good
        print(f"  {'✅' if good else '❌'} {label}")
    if not ok:
        raise SystemExit("产物检查未通过")

    # 明文泄漏终检: dist 里不允许存在密封清单内的 .json (公开数据白名单除外)
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    from seal_assets import SEALED_NAMES
    leaked = [f.name for f in (dist_dir / "_internal" / "src" / "pvp" / "data").glob("*.json")
              if f.stem in SEALED_NAMES]
    if leaked:
        raise SystemExit(f"明文数据泄漏到分发包: {leaked}")
    log("  ✓ 无明文核心数据泄漏")

    zip_path = dist_dir.parent / f"{name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Compress-Archive -Path '{dist_dir}\\*' -DestinationPath '{zip_path}' -CompressionLevel Optimal"],
                   capture_output=True, text=True)
    if zip_path.exists():
        log(f"\n✅ 分发包: {zip_path}  ({zip_path.stat().st_size / 1e6:.0f} MB)")
    log(f"目录: {dist_dir}  ({sum(f.stat().st_size for f in dist_dir.rglob('*') if f.is_file()) / 1e6:.0f} MB)")


# ========================================
# main
# ========================================
def main() -> None:
    rotate = "--rotate" in sys.argv
    skip_seal = "--skip-seal" in sys.argv
    name = "洛克王国助手"

    for a in sys.argv:
        if a.startswith("--name="):
            name = a.split("=", 1)[1]

    if "--show-keys" in sys.argv:
        show_keys(load_or_create_keys())
        return

    log("=" * 60)
    log("洛克王国助手 · 加固版构建")
    log("=" * 60)

    keys = load_or_create_keys(rotate=rotate)
    seed = keys["data_seed"]
    pub = keys.get("ed25519_public_raw") or ""
    write_pubkey_anchor(pub)

    build_auth_core_pyd()

    if not skip_seal:
        seal_data(seed, force=rotate)
    else:
        log("[3/6] 跳过数据加密 (--skip-seal)")

    smoke_test(seed)

    pyinstaller_pack(name)
    verify_and_zip(name)

    show_keys(keys)
    log("构建完成。提醒: 若密钥是首次生成/已轮换, 记得把 Worker 的 DATA_SEED / ED25519_PRIVATE_KEY 同步更新。")


if __name__ == "__main__":
    main()
