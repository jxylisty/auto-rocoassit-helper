# -*- coding: utf-8 -*-
"""
卡密验证核心逻辑 (Cython 编译为 .pyd, 机器码保护) · v2 加固版

包含最敏感的函数：
- get_hwid(): 机器码生成 (MAC + 主机名 + MachineGuid 多因子)
- _local_token(): 本地完整性签名
- status(): 登录态判定（核心安全逻辑, 含断网宽限上限）
- derive_key(): 由服务端下发的 seed 派生数据解密密钥 (PBKDF2, 不落盘)
- builtin_api_base(): 内置验证服务器地址 (不再放明文配置文件)
- builtin_pubkey(): 服务端 Ed25519 公钥锚点 (防假服务端, 私钥只在 Worker)

注意：
- 此文件编译成 .pyd 后，攻击者无法 dump 字节码
- 敏感常量以字节数组构造，避免在二进制里留下可 grep 的连续字符串
- 其他网络请求、JSON 操作等明文保留在 auth.py 中
"""

import hashlib
import time


def _bs(parts) -> bytes:
    return bytes(parts)


# 内置验证服务器地址 (字节数组拼装, 编译后不形成连续字符串)
# 2026-09-21: 迁移到自定义子域名 (Workers 的共享域名在国内被 DNS 污染,
# 自有域名走正常解析可达性高; 裸域留给用户其他业务, 旧地址保留为备用端点)
_BUILTIN_API_BASE = _bs([
    0x68, 0x74, 0x74, 0x70, 0x73, 0x3A, 0x2F, 0x2F,  # https://
    0x61, 0x75, 0x74, 0x68, 0x2E,  # auth.
    0x6D, 0x79, 0x31, 0x32, 0x33,  # my123
    0x2E, 0x62, 0x6F, 0x6E, 0x64,  # .bond
]).decode("ascii")

# 备用端点 (主端点连不上时依次尝试; 保持顺序 = 优先级)
# [0] = 旧的 workers.dev 地址 (绑定 Custom Domain 后可留作备用)
_BUILTIN_API_FALLBACKS = [
    "https://lucky-cell-cd0b.zzx051012-e82.workers.dev",
]

# 本地完整性盐 (配合 pyd 二进制不可读, 明文改 auth.json 的 expires_at 会对不上 token)
_LOCAL_SALT = _bs([0x4C, 0x4B, 0x57, 0x23, 0x76, 0x32, 0x23]) + _bs([
    0x61, 0x37, 0x66, 0x33, 0x64, 0x39, 0x63, 0x31, 0x65, 0x35, 0x62, 0x32,
])

# 数据密钥派生盐 (seed 由服务端在 activate/verify 响应中下发, 不落盘)
_DATA_KDF_SALT = _bs([
    0x4C, 0x4B, 0x57, 0x2D, 0x44, 0x41, 0x54, 0x41, 0x2D, 0x76, 0x31,
])

# 服务端 Ed25519 公钥 (公开锚点, 由 tools/build_hardened.py 部署后自动填入;
# 为空表示尚未启用 Ed25519 验签, 退化为通道 HMAC)
_ED25519_PUB_HEX = "4c3ede8647f625380a6ad7b07dc63655fe8f55d4eb32e483f2991462f85c0645"


def builtin_api_base() -> str:
    """内置验证服务器主地址"""
    return _BUILTIN_API_BASE


def builtin_api_fallbacks() -> list:
    """备用验证服务器列表 (主地址网络失败时依次尝试)"""
    return list(_BUILTIN_API_FALLBACKS)


def builtin_pubkey() -> str:
    """服务端 Ed25519 公钥 hex (空串 = 未启用)"""
    return _ED25519_PUB_HEX


