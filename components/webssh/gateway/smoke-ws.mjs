// 冒烟测试：不经浏览器，直接对网关的 WS 端点跑三条台架命令。
// 用法：node gateway/smoke-ws.mjs $GATEWAY_TOKEN
import WebSocket from 'ws';
const ws = new WebSocket(`ws://localhost:8022/ws?device=bench&token=${process.argv[2]}`);
const cmds = ['hostname', 'tasklist | findstr /i motordebug', 'dir C:\\fc_pull'];
let i = 0, out = '';
ws.on('message', (raw) => {
  const m = JSON.parse(raw.toString());
  if (m.type === 'status') { console.log('[status]', m.state, m.detail);
    if (m.state === 'connected') setTimeout(next, 1200); }
  if (m.type === 'data') { out += m.data; process.stdout.write(m.data); }
});
function next() {
  if (i >= cmds.length) return setTimeout(() => { console.log('\n=== 收到字节', out.length); ws.close(); process.exit(0); }, 2500);
  ws.send(JSON.stringify({ type: 'input', data: cmds[i++] + '\r' }));
  setTimeout(next, 4000);
}
