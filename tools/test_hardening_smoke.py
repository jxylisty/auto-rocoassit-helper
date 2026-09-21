# -*- coding: utf-8 -*-
"""加固链路冒烟测试 (开发环境, auth_core 以 .py 形态)"""
import sys
from pathlib import Path
sys.path.insert(0, r"D:\洛克王国ai\lkwgai_pvp_assistant")

# 1) auth_core 逻辑
from src.gui import auth_core
hwid = auth_core.get_hwid()
print("hwid:", hwid[:16], "len:", len(hwid))
tok = auth_core._local_token(hwid, 123, "X")
assert len(tok) == 64
key = auth_core.derive_key("TEST-SEED-123")
assert len(key) == 32
print("api_base:", auth_core.builtin_api_base())

# status 全场景 (last_verify 取真实当前时间, 模拟"刚校验过")
now_ms = int(__import__("time").time() * 1000)
ok_sig = auth_core._local_token(hwid, 9999999999999, "CODE")
st = auth_core.status(hwid, "CODE", "tok", 9999999999999, ok_sig, now_ms)
assert st["authorized"] is True, st
st2 = auth_core.status(hwid, "CODE", "tok", 9999999999999, "badsig", now_ms)
assert st2["authorized"] is False and st2["reason"] == "tampered", st2
st3 = auth_core.status(hwid, "CODE", "tok", 9999999999999, ok_sig, 1)
assert st3["authorized"] is False and st3["reason"] == "grace_expired", st3
st4 = auth_core.status(hwid, "", "", 0, "", 0)
assert st4["authorized"] is False and st4["reason"] == "none", st4

# seed_cache 本机绑定
w = auth_core.wrap_cache_seed("TEST-SEED-123", hwid)
assert auth_core.unwrap_cache_seed(w, hwid) == "TEST-SEED-123"
assert auth_core.unwrap_cache_seed(w, "other") != "TEST-SEED-123"
print("auth_core OK")

# 2) seadata 加解密往返
from src.pvp import seadata
blob = seadata.encrypt_bytes(key, b'{"hello": "world", "n": 123}', b"ctx")
assert blob[:7] == b"LKWSD01"
pt = seadata.decrypt_bytes(key, blob, b"ctx")
assert pt == b'{"hello": "world", "n": 123}'
try:
    seadata.decrypt_bytes(auth_core.derive_key("WRONG"), blob, b"ctx")
    raise SystemExit("错误密钥未被拒绝")
except seadata.SeadataError:
    print("错误密钥正确拒绝")
try:
    seadata.decrypt_bytes(key, blob, b"other-ctx")
    raise SystemExit("错误 context 未被拒绝")
except seadata.SeadataError:
    print("错误 context 正确拒绝")
print("seadata OK")

# 3) dist 语义 (临时目录, 只有 .bin): 未授权必须拒绝, 授权后可读
from src.pvp import pet_loader, skill_loader, type_chart, pvp_rules
import tempfile, shutil as _sh

_tmp = Path(tempfile.mkdtemp(prefix="lkw_seadata_"))
_orig_dir = seadata.DATA_DIR
try:
    blob_real = seadata.encrypt_bytes(key, b'{"k": "v", "big": [1,2,3]}', b"t_sealed")
    (_tmp / "t_sealed.bin").write_bytes(blob_real)
    (_tmp / "t_open.json").write_text('{"open": true}', encoding="utf-8")
    seadata.DATA_DIR = _tmp
    seadata.set_key(b"")          # 清空密钥
    try:
        seadata.load("t_sealed")
        raise SystemExit("dist 语义失败: 未授权却读到了密封数据")
    except seadata.SeadataError:
        pass
    assert seadata.load("t_open") == {"open": True}   # 公开数据明文可读
    seadata.set_key(key)          # 注入密钥
    assert seadata.load("t_sealed")["k"] == "v"       # 授权后可读
finally:
    seadata.DATA_DIR = _orig_dir
    _sh.rmtree(_tmp, ignore_errors=True)
    seadata.set_key(b"")   # 恢复未注入状态 (TEST 密钥解不了真实密封数据, 不能留着)

# 4) 重载链: 仓库处于 .bin 密封态时必须用真实 data_seed 触发重载
#    (明文 .json 开发态则任意密钥都能跑, 此处优先真实 seed, 两种状态都兼容)
import json as _json
_keys_file = Path(__file__).resolve().parents[1] / "build" / "_hardened" / "keys.json"
if _keys_file.exists():
    _real_seed = _json.loads(_keys_file.read_text(encoding="utf-8"))["data_seed"]
    seadata.set_key_from_seed(_real_seed)   # 注入真实密钥并自动触发全部重载
else:
    print("(未找到 keys.json: 假定开发明文态, 校验直读数据)")

# 4) 重载链: pet_loader/skill_loader 注册了重载, set_key 后自动重建数据+派生索引
assert len(pet_loader._PET_DETAIL) > 100, f"重载后 pet_detail 异常: {len(pet_loader._PET_DETAIL)}"
assert len(pet_loader._PET_SKILLS) > 100
assert len(skill_loader._SKILLS) > 100
assert pet_loader.get_pet_count() > 100
assert len(pet_loader._TITLE_TO_FORM) > 100
assert len(pet_loader._FINAL_ALLOWED) > 50
assert type_chart._CHART
assert pvp_rules.PVP_RULES
print("data loaders OK (重载后 pets=", len(pet_loader._PET_DETAIL),
      "titles=", len(pet_loader._TITLE_TO_FORM),
      "skills=", len(skill_loader._SKILLS), ")")

# 5) auth.py 完整链 (不触网)
from src.gui import auth
s = auth.status()
assert "authorized" in s
print("auth.status:", {k: s[k] for k in ("ok", "authorized", "reason") if k in s})
print("seed_ready:", auth.seed_ready())
print("ALL_SMOKE_OK")
