/**
 * webssh gateway — 浏览器 WebSocket  <->  SSH（ssh2）
 *
 * 职责：
 *   1. WS /ws?token=..&device=..   打开一个交互式 SSH shell，双向转发
 *   2. POST /remote/screenshot     经 SSH 跑 shot.ps1，把台架机图像以 base64 回传
 *   3. GET  /devices /health       设备清单与存活探测
 *
 * 安全：私钥路径与访问 token 全部来自环境变量，代码里不写死任何凭据。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import http from 'node:http';
import express from 'express';
import { WebSocketServer } from 'ws';
import { Client as SSHClient } from 'ssh2';
import 'dotenv/config';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.GATEWAY_PORT || 8022);
const TOKEN = process.env.GATEWAY_TOKEN || '';
const LOG_DIR = path.resolve(__dirname, process.env.GATEWAY_LOG_DIR || 'logs');
const DEVICES = JSON.parse(fs.readFileSync(path.join(__dirname, 'devices.json'), 'utf8'));

fs.mkdirSync(LOG_DIR, { recursive: true });

if (!TOKEN) {
  console.error('[gateway] 致命错误：未设置 GATEWAY_TOKEN，拒绝以无鉴权方式启动。参见 .env.example');
  process.exit(1);
}

/* ---------- 工具 ---------- */

const ts = () => new Date().toISOString();
const sessionId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

/** 会话日志：每个 SSH 会话一个文件，落在 logs/ */
function makeLogger(sid, deviceId) {
  const file = path.join(LOG_DIR, `${new Date().toISOString().slice(0, 10)}_${deviceId}_${sid}.log`);
  const fd = fs.createWriteStream(file, { flags: 'a' });
  const write = (tag, msg) => fd.write(`[${ts()}] [${tag}] ${msg}\n`);
  return { file, write, close: () => fd.end() };
}

/** 私钥：keyRef 是环境变量名，值是私钥文件路径（不是私钥本体，避免进程环境泄露） */
function loadPrivateKey(keyRef) {
  const p = process.env[keyRef];
  if (!p) throw new Error(`设备要求的私钥环境变量 ${keyRef} 未设置`);
  const abs = p.startsWith('~') ? path.join(process.env.HOME || '', p.slice(1)) : p;
  if (!fs.existsSync(abs)) throw new Error(`私钥文件不存在：${abs}`);
  return fs.readFileSync(abs);
}

function resolveDevice(id) {
  const d = DEVICES[id];
  if (!d) throw new Error(`未知设备 ${id}`);
  // 仪器类设备（示波器/电源）不直连，经其宿主机 via 转发
  return d.via ? { ...DEVICES[d.via], id: d.id, name: d.name, presets: d.presets } : d;
}

function checkToken(t) {
  return typeof t === 'string' && t.length > 0 && t === TOKEN;
}

/** 建一条 SSH 连接（Promise 化） */
function connect(dev) {
  return new Promise((resolve, reject) => {
    const conn = new SSHClient();
    const timer = setTimeout(() => { conn.end(); reject(new Error('SSH 连接超时（15s）')); }, 15000);
    conn
      .on('ready', () => { clearTimeout(timer); resolve(conn); })
      .on('error', (e) => { clearTimeout(timer); reject(e); })
      .connect({
        host: dev.host,
        port: dev.port,
        username: dev.user,
        privateKey: loadPrivateKey(dev.keyRef),
        readyTimeout: 15000,
        keepaliveInterval: 20000,
      });
  });
}

/** 一次性执行命令，收集 stdout/stderr */
function exec(conn, cmd) {
  return new Promise((resolve, reject) => {
    conn.exec(cmd, (err, stream) => {
      if (err) return reject(err);
      let out = '', errOut = '';
      stream
        .on('close', (code) => resolve({ code, out, err: errOut }))
        .on('data', (d) => { out += d.toString('utf8'); })
        .stderr.on('data', (d) => { errOut += d.toString('utf8'); });
    });
  });
}

/* ---------- HTTP ---------- */

const app = express();
app.use(express.json({ limit: '1mb' }));
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', process.env.GATEWAY_CORS_ORIGIN || '*');
  res.setHeader('Access-Control-Allow-Headers', 'content-type,x-gateway-token');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  if (req.method === 'OPTIONS') return res.sendStatus(204);
  next();
});

const auth = (req, res, next) => {
  const t = req.get('x-gateway-token') || req.query.token;
  if (!checkToken(t)) return res.status(401).json({ error: 'bad token' });
  next();
};

app.get('/health', (_req, res) => res.json({ ok: true, ts: ts() }));

app.get('/devices', auth, (_req, res) => {
  res.json(Object.values(DEVICES).map((d) => ({
    id: d.id, name: d.name, model: d.model, kind: d.kind,
    host: d.host, port: d.port, user: d.user, keyRef: d.keyRef,
    via: d.via ?? null, presets: d.presets ?? [],
  })));
});

