# -*- coding: utf-8 -*-
"""
洛克王国 PVP 助手 - 启动入口

Usage:
    python main.py              # 启动GUI界面
    python main.py --cli        # 命令行模式
    python main.py --throw      # 启动自动扔球工具
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description='洛克王国 PVP 助手')
    parser.add_argument('--cli', action='store_true', help='命令行模式')
    parser.add_argument('--throw', action='store_true', help='启动自动扔球工具')

    args = parser.parse_args()

    if args.throw:
        # 启动自动扔球工具
        from auto_throw_ball import AutoThrowBall
        tool = AutoThrowBall()
        tool.start()
    elif args.cli:
        print("命令行模式 - 开发中...")
    else:
        # 启动GUI界面
        print("启动GUI界面...")
        try:
            from pvp_assistant_live import PVPAssistantApp
            app = PVPAssistantApp()
            app.run()
        except ImportError:
            print("GUI模块未安装，请检查 pvp_assistant_live.py")
            sys.exit(1)


if __name__ == '__main__':
    main()