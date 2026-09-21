#!/usr/bin/env node
/**
 * gen_worker_keys.js — 生成 Worker 部署所需的密钥对
 *
 * 产物:
 *   1. ED25519_PRIVATE_KEY (PKCS8 hex) → 填入 Cloudflare Worker 环境变量
 *   2. ED25519_PUBLIC_KEY  (Raw hex)  → 填入 tools/build_hardened.py 的 --pubkey
 *
 * 用法:
 *   node tools/gen_worker_keys.js
 *
 * 安全: 私钥只应存在于 Cloudflare 环境变量和本机生成时的输出里, 不要提交进 git。
 */

const crypto = require("crypto");

const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");

const pkcs8Hex = privateKey.export({ type: "pkcs8", format: "der" }).toString("hex");
const rawPubHex = publicKey.export({ type: "spki", format: "der" }).toString("hex").slice(-64); // 最后 32 字节 = raw 公钥

console.log("== 填入 Cloudflare Worker → Settings → Variables ==");
console.log(`ED25519_PRIVATE_KEY = ${pkcs8Hex}`);
console.log("");
console.log("== 填入客户端构建命令 (--pubkey 参数) ==");
console.log(`ED25519_PUBLIC_KEY  = ${rawPubHex}`);
console.log("");
console.log("DATA_SEED 示例(也可自定任意 64 位 hex):");
console.log(`DATA_SEED           = ${crypto.randomBytes(32).toString("hex")}`);
