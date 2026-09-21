#!/usr/bin/env node
/**
 * scripts/upload_release_oss.cjs
 * ---------------------------------------------------------------------------
 * tag 出包后把安装包直传阿里云 OSS，供官网「下载客户端」直接下载。
 * 由 .github/workflows/release.yml 的 release job 在 GitHub Release 发布后调用，
 * 取代官网仓 tools/sync-release.js「GitHub Release → 下载 → 校验 → 上传」的
 * 手工全量同步（那边降级为补漏/回溯旧版本的后备工具）。
 *
 * 写进 OSS 的对象（与 sync-release.js 的约定逐项一致，官网按钮直链不用动）：
 *   <prefix>/<tag>/<文件名>      版本化归档，内容不可变，长缓存
 *   <prefix>/<去版本号文件名>    稳定别名（LingYan_0.2.2_x64-setup.exe →
 *                                LingYan_x64-setup.exe），官网按钮指向这里，
 *                                每次发版覆盖、Cache-Control: no-cache
 *   <prefix>/<tag>/SHA256SUMS    校验和随版本归档（不进清单、不设别名）
 *   <prefix>/latest.json         元数据清单（版本、大小、SHA256、两种地址）
 * 上传后按域名刷新 CDN —— 本站 CDN 对可缓存对象强制 30 天 TTL 且忽略
 * Cache-Control，别名覆盖后不刷缓存的话用户最长一个月拿到旧安装包。
 *
 * 与官网工具的分工边界：version.json（客户端更新检查）与 download/index.html
 * 仍是手工维护——两者都要人写「用户语言的更新说明」，CI 不生成。
 *
 * 用法（CI 内）：
 *   node scripts/upload_release_oss.cjs --dist dist --tag v0.2.2 --repo owner/name
 * 本地演练：
 *   --dry-run                    只列计划并对每个目标 key 发 HEAD（只读，验签名/凭据）
 *   OSS_PREFIX=dl/_probe_xxx     写进一次性前缀演练全流程，完事手工删
 *
 * 配置读环境变量：
 *   OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET   必填（RAM 子账号，建议只授该
 *                                               bucket 的读写 + CDN 刷新权限）
 *   OSS_BUCKET / OSS_ENDPOINT / OSS_PREFIX / OSS_CDN_DOMAIN
 *       非机密（官网下载页本来就公开这些域名），有默认值，显式写在 workflow env。
 *   OSS_CDN_REFRESH=false                       跳过 CDN 刷新（默认刷）
 *   OSS_SECURITY_TOKEN                          STS 临时凭据才需要
 *   RELEASE_PUBLISHED_AT                        清单 publishedAt（ISO；CI 传 commit 时间）
 * ---------------------------------------------------------------------------
 */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const https = require('https');
const http = require('http');

/* Tauri 打包的签名/增量更新附属物不是给人下载的安装包，不往 OSS 传。 */
const SKIP_ASSET = /\.(sig|blockmap)$/i;
const VERSIONED_CACHE = 'public, max-age=604800';
const VOLATILE_CACHE = 'no-cache';

/* ======================= 参数与配置 ======================= */

function parseArgs(argv) {
  const opts = { dist: '', tag: '', repo: '', dryRun: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--dist') opts.dist = argv[++i];
    else if (a === '--tag') opts.tag = argv[++i];
    else if (a === '--repo') opts.repo = argv[++i];
    else if (a === '--dry-run') opts.dryRun = true;
    else if (a === '--help' || a === '-h') opts.help = true;
    else throw new Error(`认不出的参数：${a}（用 --help 看用法）`);
  }
  if (opts.help) {
    console.log('用法：node scripts/upload_release_oss.cjs --dist <目录> --tag <vX.Y.Z> '
      + '[--repo owner/name] [--dry-run]（配置走环境变量，见文件头注释）');
    process.exit(0);
  }
  if (!opts.dist || !opts.tag) throw new Error('--dist 与 --tag 必填。');
  if (!/^v\d+\.\d+\.\d+$/.test(opts.tag)) throw new Error(`tag 须为 vX.Y.Z 形态（实际：${opts.tag}）`);
  return opts;
}

