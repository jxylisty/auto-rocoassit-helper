# -*- coding: utf-8 -*-
"""
Cython 编译 auth_core.py 为 .pyd（机器码保护，免费防破解方案）

用法:
    python tools/build_cython_auth.py            # 编译到 src/gui/auth_core.pyd
    python tools/build_cython_auth.py --clean    # 先清理缓存

产物:
    src/gui/auth_core.pyd       # 编译后的机器码文件（无法反编译字节码）
    build/                      # 临时构建目录

说明:
    - auth_core.py 包含最核心的鉴权逻辑（hwid、local_token、status 判定）
    - 编译成 .pyd 后，攻击者无法 dump 字节码或反编译 pyc
    - PyInstaller 会自动把 .pyd 打包进 EXE
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "gui"
BUILD_DIR = PROJECT_ROOT / "build" / "cython_auth"


def main() -> None:
    if "--clean" in sys.argv and BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print("已清空 build/cython_auth/")

    # 检查 auth_core.py 是否存在
    core_py = SRC_DIR / "auth_core.py"
    if not core_py.exists():
        raise SystemExit("错误：auth_core.py 不存在，请先运行拆分脚本")

    # 创建 setup.py 动态生成
    setup_py = BUILD_DIR / "setup.py"
    setup_py.parent.mkdir(parents=True, exist_ok=True)
    
    # 使用相对路径，避免 Windows 路径问题
    core_py_rel = core_py.relative_to(BUILD_DIR)
    setup_py.write_text(f'''
from setuptools import setup
from Cython.Build import cythonize
import os

# 设置编译器优化级别
os.environ["CYTHON_COMPILER"] = "gcc"

setup(
    ext_modules=cythonize(
        "{core_py_rel.as_posix()}",
        compiler_directives={{'language_level': "3", 'binding': True}},
        annotate=False  # 不生成 HTML 注解文件
    ),
    script_args=['build_ext', '--inplace']
)
''', encoding='utf-8')

    print(f">>> 开始编译 {core_py.name} ...")
    r = subprocess.run(
        [sys.executable, str(setup_py)],
        cwd=str(BUILD_DIR),
        capture_output=True,
        text=True
    )
    
    if r.returncode != 0:
        print("编译失败:")
        print(r.stdout)
        print(r.stderr)
        raise SystemExit("Cython 编译失败，请确保已安装 GCC 编译器")
    
    # 检查输出
    pyd_file = SRC_DIR / "auth_core.pyd"
    if pyd_file.exists():
        size = pyd_file.stat().st_size
        print(f"✅ 编译成功：{pyd_file.name} ({size:,} 字节)")
        
        # 验证导入
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("auth_core", pyd_file)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            
            # 测试核心函数
            hwid = m.get_hwid()
            assert len(hwid) == 32, f"hwid 长度错误：{len(hwid)}"
            
            token = m._local_token(hwid, 9999999999, "TEST-CODE")
            assert len(token) == 64, f"token 长度错误：{len(token)}"
            
            print("✅ 导入验证通过，核心函数可用")
        except Exception as e:
            print(f"⚠️  导入验证失败：{e}")
    else:
        print("❌ 未找到生成的 .pyd 文件")
        print("尝试查找:")
        for p in BUILD_DIR.rglob("*.pyd"):
            print(f"  找到：{p.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
