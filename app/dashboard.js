/* Dashboard (A1–A5): the «Клиенты» section, plus placeholders for the sections that
 * stage 2C fills in pages.js (re-registering a route replaces its placeholder).
 * Honesty rules (DS-3): a stale snapshot or a lost connection greys everything out —
 * no green or red over old data; «онлайн» means a fresh handshake with the entry node. */
(function(){
'use strict';
const root=typeof globalThis!=='undefined'?globalThis:window;
const WG=root.WG;
const {tr,esc,icon}=WG;

WG.addStrings('ru',{
 'Open exit settings':'Открыть настройки выходов','Open split tunnel':'Открыть сплит-туннель',
 'State':'Состояние','Cascade':'Каскад','Now':'Сейчас','Exit':'Выход','Working':'Работает','Failure':'Сбой','Outage':'Авария',
 'Unknown':'Неизвестно','Loading…':'Загрузка…','split on':'сплит вкл','split off':'сплит выкл',
 'last data {t}':'последние данные {t}','both exits down · {t}':'оба выхода недоступны · {t}',
 '{exit} not responding · {n} without exit':'{exit} не отвечает · без выхода: {n}',
 'OK':'ОК','NO ANSWER':'НЕТ ОТВЕТА','CHECK {n}/3':'ПРОВЕРКА {n}/3','check {t}':'проверка {t}','no data':'нет данных',
 'affected':'затронуто','Scheme':'Схема','Devices':'Устройства','Entry RU':'Вход RU','ok':'ок','down':'нет ответа',
 '{p}% of quota':'{p}% квоты','RU direct from the entry':'РФ напрямую со входа','Split tunnel off':'Сплит выключен',
 'More details':'Подробнее','online':'онлайн','total':'всего','off':'выкл','connected to the entry':'подключены ко входу',
 'data as of {t}':'данные на {t}','as of {t}':'на {t}','search by name or IP':'поиск по имени или IP','search':'поиск',
 'Search clients':'Поиск клиентов','Filter clients':'Фильтр клиентов','All':'Все','Offline':'Офлайн',
 'Name':'Имя','Address':'Адрес','Month':'За месяц','Connection':'Связь','Actions':'Действия',
 'no expiry':'бессрочно','until {d}':'до {d}','expires in {t}':'истекает через {t}','expired':'истёк','extend':'продлить',
 'disabled':'выключен','never connected':'не подключался','at {t}':'в {t}','was {t}':'был {t}','was at {t}':'был в {t}',
 'entry ok · no exit':'вход ок · выхода нет','{v} this month':'{v} за месяц',
 'Config and QR':'Конфиг и QR','Edit client':'Изменить клиента','Move to {exit}':'Перевести на {exit}',
 'Connection history':'История подключений','Turn off':'Выключить','Turn on':'Включить','can be undone':'можно отменить',
 'Delete client…':'Удалить клиента…','{exit} ok · {p}%':'{exit} ок · {p}%','{exit} is down':'{exit} недоступен',
 '{exit} quota used up':'квота {exit} исчерпана','{exit} not checked':'{exit} не проверен','Enable':'Вкл',
 'Client actions':'Действия с клиентом','+ {n} more ↓':'+ ещё {n} ↓','Show all':'Показать всех',
 'entry RU · CPU {c}% · memory {m} · up {u}':'вход RU · ЦП {c}% · память {m} · работает {u}',
 'No clients yet':'Клиентов пока нет','Add the first device — the config and QR code appear right away.':'Добавьте первое устройство — конфиг и QR-код появятся сразу.',
 'Nobody matches':'Никто не подходит','Reset filters':'Сбросить фильтры','Waiting for the first data…':'Ждём первые данные…'
});

const ONLINE_S=180;              /* server ONLINE_S: a handshake younger than this is «online» */
const ROW_LIMIT=10;               /* rows before «ещё N» while no search/filter is active */
const FILTERS=['all','nl','us','offline'];
let _filter=(function(){let v=null;try{v=localStorage.getItem('wgui-clients-filter')}catch(e){}return FILTERS.indexOf(v)>=0?v:'all'})();
let _query='',_expanded=false,_ui=null;

/* ------------------------------------------------------------ model */
function mode(s){
 if(!s.loaded)return s.offline?'offline':'loading';
 if(s.offline)return'offline';
 if(s.stale)return'stale';
 if(s.tunnel&&s.tunnel.state==='down')return'crash';
 return'live';
}
const isUnknown=m=>m==='offline'||m==='stale'||m==='loading';
function exitInfo(s,key){
 const t=(s.tunnel&&s.tunnel.exits&&s.tunnel.exits[key])||null;
 const p=(s.exit_policy&&s.exit_policy.exits&&s.exit_policy.exits[key])||null;
 const used=p?+p.used||0:0,quota=p?+p.quota||0:0;
 let health='unknown';
 if(t&&!isUnknown(mode(s))&&+t.checked_age>=0){
  if(t.ok)health='ok';
  else if(t.health==='down')health='down';
  else health='warn';
 }
 return{key,t,p,used,quota,ratio:quota>0?used/quota:0,clients:p?+p.clients||0:0,health,
  exhausted:!!(p&&(p.exhausted||(quota>0&&used>=quota)))};
}
function now(s){return +s.now||Math.round(Date.now()/1000)}
function peerExitDown(s,p,m){
 if(isUnknown(m)||!p.enabled)return false;
 const e=s.tunnel&&s.tunnel.exits&&s.tunnel.exits[p.exit==='us'?'us':'nl'];
 return !!(e&&!e.ok);
}
/* Was the client online when the data was taken? In a stale snapshot the server has
   already aged handshakes, so «online» is false; the age at snapshot time tells. */
function wasOnline(s,p){
 if(!p.enabled||!(+p.age>=0))return false;
 return(+p.age-(+s.snapshot_age||0))<ONLINE_S;
}
function expiry(p,nowTs){
 const exp=+p.expires||0;
 if(!exp)return{kind:'none',text:tr('no expiry')};
 const left=exp-nowTs;
 if(left<=0)return{kind:'expired',text:tr('expired')};
 if(left<7*86400){
  const t=left<86400?WG.count(Math.max(1,Math.ceil(left/3600)),'hour'):WG.count(Math.ceil(left/86400),'day');
  return{kind:'soon',text:tr('expires in {t}',{t})};
 }
 return{kind:'later',text:tr('until {d}',{d:WG.fmtDate(exp)})};
}
function bigNum(v){return v>=10||v===0?String(Math.round(v)):v.toFixed(1)}
function gib(n){return Math.round((+n||0)/1073741824)}
function shortBytes(n){
 const s=WG.fmtBytes(n),m=/^(\d+)\.(\d) (.+)$/.exec(s);
 return m&&+m[1]>=10?m[1]+' '+m[3]:s;
}
function exitLabel(key){return String(key).toUpperCase()}
const GIB=()=>WG.lang==='en'?'GiB':'ГиБ';

/* ------------------------------------------------------------ pieces */
function sparkPoints(values,w,h,top){
 const v=(values||[]).map(x=>+x||0);
 if(v.length<2)return'0,'+(h-1)+' '+w+','+(h-1);
 const max=top||Math.max.apply(null,v)||1;
 return v.map((x,i)=>(i*w/(v.length-1)).toFixed(1)+','+(h-1-(x/max)*(h-3)).toFixed(1)).join(' ');
}
function spark(values,w,h,cls,top){
 return '<svg class="spark '+(cls||'')+'" width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
  +'<polyline points="'+sparkPoints(values,w,h,top)+'"/></svg>';
}
function bar(ratio,n,unknownTone){
 const filled=ratio>0?Math.min(n,Math.max(1,Math.round(ratio*n))):0;
 const tone=unknownTone?'is-u':ratio>=1?'is-bad':ratio>=.7?'is-warn':'is-on';
 let h='<span class="bar" aria-hidden="true">';
 for(let i=0;i<n;i++){
  const zone=(i+1)/n>.9?' z-bad':(i+1)/n>.8?' z-warn':'';
  h+='<i class="'+(i<filled?tone:'')+zone+'"></i>';
 }
 return h+'</span>';
}
function statusShort(x){
 const t={ok:['is-ok','● '+tr('OK')],down:['is-bad','× '+tr('NO ANSWER')],warn:['is-warn','! '+Math.min(3,+(x.t&&x.t.fails)||1)+'/3'],unknown:['is-u','● ?']}[x.health];
 return'<span class="g-st m-only '+t[0]+'">'+esc(t[1])+'</span>';
}
function statusChip(x,s){
 return'<span class="d-only">'+statusLong(x,s)+'</span>'+statusShort(x);
}
function statusLong(x,s){
 if(x.health==='ok')return'<span class="g-st is-ok">● '+esc(tr('OK'))+' '+esc(WG.fmtAgo(+x.t.checked_age,{suffix:false}))+'</span>';
 if(x.health==='down'){
  const since=+x.t.health_since?now(s)-x.t.health_since:-1;
  return'<span class="g-st is-bad">× '+esc(tr('NO ANSWER'))+(since>=0?' '+esc(WG.fmtAgo(since,{suffix:false})):'')+'</span>';
 }
 if(x.health==='warn')return'<span class="g-st is-warn">! '+esc(tr('CHECK {n}/3',{n:Math.min(3,+x.t.fails||1)}))+'</span>';
 const age=x.t&&+x.t.checked_age>=0?+x.t.checked_age:-1;
 return'<span class="g-st is-u">? '+esc(age>=0?tr('check {t}',{t:WG.fmtAgo(age)}):tr('no data'))+'</span>';
}
function gaugesHTML(s,m){
 const u=isUnknown(m),nl=exitInfo(s,'nl'),us=exitInfo(s,'us'),peers=s.peers||[];
 const thr=(s.thr&&s.thr.cur)||{down:0,up:0};
 let state,tone,sub;
 if(m==='loading'){state=tr('Loading…');tone='u';sub=tr('Waiting for the first data…')}
 else if(u){state=tr('Unknown');tone='u';sub=s.loaded?tr('last data {t}',{t:WG.fmtTime(s.dataAt)}):tr('no data')}
 else if(m==='crash'){
  const since=Math.max(+(nl.t&&nl.t.health_since)||0,+(us.t&&us.t.health_since)||0);
  state=tr('Outage');tone='bad';sub=tr('both exits down · {t}',{t:since?WG.fmtAgo(now(s)-since,{suffix:false}):'—'});
 }else if(s.tunnel&&s.tunnel.state==='degraded'){
  const bad=[nl,us].filter(x=>x.t&&!x.t.ok)[0]||us;
  state=tr('Failure');tone='bad';sub=tr('{exit} not responding · {n} without exit',{exit:exitLabel(bad.key),n:+(bad.t&&bad.t.affected_clients)||0});
 }else{
  state=tr('Working');tone='ok';
  sub='RU → NL '+nl.clients+' · US '+us.clients+' · '+tr(s.rud?'split on':'split off');
 }
 const speed=u?'—':'↓'+bigNum(+WG.mbit(thr.down))+' ↑'+bigNum(+WG.mbit(thr.up));
 let h='<div class="g-cell g-casc"><div class="g-lab d-only">'+esc(tr('Cascade'))+'</div>'
  +'<div class="g-state is-'+tone+'"><span class="g-dot" aria-hidden="true"></span><span class="g-state-t">'+esc(state)+'</span>'
  +'<span class="g-speed m-only">'+(u?(s.loaded?esc(tr('as of {t}',{t:WG.fmtTime(s.dataAt)})):'—'):esc(speed)+' '+esc(tr('Mbit/s')))+'</span></div>'
  +'<div class="g-sub d-only">'+esc(sub)+'</div></div>';
 [nl,us].forEach(x=>{
  const affected=m==='crash'||(x.health==='down'&&!u)?+(x.t&&x.t.affected_clients)||0:0;
  const numTone=u?'is-u':x.ratio>=1?'is-bad':x.ratio>=.7?'is-warn':'';
  const pct=x.ratio>=.7?' · '+Math.floor(x.ratio*100)+'%':'';
  h+='<div class="g-cell g-exit" data-exit="'+x.key+'">'
   +'<div class="g-head"><span class="g-lab"><span class="d-only">'+esc(tr('Exit'))+' '+exitLabel(x.key)+' · '+esc(WG.exitCity(x.key))+'</span>'
   +'<span class="m-only g-lab-m">'+exitLabel(x.key)+'</span></span>'+statusChip(x,s)+'</div>'
   +'<div class="g-fig"><span class="g-num '+numTone+'">'+gib(x.used)+'</span>'
   +'<span class="g-unit d-only">/ '+gib(x.quota)+' '+GIB()+pct+' · '
   +esc(affected?WG.count(affected,'client')+' '+tr('affected'):WG.count(x.clients,'client'))+'</span>'
   +'<span class="g-unit m-only">/'+gib(x.quota)+(pct||' '+GIB())+'</span></div>'
   +'<span class="d-only">'+bar(x.ratio,20,u)+'</span><span class="m-only">'+bar(x.ratio,10,u)+'</span>'
   +'<div class="g-foot m-only">'+esc(WG.count(x.clients,'client'))+'</div></div>';
 });
 const series=(s.thr&&s.thr.series)||[];
 const top=Math.max.apply(null,[1].concat(series.map(x=>+x.down||0),series.map(x=>+x.up||0)));
 h+='<div class="g-cell g-now d-only"><div class="g-lab">'+esc(tr('Now'))+' · '+esc(tr('Mbit/s'))+'</div>'
  +(u?'<div class="g-fig"><span class="g-num is-u">—</span></div>'
   :'<div class="g-fig"><span class="g-num">↓'+bigNum(+WG.mbit(thr.down))+'</span><span class="g-num2">↑'+bigNum(+WG.mbit(thr.up))+'</span></div>')
  +'<div class="g-spark'+(u?' is-u':'')+'">'+spark(series.map(x=>x.down),252,22,'s-down',top)+spark(series.map(x=>x.up),252,22,'s-up',top)+'</div></div>';
 return h;
}
function schemeHTML(s,m){
 if(m!=='live')return'';
 const xs=[exitInfo(s,'nl'),exitInfo(s,'us')],total=xs.reduce((a,x)=>a+x.clients,0)||1;
 const main=xs[0].clients>=xs[1].clients?xs[0]:xs[1];
 const branch=x=>{
  const share=x.clients/total,w=2+Math.round(4*share);
  const tone=x.health==='down'?' is-bad':x.ratio>=.7?' is-warn':'';
  const txt=exitLabel(x.key)+' · '+(x===main?WG.count(x.clients,'client'):x.clients)+' · '
   +(x.health==='down'?tr('down'):tr('ok'))+(x.ratio>=.7?' · '+tr('{p}% of quota',{p:Math.floor(x.ratio*100)}):'');
  return'<div class="sc-br"><span class="sc-line" style="height:'+w+'px"></span><span class="sc-box'+(x===main?' is-main':'')+tone+'">'+esc(txt)+'</span></div>';
 };
 return'<span class="label sc-lab">'+esc(tr('Scheme'))+'</span>'
  +'<span class="sc-box">'+esc(tr('Devices'))+' '+(s.peers||[]).length+'</span><span class="sc-line sc-line-in"></span>'
  +'<span class="sc-box is-ink">'+esc(tr('Entry RU'))+'</span>'
  +'<div class="sc-brs">'+branch(xs[0])+branch(xs[1])+'</div>'
  +'<span class="sc-rud">'+(s.rud?'<span class="sc-dash"></span>'+esc(tr('RU direct from the entry')):esc(tr('Split tunnel off')))+'</span>'
  +'<a class="sc-more" href="#/exits">'+esc(tr('More details'))+' →</a>';
}
function metaHTML(s,m,peers){
 if(!s.loaded)return'';
 const on=peers.filter(p=>p.online).length,off=peers.filter(p=>!p.enabled).length;
 if(isUnknown(m))return'<span class="d-only">'+esc(tr('data as of {t}',{t:WG.fmtTime(s.dataAt)}))+'</span>'
  +'<span class="m-only">'+esc(tr('as of {t}',{t:WG.fmtTime(s.dataAt)}))+' · '+peers.length+'</span>';
 if(m==='crash'){
  const aff=+(s.tunnel&&s.tunnel.affected_clients)||0;
  return'<span class="d-only">'+esc(on+' '+tr('connected to the entry')+' · '+aff+' '+tr('affected')+' · '+off+' '+tr('off'))+'</span>'
   +'<span class="m-only">'+esc(aff+' '+tr('affected')+' · '+peers.length)+'</span>';
 }
 return'<span class="d-only">'+esc(on+' '+tr('online')+' · '+peers.length+' '+tr('total')+' · '+off+' '+tr('off'))+'</span>'
  +'<span class="m-only">'+esc(on+' '+tr('online')+' · '+peers.length)+'</span>';
}
function filterHTML(peers){
 const n={all:peers.length,nl:peers.filter(p=>p.exit!=='us').length,us:peers.filter(p=>p.exit==='us').length,offline:peers.filter(p=>!p.online).length};
 const lab={all:tr('All'),nl:'NL',us:'US',offline:tr('Offline')};
 return FILTERS.map(f=>'<button type="button" class="seg-b'+(f==='offline'?' d-only':'')+'" data-act="cl-filter" data-f="'+f+'" aria-pressed="'+(f===_filter)+'">'
  +esc(lab[f])+'<span class="seg-n"> '+n[f]+'</span></button>').join('');
}
function visiblePeers(peers){
 const q=_query.trim().toLowerCase();
 return peers.filter(p=>{
  if(_filter==='nl'&&p.exit==='us')return false;
  if(_filter==='us'&&p.exit!=='us')return false;
  if(_filter==='offline'&&p.online)return false;
  if(!q)return true;
  return [p.name,p.ip,String(p.endpoint||'').split(':')[0]].some(v=>String(v||'').toLowerCase().indexOf(q)>=0);
 });
}
/* A row is a fixed set of cells; each cell is patched only when its own content changes,
   so the «12 с назад» tick never re-creates the buttons a keyboard user is on. */
function rowCells(s,m,p){
 const u=isUnknown(m),off=!!s.offline,nowTs=now(s),ex=expiry(p,nowTs),down=peerExitDown(s,p,m);
 const on=!u&&p.online,was=u&&(m==='offline'?p.online:wasOnline(s,p));
 const dot=!p.enabled?'is-dis':u?(was?'is-u':'is-off'):on?(down?'is-warn':'is-on'):'is-off';
 const ep=String(p.endpoint||'').replace(/:\d+$/,'').replace(/^\[|\]$/g,'');
 const expHTML=ex.kind==='soon'?'<span class="is-warn">'+esc(ex.text)+' · <button type="button" class="linkbtn" data-act="cl-extend" data-live>'+esc(tr('extend'))+'</button></span>'
  :ex.kind==='expired'?'<span class="is-bad">'+esc(ex.text)+'</span>':esc(ex.text);
 const sub=!p.enabled?esc(tr('disabled')):(ep&&ex.kind!=='soon'&&ex.kind!=='expired'?esc(ep)+' · ':'')+expHTML;
 const rate=(p.spark&&p.spark.length)?+p.spark[p.spark.length-1]:0;
 const nowCell=u||!on?'<span class="c-dash">—</span>':esc(WG.fmtMbit(rate));
 const hsTs=+p.age>=0?nowTs-(+p.age):0;
 let conn,connTone='';
 if(!p.enabled){conn=tr('disabled');connTone='is-faint'}
 else if(+p.age<0){conn=tr('never connected');connTone='is-faint'}
 else if(u)conn=+p.age<86400?tr('at {t}',{t:WG.fmtTime(hsTs)}):WG.fmtAgo(+p.age);
 else if(on&&down){conn=tr('entry ok · no exit');connTone='is-bad'}
 else if(on){conn=WG.fmtAgo(+p.age);connTone='is-ok'}
 else conn=WG.fmtAgo(+p.age);
 const month=(+p.mrx||0)+(+p.mtx||0);
 let meta;
 if(!p.enabled)meta=esc(tr('disabled'));
 else if(ex.kind==='soon'||ex.kind==='expired')meta='<span class="is-'+(ex.kind==='soon'?'warn':'bad')+'">'+esc(ex.text)+'</span>';
 else if(u)meta=esc(tr('{v} this month',{v:shortBytes(month)})+(+p.age>=0&&+p.age<86400?' · '+tr('was at {t}',{t:WG.fmtTime(hsTs)}):''));
 else if(on&&down)meta='<span class="is-bad">'+esc(tr('entry ok · no exit'))+'</span>';
 else if(on)meta=esc(WG.fmtMbit(rate)+' · '+tr('{v} this month',{v:shortBytes(month)}));
 else meta=esc(+p.age>=0?tr('was {t}',{t:WG.fmtAgo(+p.age)}):tr('never connected'));
 const badge='<span class="badge'+(!p.enabled?' is-off':down&&!u?' is-bad':'')+'">'+exitLabel(p.exit||'nl')+(down&&!u&&p.enabled?' ×':'')+'</span>';
 const dis=off?' disabled':'';
 const act=p.enabled
  ?'<button type="button" class="ibtn c-qr" data-act="cl-qr" data-live aria-label="'+esc(tr('Config and QR')+': '+p.name)+'"'+dis+'>'+icon('qr',14)+'</button>'
  :'<button type="button" class="btn btn-primary c-on" data-act="cl-enable" data-live'+dis+'>'+esc(tr('Enable'))+'</button>';
 return[
  ['c-dot','<span class="dot '+dot+'"></span>'],
  ['c-name','<span class="c-n">'+esc(p.name)+'</span><span class="c-sub d-only">'+sub+'</span>'
   +'<span class="c-meta m-only">'+badge+'<span class="c-meta-t">'+meta+'</span></span>'],
  ['c-ip d-only',esc(p.ip)],
  ['c-exit d-only',badge],
  ['c-now d-only',spark(p.spark,90,18,u||!on?'is-u':'')+'<span class="c-rate">'+nowCell+'</span>'],
  ['c-month d-only',esc(WG.fmtBytes(month))],
  ['c-conn d-only '+connTone,esc(conn)],
  ['c-act',act+'<button type="button" class="ibtn c-more" data-act="cl-menu" data-live aria-haspopup="menu" aria-expanded="false" aria-label="'
   +esc(tr('Client actions')+': '+p.name)+'"'+dis+'>'+icon('more',16)+'</button>']
 ];
}
function rowHTML(s,m,p){return rowCells(s,m,p).map(c=>'<span class="'+c[0]+'" role="cell">'+c[1]+'</span>').join('')}
const ROWS=new Map();          /* pubkey → {el, cells, sig}: rows are patched, never rebuilt */
function renderRows(container,s,m,list){
 const keep=new Set();
 list.forEach((p,i)=>{
  keep.add(p.pubkey);
  const cells=rowCells(s,m,p),cls='crow'+(p.enabled?'':' is-dis');
  let r=ROWS.get(p.pubkey);
  if(!r){
   const el=document.createElement('div');
   el.setAttribute('role','row');el.setAttribute('data-pk',p.pubkey);
   r={el,cells:cells.map(()=>{const c=document.createElement('span');c.setAttribute('role','cell');el.appendChild(c);return c}),sig:[],cls:''};
   ROWS.set(p.pubkey,r);
  }
  if(r.cls!==cls){r.el.className=cls;r.cls=cls}
  cells.forEach((c,j)=>{
   const key=c[0]+'|'+c[1];
   if(r.sig[j]===key)return;
   r.sig[j]=key;r.cells[j].className=c[0];r.cells[j].innerHTML=c[1];
  });
  const at=container.children[i];
  if(at!==r.el)container.insertBefore(r.el,at||null);
 });
 [...container.children].forEach(el=>{if(!keep.has(el.getAttribute('data-pk')))el.remove()});
 ROWS.forEach((r,k)=>{if(!keep.has(k)&&!r.el.parentElement)ROWS.delete(k)});
}
function hostText(h){
 if(!h)return'';
 const up=+h.uptime||0;
 const ut=up<86400?Math.max(1,Math.floor(up/3600))+' '+tr('h'):WG.count(Math.floor(up/86400),'day');
 const mem=((+h.mem_used||0)/1073741824).toFixed(1)+'/'+((+h.mem_total||0)/1073741824).toFixed(1)+' '+GIB();
 return tr('entry RU · CPU {c}% · memory {m} · up {u}',{c:Math.round(+h.cpu||0),m:mem,u:ut});
}

/* ------------------------------------------------------------ page */
function renderPage(el,ctx){
 const narrow=root.matchMedia&&root.matchMedia('(max-width: 600px)').matches;
 el.innerHTML='<div class="dash">'
  +'<section class="gauges" aria-label="'+esc(tr('State'))+'"></section>'
  +'<section class="scheme d-only" aria-label="'+esc(tr('Scheme'))+'"></section>'
  +'<section class="clients" aria-labelledby="cl-title">'
  +'<div class="cl-h"><div class="cl-ht"><h1 class="cl-title" id="cl-title">'+esc(tr('Clients'))+'</h1><span class="cl-meta"></span></div>'
  +'<div class="cl-tools"><label class="search">'+icon('search',14)
  +'<input class="search-in" type="search" autocomplete="off" spellcheck="false" aria-label="'+esc(tr('Search clients'))+'" placeholder="'
  +esc(narrow?tr('search'):tr('search by name or IP'))+'"></label>'
  +'<div class="seg cl-filter" role="group" aria-label="'+esc(tr('Filter clients'))+'"></div></div></div>'
  +'<div class="ct" role="table" aria-labelledby="cl-title">'
  +'<div class="ct-head d-only" role="row"><span role="columnheader" class="c-dot"></span><span role="columnheader">'+esc(tr('Name'))+'</span>'
  +'<span role="columnheader" class="c-ip">'+esc(tr('Address'))+'</span><span role="columnheader">'+esc(tr('Exit'))+'</span>'
  +'<span role="columnheader">'+esc(tr('Now'))+'</span><span role="columnheader">'+esc(tr('Month'))+'</span>'
  +'<span role="columnheader">'+esc(tr('Connection'))+'</span><span role="columnheader" class="c-act">'+esc(tr('Actions'))+'</span></div>'
  +'<div class="ct-body" role="rowgroup"></div><div class="ct-empty" hidden></div></div>'
  +'<div class="cl-foot"><span class="cl-more"></span><span class="cl-host d-only"></span></div>'
  +'</section></div>';
 const q=sel=>el.querySelector(sel);
 _ui={el,gauges:q('.gauges'),scheme:q('.scheme'),meta:q('.cl-meta'),filter:q('.cl-filter'),rows:q('.ct-body'),
  empty:q('.ct-empty'),more:q('.cl-more'),host:q('.cl-host'),search:q('.search-in'),sig:{}};
 ROWS.clear();
 _ui.search.value=_query;
 _ui.search.addEventListener('input',()=>{_query=_ui.search.value;update(WG.state)});
 ctx.on('status',update);
 update(WG.state);
}
function setHTML(key,el,html){
 if(!el||_ui.sig[key]===html)return;
 _ui.sig[key]=html;el.innerHTML=html;
}
function update(s){
 if(!_ui)return;
 const m=mode(s),peers=s.peers||[];
 _ui.el.firstChild&&_ui.el.firstChild.setAttribute&&_ui.el.firstChild.setAttribute('data-mode',m);
 setHTML('g',_ui.gauges,gaugesHTML(s,m));
 const sc=schemeHTML(s,m);
 setHTML('s',_ui.scheme,sc);_ui.scheme.hidden=!sc;
 setHTML('m',_ui.meta,metaHTML(s,m,peers));
 setHTML('f',_ui.filter,filterHTML(peers));
 const list=visiblePeers(peers),narrowed=_filter!=='all'||!!_query.trim();
 const shown=_expanded||narrowed?list:list.slice(0,ROW_LIMIT);
 renderRows(_ui.rows,s,m,shown);
 let empty='';
 if(!s.loaded)empty='<p class="ct-msg">'+esc(tr('Waiting for the first data…'))+'</p>';
 else if(!peers.length)empty='<p class="ct-title">'+esc(tr('No clients yet'))+'</p><p class="ct-msg">'+esc(tr('Add the first device — the config and QR code appear right away.'))+'</p>'
  +'<button type="button" class="btn btn-primary" data-act="add-client" data-live'+(s.offline?' disabled':'')+'>'+icon('add',16)+esc(tr('Add client'))+'</button>';
 else if(!list.length)empty='<p class="ct-title">'+esc(tr('Nobody matches'))+'</p><button type="button" class="btn btn-outline" data-act="cl-reset">'+esc(tr('Reset filters'))+'</button>';
 setHTML('e',_ui.empty,empty);_ui.empty.hidden=!empty;
 const rest=list.length-shown.length;
 setHTML('x',_ui.more,rest>0?'<button type="button" class="cl-morebtn" data-act="cl-more">'+esc(tr('+ {n} more ↓',{n:WG.count(rest,'client')}))+'</button>':'');
 setHTML('h',_ui.host,s.loaded?esc(hostText(s.host)):'');
}

/* ------------------------------------------------------------ actions */
function pkOf(el){const r=el.closest('[data-pk]');return r?r.getAttribute('data-pk'):''}
WG.delegate('cl-filter',el=>{
 _filter=el.getAttribute('data-f');
 try{localStorage.setItem('wgui-clients-filter',_filter)}catch(e){}
 update(WG.state);
});
WG.delegate('cl-reset',()=>{_filter='all';_query='';if(_ui)_ui.search.value='';try{localStorage.setItem('wgui-clients-filter','all')}catch(e){}update(WG.state)});
WG.delegate('cl-more',()=>{_expanded=true;update(WG.state)});
WG.delegate('cl-qr',el=>WG.actions.showConfig(pkOf(el)));
WG.delegate('cl-enable',el=>WG.actions.toggleEnabled(pkOf(el)));
WG.delegate('cl-extend',el=>WG.actions.editClient(pkOf(el)));
WG.delegate('cl-menu',el=>{
 const pk=pkOf(el),p=WG.peer(pk);if(!p)return;
 WG.menu.open(el,clientMenu(p),{title:p.name});
});
function clientMenu(p){
 const s=WG.state,m=mode(s),pk=p.pubkey,other=p.exit==='us'?'nl':'us',x=exitInfo(s,other),O=exitLabel(other);
 let hint,tone='',blocked=false;
 if(x.exhausted){hint=tr('{exit} quota used up',{exit:O});tone='bad';blocked=true}
 else if(isUnknown(m)){hint=tr('{exit} not checked',{exit:O})}
 else if(x.health==='down'){hint=tr('{exit} is down',{exit:O});tone='bad';blocked=true}
 else if(x.health==='ok'){hint=tr('{exit} ok · {p}%',{exit:O,p:Math.floor(x.ratio*100)});tone=x.ratio>=.7?'warn':'ok'}
 else hint=tr('{exit} not checked',{exit:O});
 return[
  {icon:'qr',label:tr('Config and QR'),key:'q',act:()=>WG.actions.showConfig(pk)},
  {icon:'edit',label:tr('Edit client'),key:'e',act:()=>WG.actions.editClient(pk)},
  {icon:'switch-exit',label:tr('Move to {exit}',{exit:O}),hint,hintTone:tone,disabled:blocked,act:()=>WG.actions.switchExit(pk,other)},
  {icon:'journal',label:tr('Connection history'),key:'h',act:()=>WG.actions.showConfig(pk,{section:'history'})},
  {type:'sep'},
  p.enabled?{icon:'power',label:tr('Turn off'),hint:tr('can be undone'),act:()=>WG.actions.toggleEnabled(pk)}
   :{icon:'power',label:tr('Turn on'),act:()=>WG.actions.toggleEnabled(pk)},
  {type:'sep'},
  {icon:'delete',label:tr('Delete client…'),danger:true,act:()=>WG.actions.deleteClient(pk)}
 ];
}

/* ------------------------------------------------------------ plaques (DS-2, D-priority)
 * Derived from every status poll, whatever section is open. One shows at a time:
 * outage → stale / no connection → failover and switches → quota. Each has an action. */
WG.addStrings('ru',{
 'Outage':'Авария','Data is stale':'Данные устарели','No connection':'Нет связи','Failure {exit}':'Сбой {exit}',
 'Switch':'Переключение','Auto-switch':'Автопереключение','Quota {exit}':'Квота {exit}',
 'Both exits are down since {t}.':'Оба выхода недоступны с {t}.',
 'Affected: {n} enabled, {k} of them connected to the entry.':'Затронуто {n} включённых, {k} из них подключены ко входу.',
 'RU subnets work directly — split is on.':'Подсети РФ работают напрямую — сплит включён.',
 'Split is off, so client traffic has no way out.':'Сплит выключен — трафику клиентов некуда выйти.',
 '{exit} does not answer since {t}: {n} enabled without an exit.':'{exit} не отвечает с {t}: без выхода {n} включённых.',
 'Automatic switch did not run: {r}':'Автопереключение не выполнено: {r}',
 'Automatic failover is off.':'Автопереключение при сбое выключено.',
 'The server answers but has not refreshed the state for {t} — data collection is stuck. Values below are from {at}; things may be different now.':
  'Сервер отвечает, но не обновлял состояние {t} — сбор данных завис. Ниже значения на {at}, сейчас всё может быть иначе.',
 'The panel does not answer. Showing data from {at} ({t}); actions are off.':'Панель не отвечает. Показаны данные от {at} ({t}), действия выключены.',
 'The server did not answer in 12 s. Showing data from {at} ({t}); actions are off.':'Сервер не ответил за 12 с. Показаны данные от {at} ({t}), действия выключены.',
 'The panel does not answer and there is no data yet.':'Панель не отвечает, данных пока нет.',
 'retry in {n} s':'повтор через {n} с',
 '{at} — {n} moved {from} → {to}. {from} failed its checks several times in a row.':'{at} — {n} переведены {from} → {to}. {from} не прошёл проверки несколько раз подряд.',
 '{at} — {n} moved {from} → {to}: the monthly quota of {from} ran out.':'{at} — {n} переведены {from} → {to}: месячная квота {from} исчерпана.',
 '{exit} healthy again since {t}':'{exit} снова в норме с {t}','{exit} still down':'{exit} пока недоступен',
 'Move {n} back to {exit}':'Вернуть {n} на {exit}',
 '{exit} used {p}% of its monthly quota ({u} of {q}).':'{exit} израсходовал {p}% месячной квоты ({u} из {q}).',
 'The {exit} quota is used up ({u} of {q}).':'Квота {exit} исчерпана ({u} из {q}).',
 'At 100% its clients move to {other} automatically.':'При 100% клиенты перейдут на {other} автоматически.',
 'Its clients move to {other} automatically.':'Клиенты переводятся на {other} автоматически.',
 'Switching by quota is off.':'Переключение по квоте выключено.',
 'Exits':'Выходы','Journal':'Журнал','Retry now':'Повторить сейчас','Configure':'Настроить'
});
const SWITCH_BANNER_S=24*3600;
function deriveBanners(s){
 const m=mode(s),want={},nowTs=now(s),pol=s.exit_policy||{},go=name=>()=>WG.router.go(name);
 const toExits={label:tr('Exits'),act:go('exits'),primary:true};
 const toJournal={label:tr('Journal'),act:go('journal')};
 if(m==='offline'){
  const age=WG.dataAge();
  const text=!s.loaded?tr('The panel does not answer and there is no data yet.')
   :tr(s.timedOut?'The server did not answer in 12 s. Showing data from {at} ({t}); actions are off.':'The panel does not answer. Showing data from {at} ({t}); actions are off.',
    {at:WG.fmtTime(s.dataAt),t:WG.fmtAgo(age)});
  want.offline={level:'offline',tag:tr('No connection'),icon:'offline',text,note:tr('retry in {n} s'),countdownTo:s.retryAt,
   actions:[{label:tr('Retry now'),act:()=>WG.refresh()}]};
 }else if(m==='stale'){
  want.stale={level:'stale',tag:tr('Data is stale'),icon:'clock',
   text:tr('The server answers but has not refreshed the state for {t} — data collection is stuck. Values below are from {at}; things may be different now.',
    {t:WG.fmtAgo(+s.snapshot_age||0,{suffix:false}),at:WG.fmtTime(s.dataAt)}),actions:[toJournal]};
 }else if(m==='crash'){
  const xs=WG.EXITS.map(k=>exitInfo(s,k)),since=Math.max.apply(null,xs.map(x=>+(x.t&&x.t.health_since)||0));
  const enabled=(s.peers||[]).filter(p=>p.enabled),connected=enabled.filter(p=>p.online).length;
  want.crash={level:'crash',tag:tr('Outage'),icon:'error',note:since?WG.fmtAgo(nowTs-since,{suffix:false}):'',
   text:tr('Both exits are down since {t}.',{t:since?WG.fmtTime(since):'—'})+' '
    +tr('Affected: {n} enabled, {k} of them connected to the entry.',{n:enabled.length,k:connected})+' '
    +tr(s.rud?'RU subnets work directly — split is on.':'Split is off, so client traffic has no way out.'),
   actions:[toExits,toJournal]};
 }else if(m==='live'){
  WG.EXITS.map(k=>exitInfo(s,k)).forEach(x=>{
   const aff=+(x.t&&x.t.affected_clients)||0;
   if(!x.t||x.t.ok||!aff)return;
   const since=+x.t.health_since||0,hb=pol.health_blocked;
   let extra='';
   if(pol.health_failover===false)extra=' '+tr('Automatic failover is off.');
   else if(hb)extra=' '+tr('Automatic switch did not run: {r}',{r:WG.reasonText(hb.code||hb)});
   want['down-'+x.key]={level:'crash',tag:tr('Failure {exit}',{exit:exitLabel(x.key)}),icon:'error',
    note:since?WG.fmtAgo(nowTs-since,{suffix:false}):'',
    text:tr('{exit} does not answer since {t}: {n} enabled without an exit.',{exit:exitLabel(x.key),t:since?WG.fmtTime(since):'—',n:aff})+extra,
    actions:[toExits]};
  });
 }
 const ls=pol.last_switch;
 if(ls&&typeof ls==='object'&&!ls.revert_of&&ls.changed!==false&&+ls.ts>0&&nowTs-ls.ts<SWITCH_BANNER_S
  &&(ls.reason==='health'||ls.reason==='quota')&&WG.EXITS.indexOf(ls.source)>=0&&WG.EXITS.indexOf(ls.target)>=0){
  const n=+ls.members_count||0,from=exitLabel(ls.source),to=exitLabel(ls.target),src=exitInfo(s,ls.source);
  const who=n?WG.count(n,'client'):tr('clients');
  const at=WG.fmtTime(ls.ts);
  if(ls.reason==='health'){
   const healthy=src.health==='ok',since=src.t&&+src.t.health_since;
   const canRevert=healthy&&n>0&&+ls.event_id>0;
   want.failover={level:'failover',tag:tr('Failure {exit}',{exit:from}),icon:'warning',
    text:tr('{at} — {n} moved {from} → {to}. {from} failed its checks several times in a row.',{at,n:who,from,to}),
    note:isUnknown(m)?'':healthy?tr('{exit} healthy again since {t}',{exit:from,t:since?WG.fmtTime(since):'—'}):tr('{exit} still down',{exit:from}),
    actions:[canRevert?{label:tr('Move {n} back to {exit}',{n,exit:from}),act:()=>WG.actions.revertSwitch(+ls.event_id),primary:true,live:true}:toExits],
    dismiss:'switch:'+(ls.event_id||ls.ts)};
  }else{
   want.failover={level:'failover',tag:tr('Switch'),icon:'switch-exit',
    text:tr('{at} — {n} moved {from} → {to}: the monthly quota of {from} ran out.',{at,n:who,from,to}),
    actions:[toExits],dismiss:'switch:'+(ls.event_id||ls.ts)};
  }
 }
 const blocked=pol.blocked;
 if(blocked&&!want.failover&&!Object.keys(want).some(k=>k.indexOf('down-')===0)){
  want.blocked={level:'failover',tag:tr('Auto-switch'),icon:'warning',
   text:tr('Automatic switch did not run: {r}',{r:WG.reasonText(blocked.code||blocked)}),actions:[toExits]};
 }
 WG.EXITS.map(k=>exitInfo(s,k)).forEach(x=>{
  if(!x.quota||x.ratio<.9||!x.clients)return;
  const other=exitLabel(x.key==='us'?'nl':'us'),E=exitLabel(x.key),u=gib(x.used)+' '+GIB(),q=gib(x.quota)+' '+GIB();
  const first=x.exhausted?tr('The {exit} quota is used up ({u} of {q}).',{exit:E,u,q}):tr('{exit} used {p}% of its monthly quota ({u} of {q}).',{exit:E,p:Math.floor(x.ratio*100),u,q});
  const then=pol.auto_switch===false?tr('Switching by quota is off.'):tr(x.exhausted?'Its clients move to {other} automatically.':'At 100% its clients move to {other} automatically.',{other});
  want['quota-'+x.key]={level:'quota',tag:tr('Quota {exit}',{exit:E}),icon:'usage',text:first+' '+then,
   actions:[{label:tr('Configure'),act:()=>WG.actions.exitsSettings(),live:true}],
   dismiss:'quota:'+x.key+':'+(x.exhausted?'full':'90')+':'+new Date(nowTs*1000).toISOString().slice(0,7)};
 });
 ['offline','stale','crash','down-nl','down-us','failover','blocked','quota-nl','quota-us'].forEach(id=>{
  if(want[id])WG.banner.set(id,want[id],true);else WG.banner.clear(id,true);
 });
 WG.banner.render();
}
WG.addStrings('ru',{'clients':'клиенты'});
WG.on('status',deriveBanners);

/* ------------------------------------------------------------ placeholders */
function placeholder(name,title,action){
 return function(el){
  el.innerHTML='<div class="ph"><h1 class="ph-t">'+esc(title)+'</h1>'
   +'<p class="prose muted">'+esc(tr('This section moves to the new design in the next step.'))+'</p>'
   +(action?'<div><button class="btn btn-outline" type="button" data-act="ph-'+name+'">'+esc(tr(action))+'</button></div>':'')+'</div>';
 };
}
WG.delegate('ph-exits',()=>WG.actions.exitsSettings());
WG.delegate('ph-split',()=>WG.actions.splitSettings());

WG.router.register('clients',{title:tr('Clients'),icon:'clients',mobileTab:true,render:renderPage,leave(){_ui=null}});
WG.router.register('exits',{title:tr('Exits'),icon:'exits',mobileTab:true,render:placeholder('exits',tr('Exits'),'Open exit settings')});
WG.router.register('split',{title:tr('Split'),icon:'split',render:placeholder('split',tr('Split tunnel'),'Open split tunnel')});
WG.router.register('usage',{title:tr('Usage'),icon:'usage',mobileTab:true,render:placeholder('usage',tr('Usage'))});
WG.router.register('journal',{title:tr('Journal'),icon:'journal',render:placeholder('journal',tr('Journal'))});

WG.dashboard={mode,exitInfo,rowHTML,renderRows,visiblePeers,gaugesHTML,schemeHTML,clientMenu,expiry,hostText};
})();
