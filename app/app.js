const CSRF=document.querySelector('meta[name=csrf]').content;
let _act="";   /* pubkey the currently-open modal acts on (avoids quoting args into onclick) */
const IP={d:'<path d="M2 3h20v14H2z"/><path d="M8 21h8M12 17v4"/>',
 srv:'<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01M6 18h.01"/>',
 net:'<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',edit:'<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
 pow:'<path d="M18.4 6.6a9 9 0 1 1-12.8 0"/><path d="M12 2v10"/>',
 trash:'<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
 dl:'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/>',
 qr:'<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3M21 14v7h-7M17 21h.01"/>',
 copy:'<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
 chart:'<path d="M3 3v18h18"/><rect x="7" y="11" width="3" height="6"/><rect x="12" y="7" width="3" height="10"/><rect x="17" y="13" width="3" height="4"/>',
 phone:'<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
 laptop:'<rect x="4" y="5" width="16" height="11" rx="1"/><path d="M2 20h20"/>',
 tablet:'<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M11 18h2"/>',
 router:'<rect x="2" y="13" width="20" height="8" rx="2"/><path d="M6.5 17h.01M12 13V8M9 9l3-3 3 3"/>',
 user:'<circle cx="12" cy="8" r="3.5"/><path d="M5.5 20a6.5 6.5 0 0 1 13 0"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 cal:'<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/>',
 branch:'<line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
 list:'<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
 hist:'<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/>',
 check:'<path d="M20 6 9 17l-5-5"/>'};
function devIcon(name){const s=(name||'').toLowerCase();
 if(/phone|iphone|android|pixel|galaxy|redmi|xiaomi|moto|oneplus/.test(s))return 'phone';
 if(/mac|book|laptop|notebook|thinkpad|\bpc\b|win|ubuntu|linux|desktop|imac/.test(s))return 'laptop';
 if(/pad|tablet|kindle/.test(s))return 'tablet';
 if(/router|gateway|keenetic|mikrotik|openwrt|\brt-|nas|vps|server|srv/.test(s))return 'router';
 if(/^[a-zа-я]+[-_][a-zа-я]+$/i.test(s))return 'user';
 return 'd';}
function csparkSVG(s){
 if(!s||s.length<2)return '';
 const mx=Math.max.apply(null,s);if(mx<=0)return '';
 const W=600,H=24,n=s.length,X=i=>W*i/(n-1),Y=v=>H-1.5-(H-4)*v/mx;
 let ln='';for(let i=0;i<n;i++)ln+=(i?'L':'M')+X(i).toFixed(1)+' '+Y(s[i]).toFixed(1);
 return '<svg class="csv" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none"><path class="ca" d="'+ln+' L'+W+' '+H+' L0 '+H+' Z"/><path class="cl" d="'+ln+'"/></svg>';}
