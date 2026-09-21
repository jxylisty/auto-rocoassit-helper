# -*- coding: utf-8 -*-
"""卡密激活验证客户端 · v2 加固版 (配合 server/worker.js 的 Cloudflare Workers 服务端)

流程：激活 (绑机, 发 token+seed) → 本地存 auth.json (不含明文 seed) → 启动静默校验。
安全：
  - token = HMAC-SHA256(机器码|到期时间, 服务端盐), 客户端不可伪造;
  - 服务端响应带 Ed25519 签名 (私钥只在 Worker, 公钥锚定在 auth_core.pyd),
    假服务端/中间人无法伪造合法响应 —— api_base 已内置进 pyd, 不再读明文配置;
  - 断网宽限: 本地 token 未过期即放行, 但有 7 天上限 (auth_core.status);
  - seed (核心数据解密种子) 只存内存; auth.json 里存的是与本机 hwid 绑定的
    混淆缓存 (seed_cache), 整目录拷到别的机器无法还原。
存储：data/config/auth.json(受 updater PROTECTED_PREFIXES 保护，不被自动更新覆盖)。

核心鉴权逻辑已编译为 auth_core.pyd(Cython 机器码保护)，此处仅做接口封装。
"""
import base64
import hashlib
import hmac as _hmac_mod
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTH_FILE = PROJECT_ROOT / "data" / "config" / "auth.json"

DEFAULTS = {
    "code": "",               # 已激活的卡密
    "token": "",
    "hwid": "",
    "expires_at": 0,          # 毫秒时间戳
    "nickname": "",
    "last_verify": 0,
    "local_sig": "",          # 本地完整性签名 (hwid|expires_at|code), 防手改 auth.json
    "seed_cache": "",         # seed 的本机绑定混淆缓存 (非明文)
}

# 兼容旧版字段: 读取时忽略, 保存时剔除
_LEGACY_KEYS = ("api_base",)


# ========================================
# 导入 Cython 编译的核心模块 (.pyd)
# ========================================
try:
    from . import auth_core  # noqa: F401
except ImportError:
    # 开发环境：如果没有 .pyd，尝试用 .py fallback
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "src" / "gui"))
    import auth_core as _auth_core_fallback

    get_hwid = _auth_core_fallback.get_hwid
    _local_token = _auth_core_fallback._local_token
    _core_status = _auth_core_fallback.status
    derive_key = _auth_core_fallback.derive_key
    builtin_api_base = _auth_core_fallback.builtin_api_base
    builtin_pubkey = _auth_core_fallback.builtin_pubkey
    wrap_cache_seed = _auth_core_fallback.wrap_cache_seed
    unwrap_cache_seed = _auth_core_fallback.unwrap_cache_seed
else:
    # 打包环境：使用 .pyd 机器码版本
    get_hwid = auth_core.get_hwid
    _local_token = auth_core._local_token
    _core_status = auth_core.status
    derive_key = auth_core.derive_key
    builtin_api_base = auth_core.builtin_api_base
    builtin_pubkey = auth_core.builtin_pubkey
    wrap_cache_seed = auth_core.wrap_cache_seed
    unwrap_cache_seed = auth_core.unwrap_cache_seed


# ----------------------------------------
# seed (核心数据解密种子) 管理: 只存内存 + 本机绑定缓存
# ----------------------------------------
_SEED_MEM: str | None = None


def _boot_key() -> None:
    """启动时尽力恢复数据密钥: seed_cache(本机绑定) → 注入 seadata。
    失败静默 (未激活/新机器属正常状态, 激活或联网校验后自动恢复)。"""
    global _SEED_MEM
    if _SEED_MEM is not None:
        return
    try:
        st = load_state()
        wrapped = st.get("seed_cache") or ""
        if not wrapped:
            return
        seed = unwrap_cache_seed(wrapped, st.get("hwid") or "")
        if seed:
            _SEED_MEM = seed
            from src.pvp import seadata
            seadata.set_key_from_seed(seed)
    except Exception:
        pass


def _apply_seed(seed: str, st: dict) -> None:
    """收到新 seed: 注入内存 + seadata, 并写本机绑定缓存"""
    global _SEED_MEM
    if not seed:
        return
    _SEED_MEM = seed
    try:
        from src.pvp import seadata
        seadata.set_key_from_seed(seed)
        st["seed_cache"] = wrap_cache_seed(seed, st.get("hwid") or "")
    except Exception:
        pass


def seed_ready() -> bool:
    """核心数据密钥是否已就绪"""
    try:
        from src.pvp import seadata
        return seadata.is_ready()
    except Exception:
        return False