function loadConfig() {
  const env = process.env;
  const cfg = {
    accessKeyId: env.OSS_ACCESS_KEY_ID || '',
    accessKeySecret: env.OSS_ACCESS_KEY_SECRET || '',
    securityToken: env.OSS_SECURITY_TOKEN || '',
    bucket: env.OSS_BUCKET || 'ddmdjhome',
    endpoint: (env.OSS_ENDPOINT || 'oss-cn-beijing.aliyuncs.com')
      .replace(/^https?:\/\//, '').replace(/\/+$/, ''),
    prefix: String(env.OSS_PREFIX || 'dl').replace(/^\/+|\/+$/g, ''),
    cdnDomain: env.OSS_CDN_DOMAIN || 'ddmdj.com,www.ddmdj.com',
    refresh: (env.OSS_CDN_REFRESH || 'true').toLowerCase() !== 'false',
    publishedAt: env.RELEASE_PUBLISHED_AT || '',
  };
  cfg.secure = !/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(cfg.endpoint);
  return cfg;
}

function checkConfig(cfg) {
  const missing = [];
  if (!cfg.accessKeyId) missing.push('OSS_ACCESS_KEY_ID');
  if (!cfg.accessKeySecret) missing.push('OSS_ACCESS_KEY_SECRET');
  if (missing.length) {
    throw new Error(`缺少配置：${missing.join('、')}。到仓库 Settings → Secrets and variables → Actions `
      + '配置后重跑本 job（上传是覆盖写，重跑幂等）。');
  }
}

/* ======================= OSS 签名与请求（与官网 tools/deploy-oss.js 同源） ======================= */

/* OSS 签名 V1：
     StringToSign = 动词 \n Content-MD5 \n Content-Type \n Date \n
                    规范化 x-oss- 头 + 规范化资源
   规范化 x-oss- 头：只取 x-oss- 开头的头，键小写、去空白、按字典序，每条以 \n 结尾。
   签名算法 HMAC-SHA1；签了的头必须发出去，否则远端比对不一致。 */
function sign(cfg, method, key, { contentType = '', contentMd5 = '', extraHeaders = {} } = {}) {
  const date = new Date().toUTCString();
  const allHeaders = { ...extraHeaders };
  if (cfg.securityToken) allHeaders['x-oss-security-token'] = cfg.securityToken;
  const canonicalHeaders = Object.keys(allHeaders)
    .filter((k) => k.toLowerCase().startsWith('x-oss-'))
    .map((k) => [k.toLowerCase(), String(allHeaders[k]).trim()])
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([k, v]) => `${k}:${v}\n`)
    .join('');
  const resource = `/${cfg.bucket}/${key}`;
  const stringToSign = [method, contentMd5, contentType, date, `${canonicalHeaders}${resource}`].join('\n');
  const signature = crypto.createHmac('sha1', cfg.accessKeySecret)
    .update(stringToSign, 'utf8').digest('base64');
  const out = { Date: date, Authorization: `OSS ${cfg.accessKeyId}:${signature}` };
  if (cfg.securityToken) out['x-oss-security-token'] = cfg.securityToken;
  return out;
}

const encodeKey = (key) => key.split('/').map(encodeURIComponent).join('/');

function request(cfg, method, key, { body, contentType = '', contentMd5 = '', headers = {} } = {}) {
  const reqHeaders = { ...headers, ...sign(cfg, method, key, { contentType, contentMd5, extraHeaders: headers }) };
  /* 空值不能发出去：OSS 会把它当成真的头去比对签名，而签名里那一栏是空字符串。 */
  if (contentType) reqHeaders['Content-Type'] = contentType;
  if (contentMd5) reqHeaders['Content-MD5'] = contentMd5;
  if (body) reqHeaders['Content-Length'] = body.length;
  /* 虚拟主机式：bucket 拼进域名（<bucket>.<endpoint>），对象 key 直接做路径。 */
  const [hostname, port] = `${cfg.bucket}.${cfg.endpoint}`.split(':');
  return new Promise((resolve, reject) => {
    const mod = cfg.secure ? https : http;
    const req = mod.request(
      { method, hostname, port: port ? Number(port) : undefined, path: `/${encodeKey(key)}`, headers: reqHeaders },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString('utf8') }));
      },
    );
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function withRetry(fn, label) {
  let lastErr;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fn();
      if (res.status >= 500 || res.status === 429) {
        lastErr = new Error(`${label} 返回 ${res.status}：${res.body.slice(0, 200)}`);
        await sleep(400 * 2 ** attempt);
        continue;
      }
      return res;
    } catch (e) {
      lastErr = e;
      await sleep(400 * 2 ** attempt);
    }
  }
  throw lastErr;
}