function ic(n,s){s=s||16;return '<svg width="'+s+'" height="'+s+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'+IP[n]+'</svg>';}
const fmtB=n=>{n=+n;const u=["B","KiB","MiB","GiB","TiB","PiB"];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return n.toFixed(1)+" "+u[i]};
const fmtAge=s=>{const r=LANG==='ru';if(s<0)return r?"никогда":"never";if(s<60)return s+(r?"с назад":"s ago");if(s<3600)return(s/60|0)+(r?"м назад":"m ago");if(s<86400)return(s/3600|0)+(r?"ч ":"h ")+((s%3600)/60|0)+(r?"м назад":"m ago");return(s/86400|0)+(r?"д назад":"d ago")};
const fmtTime=ts=>{const d=new Date(ts*1000),p=n=>(''+n).padStart(2,'0');return p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes())};
const fmtLeft=s=>{const r=LANG==='ru';if(s<=0)return r?"истёк":"expired";if(s<3600)return(s/60|0)+(r?"м":"m left");if(s<86400)return(s/3600|0)+(r?"ч":"h left");return Math.ceil(s/86400)+(r?"д":"d left")};
const mbit=bps=>(bps*8/1e6).toFixed(bps*8/1e6>=10?0:1);
const esc=s=>s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
/* i18n */
let LANG=(function(){try{return localStorage.getItem('wgui-lang')||'ru'}catch(e){return'ru'}})();
const RU={
 "client status":"статус клиентов","Throughput":"Трафик","last 5 min":"за 5 мин","Clients":"Клиенты",
 "online":"онлайн","offline":"оффлайн","never":"никогда","reconnecting…":"переподключение…","updated":"обновлено",
 "collecting throughput…":"собираю данные…","devices":"устройства","entry · RU":"вход · РФ","exit · NL":"выход · NL",
 "You":"Вы","Internet":"Интернет","egress checked":"выход проверен","total":"всего",
 "cascade up":"каскад работает","tunnel up · no exit":"туннель есть · нет выхода","tunnel down":"туннель упал",
 "RU → direct":"РФ → напрямую","logout":"выход","disabled":"выключен","load avg":"загрузка","uptime":"аптайм",
 "read-only status · writes via secure helper":"только чтение · запись через защищённый хелпер",
 "Split":"Сплит","Usage":"Трафик","Log":"Журнал","Backup":"Бэкап","+ Add client":"+ Клиент",
 "Add client":"Добавить клиента","Name":"Имя","Expires":"Истекает","Never":"Никогда","in 1 day":"через 1 день",
 "in 7 days":"через 7 дней","in 30 days":"через 30 дней","Cancel":"Отмена","Create":"Создать","Done":"Готово",
 "Copy":"Копировать","Rename":"Переименовать","Rename client":"Переименовать клиента","Save":"Сохранить",
 "Delete":"Удалить","Recent connections":"Недавние подключения","Audit log":"Журнал действий","Split-tunnel":"Сплит-туннель",
 "RU + custom direct":"РФ + свои правила","Route RU traffic direct":"РФ-трафик напрямую","Refresh RU list":"Обновить список РФ",
 "Save list":"Сохранить список","Close":"Закрыть","By client · this month":"По клиентам · за месяц",
 "No traffic yet this month.":"Трафика за месяц пока нет.","No admin actions logged yet.":"Действий пока не было.",
 "No usage recorded yet — history accrues from now (sampled every minute). Check back later.":"Данных пока нет — история копится с этого момента (раз в минуту). Загляни позже.",
 "Toggle theme":"Сменить тему","Sign out":"Выйти","Show config / QR":"Конфиг / QR","Enable":"Включить","Disable":"Выключить",
 "Tunnel address":"Адрес в туннеле","Client public endpoint":"Публичный адрес клиента","Last handshake":"Последний handshake",
 "Last WireGuard handshake":"Последний WireGuard handshake","Total since connect":"Всего с подключения",
 "Traffic this calendar month":"Трафик за календарный месяц","Temporary client (auto-disables)":"Временный клиент (сам выключится)",
 "Online — recent handshake":"Онлайн — свежий handshake","Offline":"Оффлайн","Disabled":"Выключен",
 "Throughput, last ~2 min":"Трафик за ~2 мин","Entry-node CPU load":"Загрузка CPU входной ноды","Memory used / total":"Память занято / всего",
 "Load average 1·5·15 min":"Средняя загрузка 1·5·15 мин","Entry-node uptime":"Аптайм входной ноды",
 "Aggregate live throughput across all clients":"Суммарный трафик всех клиентов",
 "Your devices connect to the entry node":"Твои устройства подключаются к входной ноде",
 "Entry node · Russia · 203.0.113.10":"Входная нода · Россия · 203.0.113.10",
 "Traffic exits the internet with the DO IP":"Трафик выходит в интернет с IP DO",
 "Last WireGuard handshake on the VDSina→DO link":"Последний handshake на линке VDSina→DO",
 "Last live exit-IP verification":"Последняя проверка exit-IP",
 "RU traffic bypasses the cascade and exits directly via VDSina (RU IP)":"РФ-трафик идёт мимо каскада и выходит напрямую через VDSina (РФ IP)",
 "Split-tunnel policy (what bypasses the cascade)":"Политика сплит-туннеля (что мимо каскада)",
 "Traffic history and monthly usage":"История трафика и расход за месяц",
 "Audit log — recent admin actions":"Журнал — недавние действия","Download a backup (configs + keys)":"Скачать бэкап (конфиги + ключи)",
 "Generate a new client config":"Сгенерировать конфиг клиента","Re-download the RU list from the internet":"Перекачать список РФ из интернета",
 "Turn ON":"Включить","Turn OFF":"Выключить","peak":"пик","Config copied":"Конфиг скопирован","Copy failed":"Не скопировалось",
 "Preparing backup…":"Готовлю бэкап…","Backup downloaded — keep it safe (contains private keys)":"Бэкап скачан — храни в надёжном месте (внутри приватные ключи)",
 "sign in to manage the cascade":"войдите для управления каскадом","Username":"Логин","Password":"Пароль","Sign in":"Войти",
 "Invalid username or password":"Неверный логин или пароль"
};
function tr(s){return LANG==='ru'&&RU[s]?RU[s]:s}
function applyI18n(root){
 if(LANG!=='ru')return;
 root=root||document.body;
 const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),ns=[];let n;while(n=w.nextNode())ns.push(n);
 ns.forEach(t=>{const k=t.nodeValue.trim();if(k&&RU[k])t.nodeValue=t.nodeValue.replace(k,RU[k])});
 root.querySelectorAll&&root.querySelectorAll('[data-tip]').forEach(e=>{const k=e.getAttribute('data-tip');if(RU[k])e.setAttribute('data-tip',RU[k])});
}
function toggleLang(){LANG=LANG==='ru'?'en':'ru';try{localStorage.setItem('wgui-lang',LANG)}catch(e){}
 const b=document.getElementById('lang');if(b)b.textContent=LANG==='ru'?'EN':'RU';location.reload()}
