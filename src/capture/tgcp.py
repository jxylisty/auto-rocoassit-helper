# -*- coding: utf-8 -*-
"""TGCP 协议底层解析 —— 洛克王国：世界 客户端与服务器通信帧格式

本模块只依赖标准库 + pycryptodome，实现四件事：
    1. BE21 帧头解析（21 字节大端固定头）
    2. 0x1002 握手包会话密钥提取（密钥明文裸传，无需解密）
    3. AES-128-CBC 解密 0x4013 业务包
    4. 轻量 protobuf 顶层解包（只解 wire-type 与字段号，不做 schema 翻译）

设计说明：
    这是对 TGCP/BE21 协议栈的独立实现，用于把游戏战斗数据从网络层直接取出，
    以替代此前基于屏幕 OCR 的识别方案。OCR 层保持原样不动，两条数据源可并行。

帧头结构（21 字节，大端）：
    offset  size  field
    0       2     magic       固定 0x3366
    2       2     head_ver    固定 0x000B
    4       2     body_ver    固定 0x000B
    6       2     cmd         命令码（0x1001=SYN / 0x1002=ACK / 0x2001=AUTH / 0x4013=DATA）
    8       1     flags       加密标志
    9       4     seq         序列号
    13      4     hdr_len     头总长（含此 21 字节固定头 + 变长 header_extra）
    17      4     body_len    body 长度
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAGIC = b"\x33\x66"
FIXED_HDR_LEN = 21

CMD_SYN = 0x1001
CMD_ACK = 0x1002
CMD_AUTH_REQ = 0x2001
CMD_DATA = 0x4013

_AES_IV = bytes(range(16))
_KNOWN_CMD_RANGE = range(0x0001, 0x8000)
_MAX_FRAME_LEN = 4 * 1024 * 1024

_CMD_NAMES = {
    CMD_SYN: "SYN",
    CMD_ACK: "ACK",
    CMD_AUTH_REQ: "AUTH_REQ",
    CMD_DATA: "DATA",
}


def _aes():
    try:
        from Crypto.Cipher import AES
    except ImportError as exc:  # pragma: no cover - 环境缺依赖时给出明确指引
        raise RuntimeError(
            "缺少 pycryptodome，无法解密战斗包。请执行: pip install pycryptodome"
        ) from exc
    return AES


def cmd_name(cmd: int) -> str:
    return _CMD_NAMES.get(cmd, f"0x{cmd:04X}")


def parse_key_text(text: str) -> bytes:
    """把 16 字节 ASCII 或 32 位 hex 文本解析成 AES key。"""
    raw = text.strip()
    if len(raw) == 16:
        try:
            return raw.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("key 必须是 16 字节 ASCII 或 32 位 hex") from exc
    hex_cand = "".join(c for c in raw if c in "0123456789abcdefABCDEF")
    if len(hex_cand) == 32:
        return bytes.fromhex(hex_cand)
    raise ValueError("key 必须是 16 字节 ASCII 或 32 位 hex")


def printable_ascii(blob: bytes) -> str | None:
    if blob and all(32 <= b < 127 for b in blob):
        return blob.decode("ascii")
    return None


@dataclass
class TgcpFrame:
    """一个解析出来的 TGCP 帧。"""

    direction: str
    stream_offset: int
    cmd: int
    seq: int
    hdr_len: int
    body_len: int
    header_extra: bytes = b""
    body: bytes = b""

    @property
    def cmd_name(self) -> str:
        return cmd_name(self.cmd)

    def session_key(self) -> bytes | None:
        """0x1002 的 header_extra 形如 02 10 <16字节key> 00 00 00 04 ...，
        其中 0x10 = 16 表示其后 16 字节就是会话密钥（明文）。"""
        extra = self.header_extra
        if self.cmd != CMD_ACK or len(extra) < 18:
            return None
        if extra[0] != 0x02 or extra[1] != 0x10:
            return None
        return extra[2:18]

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "stream_offset": self.stream_offset,
            "cmd": self.cmd,
            "cmd_hex": f"0x{self.cmd:04X}",
            "cmd_name": self.cmd_name,
            "seq": self.seq,
            "hdr_len": self.hdr_len,
            "body_len": self.body_len,
            "header_extra_hex": self.header_extra.hex(),
            "body_hex": self.body.hex(),
        }


def _validate_header(data: bytearray, off: int) -> bool:
    if off + FIXED_HDR_LEN > len(data):
        return False
    cmd = int.from_bytes(data[off + 6:off + 8], "big")
    hdr_len = int.from_bytes(data[off + 13:off + 17], "big")
    body_len = int.from_bytes(data[off + 17:off + 21], "big")
    if cmd not in _KNOWN_CMD_RANGE:
        return False
    if hdr_len < FIXED_HDR_LEN:
        return False
    if (hdr_len + body_len) > _MAX_FRAME_LEN:
        return False
    return True


def parse_frames(data: bytearray, direction: str, start: int) -> tuple[list[TgcpFrame], int]:
    """从字节流里连续抽取 TGCP 帧，返回 (帧列表, 下一个待解析偏移)。

    遇到不完整的尾帧时停在帧头处，等后续 TCP 段补齐。
    """
    frames: list[TgcpFrame] = []
    off = start
    size = len(data)
    while off + FIXED_HDR_LEN <= size:
        if data[off:off + 2] != MAGIC:
            nxt = data.find(MAGIC, off + 1)
            if nxt < 0:
                break
            off = nxt
            continue
        if not _validate_header(data, off):
            off += 2
            continue
        cmd = int.from_bytes(data[off + 6:off + 8], "big")
        seq = int.from_bytes(data[off + 9:off + 13], "big")
        hdr_len = int.from_bytes(data[off + 13:off + 17], "big")
        body_len = int.from_bytes(data[off + 17:off + 21], "big")
        total = hdr_len + body_len
        if off + total > size:
            break
        frames.append(
            TgcpFrame(
                direction=direction,
                stream_offset=off,
                cmd=cmd,
                seq=seq,
                hdr_len=hdr_len,
                body_len=body_len,
                header_extra=bytes(data[off + FIXED_HDR_LEN:off + hdr_len]),
                body=bytes(data[off + hdr_len:off + total]),
            )
        )
        off += total
    return frames, off


def decrypt_body(key: bytes, body: bytes) -> bytes:
    """AES-128-CBC 解密业务包 body，IV = 0x00..0x0f。"""
    if len(body) < 16:
        raise ValueError("body 长度不足，无法解密")
    if len(body) % 16 != 0:
        raise ValueError("body 不是 16 字节对齐")
    aes = _aes()
    return aes.new(key, aes.MODE_CBC, _AES_IV).decrypt(body)


def strip_padding(plain: bytes) -> bytes:
    """剥掉 tsf4g 尾部填充（尾部若干字节为填充长度记录，以 0 为主）。"""
    if not plain:
        return plain
    end = len(plain)
    while end > 0 and plain[end - 1] == 0:
        end -= 1
    return plain[:end]


# ---------------------------------------------------------------------------
# 轻量 protobuf 解包（只需字段号 + wire type，用于拿到顶层结构）
# ---------------------------------------------------------------------------

def read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift > 63:
            break
    raise ValueError("varint 越界")


def decode_fields(data: bytes) -> list[tuple[int, int, Any]]:
    """解出 [(field_no, wire_type, value)]。

    wire_type: 0=varint(int), 1=fixed64, 2=length-delimited(bytes), 5=fixed32。
    length-delimited 的 value 保留原始 bytes（调用方可再尝试 utf8 / 递归）。
    """
    fields: list[tuple[int, int, Any]] = []
    pos = 0
    size = len(data)
    while pos < size:
        try:
            tag, pos = read_varint(data, pos)
        except ValueError:
            break
        field_no = tag >> 3
        wire = tag & 0x07
        if field_no == 0:
            break
        if wire == 0:
            try:
                val, pos = read_varint(data, pos)
            except ValueError:
                break
            fields.append((field_no, 0, val))
        elif wire == 1:
            if pos + 8 > size:
                break
            fields.append((field_no, 1, data[pos:pos + 8]))
            pos += 8
        elif wire == 2:
            try:
                ln, pos = read_varint(data, pos)
            except ValueError:
                break
            if pos + ln > size:
                break
            fields.append((field_no, 2, data[pos:pos + ln]))
            pos += ln
        elif wire == 5:
            if pos + 4 > size:
                break
            fields.append((field_no, 5, data[pos:pos + 4]))
            pos += 4
        else:
            break
    return fields


def decode_message(data: bytes, depth: int = 0, max_depth: int = 6) -> dict[str, Any]:
    """递归解析成 {字段号: [值...]}；bytes 尽量解成 str 或继续递归。"""
    out: dict[str, Any] = {}
    if depth > max_depth:
        return out
    for field_no, wire, value in decode_fields(data):
        key = str(field_no)
        if wire == 2:
            assert isinstance(value, bytes)
            text = _try_utf8(value)
            if text is not None:
                item: Any = text
            else:
                sub = decode_message(value, depth + 1, max_depth)
                item = sub if sub else value.hex()
        elif wire == 0:
            item = value
        else:
            item = value.hex() if isinstance(value, bytes) else value
        out.setdefault(key, []).append(item)
    return out


def _try_utf8(blob: bytes) -> str | None:
    if not blob:
        return None
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not any("\u4e00" <= ch <= "\u9fff" for ch in text) and not text.isprintable():
        return None
    return text


def parse_session_key_from_frames(frames: list[TgcpFrame]) -> bytes | None:
    """从一批帧里找 0x1002 并取出会话密钥。"""
    for frame in frames:
        key = frame.session_key()
        if key:
            return key
    return None


@dataclass
class DirectionBuffer:
    """单方向 TCP 流重组 + TGCP 帧抽取。"""

    direction: str
    buffer: bytearray = field(default_factory=bytearray)
    parse_offset: int = 0
    stream_base: int = 0
    _base_seq: int | None = None
    _next_seq: int | None = None
    _pending: dict[int, bytes] = field(default_factory=dict)

    def feed(self, seq: int, payload: bytes) -> list[TgcpFrame]:
        if not payload:
            return []
        if self._base_seq is None:
            self._base_seq = seq
            self.buffer.extend(payload)
            self._next_seq = seq + len(payload)
        else:
            self._ingest(seq, payload)

        base = self.stream_base
        frames, new_off = parse_frames(self.buffer, self.direction, self.parse_offset)
        self.parse_offset = new_off
        for f in frames:
            f.stream_offset += base

        if self.parse_offset >= 0x10000 and self.parse_offset > len(self.buffer) // 2:
            trim = self.parse_offset
            del self.buffer[:trim]
            self.stream_base += trim
            if self._base_seq is not None:
                self._base_seq += trim
            self.parse_offset = 0
        return frames

    def _ingest(self, seq: int, payload: bytes) -> None:
        assert self._base_seq is not None and self._next_seq is not None
        end = seq + len(payload)

        if seq < self._base_seq:
            if end <= self._base_seq:
                return
            prepend = self._base_seq - seq
            self.buffer = bytearray(payload[:prepend]) + self.buffer
            self._base_seq = seq
            self.parse_offset += prepend
            self.stream_base = max(0, self.stream_base - prepend)
            if end <= self._next_seq:
                return
            payload = payload[self._next_seq - seq:]
            seq = self._next_seq
            if not payload:
                return

        if seq <= self._next_seq:
            start = seq - self._base_seq
            overlap = self._next_seq - seq
            if overlap > 0 and start >= 0:
                overlap = min(overlap, len(payload))
                existing = bytes(self.buffer[start:start + overlap])
                incoming = payload[:overlap]
                if existing != incoming:
                    # 同一 seq 上出现内容不同的重传（例如捕获到 6 字节全零伪段
                    # 后紧跟真正帧头），且冲突位于未解析区间时，以新内容替换，
                    # 否则保持已解析内容不回溯。
                    if start < self.parse_offset:
                        return
                    del self.buffer[start:]
                    self.buffer.extend(payload)
                    self._next_seq = seq + len(payload)
                    self.parse_offset = min(self.parse_offset, start)
                    self._drain()
                    return
            if overlap >= len(payload):
                return
            self.buffer.extend(payload[overlap:])
            self._next_seq += len(payload) - overlap
            self._drain()
            return

        self._pending[seq] = payload

    def _drain(self) -> None:
        assert self._next_seq is not None
        while self._pending:
            seq = min(self._pending)
            if seq > self._next_seq:
                return
            payload = self._pending.pop(seq)
            overlap = self._next_seq - seq
            if overlap >= len(payload):
                continue
            self.buffer.extend(payload[overlap:])
            self._next_seq += len(payload) - overlap
