// App shell only. Never cache /api responses or private user data.
const CACHE='executive-desk-v16-upcoming-fixed-button-20261114';
const FILES=['./','./index.html','./cloud.js','./eda-upgrades.css','./eda-upgrades.js','./manifest.webmanifest','./icon-192.png','./icon-512.png','./apple-touch-icon.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(FILES)));self.skipWaiting();});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim();});
self.addEventListener('fetch',e=>{
 const req=e.request,u=new URL(req.url);
 if(req.method!=='GET'||u.origin!==self.location.origin||u.pathname.startsWith('/api/'))return;
 e.respondWith(fetch(req).then(res=>{if(res.ok&&/\.(?:html|js|css|webmanifest|png)$/.test(u.pathname)){const c=res.clone();caches.open(CACHE).then(cache=>cache.put(req,c));}return res;}).catch(()=>caches.match(req).then(v=>v||caches.match('./index.html'))));
});

// Background Web Push (RFC 8291). Payload is JSON: {title, body, url, tag}.
self.addEventListener('push',e=>{
 let data={title:'Executive Desk AI',body:'You have an update.',url:'./',tag:'eda-reminder'};
 if(e.data){try{const parsed=e.data.json();if(parsed&&typeof parsed==='object')data={...data,...parsed};}catch{try{data.body=e.data.text()||data.body}catch{}}}
 e.waitUntil(self.registration.showNotification(data.title,{body:data.body,icon:'./icon-192.png',badge:'./icon-192.png',tag:data.tag,renotify:true,data:{url:data.url||'./'}}));
});

self.addEventListener('notificationclick',e=>{
 e.notification.close();
 const target=new URL(e.notification.data?.url||'./',self.location.origin).href;
 e.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(list=>{
  for(const c of list){if(c.url===target&&'focus' in c)return c.focus();}
  if(self.clients.openWindow)return self.clients.openWindow(target);
 }));
});
