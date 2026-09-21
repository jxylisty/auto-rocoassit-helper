/**
 * 洛克王国助手 · 卡密激活验证服务 v2 (Cloudflare Workers + KV) · 加固版
 *
 * 部署(六步, 详见 部署说明.md):
 *   1. 注册 Cloudflare(免费) → Workers & Pages → Create Worker
 *   2. Storage & Databases → KV → 创建命名空间 AUTH_CODES
 *   3. Worker → Settings → Variables:
 *        ADMIN_KEY            = *** 管理页/生成卡密用)
 *        SIGN_SALT            = token 签名盐(随机一串字符, 泄露即可作废所有token)
 *        DATA_SEED            = 核心数据解密种子(随机 32 字节 hex; 与 tools/build_hardened.py
 *                               加密数据时用的 --seed 保持一致; 轮换需重发分发包)
 *        ED25519_PRIVATE_KEY  = Ed25519 私钥 PKCS8 hex (由 tools/gen_worker_keys.js 生成;
 *                               对应公钥 hex 填入客户端 auth_core.py 后重新编译)
 *   4. Settings → Bindings → KV: 变量名 AUTH_CODES 绑定刚才的命名空间
 *   5. 部署本 worker.js
 *   6. 客户端内置此地址, 无需配置 auth.json
 *
 * 客户端对接协议:
 *   POST /activate  {code, hwid}          → {ok, token, expires_at, nickname, seed, sig}
 *   POST /verify    {hwid, token}         → {ok, valid, expires_at, nickname, seed, sig}
 *   POST /deactivate {code, hwid, admin?} → 换机解绑(带 admin key 免限频)
 *   GET  /admin?key=***                   → 管理页(生成/列表/吊销)
 *
 * v2 变更:
 *   - 响应签名升级为 Ed25519 (私钥只在 Worker, 客户端内置公钥锚点), 保留通道 HMAC 兼容
 *   - activate/verify 成功响应附带 seed (客户端据此派生核心数据解密密钥, 不落盘)
 *   - 新增 /healthz 供部署自检 (不暴露任何密钥)
 */

const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8",
                       "Access-Control-Allow-Origin": "*",
                       "Access-Control-Allow-Headers": "Content-Type" };

const err = (msg, status = 400) => new Response(JSON.stringify({ ok: false, message: msg }),
                                               { status, headers: JSON_HEADERS });
const okj = (obj) => new Response(JSON.stringify({ ok: true, ...obj }),
                                  { headers: JSON_HEADERS });

// ---------------- 工具 ----------------
function hexToBuf(hex) {
    const clean = String(hex || "").trim();
    const out = new Uint8Array(clean.length / 2);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.substr(i * 2, 2), 16);
    return out;
}
function bufToHex(buf) {
    return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}
function bufToB64(bytes) {
    let s = "";
    for (const b of bytes) s += String.fromCharCode(b);
    return btoa(s);
}

async function hmac(payload, salt) {
    const key = await crypto.subtle.importKey(
        "raw", new TextEncoder().encode(salt),
        { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload));
    return bufToHex(sig);
}

// 通道签名(旧协议兼容): 盐 = sha256("#LKW-CH#" + 站点origin)
async function chanSalt(origin) {
    const d = new TextEncoder().encode("#LKW-CH#" + origin);
    const h = await crypto.subtle.digest("SHA-256", d);
    return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, "0")).join("");
}

// Ed25519 响应签名: sig = base64(Ed25519.sign(sha256(原始JSON体)))
async function loadSignKey(env) {
    if (!env.ED25519_PRIVATE_KEY) return null;
    try {
        return await crypto.subtle.importKey(
            "pkcs8", hexToBuf(env.ED25519_PRIVATE_KEY),
            { name: "Ed25519" }, false, ["sign"]);
    } catch (e) {
        return null;
    }
}

async function signResp(obj, salt, signKey) {
    const body = JSON.stringify(obj);
    if (signKey) {
        const msg = new Uint8Array(
            await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body)));
        const sig = await crypto.subtle.sign("Ed25519", signKey, msg);
        return body.slice(0, -1) + `,"sig":"${bufToB64(new Uint8Array(sig))}"}`;
    }
    // 兼容: 旧客户端(通道 HMAC)
    return body.slice(0, -1) + `,"sig":"${await hmac(body, salt)}"}`;
}

function genCode(prefix = "LK") {
    // 卡密格式 LK-XXXX-XXXX-XXXX (去易混淆字符 0O1I)
    const cs = "23456789ABCDEFGHJKMNPQRSTUVWXYZ";
    const seg = () => [...crypto.getRandomValues(new Uint8Array(4))]
        .map(b => cs[b % cs.length]).join("");
    return `${prefix}-${seg()}-${seg()}-${seg()}`;
}