function setLangBtn(){const b=document.getElementById('lang');if(b)b.textContent=LANG==='ru'?'EN':'RU'}
const octet=ip=>{const p=(''+ip).split('.');return +p[p.length-1]||0};
const mbN=bps=>bps*8/1e6, mbF=v=>v.toFixed(v>=10?0:1);
const _pv={};                 /* previous numeric values, keyed -> for tweening */
function tw(el,key,to,fmt){
 const from=(_pv[key]==null)?to:_pv[key]; _pv[key]=to;
 if(el.__raf)cancelAnimationFrame(el.__raf);
 if(from===to||window.matchMedia&&matchMedia('(prefers-reduced-motion:reduce)').matches){el.textContent=fmt(to);return}
 const t0=performance.now();
 function step(now){let k=Math.min(1,(now-t0)/600);k=1-Math.pow(1-k,3);el.textContent=fmt(from+(to-from)*k);el.__raf=k<1?requestAnimationFrame(step):0}
 el.__raf=requestAnimationFrame(step);
}
function thrPills(c){
 const thr=document.getElementById('thr');
 if(!thr.__i){thr.__i=1;thr.innerHTML='<span class="dn">↓ <b id="thrd">0</b></span> <span class="up">↑ <b id="thru">0</b></span> Mbit/s';}
 const cn=document.getElementById('chartnow');
 if(!cn.__i){cn.__i=1;cn.innerHTML='<span class="dn">↓ <b id="cnd">0</b></span> <span class="up">↑ <b id="cnu">0</b></span> Mbit/s';}
 const md=mbN(c.down),mu=mbN(c.up);
 tw(document.getElementById('thrd'),'thrd',md,mbF);tw(document.getElementById('thru'),'thru',mu,mbF);
 tw(document.getElementById('cnd'),'cnd',md,mbF);tw(document.getElementById('cnu'),'cnu',mu,mbF);
}

