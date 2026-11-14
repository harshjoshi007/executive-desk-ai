/* Executive Desk AI V16 Full Project — authenticated same-origin backend client.
 * App records live on the server, never in browser-only localStorage once signed in.
 * Session token is a server-controlled HttpOnly cookie; only CSRF is held in memory.
 *
 * Google Sign-In, Google Calendar sync (two-way) and Web Push notifications are
 * real integrations backed by the FastAPI server and Google's live endpoints.
 * When Google credentials are not configured the UI shows a clear error instead
 * of pretending to be connected.
 */
(()=>{
'use strict';
const s={active:true, ready:false, email:'', csrf:'', revision:0, pending:null, base:null,
  pendingSeq:0, ackSeq:0, busy:false, conflict:false, error:'', notice:'', status:'Sign in required',
  lastSync:0, timer:null, debounce:null, booting:true,
  googleConfigured:false, google:{configured:false,connected:false,email:null,calendar_scope:false,gmail_scope:false,
    push_ready:false,push_public_key:null,push_devices:0}, notified:{}, googleBusy:false,
  whatsapp:{configured:false,mode:'template',template:'',number:'',enabled:false,last_error:''},
  email:{configured:false,enabled:false,from:'',address:''}};
const PENDING_KEY='eda-v16-unsynced-v1';
const safe=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const copy=x=>JSON.parse(JSON.stringify(x));
function localPending(){try{const p=JSON.parse(localStorage.getItem(PENDING_KEY)||'null');return p&&p.email===s.email?p.payload:null}catch{return null}}
function preserve(){try{if(s.pending)localStorage.setItem(PENDING_KEY,JSON.stringify({email:s.email,payload:s.pending,at:Date.now()}));else localStorage.removeItem(PENDING_KEY)}catch(e){s.error='Browser storage unavailable: download a backup now'}}
function loginHTML(){const showForm=!s.booting;const feedback=s.error||s.notice;return `<div class="v14-login-screen"><section class="v14-login-card"><div class="v14-login-brand">✦ Executive Desk AI <span class="v14-version">Full project</span></div><h1>${s.booting?'Opening your workspace':'Sign in to your private workspace'}</h1><p>One account keeps your tasks, calendar, notes, memory, daily plan and history the same across devices.</p>${s.booting?'<p>Checking your account…</p>':`<form id="eda-server-login"><label>Email<input name="email" type="email" autocomplete="username" placeholder="you@company.com" required></label><label>Password<input name="password" type="password" autocomplete="current-password" required></label><button type="submit">Sign in</button></form>${s.googleConfigured?'<div class="v14-login-sep"><span>or</span></div><button type="button" id="eda-google-login" class="v14-google-btn">Sign in with Google</button>':''}`}<p class="v14-login-feedback" role="alert">${safe(feedback)}</p><p style="font-size:12px">Create your private account with <b>python manage.py add-user</b> on the server first, or sign in with Google once Google credentials are configured. This is a real server-based workspace.</p></section></div>`;}
function label(){return s.status;}
function panelHTML(){return `<div class="page-header"><div><div class="eyebrow">PRIVATE WORKSPACE</div><h1>Account & sync</h1><p class="subhead">Saved to one central database. Open this exact website address on your laptop, iPhone, or Android.</p></div></div><div class="card" style="padding:20px;max-width:780px"><div class="settingsrow"><div><b>Signed in</b><small>${safe(s.email)}</small></div><span class="status-pill">${safe(s.status)}</span></div><div class="settingsrow"><div><b>Server revision</b><small>${s.revision} · ${s.lastSync?new Date(s.lastSync).toLocaleString():'Waiting for sync'}</small></div><button class="btn subtle" data-server-action="refresh">Refresh now</button></div>${s.error?`<div class="v14-sync-conflict" role="alert">${safe(s.error)}</div>`:''}<p>Changes are saved on the server and automatically checked on other devices. Use the same login on every device.</p><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:16px"><button class="btn subtle" data-server-action="download">Download JSON backup</button><button class="btn subtle" data-server-action="import">Import backup</button><button class="btn subtle" data-server-action="logout">Sign out</button></div><input id="eda-import-file" type="file" accept="application/json,.json" hidden>${s.conflict?`<div class="v14-sync-conflict"><b>Needs review: newer data on another device.</b><p>Your edits are kept locally until you decide how to resolve them.</p><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn subtle" data-server-action="download">Download my edits</button><button class="btn subtle" data-server-action="use-cloud">Use latest cloud data</button><button class="btn" data-server-action="replace-cloud">Replace cloud with my edits (review)</button></div></div>`:''}</div>`;}
async function request(path,options={}){
 const headers={'Accept':'application/json',...(options.body?{'Content-Type':'application/json'}:{}),...(options.method && !['GET','HEAD'].includes(options.method)?{'X-EDA-CSRF':s.csrf}:{})};
 const r=await fetch('/api/'+path,{...options,headers:{...headers,...options.headers},credentials:'same-origin',cache:'no-store'});
 let v={};try{v=await r.json()}catch{}
 if(!r.ok){const e=new Error(v.detail||v.message||'Request failed ('+r.status+')');e.code=r.status;e.info=v;throw e;}
 return v;
}
function paint(){const el=document.querySelector('.v14-sync-button span');if(el)el.textContent=s.status;}
function download(payload,filename){const b=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}
async function openWorkspace(){const row=await request('workspace');s.revision=row.revision;s.base=copy(row.payload);s.ready=true;s.booting=false;s.status='Synced';s.error='';s.lastSync=Date.now();const old=localPending();if(old){s.pending=old;s.conflict=true;s.status='Needs review';}window.EDA_SET_WORKSPACE(row.payload);refreshGoogle();refreshWhatsApp();refreshEmail();if(s.timer)clearInterval(s.timer);s.timer=setInterval(()=>{if(!document.hidden&&navigator.onLine!==false){inAppNotify();if(s.pending&&!s.conflict)flush();else poll()}},4000);paint();}
async function login(email,password){s.booting=true;s.error='';s.notice='';window.render();try{
 const reply=await request('auth/login',{method:'POST',body:JSON.stringify({email,password})});s.email=reply.email;s.csrf=reply.csrf;await openWorkspace();
 }catch(e){s.booting=false;s.ready=false;s.error=e.message;s.status='Sign in required';window.render();}}
async function resume(){try{const session=await request('auth/session');const token=await request('auth/csrf',{method:'POST'});s.email=session.email;s.csrf=token.csrf;await openWorkspace();}catch(e){s.ready=false;s.booting=false;s.status='Sign in required';if(!s.notice)s.error='';window.render();}}
function save(payload){if(!s.ready){s.error='Sign in to save changes';paint();return;}
 s.pending=copy(payload);s.pendingSeq++;preserve();s.status=s.conflict?'Needs review':'Saving…';paint();
 if(!s.conflict){clearTimeout(s.debounce);s.debounce=setTimeout(flush,550)}
}
async function flush(){if(!s.ready||s.busy||s.conflict||!s.pending||navigator.onLine===false)return;
 s.busy=true;const latest=copy(s.pending),seq=s.pendingSeq;
 try{const r=await request('workspace',{method:'PUT',body:JSON.stringify({expected_revision:s.revision,payload:latest})});
  s.revision=r.revision;s.base=latest;s.lastSync=Date.now();s.error='';s.ackSeq=seq;
  if(s.pendingSeq===seq){s.pending=null;preserve();s.status='Synced'}else s.status='Saving…';
 }catch(e){s.error=e.message;if(e.code===409){s.conflict=true;s.status='Needs review'}else if(e.code===401){s.conflict=true;s.status='Session expired'}else s.status='Offline · retry';
 }finally{s.busy=false;paint();if(s.pending&&!s.conflict&&s.ackSeq<s.pendingSeq&&s.status!=='Offline · retry')setTimeout(flush,500)}
}
async function poll(){if(!s.ready||s.busy||s.pending||s.conflict||navigator.onLine===false)return;
 try{const row=await request('workspace');if(row.revision!==s.revision){s.revision=row.revision;s.base=copy(row.payload);s.lastSync=Date.now();s.status='Synced';window.EDA_SET_WORKSPACE(row.payload);}else{s.status='Synced';s.lastSync=Date.now();paint()}}
 catch(e){s.error=e.message;s.status='Connection error';paint()}
}
async function action(kind){
 if(kind==='download'){download(s.pending||window.EDA_GET_WORKSPACE(),'executive-desk-backup-'+new Date().toISOString().slice(0,10)+'.json');return;}
 if(kind==='import'){document.querySelector('#eda-import-file')?.click();return;}
 if(kind==='logout'){if(s.pending && !confirm('Unsynced changes exist. Download a backup before signing out. Continue?'))return;
  await request('auth/logout',{method:'POST'});s.ready=false;s.csrf='';s.email='';s.pending=null;s.base=null;s.conflict=false;s.status='Sign in required';s.notified={};clearInterval(s.timer);localStorage.removeItem(PENDING_KEY);window.EDA_SET_WORKSPACE(window.freshWorkspace());window.render();return;}
 if(kind==='refresh'){if(s.pending){alert('You have unsynced edits. Download a backup and resolve them before refreshing.');return;}await poll();window.render();return;}
 if(kind==='use-cloud'){if(!confirm('Use the server version and discard these unsynced local edits? Download a backup first.'))return;
  const row=await request('workspace');s.pending=null;s.conflict=false;s.error='';s.revision=row.revision;s.base=copy(row.payload);s.status='Synced';preserve();window.EDA_SET_WORKSPACE(row.payload);return;}
 if(kind==='replace-cloud'){if(!s.pending)return;if(!confirm('Replace the newer server workspace with your local version? Changes on another device could be lost. Download both backups before proceeding.'))return;
  const row=await request('workspace');s.revision=row.revision;s.conflict=false;s.error='';s.pendingSeq++;s.status='Saving…';await flush();window.render();return;}
}

/* ----------------------------- Google / Calendar ------------------------- */
function urlBase64ToUint8Array(base64String){const padding='='.repeat((4-(base64String||'').length%4)%4);const base64=(base64String+padding).replace(/-/g,'+').replace(/_/g,'/');const raw=atob(base64);const out=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);return out;}
async function checkGoogleAvailable(){try{const r=await request('auth/google/available');s.googleConfigured=!!r.configured;}catch{s.googleConfigured=false;}}
function captureGoogleError(){try{const u=new URL(location.href);const m=u.searchParams.get('google_error');if(m){s.notice=m;u.searchParams.delete('google_error');history.replaceState({},'',u.pathname+(u.searchParams.toString()?'?'+u.searchParams.toString():'')+u.hash);}}catch{}}
async function refreshGoogle(){try{const g=await request('google/status');const changed=JSON.stringify(g)!==JSON.stringify(s.google);s.google=g;if(changed&&s.ready)window.render?.();return g;}catch(e){return s.google;}}
function googleStart(mode){location.href='/api/auth/google/start?mode='+encodeURIComponent(mode||'login')+'&next='+encodeURIComponent('/');}
async function googleDisconnect(){await request('google/disconnect',{method:'POST'});return refreshGoogle();}
async function calendarList(timeMin,timeMax){const r=await request('google/calendar/events?time_min='+encodeURIComponent(timeMin)+'&time_max='+encodeURIComponent(timeMax));return r.events;}
async function calendarCreate(ev){const r=await request('google/calendar/events',{method:'POST',body:JSON.stringify(ev)});return r.event;}
async function calendarUpdate(id,ev){const r=await request('google/calendar/events/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify(ev)});return r.event;}
async function calendarDelete(id){return request('google/calendar/events/'+encodeURIComponent(id),{method:'DELETE'});}
async function gmailDraft(d){return request('google/gmail/draft',{method:'POST',body:JSON.stringify(d)});}

/* -------------- Gmail Inbox, Send and per-message read status -------------- */
async function gmailList({label='INBOX',max_results=20,page_token='',query=''}={}){
 const q=new URLSearchParams({label,max_results:String(max_results),page_token,query});
 return request('google/gmail/messages?'+q.toString());
}
async function gmailGet(id){return request('google/gmail/messages/'+encodeURIComponent(id));}
async function gmailSetRead(id,read){return request('google/gmail/messages/'+encodeURIComponent(id)+'/read',
 {method:'POST',body:JSON.stringify({read:!!read})});}
async function gmailSend(payload){return request('google/gmail/send',
 {method:'POST',body:JSON.stringify(payload)});}
async function gmailSaveDraft(payload){return request('google/gmail/drafts/rich',
 {method:'POST',body:JSON.stringify(payload)});}
async function exportPdf(payload){
 if(!s.ready)throw new Error('Sign in before exporting');
 const r=await fetch('/api/exports/pdf',{method:'POST',credentials:'same-origin',cache:'no-store',
  headers:{'Content-Type':'application/json','X-EDA-CSRF':s.csrf},body:JSON.stringify(payload)});
 if(!r.ok){let problem={};try{problem=await r.json()}catch{}throw new Error(problem.detail||'PDF export failed ('+r.status+')')}
 return {blob:await r.blob()};
}

/* -------------------------------- WhatsApp -------------------------------- */
async function refreshWhatsApp(){try{const w=await request('whatsapp/status');const changed=JSON.stringify(w)!==JSON.stringify(s.whatsapp);s.whatsapp=w;if(changed&&s.ready)window.render?.();return w;}catch(e){return s.whatsapp;}}
async function whatsappSave(number,enabled){const r=await request('whatsapp/set',{method:'POST',body:JSON.stringify({phone_number:number,enabled:!!enabled})});await refreshWhatsApp();return r;}
async function whatsappDisable(){const r=await request('whatsapp/disable',{method:'POST'});await refreshWhatsApp();return r;}
async function whatsappTest(){const r=await request('whatsapp/test',{method:'POST'});await refreshWhatsApp();return r;}

/* ---------------------------------- Email --------------------------------- */
async function refreshEmail(){try{const r=await request('email/status');const e={configured:!!r.configured,enabled:!!r.enabled,from:r.from||'',address:r.address||s.email};const changed=JSON.stringify(e)!==JSON.stringify(s.email);s.email=e;if(changed&&s.ready)window.render?.();return e;}catch(err){return s.email;}}
async function emailTest(){return request('email/test',{method:'POST'});}

/* ---------------------------------- Push --------------------------------- */
function pushSupported(){return ('serviceWorker' in navigator) && ('PushManager' in window) && ('Notification' in window);}
function notifPermission(){return ('Notification' in window)?Notification.permission:'unsupported';}
async function pushEnable(){
 if(!pushSupported())throw new Error('This browser cannot do background notifications. Use Chrome or Safari over HTTPS (or localhost).');
 const perm=await Notification.requestPermission();
 if(perm!=='granted')throw new Error('Notification permission was not granted.');
 const reg=await navigator.serviceWorker.ready;
 const key=await request('push/key');
 const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlBase64ToUint8Array(key.public_key)});
 await request('push/subscribe',{method:'POST',body:JSON.stringify(sub.toJSON())});
 await refreshGoogle();
 return true;
}
async function pushDisable(){
 const reg=await navigator.serviceWorker.ready;
 const sub=await reg.pushManager.getSubscription();
 if(sub){await request('push/unsubscribe?endpoint='+encodeURIComponent(sub.endpoint),{method:'POST'}).catch(()=>{});await sub.unsubscribe().catch(()=>{});}
 else{await request('push/unsubscribe',{method:'POST'}).catch(()=>{});}
 await refreshGoogle();
 return true;
}
async function pushTest(){return request('push/test',{method:'POST'});}
// Foreground OS pop-ups while the tab is open (background push is server-side).
function inAppNotify(){
 if(!('Notification' in window)||Notification.permission!=='granted'||document.hidden)return;
 let ws;try{ws=window.EDA_GET_WORKSPACE?.()}catch{return}
 if(!ws)return;
 const now=Date.now(),horizon=now+10*60*1000;
 const fire=(key,title,body)=>{if(s.notified[key])return;s.notified[key]=true;try{new Notification(title,{body,icon:'./icon-192.png',tag:key});}catch{}};
 for(const t of (ws.tasks||[])){if(t.status==='Completed'||t.status==='Cancelled'||!t.due)continue;const dt=Date.parse(t.due);if(dt>=now&&dt<=horizon)fire('task:'+t.id+'@'+t.due,'Task due soon',t.title||'A task is due soon.');}
 for(const m of (ws.meetings||[])){if(m.status==='Cancelled'||!m.at)continue;const dt=Date.parse(m.at);if(dt>=now&&dt<=horizon)fire('meeting:'+m.id+'@'+m.at,'Meeting starting soon',(m.title||'Meeting')+(m.location?' · '+m.location:''));}
}

function wire(){document.addEventListener('submit',e=>{if(e.target.id==='eda-server-login'){e.preventDefault();const f=new FormData(e.target);login(String(f.get('email')||'').trim(),String(f.get('password')||''));}});
 document.addEventListener('click',e=>{if(e.target.closest('#eda-google-login')){e.preventDefault();googleStart('login');return;}
  const el=e.target.closest('[data-server-action]');if(el){e.preventDefault();action(el.dataset.serverAction).catch(err=>{s.error=err.message;window.render()})}});
 document.addEventListener('change',async e=>{if(e.target.id!=='eda-import-file'||!e.target.files?.[0])return;
  try{const json=JSON.parse(await e.target.files[0].text());if(json?.version!==1||!Array.isArray(json.tasks)||!Array.isArray(json.instructions))throw new Error('Invalid Executive Desk JSON');
   if(!confirm('Stage this backup for import? You will review and confirm before replacing the server copy.'))return;
   s.pending=json;s.conflict=true;s.status='Needs review';preserve();window.nav('More','activation');alert('Backup staged. Download the existing server backup, then select Replace cloud if appropriate.');}
  catch(err){alert('Backup import failed: '+err.message)}
 });
 window.addEventListener('online',()=>{if(s.ready){if(s.pending&&!s.conflict)flush();else poll()}});
 document.addEventListener('visibilitychange',()=>{if(s.ready&&!document.hidden){inAppNotify();if(s.pending&&!s.conflict)flush();else poll()}});
 window.addEventListener('beforeunload',e=>{if(s.pending&&s.status==='Saving…'){e.preventDefault();e.returnValue='';}});
}
async function init(){wire();captureGoogleError();await checkGoogleAvailable();await resume();}
window.edaCloud={active:true, gateHTML:loginHTML,panelHTML,label,save,init,rawState:s,
 googleState:()=>s.google, refreshGoogle, googleStart, googleDisconnect,
 calendarList, calendarCreate, calendarUpdate, calendarDelete, gmailDraft,
 gmailList, gmailGet, gmailSetRead, gmailSend, gmailSaveDraft, exportPdf,
 whatsappState:()=>s.whatsapp, refreshWhatsApp, whatsappSave, whatsappDisable, whatsappTest,
 emailState:()=>s.email, refreshEmail, emailTest,
 pushEnable, pushDisable, pushTest, pushSupported, notifPermission, inAppNotify};
Object.defineProperty(window.edaCloud,'ready',{get(){return s.ready}});
Object.defineProperty(window.edaCloud,'googleConfigured',{get(){return s.googleConfigured}});
window.addEventListener('DOMContentLoaded',init);
})();
