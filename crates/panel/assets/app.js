"use strict";
const $ = id => document.getElementById(id);
let csrf = "", revision = 0, exported = null, editing = null, issuing = null, issueAttempt = null, auditBefore = null;
const show = (id, visible) => $(id).classList.toggle("hidden", !visible);
function message(id,text) { $(id).textContent=text; show(id,!!text); }
function notice(text) { message("notice",text); }
function node(tag,text,className) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(className)n.className=className; return n; }
function bytes(n) {
  if(n===0)return "0 B";
  const unit=Math.min(3,Math.floor(Math.log(n)/Math.log(1024)));
  return (n/Math.pow(1024,unit)).toFixed(unit===0?0:1)+" "+["B","KiB","MiB","GiB"][unit];
}
function activeProfiles(user) { return user.credentials.filter(c=>!c.revoked); }
function deviceLimit(user) { return user.policy.device_limit ?? 16; }
async function json(url,body) {
  const r=await fetch(url,{method:body===undefined?"GET":"POST",credentials:"same-origin",headers:body===undefined?{}:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:body===undefined?undefined:JSON.stringify(body)});
  if(r.status===401) {
    clearProfile(); for(const id of ["profile","issue","edit"])if($(id).open)$(id).close();
    show("login",true);show("dashboard",false);show("logout",false);
    const error=new Error("Sign in required");error.definitive=true;throw error;
  }
  if(r.status===204)return {};
  const data=await r.json();
  if(!r.ok) { const error=new Error(data.error||"Request failed");error.definitive=r.status<500;throw error; }
  return data;
}
async function sendCommand(request) {
  let result;
  try { result=await json("/api/command",request); }
  catch(error) { if(error instanceof TypeError)result=await json("/api/command",request);else throw error; }
  revision=result.desired_revision;
  $("revision").textContent="Policy revision "+revision+" · applied "+result.applied_revision;
  if(result.result.kind==="error") { const error=new Error(result.result.message);error.definitive=!["cleanup_pending","storage_unavailable"].includes(result.result.code);throw error; }
  return result.result;
}
async function command(command) { return sendCommand({request_id:crypto.randomUUID(),expected_revision:revision,command}); }
function action(label,handler,kind="quiet") {
  const b=node("button",label,kind);b.type="button";
  b.addEventListener("click",async()=>{b.disabled=true;try{notice("");await handler();}catch(e){notice(e.message);}finally{if(b.isConnected)b.disabled=false;}});
  return b;
}
function readPolicy(form) {
  const quota=form.elements.quota.value.trim(),expiry=form.elements.expiry.value,devices=form.elements.device_limit.value.trim();
  const limit=quota===""?null:Math.floor(Number(quota)*1073741824),device_limit=Number(devices);
  if(limit!==null&&(!Number.isSafeInteger(limit)||limit<0))throw new Error("Invalid traffic quota");
  if(devices===""||!Number.isInteger(device_limit)||device_limit<0||device_limit>16)throw new Error("Device profile limit must be a whole number from 0 to 16");
  if(device_limit<Number(form.elements.device_limit.min))throw new Error("Revoke a profile before lowering the device limit");
  return {limit_bytes:limit,expires_at:expiry?Math.floor(new Date(expiry).getTime()/1000):null,reset_monthly:form.elements.monthly.checked,device_limit};
}
function openSettings(user) {
  editing=user.id;const f=$("edit-form"),count=activeProfiles(user).length;
  f.elements.device_limit.min=String(count);f.elements.device_limit.value=deviceLimit(user);
  $("device-limit-help").textContent=count+" issued · minimum "+count+" · maximum 16. Revoked profiles do not count.";
  f.elements.monthly.checked=user.policy.reset_monthly;
  f.elements.quota.value=user.policy.limit_bytes===null?"":user.policy.limit_bytes/1073741824;
  const date=user.policy.expires_at?new Date(user.policy.expires_at*1000):null;
  f.elements.expiry.value=date?new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16):"";
  message("edit-error","");$("edit").showModal();
}
function openIssue(user) {
  if(issueAttempt&&issueAttempt.command.user_id!==user.id)throw new Error("Resolve the pending device creation before adding a different device");
  issuing=user;const f=$("issue-form");
  f.elements.label.value=issueAttempt?issueAttempt.command.label:"";
  f.elements.label.readOnly=!!issueAttempt;
  $("issue-owner").textContent="For "+user.label+" · "+activeProfiles(user).length+" of "+deviceLimit(user)+" profiles issued";
  $("issue-submit").textContent=issueAttempt?"Retry creation":"Create connection profile";
  message("issue-error",issueAttempt?"The previous result is unknown. Retry checks the same request; it will not create a second profile.":"");
  $("issue").showModal();f.elements.label.focus();
}
async function openProfile(credentialId,label) {
  clearProfile();
  const result=await command({op:"export_profile",credential_id:credentialId});
  if(!result.deeplink.startsWith("tt://"))throw new Error("Unsupported profile link");
  exported=result;$("profile-title").textContent="Connect "+label;
  $("deeplink").value=result.deeplink;$("open-app").href=result.deeplink;
  $("qr").src="data:image/svg+xml;base64,"+btoa(unescape(encodeURIComponent(result.qr_svg)));
  $("profile").showModal();
}
function renderDevice(credential) {
  const card=node("div",undefined,"device-card");card.dataset.credentialId=credential.id;
  const heading=node("div",undefined,"device-heading"),icon=node("span","▯","device-icon");icon.setAttribute("aria-hidden","true");
  const title=node("div");title.append(node("div",credential.label,"device-name"),node("div",credential.active_sessions>0?"Profile connected":"No active connection","device-status"+(credential.active_sessions>0?" connected":"")));
  heading.append(icon,title);
  const controls=node("div",undefined,"device-actions");
  const connect=action("Connection profile",()=>openProfile(credential.id,credential.label),"connect-profile");
  const more=node("details",undefined,"device-menu"),summary=node("summary","More");summary.setAttribute("aria-label","More actions for "+credential.label);
  const options=node("div",undefined,"menu-options");
  options.append(
    action("Change password",async()=>{if(confirm("Replace this profile's password and close its TLS connections? You will need to import the new profile.")){await command({op:"rotate_credential",credential_id:credential.id});await refresh();await openProfile(credential.id,credential.label);}}),
    action("Revoke access",async()=>{if(confirm("Revoke "+credential.label+"? Its connections will close and its device slot will become available.")){await command({op:"revoke_credential",credential_id:credential.id});await refresh();}},"danger")
  );
  more.append(summary,options);controls.append(connect,more);card.append(heading,controls);return card;
}
function renderUser(user) {
  const card=node("article",undefined,"user-card");card.dataset.userId=user.id;
  const heading=node("div",undefined,"user-heading"),identity=node("div");
  identity.append(node("h2",user.label),node("span",user.status.replaceAll("_"," "),"status "+user.status));
  heading.append(identity,action("Access settings",()=>openSettings(user),"quiet access-settings"));
  const metrics=node("div",undefined,"user-metrics"),traffic=node("div"),devices=node("div"),active=activeProfiles(user),limit=deviceLimit(user);
  traffic.append(node("span","Traffic","metric-label"),node("div",bytes(user.confirmed_bytes)+" / "+(user.policy.limit_bytes===null?"Unlimited":bytes(user.policy.limit_bytes)),"metric-value"));
  if(user.policy.limit_bytes!==null) {
    traffic.append(node("div",bytes(Math.max(0,user.policy.limit_bytes-user.charged_bytes+user.available_lease_bytes))+" remaining","metric-secondary"));
    const track=node("div",undefined,"quota-track"),fill=node("div",undefined,"quota-fill");
    fill.style.width=Math.min(100,user.policy.limit_bytes===0?100:100*user.confirmed_bytes/user.policy.limit_bytes)+"%";track.append(fill);traffic.append(track);
  }
  devices.append(node("span","Device profiles","metric-label"),node("div",active.length+" / "+limit+" issued","metric-value device-count"),node("div",Math.max(0,limit-active.length)+" slots available","metric-secondary"));
  metrics.append(traffic,devices);
  const deviceHeading=node("div",undefined,"devices-heading");
  const pending=issueAttempt?.command.user_id===user.id;
  const add=action(pending?"Resume setup":"Add device",()=>openIssue(user),"add-device");
  add.disabled=active.length>=limit&&!pending;
  if(add.disabled)add.title="Device limit reached. Raise the limit in Access settings or revoke a profile.";
  deviceHeading.append(node("h3","Devices"),add);
  const grid=node("div",undefined,"device-grid");
  for(const credential of active)grid.append(renderDevice(credential));
  if(!active.length)grid.append(node("p",limit===0?"Issuing is disabled. Raise the device limit in Access settings.":"No device profiles yet. Add a device to get its connection link and QR code.","empty-devices"));
  card.append(heading,metrics,deviceHeading,grid);
  const revoked=user.credentials.filter(c=>c.revoked);
  if(revoked.length) {const list=node("details",undefined,"revoked-list");list.append(node("summary","Revoked profiles · "+revoked.length));for(const credential of revoked)list.append(node("div",credential.label+" · access revoked","revoked-item"));card.append(list);}
  const more=node("details",undefined,"user-more"),controls=node("div",undefined,"row");
  controls.append(
    action(user.status==="blocked"?"Unblock user":"Block user",async()=>{if(user.status==="blocked"||confirm("Block this user and close all their device connections?")){await command({op:"block_user",user_id:user.id,blocked:user.status!=="blocked"});await refresh();}},user.status==="blocked"?"quiet":"danger"),
    action("Reset traffic quota",async()=>{if(confirm("Start a new traffic quota period? Device profiles and their limit will be preserved.")){await command({op:"start_period",user_id:user.id,period_id:"manual-"+crypto.randomUUID()});await refresh();}})
  );
  more.append(node("summary","More user actions"),controls);
  const technical=node("details",undefined,"connection-details");
  technical.append(node("summary","Connection details"),node("p","TLS connections: "+user.active_sessions+". A profile can have several connections; this is not a device count.","small muted"),node("p","Quota period: "+user.period_id,"small muted"));
  if(user.policy.expires_at)technical.append(node("p","Access expires: "+new Date(user.policy.expires_at*1000).toLocaleString(),"small muted"));
  if(user.next_reset_at)technical.append(node("p","Traffic resets: "+new Date(user.next_reset_at*1000).toLocaleString(),"small muted"));
  const uncertain=Math.max(0,user.charged_bytes-user.available_lease_bytes-user.pending_bytes-user.confirmed_bytes);
  if(uncertain)technical.append(node("p","Uncertain usage: "+bytes(uncertain),"small muted"));
  card.append(more,technical);return card;
}
async function refresh() {
  const info=await command({op:"info"});
  if(info.kind!=="info"||info.info.api_version!==1)throw new Error("Unsupported agent API");
  for(const capability of ["calendar_periods","audit","audited_profile_export","bounded_storage","device_profile_limits"])
    if(!info.info.capabilities.includes(capability))throw new Error("Update the agent to use device profile limits");
  const users=[];let after=null,snapshot=null;
  do {
    const page=await command({op:"users",after});
    if(snapshot!==null&&revision!==snapshot)throw new Error("Policy changed while loading users. Refresh again.");
    snapshot=revision;users.push(...page.users);after=page.next_after;
  } while(after!==null);
  $("timezone").textContent=info.info.period_timezone;
  const storage=info.info.storage;
  $("storage").textContent=storage?(storage.last_write_failed?"Storage write failed. ":"")+"Audit: "+storage.audit_rows+"/"+storage.audit_max_rows+" entries, up to "+storage.audit_max_days+" days. Retry receipts: "+storage.request_rows+"/"+storage.request_max_rows+", up to "+storage.request_max_days+" days. Quota history is preserved.":"Storage status unavailable.";
  $("users").replaceChildren();$("stats").replaceChildren();
  const connected=users.reduce((n,u)=>n+u.credentials.filter(c=>c.active_sessions>0).length,0);
  for(const [value,label] of [[users.length,"Users"],[users.filter(u=>u.status==="active").length,"With access"],[connected,"Connected profiles"]]) {
    const card=node("div",undefined,"stat");card.append(node("strong",String(value)),node("span",label));$("stats").append(card);
  }
  show("empty",users.length===0);for(const user of users)$("users").append(renderUser(user));
}
async function signedIn(){show("login",false);show("dashboard",true);show("logout",true);await refresh();}
$("login-form").addEventListener("submit",async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector("button");b.disabled=true;try{notice("");const result=await json("/api/login",{username:f.elements.username.value,password:f.elements.password.value});f.elements.password.value="";csrf=result.csrf;await signedIn();}catch(e){notice(e.message);}finally{b.disabled=false;}});
$("create-form").addEventListener("submit",async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector("button");if(b.disabled)return;b.disabled=true;try{notice("");await command({op:"create_user",label:f.elements.label.value,policy:readPolicy(f)});f.reset();$("create-form").closest("details").open=false;await refresh();}catch(e){notice(e.message);}finally{b.disabled=false;}});
$("edit-form").addEventListener("submit",async e=>{e.preventDefault();const b=e.currentTarget.querySelector("button");if(b.disabled)return;b.disabled=true;try{message("edit-error","");await command({op:"set_policy",user_id:editing,policy:readPolicy(e.currentTarget)});$("edit").close();await refresh();}catch(e){message("edit-error",e.message);}finally{b.disabled=false;}});
$("issue-form").addEventListener("submit",async e=>{
  e.preventDefault();const f=e.currentTarget,b=$("issue-submit");if(b.disabled||!issuing)return;b.disabled=true;message("issue-error","");
  if(!issueAttempt)issueAttempt={request_id:crypto.randomUUID(),expected_revision:revision,command:{op:"create_credential",user_id:issuing.id,label:f.elements.label.value.trim()}};
  try {
    const result=await sendCommand(issueAttempt),label=issueAttempt.command.label;
    issueAttempt=null;f.elements.label.readOnly=false;$("issue").close();f.reset();await refresh();
    try {await openProfile(result.resource_id,label);}catch(e){notice("Device profile created. Open its Connection profile button to retrieve the link. "+e.message);}
  } catch(e) {
    if(e.definitive)issueAttempt=null;
    f.elements.label.readOnly=!!issueAttempt;$("issue-submit").textContent=issueAttempt?"Retry creation":"Create connection profile";
    message("issue-error",e.message+(issueAttempt?" Retry uses the same request and will not issue another profile.":""));
  } finally {b.disabled=false;}
});
document.querySelectorAll("[data-device-name]").forEach(b=>b.addEventListener("click",()=>{if(!issueAttempt){$("issue-form").elements.label.value=b.dataset.deviceName;$("issue-form").elements.label.focus();}}));
$("cancel-issue").addEventListener("click",()=>$("issue").close());
$("cancel-edit").addEventListener("click",()=>$("edit").close());
$("logout").addEventListener("click",async()=>{try{await json("/api/logout",{});issueAttempt=null;location.reload();}catch(e){notice(e.message);}});
$("refresh").addEventListener("click",()=>refresh().catch(e=>notice(e.message)));
function clearProfile(){exported=null;$("deeplink").value="";$("qr").removeAttribute("src");$("open-app").removeAttribute("href");$("profile-status").textContent="";document.querySelector(".profile-format").open=false;}
$("close-profile").addEventListener("click",()=>$("profile").close());$("profile").addEventListener("close",clearProfile);
$("copy-link").addEventListener("click",async()=>{if(!exported)return;try{await navigator.clipboard.writeText($("deeplink").value);$("profile-status").textContent="Connection link copied.";}catch{document.querySelector(".profile-format").open=true;$("deeplink").select();$("profile-status").textContent="Select and copy the connection link manually.";}});
$("download-toml").addEventListener("click",()=>{if(!exported)return;const url=URL.createObjectURL(new Blob([exported.toml],{type:"text/plain"}));const a=node("a");a.href=url;a.download="trusttunnel-profile.toml";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
async function audit(reset) {
  if(reset){auditBefore=null;$("audit-rows").replaceChildren();}
  const result=await command({op:"audit",before:auditBefore});
  for(const item of result.entries){const tr=node("tr");tr.append(node("td",new Date(item.timestamp*1000).toLocaleString()),node("td",String(item.revision)),node("td",item.operation),node("td",item.subject||"—"),node("td",item.actor_uid==null?"Unknown / internal":String(item.actor_uid)),node("td",item.credential_id||"—"));$("audit-rows").append(tr);}
  auditBefore=result.next_before;$("audit-more").disabled=auditBefore===null;
}
$("audit-refresh").addEventListener("click",()=>audit(true).catch(e=>notice(e.message)));
$("audit-more").addEventListener("click",()=>audit(false).catch(e=>notice(e.message)));
json("/api/session").then(s=>{csrf=s.csrf;return signedIn();}).catch(e=>{show("login",true);if(e.message!=="Sign in required")notice(e.message);});