// ---------------- 路由 ----------------
export default {
    async fetch(request, env) {
        const url = new URL(request.url);
        const kv = env.AUTH_CODES;
        if (!kv || !env.ADMIN_KEY || !env.SIGN_SALT) {
            return err("服务端未配置完成(KV/ADMIN_KEY/SIGN_SALT)", 500);
        }
        if (request.method === "OPTIONS") return new Response(null, { headers: JSON_HEADERS });

        // ---------- 健康检查(部署自检, 不暴露任何密钥) ----------
        if (url.pathname === "/healthz") {
            let edOk = false;
            try { edOk = !!(await loadSignKey(env)); } catch (e) { edOk = false; }
            return okj({ service: "lkw-auth", ed25519: edOk, seed: !!env.DATA_SEED });
        }

        const signKey = await loadSignKey(env);
        const salt = await chanSalt(url.origin);

        // ---------- 管理页 ----------
        if (url.pathname === "/admin" && request.method === "GET") {
            if (url.searchParams.get("key") !== env.ADMIN_KEY) return err("管理密钥错误", 403);
            return new Response(adminPage(), { headers: { "Content-Type": "text/html; charset=utf-8" } });
        }

        // ---------- 管理操作(生成/列表/吊销) ----------
        if (url.pathname === "/admin/gen" && request.method === "POST") {
            const body = await request.json().catch(() => ({}));
            if (body.key !== env.ADMIN_KEY) return err("管理密钥错误", 403);
            const days = Math.max(1, Math.min(3650, parseInt(body.days) || 30));
            const count = Math.max(1, Math.min(50, parseInt(body.count) || 1));
            const note = String(body.note || "").slice(0, 40);
            const made = [];
            for (let i = 0; i < count; i++) {
                const code = genCode();
                await kv.put(`code:${code}`, JSON.stringify({
                    status: "unused", days,
                    expires_at: 0,        // 激活时才起算
                    bound_hwid: "", bound_at: 0, note,
                    created_at: Date.now(),
                }));
                made.push(code);
            }
            return okj({ codes: made });
        }

        if (url.pathname === "/admin/list" && request.method === "GET") {
            if (url.searchParams.get("key") !== env.ADMIN_KEY) return err("管理密钥错误", 403);
            const list = [];
            const it = await kv.list({ prefix: "code:", limit: 500 });
            for (const k of it.keys) {
                const v = JSON.parse(await kv.get(k.name) || "{}");
                list.push({ code: k.name.slice(5), ...v });
            }
            list.sort((a, b) => b.created_at - a.created_at);
            return okj({ list });
        }

        if (url.pathname === "/admin/revoke" && request.method === "POST") {
            const body = await request.json().catch(() => ({}));
            if (body.key !== env.ADMIN_KEY) return err("管理密钥错误", 403);
            const key = `code:${String(body.code || "").trim().toUpperCase()}`;
            const v = JSON.parse(await kv.get(key) || "null");
            if (!v) return err("卡密不存在", 404);
            v.status = "revoked";
            await kv.put(key, JSON.stringify(v));
            return okj({ code: body.code });
        }

        // ---------- 激活 ----------
        if (url.pathname === "/activate" && request.method === "POST") {
            const body = await request.json().catch(() => ({}));
            const code = String(body.code || "").trim().toUpperCase();
            const hwid = String(body.hwid || "").trim();
            if (!code || !hwid) return err("参数缺失");
            const key = `code:${code}`;
            const v = JSON.parse(await kv.get(key) || "null");
            if (!v) return err("卡密不存在");
            if (v.status === "revoked") return err("卡密已被吊销");
            if (v.status === "bound" && v.bound_hwid !== hwid) {
                return err("卡密已绑定其他设备, 如需换机请联系管理员解绑");
            }
            if (v.status === "unused") {
                v.status = "bound";
                v.bound_hwid = hwid;
                v.bound_at = Date.now();
                v.expires_at = Date.now() + v.days * 86400000;
                await kv.put(key, JSON.stringify(v));
            }
            const token = await hmac(`${hwid}|${v.expires_at}`, env.SIGN_SALT);
            return new Response(await signResp({
                ok: true,
                token, expires_at: v.expires_at, days: v.days,
                nickname: `训练家_${code.slice(-4)}`,
                ...(env.DATA_SEED ? { seed: env.DATA_SEED } : {}),
            }, salt, signKey), { headers: JSON_HEADERS });
        }

        // ---------- 启动校验 ----------
        if (url.pathname === "/verify" && request.method === "POST") {
            const body = await request.json().catch(() => ({}));
            const code = String(body.code || "").trim().toUpperCase();
            const hwid = String(body.hwid || "").trim();
            const token = String(body.token || "").trim();
            if (!code || !hwid || !token) return err("参数缺失");
            const v = JSON.parse(await kv.get(`code:${code}`) || "null");
            if (!v) return err("卡密不存在", 404);
            if (v.status === "revoked") return err("卡密已被吊销", 403);
            if (v.status !== "bound" || v.bound_hwid !== hwid)
                return err("卡密与设备不匹配", 403);
            const expect = await hmac(`${hwid}|${v.expires_at}`, env.SIGN_SALT);
            if (token !== expect) return err("token 校验失败", 403);
            if (Date.now() > v.expires_at) return err("卡密已过期", 403);
            return new Response(await signResp({
                ok: true, expires_at: v.expires_at,
                nickname: `训练家_${code.slice(-4)}`,
                ...(env.DATA_SEED ? { seed: env.DATA_SEED } : {}),
            }, salt, signKey), { headers: JSON_HEADERS });
        }

        // ---------- 换机解绑 ----------
        if (url.pathname === "/deactivate" && request.method === "POST") {
            const body = await request.json().catch(() => ({}));
            const code = String(body.code || "").trim().toUpperCase();
            const key = `code:${code}`;
            const v = JSON.parse(await kv.get(key) || "null");
            if (!v) return err("卡密不存在", 404);
            const isAdmin = body.admin_key === env.ADMIN_KEY;
            const boundHours = (Date.now() - (v.bound_at || 0)) / 3600000;
            if (!isAdmin && boundHours < 72)
                return err(`绑定未满 72 小时, 暂不能自助换机(剩余 ${Math.ceil(72 - boundHours)}h)`);
            v.status = "unused";
            v.bound_hwid = ""; v.bound_at = 0; v.expires_at = 0;
            await kv.put(key, JSON.stringify(v));
            return okj({ code });
        }

        return err("未知接口", 404);
    },
};

