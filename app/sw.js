const C='wgui-shell-v26';
const SHELL=[
 '/','/index.html','/login','/login.html',
 '/app.css','/app.js','/boot.js','/theme.js','/cascade.js','/clients.js','/login.js',
 '/inter.woff2','/icon.svg','/apple-touch-icon.png','/manifest.webmanifest'
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
 e.respondWith(
  fetch(req).then(r=>{
   if(r.ok&&r.type==='basic'){
    const c=r.clone();
    caches.open(C).then(x=>x.put(req,c)).catch(()=>{});
   }
   return r;
  }).catch(()=>caches.match(req))
 );
});
