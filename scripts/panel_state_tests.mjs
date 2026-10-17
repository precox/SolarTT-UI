// Pure JavaScript regressions against the shipped script. No browser or network.
import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../crates/panel/assets/app.js',import.meta.url),'utf8');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const response=(status,body)=>({status,ok:status>=200&&status<300,json:async()=>body});
const applied=(revision,result)=>response(200,{desired_revision:revision,applied_revision:revision,result});
const manualIds=['name','address','hostname','sni','username','password','dns','random'].map(k=>'manual-'+k);
function harness(route,bootstrapReply=new Promise(()=>{})) {
  const elements=new Map();
  function element(id) {
    if(elements.has(id))return elements.get(id);
    const classes=new Set(),listeners=new Map();
    const e={id,value:'',type:'password',textContent:'',open:false,disabled:false,readOnly:false,elements:{},attrs:new Map(),
      classList:{toggle(c,on){on?classes.add(c):classes.delete(c);},contains(c){return classes.has(c);}},
      addEventListener(k,f){listeners.set(k,f);},trigger(k){return listeners.get(k)?.({preventDefault(){},currentTarget:e});},
      setAttribute(k,v){e.attrs.set(k,v);},removeAttribute(k){e.attrs.delete(k);},focus(){},select(){},
      close(){e.open=false;listeners.get('close')?.();},showModal(){e.open=true;},reset(){},append(){},replaceChildren(){},
      querySelector(){return element(id+'-button');}};
    elements.set(id,e);return e;
  }
  element('issue-form').elements.label=element('issue-label');
  element('login-form').elements.username=element('login-username');
  element('login-form').elements.password=element('login-password');
  const document={getElementById:element,createElement:tag=>element('created-'+elements.size+'-'+tag),querySelector:element,
    querySelectorAll:selector=>selector.startsWith('#manual-settings')?manualIds.map(element):[]};
  let serial=0,bootstrap=true;
  async function fetch(url,options) {
    if(bootstrap&&url==='/api/session'){bootstrap=false;return bootstrapReply;}
    if(url==='/api/login')return response(200,{csrf:'synthetic-csrf'});
    if(url==='/api/command') {
      const req=JSON.parse(options.body);
      if(req.command.op==='info')return applied(1,{kind:'info',info:{api_version:1,period_timezone:'UTC',capabilities:['calendar_periods','audit','audited_profile_export','bounded_storage','device_profile_limits']}});
      if(req.command.op==='users')return applied(1,{kind:'users',users:[],next_after:null});
    }
    return route(url,options);
  }
  const factory=new Function('document','fetch','crypto','navigator','location','btoa',source+'\nreturn {json,sendCommand,openProfile,openIssue,clearProfile,pending:()=>issueAttempt,exported:()=>exported};');
  const app=factory(document,fetch,{randomUUID:()=>`synthetic-request-${++serial}`},{},{reload(){throw new Error('Unexpected reload loses pending issuance');}},()=> 'synthetic-image');
  async function login(){element('login-form').elements.username.value='admin';element('login-form').elements.password.value='synthetic-admin-password';await element('login-form').trigger('submit');}
  async function submit(){await element('issue-form').trigger('submit');}
  return {app,element,login,submit};
}
function profile() {
  return applied(1,{kind:'profile',manual:{addresses:['192.0.2.1:443'],hostname:'media.example.test',custom_sni:'media.example.test',username:'synthetic-user',password:'synthetic-profile-password',dns_upstreams:[],client_random_prefix:null,certificate:null,upstream_protocol:'http2',skip_verification:false,anti_dpi:false,has_ipv6:false},deeplink:'tt://synthetic',qr_svg:'<svg/>',toml:'synthetic'});
}
function cleared(h) {
  assert.equal(h.element('profile').open,false,'profile must stay closed');
  assert.equal(h.app.exported(),null,'export must stay cleared');
  for(const id of manualIds)assert.equal(h.element(id).value,'','manual field must stay empty');
  assert.equal(h.element('deeplink').value,'');
  assert.equal(h.element('qr').attrs.has('src'),false);
}
for(const duringBody of [false,true])test(`late export after 401, body pending=${duringBody}`,async()=>{
  const fetchGate=deferred(),bodyGate=deferred(),bodyStarted=deferred();
  const h=harness(url=>url==='/expire'?response(401,{}):fetchGate.promise);
  const pending=h.app.openProfile('profile-A','Phone').catch(e=>e);
  if(duringBody){fetchGate.resolve({status:200,ok:true,json(){bodyStarted.resolve();return bodyGate.promise;}});await bodyStarted.promise;}
  await assert.rejects(h.app.json('/expire'));
  if(duringBody)bodyGate.resolve(await profile().json());else fetchGate.resolve(profile());
  await pending;cleared(h);
  assert.equal(h.element('login').classList.contains('hidden'),false);
});
test('old export and old 401 cannot replace a reauthenticated session',async()=>{
  const exportGate=deferred(),old401=deferred();
  const h=harness(url=>url==='/late-401'?old401.promise:exportGate.promise);
  const pending=h.app.openProfile('profile-A','Phone').catch(e=>e);
  const old=h.app.json('/late-401').catch(e=>e);
  await h.login();assert.equal(h.element('dashboard').classList.contains('hidden'),false);
  old401.resolve(response(401,{}));exportGate.resolve(profile());await Promise.all([pending,old]);
  cleared(h);assert.equal(h.element('dashboard').classList.contains('hidden'),false,'old 401 must not sign out new session');
});
for(const status of [200,401])test(`delayed bootstrap ${status} cannot replace a new login or CSRF token`,async()=>{
  const bootstrap=deferred();let token;
  const h=harness((url,options)=>{token=options.headers['X-CSRF-Token'];return response(200,{});},bootstrap.promise);
  await h.login();bootstrap.resolve(response(status,{csrf:'synthetic-old-csrf'}));
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.element('login').classList.contains('hidden'),true);
  assert.equal(h.element('dashboard').classList.contains('hidden'),false);
  await h.app.json('/probe',{});assert.equal(token,'synthetic-csrf');
});
test('network failure from an old session cannot retry under a new session',async()=>{
  const gate=deferred();let deliveries=0;
  const h=harness(()=>{deliveries++;return gate.promise;});
  const pending=h.app.sendCommand({request_id:'synthetic-old',expected_revision:0,command:{op:'create_credential'}}).catch(e=>e);
  await h.login();gate.reject(new TypeError('Synthetic network failure'));await pending;
  assert.equal(deliveries,1,'old request must not be retried with the new session');
});
test('closing a profile invalidates a pending export',async()=>{
  const gate=deferred(),h=harness(()=>gate.promise);
  const pending=h.app.openProfile('profile-A','Phone');h.app.clearProfile();gate.resolve(profile());await pending;cleared(h);
});
test('sign out invalidates pending export without reloading',async()=>{
  const gate=deferred(),h=harness(url=>url==='/api/logout'?response(204,{}):gate.promise);
  const pending=h.app.openProfile('profile-A','Phone').catch(e=>e);
  await h.element('logout').trigger('click');gate.resolve(profile());await pending;cleared(h);
  assert.equal(h.element('login').classList.contains('hidden'),false);
});
for(const status of [401,403])test(`lost issuance response, ${status}, reauthentication and same-key replay`,async()=>{
  const ids=[],receipts=new Map();let calls=0,revision=0;
  const h=harness((url,options)=>{
    if(url==='/api/logout')return response(204,{});
    const req=JSON.parse(options.body);if(req.command.op==='export_profile')return profile();ids.push(req.request_id);calls++;
    if(calls===2)return response(status,{error:status===403?'CSRF check failed':'Synthetic authentication rejection'});
    if(receipts.has(req.request_id))return applied(revision,{kind:'applied',resource_id:receipts.get(req.request_id)});
    assert.equal(req.expected_revision,revision,'authority must check the expected revision');
    revision++;receipts.set(req.request_id,'synthetic-profile');
    return response(503,{error:'Synthetic response lost after commit'});
  });
  const owner={id:'owner-A',label:'Owner A',credentials:[],policy:{device_limit:2}};
  h.app.openIssue(owner);h.element('issue-label').value='Phone';await h.submit();assert.ok(h.app.pending());
  await h.submit();assert.ok(h.app.pending(),'auth rejection cannot resolve an earlier unknown commit');
  assert.equal(h.element('login').classList.contains('hidden'),false,'reauthentication must be available without losing the pending ID');
  await h.element('logout').trigger('click');assert.ok(h.app.pending(),'sign out must retain pending issuance in this tab');
  await h.login();h.app.openIssue(owner);await h.submit();
  assert.equal(new Set(ids).size,1,'all retries must use the original ID');assert.equal(receipts.size,1,'exactly one profile can be created');
  assert.equal(h.app.pending(),null,'applied receipt resolves pending issuance');
});
test('expired retry history does not allow an automatic new issuance ID',async()=>{
  let calls=0;
  const h=harness(()=>++calls===1?response(503,{error:'Synthetic unknown outcome'}):applied(1,{kind:'error',code:'request_expired',message:'Synthetic expired receipt'}));
  const owner={id:'owner-A',label:'Owner A',credentials:[],policy:{device_limit:2}};
  h.app.openIssue(owner);h.element('issue-label').value='Phone';await h.submit();const id=h.app.pending().request_id;
  await h.submit();assert.equal(h.app.pending().request_id,id);assert.match(h.element('issue-error').textContent,/Review existing profiles and audit history/);
});