function ossMessage(body) {
  const m = /<Message>([^<]*)<\/Message>/.exec(body || '');
  const c = /<Code>([^<]*)<\/Code>/.exec(body || '');
  return m ? `${c ? `${c[1]} — ` : ''}${m[1]}` : (body || '').slice(0, 200);
}

/* ======================= CDN 刷新（阿里云 POP 签名，与官网工具同源） ======================= */

const percentEncode = (s) => encodeURIComponent(s)
  .replace(/\+/g, '%20').replace(/\*/g, '%2A').replace(/%7E/g, '~');

function popSignedQuery(params, secret) {
  const canonical = Object.keys(params).sort()
    .map((k) => `${percentEncode(k)}=${percentEncode(params[k])}`).join('&');
  const stringToSign = `GET&${percentEncode('/')}&${percentEncode(canonical)}`;
  const signature = crypto.createHmac('sha1', `${secret}&`).update(stringToSign, 'utf8').digest('base64');
  return `${canonical}&Signature=${percentEncode(signature)}`;
}

function aliError(body) {
  try {
    const j = JSON.parse(body);
    return [j.Code, j.Message].filter(Boolean).join(' — ') || body.slice(0, 200);
  } catch {
    return body.slice(0, 200);
  }
}

async function refreshCdn(cfg, urls) {
  const host = 'cdn.aliyuncs.com';
  let done = 0;
  for (let i = 0; i < urls.length; i += 100) {
    const batch = urls.slice(i, i + 100);
    const params = {
      AccessKeyId: cfg.accessKeyId,
      Action: 'RefreshObjectCaches',
      Format: 'JSON',
      ObjectPath: batch.join('\n'),
      ObjectType: 'File',
      SignatureMethod: 'HMAC-SHA1',
      SignatureNonce: crypto.randomUUID(),
      SignatureVersion: '1.0',
      Timestamp: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
      Version: '2018-05-10',
    };
    const res = await withRetry(() => new Promise((resolve, reject) => {
      const req = https.request(
        { method: 'GET', hostname: host, path: `/?${popSignedQuery(params, cfg.accessKeySecret)}` },
        (r) => {
          const chunks = [];
          r.on('data', (c) => chunks.push(c));
          r.on('end', () => resolve({ status: r.statusCode, body: Buffer.concat(chunks).toString('utf8') }));
        },
      );
      req.on('error', reject);
      req.end();
    }), 'CDN 刷新');
    if (res.status !== 200 || /"Code"\s*:\s*"/.test(res.body)) {
      throw new Error(`CDN 刷新失败（${res.status}）：${aliError(res.body)}\n`
        + '安装包已经传上 OSS 了，这一步只是刷缓存。别名地址被 CDN 强制缓存 30 天，'
        + '请尽快处理：给该 RAM 账号授 CDN 刷新权限（RefreshObjectCaches）后重跑本 job（覆盖上传幂等），'
        + '或去 CDN 控制台手工刷新，或临时设 OSS_CDN_REFRESH=false 让出包不再卡在这。');
    }
    done += batch.length;
  }
  return done;
}

/* ======================= 本地产物枚举与清单 ======================= */

function* walk(dir) {
  for (const name of fs.readdirSync(dir).sort()) {
    const abs = path.join(dir, name);
    if (fs.statSync(abs).isDirectory()) yield* walk(abs);
    else yield abs;
  }
}

function collectFiles(distDir) {
  if (!fs.existsSync(distDir)) throw new Error(`找不到产物目录：${distDir}`);
  const byName = new Map();
  for (const abs of walk(distDir)) {
    const name = path.basename(abs);
    if (name === '.DS_Store' || SKIP_ASSET.test(name)) continue;
    if (byName.has(name)) throw new Error(`产物重名：${name} 同时出现在 ${byName.get(name)} 与 ${abs}`);
    byName.set(name, abs);
  }
  const files = [...byName.entries()].map(([name, abs]) => ({ name, abs, size: fs.statSync(abs).size }));
  const installers = files.filter((f) => f.name !== 'SHA256SUMS');
  const sums = files.find((f) => f.name === 'SHA256SUMS') || null;
  if (!installers.length) throw new Error(`${distDir} 下没有安装包（exe/msi/dmg）——检查上游构建产物。`);
  return { installers, sums };
}

