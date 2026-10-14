/* WG core — runtime shared by every screen of the Tablo Light UI (no build step;
 * CSP: scripts from 'self' only, no inline handlers — clicks go through data-act).
 *
 * Load order (index.html): icons.js → core.js → dashboard.js → modals.js → pages.js.
 * WG starts on DOMContentLoaded, after every script has registered its routes/actions.
 *
 * Contract (stage 1 → stages 2B/2C):
 *  Text     WG.tr(key, vars?)            English key → current language; '{x}' ← vars.x
 *           WG.addStrings(lang, dict)    extend the catalog: WG.addStrings('ru', {'Save': 'Сохранить'})
 *           WG.plural(n, {one, few, many, other})  Intl.PluralRules; '{n}' in a form ← n;
 *                                        forms may also be {ru:{…}, en:{…}}
 *           WG.count(n, noun)            '17 клиентов' — nouns: client, day, hour, minute, attempt, exit
 *           WG.lang                      'ru' | 'en';  WG.setLang(lang) stores it and reloads
 *  Format   WG.fmtBytes(n) '33.0 ГиБ' · WG.fmtMbit(bytesPerSec) '4.2 Мбит/с' · WG.fmtAgo(sec, {suffix})
 *           '12 с назад' · WG.fmtDate(ts) '14 окт' · WG.fmtTime(ts, seconds?) '20:41' ·
 *           WG.fmtClock(sec) '2:30' · WG.esc(s)          (ts = unix seconds)
 *  Icons    WG.icon(name, size=16) → '<svg…>' (icons.js; colour = currentColor)
 *  Data     WG.state      last /api/status payload + {loaded, fetchedAt (ms), dataAt (unix s),
 *                         offline, stale, timedOut, fails, retryAt (ms)}
 *           WG.on('status', fn) → unsubscribe; fn(WG.state) after every poll, failed ones too.
 *           Other events: 'route' (name). WG.refresh() polls now and resets the backoff.
 *           WG.unknown()  true while data must not be trusted (offline or stale snapshot)
 *           WG.api(path, {timeout}?) → Promise<json>; 12 s deadline; 401 → /login
 *           WG.admin(body) → Promise<{kind, data, message, steps?}>,
 *                            kind: 'ok' | 'warn' | 'failed' | 'unknown' | 'busy' | 'partial'
 *           WG.targetText(code), WG.reasonText(code)  human text for server codes
 *  Ops      WG.ops.run({key, label, call, done?, undo?, check?, open?}) → Promise<outcome>.
 *           call() returns WG.admin(…) (or an outcome). A key that is running is not started
 *           again — the same promise comes back. Strip (D1): only elapsed time; 'ok' (text: done
 *           or label) fades after 5 s, other outcomes stay until «Понятно» even if the window
 *           that started them is closed; 'unknown' offers «Проверить состояние» (check() + a
 *           refresh), 'busy' — «Повторить», 'partial' lists outcome.steps [{state, text}].
 *           undo: fn → «Отменить» for 10 s after 'ok'; open: {label, act} extra button.
 *           Every finished op except 'busy' refreshes /api/status in the background.
 *           WG.ops.running(key) → bool
 *  Windows  WG.modal.open({title, eyebrow, body, footer, size:'sm'|'md'|'lg', onClose}) → handle
 *             body/footer: HTML string or Node. handle: {el, body, footer, alive(), close(),
 *             api(path)} — api() requests are aborted when the window closes. ≤600 px: bottom
 *             sheet. Focus trap, Esc, focus returns to the opener. One window at a time.
 *           WG.modal.close()
 *           WG.confirm({title, eyebrow, body, confirmLabel, danger, typeToConfirm}) → Promise<bool>
 *           WG.menu.open(anchorEl, items, {title, sheet}?) — items:
 *             {icon, label, hint, hintTone:'ok'|'warn'|'bad', danger, disabled, key, act: fn}
 *             | {type:'sep'} | {type:'segment', icon, label, value, options:[{value, label}], onChange}
 *           WG.delegate(name, fn(el, event)) — handler for [data-act=name] clicks
 *  Routing  WG.router.register(name, {title, icon, render(el, ctx), mobileTab?, nav?})
 *             ctx.on(event, fn) unsubscribes when the route is left; re-registering replaces.
 *             Routes: #/clients (default), #/exits, #/usage, #/journal, #/split.
 *           WG.router.go(name), WG.router.current()
 *  Banners  WG.banner.set(id, {level, tag, icon, text, note, countdownTo, actions:[{label, act,
 *             primary, live}], dismiss}, quiet?) / WG.banner.clear(id, quiet?) / WG.banner.render().
 *             level: crash | stale | offline | failover | quota | info — one banner shows (that
 *             order), the rest fold into «ещё N». dismiss: key remembered by «Скрыть»; '{n}' in
 *             note counts down to countdownTo (ms); live actions are off without a connection.
 *  Actions  WG.actions.<name> — stage 1 stubs; stage 2B assigns real ones with
 *           Object.assign(WG.actions, {…}). addClient(), showConfig(pubkey, {section}?),
 *           editClient(pubkey), toggleEnabled(pubkey), deleteClient(pubkey),
 *           switchExit(pubkey, exit), exitsSettings(), revertSwitch(eventId), splitSettings(),
 *           backup(), logoutAll()
 *  Misc     WG.EXITS ['nl','us'], WG.exitCity(key), WG.peer(pubkey), WG.theme.get()/set(mode)
 */