function adminPage() {
    return `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>卡密管理</title>
<style>
 body{font-family:system-ui;background:#f6efdc;color:#3f3428;max-width:860px;margin:24px auto;padding:0 16px}
 input,select,button{padding:6px 10px;border:1px solid #dccfa8;border-radius:6px;font-size:14px}
 button{background:#8a6420;color:#fff;cursor:pointer;border:none}
 table{width:100%;border-collapse:collapse;margin-top:12px;background:#fffdf6;font-size:13px}
 th,td{padding:6px 8px;border:1px solid #e8dcb8;text-align:left}
 .st-unused{color:#2e7d4f}.st-bound{color:#8a6410}.st-revoked{color:#a8402f}
 code{background:#efe6c8;padding:1px 5px;border-radius:4px}
 #out{white-space:pre-wrap;background:#fffdf6;border:1px dashed #c8b482;padding:10px;margin-top:10px;border-radius:8px}
</style></head><body>
<h2>🎟️ 卡密管理</h2>
<p>生成 → 把卡密发给朋友 → 客户端「激活」输入。</p>
<div>
 时长 <select id="days"><option value="7">7天</option><option value="30" selected>30天</option>
 <option value="90">90天</option><option value="365">365天</option></select>
 数量 <input id="count" type="number" value="1" min="1" max="50" style="width:60px">
 备注 <input id="note" style="width:120px" placeholder="发给谁">
 <button onclick="gen()">生成卡密</button>
 <button onclick="lst()" style="background:#5a4426">刷新列表</button>
</div>
<div id="out"></div>
<table id="tb"></table>
<script>
const K = localStorage.getItem('adminKey') || '';
if (!K) localStorage.setItem('adminKey', prompt('管理密钥:') || '');
async function gen(){
  const r = await fetch('/admin/gen', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({key:localStorage.getItem('adminKey'), days:+days.value, count:+count.value, note:note.value})});
  const j = await r.json();
  document.getElementById('out').textContent = j.ok ? '新卡密:\\n' + j.codes.join('\\n') : j.message;
  lst();
}
async function lst(){
  const r = await fetch('/admin/list?key=' + encodeURIComponent(localStorage.getItem('adminKey') || ''));
  const j = await r.json();
  if (!j.ok) { document.getElementById('out').textContent = j.message; return; }
  document.getElementById('tb').innerHTML = '<tr><th>卡密</th><th>状态</th><th>天数</th><th>到期</th><th>备注</th><th></th></tr>' +
    j.list.map(x => '<tr><td><code>' + x.code + '</code></td>'
      + '<td class="st-' + x.status + '">' + ({unused:'未用',bound:'已绑定',revoked:'已吊销'})[x.status] + '</td>'
      + '<td>' + (x.days||'') + '</td>'
      + '<td>' + (x.expires_at ? new Date(x.expires_at).toLocaleDateString() : '-') + '</td>'
      + '<td>' + (x.note||'') + '</td>'
      + '<td>' + (x.status !== 'revoked' ? '<button onclick="rv(\\'' + x.code + '\\')">吊销</button>' : '') + '</td></tr>').join('');
}
async function rv(c){
  if (!confirm('吊销 ' + c + ' ?')) return;
  await fetch('/admin/revoke', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({key:localStorage.getItem('adminKey'), code:c})});
  lst();
}
lst();
</script></body></html>`;
}
