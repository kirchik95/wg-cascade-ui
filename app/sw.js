const C='wgui-shell-v28';
const NET_WAIT_MS=4000;
const SHELL=[
 '/','/index.html','/login','/login.html',
 '/app.css','/modals.css','/pages.css',
 '/core.js','/dashboard.js','/modals.js','/pages.js',
 '/boot.js','/theme.js','/login.js',
 '/icon.svg','/apple-touch-icon.png','/manifest.webmanifest'
];
function sameOrigin(url){
 try{return new URL(url).origin===self.location.origin}catch(e){return false}
}
function cacheablePath(url){
 try{
  const u=new URL(url);
  if(u.origin!==self.location.origin)return false;
  if(u.search)return false;
  const p=u.pathname;
  if(p.indexOf('/api/')===0||p==='/logout'||p==='/logout-all'||p==='/healthz')return false;
  return SHELL.indexOf(p)>=0;
 }catch(e){return false}
}
self.addEventListener('install',e=>{
 e.waitUntil(caches.open(C).then(cache=>cache.addAll(SHELL.filter(p=>p.indexOf('.html')<0&&p!=='/'&&p!=='/login')).catch(()=>{})).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',e=>{e.waitUntil(
 caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{
 const req=e.request;
 if(req.method!=='GET'||!sameOrigin(req.url))return;
 if(!cacheablePath(req.url))return;
 /* Network first, but a stalled network must not hang the shell: after NET_WAIT_MS serve the
    cached copy if there is one (the network answer still refreshes the cache when it lands). */
 const net=fetch(req).then(r=>{
  if(r.ok&&r.type==='basic'){
   const c=r.clone();
   caches.open(C).then(x=>x.put(req,c)).catch(()=>{});
  }
  return r;
 });
 e.respondWith(new Promise(resolve=>{
  let done=false;
  const finish=r=>{if(!done&&r){done=true;resolve(r);}};
  const fromCache=()=>caches.match(req).then(hit=>{if(hit)finish(hit);return hit;});
  const t=setTimeout(fromCache,NET_WAIT_MS);
  net.then(r=>{clearTimeout(t);finish(r);},()=>{clearTimeout(t);
   fromCache().then(hit=>{if(!hit)finish(Response.error());});});
 }));
});
