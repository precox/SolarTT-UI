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
  }, 'Chrome debugger', 45000);
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
  async function visible(id) { return evaluate('(() => {const e=document.getElementById('+JSON.stringify(id)+'); return !!e && !e.classList.contains("hidden");})()'); }
  async function viewport(width) {
    await call('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:true});
  }
  async function fitsScreen() {
    return evaluate('document.documentElement.scrollWidth <= window.innerWidth && Array.from(document.querySelectorAll(".user-card button")).filter(b=>b.getClientRects().length).every(b=>{const r=b.getBoundingClientRect();return r.left>=0 && r.right<=window.innerWidth && r.height>=44;})');
  }
  async function closeProfile() {
    await evaluate('document.getElementById("close-profile").click()');
    await waitFor(async()=>await evaluate('exported === null && document.getElementById("deeplink").value === "" && !document.getElementById("qr").hasAttribute("src") && !document.getElementById("open-app").hasAttribute("href") && Array.from(document.querySelectorAll("#manual-settings input,#manual-settings textarea")).every(e=>e.value==="") && document.getElementById("manual-password").type==="password" && document.getElementById("show-password").getAttribute("aria-pressed")==="false" && document.getElementById("manual-ipv6").textContent==="" && document.getElementById("profile-status").textContent==="" && !document.querySelector(".profile-exports").open && !document.querySelector(".profile-format").open'),'cleared profile');
  }
  async function checkManualSetup(name) {
    assert(await evaluate('(() => {const m=exported.manual,v=id=>document.getElementById("manual-"+id).value;return v("name")==='+JSON.stringify(name)+' && v("address")===m.addresses[0] && v("hostname")===m.hostname && v("sni")===m.custom_sni && v("username")===m.username && v("password")===m.password && v("dns")===m.dns_upstreams.join("\n") && v("random")==="" && document.querySelector("[data-copy-field=manual-random]").disabled && m.upstream_protocol==="http2" && !m.skip_verification && !m.anti_dpi && m.certificate===null && document.getElementById("manual-ipv6").textContent===(m.has_ipv6?"On · checked":"Off · unchecked") && !document.querySelector(".profile-exports").open && document.getElementById("manual-password").type==="password";})()'),'manual Android fields differ from the exported profile');
    assert(await evaluate('(() => {const b=document.getElementById("show-password"),p=document.getElementById("manual-password");b.click();const visible=p.type==="text" && b.getAttribute("aria-pressed")==="true";b.click();return visible && p.type==="password" && b.getAttribute("aria-pressed")==="false";})()'),'password visibility controls failed');
    // Synthetic fixture only; copied values never leave this browser evaluation.
    assert(await evaluate('(async()=>{const saved=Object.getOwnPropertyDescriptor(navigator,"clipboard");let copied=null;try{Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async value=>{copied=value;}}});for(const b of document.querySelectorAll("[data-copy-field]")){if(b.disabled)continue;copied=null;b.click();await Promise.resolve();if(copied!==document.getElementById(b.dataset.copyField).value)return false;}Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async()=>{throw new Error("Synthetic clipboard denied");}}});document.querySelector("[data-copy-field=manual-password]").click();await new Promise(resolve=>setTimeout(resolve,0));return document.getElementById("manual-password").type==="password" && document.getElementById("profile-status").textContent.includes("Tap Show password") && !document.getElementById("profile-status").textContent.includes(exported.manual.password);}finally{copied=null;if(saved)Object.defineProperty(navigator,"clipboard",saved);else delete navigator.clipboard;}})()'),'manual field copying or denied-clipboard fallback failed');
    for(const width of [320,390,1280]) {
      await viewport(width);
      assert(await evaluate('(() => {const d=document.getElementById("profile");return d.scrollWidth<=d.clientWidth && d.getBoundingClientRect().left>=0 && d.getBoundingClientRect().right<=innerWidth && Array.from(d.querySelectorAll("button")).filter(b=>b.getClientRects().length).every(b=>{const r=b.getBoundingClientRect();return r.height>=44 && r.left>=0 && r.right<=innerWidth;});})()'),'manual setup overflowed or had undersized controls');
    }
    await viewport(390);
  }
  async function issueDevice(name,unknownResult=false) {
    await evaluate('fixtureCard().querySelector(".add-device").click()');
    await waitFor(async()=>await evaluate('document.getElementById("issue").open'),'device setup');
    assert(await evaluate('document.getElementById("issue").scrollWidth <= document.getElementById("issue").clientWidth'),'device form overflowed');
    if(unknownResult) {
      await evaluate('(() => {const original=globalThis.fetch;globalThis.fetch=async function(url,options){const response=await original(url,options);if(url==="/api/command" && JSON.parse(options.body).command.op==="create_credential"){globalThis.fetch=original;return new Response(JSON.stringify({error:"Synthetic response lost after commit"}),{status:503,headers:{"Content-Type":"application/json"}});}return response;};})()');
    }
    await evaluate('(() => {const f=document.getElementById("issue-form");f.elements.label.value='+JSON.stringify(name)+';f.requestSubmit();})()');
    if(unknownResult) {
      await waitFor(async()=>await evaluate('document.getElementById("issue-submit").textContent==="Retry creation" && !document.getElementById("issue-submit").disabled'),'unknown creation result');
      await evaluate('document.getElementById("issue-form").requestSubmit()');
    }
    await waitFor(async()=>await evaluate('document.getElementById("profile").open && document.getElementById("deeplink").value.startsWith("tt://")'),'created profile export');
    assert(await evaluate('document.getElementById("qr").src.startsWith("data:image/svg+xml;base64,")'),'QR was not generated locally');
    assert(await evaluate('document.getElementById("open-app").getAttribute("href").startsWith("tt://")'),'app link missing');
    await checkManualSetup(name);
    await closeProfile();
  }
  await call('Page.enable');
  await call('Runtime.enable');
  await viewport(390);
  await call('Page.navigate',{url:fixture.origin});
  await waitFor(async()=>await evaluate('document.readyState === "complete"') && await visible('login'),'login form');
  await evaluate('(() => {const f=document.getElementById("login-form");f.elements.username.value="admin";f.elements.password.value='+JSON.stringify(fixture.password)+';f.requestSubmit();})()');
  fixture.password='';
  await waitFor(async()=>await visible('dashboard') && await evaluate('document.querySelectorAll("#users .user-card").length===1'),'authenticated dashboard');
  assert(await evaluate('document.querySelector("#login-form [name=password]").value===""'),'login password remained in form');
  const label='<img src=x onerror="window.solarttXss=true">';
  await evaluate('(() => {document.querySelector("details.create").open=true;const f=document.getElementById("create-form");f.elements.label.value='+JSON.stringify(label)+';f.elements.quota.value="0.001";f.elements.device_limit.value="1";f.elements.monthly.checked=true;f.requestSubmit();})()');
  await waitFor(async()=>await evaluate('document.querySelectorAll("#users .user-card").length===2'),'created user');
  await evaluate('globalThis.fixtureCard=()=>Array.from(document.querySelectorAll("#users .user-card")).find(r=>r.querySelector("h2").textContent==='+JSON.stringify(label)+')');
  assert(await evaluate('document.getElementById("users").textContent.includes('+JSON.stringify(label)+') && !document.querySelector("#users img") && !window.solarttXss'),'label was interpreted as HTML');
  await issueDevice('Browser phone',true);
  assert(await evaluate('fixtureCard().querySelectorAll(".device-card").length===1 && fixtureCard().querySelector(".add-device").disabled'),'one-slot device limit not reflected');
  assert(await evaluate('(async()=>{try{await command({op:"create_credential",user_id:fixtureCard().dataset.userId,label:"Over limit"});return false;}catch(e){return e.message.includes("Device limit reached");}})()'),'API bypassed the device limit');
  await evaluate('fixtureCard().querySelector(".access-settings").click()');
  assert(await evaluate('(() => {const f=document.getElementById("edit-form");f.elements.device_limit.value="0";return f.elements.device_limit.min==="1" && !f.elements.device_limit.checkValidity();})()'),'lowering limit below issued profiles was offered');
  assert(await evaluate('(() => {const f=document.getElementById("edit-form");f.elements.device_limit.value="2";return f.checkValidity();})()'),'stored byte quota prevented editing the device limit');
  await evaluate('document.getElementById("edit-form").requestSubmit()');
  await waitFor(async()=>await evaluate('!document.getElementById("edit").open && !fixtureCard().querySelector(".add-device").disabled'),'raised device limit');
  assert(await evaluate('(async()=>{const result=await command({op:"users",after:null});return result.users.find(u=>u.id===fixtureCard().dataset.userId).policy.limit_bytes===Math.floor(0.001*1073741824);})()'),'device limit edit changed the stored byte quota');
  await issueDevice('Browser computer');
  assert(await evaluate('fixtureCard().querySelectorAll(".device-card").length===2 && fixtureCard().querySelector(".add-device").disabled'),'two-slot device limit not reflected');
  await evaluate('(() => {const d=fixtureCard().querySelector(".device-card");d.querySelector("details").open=true;d.querySelector(".danger").click();})()');
  await waitFor(async()=>await evaluate('fixtureCard().querySelectorAll(".device-card").length===1 && !fixtureCard().querySelector(".add-device").disabled'),'revoked slot available');
  await issueDevice('Browser tablet');
  assert(await evaluate('fixtureCard().querySelectorAll(".device-card").length===2'),'revoked slot could not be replaced');
  for(const width of [320,390,1280]) {
    await viewport(width);
    assert(await fitsScreen(),'device cards overflowed or had undersized buttons');
  }
  await viewport(390);
  assert(await evaluate('document.getElementById("storage").textContent.includes("Audit:")'),'storage status was not rendered');
  await evaluate('document.getElementById("audit-refresh").closest("details").open=true;document.getElementById("audit-refresh").click()');
  await waitFor(async()=>await evaluate('document.querySelectorAll("#audit-rows tr").length>0'),'audit history');
  assert(await evaluate('(() => {const row=Array.from(document.querySelectorAll("#audit-rows tr")).find(r=>r.children[2].textContent==="profile_export_prepared");return !!row && /^[0-9]+$/.test(row.children[4].textContent) && row.children[5].textContent!=="—";})()'),'trusted export actor/profile was not rendered');
  await evaluate('document.querySelector(".audit").open=false');
  const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
  await mkdir(join(root,'dist'),{recursive:true});
  await writeFile(join(root,'dist/panel-fixture.png'),Buffer.from(screenshot.data,'base64'));
  await evaluate('document.getElementById("logout").click()');
  await waitFor(async()=>await visible('login') && !await visible('dashboard'),'logout');
  assert(await evaluate('fetch("/api/session").then(r=>r.status===401)'),'logout session remained valid');
  console.log('Browser manual Android setup/copy/privacy, mobile cards, device limits, idempotent issuance, revoke/reissue, profile clearing, HTML label and logout checks passed');
} finally {
  if (socket) socket.close();
  if (chrome.exitCode === null && chrome.signalCode === null) {
    const exited = new Promise(resolve => chrome.once('exit', resolve));
    chrome.kill('SIGTERM');
    await Promise.race([exited, pause(3000)]);
    if (chrome.exitCode === null && chrome.signalCode === null) { chrome.kill('SIGKILL'); await exited; }
  }
  // Renderer teardown can briefly recreate files after the main Chrome process exits.
  // Bound retries for ENOTEMPTY/EBUSY; a persistent failure still fails the job.
  await rm(profile, {recursive: true, force: true, maxRetries: 8, retryDelay: 100});
}