let _cascKey="";
function renderCascade(t,rud){
 const cls={up:'ok',degraded:'warn',down:'bad'}[t.state];
 const flow=t.state==='up'?'flow':(t.state==='degraded'?'warn':'bad');
 const exitIP=(t.exit_seen||t.exit_ip);
 const key=t.state+'|'+exitIP+'|'+(rud?1:0);
 if(key!==_cascKey){           // rebuild the diagram only when state changes -> smooth flow animation
  _cascKey=key;
  document.getElementById('cascade').innerHTML=
   '<div class="hop"><div class="hicon live" data-tip="Your devices connect to the entry node">'+ic('d',22)+'</div><div class="hname">You</div><div class="hsub">devices</div></div>'
  +'<div class="link flow"></div>'
  +'<div class="hop"><div class="hicon ok" data-tip="Entry node · Russia · 203.0.113.10">'+ic('srv',22)+'</div><div class="hname">VDSina</div><div class="hsub">entry · RU</div></div>'
  +'<div class="link '+flow+'"></div>'
  +'<div class="hop"><div class="hicon '+cls+'" data-tip="Exit node · Amsterdam, NL · '+exitIP+'">'+ic('srv',22)+'</div><div class="hname">DO</div><div class="hsub">exit · NL</div></div>'
  +'<div class="link '+(t.state==='up'?'flow':cls)+'"></div>'
  +'<div class="hop"><div class="hicon '+(t.state==='up'?'live':cls)+'" data-tip="Traffic exits the internet with the DO IP">'+ic('net',22)+'</div><div class="hname">Internet</div><div class="hsub mono">'+exitIP+'</div></div>';
 }
 const lbl={up:'cascade up',degraded:'tunnel up · no exit',down:'tunnel down'}[t.state];
 document.getElementById('tline').innerHTML='<span class="st '+cls+'">● '+tr(lbl)+'</span>'
  +(rud?'<span class="rud" data-tip="RU traffic bypasses the cascade and exits directly via VDSina (RU IP)">'+ic('branch')+tr('RU → direct')+'</span>':'')
  +'<span data-tip="Last WireGuard handshake on the VDSina→DO link">wg-do ⇅ '+fmtAge(t.wg_age)+'</span>'
  +(t.checked_age>=0?'<span data-tip="Last live exit-IP verification">'+tr('egress checked')+' '+fmtAge(t.checked_age)+'</span>':'');
}
function renderHost(h){
 const el=document.getElementById('hostbar');
 if(!h){el.style.display='none';return}
 el.style.display='flex';
 if(!el.__i){el.__i=1;el.innerHTML=
   '<div class="ht-h" data-tip="VDSina entry node — the cascade performance ceiling (1 vCPU, double crypto)">VDSina <span>entry · RU</span></div>'
  +'<div class="ht-cpu"><span>CPU</span><b id="vcpu">0</b><span>%</span><div class="ht-bar"><i id="cpubar"></i></div></div>'
  +'<div class="ht-row"><span>RAM</span><b id="hbram"></b></div>'
  +'<div class="ht-row"><span>load avg</span><b id="hbload"></b></div>'
  +'<div class="ht-row"><span>uptime</span><b id="hbup"></b></div>';}
 const cc=h.cpu>=85?'bad':(h.cpu>=60?'warn':'');
 const bar=document.getElementById('cpubar');
 bar.style.width=Math.min(100,h.cpu)+'%';
 bar.style.background=cc==='bad'?'var(--red)':(cc==='warn'?'var(--amber)':'var(--green)');
 tw(document.getElementById('vcpu'),'cpu',h.cpu,v=>Math.round(v));
 const gb=b=>(b/1073741824).toFixed(1);
 document.getElementById('hbram').textContent=gb(h.mem_used)+' / '+gb(h.mem_total)+' GB';
 document.getElementById('hbload').textContent=h.load.map(x=>x.toFixed(2)).join('  ');
 document.getElementById('hbup').textContent=(h.uptime/86400|0)+'d '+((h.uptime%86400)/3600|0)+'h';
}
function spark(series){
 const W=600,H=56,pad=3;
 if(series.length<2)return '<text x="8" y="32" class="ph">collecting throughput…</text>';
 const max=Math.max(1,...series.map(s=>Math.max(s.down,s.up)));
 const n=series.length,X=i=>pad+(W-2*pad)*i/(n-1),Y=v=>H-pad-(H-2*pad)*v/max;
 const ln=k=>series.map((s,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(s[k]).toFixed(1)).join(' ');
 const ar=k=>ln(k)+' L'+X(n-1).toFixed(1)+' '+H+' L'+X(0).toFixed(1)+' '+H+' Z';
 return '<path class="ar dn" d="'+ar('down')+'"/><path class="ar up" d="'+ar('up')+'"/><path class="ln dn" d="'+ln('down')+'"/><path class="ln up" d="'+ln('up')+'"/>';
}
function renderClients(peers){
 peers=peers.slice().sort((a,b)=>octet(a.ip)-octet(b.ip));   // stable order so cards don't jump
 document.getElementById('csum').textContent=peers.filter(p=>p.online).length+' '+tr('online')+' · '+peers.length+' '+(LANG==='ru'?'всего':'total');
 document.getElementById('cards').innerHTML=peers.map(p=>{
  const pj=JSON.stringify(p.pubkey),nj=JSON.stringify(p.name);
  const prevAge=_pv['age-'+p.pubkey];
  const fresh=p.online&&prevAge!=null&&p.age>=0&&p.age<prevAge;   // handshake just refreshed
  _pv['age-'+p.pubkey]=p.age;
  const prx=_pv['rx-'+p.pubkey],ptx=_pv['tx-'+p.pubkey];          // for smooth count from previous
  const acts=
   '<button class="ib" data-tip="Show config / QR" onclick=\'showCfg('+pj+')\'>'+ic('qr')+'</button>'
  +'<button class="ib" data-tip="Rename" onclick=\'openRename('+pj+','+nj+')\'>'+ic('edit')+'</button>'
  +'<button class="ib '+(p.enabled?'':'good')+'" data-tip="'+(p.enabled?'Disable':'Enable')+'" onclick=\'toggleEn('+pj+','+(p.enabled?'true':'false')+')\'>'+ic('pow')+'</button>'
  +'<button class="ib danger" data-tip="Delete" onclick=\'confirmDel('+pj+','+nj+')\'>'+ic('trash')+'</button>';
  const sv=csparkSVG(p.spark);
  return '<div class="crow '+(p.online?'on':'')+' '+(p.enabled?'':'off-cl')+(fresh?' flash':'')+'">'
   +'<div class="ctop"><div class="av" data-tip="'+(p.online?'Online — recent handshake':(p.enabled?'Offline':'Disabled'))+'">'+ic(devIcon(p.name),20)+'<span class="avdot '+(p.online?'on':'')+'"></span></div>'
   +'<div class="idc"><div class="nm">'+esc(p.name)
   +(p.expires?'<span class="chip '+((p.expires-(Date.now()/1000|0))<=0?'chip-exp':'chip-tmp')+'" data-tip="Temporary client (auto-disables)">'+ic('clock',10)+fmtLeft(p.expires-(Date.now()/1000|0))+'</span>':'')
   +(p.enabled?'':'<span class="chip">disabled</span>')+'</div>'
   +'<div class="ipa mono" data-tip="Tunnel address">'+p.ip+'</div>'
   +(p.endpoint?'<div class="ep mono" data-tip="Client public endpoint">'+ic('net',11)+p.endpoint+'</div>':'')+'</div></div>'
   +'<div class="stat '+(p.online?'':'o')+'"><div class="hs" data-tip="Last WireGuard handshake">'+(p.online?'online':'offline')+'</div>'
   +'<div data-tip="Last handshake">'+ic('clock',11)+fmtAge(p.age)+'</div><div class="xfer mono" data-tip="Total since connect"><span class="dn">↓ <b class="vx" data-k="rx-'+p.pubkey+'" data-to="'+p.rx+'">'+fmtB(prx==null?p.rx:prx)+'</b></span><span class="up">↑ <b class="vx" data-k="tx-'+p.pubkey+'" data-to="'+p.tx+'">'+fmtB(ptx==null?p.tx:ptx)+'</b></span></div>'
   +((p.mrx||p.mtx)?'<div class="mo mono" data-tip="Traffic this calendar month">'+ic('cal',11)+'↓'+fmtB(p.mrx)+' ↑'+fmtB(p.mtx)+'</div>':'')+'</div>'
   +'<div class="acts">'+acts+'</div>'
   +(sv?'<div class="cspark" data-tip="Throughput, last ~2 min">'+sv+'</div>':'')+'</div>';
 }).join('');
 document.querySelectorAll('#cards .vx').forEach(b=>tw(b,b.dataset.k,+b.dataset.to,fmtB));
}
async function tick(){
 try{
  const r=await fetch("/api/status",{cache:"no-store"});
  if(r.status===401){location.href="/login";return}
  const d=await r.json();
  renderCascade(d.tunnel,d.rud);renderHost(d.host);renderClients(d.peers);
  thrPills(d.thr.cur);
  document.getElementById('spark').innerHTML=spark(d.thr.series);
  document.getElementById('upd').textContent=tr('updated')+' '+new Date(d.now*1000).toLocaleTimeString();
  applyI18n();
 }catch(e){document.getElementById('upd').textContent=tr('reconnecting…')}
}
/* admin */
async function admin(body){
 const r=await fetch("/api/admin",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF":CSRF},body:JSON.stringify(body)});
 if(r.status===401){location.href="/login";return{ok:false,error:"session expired"}}
 return r.json();
}
const mbg=()=>document.getElementById('mbg');
function openModal(h){const m=document.getElementById('modal');m.innerHTML=h;applyI18n(m);mbg().classList.add('show');}
function closeModal(){mbg().classList.remove('show')}
function toast(m){const t=document.getElementById('toast');t.textContent=tr(m);t.style.display='block';clearTimeout(window.__tt);window.__tt=setTimeout(()=>t.style.display='none',3200)}
function openAdd(){openModal(
 '<div class="mtitle">'+ic('plus',18)+' Add client</div>'
 +'<label class="fl">Name<input id="cn" placeholder="e.g. iphone, laptop" autocomplete="off"></label>'
 +'<label class="fl">Expires<select id="cx" class="fsel"><option value="0">Never</option><option value="1">in 1 day</option><option value="7">in 7 days</option><option value="30">in 30 days</option></select></label>'
 +'<div class="merr" id="me"></div>'
 +'<div class="mrow"><button class="ghost" onclick="closeModal()">Cancel</button><button class="primary" id="ab" onclick="doAdd()">Create</button></div>');
 setTimeout(()=>{const i=document.getElementById('cn');i.focus();i.onkeydown=e=>{if(e.key==="Enter")doAdd()}},30);}
async function doAdd(){const n=document.getElementById('cn').value.trim();const days=+document.getElementById('cx').value;
 const expires=days>0?((Date.now()/1000|0)+days*86400):0;const b=document.getElementById('ab');
 b.disabled=true;b.textContent='Creating…';const r=await admin({op:'add',name:n,expires:expires});
 if(!r||!r.ok){document.getElementById('me').textContent=(r&&r.error)||'failed';b.disabled=false;b.textContent='Create';return}
 showResult(r);tick();}
function showResult(r){openModal(
 '<div class="mtitle">'+ic('check',18)+' '+esc(r.name)+'<span class="mip">'+r.ip+'</span></div>'
 +(r.split?'<div class="splitnote">'+ic('branch')+'<span>Split-tunnel: RU &amp; local IPs go <b>direct</b>, the rest via the cascade. Large config — import the <b>.conf file</b> (too big for QR), then re-import to apply.</span></div>':'')
 +(r.qr?'<div class="qrwrap"><img src="data:image/png;base64,'+r.qr+'"></div>':'')
 +'<pre class="conf">'+esc(r.conf)+'</pre>'
 +(r.conns&&r.conns.length?'<div class="ulh">'+ic('hist',13)+' Recent connections</div><div class="connlist">'+r.conns.map(c=>'<div class="connrow"><span>'+fmtTime(c.ts)+'</span><span class="mono">'+esc(c.endpoint||'—')+'</span></div>').join('')+'</div>':'')
 +'<div class="mrow"><button class="ghost" onclick="copyConf()">'+ic('copy')+' Copy</button>'
 +'<button class="ghost" onclick="dlConf()">'+ic('dl')+' .conf</button>'
 +'<button class="primary" onclick="closeModal()">Done</button></div>');
 window.__cf=r.conf;window.__cn=r.name;}
function copyConf(){navigator.clipboard.writeText(window.__cf).then(()=>toast('Config copied'),()=>toast('Copy failed'))}
function dlConf(){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([window.__cf],{type:'text/plain'}));
 a.download=window.__cn+'.conf';a.click();URL.revokeObjectURL(a.href)}
async function showCfg(pub){const r=await admin({op:'getconf',pubkey:pub});if(!r||!r.ok){toast((r&&r.error)||'failed');return}
 try{const h=await(await fetch('/api/connections?pub='+encodeURIComponent(pub),{cache:'no-store'})).json();r.conns=h.connections||[]}catch(e){}
 showResult(r)}
async function doExport(){
 toast('Preparing backup…');const r=await admin({op:'export'});
 if(!r||!r.ok){toast((r&&r.error)||'export failed');return}
 const bin=atob(r.archive),arr=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)arr[i]=bin.charCodeAt(i);
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([arr],{type:'application/gzip'}));
 a.download=r.name||'wg-cascade-backup.tar.gz';a.click();URL.revokeObjectURL(a.href);
 toast('Backup downloaded — keep it safe (contains private keys)');
}
function aopcls(op){if(op==='delete'||op==='disable'||op==='expire')return'bad';if(op==='add'||op==='enable')return'ok';return''}
async function openAudit(){
 openModal('<div class="mtitle">'+ic('list',18)+' Audit log</div><div id="aubody" class="mtext">loading…</div>');
 let r;try{r=await(await fetch('/api/audit',{cache:'no-store'})).json()}catch(e){document.getElementById('aubody').textContent='failed to load';return}
 const ev=r.events||[];
 let h=ev.length?'<div class="connlist">'+ev.map(e=>'<div class="aurow"><span class="aop '+aopcls(e.op)+'">'+esc(e.op)+'</span><span class="ad">'+esc(e.detail||'')+'</span><span class="at">'+fmtTime(e.ts)+'</span></div>').join('')+'</div>':'<p class="mtext">No admin actions logged yet.</p>';
 h+='<div class="mrow"><button class="primary" onclick="closeModal()">Done</button></div>';
 const b=document.getElementById('aubody');b.className='';b.innerHTML=h;
}
async function openUsage(){
 openModal('<div class="mtitle">'+ic('chart',18)+' Usage <span class="mip" id="umo"></span></div><div id="ubody" class="mtext">loading…</div>');
 let r;try{r=await(await fetch('/api/history',{cache:'no-store'})).json()}catch(e){document.getElementById('ubody').textContent='failed to load';return}
 document.getElementById('umo').textContent=r.month;renderUsage(r);
}
function renderUsage(r){
 const d=r.daily||[],n=d.length;let h='';
 if(!n){h='<p class="mtext">No usage recorded yet — history accrues from now (sampled every minute). Check back later.</p>';}
 else{
  const max=Math.max(1,...d.map(x=>x.rx+x.tx)),W=380,H=120,base=H-14,slot=W/n,bw=Math.max(2,slot-2);
  let bars='';
  d.forEach((x,i)=>{const X=i*slot+1,hr=x.rx/max*base,hu=x.tx/max*base;
   bars+='<rect x="'+X.toFixed(1)+'" y="'+(base-hr-hu).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+hu.toFixed(1)+'" class="bu"/>'
        +'<rect x="'+X.toFixed(1)+'" y="'+(base-hr).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+hr.toFixed(1)+'" class="bd"/>';});
  h='<div class="umax"><span><b class="dn">↓</b> down · <b class="up">↑</b> up</span><span>peak '+fmtB(max)+'/day</span></div>'
   +'<svg class="ubar" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+bars+'<line x1="0" y1="'+base+'" x2="'+W+'" y2="'+base+'" class="bax"/></svg>'
   +'<div class="udates"><span>'+d[0].day.slice(5)+'</span><span>'+d[n-1].day.slice(5)+'</span></div>';
  const cl=r.clients||[];
  h+='<div class="ulh">By client · this month</div>';
  if(!cl.length){h+='<p class="mtext" style="margin:0 0 6px">No traffic yet this month.</p>';}
  else{const cmax=Math.max(1,...cl.map(c=>c.rx+c.tx));
   cl.forEach(c=>{const t=c.rx+c.tx;h+='<div class="urow"><div class="un">'+esc(c.name)+'</div>'
    +'<div class="ub"><div class="ubf" style="width:'+(t/cmax*100).toFixed(1)+'%"></div></div>'
    +'<div class="ut mono">'+fmtB(t)+'</div></div>';});}
 }
 h+='<div class="mrow"><button class="primary" onclick="closeModal()">Done</button></div>';
 const b=document.getElementById('ubody');b.className='';b.innerHTML=h;
}
async function openSplitSettings(){
 openModal('<div class="mtitle">'+ic('branch',18)+' Split-tunnel <span class="mip">RU + custom direct</span></div><div id="sbody" class="mtext">loading…</div>');
 const r=await admin({op:'splitinfo'});
 if(!r||!r.ok){document.getElementById('sbody').textContent=(r&&r.error)||'failed to load';return}
 renderSplit(r);
}
function renderSplit(r){
 const m=r.meta||{},srv=r.server||{},on=(srv.state==='on');
 let h='<div class="sstoggle '+(on?'on':'')+'"><div><div class="sst-t">Route RU traffic direct</div>'
   +'<div class="sst-s">'+(on?'ON — RU exits via VDSina (RU IP); the rest via the cascade (NL)':'OFF — all client traffic goes through the cascade (NL exit)')+'</div></div>'
   +'<button class="switch '+(on?'on':'')+'" onclick="splitServer('+(on?'false':'true')+')" data-tip="'+(on?'Turn OFF':'Turn ON')+'"><span></span></button></div>'
   +'<div class="ssrow"><div><b>'+(m.ru_count||0).toLocaleString()+'</b> RU subnets · <b>'+(srv.ipset||m.direct_count||0).toLocaleString()+'</b> in set</div>'
   +'<div class="dim">'+(m.built_at?('built '+m.built_at):'')+'</div></div>'
   +'<label class="fl">Also route DIRECT — extra IPs / CIDRs / domains, one per line'
   +'<textarea id="sx" class="ssarea" spellcheck="false" placeholder="example.com&#10;203.0.113.0/24">'+esc((r.extra||[]).join("\n"))+'</textarea></label>'
   +'<div class="merr" id="me"></div>'
   +'<div class="ssbtns"><button class="ghost" id="srf" onclick="splitSave(true)" data-tip="Re-download the RU list from the internet">'+ic('cal')+' Refresh RU list</button></div>'
   +'<div class="splitnote">'+ic('branch')+'<span>Server-side &amp; global — applies to <b>all clients at once</b>, no per-client setup and no re-import. RU sites see VDSina’s RU IP.</span></div>'
   +'<div class="mrow"><button class="ghost" onclick="closeModal()">Close</button><button class="primary" id="ssave" onclick="splitSave(false)">Save list</button></div>';
 const b=document.getElementById('sbody');b.className='';b.innerHTML=h;
}
async function splitServer(on){
 const r=await admin({op:'splitserver',split:on});
 if(!r||!r.ok){toast((r&&r.error)||'failed');return}
 toast('RU-direct '+(on?'enabled':'disabled')+' for all clients');renderSplit(r);
}
async function splitSave(refresh){
 const entries=document.getElementById('sx').value.split(/\n+/).map(s=>s.trim()).filter(Boolean);
 const btn=document.getElementById(refresh?'srf':'ssave'),old=btn.innerHTML;btn.disabled=true;btn.textContent=refresh?'Refreshing…':'Saving…';
 const r=await admin({op:'splitsave',refresh:refresh,entries:entries});
 if(!r||!r.ok){document.getElementById('me').textContent=(r&&r.error)||'failed';btn.disabled=false;btn.innerHTML=old;return}
 toast('List rebuilt · '+(((r.meta&&r.meta.direct_count)||0)).toLocaleString()+' direct routes');renderSplit(r);
}
function openRename(pub,name){_act=pub;openModal(
 '<div class="mtitle">'+ic('edit',18)+' Rename client</div>'
 +'<label class="fl">Name<input id="rn" value="'+esc(name)+'"></label><div class="merr" id="me"></div>'
 +'<div class="mrow"><button class="ghost" onclick="closeModal()">Cancel</button><button class="primary" onclick="doRename()">Save</button></div>');
 setTimeout(()=>{const i=document.getElementById('rn');i.focus();i.select();i.onkeydown=e=>{if(e.key==="Enter")doRename()}},30);}