const sha256File = (file) => new Promise((resolve, reject) => {
  const hash = crypto.createHash('sha256');
  fs.createReadStream(file)
    .on('data', (c) => hash.update(c))
    .on('end', () => resolve(hash.digest('hex')))
    .on('error', reject);
});

const contentTypeOf = (name) => /\.json$/i.test(name) ? 'application/json; charset=utf-8'
  : /(^|\/)SHA256SUMS$/i.test(name) ? 'text/plain; charset=utf-8'
    : 'application/octet-stream';

const platformOf = (name) => /\.(exe|msi)$/i.test(name) ? 'windows'
  : /\.(dmg|pkg)$/i.test(name) ? 'macos'
    : /\.(AppImage|deb|rpm)$/i.test(name) ? 'linux' : 'other';

/* LingYan_0.2.2_x64-setup.exe → LingYan_x64-setup.exe。去掉首个版本号段，
   得到跨版本不变的稳定文件名；名字里没有版本号的原样保留。 */
const stableName = (name, version) => name.replace(`_${version}`, '');

/* 对外下载域名：CDN 域名第一个优先，没配退回 OSS 直连域名。 */
const publicBase = (cfg) => `https://${String(cfg.cdnDomain || '').split(',').map((d) => d.trim()).filter(Boolean)[0]
  || `${cfg.bucket}.${cfg.endpoint}`}`;

const fmtSize = (n) => (n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);

/* ======================= 主流程 ======================= */

async function putObject(cfg, key, body, contentType, cache) {
  const contentMd5 = crypto.createHash('md5').update(body).digest('base64');
  const res = await withRetry(
    () => request(cfg, 'PUT', key, { body, contentType, contentMd5, headers: { 'Cache-Control': cache } }),
    `PUT ${key}`,
  );
  if (res.status !== 200) throw new Error(`上传 ${key} 失败：${res.status} ${ossMessage(res.body)}`);
}

