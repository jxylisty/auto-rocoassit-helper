# -*- coding: utf-8 -*-
"""packet_capture — 洛克王国：世界 TCP 8195 战斗流量旁路抓包引擎

职责边界（只做网络层，不含任何业务语义）：
    1. 用 scapy 旁路监听本机与游戏服务器之间的 TCP 流量（只读、不改包、不注入）
    2. 按 TCP seq 做流重组，抽出 TGCP 帧（见 src.capture.tgcp）
    3. 从 0x1002 握手帧提取会话密钥（明文裸传）
    4. 用密钥 AES 解密 0x4013 业务帧，剥掉 tsf4g 尾部填充
    5. 把每个解出的帧通过回调交给上层（battle_listener 负责语义化）

设计说明：
    本模块替代此前基于屏幕 OCR 的对局数据采集方案的网络层部分。
    OCR 层保持原样不动，两条数据源可并行使用。
    只做协议层，不做 opcode 语义翻译（那部分由上层监听器扩展）。

用法（一般由 tools/pvp_packet_capture.py 驱动）：
    engine = PacketCaptureEngine(iface="WLAN", port=8195, on_frame=cb)
    engine.run(seconds=0)   # 0 = 一直跑到 stop()
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.capture import tgcp

DEFAULT_PORT = 8195

FrameCallback = Callable[["DecodedFrame"], None]


@dataclass
class DecodedFrame:
    """一条已完成解析（必要时已解密）的 TGCP 帧。"""

    captured_at: str
    direction: str
    cmd: int
    cmd_name: str
    seq: int
    header_extra: bytes
    raw_body: bytes
    key: bytes | None = None
    plain_body: bytes | None = None
    decrypt_status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "captured_at": self.captured_at,
            "direction": self.direction,
            "cmd": self.cmd,
            "cmd_hex": f"0x{self.cmd:04X}",
            "cmd_name": self.cmd_name,
            "seq": self.seq,
            "header_extra_hex": self.header_extra.hex(),
            "raw_body_hex": self.raw_body.hex(),
            "key_hex": self.key.hex() if self.key else "",
            "key_ascii": tgcp.printable_ascii(self.key) if self.key else "",
            "plain_body_hex": self.plain_body.hex() if self.plain_body is not None else "",
            "decrypt_status": self.decrypt_status,
        }


@dataclass
class FlowBuffers:
    """一个 TCP 流的双向重组缓冲。"""

    c2s: tgcp.DirectionBuffer = field(default_factory=lambda: tgcp.DirectionBuffer("c2s"))
    s2c: tgcp.DirectionBuffer = field(default_factory=lambda: tgcp.DirectionBuffer("s2c"))
    key: bytes | None = None


def _now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _extract_tcp(packet):
    """返回 (src_ip, src_port, dst_ip, dst_port, seq, payload) 或 None。"""
    try:
        from scapy.layers.inet import IP, TCP
        from scapy.layers.inet6 import IPv6
    except ImportError:
        return None
    if not packet.haslayer(TCP):
        return None
    tcp = packet[TCP]
    payload = bytes(tcp.payload)
    ip = packet[IP] if packet.haslayer(IP) else (packet[IPv6] if packet.haslayer(IPv6) else None)
    if ip is None:
        return None
    return ip.src, int(tcp.sport), ip.dst, int(tcp.dport), int(tcp.seq), payload


class PacketCaptureEngine:
    """旁路抓包 + TGCP 解析引擎。

    线程模型：
        run() 在调用线程里跑 scapy 的 sniff 循环；stop() 可安全地从其它线程调用。
        每解出一个帧就在抓包线程内同步回调 on_frame（回调需保持轻量）。
    """

    def __init__(
        self,
        *,
        iface: str | None = None,
        port: int = DEFAULT_PORT,
        on_frame: FrameCallback | None = None,
        preset_key: bytes | None = None,
        pcap_out: str | Path | None = None,
        verbose: bool = True,
    ) -> None:
        self.iface = iface
        self.port = int(port)
        self.on_frame = on_frame
        self.preset_key = preset_key
        self.pcap_out = str(pcap_out) if pcap_out else None
        self.verbose = verbose

        self._flows: dict[tuple, FlowBuffers] = {}
        self._worker: "PcapWriter | None" = None
        self._stop = threading.Event()
        self.stats = {
            "packets": 0,
            "frames": 0,
            "key_hits": 0,
            "decrypted": 0,
            "errors": 0,
        }
        self._log_lock = threading.Lock()

    # ---------------- 日志 ----------------

    def _log(self, msg: str) -> None:
        if not self.verbose:
            return
        with self._log_lock:
            print(f"[{_now_text()}] {msg}", flush=True)

    # ---------------- 生命周期 ----------------

    def stop(self) -> None:
        self._stop.set()

    def run(self, *, seconds: int = 0, ready_cb: Callable[[], None] | None = None) -> None:
        """开始抓包。seconds<=0 表示一直抓到 stop() 被调用。

        ready_cb 在 sniff 句柄就绪后触发，用于提示用户「现在可以点进入世界了」。
        """
        try:
            from scapy.all import sniff
            from scapy.utils import PcapWriter
        except ImportError as exc:
            raise RuntimeError(
                "缺少 scapy，无法抓包。请执行: pip install 'scapy>=2.7,<3'"
            ) from exc

        if self.pcap_out:
            Path(self.pcap_out).parent.mkdir(parents=True, exist_ok=True)
            self._worker = PcapWriter(self.pcap_out, append=True, sync=True)

        bpf = f"tcp port {self.port}"
        deadline = time.time() + seconds if seconds > 0 else None
        if ready_cb:
            ready_cb()
        self._log(f"开始旁路抓包 iface={self.iface or '默认网卡'} filter='{bpf}'")

        def _handler(packet) -> bool:
            if self._stop.is_set():
                return True
            try:
                self._process_packet(packet)
            except Exception as exc:  # 单包异常不能中断整条抓包
                self.stats["errors"] += 1
                self._log(f"[error] 处理数据包失败: {exc}")
            if deadline is not None and time.time() >= deadline:
                return True
            return False

        try:
            sniff(
                iface=self.iface,
                filter=bpf,
                prn=_handler,
                store=False,
                stop_filter=lambda _p: self._stop.is_set(),
            )
        except PermissionError as exc:
            raise RuntimeError(
                "抓包权限不足，请以管理员身份运行，并确认已安装 Npcap。"
            ) from exc
        finally:
            if self._worker is not None:
                self._worker.close()
                self._worker = None
            self._log(
                "[summary] packets={packets} frames={frames} key_hits={key_hits} "
                "decrypted={decrypted} errors={errors}".format(**self.stats)
            )

    # ---------------- 单包处理 ----------------

    def _process_packet(self, packet) -> None:
        if self._worker is not None:
            self._worker.write(packet)
        info = _extract_tcp(packet)
        if info is None:
            return
        src_ip, sport, dst_ip, dport, seq, payload = info
        if not payload:
            return

        if dport == self.port:
            direction = "c2s"
            flow_key = (src_ip, sport, dst_ip, dport)
        elif sport == self.port:
            direction = "s2c"
            flow_key = (dst_ip, dport, src_ip, sport)
        else:
            return

        self.stats["packets"] += 1
        flow = self._flows.get(flow_key)
        if flow is None:
            flow = FlowBuffers(key=self.preset_key)
            self._flows[flow_key] = flow
            self._log(f"[flow] new flow={src_ip}:{sport}->{dst_ip}:{dport}")

        buf = flow.c2s if direction == "c2s" else flow.s2c
        frames = buf.feed(seq, payload)
        for frame in frames:
            self._handle_frame(flow, frame)

    def _handle_frame(self, flow: FlowBuffers, frame: tgcp.TgcpFrame) -> None:
        self.stats["frames"] += 1

        key = flow.key or self.preset_key
        if frame.cmd == tgcp.CMD_ACK:
            session_key = frame.session_key()
            if session_key and session_key != flow.key:
                flow.key = session_key
                key = session_key
                self.stats["key_hits"] += 1
                self._log(
                    f"[ack_0x1002] dir={frame.direction} seq={frame.seq} "
                    f"key_hex={session_key.hex()} "
                    f"key_ascii={tgcp.printable_ascii(session_key) or '<non-ascii>'}"
                )

        decoded = DecodedFrame(
            captured_at=_now_text(),
            direction=frame.direction,
            cmd=frame.cmd,
            cmd_name=frame.cmd_name,
            seq=frame.seq,
            header_extra=frame.header_extra,
            raw_body=frame.body,
            key=key,
        )

        if frame.cmd == tgcp.CMD_DATA:
            if not key:
                decoded.decrypt_status = "no_key"
            else:
                try:
                    plain = tgcp.decrypt_body(key, frame.body)
                    decoded.plain_body = tgcp.strip_padding(plain)
                    decoded.decrypt_status = "ok"
                    self.stats["decrypted"] += 1
                except ValueError as exc:
                    decoded.decrypt_status = f"decrypt_error:{exc}"
                    self.stats["errors"] += 1
        else:
            decoded.decrypt_status = "control"

        if self.on_frame is not None:
            try:
                self.on_frame(decoded)
            except Exception as exc:
                self.stats["errors"] += 1
                self._log(f"[listener_error] cmd={frame.cmd_name} seq={frame.seq} error={exc}")
