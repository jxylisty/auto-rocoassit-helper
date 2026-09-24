# -*- coding: utf-8 -*-
"""PVP 对局封包探测工具

旁路监听游戏客户端与服务器之间的 TCP 8195 流量,把原始载荷落盘,
用于判断「战斗阶段到底有没有可读明文」,再决定是否值得投入做协议解析。

只读流量、不改包、不注入进程、不读内存,纯观察工具。
需要管理员权限(Windows 内核级抓包驱动 WinDivert 必需)。

用法:
    python tools/pvp_packet_probe.py                  # 抓 8195,跑到按 Ctrl+C
    python tools/pvp_packet_probe.py --port 8195
    python tools/pvp_packet_probe.py --seconds 300    # 抓 5 分钟后自动停
    python tools/pvp_packet_probe.py --hexdump        # 控制台实时打印十六进制

输出目录: data/capture_test/packets_<时间戳>/
    raw/            每个连接的原始字节流(*.bin)
    packets.jsonl   每个报文的元信息(方向/时间/长度/头部分析)
    summary.txt     本次抓包的统计摘要

判读要点:
    打开 summary.txt,重点看「可读文本占比」。
    如果某个方向大量出现 0x00-0x1f 以外的可打印字符 → 可能是明文/半明文
    如果字节熵很高、几乎无重复 → 大概率为加密流,协议逆向成本极高
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pydivert
except ImportError:
    print("[错误] 缺少 pydivert 依赖,请执行: pip install pydivert")
    sys.exit(1)


DEFAULT_PORT = 8195
OUTPUT_ROOT = PROJECT_ROOT / "data" / "capture_test"


def is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_admin() -> bool:
    if is_admin():
        return True

    print("[提示] 抓包需要管理员权限,正在尝试提权...")
    try:
        import ctypes

        script = str(Path(__file__).resolve())
        params = " ".join(sys.argv[1:])
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params}', None, 1
        )
        if ret > 32:
            print("[提示] 已在新窗口以管理员身份启动,本窗口可以关闭了。")
            return False
    except Exception as exc:
        print(f"[错误] 提权失败: {exc}")
    print("[错误] 请右键以管理员身份运行本脚本。")
    return False


def printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    printable = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(data)


def byte_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def find_repeats(data: bytes, min_len: int = 4, top: int = 5) -> list[tuple[bytes, int]]:
    """找重复出现的字节片段,重复多说明结构固定(可能是明文头或固定字段)。"""
    seen: Counter[bytes] = Counter()
    step = 1
    for i in range(0, max(1, len(data) - min_len), step):
        seen[data[i : i + min_len]] += 1
    return [(chunk, cnt) for chunk, cnt in seen.most_common(top) if cnt > 1]


def hexdump(data: bytes, limit: int = 256) -> str:
    lines = []
    shown = data[:limit]
    for i in range(0, len(shown), 16):
        chunk = shown[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  {i:08x}  {hex_part:<47}  {ascii_part}")
    if len(data) > limit:
        lines.append(f"  ... 共 {len(data)} 字节,仅显示前 {limit} 字节")
    return "\n".join(lines)


class ConnectionTracker:
    def __init__(self, out_dir: Path, hexdump_enabled: bool) -> None:
        self.out_dir = out_dir
        self.raw_dir = out_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.hexdump_enabled = hexdump_enabled
        self.packet_log = out_dir / "packets.jsonl"

        self.conns: dict[str, dict] = {}
        self.stats: dict[str, dict] = {}
        self.total_packets = 0
        self.total_bytes = 0
        self.start_time = time.time()

    def _conn_key(self, packet) -> str:
        return f"{packet.src_addr}:{packet.src_port}->{packet.dst_addr}:{packet.dst_port}"

    def _direction(self, packet) -> str:
        # outbound 表示本机发出(客户端→服务器),inbound 表示服务器→客户端
        return "send" if packet.is_outbound else "recv"

    def handle(self, packet) -> None:
        payload = packet.payload
        if not payload:
            return

        key = self._conn_key(packet)
        direction = self._direction(packet)
        now = time.time()

        conn = self.conns.setdefault(
            key,
            {
                "first_seen": now,
                "send_bytes": 0,
                "recv_bytes": 0,
                "raw_send": bytearray(),
                "raw_recv": bytearray(),
            },
        )

        stream_key = f"{key}|{direction}"
        stat = self.stats.setdefault(
            stream_key,
            {
                "conn": key,
                "direction": direction,
                "packets": 0,
                "bytes": 0,
                "sizes": [],
                "first_seen": now,
                "last_seen": now,
                "merged": bytearray(),
            },
        )

        stat["packets"] += 1
        stat["bytes"] += len(payload)
        stat["last_seen"] = now
        stat["merged"].extend(payload)

        if direction == "send":
            conn["send_bytes"] += len(payload)
            conn["raw_send"].extend(payload)
        else:
            conn["recv_bytes"] += len(payload)
            conn["raw_recv"].extend(payload)

        self.total_packets += 1
        self.total_bytes += len(payload)

        record = {
            "t": round(now - self.start_time, 3),
            "conn": key,
            "direction": direction,
            "length": len(payload),
        }
        with open(self.packet_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        if self.hexdump_enabled:
            tag = "SEND" if direction == "send" else "RECV"
            print(f"\n[{tag}] {key}  {len(payload)} 字节")
            print(hexdump(payload, limit=128))

    def finalize(self) -> None:
        for key, conn in self.conns.items():
            safe = key.replace(":", "_").replace("->", "__")
            if conn["raw_send"]:
                (self.raw_dir / f"{safe}.send.bin").write_bytes(bytes(conn["raw_send"]))
            if conn["raw_recv"]:
                (self.raw_dir / f"{safe}.recv.bin").write_bytes(bytes(conn["raw_recv"]))

        self._write_summary()

    def _write_summary(self) -> None:
        elapsed = time.time() - self.start_time
        lines: list[str] = []
        lines.append("=" * 70)
        lines.append("PVP 封包探测摘要")
        lines.append("=" * 70)
        lines.append(f"抓包时长      : {elapsed:.1f} 秒")
        lines.append(f"连接数        : {len(self.conns)}")
        lines.append(f"报文总数      : {self.total_packets}")
        lines.append(f"总字节数      : {self.total_bytes}")
        lines.append("")

        if not self.stats:
            lines.append("!! 没有抓到任何 8195 端口的数据包。")
            lines.append("   可能原因:")
            lines.append("   1. 抓包工具启动时游戏还没进入世界(需先开工具,再进游戏/重连)")
            lines.append("   2. 游戏走的是 UDP 而不是 TCP")
            lines.append("   3. 目标端口不是 8195,试试 --port 或抓全部端口")
            lines.append("   4. 网络经过加速器/代理,流量没经过本机网卡")
            (self.out_dir / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
            print("\n".join(lines))
            return

        lines.append("-" * 70)
        lines.append("各流量方向分析")
        lines.append("-" * 70)

        verdict_lines: list[str] = []
        for stream_key, stat in sorted(self.stats.items(), key=lambda x: -x[1]["bytes"]):
            merged = bytes(stat["merged"])
            ratio = printable_ratio(merged)
            entropy = byte_entropy(merged)
            lines.append("")
            lines.append(f"连接      : {stat['conn']}")
            lines.append(f"方向      : {'客户端→服务器 (send)' if stat['direction'] == 'send' else '服务器→客户端 (recv)'}")
            lines.append(f"报文数    : {stat['packets']}")
            lines.append(f"字节数    : {stat['bytes']}")
            lines.append(f"平均包长  : {stat['bytes'] / max(1, stat['packets']):.1f}")
            lines.append(f"可读文本占比: {ratio * 100:.1f}%")
            lines.append(f"字节熵    : {entropy:.2f} / 8.00  (越高越像加密,越低越像结构化明文)")

            repeats = find_repeats(merged)
            if repeats:
                lines.append("重复片段  :")
                for chunk, cnt in repeats:
                    try:
                        shown = chunk.decode("utf-8")
                    except UnicodeDecodeError:
                        shown = chunk.hex()
                    lines.append(f"    {chunk.hex()}  x{cnt}   ({shown!r})")

            lines.append("--- 前 512 字节 ---")
            lines.append(hexdump(merged, limit=512))

            if ratio > 0.55 and entropy < 6.0:
                verdict_lines.append(
                    f"  [+] {stat['conn']} [{stat['direction']}]: 疑似明文/半明文,值得进一步解析"
                )
            elif entropy > 7.5:
                verdict_lines.append(
                    f"  [-] {stat['conn']} [{stat['direction']}]: 高度加密,协议逆向成本极高"
                )
            else:
                verdict_lines.append(
                    f"  [?] {stat['conn']} [{stat['direction']}]: 混合特征,需要人工判读十六进制"
                )

        lines.append("")
        lines.append("-" * 70)
        lines.append("总体判读")
        lines.append("-" * 70)
        lines.extend(verdict_lines)
        lines.append("")
        lines.append("说明: 这只是粗判。真正的结论要打开 raw/*.bin 看十六进制。")
        lines.append("      若为 protobuf,通常能看到 0x08/0x12/0x1a 之类的字段标签规律。")
        lines.append("      若为完整加密,则字节分布均匀、无明显结构。")

        content = "\n".join(lines)
        (self.out_dir / "summary.txt").write_text(content, encoding="utf-8")
        print("\n" + content)


def build_filter(port: int | None) -> str:
    if port is None:
        return "tcp"
    return f"tcp.DstPort == {port} or tcp.SrcPort == {port}"


def main() -> int:
    parser = argparse.ArgumentParser(description="PVP 对局封包探测工具(只读旁路抓包)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"目标端口,默认 {DEFAULT_PORT}")
    parser.add_argument("--all-ports", action="store_true", help="抓所有 TCP 端口(排查真实端口用)")
    parser.add_argument("--seconds", type=int, default=0, help="抓包秒数,0 表示一直抓到 Ctrl+C")
    parser.add_argument("--hexdump", action="store_true", help="控制台实时打印十六进制")
    parser.add_argument("--yes", action="store_true", help="跳过确认提示")
    args = parser.parse_args()

    if not ensure_admin():
        return 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "allports" if args.all_ports else f"port{args.port}"
    out_dir = OUTPUT_ROOT / f"packets_{label}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    port = None if args.all_ports else args.port
    filter_str = build_filter(port)

    print("=" * 70)
    print("PVP 对局封包探测工具")
    print("=" * 70)
    print(f"过滤条件  : {filter_str}")
    print(f"输出目录  : {out_dir}")
    print(f"抓包时长  : {'一直抓到 Ctrl+C' if args.seconds <= 0 else str(args.seconds) + ' 秒'}")
    print("")
    print("重要: 先保持本工具运行,然后再点击游戏里的『进入世界』。")
    print("      如果已经进入游戏,请退出到登录界面重新进入,否则抓不到握手流量。")
    print("")
    print("只读流量,不改包、不注入、不读内存。仍请自行评估账号风险。")
    print("=" * 70)

    if not args.yes:
        input("\n准备好后按 Enter 开始抓包(或 Ctrl+C 取消)...")

    tracker = ConnectionTracker(out_dir, args.hexdump)

    print(f"\n开始抓包... {'(Ctrl+C 停止)' if args.seconds <= 0 else f'({args.seconds} 秒后自动停止)'}")
    start = time.time()

    try:
        with pydivert.WinDivert(filter_str) as w:
            print("抓包句柄已打开,等待数据流...\n")
            while True:
                packet = w.recv()
                tracker.handle(packet)
                # 只读观察:原样放行,绝不影响游戏连接
                w.send(packet)

                if args.seconds > 0 and time.time() - start >= args.seconds:
                    print(f"\n已达到 {args.seconds} 秒,停止抓包。")
                    break
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C,停止抓包。")
    except PermissionError:
        print("\n[错误] 权限不足。请右键以管理员身份运行本脚本。")
        return 1
    except Exception as exc:
        print(f"\n[错误] 抓包过程出错: {exc}")
        tracker.finalize()
        return 1

    tracker.finalize()
    print(f"\n原始数据已保存到: {out_dir}")
    print("先看 summary.txt,再按需查看 raw/*.bin。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
