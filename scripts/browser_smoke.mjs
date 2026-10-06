// Disposable runner only. Browser automation uses Chrome's local debugging API.
// No dependencies, production credentials, external browser service or telemetry.
import {spawn} from 'node:child_process';
import {readFile, mkdir, rm, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import assert from 'node:assert/strict';

if (process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_OS !== 'Linux') {
  throw new Error('Browser smoke test requires a disposable GitHub Actions Linux runner');
}
let input = '';
for await (const chunk of process.stdin) input += chunk;
const fixture = JSON.parse(input);
input = '';
const root = resolve(import.meta.dirname, '..');
const profile = join(root, '.dev/browser-profile');
await mkdir(profile, {recursive: true, mode: 0o700});
const chrome = spawn('google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu',
  '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
  '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
  `--user-data-dir=${profile}`, 'about:blank'], {stdio: 'ignore'});
let socket;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(action, description, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (chrome.exitCode !== null || chrome.signalCode !== null) throw new Error('Chrome exited unexpectedly');
    // Navigation can temporarily destroy the previous JS execution context.
    try { if (await action()) return; } catch { /* retry within the deadline */ }
    await pause(50);
  }
  throw new Error(`Timed out: ${description}`);
}
try {
  let port;
  await waitFor(async () => {
    if (chrome.exitCode !== null) throw new Error('Chrome exited before opening its debugger');
    try { port = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; return !!port; }
    catch { return false; }
  }, 'Chrome debugger');
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find(target => target.type === 'page');
  assert(page, 'Chrome page target missing');
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, {once: true});
    socket.addEventListener('error', reject, {once: true});
  });
  let nextId = 0;
  const pending = new Map();
  function call(method, params = {}) {
    const id = ++nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Debugger timeout: ${method}`)); }, 15000);
      pending.set(id, {resolve, reject, timer});
      socket.send(JSON.stringify({id, method, params}));
    });
  }
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const waiter = pending.get(message.id); pending.delete(message.id); clearTimeout(waiter.timer);
      if (message.error) waiter.reject(new Error(`Debugger rejected ${message.error.code}`));
      else waiter.resolve(message.result);
    } else if (message.method === 'Page.javascriptDialogOpening') {
      call('Page.handleJavaScriptDialog', {accept: true, promptText: 'Browser fixture'}).catch(() => {});
    }
  });
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    // Do not print evaluated expressions or values: they can contain fixture secrets.
    if (result.exceptionDetails) throw new Error('Browser evaluation failed');
    return result.result.value;
  }
  async function visible(id) { return evaluate(`(() => {const e=document.getElementById(${JSON.stringify(id)}); return !!e && !e.classList.contains('hidden');})()`); }
  await call('Page.enable');
  await call('Runtime.enable');
  await call('Page.navigate', {url: fixture.origin});
  await waitFor(async () => await evaluate('document.readyState === "complete"') && await visible('login'), 'login form');
  await evaluate(`(() => {const f=document.getElementById('login-form'); f.elements.username.value='admin'; f.elements.password.value=${JSON.stringify(fixture.password)}; f.requestSubmit();})()`);
  fixture.password = '';
  await waitFor(async () => await visible('dashboard') && await evaluate('document.querySelectorAll("#users tr").length === 1'), 'authenticated dashboard');
  assert(await evaluate('document.querySelector("#login-form [name=password]").value === ""'), 'login password remained in form');
  const label = '<img src=x onerror="window.solarttXss=true">';
  await evaluate(`(() => {document.querySelector('details.create').open=true; const f=document.getElementById('create-form'); f.elements.label.value=${JSON.stringify(label)}; f.elements.quota.value='0.001'; f.elements.monthly.checked=true; f.requestSubmit();})()`);
  await waitFor(async () => await evaluate('document.querySelectorAll("#users tr").length === 2'), 'created user');
  assert(await evaluate(`document.getElementById('users').textContent.includes(${JSON.stringify(label)}) && !document.querySelector('#users img') && !window.solarttXss`), 'label was interpreted as HTML');
  await evaluate(`Array.from(document.querySelectorAll('#users tr')).find(r=>r.textContent.includes(${JSON.stringify(label)})).querySelector('button').click()`);
  await waitFor(async () => await evaluate(`Array.from(document.querySelectorAll('#users tr')).find(r=>r.textContent.includes(${JSON.stringify(label)})).querySelectorAll('.credential').length === 1`), 'issued credential');
  await evaluate(`Array.from(document.querySelectorAll('#users tr')).find(r=>r.textContent.includes(${JSON.stringify(label)})).querySelector('.credential button').click()`);
  await waitFor(async () => await evaluate('document.getElementById("profile").open && document.getElementById("deeplink").value.startsWith("tt://")'), 'profile export');
  assert(await evaluate('document.getElementById("qr").src.startsWith("data:image/svg+xml;base64,")'), 'QR was not generated locally');
  await evaluate('document.getElementById("close-profile").click()');
  await waitFor(async () => await evaluate('exported === null && document.getElementById("deeplink").value === "" && !document.getElementById("qr").hasAttribute("src")'), 'cleared profile');
  assert(await evaluate('document.getElementById("storage").textContent.includes("Audit:")'), 'storage status was not rendered');
  await evaluate('document.getElementById("audit-refresh").closest("details").open=true; document.getElementById("audit-refresh").click()');
  await waitFor(async () => await evaluate('document.querySelectorAll("#audit-rows tr").length > 0'), 'audit history');
  assert(await evaluate('(() => {const row=Array.from(document.querySelectorAll("#audit-rows tr")).find(r=>r.children[2].textContent==="profile_export_prepared");return !!row && /^\\d+$/.test(row.children[4].textContent) && row.children[5].textContent!=="—";})()'), 'trusted export actor/profile was not rendered');
  const screenshot = await call('Page.captureScreenshot' , {format: 'png', captureBeyondViewport: true});
  await mkdir(join(root, 'dist'), {recursive: true});
  await writeFile(join(root, 'dist/panel-fixture.png'), Buffer.from(screenshot.data, 'base64'));
  await evaluate('document.getElementById("logout").click()');
  await waitFor(async () => await visible('login') && !await visible('dashboard'), 'logout');
  assert(await evaluate('fetch("/api/session").then(r=>r.status === 401)'), 'logout session remained valid');
  console.log('Browser login, create, issue, profile clearing, HTML label and logout checks passed');
} finally {
  if (socket) socket.close();
  if (chrome.exitCode === null && chrome.signalCode === null) {
    const exited = new Promise(resolve => chrome.once('exit', resolve));
    chrome.kill('SIGTERM');
    await Promise.race([exited, pause(3000)]);
    if (chrome.exitCode === null && chrome.signalCode === null) { chrome.kill('SIGKILL'); await exited; }
  }
  await rm(profile, {recursive: true, force: true});
}
