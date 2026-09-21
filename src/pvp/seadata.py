# -*- coding: utf-8 -*-
"""seadata — 核心数据加密加载器 (P0 加固: 资产与授权绑定)

数据在分发包中以 .bin 形态存在 (seal_assets.py 产出):
    blob = MAGIC(7B) | tag(hex 64B) | ciphertext
    ciphertext = plaintext XOR keystream(sha256(key_enc || counter))
    tag        = HMAC-SHA256(key_mac, "LKW-TAG" || context || ciphertext)
    key        = auth_core.derive_key(seed)  (32B, seed 由服务端下发, 不落盘)

设计:
  - 密封清单内的数据 (核心竞技数据): 授权后才能读; patch 掉提示也拿不到明文
  - 公开数据 (克制表/规则等游戏常识): 保持明文, 不增加无谓复杂度
  - 数据 loader 在 import 时通过 register_reload 注册重载函数;
    set_key() 注入密钥后自动触发重载 → 新用户首次激活后数据即时可用, 无需重启
  - 密钥未就绪时 import 永不失败 (loader 先空载启动), 引擎启动由门禁拦截

开发环境: 仓库里是明文 .json (seal_assets.py --unseal 可恢复), 全部直读。
纯标准库实现, 不引入第三方依赖。
"""
import hashlib
import hmac
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

MAGIC = b"LKWSD01"
_TAG_LEN = 64
_PREFIX_ENC = b"LKW-ENC"
_PREFIX_TAG = b"LKW-TAG"


class SeadataError(RuntimeError):
    """数据加载/解密失败 (密钥未就绪、密钥错误或数据被篡改)"""


_KEY = None  # bytes[32] | None

# 重载注册表: 数据 loader 在 import 时注册自己的重载函数;
# set_key() 后自动触发全部重载 → 授权成功后数据即时可用
_RELOADERS = []


def register_reload(fn) -> None:
    """注册数据重载函数 (密钥注入后被自动调用)"""
    if fn not in _RELOADERS:
        _RELOADERS.append(fn)


def _run_reloaders() -> None:
    for fn in list(_RELOADERS):
        try:
            fn()
        except Exception:
            pass


def set_key(key_32) -> None:
    """注入 32 字节解密密钥 (由 auth_core.derive_key(seed) 产生);
    传空/None 清除密钥。密钥变化后自动触发已注册的数据重载。"""
    global _KEY
    if key_32 and len(key_32) != 32:
        raise ValueError("data key must be 32 bytes")
    _KEY = bytes(key_32) if key_32 else None
    _run_reloaders()


def set_key_from_seed(seed: str) -> None:
    """由服务端下发的 seed 直接派生并注入密钥"""
    try:
        from src.gui import auth_core
        set_key(auth_core.derive_key(seed))
    except Exception as e:  # pragma: no cover
        raise SeadataError(f"密钥派生失败: {e}")


def is_ready() -> bool:
    """密钥是否已注入 (与 has_sealed_data 配合做引擎门禁)"""
    return _KEY is not None


def has_sealed(name: str) -> bool:
    return (DATA_DIR / f"{name}.bin").exists()


def has_plain(name: str) -> bool:
    return (DATA_DIR / f"{name}.json").exists()


def has_sealed_data() -> bool:
    """分发包内是否存在加密数据 (有密封数据时引擎门禁才要求密钥)"""
    try:
        return any(DATA_DIR.glob("*.bin"))
    except Exception:
        return False


# ---------------- 加解密原语 ----------------

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


def encrypt_bytes(key: bytes, plaintext: bytes, context: bytes = b"") -> bytes:
    if not key or len(key) != 32:
        raise ValueError("need 32-byte key")
    ct = _xor(plaintext, _keystream(key[:16], len(plaintext)))
    tag = hmac.new(key[16:], _PREFIX_TAG + context + ct, hashlib.sha256).hexdigest()
    return MAGIC + tag.encode("ascii") + ct


def decrypt_bytes(key: bytes, blob: bytes, context: bytes = b"") -> bytes:
    if not key or len(key) != 32:
        raise SeadataError("解密密钥未就绪 (未授权?)")
    if blob[:len(MAGIC)] != MAGIC:
        raise SeadataError("数据格式错误")
    tag = blob[len(MAGIC):len(MAGIC) + _TAG_LEN].decode("ascii", "ignore")
    ct = blob[len(MAGIC) + _TAG_LEN:]
    expect = hmac.new(key[16:], _PREFIX_TAG + context + ct, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(tag, expect):
        raise SeadataError("数据校验失败 (密钥错误或数据被篡改)")
    return _xor(ct, _keystream(key[:16], len(ct)))


def decrypt_json(key: bytes, blob: bytes, context: bytes = b""):
    return json.loads(decrypt_bytes(key, blob, context).decode("utf-8"))


# ---------------- 统一加载入口 ----------------

def load(name: str):
    """加载核心数据:
    - 已密封且密钥就绪 → 解密 .bin (防明文旁路)
    - 未密封 (公开数据) → 直读明文 .json
    - 已密封但密钥未就绪 → SeadataError (引擎门禁拦截, 提示联网授权)
    """
    if _KEY is not None and has_sealed(name):
        blob = (DATA_DIR / f"{name}.bin").read_bytes()
        return decrypt_json(_KEY, blob, name.encode("utf-8"))
    p = DATA_DIR / f"{name}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    if has_sealed(name):
        raise SeadataError(f"核心数据 {name} 未就绪: 请联网启动一次以完成授权")
    raise FileNotFoundError(f"数据文件缺失: {name} (.json/.bin 均不存在)")


def load_optional(name: str, default=None):
    """同 load, 但数据不可用时返回 default (用于可选数据文件)"""
    try:
        return load(name)
    except (FileNotFoundError, SeadataError):
        return default