async function doRename(){const n=document.getElementById('rn').value.trim();const r=await admin({op:'rename',pubkey:_act,name:n});
 if(!r||!r.ok){document.getElementById('me').textContent=(r&&r.error)||'failed';return}closeModal();tick();}
async function toggleEn(pub,en){const r=await admin({op:'enabled',pubkey:pub,enabled:!en});if(!r||!r.ok)toast((r&&r.error)||'failed');tick();}
async function toggleSplit(pub,cur){const r=await admin({op:'split',pubkey:pub,split:!cur});
 if(!r||!r.ok){toast((r&&r.error)||'failed');return}tick();
 if(r.split){showResult(r);toast('Split-tunnel ON — re-import this config on the device');}
 else toast('Full tunnel restored — re-import the config on the device');}
function confirmDel(pub,name){_act=pub;openModal(
 '<div class="mtitle">'+ic('trash',18)+' Delete '+esc(name)+'?</div>'
 +'<p class="mtext">This permanently revokes this client’s access to the cascade. The device will no longer be able to connect.</p>'
 +'<div class="mrow"><button class="ghost" onclick="closeModal()">Cancel</button><button class="btn-danger" onclick="doDel()">Delete</button></div>');}
async function doDel(){const r=await admin({op:'delete',pubkey:_act});closeModal();if(!r||!r.ok)toast((r&&r.error)||'failed');tick();}
document.addEventListener('keydown',e=>{if(e.key==="Escape")closeModal()});
function skelCard(){return '<div class="crow"><div class="ctop"><div class="skel skel-av"></div>'
 +'<div style="flex:1"><div class="skel" style="width:48%;height:14px;margin-bottom:8px"></div><div class="skel" style="width:32%;height:11px"></div></div></div>'
 +'<div class="skel" style="width:64%;height:11px;margin-top:5px"></div><div class="skel" style="width:80%;height:11px;margin-top:7px"></div>'
 +'<div class="skel" style="height:24px;margin-top:10px"></div></div>';}
function renderSkeleton(){
 document.getElementById('cards').innerHTML=skelCard()+skelCard()+skelCard()+skelCard();
 const hb=document.getElementById('hostbar');hb.style.display='flex';
 hb.innerHTML='<div class="skel" style="width:42%;height:13px;margin-bottom:11px"></div>'
  +'<div class="skel" style="height:11px;margin-bottom:9px"></div>'.repeat(4);
 document.getElementById('spark').innerHTML='<rect x="2" y="6" width="596" height="44" rx="6" class="skel-svg"/>';
}
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(function(){})}
setLangBtn();applyI18n();renderSkeleton();tick();setInterval(tick,5000);
