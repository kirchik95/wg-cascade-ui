function cardStructSig(p){
 /* Omit online/spark/endpoint — those update in place so card height stays stable (no CLS). */
 return [p.pubkey,p.name,p.enabled?1:0,p.expires||0,clientExit(p),p.ip||'',_clientsView].join('|');
}
function clientActsHTML(p,exit,mode){
 const labeled=mode==='labeled';
 const en=tr(p.enabled?'Disable':'Enable');
 const pk=esc(p.pubkey), nm=esc(p.name);
 function mk(act,tip,label,icon,opts){
  opts=opts||{};
  const danger=opts.danger?' danger':'';
  const good=opts.good&&!p.enabled?' good':'';
  let data=' type="button" data-act="'+act+'"';
  if(act==='cfg')data+=' data-pk="'+pk+'"';
  else if(act==='edit')data+=' data-pk="'+pk+'" data-name="'+nm+'" data-exp="'+(p.expires||0)+'" data-exit="'+esc(exit)+'"';
  else if(act==='toggle')data+=' data-pk="'+pk+'" data-en="'+(p.enabled?'1':'0')+'"';
  else if(act==='del')data+=' data-pk="'+pk+'" data-name="'+nm+'"';
  const tipTr=tr(tip), labelTr=tr(label);
  const tipAttr=' data-tip="'+esc(tipTr)+'" aria-label="'+esc(labeled?labelTr:tipTr)+'"';
  if(labeled)return '<button class="act'+danger+'"'+data+tipAttr+'>'+ic(icon)+'<span>'+labelTr+'</span></button>';
  return '<button class="ib'+danger+good+'"'+data+tipAttr+'>'+ic(icon)+'</button>';
 }
 return mk('cfg','Show config / QR','Config','qr')
  +mk('edit','Edit','Rename','edit')
  +mk('toggle',en,en,'pow',{good:1})
  +mk('del','Delete','Delete','trash',{danger:1});
}
function clientCardHTML(p){
 const exit=clientExit(p);
 const prevAge=_pv['age-'+p.pubkey];
 const fresh=p.online&&prevAge!=null&&p.age>=0&&p.age<prevAge;
 _pv['age-'+p.pubkey]=p.age;
 const prx=_pv['rx-'+p.pubkey],ptx=_pv['tx-'+p.pubkey];
 const acts=clientActsHTML(p,exit,_clientsView==='list'?'icon':'labeled');
 const chips='<button type="button" class="chip chip-exit chip-'+exit+'" data-tip="'+esc(tr('Click to switch exit'))+'" aria-label="'+esc(tr('Switch exit')+': '+exit.toUpperCase())+'" data-act="exit" data-pk="'+esc(p.pubkey)+'" data-exit="'+esc(exit)+'">'+exit.toUpperCase()+'</button>'
  +(p.expires?'<span class="chip '+((p.expires-(Date.now()/1000|0))<=0?'chip-exp':'chip-tmp')+'" data-tip="'+esc(tr('Temporary client (auto-disables)'))+'">'+ic('clock',10)+fmtLeft(p.expires-(Date.now()/1000|0))+'</span>':'')
  +(p.enabled?'':'<span class="chip">'+tr('disabled')+'</span>');
 const xfer='<div class="xfer mono" data-tip="'+esc(tr('Total since connect'))+'"><span class="dn">↓ <b class="vx" data-k="rx-'+esc(p.pubkey)+'" data-to="'+p.rx+'">'+fmtB(prx==null?p.rx:prx)+'</b></span><span class="up">↑ <b class="vx" data-k="tx-'+esc(p.pubkey)+'" data-to="'+p.tx+'">'+fmtB(ptx==null?p.tx:ptx)+'</b></span></div>';
 const cls='crow '+(_clientsView==='list'?'crow-list ':'')+(p.online?'on':'')+' '+(p.enabled?'':'off-cl')+(fresh?' flash':'');
 const head='<div class="'+cls+'" data-pk="'+esc(p.pubkey)+'" data-ssig="'+esc(cardStructSig(p))+'">';
 const onlineTip=tr(p.online?'Online — recent handshake':(p.enabled?'Offline':'Disabled'));
 const onlineLbl=tr(p.online?'online':'offline');
 if(_clientsView==='list'){
  return head
   +'<div class="av" data-tip="'+esc(onlineTip)+'">'+esc(initials(p.name))+'<span class="avdot '+(p.online?'on':'')+'"></span></div>'
   +'<div class="idc"><div class="nm"><span class="nmt">'+esc(p.name)+'</span>'+chips+'</div>'
   +'<div class="lmeta"><span class="hs'+(p.online?'':' o')+'">'+onlineLbl+'</span>'
   +'<span class="age">'+ic('clock',11)+fmtAge(p.age)+'</span>'
   +'<span class="ipa mono" data-tip="'+esc(tr('Tunnel address'))+'">'+esc(p.ip)+'</span>'
   +xfer+'</div></div>'
   +'<div class="acts">'+acts+'</div></div>';
 }
 const sv=csparkSVG(p.spark);
 return head
  +'<div class="ctop"><div class="av" data-tip="'+esc(onlineTip)+'">'+esc(initials(p.name))+'<span class="avdot '+(p.online?'on':'')+'"></span></div>'
  +'<div class="idc"><div class="nm"><span class="nmt">'+esc(p.name)+'</span>'+chips+'</div>'
  +'<div class="ipa mono" data-tip="'+esc(tr('Tunnel address'))+'">'+esc(p.ip)+'</div>'
  +(p.endpoint?'<div class="ep mono" data-tip="'+esc(tr('Client public endpoint'))+'">'+ic('net',11)+esc(p.endpoint)+'</div>':'')+'</div>'
  +'<div class="pillstat'+(p.online?'':' o')+'"><div class="hs">'+onlineLbl+'</div>'
  +'<div class="age">'+ic('clock',11)+fmtAge(p.age)+'</div></div></div>'
  +'<div class="stat">'+xfer
  +'<div class="mo mono" data-tip="'+esc(tr('Traffic this calendar month'))+'">'+(p.mrx||p.mtx?ic('cal',11)+'↓'+fmtB(p.mrx)+' ↑'+fmtB(p.mtx):'')+'</div></div>'
  +'<div class="cspark" data-tip="'+esc(csparkTip(p.spark))+'">'+(sv||'')+'</div>'
  +'<div class="acts">'+acts+'</div></div>';
}
function emptyStateHTML(kind){
 if(kind==='none'){
  return '<div class="empty">'+ic('plus',28)+'<b>'+tr('No clients yet')+'</b><p>'+tr('Create a client to generate a WireGuard config and QR code.')+'</p>'
   +'<button class="primary" type="button" data-act="add">'+tr('+ Client')+'</button></div>';
 }
 return '<div class="empty">'+ic('search',28)+'<b>'+tr('No matches')+'</b><p>'+tr('Try a different name or IP.')+'</p></div>';
}
/* Fresh-handshake flashes are restarted in one batch: drop the class now, re-add it in the
   next frame. No per-card `void el.offsetWidth` (a forced synchronous layout each). */