(function(){
'use strict';
const root=typeof globalThis!=='undefined'?globalThis:window;
const WG=root.WG||(root.WG={});
const doc=document;
const $=id=>doc.getElementById(id);
function store(key,value){
 try{if(value===undefined)return localStorage.getItem(key);localStorage.setItem(key,value)}catch(e){}
 return null;
}

/* ------------------------------------------------------------------ i18n */
let LANG=store('wgui-lang')==='en'?'en':'ru';
const STR={ru:{
 'Skip to content':'К содержимому','Sections':'Разделы','Account':'Аккаунт','Add client':'Добавить клиента',
 'Client':'Клиент','Clients':'Клиенты','Exits':'Выходы','Split':'Сплит','Usage':'Расход','Journal':'Журнал','More':'Ещё',
 'Split tunnel':'Сплит-туннель','Config backup':'Бэкап конфигураций','Theme':'Тема','Language':'Язык',
 'Light':'Светлая','Dark':'Тёмная','Auto':'Авто','Sign out':'Выйти','Sign out everywhere…':'Выйти на всех устройствах…',
 'Sign out on all devices?':'Выйти на всех устройствах?','Sign out everywhere':'Выйти везде',
 'Every session ends, this one too. You will need to sign in again.':'Завершатся все сессии, включая эту. Потом нужно будет войти заново.',
 'Close':'Закрыть','Cancel':'Отмена','Confirm':'Подтвердить','Got it':'Понятно','Retry':'Повторить','Undo':'Отменить',
 'Check state':'Проверить состояние','Retry now':'Повторить сейчас','Hide':'Скрыть','Details':'Подробнее',
 'Type «{text}» to confirm':'Введите «{text}», чтобы подтвердить',
 'data':'данные','ago':'назад','never':'никогда','s':'с','min':'мин','h':'ч',
 'RU direct · on':'РФ напрямую · вкл','RU direct · off':'РФ напрямую · выкл',
 'Coming soon':'Скоро','This window moves to the new design in the next step.':'Это окно переезжает в новый дизайн на следующем этапе.',
 'This section moves to the new design in the next step.':'Этот раздел переезжает в новый дизайн на следующем этапе.',
 'Amsterdam':'Амстердам','New York':'Нью-Йорк','Mbit/s':'Мбит/с',
 'and {n} more':'ещё {n}','Show less':'Свернуть',
 'Session expired — sign in again':'Сессия истекла — войдите снова',
 'Could not sign out everywhere. Nothing changed.':'Не удалось выйти на всех устройствах. Ничего не изменилось.',
 'Running':'Выполняется','Applied':'Применено','Applied, but':'Применено, но','Not applied':'Не применено',
 'Result unknown':'Результат неизвестен','Server busy':'Сервер занят','Partially':'Частично',
 'disappears in {n} s':'исчезнет через {n} с','State refreshed — check whether the change is there.':'Состояние обновлено — проверьте, применилось ли изменение.',
 'No answer from the server in {t}. The change may have applied — check before repeating.':'Сервер не ответил за {t}. Изменение могло примениться — не повторяйте вслепую.',
 'The connection dropped. The change may have applied — check before repeating.':'Связь прервалась. Изменение могло примениться — не повторяйте вслепую.',
 'Not started: another operation is running (maybe an automatic switch). Nothing changed.':'Не начато: идёт другая операция (возможно, автопереключение). Ничего не изменилось.',
 'Nothing changed.':'Ничего не изменилось.','Done.':'Готово.',
 'The server refused the request.':'Сервер отклонил запрос.','The server answered with an error.':'Сервер ответил ошибкой.',
 'Cleanup after the change did not finish.':'Уборка после изменения не завершилась.',
 'skipped':'пропущено','done':'выполнено','applied only in part:':'применилось не полностью:',
 'Exit switching is blocked.':'Переключение выходов заблокировано.'
}};
function addStrings(lang,dict){STR[lang]=Object.assign(STR[lang]||{},dict||{})}
function tr(key,vars){
 const table=STR[LANG];
 let s=table&&Object.prototype.hasOwnProperty.call(table,key)?table[key]:key;
 s=String(s);
 if(vars)s=s.replace(/\{(\w+)\}/g,(m,k)=>Object.prototype.hasOwnProperty.call(vars,k)?String(vars[k]):m);
 return s;
}
const PR={};
function pluralCategory(n){
 try{
  if(!PR[LANG])PR[LANG]=new Intl.PluralRules(LANG==='ru'?'ru-RU':'en-US');
  return PR[LANG].select(n);
 }catch(e){
  if(LANG!=='ru')return n===1?'one':'other';
  const a=Math.abs(n)%100,b=a%10;
  if(a>10&&a<20)return'many';if(b===1)return'one';if(b>=2&&b<=4)return'few';return'many';
 }
}
function plural(n,forms){
 forms=forms||{};
 if(forms[LANG]&&typeof forms[LANG]==='object')forms=forms[LANG];
 let s=forms[pluralCategory(n)];
 if(s==null)s=forms.other!=null?forms.other:forms.many!=null?forms.many:forms.one;
 return String(s==null?'':s).replace(/\{n\}/g,n);
}
const NOUNS={
 client:{ru:{one:'{n} клиент',few:'{n} клиента',many:'{n} клиентов',other:'{n} клиента'},en:{one:'{n} client',other:'{n} clients'}},
 day:{ru:{one:'{n} день',few:'{n} дня',many:'{n} дней',other:'{n} дня'},en:{one:'{n} day',other:'{n} days'}},
 hour:{ru:{one:'{n} час',few:'{n} часа',many:'{n} часов',other:'{n} часа'},en:{one:'{n} hour',other:'{n} hours'}},
 minute:{ru:{one:'{n} минуту',few:'{n} минуты',many:'{n} минут',other:'{n} минуты'},en:{one:'{n} minute',other:'{n} minutes'}},
 attempt:{ru:{one:'{n} попытка',few:'{n} попытки',many:'{n} попыток',other:'{n} попытки'},en:{one:'{n} attempt',other:'{n} attempts'}},
 exit:{ru:{one:'{n} выход',few:'{n} выхода',many:'{n} выходов',other:'{n} выхода'},en:{one:'{n} exit',other:'{n} exits'}}
};
function count(n,noun){return NOUNS[noun]?plural(n,NOUNS[noun]):n+' '+noun}
function setLang(lang){store('wgui-lang',lang==='en'?'en':'ru');try{location.reload()}catch(e){}}

/* --------------------------------------------------------------- format */
const esc=s=>String(s==null?'':s).replace(/[&<>"'`]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','`':'&#96;'}[c]));
const UNITS={ru:['Б','КиБ','МиБ','ГиБ','ТиБ'],en:['B','KiB','MiB','GiB','TiB']};
function fmtBytes(n){
 n=+n;if(!Number.isFinite(n)||n<0)n=0;
 let i=0;while(n>=1024&&i<4){n/=1024;i++}
 return(i?n.toFixed(1):String(Math.round(n)))+' '+UNITS[LANG][i];
}
function mbit(bps){
 const v=(+bps||0)*8/1e6;
 if(v<=0)return'0';
 return v<100?v.toFixed(1):String(Math.round(v));
}
function fmtMbit(bps){return mbit(bps)+' '+tr('Mbit/s')}
function fmtAgo(sec,opts){
 sec=+sec;
 if(!Number.isFinite(sec)||sec<0)return tr('never');
 sec=Math.floor(sec);
 let v;
 if(sec<60)v=sec+' '+tr('s');
 else if(sec<3600)v=Math.floor(sec/60)+' '+tr('min');
 else if(sec<86400)v=Math.floor(sec/3600)+' '+tr('h');
 else v=count(Math.floor(sec/86400),'day');
 return opts&&opts.suffix===false?v:v+' '+tr('ago');
}
const MONTHS={ru:['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек'],
 en:['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']};
function fmtDate(ts){
 const d=new Date((+ts||0)*1000),m=MONTHS[LANG][d.getMonth()];
 const y=d.getFullYear()!==new Date().getFullYear()?' '+d.getFullYear():'';
 return LANG==='ru'?d.getDate()+' '+m+y:m+' '+d.getDate()+(y?','+y:'');
}
const pad=n=>(n<10?'0':'')+n;
function fmtTime(ts,seconds){
 const d=new Date((+ts||0)*1000);
 return pad(d.getHours())+':'+pad(d.getMinutes())+(seconds?':'+pad(d.getSeconds()):'');
}
function fmtClock(sec){
 sec=Math.max(0,Math.floor(+sec||0));
 const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=sec%60;
 return h?h+':'+pad(m)+':'+pad(s):m+':'+pad(s);
}

/* ------------------------------------------------------------ server codes */
const POLICY_TEXT={
 en:{invalid_target:'The requested exit is invalid.',target_unhealthy:'The target exit is unavailable.',
  target_stale:'The target exit health check is stale.',target_exhausted:'The target exit quota is exhausted.',
  both_exhausted:'Both exit quotas are exhausted.',both_unhealthy:'Both exits are failing health checks.',
  failover_cooldown:'A switch ran recently; waiting before switching again.',
  counter_unavailable:'Current and target exit counter data is unavailable.',helper_failed:'Routing could not be applied.',
  missing_policy:'Exit settings have not been saved yet.',invalid_policy:'Exit settings are damaged.',
  no_clients_to_switch:'All clients already use this exit.'},
 ru:{invalid_target:'Недопустимый выход.',target_unhealthy:'Целевой выход недоступен.',
  target_stale:'Проверка целевого выхода устарела.',target_exhausted:'Квота целевого выхода исчерпана.',
  both_exhausted:'Квоты обоих выходов исчерпаны.',both_unhealthy:'Оба выхода не проходят проверки.',
  failover_cooldown:'Переключение было недавно — ждём перед следующим.',
  counter_unavailable:'Нет данных счётчиков текущего и целевого выходов.',helper_failed:'Не удалось применить маршрутизацию.',
  missing_policy:'Настройки выходов ещё не сохранены.',invalid_policy:'Файл настроек выходов повреждён.',
  no_clients_to_switch:'Все клиенты уже на этом выходе.'}
};
/* add/setexit: the server refuses a confirmed-down or exhausted target (409 + code)
   and only warns (ok + warning) when the target's health is not verified yet. */
const TARGET_TEXT={
 en:{target_unhealthy:'The target exit is down: it failed several health checks in a row.',
  target_exhausted:'The target exit monthly quota is exhausted.',
  target_stale:'The exit health is not verified yet — check that the client connects.',
  target_unverified:'The last health check of this exit failed — check that the client connects.'},
 ru:{target_unhealthy:'Выход недоступен: несколько проверок подряд не прошли.',
  target_exhausted:'Месячная квота этого выхода исчерпана.',
  target_stale:'Состояние выхода ещё не проверено — убедитесь, что клиент подключается.',
  target_unverified:'Последняя проверка выхода не прошла — убедитесь, что клиент подключается.'}
};
function targetText(code){return(TARGET_TEXT[LANG][code])||''}
/* Never shows a raw server identifier: unknown codes get the generic sentence. */
function reasonText(code){
 code=String(code==null?'':code);
 return POLICY_TEXT[LANG][code]||targetText(code)||tr('Exit switching is blocked.');
}

/* ------------------------------------------------------------ events */
const LISTENERS={};
function on(evt,fn){
 (LISTENERS[evt]||(LISTENERS[evt]=[])).push(fn);
 return()=>{const l=LISTENERS[evt]||[],i=l.indexOf(fn);if(i>=0)l.splice(i,1)};
}
function emit(evt,data){
 (LISTENERS[evt]||[]).slice().forEach(fn=>{try{fn(data)}catch(e){if(root.console)console.error(e)}});
}
const ACTS={};
function delegate(name,fn){ACTS[name]=fn}
doc.addEventListener('click',e=>{
 const el=e.target&&e.target.closest&&e.target.closest('[data-act]');
 if(!el||el.disabled||el.getAttribute('aria-disabled')==='true')return;
 const fn=ACTS[el.getAttribute('data-act')];
 if(fn)fn(el,e);
});

/* ------------------------------------------------------------ network */
const GET_DEADLINE_MS=12000;  /* a stuck GET must not stall polling */
const TICK_MS=5000,TICK_HIDDEN_MS=15000,TICK_MAX_BACKOFF_MS=60000;
/* Browser deadline per admin op: always above the server's own budget for that op,
   so the server's answer (success, rollback or "busy") arrives before we give up. */
const ADMIN_TIMEOUT_MS={add:210000,rename:160000,enabled:160000,delete:160000,setexit:160000,
 setexpiry:160000,setexitall:100000,revertswitch:100000,setexitpolicy:100000,splitsave:195000,splitserver:195000,export:60000};
const ADMIN_DEFAULT_TIMEOUT_MS=60000;
function csrf(){const m=doc.querySelector('meta[name=csrf]');return m?m.content:''}
/* fetch with a hard deadline; read(response) runs inside it too. Returns {promise, abort}:
   abort() rejects with AbortError, the deadline with TimeoutError. */
function timedFetch(url,opts,ms,read){
 const ac=typeof AbortController!=='undefined'?new AbortController():null;
 const o=Object.assign({},opts||{});if(ac)o.signal=ac.signal;
 let timer=null,settled=false,rejectFn=null;
 const fail=name=>{
  if(settled)return;settled=true;clearTimeout(timer);
  if(ac){try{ac.abort()}catch(e){}}
  const err=new Error(name==='TimeoutError'?'timeout':'aborted');err.name=name;rejectFn(err);
 };
 const promise=new Promise((resolve,reject)=>{
  rejectFn=reject;
  timer=setTimeout(()=>fail('TimeoutError'),ms);
  let f;try{f=fetch(url,o)}catch(e){settled=true;clearTimeout(timer);reject(e);return}
  Promise.resolve(f).then(r=>read?read(r):r).then(
   v=>{if(settled)return;settled=true;clearTimeout(timer);resolve(v)},
   e=>{if(settled)return;settled=true;clearTimeout(timer);reject(e)});
 });
 return{promise,abort:()=>fail('AbortError')};
}
const respOk=r=>typeof r.ok==='boolean'?r.ok:(r.status>=200&&r.status<300);
let _leaving=false;
function toLogin(){if(_leaving)return;_leaving=true;try{location.href='/login'}catch(e){}}
function apiRequest(path,opts){
 return timedFetch(path,{cache:'no-store'},(opts&&opts.timeout)||GET_DEADLINE_MS,r=>{
  if(r.status===401){toLogin();throw new Error(tr('Session expired — sign in again'))}
  if(!respOk(r)){const e=new Error('HTTP '+r.status);e.status=r.status;throw e}
  return r.json();
 });
}
function api(path,opts){return apiRequest(path,opts).promise}

function adminTimeout(op){
 return Object.prototype.hasOwnProperty.call(ADMIN_TIMEOUT_MS,op)?ADMIN_TIMEOUT_MS[op]:ADMIN_DEFAULT_TIMEOUT_MS;
}
function outcome(kind,data,message,extra){return Object.assign({kind,data:data||null,message:message||''},extra||{})}
function failMessage(data){
 const code=data&&(data.code||data.error);
 if(code&&(TARGET_TEXT[LANG][code]||POLICY_TEXT[LANG][code]))return targetText(code)||reasonText(code);
 return tr('The server refused the request.')+' '+tr('Nothing changed.');
}
/* POST /api/admin and fold every answer into one of six outcomes (D1). A missing
   answer is never "failed": the helper may still have committed. */
async function admin(body){
 const op=body&&body.op,ms=adminTimeout(op);
 let r;
 try{
  r=await timedFetch('/api/admin',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF':csrf()},
   body:JSON.stringify(body),cache:'no-store'},ms).promise;
 }catch(e){
  if(e&&e.name==='TimeoutError')
   return outcome('unknown',null,tr('No answer from the server in {t}. The change may have applied — check before repeating.',{t:fmtClock(ms/1000)}));
  return outcome('unknown',null,tr('The connection dropped. The change may have applied — check before repeating.'));
 }
 if(r.status===401){toLogin();return outcome('failed',null,tr('Session expired — sign in again'))}
 let data=null;
 try{data=await r.json()}catch(e){data=null}
 if(!data||typeof data!=='object')
  return respOk(r)?outcome('unknown',null,tr('The connection dropped. The change may have applied — check before repeating.'))
   :outcome('failed',null,tr('The server answered with an error.')+' '+tr('Nothing changed.'));
 if(data.busy===true||data.error==='busy')
  return outcome('busy',data,tr('Not started: another operation is running (maybe an automatic switch). Nothing changed.'));
 if(data.committed==='unknown'||data.error==='timeout')
  return outcome('unknown',data,tr('No answer from the server in {t}. The change may have applied — check before repeating.',{t:fmtClock(ms/1000)}));
 if(data.ok===true&&respOk(r)){
  if(Array.isArray(data.skipped)&&data.skipped.length){
   const steps=(data.changed||[]).map(x=>({state:'ok',text:typeof x==='string'?x:(x&&x.name)||''}))
    .concat(data.skipped.map(x=>({state:'failed',text:((x&&x.name)||'')+(x&&x.reason?': '+reasonText(x.reason):'')})));
   return outcome('partial',data,'',{steps});
  }
  if(data.warning)return outcome('warn',data,targetText(data.warning)||reasonText(data.warning));
  if(data.cleanup_warning)return outcome('warn',data,tr('Cleanup after the change did not finish.'));
  return outcome('ok',data,'');
 }
 return outcome('failed',data,failMessage(data));
}

/* ------------------------------------------------------------ polling */
WG.state={loaded:false,peers:[],fetchedAt:0,dataAt:0,offline:false,stale:false,timedOut:false,fails:0,retryAt:0};
let _tickBusy=false,_tickAbort=null,_tickTimer=null,_tickSeq=0,_tickFails=0,_planned=null;
async function tick(){
 if(_tickBusy)return;
 if(doc.hidden)return;          /* hidden tab: no fetch, no DOM work; refreshed on return */
 _tickBusy=true;
 const seq=++_tickSeq;
 const req=timedFetch('/api/status',{cache:'no-store'},GET_DEADLINE_MS,async r=>{
  if(r.status===401||!respOk(r))return{r,d:null};
  return{r,d:await r.json()};
 });
 _tickAbort=req;
 try{
  const res=await req.promise;
  if(seq!==_tickSeq)return;
  if(res.r.status===401){toLogin();return}
  if(!respOk(res.r)||!res.d||typeof res.d!=='object')throw new Error('status '+res.r.status);
  const d=res.d;
  _tickFails=0;
  WG.state=Object.assign({},d,{loaded:true,peers:Array.isArray(d.peers)?d.peers:[],fetchedAt:Date.now(),
   dataAt:(+d.now||0)-(+d.snapshot_age||0),offline:false,stale:d.stale===true,timedOut:false,fails:0,retryAt:0});
  publish();
 }catch(e){
  if(e&&e.name==='AbortError')return;
  if(seq!==_tickSeq)return;
  _tickFails++;
  _planned=nextTickDelay();
  WG.state=Object.assign({},WG.state,{offline:true,timedOut:!!(e&&e.name==='TimeoutError'),fails:_tickFails,retryAt:Date.now()+_planned});
  publish();
 }finally{
  if(_tickAbort===req)_tickAbort=null;
  if(seq===_tickSeq)_tickBusy=false;
 }
}
function publish(){
 emit('status',WG.state);
 applyLiveLock();
 renderAge();
}
/* 5 s while healthy; exponential backoff with ±20% jitter after failures, capped at 60 s. */
function nextTickDelay(){
 if(doc.hidden)return TICK_HIDDEN_MS;
 if(!_tickFails)return TICK_MS;
 const base=Math.min(TICK_MAX_BACKOFF_MS,TICK_MS*Math.pow(2,_tickFails-1));
 return Math.round(base*(0.8+Math.random()*0.4));
}
function scheduleTick(ms){
 if(_tickTimer)clearTimeout(_tickTimer);
 WG.state.retryAt=Date.now()+ms;
 _tickTimer=setTimeout(async()=>{
  _tickTimer=null;
  try{await tick()}finally{const d=_planned!=null?_planned:nextTickDelay();_planned=null;scheduleTick(d)}
 },ms);
}
/* Network back / tab visible / «Повторить сейчас»: drop a stuck request, reset backoff, poll now. */
function kickTick(){
 _tickFails=0;_planned=null;
 if(_tickAbort){try{_tickAbort.abort()}catch(e){}}
 scheduleTick(0);
}
function unknown(){return !WG.state.loaded||WG.state.offline||WG.state.stale}
function dataAge(){
 const s=WG.state;
 if(!s.loaded)return -1;
 return Math.max(0,(+s.snapshot_age||0)+Math.round((Date.now()-s.fetchedAt)/1000));
}
/* Buttons marked data-live talk to the server: off while there is no connection. */
function applyLiveLock(){
 const b=doc.body;if(!b)return;
 const off=WG.state.offline;
 b.classList.toggle('is-offline',!!off);
 b.classList.toggle('is-stale',!off&&!!WG.state.stale);
 (b.querySelectorAll?b.querySelectorAll('[data-live]'):[]).forEach(el=>{el.disabled=!!off});
}
function renderAge(){
 const el=$('age');if(!el)return;
 const s=WG.state;
 if(!s.loaded){el.textContent='';return}
 const age=dataAge(),old=s.offline||s.stale;
 el.classList.toggle('is-old',!!old);
 el.innerHTML='<span class="age-l">'+esc(tr('data'))+' '+esc(fmtTime(s.dataAt,!old))+' · </span>'
  +'<span class="age-v">'+esc(fmtAgo(age,{suffix:old}))+'</span>';
}

/* ------------------------------------------------------------ helpers */
const EXITS=['nl','us'];
function exitCity(key){return tr(key==='us'?'New York':'Amsterdam')}
function peer(pubkey){return(WG.state.peers||[]).find(p=>p&&p.pubkey===pubkey)||null}
function icon(name,size){return root.WGIcons?root.WGIcons.icon(name,size):''}

/* ------------------------------------------------------------ focus */
const FOCUSABLE='a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
function focusables(rootEl){
 return [...rootEl.querySelectorAll(FOCUSABLE)].filter(el=>el.offsetParent!==null||el===doc.activeElement);
}
function trapTab(rootEl,e){
 const f=focusables(rootEl);if(!f.length){e.preventDefault();return}
 const first=f[0],last=f[f.length-1],a=doc.activeElement;
 if(e.shiftKey&&(a===first||!rootEl.contains(a))){e.preventDefault();last.focus()}
 else if(!e.shiftKey&&(a===last||!rootEl.contains(a))){e.preventDefault();first.focus()}
}
function put(el,content){
 if(content==null)return;
 if(typeof content==='string')el.innerHTML=content;else el.appendChild(content);
}

/* ------------------------------------------------------------ modal */
let _modal=null;
function modalOpen(o){
 o=o||{};
 const returnTo=_modal?_modal._returnTo:doc.activeElement;
 if(_modal)_modal._dispose('replaced',false);
 const layer=$('layer')||doc.body;
 const wrap=doc.createElement('div');
 wrap.className='dlg-wrap';
 const size=o.size==='sm'||o.size==='lg'?o.size:'md';
 wrap.innerHTML='<div class="scrim" data-act="modal-close"></div>'
  +'<div class="dlg dlg-'+size+'" role="dialog" aria-modal="true" aria-labelledby="dlg-t" tabindex="-1">'
  +'<div class="dlg-grip" aria-hidden="true"></div>'
  +'<header class="dlg-h"><div class="dlg-ht">'+(o.eyebrow?'<div class="eyebrow">'+esc(o.eyebrow)+'</div>':'')
  +'<h2 class="dlg-title" id="dlg-t">'+esc(o.title||'')+'</h2></div>'
  +'<button class="ibtn dlg-x" type="button" data-act="modal-close" aria-label="'+esc(tr('Close'))+'">'+icon('x',16)+'</button></header>'
  +'<div class="dlg-b"></div><footer class="dlg-f"></footer></div>';
 layer.appendChild(wrap);
 const el=wrap.querySelector('.dlg'),body=wrap.querySelector('.dlg-b'),footer=wrap.querySelector('.dlg-f');
 put(body,o.body);
 if(o.footer==null||o.footer==='')footer.hidden=true;else put(footer,o.footer);
 const reqs=[];
 const h={el,body,footer,_wrap:wrap,_returnTo:returnTo,_closed:false,
  alive(){return !h._closed&&_modal===h},
  close(){if(_modal===h)modalClose()},
  api(path,opts){
   const req=apiRequest(path,opts);reqs.push(req);
   const done=()=>{const i=reqs.indexOf(req);if(i>=0)reqs.splice(i,1)};
   req.promise.then(done,done);
   return req.promise;
  },
  _dispose(reason,restore){
   if(h._closed)return;h._closed=true;
   reqs.splice(0).forEach(r=>{try{r.abort()}catch(e){}});
   wrap.remove();
   if(_modal===h)_modal=null;
   if(!_modal&&doc.body)doc.body.classList.remove('has-modal');
   if(typeof o.onClose==='function'){try{o.onClose(reason)}catch(e){}}
   if(restore&&returnTo&&returnTo.focus&&returnTo.isConnected!==false){try{returnTo.focus()}catch(e){}}
  }
 };
 _modal=h;
 if(doc.body)doc.body.classList.add('has-modal');
 setTimeout(()=>{
  if(!h.alive())return;
  const auto=el.querySelector('[autofocus]');
  const target=auto||focusables(body)[0]||focusables(el)[0]||el;
  try{target.focus()}catch(e){}
 },0);
 return h;
}
function modalClose(reason){if(_modal)_modal._dispose(reason||'close',true)}
delegate('modal-close',()=>modalClose('close'));

function confirmBox(o){
 o=o||{};
 return new Promise(resolve=>{
  let answered=false;
  const finish=v=>{if(answered)return;answered=true;resolve(v)};
  const need=o.typeToConfirm?String(o.typeToConfirm):'';
  const body=(o.body?'<div class="prose">'+o.body+'</div>':'')
   +(need?'<label class="field"><span class="field-l">'+esc(tr('Type «{text}» to confirm',{text:need}))+'</span>'
    +'<input class="input" type="text" autocomplete="off" spellcheck="false" data-confirm-input autofocus></label>':'');
  const footer='<button class="btn" type="button" data-act="modal-close">'+esc(tr('Cancel'))+'</button>'
   +'<button class="btn '+(o.danger?'btn-danger':'btn-primary')+'" type="button" data-confirm-ok'+(need?' disabled':'')+'>'
   +esc(o.confirmLabel||tr('Confirm'))+'</button>';
  const h=modalOpen({title:o.title,eyebrow:o.eyebrow,body,footer,size:'sm',onClose:()=>finish(false)});
  const ok=h.el.querySelector('[data-confirm-ok]'),input=h.el.querySelector('[data-confirm-input]');
  if(input)input.addEventListener('input',()=>{ok.disabled=input.value.trim()!==need});
  ok.addEventListener('click',()=>{if(ok.disabled)return;finish(true);h.close()});
 });
}

/* ------------------------------------------------------------ menu */
let _menu=null;
function menuClose(restore){
 const m=_menu;if(!m)return;_menu=null;
 m.wrap.remove();
 if(m.anchor&&m.anchor.setAttribute)m.anchor.setAttribute('aria-expanded','false');
 if(restore!==false&&m.anchor&&m.anchor.focus){try{m.anchor.focus()}catch(e){}}
}
function isNarrow(){try{return !!(root.matchMedia&&root.matchMedia('(max-width: 600px)').matches)}catch(e){return false}}
function menuOpen(anchor,items,opts){
 opts=opts||{};
 const reopen=_menu&&_menu.anchor===anchor;
 menuClose(false);
 if(reopen&&!opts.force)return null;
 const sheet=!!opts.sheet||isNarrow();
 const wrap=doc.createElement('div');
 wrap.className='menu-wrap'+(sheet?' is-sheet':'');
 let html=sheet?'<div class="scrim" data-act="menu-close"></div>':'';
 html+='<div class="menu" role="menu" tabindex="-1"'+(opts.title?' aria-label="'+esc(opts.title)+'"':'')+'>';
 if(sheet)html+='<div class="dlg-grip" aria-hidden="true"></div>';
 if(opts.title)html+='<div class="menu-h">'+esc(opts.title)+'</div>';
 (items||[]).forEach((it,i)=>{
  if(!it)return;
  if(it.type==='sep'){html+='<div class="menu-sep" role="separator"></div>';return}
  if(it.type==='segment'){
   html+='<div class="mi mi-seg" role="group" aria-label="'+esc(it.label)+'"><span class="mi-ic">'+icon(it.icon,sheet?20:16)+'</span>'
    +'<span class="mi-l">'+esc(it.label)+'</span><span class="seg seg-sm">'
    +(it.options||[]).map(op=>'<button type="button" role="menuitemradio" class="seg-b" aria-checked="'+(op.value===it.value)+'" data-mi="'+i+'" data-v="'+esc(op.value)+'">'+esc(op.label)+'</button>').join('')
    +'</span></div>';
   return;
  }
  html+='<button type="button" role="menuitem" class="mi'+(it.danger?' is-danger':'')+'" data-mi="'+i+'"'+(it.disabled?' disabled':'')+'>'
   +'<span class="mi-ic">'+icon(it.icon,sheet?20:16)+'</span><span class="mi-l">'+esc(it.label)+'</span>'
   +((it.hint||it.key)?'<span class="mi-h'+(it.hintTone?' is-'+it.hintTone:'')+'">'+esc(it.hint||String(it.key).toUpperCase())+'</span>':'')
   +'</button>';
 });
 html+='</div>';
 wrap.innerHTML=html;
 ($('layer')||doc.body).appendChild(wrap);
 const menu=wrap.querySelector('.menu');
 if(!sheet)place(menu,anchor);
 if(anchor&&anchor.setAttribute)anchor.setAttribute('aria-expanded','true');
 _menu={wrap,menu,anchor,items:items||[]};
 menu.addEventListener('click',e=>{
  const b=e.target&&e.target.closest&&e.target.closest('[data-mi]');
  if(!b||b.disabled)return;
  const it=_menu&&_menu.items[+b.getAttribute('data-mi')];if(!it)return;
  if(it.type==='segment'){
   const v=b.getAttribute('data-v');
   menu.querySelectorAll('[data-mi="'+b.getAttribute('data-mi')+'"]').forEach(x=>x.setAttribute('aria-checked',String(x===b)));
   if(typeof it.onChange==='function')it.onChange(v);
   return;
  }
  menuClose();
  if(typeof it.act==='function')it.act();
 });
 setTimeout(()=>{const f=menuItems()[0];if(f)f.focus();else menu.focus()},0);
 return menu;
}
function menuItems(){return _menu?[..._menu.menu.querySelectorAll('[data-mi]')].filter(b=>!b.disabled):[]}
function place(menu,anchor){
 if(!anchor||!anchor.getBoundingClientRect||!menu.style)return;
 const r=anchor.getBoundingClientRect(),vw=root.innerWidth||1024,vh=root.innerHeight||768;
 menu.style.position='fixed';
 const w=menu.offsetWidth||280,hgt=menu.offsetHeight||240;
 let left=Math.min(Math.max(8,r.right-w),vw-w-8);
 let top=r.bottom+6;
 if(top+hgt>vh-8&&r.top-hgt-6>8)top=r.top-hgt-6;
 menu.style.left=Math.round(left)+'px';menu.style.top=Math.round(top)+'px';
}
delegate('menu-close',()=>menuClose());
doc.addEventListener('mousedown',e=>{
 if(!_menu)return;
 const t=e.target;
 if(_menu.menu.contains(t)||(_menu.anchor&&_menu.anchor.contains&&_menu.anchor.contains(t)))return;
 if(t&&t.getAttribute&&t.getAttribute('data-act')==='menu-close')return;
 menuClose(false);
});

/* ------------------------------------------------------------ keyboard */
doc.addEventListener('keydown',e=>{
 if(_menu){
  const list=menuItems(),i=list.indexOf(doc.activeElement);
  if(e.key==='Escape'){e.preventDefault();menuClose();return}
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){
   e.preventDefault();if(!list.length)return;
   const n=e.key==='ArrowDown'?(i+1)%list.length:(i<=0?list.length-1:i-1);list[n].focus();return;
  }
  if(e.key==='Home'||e.key==='End'){e.preventDefault();const n=e.key==='Home'?list[0]:list[list.length-1];if(n)n.focus();return}
  if(e.key==='Tab'){menuClose(false);return}
  if(e.key&&e.key.length===1&&!e.metaKey&&!e.ctrlKey&&!e.altKey){
   const k=e.key.toLowerCase(),idx=_menu.items.findIndex(it=>it&&it.key&&String(it.key).toLowerCase()===k&&!it.disabled);
   if(idx>=0){e.preventDefault();const it=_menu.items[idx];menuClose();if(typeof it.act==='function')it.act()}
  }
  return;
 }
 if(_modal){
  if(e.key==='Escape'){e.preventDefault();modalClose('esc');return}
  if(e.key==='Tab')trapTab(_modal.el,e);
 }
});

/* ------------------------------------------------------------ banners */
const LEVEL_RANK={crash:0,stale:1,offline:1,failover:2,quota:3,info:4};
const BANNERS=new Map();
let _bannerSig='',_bannerOpen=false;
function hiddenBanners(){try{return JSON.parse(store('wgui-banner-hidden')||'[]')||[]}catch(e){return[]}}
function bannerSet(id,spec,quiet){BANNERS.set(id,Object.assign({id},spec));if(!quiet)renderBanners()}
function bannerClear(id,quiet){if(BANNERS.delete(id)&&!quiet)renderBanners()}
function visibleBanners(){
 const hidden=hiddenBanners();
 return [...BANNERS.values()].filter(b=>!(b.dismiss&&hidden.indexOf(b.dismiss)>=0))
  .sort((a,b)=>(LEVEL_RANK[a.level]??9)-(LEVEL_RANK[b.level]??9));
}
function bannerHTML(b,i,compact){
 const acts=(b.actions||[]).map((a,j)=>'<button type="button" class="btn btn-sm '+(a.primary?'btn-primary':'btn-outline')+'" data-act="banner-act" data-b="'+esc(b.id)+'" data-j="'+j+'"'
  +(a.live||a.primary?' data-live':'')+(a.disabled||((a.live||a.primary)&&WG.state.offline)?' disabled':'')+'>'+esc(a.label)+'</button>').join('')
  +(b.dismiss?'<button type="button" class="btn btn-sm btn-text" data-act="banner-hide" data-b="'+esc(b.id)+'">'+esc(tr('Hide'))+'</button>':'');
 return '<section class="bn bn-'+esc(b.level)+(compact?' is-compact':'')+'" role="'+(b.level==='crash'?'alert':'status')+'" data-b="'+esc(b.id)+'">'
  +'<div class="bn-top"><span class="bn-tag">'+(b.icon?icon(b.icon,14):'')+'<span>'+esc(b.tag||'')+'</span></span>'
  +(b.note?'<span class="bn-note"'+(b.countdownTo?' data-countdown="'+(+b.countdownTo)+'" data-tpl="'+esc(b.note)+'"':'')+'>'
   +esc(b.countdownTo?countdownText(b.note,b.countdownTo):b.note)+'</span>':'')+'</div>'
  +'<p class="bn-text">'+esc(b.text||'')+'</p>'
  +(acts?'<div class="bn-acts">'+acts+'</div>':'')+'</section>';
}
/* '{n}' in a banner note counts down to spec.countdownTo (ms) without re-rendering the banner. */
function countdownText(tpl,to){return String(tpl).replace('{n}',Math.max(0,Math.ceil((to-Date.now())/1000)))}
function renderCountdowns(){
 (doc.querySelectorAll?doc.querySelectorAll('[data-countdown]'):[]).forEach(el=>{
  el.textContent=countdownText(el.getAttribute('data-tpl'),+el.getAttribute('data-countdown'));
 });
}
function renderBanners(){
 const el=$('banner');if(!el)return;
 const list=visibleBanners();
 const sig=JSON.stringify([_bannerOpen,WG.state.offline,list.map(b=>[b.id,b.level,b.tag,b.note,b.text,(b.actions||[]).map(a=>a.label+(a.disabled?'!':''))])]);
 if(sig===_bannerSig)return;
 _bannerSig=sig;
 if(!list.length){el.innerHTML='';el.hidden=true;return}
 el.hidden=false;
 let html=bannerHTML(list[0],0,false);
 if(list.length>1){
  if(_bannerOpen)html+=list.slice(1).map((b,i)=>bannerHTML(b,i+1,true)).join('');
  html+='<button type="button" class="bn-more" data-act="banner-more" aria-expanded="'+_bannerOpen+'">'
   +esc(_bannerOpen?tr('Show less'):tr('and {n} more',{n:list.length-1}))+'</button>';
 }
 el.innerHTML=html;
}
delegate('banner-more',()=>{_bannerOpen=!_bannerOpen;renderBanners()});
delegate('banner-hide',el=>{
 const b=BANNERS.get(el.getAttribute('data-b'));if(!b||!b.dismiss)return;
 const h=hiddenBanners().filter(x=>x!==b.dismiss);h.push(b.dismiss);
 store('wgui-banner-hidden',JSON.stringify(h.slice(-20)));
 renderBanners();
});
delegate('banner-act',el=>{
 const b=BANNERS.get(el.getAttribute('data-b')),a=b&&(b.actions||[])[+el.getAttribute('data-j')];
 if(a&&typeof a.act==='function')a.act();
});

/* ------------------------------------------------------------ operations strip (D1) */
const OPS=new Map();            /* key → running entry */
const RESULTS=[];               /* outcomes waiting for «Понятно» (ok ones fade by themselves) */
let _opsTimer=null,_opSeq=0;
const OP_TAG={ok:'Applied',warn:'Applied, but',failed:'Not applied',unknown:'Result unknown',busy:'Server busy',partial:'Partially'};
const OP_IC={ok:'✓',warn:'✓!',failed:'×',unknown:'?',busy:'…',partial:'½'};
const OP_OK_MS=5000,OP_UNDO_MS=10000;
function asOutcome(v){
 if(v&&typeof v==='object'&&OP_TAG[v.kind])return v;
 if(v&&typeof v==='object'&&v.ok===true)return outcome('ok',v,'');
 return outcome('failed',v&&typeof v==='object'?v:null,tr('The server answered with an error.')+' '+tr('Nothing changed.'));
}
function opsRun(o){
 o=o||{};
 const key=String(o.key||o.label||'op');
 const running=OPS.get(key);
 if(running)return running.promise;
 for(let i=RESULTS.length-1;i>=0;i--)if(RESULTS[i].key===key)dropResult(RESULTS[i]);
 const entry={key,label:String(o.label||''),start:Date.now()};
 OPS.set(key,entry);
 entry.promise=(async()=>{
  let out;
  try{out=asOutcome(await(typeof o.call==='function'?o.call():o.call))}
  catch(e){out=outcome('unknown',null,tr('The connection dropped. The change may have applied — check before repeating.'))}
  OPS.delete(key);
  addResult(o,key,out);
  if(out.kind!=='busy')kickTick();     /* refresh in the background — never awaited */
  return out;
 })();
 renderOps();
 return entry.promise;
}
function addResult(o,key,out){
 const ttl=out.kind==='ok'?(typeof o.undo==='function'?OP_UNDO_MS:OP_OK_MS):0;
 RESULTS.push({id:++_opSeq,key,opts:o,kind:out.kind,out,until:ttl?Date.now()+ttl:0,checked:false,el:null});
 renderOps();
}
function dropResult(r){
 const i=RESULTS.indexOf(r);if(i>=0)RESULTS.splice(i,1);
 if(r.el)r.el.remove();
}
function opMessage(r){
 const o=r.opts,out=r.out,label=String(o.label||'');
 if(r.kind==='ok')return String(o.done||label);
 if(r.kind==='warn')return String(o.done||label)+(out.message?' — '+out.message:'');
 if(r.kind==='partial')return(label?label+' — ':'')+tr('applied only in part:');
 return(label?label+': ':'')+(out.message||'');
}
function resultHTML(r){
 const steps=r.kind==='partial'&&r.out.steps&&r.out.steps.length?'<ul class="op-steps">'+r.out.steps.map(s=>{
  const st=s.state==='ok'?'ok':s.state==='failed'?'failed':'skipped';
  return'<li class="is-'+st+'">'+(st==='ok'?'✓ ':st==='failed'?'× ':'— ')+esc(s.text)+'</li>';
 }).join('')+'</ul>':'';
 let acts='';
 if(r.kind==='ok'){
  if(typeof r.opts.undo==='function')acts+='<button type="button" class="btn btn-sm btn-outline" data-act="op-undo" data-live>'+esc(tr('Undo'))+'</button>';
  acts+='<span class="op-note" data-op-ttl>'+esc(tr('disappears in {n} s',{n:Math.max(0,Math.ceil((r.until-Date.now())/1000))}))+'</span>';
 }else{
  if(r.kind==='unknown')acts+='<button type="button" class="btn btn-sm btn-primary" data-act="op-check">'+esc(tr('Check state'))+'</button>';
  if(r.kind==='busy')acts+='<button type="button" class="btn btn-sm btn-outline" data-act="op-retry" data-live>'+esc(tr('Retry'))+'</button>';
  if(r.opts.open&&r.opts.open.label)acts+='<button type="button" class="btn btn-sm btn-outline" data-act="op-open">'+esc(r.opts.open.label)+'</button>';
  acts+='<button type="button" class="btn btn-sm btn-text" data-act="op-dismiss">'+esc(tr('Got it'))+'</button>';
 }
 return'<span class="op-ic" aria-hidden="true">'+OP_IC[r.kind]+'</span><span class="op-tag">'+esc(tr(OP_TAG[r.kind]))+'</span>'
  +'<div class="op-msg">'+esc(opMessage(r))+steps
  +(r.checked?'<div class="op-sub">'+esc(tr('State refreshed — check whether the change is there.'))+'</div>':'')+'</div>'
  +'<div class="op-acts">'+acts+'</div>';
}
function runHTML(){
 const list=[...OPS.values()];
 return'<span class="op-bar" aria-hidden="true"></span><span class="op-tag">'+esc(tr('Running'))+' · '+list.length+'</span>'
  +'<div class="op-msg">'+list.map(e=>esc(e.label)+' · <span class="op-time">'+fmtClock((Date.now()-e.start)/1000)+'</span>').join(' · ')+'</div>';
}
function renderOps(){
 const box=$('ops');
 if(box){
  let run=box.querySelector('.op-run');
  if(OPS.size){
   if(!run){
    run=doc.createElement('div');run.className='op op-run';run.setAttribute('aria-live','off');
    box.insertBefore(run,box.firstChild);
   }
   run.innerHTML=runHTML();
  }else if(run)run.remove();
  RESULTS.forEach(r=>{
   if(r.el&&r.el.isConnected!==false&&!r.dirty)return;
   const fresh=!r.el;
   if(fresh){
    r.el=doc.createElement('div');
    r.el.setAttribute('data-op',String(r.id));
    if(r.kind==='failed'||r.kind==='unknown'||r.kind==='partial')r.el.setAttribute('role','alert');
   }
   r.el.className='op op-'+r.kind;
   r.el.innerHTML=resultHTML(r);r.dirty=false;
   if(fresh)box.appendChild(r.el);
  });
 }
 if(!_opsTimer&&(OPS.size||RESULTS.some(r=>r.until)))_opsTimer=setTimeout(opsTick,1000);
}
function opsTick(){
 _opsTimer=null;
 const t=Date.now();
 RESULTS.filter(r=>r.until&&r.until<=t).forEach(dropResult);
 RESULTS.forEach(r=>{
  if(!r.until||!r.el)return;
  const n=r.el.querySelector('[data-op-ttl]');
  if(n)n.textContent=tr('disappears in {n} s',{n:Math.max(0,Math.ceil((r.until-t)/1000))});
 });
 renderOps();
}
function resultOf(el){const box=el.closest('[data-op]'),id=box&&+box.getAttribute('data-op');return RESULTS.find(r=>r.id===id)||null}
delegate('op-dismiss',el=>{const r=resultOf(el);if(r)dropResult(r)});
delegate('op-retry',el=>{const r=resultOf(el);if(r){dropResult(r);opsRun(r.opts)}});
delegate('op-open',el=>{const r=resultOf(el);if(r&&typeof r.opts.open.act==='function')r.opts.open.act()});
delegate('op-undo',el=>{const r=resultOf(el);if(r){dropResult(r);r.opts.undo()}});
delegate('op-check',el=>{
 const r=resultOf(el);if(!r)return;
 if(typeof r.opts.check==='function'){try{r.opts.check()}catch(e){}}
 kickTick();
 r.checked=true;r.dirty=true;renderOps();
});

/* ------------------------------------------------------------ theme */
const THEMES=['light','dark','auto'];
function themeGet(){const t=store('wgui-theme');return THEMES.indexOf(t)>=0?t:'light'}
function themeSet(mode){
 if(THEMES.indexOf(mode)<0)mode='light';
 store('wgui-theme',mode);
 const html=doc.documentElement;
 if(html.setAttribute)html.setAttribute('data-theme',mode);
 let dark=mode==='dark';
 if(mode==='auto'){try{dark=!!(root.matchMedia&&root.matchMedia('(prefers-color-scheme: dark)').matches)}catch(e){}}
 (doc.querySelectorAll?doc.querySelectorAll('meta[name=theme-color]'):[]).forEach(m=>{m.content=dark?'#121210':'#FFFFFF'});
}

/* ------------------------------------------------------------ router + shell */
const ROUTES=new Map();
let _route=null,_routeCtx=null,_started=false;
function routeFromHash(){
 const m=/^#\/([a-z-]+)/.exec((root.location&&location.hash)||'');
 const name=m&&m[1];
 return name&&ROUTES.has(name)?name:(ROUTES.has('clients')?'clients':[...ROUTES.keys()][0]);
}
function register(name,def){
 ROUTES.set(name,Object.assign({name},def||{}));
 if(!_started)return;
 renderNav();
 if(_route===name)renderRoute(true);
 else if(routeFromHash()===name&&_route!==name)renderRoute();
}
function go(name){
 if(!ROUTES.has(name))return;
 if(_route===name)return renderRoute(true);
 try{location.hash='#/'+name}catch(e){}
 if(!root.location||location.hash!=='#/'+name)renderRoute();
}
function renderRoute(force){
 const name=routeFromHash();
 if(!name||(_route===name&&!force))return;
 const prev=_route;
 if(_routeCtx){_routeCtx._offs.splice(0).forEach(f=>f());const d=ROUTES.get(_routeCtx.name);if(d&&typeof d.leave==='function'){try{d.leave()}catch(e){}}}
 _route=name;
 menuClose(false);
 const def=ROUTES.get(name),view=$('view');
 const ctx={name,_offs:[],on(evt,fn){const off=on(evt,fn);ctx._offs.push(off);return off}};
 _routeCtx=ctx;
 if(view){
  view.innerHTML='';
  const page=doc.createElement('section');
  page.className='page page-'+name;
  page.setAttribute('data-page',name);
  view.appendChild(page);
  if(typeof def.render==='function'){try{def.render(page,ctx)}catch(e){if(root.console)console.error(e)}}
 }
 doc.title=(def.title?def.title+' · ':'')+'WG Cascade';
 renderNav();
 if(prev&&prev!==name){
  const main=$('main');
  if(main&&main.focus){try{main.focus({preventScroll:true})}catch(e){}}
  if(root.scrollTo){try{root.scrollTo(0,0)}catch(e){}}
 }
 emit('route',name);
}
function renderNav(){
 const nav=$('nav'),tab=$('tabbar');
 const list=[...ROUTES.values()];
 if(nav)nav.innerHTML=list.filter(r=>r.nav!==false).map(r=>'<a class="nav-i" href="#/'+esc(r.name)+'"'+(r.name===_route?' aria-current="page"':'')+'>'
  +icon(r.icon,16)+'<span>'+esc(r.title||r.name)+'</span></a>').join('');
 if(tab){
  const tabs=list.filter(r=>r.mobileTab);
  const moreOn=!tabs.some(r=>r.name===_route);
  tab.innerHTML=tabs.map(r=>'<a class="tab" href="#/'+esc(r.name)+'"'+(r.name===_route?' aria-current="page"':'')+'>'
   +'<span class="tab-ic">'+icon(r.icon,20)+'</span><span class="tab-l">'+esc(r.title||r.name)+'</span></a>').join('')
   +'<button type="button" class="tab'+(moreOn?' is-on':'')+'" data-act="more" aria-haspopup="menu" aria-expanded="false">'
   +'<span class="tab-ic">'+icon('more',20)+'</span><span class="tab-l">'+esc(tr('More'))+'</span></button>';
 }
}
function themeItem(){
 return{type:'segment',icon:'sun',label:tr('Theme'),value:themeGet(),
  options:[{value:'light',label:tr('Light')},{value:'dark',label:tr('Dark')},{value:'auto',label:tr('Auto')}],onChange:themeSet};
}
function langItem(){
 return{type:'segment',icon:'globe',label:tr('Language'),value:LANG,
  options:[{value:'ru',label:'RU'},{value:'en',label:'EN'}],onChange:v=>{if(v!==LANG)setLang(v)}};
}
delegate('account',el=>menuOpen(el,[
 themeItem(),langItem(),{type:'sep'},
 {icon:'download',label:tr('Config backup'),act:()=>WG.actions.backup()},
 {type:'sep'},
 {icon:'logout',label:tr('Sign out'),act:()=>{try{location.href='/logout'}catch(e){}}},
 {icon:'lock',label:tr('Sign out everywhere…'),danger:true,act:()=>WG.actions.logoutAll()}
],{title:tr('Account')}));
delegate('more',el=>menuOpen(el,[
 {icon:'split',label:tr('Split tunnel'),hint:(WG.state.rud?tr('RU direct · on'):tr('RU direct · off'))+' ›',hintTone:WG.state.rud&&!unknown()?'ok':'',act:()=>go('split')},
 {icon:'journal',label:tr('Journal'),hint:'›',act:()=>go('journal')},
 {icon:'download',label:tr('Config backup'),hint:'›',act:()=>WG.actions.backup()},
 themeItem(),langItem(),
 {icon:'logout',label:tr('Sign out'),act:()=>{try{location.href='/logout'}catch(e){}}},
 {icon:'lock',label:tr('Sign out everywhere…'),danger:true,act:()=>WG.actions.logoutAll()}
],{title:tr('More'),sheet:true}));
delegate('add-client',()=>WG.actions.addClient());
function renderShell(){
 const acct=$('acct');
 if(acct){acct.innerHTML=icon('user',16);acct.setAttribute('aria-label',tr('Account'))}
 const add=$('addbtn');
 if(add){add.setAttribute('aria-label',tr('Add client'));const t=add.querySelector('.addbtn-t');if(t)t.textContent=tr('Client')}
 (doc.querySelectorAll?doc.querySelectorAll('[data-i18n]'):[]).forEach(el=>{el.textContent=tr(el.textContent.trim())});
 ['nav','tabbar'].forEach(id=>{const el=$(id);if(el&&el.setAttribute)el.setAttribute('aria-label',tr('Sections'))});
}

/* ------------------------------------------------------------ actions (stubs) */
function stub(title){
 return function(){
  modalOpen({eyebrow:tr('Coming soon'),title:tr(title),size:'sm',
   body:'<p class="prose">'+esc(tr('This window moves to the new design in the next step.'))+'</p>',
   footer:'<button class="btn btn-primary" type="button" data-act="modal-close">'+esc(tr('Close'))+'</button>'});
 };
}
async function logoutAll(){
 const ok=await confirmBox({title:tr('Sign out on all devices?'),
  body:esc(tr('Every session ends, this one too. You will need to sign in again.')),confirmLabel:tr('Sign out everywhere'),danger:true});
 if(!ok)return;
 try{
  const r=await timedFetch('/logout-all',{method:'POST',headers:{'X-CSRF':csrf()},cache:'no-store'},GET_DEADLINE_MS).promise;
  if(!respOk(r)&&r.status!==401)throw new Error('HTTP '+r.status);
 }catch(e){
  modalOpen({title:tr('Not applied'),size:'sm',body:'<p class="prose">'+esc(tr('Could not sign out everywhere. Nothing changed.'))+'</p>',
   footer:'<button class="btn btn-primary" type="button" data-act="modal-close">'+esc(tr('Got it'))+'</button>'});
  return;
 }
 toLogin();
}
const actions={
 addClient:stub('Add client'),showConfig:stub('Config and QR'),editClient:stub('Edit client'),
 toggleEnabled:stub('Turn off'),deleteClient:stub('Delete client'),switchExit:stub('Change exit'),
 exitsSettings:stub('Exit settings'),revertSwitch:stub('Move clients back'),splitSettings:stub('Split tunnel'),
 backup:stub('Config backup'),logoutAll
};
addStrings('ru',{'Config and QR':'Конфиг и QR','Edit client':'Изменить клиента','Turn off':'Выключить',
 'Delete client':'Удалить клиента','Change exit':'Сменить выход','Exit settings':'Настройки выходов',
 'Move clients back':'Вернуть клиентов'});

/* ------------------------------------------------------------ start */
function start(){
 if(_started)return;_started=true;
 themeSet(themeGet());
 renderShell();
 renderNav();
 renderRoute(true);
 if(root.addEventListener){
  root.addEventListener('hashchange',()=>renderRoute());
  root.addEventListener('online',kickTick);
 }
 doc.addEventListener('visibilitychange',()=>{if(!doc.hidden)kickTick()});
 setInterval(()=>{renderAge();renderCountdowns();emit('second')},1000);
 scheduleTick(0);
}

Object.defineProperty(WG,'lang',{get:()=>LANG,configurable:true});
Object.assign(WG,{
 tr,addStrings,plural,count,setLang,
 fmtBytes,fmtMbit,mbit,fmtAgo,fmtDate,fmtTime,fmtClock,esc,icon,
 on,emit,delegate,refresh:kickTick,unknown,dataAge,api,admin,targetText,reasonText,
 modal:{open:modalOpen,close:modalClose,current:()=>_modal},
 confirm:confirmBox,
 ops:{run:opsRun,running:key=>OPS.has(String(key))},
 menu:{open:menuOpen,close:menuClose},
 router:{register,go,current:()=>_route},
 banner:{set:bannerSet,clear:bannerClear,render:renderBanners},
 theme:{get:themeGet,set:themeSet},
 actions:WG.actions?Object.assign(actions,WG.actions):actions,
 EXITS,exitCity,peer,
 _poll:{tick,nextTickDelay,kick:kickTick,timedFetch,focusables,adminTimeout,start}
});
if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',start);
else setTimeout(start,0);
})();