/** 存活探测：对宿主机跑一条最轻的命令 */
app.get('/probe/:id', auth, async (req, res) => {
  let conn;
  try {
    const dev = resolveDevice(req.params.id);
    conn = await connect(dev);
    const r = await exec(conn, 'hostname');
    res.json({ online: true, hostname: r.out.trim() });
  } catch (e) {
    res.json({ online: false, error: String(e.message || e) });
  } finally { conn?.end(); }
});

/**
 * POST /remote/screenshot  { deviceId }
 * 把 shot.ps1 以 base64 EncodedCommand 方式送过去执行，避免引号与 GBK 控制台乱码。
 * 返回 { mode, dataUrl }：mode 说明这张图是实时截屏还是台架机上最近一张 bmp 回退。
 */
app.post('/remote/screenshot', auth, async (req, res) => {
  const deviceId = req.body?.deviceId || 'bench';
  const sid = sessionId();
  const log = makeLogger(sid, `${deviceId}-shot`);
  let conn;
  try {
    const dev = resolveDevice(deviceId);
    log.write('shot', `connect ${dev.user}@${dev.host}:${dev.port}`);
    conn = await connect(dev);
    const ps = fs.readFileSync(path.join(__dirname, 'shot.ps1'), 'utf8');
    const encoded = Buffer.from(ps, 'utf16le').toString('base64');
    const r = await exec(conn, `powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand ${encoded}`);

    const mode = (r.out.match(/SHOT_MODE:(.*)/) || [, 'unknown'])[1].trim();
    const b64 = (r.out.split('SHOT_B64_BEGIN')[1] || '').split('SHOT_B64_END')[0].replace(/\s+/g, '');
    if (!b64) throw new Error(`远端未返回图像：${r.out.slice(0, 300)} ${r.err.slice(0, 300)}`);

    // 回退文件可能是 bmp，用扩展名决定 MIME
    const mime = /\.bmp$/i.test(mode) ? 'image/bmp' : /\.jpe?g$/i.test(mode) ? 'image/jpeg' : 'image/png';
    log.write('shot', `ok mode=${mode} bytes=${b64.length}`);
    res.json({ deviceId, mode, takenAt: ts(), dataUrl: `data:${mime};base64,${b64}` });
  } catch (e) {
    log.write('shot', `fail ${e.message}`);
    res.status(502).json({ error: String(e.message || e) });
  } finally { conn?.end(); log.close(); }
});

/* ---------- WebSocket ↔ SSH shell ---------- */

const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/ws' });

wss.on('connection', (ws, req) => {
  const url = new URL(req.url, 'http://localhost');
  const sid = sessionId();
  const deviceId = url.searchParams.get('device') || 'bench';

  if (!checkToken(url.searchParams.get('token'))) {
    ws.send(JSON.stringify({ type: 'status', state: 'error', detail: '鉴权失败：token 不正确' }));
    return ws.close(4401, 'unauthorized');
  }

  const log = makeLogger(sid, deviceId);
  const send = (o) => ws.readyState === ws.OPEN && ws.send(JSON.stringify(o));
  send({ type: 'status', state: 'connecting', detail: `会话 ${sid}` });
  log.write('ws', `open device=${deviceId} from=${req.socket.remoteAddress}`);

  let conn, stream;
  (async () => {
    const dev = resolveDevice(deviceId);
    conn = await connect(dev);
    log.write('ssh', `ready ${dev.user}@${dev.host}:${dev.port}`);
    stream = await new Promise((resolve, reject) =>
      conn.shell({ term: 'xterm-256color', cols: 120, rows: 30 }, (e, s) => (e ? reject(e) : resolve(s))));

    send({ type: 'status', state: 'connected', detail: `${dev.user}@${dev.host}:${dev.port}` });
    stream.on('data', (d) => { const s = d.toString('utf8'); log.write('out', s.replace(/\n/g, '\\n')); send({ type: 'data', data: s }); });
    stream.stderr.on('data', (d) => send({ type: 'data', data: d.toString('utf8') }));
    stream.on('close', () => { send({ type: 'status', state: 'closed', detail: '远端关闭会话' }); ws.close(); });
  })().catch((e) => {
    log.write('ssh', `fail ${e.message}`);
    send({ type: 'status', state: 'error', detail: String(e.message || e) });
    ws.close();
  });

  ws.on('message', (raw) => {
    let m; try { m = JSON.parse(raw.toString()); } catch { return; }
    if (m.type === 'input' && stream) { log.write('in', JSON.stringify(m.data)); stream.write(m.data); }
    else if (m.type === 'resize' && stream) stream.setWindow(m.rows, m.cols, 0, 0);
  });

  ws.on('close', () => { log.write('ws', 'close'); log.close(); stream?.end(); conn?.end(); });
});

server.listen(PORT, () => {
  console.log(`[gateway] http+ws :${PORT}  设备 ${Object.keys(DEVICES).join(', ')}  日志 ${LOG_DIR}`);
});