let _flashQueue=[];
function queueFlash(el){el.classList.remove('flash');_flashQueue.push(el);}
function flushFlashes(){
 if(!_flashQueue.length)return;
 const els=_flashQueue;_flashQueue=[];
 const add=()=>els.forEach(el=>el.classList.add('flash'));
 if(typeof requestAnimationFrame==='function')requestAnimationFrame(()=>requestAnimationFrame(add));
 else add();
}
function tweenCard(el,p){
 el.querySelectorAll('.vx').forEach(b=>{
  const k=b.dataset.k;const to=k.indexOf('rx-')===0?p.rx:p.tx;b.dataset.to=to;tw(b,k,+to,fmtB);
 });
}
function cardFromHTML(html){
 const tmp=document.createElement('div');tmp.innerHTML=html;
 return tmp.firstElementChild||tmp.firstChild;
}
function updateCardLive(el,p){
 const prevAge=_pv['age-'+p.pubkey];
 const fresh=p.online&&prevAge!=null&&p.age>=0&&p.age<prevAge;
 _pv['age-'+p.pubkey]=p.age;
 if(fresh)queueFlash(el);
 el.classList.toggle('on',!!p.online);
 const av=el.querySelector('.av');
 if(av){
  av.setAttribute('data-tip',tr(p.online?'Online — recent handshake':(p.enabled?'Offline':'Disabled')));
  const avdot=av.querySelector('.avdot');if(avdot)avdot.classList.toggle('on',!!p.online);
 }
 const age=el.querySelector('.age');if(age)age.innerHTML=ic('clock',11)+fmtAge(p.age);
 const hs=el.querySelector('.hs');
 if(hs){
  hs.textContent=tr(p.online?'online':'offline');
  hs.classList.toggle('o',!p.online);
 }
 const pillstat=el.querySelector('.pillstat');
 if(pillstat)pillstat.classList.toggle('o',!p.online);
 tweenCard(el,p);
 if(el.classList.contains('crow-list'))return;
 const ep=el.querySelector('.ep');
 if(p.endpoint){
  const html=ic('net',11)+esc(p.endpoint);
  if(ep){ep.innerHTML=html;ep.hidden=false;}
  else{
   const idc=el.querySelector('.idc');
   if(idc)idc.insertAdjacentHTML('beforeend','<div class="ep mono" data-tip="'+esc(tr('Client public endpoint'))+'">'+html+'</div>');
  }
 }else if(ep){ep.innerHTML='';ep.hidden=true;}
 const mo=el.querySelector('.mo');
 if(mo)mo.innerHTML=(p.mrx||p.mtx)?ic('cal',11)+'↓'+fmtB(p.mrx)+' ↑'+fmtB(p.mtx):'';
 let sparkEl=el.querySelector('.cspark');
 if(!sparkEl){
  const actsEl=el.querySelector('.acts');
  const html='<div class="cspark"></div>';
  if(actsEl)actsEl.insertAdjacentHTML('beforebegin',html);
  else el.insertAdjacentHTML('beforeend',html);
  sparkEl=el.querySelector('.cspark');
 }
 if(sparkEl){
  const sv=csparkSVG(p.spark);
  sparkEl.innerHTML=sv||'';
  sparkEl.setAttribute('data-tip',csparkTip(p.spark));
 }
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

 /* One pass, element references kept in `order`: no per-key DOM queries (was O(n²)). */
 const order=[];
 filtered.forEach(p=>{
  let el=existing.get(p.pubkey);
  const ssig=cardStructSig(p);
  if(!el){
   el=cardFromHTML(clientCardHTML(p));
   if(el){root.appendChild(el);applyI18n(el);tweenCard(el,p);}
  }else if(el.dataset.ssig!==ssig){
   const neu=cardFromHTML(clientCardHTML(p));
   if(neu&&typeof el.replaceWith==='function'){el.replaceWith(neu);el=neu;}
   else if(neu){root.appendChild(neu);el.remove();el=neu;}
   applyI18n(el);tweenCard(el,p);
  }else{
   updateCardLive(el,p);
  }
  if(el)order.push(el);
  existing.delete(p.pubkey);
 });
 existing.forEach(el=>{
  const pk=el.dataset&&el.dataset.pk;
  if(pk){delete _pv['age-'+pk];delete _pv['rx-'+pk];delete _pv['tx-'+pk];}
  if(typeof el.remove==='function')el.remove();
 });
 placeInOrder(root,order);
 flushFlashes();
}
/* Move only cards that are out of place; a stable list costs n reference compares. */
function placeInOrder(root,order){
 const kids=root.children;
 for(let i=0;i<order.length;i++){
  const el=order[i];
  if(kids[i]===el)continue;
  if(typeof root.insertBefore==='function'){root.insertBefore(el,kids[i]||null);continue;}
  for(let j=i;j<order.length;j++)root.appendChild(order[j]);   /* no insertBefore: re-append the tail */
  break;
 }
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
function bindTips(){
 if(document.__tipsBound||!document.addEventListener)return;document.__tipsBound=1;
 let tip=document.getElementById('floattip');
 if(!tip){
  tip=document.createElement('div');tip.id='floattip';tip.className='floattip';tip.setAttribute('role','tooltip');
  tip.setAttribute('aria-hidden','true');document.body.appendChild(tip);
 }
 let active=null;
 function place(el){
  const r=el.getBoundingClientRect(),pad=8;
  let x=r.left+r.width/2;
  tip.classList.add('show');tip.classList.remove('below');tip.removeAttribute('hidden');tip.setAttribute('aria-hidden','false');
  tip.style.left='0';tip.style.top='0';tip.style.transform='translate(-50%,calc(-100% - 10px))';
  const tw=tip.offsetWidth||0,th=tip.offsetHeight||0;
  x=Math.max(pad+tw/2,Math.min(window.innerWidth-pad-tw/2,x));
  tip.style.left=x+'px';
  if(r.top-th-12<pad){
   tip.classList.add('below');tip.style.top=r.bottom+'px';tip.style.transform='';
  }else{
   tip.style.top=r.top+'px';
  }
 }
 function show(el){
  if(!el||el===active)return;
  if(el.closest&&el.closest('.pillstat'))return;
  const text=el.getAttribute('data-tip');if(!text)return;
  active=el;tip.textContent=text;place(el);
 }
 function hide(){
  active=null;tip.classList.remove('show','below');tip.setAttribute('aria-hidden','true');tip.textContent='';
 }
 document.addEventListener('pointerover',e=>{
  const el=e.target&&e.target.closest&&e.target.closest('[data-tip]');
  if(el)show(el);else if(!tip.contains(e.target))hide();
 });
 document.addEventListener('pointerout',e=>{
  const el=e.target&&e.target.closest&&e.target.closest('[data-tip]');
  if(!el)return;
  const to=e.relatedTarget&&e.relatedTarget.closest&&e.relatedTarget.closest('[data-tip]');
  if(to===el)return;hide();
 });
 document.addEventListener('focusin',e=>{
  const el=e.target&&e.target.closest&&e.target.closest('[data-tip]');
  if(el)show(el);
 });
 document.addEventListener('focusout',e=>{
  const el=e.target&&e.target.closest&&e.target.closest('[data-tip]');
  if(!el)return;
  const to=e.relatedTarget&&e.relatedTarget.closest&&e.relatedTarget.closest('[data-tip]');
  if(to===el)return;hide();
 });
 window.addEventListener('scroll',()=>{if(active)place(active);},{passive:true,capture:true});
 window.addEventListener('resize',hide);
}
setLangBtn();hydrateIcons();applyI18n();applyClientsView();bindMenus();bindActions();bindSearch();bindTips();renderSkeleton();tick();scheduleTick(5000);
if(typeof window!=='undefined'&&window.addEventListener){
 window.addEventListener('online',()=>{setOffline(false);kickTick();});
 window.addEventListener('offline',()=>setOffline(true));
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)kickTick();});
}