def get_hwid() -> str:
    """机器码: MAC(uuid.getnode) + 主机名 + Windows MachineGuid 哈希。
    MachineGuid 来自注册表 HKLM\\SOFTWARE\\Microsoft\\Cryptography, 重装系统才变;
    改 MAC / 改主机名 / 虚拟机克隆都不再能"换机"。任一因子缺失自动降级。"""
    import socket
    import uuid
    parts = []
    try:
        parts.append(str(uuid.getnode()))
    except Exception:
        pass
    try:
        parts.append(socket.gethostname())
    except Exception:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            parts.append(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:
        pass
    if not parts:  # 兜底: 理论不可达
        parts = ["lkw-fallback"]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _local_token(hwid: str, expires_at: int, code: str) -> str:
    """生成本地完整性签名，防手改 auth.json"""
    payload = f"{hwid}|{int(expires_at or 0)}|{code}"
    return hashlib.sha256((_LOCAL_SALT + payload.encode("utf-8"))).hexdigest()


def derive_key(seed: str) -> bytes:
    """由服务端下发的 seed 派生 32 字节数据解密密钥 (PBKDF2-HMAC-SHA256)。
    seed 只存在于内存, 不写任何文件; 与 seadata 的实现约定一致。"""
    if not seed:
        return b""
    return hashlib.pbkdf2_hmac("sha256", str(seed).encode("utf-8"),
                               _DATA_KDF_SALT, 200_000, dklen=32)


def wrap_cache_seed(seed: str, hwid: str) -> str:
    """把 seed 混淆后写入 auth.json (seed_cache 字段)。
    密钥流由 本地盐+hwid 派生: 整目录拷到别的机器后无法还原 seed
    (hwid 因子含目标机器没有的 MachineGuid), 防文件夹直传分享;
    本机攻击者可还原, 属于已知残余风险 (见安全评估报告)。"""
    if not seed:
        return ""
    raw = str(seed).encode("utf-8")
    ks = hashlib.sha256(_LOCAL_SALT + b"cache|" + str(hwid).encode("utf-8")).digest()
    out = bytes(b ^ ks[i % len(ks)] for i, b in enumerate(raw))
    return out.hex()


def unwrap_cache_seed(wrapped: str, hwid: str) -> str:
    """还原 wrap_cache_seed 的 seed; 任何异常返回空串"""
    try:
        raw = bytes.fromhex(str(wrapped or ""))
        if not raw:
            return ""
        ks = hashlib.sha256(_LOCAL_SALT + b"cache|" + str(hwid).encode("utf-8")).digest()
        out = bytes(b ^ ks[i % len(ks)] for i, b in enumerate(raw))
        return out.decode("utf-8")
    except Exception:
        return ""


def status(hwid: str, code: str, token: str, expires_at, local_sig: str,
           last_verify=0) -> dict:
    """登录态判定 (纯本地，毫秒级):
    authorized: 已激活且未过期 (离线宽限在此，不发网络请求)
    过期/未激活：unauthorized; 开发者模式由 bridge 层另行放行

    断网宽限上限: last_verify 距今超过 7 天, 即使 token 本地未过期也判 unauthorized
    (防止"激活一次 + 永久断网 = 永久可用"; 重新联网校验后自动恢复)。

    参数:
        hwid: 机器码
        code: 卡密
        token: 服务端下发的 token
        expires_at: 到期时间戳 (毫秒)
        local_sig: 本地完整性签名
        last_verify: 上次与云端校验成功的时间戳 (毫秒), 0 = 从未校验过

    返回:
        {"ok": True, "authorized": bool, ...}
    """
    has_token = bool(code and token)
    expires = int(expires_at or 0)

    # 本地完整性：expires_at/code 被手改时 local_sig 对不上，按未激活处理
    if has_token and local_sig != _local_token(hwid, expires, code):
        return {"ok": True, "authorized": False, "reason": "tampered"}

    if has_token and time.time() * 1000 < expires:
        # 断网宽限上限 (7 天): 从未成功校验过(last_verify=0)时给 30 分钟窗口,
        # 覆盖"首次激活后立即离线使用"的合理场景
        lv = int(last_verify or 0)
        limit = (30 * 60 * 1000) if lv == 0 else (7 * 86400 * 1000)
        if time.time() * 1000 - lv > limit:
            return {"ok": True, "authorized": False, "reason": "grace_expired",
                    "expires_at": expires}

        return {"ok": True, "authorized": True, "code": code,
                "nickname": "",  # 昵称由外部传入或后续填充
                "expires_at": expires,
                "days_left": max(0, (expires - time.time() * 1000) // 86400000)}

    return {"ok": True, "authorized": False,
            "reason": "expired" if has_token else "none",
            "expires_at": expires}
