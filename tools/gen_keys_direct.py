# -*- coding: utf-8 -*-
"""直接生成 Ed25519 密钥对并写入 keys.json (不经过 stdout, 绕开脱敏干扰)"""
import json
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

KEYS = Path(r"D:\洛克王国ai\lkwgai_pvp_assistant\build\_hardened\keys.json")
keys = json.loads(KEYS.read_text(encoding="utf-8"))

priv = Ed25519PrivateKey.generate()
priv_pkcs8_hex = priv.private_bytes(
    serialization.Encoding.DER,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()).hex()
pub_raw_hex = priv.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw).hex()

keys["ed25519_private_pkcs8"] = priv_pkcs8_hex
keys["ed25519_public_raw"] = pub_raw_hex
KEYS.write_text(json.dumps(keys, indent=2), encoding="utf-8")
print("saved. pub_raw_len:", len(pub_raw_hex), "priv_pkcs8_len:", len(priv_pkcs8_hex))
