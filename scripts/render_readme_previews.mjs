// Render the shipped UI against synthetic API responses. No agent or database.
// Run on a disposable development machine/runner with Node 22 and Google Chrome.
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {mkdtemp, readFile, writeFile, mkdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import assert from 'node:assert/strict';

const root=resolve(import.meta.dirname,'..');
const output=join(root,'dist/readme-previews');
const profile=await mkdtemp(join(tmpdir(),'solartt-docs-'));
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const GiB=1073741824;
const demoUser={id:'demo-user-alex',label:'Alex · Demo',status:'active',
  policy:{limit_bytes:100*GiB,device_limit:3,reset_monthly:true,expires_at:null},
  confirmed_bytes:24.5*GiB,charged_bytes:24.5*GiB,available_lease_bytes:0,pending_bytes:0,
  active_sessions:3,period_id:'demo-month',next_reset_at:null,
  credentials:[{id:'demo-phone',label:'Pixel · Phone',active_sessions:3,revoked:false},
    {id:'demo-laptop',label:'MacBook · Laptop',active_sessions:0,revoked:false}]};
const demoUsers=[demoUser,{...demoUser,id:'demo-user-sam',label:'Sam · Demo',
  confirmed_bytes:8.2*GiB,charged_bytes:8.2*GiB,active_sessions:0,
  credentials:[{id:'demo-tablet',label:'Tablet',active_sessions:0,revoked:false}]}];
const assets=new Map();
for(const [url,name,type] of [['/','index.html','text/html'],['/assets/style.css','style.css','text/css'],['/assets/app.js','app.js','text/javascript']]) {
  assets.set(url,{body:await readFile(join(root,'crates/panel/assets',name)),type});
}
const server=createServer((req,res)=>{
  const asset=assets.get(req.url);
  if(req.method!=='GET'||!asset){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':asset.type,'Cache-Control':'no-store'});res.end(asset.body);
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const origin=`http://127.0.0.1:${server.address().port}`;
const chrome=spawn(process.env.CHROME_BIN||'google-chrome',[
  '--headless=new','--no-sandbox','--disable-gpu','--no-first-run',
  '--no-default-browser-check','--disable-background-networking',
  '--disable-component-update','--disable-sync','--hide-scrollbars',
  '--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',
  `--user-data-dir=${profile}`,'about:blank'],{stdio:'ignore'});
let socket;
async function waitFor(fn,description){
  const deadline=Date.now()+30000;
  while(Date.now()<deadline){
    if(chrome.exitCode!==null||chrome.signalCode!==null)throw new Error('Chrome exited');
    try{if(await fn())return;}catch{}
    await pause(100);
  }
  throw new Error(`Timeout: ${description}`);
}
try {
  let port;
  await waitFor(async()=>{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];return !!port;},'Chrome');
  const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((r,j)=>{socket.addEventListener('open',r,{once:true});socket.addEventListener('error',j,{once:true});});
  let next=0;const pending=new Map();
  socket.addEventListener('message',e=>{
    const x=JSON.parse(e.data),p=pending.get(x.id);
    if(p){pending.delete(x.id);clearTimeout(p.timer);x.error?p.reject(new Error(x.error.message)):p.resolve(x.result);}
    else if(x.method==='Fetch.requestPaused'){
      const allowed=[...assets.keys()].some(path=>x.params.request.url===origin+path);
      call(allowed?'Fetch.continueRequest':'Fetch.failRequest',allowed?{requestId:x.params.requestId}:{requestId:x.params.requestId,errorReason:'BlockedByClient'}).catch(()=>{});
    }
  });
  function call(method,params={}){return new Promise((resolve,reject)=>{const id=++next;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout'));},15000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});}
  async function evaluate(expression){const x=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(x.exceptionDetails)throw new Error('Preview evaluation failed');return x.result.value;}
  await call('Page.enable');await call('Runtime.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:1060,deviceScaleFactor:2,mobile:true});
  // Reject every network request except the three local source assets.
  await call('Fetch.enable',{patterns:[{urlPattern:'*'}]});
  const fixture=`(()=>{
    const users=${JSON.stringify(demoUsers)};
    globalThis.fetch=async(url,options)=>{
      let data;
      if(url==='/api/session')data={csrf:'demo-only-not-a-session'};
      else if(url==='/api/command'){
        const {command:c}=JSON.parse(options.body);let result;
        if(c.op==='info')result={kind:'info',info:{api_version:1,period_timezone:'UTC',capabilities:['calendar_periods','audit','audited_profile_export','bounded_storage','device_profile_limits'],storage:null}};
        else if(c.op==='users')result={kind:'users',users,next_after:null};
        else throw new Error('Demo is read-only');
        data={desired_revision:12,applied_revision:12,result};
      }else throw new Error('Unexpected demo request');
      return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
    };
    globalThis.demoUser=users[0];
  })();`;
  await call('Page.addScriptToEvaluateOnNewDocument',{source:fixture});
  await call('Page.navigate',{url:origin});
  await waitFor(async()=>await evaluate('document.querySelectorAll(".user-card").length===2'),'mock users');
  assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'),'Mobile overflow');
  // Label the screenshots without changing the product assets or its layout.
  await evaluate('document.title="SolarTT-UI · Synthetic demo";document.querySelector(".brand small").textContent="DEMO · SYNTHETIC DATA"');
  await mkdir(output,{recursive:true});
  async function capture(name){await pause(200);const x=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(join(output,name),Buffer.from(x.data,'base64'));}
  await capture('mobile-users.png');
  await evaluate('openSettings(globalThis.demoUser);document.activeElement.blur()');
  assert(await evaluate('document.getElementById("edit").open && document.getElementById("edit-form").elements.device_limit.value==="3"'),'Mock access settings');
  await capture('mobile-access.png');
  await writeFile(join(output,'provenance.json'),JSON.stringify({synthetic:true,source:'crates/panel/assets',viewport:{width:390,height:1060,scale:2},screens:['mobile-users.png','mobile-access.png'],production_access:false},null,2)+'\n');
  console.log('Rendered two mobile UI previews using synthetic data only.');
}finally{
  socket?.close();
  if(chrome.exitCode===null){const done=new Promise(r=>chrome.once('exit',r));chrome.kill('SIGTERM');await Promise.race([done,pause(3000)]);if(chrome.exitCode===null){chrome.kill('SIGKILL');await done;}}
  await new Promise(r=>server.close(r));
  await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}
