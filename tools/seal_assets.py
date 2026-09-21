# -*- coding: utf-8 -*-
"""seal_assets.py — 把核心数据 JSON 加密为 .bin (P0 加固: 资产与授权绑定)

用法:
    python tools/seal_assets.py --seed <64位hex或任意字符串>

行为:
    src/pvp/data/*.json (加密清单内) → 同名 .bin, 并删除源 .json
    已存在 .bin 时跳过 (除非 --force)
    未在清单内的 .json (如 pet_index.json 若被移出清单) 保持明文

加密方案 (与 src/pvp/seadata.py 严格对应):
    key  = PBKDF2-HMAC-SHA256(seed, "LKW-DATA-v1", 200000, 32)
    blob = MAGIC(7B) | HMAC-SHA256(key[16:], "LKW-TAG"+name+ct) hex(64B) | ct
    ct   = plaintext XOR keystream(sha256(key[:16] || counter_u64be))

密钥轮换: 换 seed → 重跑本工具 → 重新分发包 (seed 不落盘, 分发包里只有密文)。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "src" / "pvp" / "data"

# 参与加密的数据文件 (不含扩展名) —— 核心竞技数据, 真正的资产价值所在。
# 公开游戏常识 (type_chart/pet_types/pvp_rules/pvp_rules) 保持明文, 不参与密封。
SEALED_NAMES = [
    "pet_skills",       # 2.4 MB 全精灵技能映射 (自整理)
    "pet_detail",       # 精灵详细数据 (自整理)
    "pet_index",        # 图鉴索引 (含 uiTag 形态分级)
    "skills",           # 技能表 (自整理)
    "skills_with_tags", # 技能行为标签 (自整理)
    "pet_race_speed",   # 种族速度表 (自整理)
    "leader_forms",     # 首领形态名单
]

MAGIC = b"LKWSD01"
_TAG_LEN = 64
_PREFIX_TAG = b"LKW-TAG"


def derive_key(seed: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", str(seed).encode("utf-8"),
                               b"LKW-DATA-v1", 200_000, dklen=32)


def _keystream(key_enc: bytes, n: int) -> bytes:
    blocks = []
    total = 0
    counter = 0
    while total < n:
        blk = hashlib.sha256(key_enc + counter.to_bytes(8, "big")).digest()
        blocks.append(blk)
        total += len(blk)
        counter += 1
    return b"".join(blocks)[:n]


def _xor(a: bytes, b: bytes) -> bytes:
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")


def seal_file(path_json: Path, key: bytes, force: bool) -> str:
    name = path_json.stem
    out_bin = path_json.with_suffix(".bin")
    if out_bin.exists() and not force:
        return "skip(bin exists)"
    plaintext = path_json.read_bytes()
    ct = _xor(plaintext, _keystream(key[:16], len(plaintext)))
    tag = hmac.new(key[16:], _PREFIX_TAG + name.encode("utf-8") + ct,
                   hashlib.sha256).hexdigest()
    blob = MAGIC + tag.encode("ascii") + ct
    out_bin.write_bytes(blob)
    path_json.unlink()  # 加密后删除明文 (防分发包带明文)
    return f"sealed({len(plaintext):,} B → {len(blob):,} B)"


def unseal_file(path_bin: Path, key: bytes) -> str:
    """开发用: 把 .bin 解回 .json (恢复明文开发环境)"""
    name = path_bin.stem
    blob = path_bin.read_bytes()
    if blob[:len(MAGIC)] != MAGIC:
        return "not-sealed"
    tag = blob[len(MAGIC):len(MAGIC) + _TAG_LEN].decode("ascii", "ignore")
    ct = blob[len(MAGIC) + _TAG_LEN:]
    expect = hmac.new(key[16:], _PREFIX_TAG + name.encode("utf-8") + ct,
                      hashlib.sha256).hexdigest()
    if not hmac.compare_digest(tag, expect):
        return "BAD TAG (seed 不对?)"
    pt = _xor(ct, _keystream(key[:16], len(ct)))
    (path_bin.parent / f"{name}.json").write_bytes(pt)
    path_bin.unlink()
    return f"unsealed({len(pt):,} B)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True, help="数据解密种子 (与 Worker DATA_SEED 一致)")
    ap.add_argument("--force", action="store_true", help="已存在 .bin 也重新加密")
    ap.add_argument("--unseal", action="store_true", help="开发用: .bin 解回 .json (恢复明文开发环境)")
    ap.add_argument("--names", nargs="*", help="只处理指定名称 (默认全部清单)")
    args = ap.parse_args()

    key = derive_key(args.seed)
    names = args.names or SEALED_NAMES

    if args.unseal:
        print(f"解密 {len(names)} 个数据文件 → {DATA_DIR} (仅开发用, 打包前必须重新 seal)")
        for name in names:
            src = DATA_DIR / f"{name}.bin"
            if not src.exists():
                print(f"  - {name}: 无 .bin (跳过)")
                continue
            print(f"  ✓ {name}: {unseal_file(src, key)}")
        return

    print(f"加密 {len(names)} 个核心数据文件 → {DATA_DIR}")
    done, missing = 0, []
    for name in names:
        src = DATA_DIR / f"{name}.json"
        if not src.exists():
            if (DATA_DIR / f"{name}.bin").exists():
                print(f"  - {name}: 已是 .bin (跳过)")
                continue
            missing.append(name)
            print(f"  ! {name}: 源 .json 不存在 (略)")
            continue
        status = seal_file(src, key, args.force)
        done += 1
        print(f"  ✓ {name}: {status}")

    if missing:
        print(f"\n⚠ {len(missing)} 个文件未找到: {', '.join(missing)}")
    print(f"\n用法提示:\n  加密打包前:  python tools/seal_assets.py --seed <seed>\n  恢复开发明文: python tools/seal_assets.py --seed <seed> --unseal\n")


if __name__ == "__main__":
    main()