async function objectExists(cfg, key) {
  const res = await withRetry(() => request(cfg, 'HEAD', key), `HEAD ${key}`);
  if (res.status === 200) return true;
  if (res.status === 404) return false;
  throw new Error(`HEAD ${key} 失败：${res.status} ${ossMessage(res.body)}`);
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const cfg = loadConfig();
  checkConfig(cfg);
  const t0 = Date.now();
  const version = opts.tag.replace(/^v/, '');

  const { installers, sums } = collectFiles(opts.dist);
  const tagDir = `${cfg.prefix}/${opts.tag}`;
  const plan = installers.map((f) => ({
    file: f,
    versionedKey: `${tagDir}/${f.name}`,
    aliasKey: `${cfg.prefix}/${stableName(f.name, version)}`,
  }));

  const target = `${cfg.bucket}.${cfg.endpoint}/${cfg.prefix}/`;
  console.log(`目标：${target}`);
  console.log(`版本：${opts.tag}（${installers.length} 个安装包，共 ${fmtSize(installers.reduce((s, f) => s + f.size, 0))}）${opts.dryRun ? '（--dry-run，只读不写）' : ''}`);
  for (const p of plan) {
    console.log(`  ↑ ${p.versionedKey}  ${fmtSize(p.file.size)}`);
    console.log(`  ↑ ${p.aliasKey}  ${fmtSize(p.file.size)}（官网按钮指向这里）`);
  }
  if (sums) console.log(`  ↑ ${tagDir}/SHA256SUMS（校验用，随版本归档）`);
  console.log(`  ↑ ${cfg.prefix}/latest.json`);

  if (opts.dryRun) {
    for (const p of plan) {
      await objectExists(cfg, p.versionedKey);
      await objectExists(cfg, p.aliasKey);
    }
    console.log(`\ndry-run 通过（${((Date.now() - t0) / 1000).toFixed(1)}s）：凭据与签名有效、目标 bucket 可达。没有写入任何东西。`);
    return;
  }

  /* ---------- 上传：版本化归档 + 稳定别名 + latest.json ---------- */

  const base = publicBase(cfg);
  const verified = [];
  for (const p of plan) {
    const body = fs.readFileSync(p.file.abs);
    await putObject(cfg, p.versionedKey, body, contentTypeOf(p.file.name), VERSIONED_CACHE);
    await putObject(cfg, p.aliasKey, body, contentTypeOf(p.file.name), VOLATILE_CACHE);
    verified.push({
      ...p,
      sha256: await sha256File(p.file.abs),
    });
    console.log(`  ✓ ${p.file.name}  ${fmtSize(p.file.size)}（版本化 + 别名）`);
  }
  if (sums) {
    await putObject(cfg, `${tagDir}/SHA256SUMS`, fs.readFileSync(sums.abs),
      contentTypeOf('SHA256SUMS'), VERSIONED_CACHE);
    console.log(`  ✓ SHA256SUMS（版本化）`);
  }

  const shaByName = new Map(verified.map((p) => [p.file.name, p.sha256]));
  const manifest = {
    repo: opts.repo || '',
    tag: opts.tag,
    version,
    publishedAt: cfg.publishedAt || new Date().toISOString(),
    syncedAt: new Date().toISOString(),
    notesUrl: opts.repo ? `https://github.com/${opts.repo}/releases/tag/${opts.tag}` : null,
    assets: verified.map((p) => ({
      name: p.file.name,
      platform: platformOf(p.file.name),
      size: p.file.size,
      sha256: shaByName.get(p.file.name),
      url: `${base}/${encodeURI(p.aliasKey)}`,
      versionedUrl: `${base}/${encodeURI(p.versionedKey)}`,
      source: opts.repo
        ? `https://github.com/${opts.repo}/releases/download/${opts.tag}/${encodeURI(p.file.name)}`
        : null,
    })),
  };
  await putObject(cfg, `${cfg.prefix}/latest.json`,
    Buffer.from(JSON.stringify(manifest, null, 2) + '\n'),
    contentTypeOf('latest.json'), VOLATILE_CACHE);
  console.log(`  ✓ latest.json`);

  /* ---------- 刷 CDN：别名与 latest.json 被覆盖，版本化 key 防重跑覆盖 ---------- */

  let refreshed = 0;
  if (cfg.refresh) {
    const domains = String(cfg.cdnDomain || '').split(',').map((d) => d.trim()).filter(Boolean);
    const keys = [...plan.flatMap((p) => [p.versionedKey, p.aliasKey]), `${cfg.prefix}/latest.json`];
    const urls = [...new Set(domains.length ? domains.flatMap((d) => keys.map((k) => `https://${d}/${encodeURI(k)}`))
      : keys.map((k) => `${base}/${encodeURI(k)}`))];
    refreshed = await refreshCdn(cfg, urls);
    console.log(`  ↻ 已刷新 CDN 缓存 ${refreshed} 个地址`);
  } else {
    console.log('  ↻ OSS_CDN_REFRESH=false，跳过 CDN 刷新——别名地址可能长期返回旧包，记得手工刷。');
  }

  console.log(`\n完成：${verified.length} 个安装包已上 OSS（${((Date.now() - t0) / 1000).toFixed(1)}s）。`);
  console.log('官网下载直链（跨版本不变）：');
  for (const p of verified) console.log(`  ${base}/${encodeURI(p.aliasKey)}`);

  /* GitHub Step Summary：出包页直接可读的同步结果（本地跑没有这个变量，跳过）。 */
  if (process.env.GITHUB_STEP_SUMMARY) {
    const lines = [
      '## 安装包已同步阿里云 OSS',
      '',
      `版本 \`${opts.tag}\` · CDN 刷新 ${refreshed} 个地址`,
      '',
      ...verified.map((p) => `- [${stableName(p.file.name, version)}](${base}/${encodeURI(p.aliasKey)}) · ${fmtSize(p.file.size)}`),
    ];
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${lines.join('\n')}\n`);
  }
}

if (require.main === module) {
  main().catch((e) => {
    console.error(`OSS 同步中断：${e.message}`);
    process.exit(1);
  });
}

/* 导出仅供本地演练后的清理脚本复用（CI 只走命令行入口）。 */
module.exports = { request, loadConfig };
