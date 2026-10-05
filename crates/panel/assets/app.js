"use strict";
const $ = id => document.getElementById(id);
let csrf = "", revision = 0, exported = null, editing = null, auditBefore = null;
const show = (id, visible) => $(id).classList.toggle("hidden", !visible);
function notice(text) { $("notice").textContent = text; show("notice", !!text); }
function node(tag, text, className) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; }
function bytes(n) { return (n / 1073741824).toFixed(3) + " GiB"; }
async function json(url, body) {
  const r = await fetch(url, { method: body === undefined ? "GET" : "POST", credentials: "same-origin", headers: body === undefined ? {} : {"Content-Type":"application/json", "X-CSRF-Token":csrf}, body: body === undefined ? undefined : JSON.stringify(body) });
  if (r.status === 401) { clearProfile(); if ($("profile").open) $("profile").close(); show("login", true); show("dashboard", false); show("logout", false); throw new Error("Sign in required"); }
  if (r.status === 204) return {};
  const data = await r.json(); if (!r.ok) throw new Error(data.error || "Request failed"); return data;
}
async function command(command) {
  const request = { request_id: crypto.randomUUID(), expected_revision: revision, command };
  let result;
  // A network retry uses the identical idempotency key and payload.
  try { result = await json("/api/command", request); } catch (error) {
    if (error instanceof TypeError) result = await json("/api/command", request); else throw error;
  }
  revision = result.desired_revision;
  $("revision").textContent = `Policy revision ${revision} · applied ${result.applied_revision}`;
  if (result.result.kind === "error") throw new Error(result.result.message);
  return result.result;
}
function action(label, handler, kind = "quiet") {
  const b = node("button", label, kind); b.type = "button";
  b.addEventListener("click", async () => { b.disabled = true; try { notice(""); await handler(); } catch (e) { notice(e.message); } finally { b.disabled = false; } }); return b;
}
function readPolicy(form) {
  const quota = form.elements.quota.value.trim(), expiry = form.elements.expiry.value;
  const limit = quota === "" ? null : Math.floor(Number(quota) * 1073741824);
  if (limit !== null && (!Number.isSafeInteger(limit) || limit < 0)) throw new Error("Invalid traffic quota");
  return { limit_bytes: limit, expires_at: expiry ? Math.floor(new Date(expiry).getTime()/1000) : null, reset_monthly: form.elements.monthly.checked };
}
async function refresh() {
  const info = await command({op:"info"});
  if (info.kind !== "info" || info.info.api_version !== 1) throw new Error("Unsupported agent API");
  const users = []; let after = null, snapshot = null;
  do {
    const page = await command({op:"users",after});
    if (snapshot !== null && revision !== snapshot) throw new Error("Policy changed while loading users. Refresh again.");
    snapshot = revision; users.push(...page.users); after = page.next_after;
  } while (after !== null);
  $("timezone").textContent = info.info.period_timezone;
  if (!info.info.capabilities.includes("calendar_periods") || !info.info.capabilities.includes("audit")) throw new Error("Agent is missing required capabilities");
  $("users").replaceChildren(); $("stats").replaceChildren();
  for (const [value, label] of [[users.length,"Users"],[users.reduce((n,u)=>n+u.active_sessions,0),"Active sessions"],[users.filter(u=>u.status==="active").length,"Users with access"]]) {
    const card = node("div", undefined, "stat"); card.append(node("strong",String(value)),node("span",label)); $("stats").append(card);
  }
  show("empty", users.length === 0);
  for (const user of users) {
    const tr = node("tr"), identity = node("td"); identity.append(node("strong",user.label));
    for (const credential of user.credentials) {
      const item = node("div",undefined,"credential"); item.append(node("span",credential.label + (credential.revoked ? " · revoked" : "")));
      if (!credential.revoked) {
        item.append(action("Profile",async()=>{
          exported = await command({op:"export_profile",credential_id:credential.id});
          $("deeplink").value = exported.deeplink; $("qr").src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(exported.qr_svg))); $("profile").showModal();
        }), action("Rotate",async()=>{if(confirm("Replace this profile's password and close its active sessions?")) {await command({op:"rotate_credential",credential_id:credential.id});await refresh();}}),
        action("Revoke",async()=>{if(confirm("Revoke this profile and close its sessions?")) {await command({op:"revoke_credential",credential_id:credential.id});await refresh();}},"danger"));
      }
      identity.append(item);
    }
    const access = node("td"); access.append(node("span",user.status.replaceAll("_"," "),"status "+user.status));
    if (user.policy.expires_at) access.append(node("div",new Date(user.policy.expires_at*1000).toLocaleString(),"small muted"));
    if (user.next_reset_at) access.append(node("div", "Resets: " + new Date(user.next_reset_at*1000).toLocaleString(), "small muted"));
    const usage = node("td"); usage.append(node("div",bytes(user.confirmed_bytes) + " / " + (user.policy.limit_bytes===null?"unlimited":bytes(user.policy.limit_bytes))),
      node("div",`Remaining allowance: ${user.policy.limit_bytes===null?"unlimited":bytes(Math.max(0,user.policy.limit_bytes-user.charged_bytes+user.available_lease_bytes))}`,"small muted"),node("div",`Uncertain usage: ${bytes(Math.max(0,user.charged_bytes-user.available_lease_bytes-user.pending_bytes-user.confirmed_bytes))}`,"small muted"),node("div",user.period_id,"small muted"));
    const manage = node("td"), controls = node("div",undefined,"row");
    controls.append(action("Issue profile",async()=>{const label=prompt("Profile label (for example, Phone)","Phone");if(label){await command({op:"create_credential",user_id:user.id,label});await refresh();}}),
      action(user.status==="blocked"?"Unblock":"Block",async()=>{await command({op:"block_user",user_id:user.id,blocked:user.status!=="blocked"});await refresh();},user.status==="blocked"?"quiet":"danger"),
      action("Policy",async()=>{editing=user.id;const f=$("edit-form");f.elements.monthly.checked=user.policy.reset_monthly;f.elements.quota.value=user.policy.limit_bytes===null?"":user.policy.limit_bytes/1073741824;
        const date=user.policy.expires_at?new Date(user.policy.expires_at*1000):null;f.elements.expiry.value=date?new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16):"";$("edit").showModal();}),
      action("Reset quota",async()=>{if(confirm("Start a new quota period? This action is recorded.")){await command({op:"start_period",user_id:user.id,period_id:"manual-"+crypto.randomUUID()});await refresh();}}));
    manage.append(controls);tr.append(identity,access,usage,node("td",String(user.active_sessions)),manage);$("users").append(tr);
  }
}
async function signedIn() {show("login",false);show("dashboard",true);show("logout",true);await refresh();}
$("login-form").addEventListener("submit",async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector("button");b.disabled=true;try{notice("");const result=await json("/api/login",{username:f.elements.username.value,password:f.elements.password.value});f.elements.password.value="";csrf=result.csrf;await signedIn();}catch(e){notice(e.message);}finally{b.disabled=false;}});
$("create-form").addEventListener("submit",async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector("button");if(b.disabled)return;b.disabled=true;try{await command({op:"create_user",label:f.elements.label.value,policy:readPolicy(f)});f.reset();await refresh();}catch(e){notice(e.message);}finally{b.disabled=false;}});
$("edit-form").addEventListener("submit",async e=>{e.preventDefault();const b=e.currentTarget.querySelector("button");if(b.disabled)return;b.disabled=true;try{await command({op:"set_policy",user_id:editing,policy:readPolicy(e.currentTarget)});$("edit").close();await refresh();}catch(e){notice(e.message);}finally{b.disabled=false;}});
$("logout").addEventListener("click",async()=>{try{await json("/api/logout",{});location.reload();}catch(e){notice(e.message);}});
$("refresh").addEventListener("click",()=>refresh().catch(e=>notice(e.message)));
$("cancel-edit").addEventListener("click",()=>$("edit").close());
function clearProfile(){exported=null;$("deeplink").value="";$("qr").removeAttribute("src");}
$("close-profile").addEventListener("click",()=>$("profile").close());$("profile").addEventListener("close",clearProfile);
$("copy-link").addEventListener("click",()=>navigator.clipboard.writeText($("deeplink").value).catch(()=>notice("Select and copy the profile link manually.")));
$("download-toml").addEventListener("click",()=>{if(!exported)return;const url=URL.createObjectURL(new Blob([exported.toml],{type:"text/plain"}));const a=node("a");a.href=url;a.download="trusttunnel-profile.toml";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
json("/api/session").then(s=>{csrf=s.csrf;return signedIn();}).catch(e=>{show("login",true);if(e.message!=="Sign in required")notice(e.message);});

async function audit(reset) {
  if (reset) { auditBefore = null; $("audit-rows").replaceChildren(); }
  const result = await command({op:"audit",before:auditBefore});
  for (const item of result.entries) {
    const tr=node("tr");tr.append(node("td",new Date(item.timestamp*1000).toLocaleString()),node("td",String(item.revision)),node("td",item.operation),node("td",item.subject || "—"));$("audit-rows").append(tr);
  }
  auditBefore=result.next_before;$("audit-more").disabled=auditBefore===null;
}
$("audit-refresh").addEventListener("click",()=>audit(true).catch(e=>notice(e.message)));
$("audit-more").addEventListener("click",()=>audit(false).catch(e=>notice(e.message)));
