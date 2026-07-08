function cardStructSig(p){
 return [p.pubkey,p.name,p.enabled?1:0,p.online?1:0,p.expires||0,clientExit(p),p.endpoint||'',p.ip||'',!!(p.spark&&p.spark.length>1),_clientsView].join('|');
}
function clientActsHTML(p,pj,nj,exit){
 const en=p.enabled?'Disable':'Enable';
 return '<button class="ib" data-tip="Show config / QR" aria-label="Show config / QR" type="button" onclick=\'showCfg('+pj+')\'>'+ic('qr')+'</button>'
  +'<button class="ib" data-tip="Edit" aria-label="Edit" type="button" onclick=\'openEdit('+pj+','+nj+','+(p.expires||0)+','+JSON.stringify(exit)+')\'>'+ic('edit')+'</button>'
  +'<button class="ib '+(p.enabled?'':'good')+'" data-tip="'+en+'" aria-label="'+en+'" type="button" onclick=\'toggleEn('+pj+','+(p.enabled?'true':'false')+')\'>'+ic('pow')+'</button>'
  +'<button class="ib danger" data-tip="Delete" aria-label="Delete" type="button" onclick=\'confirmDel('+pj+','+nj+')\'>'+ic('trash')+'</button>';
}
function clientCardHTML(p){
 const pj=JSON.stringify(p.pubkey),nj=JSON.stringify(p.name);
 const exit=clientExit(p);
 const prevAge=_pv['age-'+p.pubkey];
 const fresh=p.online&&prevAge!=null&&p.age>=0&&p.age<prevAge;
 _pv['age-'+p.pubkey]=p.age;
 const prx=_pv['rx-'+p.pubkey],ptx=_pv['tx-'+p.pubkey];
 const acts=clientActsHTML(p,pj,nj,exit);
 const chips='<button type="button" class="chip chip-exit chip-'+exit+'" data-tip="Click to switch exit" aria-label="Switch exit: '+exit.toUpperCase()+'" onclick=\'toggleExit('+pj+','+JSON.stringify(exit)+')\'>'+exit.toUpperCase()+'</button>'
  +(p.expires?'<span class="chip '+((p.expires-(Date.now()/1000|0))<=0?'chip-exp':'chip-tmp')+'" data-tip="Temporary client (auto-disables)">'+ic('clock',10)+fmtLeft(p.expires-(Date.now()/1000|0))+'</span>':'')
  +(p.enabled?'':'<span class="chip">disabled</span>');
 const xfer='<div class="xfer mono" data-tip="Total since connect"><span class="dn">↓ <b class="vx" data-k="rx-'+p.pubkey+'" data-to="'+p.rx+'">'+fmtB(prx==null?p.rx:prx)+'</b></span><span class="up">↑ <b class="vx" data-k="tx-'+p.pubkey+'" data-to="'+p.tx+'">'+fmtB(ptx==null?p.tx:ptx)+'</b></span></div>';
 const cls='crow '+(_clientsView==='list'?'crow-list ':'')+(p.online?'on':'')+' '+(p.enabled?'':'off-cl')+(fresh?' flash':'');
 const head='<div class="'+cls+'" data-pk="'+esc(p.pubkey)+'" data-ssig="'+esc(cardStructSig(p))+'">';
 if(_clientsView==='list'){
  return head
   +'<div class="av" data-tip="'+(p.online?'Online — recent handshake':(p.enabled?'Offline':'Disabled'))+'">'+ic(devIcon(p.name),18)+'<span class="avdot '+(p.online?'on':'')+'"></span></div>'
   +'<div class="idc"><div class="nm">'+esc(p.name)+chips+'</div>'
   +'<div class="lmeta"><span class="hs'+(p.online?'':' o')+'" data-tip="Last WireGuard handshake">'+(p.online?'online':'offline')+'</span>'
   +'<span class="age" data-tip="Last handshake">'+ic('clock',11)+fmtAge(p.age)+'</span>'
   +'<span class="ipa mono" data-tip="Tunnel address">'+p.ip+'</span>'
   +xfer+'</div></div>'
   +'<div class="acts">'+acts+'</div></div>';
 }
 const sv=csparkSVG(p.spark);
 return head
  +'<div class="ctop"><div class="av" data-tip="'+(p.online?'Online — recent handshake':(p.enabled?'Offline':'Disabled'))+'">'+ic(devIcon(p.name),20)+'<span class="avdot '+(p.online?'on':'')+'"></span></div>'
  +'<div class="idc"><div class="nm">'+esc(p.name)+chips+'</div>'
  +'<div class="ipa mono" data-tip="Tunnel address">'+p.ip+'</div>'
  +(p.endpoint?'<div class="ep mono" data-tip="Client public endpoint">'+ic('net',11)+p.endpoint+'</div>':'')+'</div></div>'
  +'<div class="stat '+(p.online?'':'o')+'"><div class="hs" data-tip="Last WireGuard handshake">'+(p.online?'online':'offline')+'</div>'
  +'<div class="age" data-tip="Last handshake">'+ic('clock',11)+fmtAge(p.age)+'</div>'+xfer
  +((p.mrx||p.mtx)?'<div class="mo mono" data-tip="Traffic this calendar month">'+ic('cal',11)+'↓'+fmtB(p.mrx)+' ↑'+fmtB(p.mtx)+'</div>':'')+'</div>'
  +'<div class="acts">'+acts+'</div>'
  +(sv?'<div class="cspark" data-tip="'+esc(csparkTip(p.spark))+'">'+sv+'</div>':'')+'</div>';
}
function emptyStateHTML(kind){
 if(kind==='none'){
  return '<div class="empty">'+ic('plus',28)+'<b>'+tr('No clients yet')+'</b><p>'+tr('Create a client to generate a WireGuard config and QR code.')+'</p>'
   +'<button class="primary" type="button" onclick="openAdd()">'+tr('+ Add client')+'</button></div>';
 }
 return '<div class="empty">'+ic('search',28)+'<b>'+tr('No matches')+'</b><p>'+tr('Try a different name or IP.')+'</p></div>';
}
function updateCardLive(el,p){
 const prevAge=_pv['age-'+p.pubkey];
 const fresh=p.online&&prevAge!=null&&p.age>=0&&p.age<prevAge;
 _pv['age-'+p.pubkey]=p.age;
 if(fresh){el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash');}
 const age=el.querySelector('.age');if(age)age.innerHTML=ic('clock',11)+fmtAge(p.age);
 const hs=el.querySelector('.hs');
 if(hs){
  hs.textContent=p.online?'online':'offline';
  hs.classList.toggle('o',!p.online);
 }
 const stat=el.querySelector('.stat');
 if(stat)stat.classList.toggle('o',!p.online);
 el.querySelectorAll('.vx').forEach(b=>{
  const k=b.dataset.k;const to=k.indexOf('rx-')===0?p.rx:p.tx;b.dataset.to=to;tw(b,k,+to,fmtB);
 });
 if(el.classList.contains('crow-list'))return;
 const mo=el.querySelector('.mo');
 if(p.mrx||p.mtx){
  const html=ic('cal',11)+'↓'+fmtB(p.mrx)+' ↑'+fmtB(p.mtx);
  if(mo)mo.innerHTML=html;else{
   if(stat){const d=document.createElement('div');d.className='mo mono';d.setAttribute('data-tip','Traffic this calendar month');d.innerHTML=html;stat.appendChild(d);applyI18n(d);}
  }
 }
 const sparkEl=el.querySelector('.cspark');
 const sv=csparkSVG(p.spark);
 if(sv){
  const tip=csparkTip(p.spark);
  if(sparkEl){sparkEl.innerHTML=sv;sparkEl.setAttribute('data-tip',tip);}
  else el.insertAdjacentHTML('beforeend','<div class="cspark" data-tip="'+esc(tip)+'">'+sv+'</div>');
 }
 else if(sparkEl)sparkEl.remove();
}
function renderClients(peers){
 _peers=peers||[];
 peers=_peers.slice().sort((a,b)=>octet(a.ip)-octet(b.ip));
 const q=_cquery.trim().toLowerCase();
 let filtered=peers;
 if(_exitFilter==='nl'||_exitFilter==='us'){
  filtered=filtered.filter(p=>clientExit(p)===_exitFilter);
 }
 if(q){
  filtered=filtered.filter(p=>{
   const hay=((p.name||'')+' '+(p.ip||'')+' '+(p.endpoint||'')+' '+(clientExit(p))).toLowerCase();
   return hay.indexOf(q)>=0;
  });
 }
 const nNl=_peers.filter(p=>clientExit(p)==='nl').length;
 const nUs=_peers.filter(p=>clientExit(p)==='us').length;
 document.getElementById('csum').textContent=_peers.filter(p=>p.online).length+' '+tr('online')+' · '+_peers.length+' '+(LANG==='ru'?'всего':'total');
 const xf=document.getElementById('exitfilt');
 if(xf){
  xf.querySelectorAll('[data-xf]').forEach(b=>{
   const on=b.dataset.xf===_exitFilter;
   b.classList.toggle('on',on);
   b.setAttribute('aria-pressed',on?'true':'false');
   if(b.dataset.xf==='all')b.textContent=tr('All')+' · '+_peers.length;
   else if(b.dataset.xf==='nl')b.textContent='NL · '+nNl;
   else if(b.dataset.xf==='us')b.textContent='US · '+nUs;
  });
 }
 applyClientsView();
 const root=document.getElementById('cards');
 if(!_peers.length){root.innerHTML=emptyStateHTML('none');return;}
 if(!filtered.length){root.innerHTML=emptyStateHTML('filter');return;}

 const existing=new Map();
 root.querySelectorAll('.crow[data-pk]').forEach(el=>existing.set(el.dataset.pk,el));
 /* drop non-cards (empty/skel) */
 if(!root.querySelector('.crow[data-pk]'))root.innerHTML='';

 const order=[];
 filtered.forEach(p=>{
  order.push(p.pubkey);
  let el=existing.get(p.pubkey);
  const ssig=cardStructSig(p);
  if(!el){
   if(typeof root.insertAdjacentHTML==='function'){
    root.insertAdjacentHTML('beforeend',clientCardHTML(p));
   }else{
    root.innerHTML=(root.innerHTML||'')+clientCardHTML(p);
   }
   el=findCard(root,p.pubkey);
   if(el)applyI18n(el);
  }else if(el.dataset.ssig!==ssig){
   const tmp=document.createElement('div');tmp.innerHTML=clientCardHTML(p);
   let neu=tmp.firstChild;
   if(typeof el.replaceWith==='function')el.replaceWith(neu);
   else{el.outerHTML=clientCardHTML(p);neu=findCard(root,p.pubkey);}
   el=neu||findCard(root,p.pubkey);if(el)applyI18n(el);
  }else{
   updateCardLive(el,p);
  }
  existing.delete(p.pubkey);
 });
 existing.forEach(el=>{if(typeof el.remove==='function')el.remove();});
 /* preserve visual order */
 order.forEach(pk=>{
  const el=findCard(root,pk);
  if(el&&root.appendChild)root.appendChild(el);
 });
 const vxs=root.querySelectorAll?root.querySelectorAll('.vx'):[];
 [...vxs].forEach(b=>{if(b.dataset&&b.dataset.to!=null)tw(b,b.dataset.k,+b.dataset.to,fmtB);});
}
function findCard(root,pk){
 if(!root||!root.querySelectorAll)return null;
 return [...root.querySelectorAll('.crow[data-pk]')].find(el=>el.dataset&&el.dataset.pk===pk)||null;
}
async function toggleExit(pub,cur){
 const next=cur==='us'?'nl':'us';
 const card=findCard(document.getElementById('cards'),pub);
 const el=card&&card.querySelector('.chip-exit');
 if(el){el.disabled=true;el.classList.add('busy');}
 const r=await admin({op:'setexit',pubkey:pub,exit:next});
 if(el){el.disabled=false;el.classList.remove('busy');}
 if(!r||!r.ok){toast((r&&r.error)||'failed');return;}
 toast((r.name||'')+' → '+next.toUpperCase());
 tick();
}
function setExitFilter(f){
 _exitFilter=(f==='nl'||f==='us')?f:'all';
 renderClients(_peers);
}
function applyClientsView(){
 const root=document.getElementById('cards');
 if(root&&root.classList&&root.classList.toggle){
  root.classList.toggle('bento2',_clientsView!=='list');
  root.classList.toggle('listview',_clientsView==='list');
 }else if(root){
  const base=(root.className||'').replace(/\b(bento2|listview)\b/g,'').trim();
  root.className=(base+' '+(_clientsView==='list'?'listview':'bento2')).trim();
 }
 const vg=document.getElementById('viewfilt');
 if(vg&&vg.querySelectorAll){
  vg.querySelectorAll('[data-view]').forEach(b=>{
   const on=b.dataset.view===_clientsView;
   if(b.classList&&b.classList.toggle)b.classList.toggle('on',on);
   if(b.setAttribute)b.setAttribute('aria-pressed',on?'true':'false');
  });
 }
}
function setClientsView(v){
 const next=v==='list'?'list':'cards';
 if(next===_clientsView)return;
 _clientsView=next;
 try{localStorage.setItem('wgui-clients-view',_clientsView)}catch(e){}
 applyClientsView();
 const root=document.getElementById('cards');
 if(root)root.innerHTML='';
 renderClients(_peers);
}

if(typeof navigator!=='undefined'&&'serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(function(){})}
setLangBtn();hydrateIcons();applyI18n();applyClientsView();bindMenus();bindSearch();renderSkeleton();tick();setInterval(tick,5000);
if(typeof window!=='undefined'&&window.addEventListener){
 window.addEventListener('online',()=>{setOffline(false);tick();});
 window.addEventListener('offline',()=>setOffline(true));
}
