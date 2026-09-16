# -*- coding: utf-8 -*-
"""
PVP 数据采集器 - 控制台入口(可打包为独立 exe)

用法:
    python tools/pvp_data_collector.py            # 自动采集 + 控制台交互
    python tools/pvp_data_collector.py --output D:\\收集目录

控制台命令: Enter=手动截图  s=统计  q=退出
全局热键: F7=手动截图(游戏内可按)
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pvp.data_collector import PvpDataCollector  # noqa: E402


def main() -> None:
    output = None
    if "--output" in sys.argv:
        i = sys.argv.index("--output")
        if i + 1 < len(sys.argv):
            output = Path(sys.argv[i + 1])

    collector = PvpDataCollector(output_dir=output)
    interval = 2.0
    stop = threading.Event()
    manual_flag = threading.Event()

    # 全局热键 F7(游戏内也能按)
    try:
        import keyboard
        keyboard.add_hotkey("f7", manual_flag.set)
        print("[热键] F7 手动截图 已注册")
    except Exception as e:
        print(f"[热键] F7 注册失败({e}),改用控制台 Enter 手动截图")

    print("=" * 62)
    print("PVP 数据采集器")
    print("=" * 62)
    print(f"输出目录: {collector.output}")
    print("自动采集: 每2秒一轮(战斗中敌方头像/名牌/OCR失败样本)")
    print("手动截图: F7 或 按 Enter  (战备阶段我方阵容等)")
    print("命令: s=统计  q=退出")
    print("=" * 62)
    print("提示: 游戏保持窗口化且不被遮挡;本工具只读屏幕不做任何输入模拟")
    print()

    def auto_loop():
        while not stop.is_set():
            try:
                status = collector.auto_collect()
                stamp = time.strftime("%H:%M:%S")
                print(f"[{stamp}] {status}  |  {collector.summary()}")
            except Exception as e:
                print(f"[采集异常] {e}")
            stop.wait(interval)

    worker = threading.Thread(target=auto_loop, daemon=True)
    worker.start()

    try:
        while True:
            cmd = input().strip().lower()
            if cmd == "q":
                break
            if cmd == "s":
                print(collector.summary())
                continue
            if cmd == "" :
                manual_flag.set()
                continue
        # 退出前把最后一次手动请求处理掉
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        stop.set()
        if manual_flag.is_set():
            path = collector.save_manual("退出前")
            if path:
                print(f"已保存: {path}")
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        print("\n最终统计:", collector.summary())
        print(f"素材目录: {collector.output}")
        print("把整个 output 文件夹打包发给开发者即可")


if __name__ == "__main__":
    main()