# ----------------------------------------
# 服务端响应验签: Ed25519 (优先) → 通道 HMAC (兼容旧 Worker)
# ----------------------------------------
def _check_sig(resp: dict, base: str) -> bool:
    """校验服务端响应签名。
    Ed25519: sig = base64(sign(privkey, sha256(原始JSON体))); 公钥锚定在 pyd。
    通道 HMAC (旧协议): sig = HMAC-SHA256(原始JSON体, sha256("#LKW-CH#"+origin))。
    两种格式按公钥是否配置自动选择。"""
    sig = resp.get("sig")
    if not sig:
        return False
    body = {k: v for k, v in resp.items() if k != "sig"}
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    msg = hashlib.sha256(raw.encode("utf-8")).digest()

    pub_hex = ""
    try:
        pub_hex = builtin_pubkey() or ""
    except Exception:
        pub_hex = ""
    if pub_hex:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey)
            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
            pub.verify(base64.b64decode(str(sig)), msg)
            return True
        except Exception:
            return False

    # ---- 兼容: 通道 HMAC (仅过渡期; api_base 已内置, 攻击面大幅收窄) ----
    import hmac as _h
    from urllib.parse import urlparse
    pu = urlparse(base)
    origin = f"{pu.scheme}://{pu.netloc}" if pu.scheme else base
    salt = _h.sha256(("#LKW-CH#" + origin).encode()).hexdigest()
    expect = _hmac_mod.new(salt.encode(), raw.encode(), "sha256").hexdigest()
    return _hmac.compare_digest(expect, str(sig))


def _api(st: dict, path: str, payload: dict) -> dict:
    """调 Worker 接口; 返回 {ok, ...} 或 {ok:False, message, network:True}。
    带 sig 的响应先验签 (activate/verify), 无签名的接口 (admin/deactivate) 跳过。
    多端点回退: 主地址网络失败时依次尝试备用地址 (应对国内 DNS 污染波动)。"""
    bases = [builtin_api_base()]
    try:
        for fb in builtin_api_fallbacks():
            if fb and fb not in bases:
                bases.append(fb)
    except Exception:
        pass
    # 用户配置的 api_base 保留为最后回退 (兼容旧安装)
    cfg_base = (st.get("api_base") or "").rstrip("/")
    if cfg_base and cfg_base not in bases:
        bases.append(cfg_base)

    import requests
    last_err = ""
    for base in bases:
        try:
            r = requests.post(f"{base}{path}", json=payload, timeout=8,
                              headers={"User-Agent": "LKW-Assistant/2.1"})
            data = r.json()
            if not isinstance(data, dict):
                last_err = "响应格式异常"
                continue
            if "sig" in data and not _check_sig(data, base):
                # 每个端点独立验签 (origin 不同盐不同), 验签失败视为非法端点, 不再回退
                return {"ok": False, "message": "响应签名校验失败 (非法服务端)", "network": True}
            return data
        except Exception as e:
            last_err = f"网络错误：{e}"
            continue
    return {"ok": False, "message": last_err or "所有验证服务器均不可达", "network": True}


def load_state() -> dict:
    st = dict(DEFAULTS)
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            st.update({k: v for k, v in data.items() if k in DEFAULTS})
    except Exception:
        pass
    if not st.get("hwid"):
        st["hwid"] = get_hwid()
        save_state(st)
    return st


def save_state(st: dict):
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    out = {k: v for k, v in st.items() if k not in _LEGACY_KEYS}
    AUTH_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def activate(code: str) -> dict:
    """激活卡密 (绑定本机) → 成功返回 {ok, nickname, expires_at}"""
    st = load_state()
    code = (code or "").strip().upper()
    if not code:
        return {"ok": False, "message": "请输入卡密"}
    res = _api(st, "/activate", {"code": code, "hwid": st["hwid"]})
    if res.get("network"):
        return {"ok": False,
                "message": res["message"] + " — 请检查网络后重试"}
    if not res.get("ok"):
        return {"ok": False, "message": res.get("message", "激活失败")}
    st.update({
        "code": code, "token": res.get("token", ""),
        "expires_at": int(res.get("expires_at", 0)),
        "nickname": res.get("nickname", ""),
        "last_verify": int(time.time() * 1000),
    })
    st["local_sig"] = _local_token(st["hwid"], st["expires_at"], code)
    _apply_seed(str(res.get("seed", "")), st)
    save_state(st)
    return {"ok": True, "nickname": st["nickname"], "expires_at": st["expires_at"]}


