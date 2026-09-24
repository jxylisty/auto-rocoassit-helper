# -*- coding: utf-8 -*-
"""battle_listener — 把解密后的 TGCP 业务帧转成结构化记录并落盘

职责边界（协议层语义，不含数值/技能的领域翻译）：
    1. 解析 0x4013 解密后 body，抽出 opcode / session_id / subtype / payload
    2. 对 payload 做顶层 protobuf 解包（字段号 + wire type + 文本/子消息）
    3. 把每条业务记录写成一行 jsonl，便于离线分析与后续语义层消费
    4. 通过 on_record 回调把结构化 dict 抛给上层（供 GUI / AI 复盘使用）

与 OCR 层的关系：
    OCR 层（src.pvp.round_logger / data_collector）保持原样不动。
    本监听器把抓包数据写到独立目录 data/capture/，两条数据源互不干扰。

记录布局（解密后 body）：
    tgcp_4013_v14    : 0x1E 起，body[4:6]==55aa 且 body[24:26]==3963，
                       含 transport_seq/session_id/sub_id/req_seq，payload 自 body[30:]
    tgcp_4013_live_s2c: body[4:6]==55aa，opcode=body[0:4]，subtype=body[6:10]，payload 自 body[10:]
    tgcp_4013_live_c2s: body[8:10]==3963，opcode=body[4:8]，payload 自 body[14:]
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.capture import tgcp
from src.capture.packet_capture import DecodedFrame

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CAPTURE_DIR = PROJECT_ROOT / "data" / "capture"

RecordCallback = Callable[[dict], None]

_MAX_PROTO_DEPTH = 8
_MAX_PROTO_FIELDS = 512
_TSF4G_MARKER = b"tsf4g"


def _now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def tsf4g_trailer_len(data: bytes) -> int:
    """TSF4G 尾部长度：末尾 6 字节为 'tsf4g'+pad，且 7<=pad<=22 时有效。"""
    if len(data) < 6 or data[-6:-1] != _TSF4G_MARKER:
        return 0
    pad = data[-1]
    if 7 <= pad <= 22 and len(data) >= pad:
        return pad
    return 0


def strip_tsf4g_padding(data: bytes) -> bytes:
    trailer = tsf4g_trailer_len(data)
    return data[:-trailer] if trailer else data


def normalize_c2s_opcode(opcode: int) -> tuple[int, bool]:
    low16 = opcode & 0xFFFF
    if opcode > 0xFFFF and (opcode >> 16) == 0x0001 and low16:
        return low16, True
    return opcode, False


def parse_proto_message(
    data: bytes,
    *,
    depth: int = 0,
    max_depth: int = _MAX_PROTO_DEPTH,
    max_fields: int = _MAX_PROTO_FIELDS,
) -> dict[str, Any]:
    """轻量 protobuf 解包成 {fields:[{field,wire,value|raw_hex|text|sub}]} 树。"""
    fields: list[dict[str, Any]] = []
    off = 0
    clean = True
    while off < len(data):
        if len(fields) >= max_fields:
            clean = False
            break
        start = off
        try:
            tag, off = tgcp.read_varint(data, off)
        except ValueError:
            clean = False
            break
        field_no, wire_type = tag >> 3, tag & 7
        entry: dict[str, Any] = {"field": field_no, "wire": wire_type}
        try:
            if wire_type == 0:
                entry["value"], off = tgcp.read_varint(data, off)
            elif wire_type == 1:
                if off + 8 > len(data):
                    clean = False
                    break
                entry["raw_hex"] = data[off:off + 8].hex()
                off += 8
            elif wire_type == 2:
                blen, off = tgcp.read_varint(data, off)
                if off + blen > len(data):
                    clean = False
                    break
                blob = data[off:off + blen]
                off += blen
                entry["len"] = blen
                entry["raw_hex"] = blob.hex()
                text = tgcp._try_utf8(blob)
                if text is not None:
                    entry["text"] = text
                elif depth < max_depth and blob:
                    sub = parse_proto_message(
                        blob, depth=depth + 1, max_depth=max_depth, max_fields=max_fields
                    )
                    if sub["fields"] and sub["consumed"] == len(blob):
                        entry["sub"] = sub
            elif wire_type == 5:
                if off + 4 > len(data):
                    clean = False
                    break
                entry["raw_hex"] = data[off:off + 4].hex()
                off += 4
            else:
                clean = False
                break
        except ValueError:
            clean = False
            break
        entry["offset"] = start
        fields.append(entry)
    return {"fields": fields, "consumed": off, "clean": clean and off == len(data)}


@dataclass
class BusinessRecord:
    direction: str
    layout: str
    opcode: int
    opcode_hex: str
    payload: bytes
    session_id: int | None = None
    sub_id: int | None = None
    req_seq: int | None = None
    transport_seq: int | None = None

    def to_dict(self, *, with_tree: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "t": _now_text(),
            "direction": self.direction,
            "layout": self.layout,
            "opcode": self.opcode,
            "opcode_hex": self.opcode_hex,
            "payload_len": len(self.payload),
            "payload_hex": self.payload.hex(),
        }
        if self.session_id is not None:
            out["session_id"] = self.session_id
        if self.sub_id is not None:
            out["sub_id"] = self.sub_id
        if self.req_seq is not None:
            out["req_seq"] = self.req_seq
        if self.transport_seq is not None:
            out["transport_seq"] = self.transport_seq
        if with_tree:
            out["tree"] = parse_proto_message(self.payload)
        return out


_IVDECODER_PREFIX_LEN = 16


def parse_business_body(body: bytes, direction: str) -> BusinessRecord | None:
    """从解密后的 0x4013 body 里抽出业务记录（依次尝试各布局）。

    实测绝大多数帧外层是 Ivdecoder 封装：body 前 16 字节为头部
    （counter/长度/opcode/常量），真正的记录从 body[16:] 开始。
    因此先按「带 16 字节前缀」解析，再回退到「无前缀」解析。
    """
    candidates: list[tuple[bytes, str]] = []
    if len(body) >= _IVDECODER_PREFIX_LEN:
        candidates.append((body[_IVDECODER_PREFIX_LEN:], "ivdecoder"))
    candidates.append((body, "raw"))

    for payload, wrapper in candidates:
        for parser in (_parse_v14, _parse_live_s2c, _parse_live_c2s):
            record = parser(payload, direction)
            if record is not None:
                if wrapper == "ivdecoder":
                    record.layout = f"{record.layout}_ivdecoder"
                return record
        if direction == "c2s":
            record = _parse_c2s_fallback(payload)
            if record is not None:
                if wrapper == "ivdecoder":
                    record.layout = f"{record.layout}_ivdecoder"
                return record
    return None


def _parse_c2s_fallback(body: bytes, header_len: int = 24) -> BusinessRecord | None:
    """c2s 兜底布局：body[4:6]==55aa，[6:8]==0，payload 自 header_len 起。

    仅用于保住数据（技能选择/自动指令），opcode 取 header 里的 u32，
    精确语义留给后续扩展。
    """
    if len(body) < header_len or body[4:6] != b"\x55\xaa" or body[6:8] != b"\x00\x00":
        return None
    opcode = 0
    payload = strip_tsf4g_padding(body[header_len:])
    if not payload:
        return None
    return BusinessRecord(
        direction="c2s",
        layout="c2s_55aa_fallback",
        opcode=opcode,
        opcode_hex="0x0000",
        payload=payload,
        transport_seq=int.from_bytes(body[0:4], "big"),
    )


def _parse_v14(body: bytes, direction: str) -> BusinessRecord | None:
    if len(body) < 0x1E or body[4:6] != b"\x55\xaa" or body[24:26] != b"\x39\x63":
        return None
    reserved = int.from_bytes(body[10:12], "big")
    version = int.from_bytes(body[12:16], "big")
    record_len = int.from_bytes(body[6:10], "big")
    raw_payload = body[30:]
    trailer_len = tsf4g_trailer_len(raw_payload)
    no_trailer_len = len(body) - trailer_len
    if reserved != 0 or version not in {0, 1} or record_len != no_trailer_len - 4:
        return None

    transport_seq = int.from_bytes(body[0:4], "big")
    session_id = int.from_bytes(body[16:20], "big")
    sub_id = int.from_bytes(body[20:24], "big")
    req_seq = int.from_bytes(body[26:30], "big")
    payload = strip_tsf4g_padding(raw_payload)

    if direction == "c2s":
        opcode, _ = normalize_c2s_opcode(sub_id)
    else:
        opcode = session_id & 0xFFFF

    return BusinessRecord(
        direction=direction,
        layout="tgcp_4013_v14",
        opcode=opcode,
        opcode_hex=f"0x{opcode:04X}",
        payload=payload,
        session_id=session_id,
        sub_id=sub_id,
        req_seq=req_seq,
        transport_seq=transport_seq,
    )


def _parse_live_s2c(body: bytes, direction: str) -> BusinessRecord | None:
    if direction != "s2c" or len(body) < 10 or body[4:6] != b"\x55\xaa":
        return None
    opcode = int.from_bytes(body[0:4], "big")
    if not (0 < opcode <= 0xFFFF):
        return None
    subtype = int.from_bytes(body[6:10], "big")
    payload = strip_tsf4g_padding(body[10:])
    return BusinessRecord(
        direction=direction,
        layout="tgcp_4013_live_s2c",
        opcode=opcode,
        opcode_hex=f"0x{opcode:04X}",
        payload=payload,
        sub_id=subtype,
    )


def _parse_live_c2s(body: bytes, direction: str) -> BusinessRecord | None:
    if direction != "c2s" or len(body) < 14 or body[8:10] != b"\x39\x63":
        return None
    raw_opcode = int.from_bytes(body[4:8], "big")
    if raw_opcode <= 0 or (raw_opcode >> 16) not in {0x0000, 0x0001} or (raw_opcode & 0xFFFF) == 0:
        return None
    opcode, _ = normalize_c2s_opcode(raw_opcode)
    req_seq = int.from_bytes(body[10:14], "big")
    payload = strip_tsf4g_padding(body[14:])
    return BusinessRecord(
        direction=direction,
        layout="tgcp_4013_live_c2s",
        opcode=opcode,
        opcode_hex=f"0x{opcode:04X}",
        payload=payload,
        req_seq=req_seq,
    )


@dataclass
class BattleListener:
    """帧监听器：把 DecodedFrame 转成业务记录并落盘。

    on_record 会被传入每条业务记录的 dict（含 protobuf 树），
    GUI / AI 复盘层可据此订阅实时事件。
    """

    on_record: RecordCallback | None = None
    dump_dir: Path = field(default_factory=lambda: CAPTURE_DIR)
    dump_enabled: bool = True
    verbose: bool = True

    _file: Path | None = field(default=None, init=False)
    _frames: int = field(default=0, init=False)
    _records: int = field(default=0, init=False)
    _control_logged: int = field(default=0, init=False)

    # ---------------- 生命周期 ----------------

    def start(self, label: str = "") -> Path | None:
        if not self.dump_enabled:
            return None
        day = time.strftime("%Y%m%d")
        ts = time.strftime("%H%M%S")
        safe = "".join(ch for ch in label if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")[:16]
        d = self.dump_dir / day
        d.mkdir(parents=True, exist_ok=True)
        self._file = d / f"{ts}{('_' + safe) if safe else ''}_frames.jsonl"
        return self._file

    def close(self) -> None:
        self._file = None

    # ---------------- 帧入口（作为 PacketCaptureEngine.on_frame） ----------------

    def __call__(self, frame: DecodedFrame) -> None:
        self.handle(frame)

    def handle(self, frame: DecodedFrame) -> None:
        self._frames += 1

        if frame.cmd != tgcp.CMD_DATA:
            self._handle_control(frame)
            return
        if frame.plain_body is None:
            self._write({"t": frame.captured_at, "direction": frame.direction,
                         "event": "data_undecrypted", "status": frame.decrypt_status})
            return

        record = parse_business_body(frame.plain_body, frame.direction)
        if record is None:
            self._write({"t": frame.captured_at, "direction": frame.direction,
                         "event": "business_unparsed", "body_len": len(frame.plain_body),
                         "body_hex": frame.plain_body[:64].hex()})
            return

        self._records += 1
        rec = record.to_dict()
        rec["event"] = "business"
        self._write(rec)
        if self.on_record is not None:
            try:
                self.on_record(rec)
            except Exception as exc:
                self._write({"t": _now_text(), "event": "listener_error", "error": str(exc)})

    def _handle_control(self, frame: DecodedFrame) -> None:
        event = {"t": frame.captured_at, "direction": frame.direction,
                 "event": "control", "cmd_hex": f"0x{frame.cmd:04X}",
                 "cmd_name": frame.cmd_name, "seq": frame.seq}
        session_key = None
        if frame.cmd == tgcp.CMD_ACK and len(frame.header_extra) >= 18:
            session_key = frame.header_extra[2:18]
            event["session_key_hex"] = session_key.hex()
            event["session_key_ascii"] = tgcp.printable_ascii(session_key)
        self._write(event)
        if session_key is not None and self.verbose:
            self._control_logged += 1

    # ---------------- 落盘 ----------------

    def _write(self, obj: dict) -> None:
        if self._file is None:
            return
        try:
            with open(self._file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def summary(self) -> dict:
        return {"frames": self._frames, "records": self._records, "file": str(self._file) if self._file else ""}
