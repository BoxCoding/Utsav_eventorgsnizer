// Records the Android offline segment on a running emulator (adb + the WebView's DevTools).
// Prereq: a debug build of the app bundled against the demo server, adb reverse to it.
// Off camera: sign in and open the plan once (so it is on the device). On camera: airplane
// mode → cold start → plans open → tick a task offline → reconnect → sync.
import { execSync, spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const ADB = `${process.env.ANDROID_HOME || '/opt/homebrew/share/android-commandlinetools'}/platform-tools/adb`;
const adb = (args) => execSync(`${ADB} ${args}`).toString().trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = process.env.DEMO_PORT || '8103';

async function webview() {
  for (let i = 0; i < 30; i += 1) {
    let pid = '';
    try { pid = adb('shell pidof app.utsav.planner'); } catch { /* not started yet */ }
    const sock = pid && adb('shell cat /proc/net/unix').includes(`webview_devtools_remote_${pid}`)
      ? `webview_devtools_remote_${pid}` : null; // earlier processes leave stale sockets behind
    if (sock) {
      adb('forward --remove-all');
      adb(`forward tcp:9333 localabstract:${sock}`);
      try {
        const pages = await (await fetch('http://localhost:9333/json')).json();
        const page = pages.find((t) => t.type === 'page');
        if (page) return page.webSocketDebuggerUrl;
      } catch { /* not ready yet */ }
    }
    await sleep(500);
  }
  throw new Error('WebView DevTools not found');
}

async function run(expression) {
  const ws = new WebSocket(await webview());
  await new Promise((r) => { ws.onopen = r; });
  ws.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } }));
  const msg = await new Promise((r) => { ws.onmessage = (m) => r(JSON.parse(m.data)); });
  ws.close();
  return msg.result?.result?.value ?? msg.result?.exceptionDetails?.exception?.description;
}
const until = (cond, ms = 20000) => run(`new Promise((ok) => { const t0 = Date.now();
  const tick = () => (${cond}) || Date.now() - t0 > ${ms} ? ok(!!(${cond})) : setTimeout(tick, 200); tick(); })`);
const launch = () => { adb('shell am force-stop app.utsav.planner'); adb('shell am start -n app.utsav.planner/.MainActivity'); };

// ── off camera: sign in online, open the plan once ──
adb('shell cmd connectivity airplane-mode disable');
adb(`reverse tcp:${PORT} tcp:${PORT}`);
launch();
await until(`!document.querySelector('#auth-view').hidden || !document.querySelector('#home-view').hidden`, 30000);
await run(`(() => { if (!document.querySelector('#auth-view').hidden) {
  document.querySelector('#login-email').value = 'priya.demo@example.com';
  document.querySelector('#login-password').value = 'Utsav-demo-2026';
  document.querySelector('#login-form').requestSubmit(); } })()`);
if (!await until(`!document.querySelector('#home-view').hidden && document.querySelector('.event-card')`, 30000)) {
  throw new Error('sign-in did not reach the home screen');
}
await run(`document.querySelector('.event-card').click()`);
await until(`!document.querySelector('#event-view').hidden`);
await sleep(2000); // the plan is now stored on the device
await run(`location.hash = '#/'`);
await sleep(1500);
console.log('signed in and plan cached');

// ── on camera ──
const marks = {};
const rec = spawn(ADB, ['shell', 'screenrecord', '--bit-rate', '8000000', '--time-limit', '60', '/sdcard/offline.mp4']);
const t0 = Date.now();
const mark = (name) => { marks[name] = (Date.now() - t0) / 1000; };
await sleep(1500);
mark('airplane');
adb(`reverse --remove-all`);
adb('shell cmd connectivity airplane-mode enable');
await sleep(2500);
mark('relaunch');
launch();
await until(`!document.querySelector('#home-view').hidden && !document.querySelector('#offline-bar').hidden`);
mark('offline-home');
await sleep(3500);
await run(`document.querySelector('.event-card').click()`);
await until(`!document.querySelector('#event-view').hidden`);
await sleep(1500);
await run(`document.querySelector('#t-checklist').click()`);
await sleep(1500);
mark('tick');
// Re-query after each tick: saving re-renders the checklist.
const tickNext = `(async () => { const box = [...document.querySelectorAll('#panel-checklist .check-box')].find((x) => !x.checked);
  box.scrollIntoView({ block: 'center' }); await new Promise((r) => setTimeout(r, 900)); box.click(); })()`;
await run(tickNext);
await sleep(1500);
await run(tickNext);
await sleep(1500);
await run(`window.scrollTo({ top: 0, behavior: 'smooth' })`);
await sleep(3500);
mark('reconnect');
adb('shell cmd connectivity airplane-mode disable');
await sleep(3000);
adb(`reverse tcp:${PORT} tcp:${PORT}`);
await sleep(1000);
await run(`window.dispatchEvent(new Event('online'))`); // what Android fires when the network returns
await until(`document.querySelector('#offline-bar').hidden`);
mark('synced');
const server = await run(`(async () => { const id = location.hash.match(/event\\/(\\d+)/)[1];
  const r = await fetch('http://localhost:${PORT}/api/events/' + id, { headers: { Authorization: 'Bearer ' + localStorage.getItem('utsav:token') } });
  return (await r.json()).event.done.length; })()`);
await sleep(4000);
mark('end');
rec.kill('SIGINT');
await sleep(2500);
adb(`pull /sdcard/offline.mp4 ${join(here, 'raw', 'offline.mp4')}`);
writeFileSync(join(here, 'raw', 'offline-marks.json'), JSON.stringify({ ...marks, serverDone: server }, null, 1));
console.log(marks, 'ticks on server after sync:', server);