def status() -> dict:
    """登录态判定包装函数 (调用 .pyd 核心逻辑)"""
    st = load_state()
    result = _core_status(st["hwid"], st["code"], st["token"], st["expires_at"],
                          st["local_sig"], st.get("last_verify") or 0)
    if result.get("authorized") and not result.get("nickname"):
        result["nickname"] = st.get("nickname") or f"训练家_{st['code'][-4:]}"
    return result


def verify_remote() -> dict:
    """启动静默校验 (打服务端确认卡密没被吊销/过期, 并刷新 seed)。
    网络不通时按本地状态宽限放行; 明确被吊销则拒绝"""
    st = load_state()
    local = status()
    if not local.get("authorized"):
        return {**local, "remote": False}
    res = _api(st, "/verify", {"code": st["code"], "hwid": st["hwid"],
                               "token": st["token"]})
    st["last_verify"] = int(time.time() * 1000)
    if res.get("network"):
        save_state(st)  # 断网：宽限，保留本地登录态
        return {**local, "remote": False, "grace": True}
    if res.get("ok"):
        st["expires_at"] = int(res.get("expires_at", st["expires_at"]))
        st["nickname"] = res.get("nickname", st["nickname"])
        st["local_sig"] = _local_token(st["hwid"], st["expires_at"], st["code"])
        _apply_seed(str(res.get("seed", "")), st)
        save_state(st)
        return {"ok": True, "authorized": True, "code": st["code"],
                "nickname": st["nickname"], "expires_at": st["expires_at"],
                "remote": True}
    # 服务端明确拒绝 (吊销/过期/不匹配): 清掉本地登录态与数据密钥缓存
    if "吊销" in str(res.get("message", "")):
        st.update({"code": "", "token": "", "expires_at": 0, "nickname": "",
                   "seed_cache": ""})
        global _SEED_MEM
        _SEED_MEM = None
        try:
            from src.pvp import seadata
            seadata.set_key(b"")
        except Exception:
            pass
        save_state(st)
        return {"ok": True, "authorized": False, "reason": "revoked", "remote": True}
    if "过期" in str(res.get("message", "")):
        save_state(st)
        return {"ok": True, "authorized": False, "reason": "expired", "remote": True}
    save_state(st)
    return {"ok": True, "authorized": False, "reason": "invalid", "remote": True,
            "message": res.get("message")}


def deactivate(admin_key: str = "") -> dict:
    """换机解绑：清本地 + 请求服务端解绑 (72h 冷却，管理员免限)"""
    st = load_state()
    if st.get("code"):
        _api(st, "/deactivate", {"code": st["code"], "admin_key": admin_key})
    st.update({"code": "", "token": "", "expires_at": 0, "nickname": "",
               "local_sig": "", "seed_cache": ""})
    save_state(st)
    return {"ok": True}


# ========================================
# 后台静默校验线程 (bridge.start_auth_verify 的实现)
# ========================================
class AuthVerifier:
    """周期性向云端确认授权状态:
    - 首次延迟 25s, 之后每 30 分钟一次 (与断网宽限的 7 天上限配合)
    - 被吊销/过期时通知 bridge 停任务并弹提示
    """
    def __init__(self, on_log=None, on_denied=None,
                 first_delay: float = 25.0, interval: float = 1800.0):
        self._on_log = on_log or (lambda *a, **k: None)
        self._on_denied = on_denied
        self._first_delay = first_delay
        self._interval = interval
        self._stop = None
        self._thread = None

    def start(self):
        import threading
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="AuthVerifier")
        self._thread.start()

    def stop(self):
        if self._stop:
            self._stop.set()

    def _loop(self):
        self._stop.wait(self._first_delay)
        while not self._stop.is_set():
            try:
                r = verify_remote()
                if not r.get("ok"):
                    self._on_log(f"卡密校验异常: {r.get('message', '未知错误')}", "warning")
                elif not r.get("authorized"):
                    reason = r.get("reason", "invalid")
                    if reason == "grace_expired":
                        pass  # status() 已在本地拦截, 不重复打扰
                    else:
                        self._on_log(f"卡密已{ {'revoked': '吊销', 'expired': '过期'}.get(reason, '失效') }，功能已停用",
                                     "warning")
                        if self._on_denied:
                            try:
                                self._on_denied(reason)
                            except Exception:
                                pass
            except Exception as e:
                self._on_log(f"卡密校验失败: {e}", "warning")
            self._stop.wait(self._interval)


# 启动时尽力恢复数据密钥 (静默)
try:
    _boot_key()
except Exception:
    pass
