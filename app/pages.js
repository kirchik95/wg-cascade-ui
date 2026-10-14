/* Sections of stage 2C: «Выходы» (B3/E5), «Расход» (B1), «Журнал» (B2) and «Сплит».
 * Re-registering a route replaces the placeholder from dashboard.js (nav order is kept).
 * Honesty (DS-3): in a stale or offline state the parts that describe *now* (the scheme,
 * the «Сейчас» plaque) turn grey; dated records (check history, usage, journal) keep
 * their colours and say when they were taken.
 * Pure helpers are exported as WG.pages for the node tests. */
(function(){
'use strict';
const root=typeof globalThis!=='undefined'?globalThis:window;
const WG=root.WG;
const {tr,esc,icon}=WG;
const doc=document;
const DAY=86400,GIB=1073741824;
const FAIL_PROBES=3,HEALTH_COOLDOWN=300;          /* app/exit_policy.py */
const SWITCH_RECENT_S=24*3600;

WG.addStrings('ru',{
 /* exits */
 'Exits · how traffic flows':'Выходы · как идёт трафик','Cascade scheme':'Схема каскада',
 'thickness = clients':'толщина = клиенты','direct RU traffic':'прямой РФ-трафик','not working':'не работает',
 'Devices':'Устройства','{n} online':'{n} онлайн','online: ?':'онлайн: ?','Entry · Russia':'Вход · Россия','Russia':'Россия',
 'CPU {c}% · memory {m}':'ЦП {c}% · память {m}','CPU {c}%':'ЦП {c}%','RU split: on':'сплит РФ: вкл','RU split: off':'сплит РФ: выкл',
 'checked {t}':'проверено {t}','check {n}/3':'проверка {n}/3','no answer {t}':'нет ответа {t}','no answer':'нет ответа',
 'check {t}':'проверка {t}','no checks yet':'проверок ещё не было','Exit {exit}':'Выход {exit}',
 '{u} / {q} {unit} in {month}':'{u} / {q} {unit} за {month}','{u} / {q} {unit} · {p}%':'{u} / {q} {unit} · {p}%',
 'Directly':'Напрямую','RU sites':'Сайты РФ','RU':'РФ','split on':'сплит вкл','split off':'сплит выкл','RU IP':'RU IP',
 'split: RU straight from a RU IP':'сплит: РФ сразу с RU IP','split off: RU sites go through the exits too':'сплит выкл: сайты РФ тоже через выходы',
 'Internet':'Интернет',
 'Line thickness — how many clients use the exit. Dashed — traffic to RU sites leaves straight from the entry.':'Толщина линии — сколько клиентов на выходе. Пунктир — трафик на сайты РФ уходит прямо со входа.','ok':'ок','{n} cl':'{n} кл','no connection':'нет связи','collection stuck':'сбор завис','waiting…':'ждём…',
 'Now':'Сейчас','Exit settings':'Настройки выходов','Move {n} back to {exit}':'Вернуть {n} на {exit}',
 'Waiting for the first data…':'Ждём первые данные…',
 'No connection with the panel: the scheme shows {t}; actions are off.':'Нет связи с панелью: схема на {t}, действия недоступны.',
 'Data is stale: the scheme shows the state at {t}; things may be different now.':'Данные устарели: схема показывает состояние на {t}, сейчас всё может быть иначе.',
 'All {n} on {exit}':'Все {n} на {exit}','{a} on NL, {b} on US':'{a} на NL, {b} на US',
 'Both exits do not answer since {t}: clients reach the entry but not the internet':'Оба выхода не отвечают с {t}: клиенты подключаются ко входу, но не выходят в интернет',
 ' — only RU sites work (split).':' — работают только сайты РФ (сплит).',
 '{exit} does not answer since {t}: {n} without an exit.':'{exit} не отвечает с {t}: без выхода {n}.',
 '{exit} does not answer since {t}; no enabled clients are on it.':'{exit} не отвечает с {t}; включённых клиентов на нём нет.',
 'Automatic failover is off — move the clients by hand.':'Автопереключение по сбою выключено — переведите клиентов вручную.',
 'Automatic switch did not run: {r}':'Автопереключение не сработало: {r}',
 '{dist}: at {at} {from} failed its checks, {n} moved automatically.':'{dist}: в {at} {from} не прошёл проверки, {n} переведены автоматически.',
 '{dist}: at {at} the {from} quota ran out, {n} moved to {to}.':'{dist}: в {at} закончилась квота {from}, {n} переведены на {to}.',
 '{exit} healthy again since {t}.':'{exit} в норме с {t}.','{exit} still does not answer.':'{exit} всё ещё не отвечает.',
 '{exit} used {p}% of its quota.':'{exit} израсходовал {p}% квоты.','At 100% its clients move to {other} automatically.':'При 100% клиенты перейдут на {other} автоматически.',
 'Switching by quota is off.':'Переключение по квоте выключено.',
 '{dist}. Both exits pass their checks':'{dist}. Оба выхода проходят проверки',
 ', RU sites open straight from the entry.':', сайты РФ открываются напрямую со входа.',
 'Health checks · 24 h':'Проверки · 24 ч','as of {t}':'на {t}','could not refresh':'обновить не удалось','Loading…':'Загрузка…','Retry':'Повторить',
 'Check history is unavailable.':'История проверок недоступна.','no data':'нет данных',
 '{h}:00 — no checks':'{h}:00 — проверок не было','{h}:00 — {n} checks, {f} failed':'{h}:00 — проверок: {n}, неудачных: {f}',
 '{exit}: {n} checks in 24 h, {f} failed':'{exit}: за 24 ч проверок {n}, неудачных {f}','24 h ago':'24 ч назад','12 h':'12 ч','now':'сейчас',
 'hatched — the panel was not running':'штриховка — панель не работала',
 'failure {r}':'сбой {r}','failures {r}':'сбои {r}','{n} h without failures':'{n} ч без сбоев','{n} h no data':'{n} ч нет данных',
 'How it works':'Как это работает','Entry':'Вход','Exit':'Выход','Split':'Сплит','Protection':'Защита',
 'Devices connect to the server in Russia over WireGuard. From outside it is a plain connection to a Russian IP.':'Устройства подключаются к серверу в России по WireGuard. Снаружи это обычное соединение с российским IP.',
 'The entry forwards traffic to the client’s exit — NL or US — over AmneziaWG, a tunnel masked against blocking.':'Вход пересылает трафик на выход клиента — NL или US — по AmneziaWG, туннелю, замаскированному от блокировок.',
 'RU subnets do not go abroad: they leave straight from the entry, and Russian sites see a Russian IP.':'Подсети РФ не уходят за границу: они выходят прямо со входа, и российские сайты видят российский IP.',
 'Split is off now: all traffic, RU sites too, goes through the exits.':'Сплит сейчас выключен: весь трафик, включая сайты РФ, идёт через выходы.',
 'Exits are checked every ~{n} s.':'Выходы проверяются каждые ~{n} с.','Exits are checked all the time.':'Выходы проверяются постоянно.',
 '{n} failures in a row or a used-up quota move clients to the other exit. Back — by hand.':'{n} неудачи подряд или исчерпанная квота — клиенты уходят на второй выход. Назад — вручную.',
 '{n} failures in a row move clients to the other exit; quota switching is off. Back — by hand.':'{n} неудачи подряд — клиенты уходят на второй выход; по квоте не переключаем. Назад — вручную.',
 'A used-up quota moves clients to the other exit; on a failure they stay — move them by hand.':'Исчерпанная квота — клиенты уходят на второй выход; при сбое остаются — переводите вручную.',
 'Automatic switching is off: clients move only by hand.':'Автопереключение выключено: клиентов переводят только вручную.',
 /* usage */
 'Traffic usage':'Расход трафика','Previous month':'Предыдущий месяц','Next month':'Следующий месяц','Month':'Месяц',
 'quota {q} {unit}':'квота {q} {unit}','Through the exits this month':'Через выходы за месяц','Through the exits':'Через выходы',
 'on average {r} a day':'в среднем {r} в день','/day':'/день',
 'average over {span} ({r}): by {end} ~{p} {unit}':'по среднему за {span} ({r}): к {end} ~{p} {unit}',
 'at the pace of {span} ({r}) runs out ~{d}':'при темпе {span} ({r}) кончится ~{d}',
 'at the pace of {span} ({r}) it would run out ~{d}':'при темпе {span} ({r}) кончилась бы ~{d}',
 'quota used up on {d}':'квота исчерпана {d}','quota used up':'квота исчерпана','month total · {r} on average':'итог месяца · в среднем {r}',
 'now {exit} has {n}':'сейчас на {exit} {n}','no quota set':'квота не задана',
 'By day':'По дням','scale 0–{m} {unit}':'шкала 0–{m} {unit}','automatic switch {from} → {to}':'автопереключение {from} → {to}',
 'switch {from} → {to}':'переключение {from} → {to}','{d} · {what}':'{d} · {what}','Day':'День','Total':'Всего',
 'Usage by day through the exits, {month}':'Расход по дням через выходы, {month}',
 'By client':'По клиентам','client traffic at the entry for the month, RU direct included':'трафик клиентов на входе за месяц, включая прямой РФ',
 'Client':'Клиент','Usage':'Расход','↓ Received':'↓ Приём','↓ received':'↓ приём','↑ Sent':'↑ Отдача','deleted':'удалён',
 'Open the usage of {name}':'Открыть расход {name}','+ {n} more ↓':'+ ещё {n} ↓','Show less ↑':'Свернуть ↑','CSV':'CSV',
 'Download the client table as CSV':'Скачать таблицу клиентов в CSV','Download the daily table as CSV':'Скачать расход по дням в CSV',
 'No traffic in {month}.':'За {month} трафика нет.','The panel keeps daily usage for a limited time; older months may be empty.':'Панель хранит расход по дням ограниченное время, старые месяцы могут быть пустыми.',
 'Could not load the usage.':'Не удалось загрузить расход.','The usage database is unavailable.':'База расхода недоступна.',
 'Showing the data loaded at {t}.':'Показаны данные, загруженные в {t}.',
 /* journal */
 'Event journal':'Журнал событий','What happened':'Что происходило','All':'Всё','Exits':'Выходы','Clients':'Клиенты','Access':'Доступ',
 'Event type':'Тип событий','Export':'Экспорт','Download the loaded events as CSV':'Скачать загруженные события в CSV',
 'Today':'Сегодня','Yesterday':'Вчера','Show more':'Показать ещё','That is the whole journal.':'Это весь журнал.',
 'No events yet.':'Событий пока нет.','No events of this type.':'Событий этого типа нет.',
 'Could not load the journal.':'Не удалось загрузить журнал.','The journal is unavailable.':'Журнал недоступен.',
 'Sign-in':'Вход','Switch':'Переключение','Settings':'Настройки','Backup':'Бэкап','system':'система','protection':'защита',
 'Move {n} back →':'Вернуть {n} →','Move these clients back':'Вернуть этих клиентов',
 'Client {name} created':'Создан клиент {name}','exit {exit}':'выход {exit}','no expiry':'бессрочно','until {d}':'до {d}',
 'Renamed to {name}':'Клиент переименован в {name}','{name} turned on':'{name} включён','{name} turned off':'{name} выключен',
 'access restored':'доступ восстановлен','access paused, keys kept':'доступ приостановлен, ключи сохранены',
 'Client {name} deleted':'Клиент {name} удалён','keys and config removed':'ключи и конфиг удалены',
 '{name}: access until {d}':'{name}: доступ до {d}','{name}: no expiry now':'{name}: теперь бессрочно',
 '{name} moved to {exit}':'{name} переведён на {exit}','Everyone is already on {exit}':'Все клиенты уже на {exit}',
 'Everyone moved to {exit}':'Все клиенты переведены на {exit}','Nobody left to move back':'Возвращать было некого',
 'the clients were deleted or moved by hand':'клиенты удалены или переведены вручную',
 'Exit settings changed':'Изменены настройки выходов','quotas and automatic switching':'квоты и автопереключение',
 'Split tunnel list saved':'Сохранён список сплит-туннеля','RU subnets refreshed':'подсети РФ обновлены',
 'Split tunnel turned on':'Сплит-туннель включён','Split tunnel turned off':'Сплит-туннель выключен',
 'RU sites go straight from the entry':'сайты РФ идут прямо со входа','all traffic goes through the exits':'весь трафик идёт через выходы',
 'Config backup downloaded':'Скачан бэкап конфигураций','the archive holds every private key':'в архиве все приватные ключи',
 'Operation {op}':'Операция {op}','Not applied: {what}':'Не применено: {what}','Result unknown: {what}':'Результат неизвестен: {what}',
 'Not started: {what}':'Не начато: {what}','another operation was running':'шла другая операция',
 'the server did not answer in time — check the state':'сервер не ответил вовремя — проверьте состояние',
 'wrong password':'неверный пароль','the server refused the request':'сервер отклонил запрос',
 'creating {name}':'создание клиента {name}','renaming to {name}':'переименование в {name}','turning on {name}':'включение {name}',
 'turning off {name}':'выключение {name}','deleting {name}':'удаление {name}','changing the expiry of {name}':'смена срока {name}',
 'moving {name} to {exit}':'перевод {name} на {exit}','moving everyone to {exit}':'перевод всех на {exit}',
 'moving clients back':'возврат клиентов','exit settings':'настройки выходов','split tunnel list':'список сплит-туннеля',
 'split tunnel switch':'переключение сплит-туннеля','config backup':'бэкап конфигураций',
 '{exit} stopped answering':'{exit} перестал отвечать','{exit} passes its checks again':'{exit} снова проходит проверки',
 'it was down right after the panel started':'не отвечал уже при запуске панели','clients return by hand':'клиенты возвращаются вручную',
 '{from} failed its checks':'{from} не прошёл проверки','the {from} quota ran out':'квота {from} исчерпана','by hand':'вручную',
 'back after the switch at {t}':'возврат после переключения в {t}','back after an earlier switch':'возврат после прошлого переключения',
 'next automatic switch not before {t}':'следующее автопереключение не раньше {t}','moved back at {t}':'возвращены в {t}',
 'and {n} more':'и ещё {n}','Signed in to the panel':'Вход в панель','Failed sign-in attempt':'Неудачная попытка входа',
 'from {ip}':'с {ip}','sign-in from this address is blocked for a while':'вход с этого адреса временно заблокирован',
 'Sign-in failed on the server':'Сбой входа на сервере','could not create a session':'не удалось создать сессию',
 'Signed out on all devices':'Выход на всех устройствах','every session ended':'все сессии завершены',
 'key {k}':'ключ {k}','a client':'клиент',
 /* split */
 'Split tunnel':'Сплит-туннель','RU sites directly':'Сайты РФ напрямую','Configure split':'Настроить сплит',
 'On: RU subnets leave straight from the entry with a Russian IP.':'Включён: подсети РФ выходят прямо со входа с российским IP.',
 'Off: all traffic goes through the NL and US exits.':'Выключен: весь трафик идёт через выходы NL и US.',
 'State unknown: no fresh data.':'Состояние неизвестно: нет свежих данных.',
 'Banks, government services and other Russian sites often refuse foreign IPs. With the split on, the entry sends traffic to RU subnets straight to the internet, so those sites see a Russian address, while everything else goes through the exit.':'Банки, госуслуги и другие российские сайты часто не пускают с зарубежных IP. Со включённым сплитом вход отправляет трафик к подсетям РФ сразу в интернет, и эти сайты видят российский адрес, а всё остальное идёт через выход.',
 'The list of subnets and the server switch live in the split settings window.':'Список подсетей и переключатель на сервере — в окне настроек сплита.'
});

/* ------------------------------------------------------------ small helpers */
const LANG=()=>WG.lang==='en'?'en':'ru';
const UNIT=()=>LANG()==='en'?'GiB':'ГиБ';
const XL=k=>String(k||'').toUpperCase();
const pad=n=>(n<10?'0':'')+n;
const MONTH_NOM={ru:['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'],
 en:['January','February','March','April','May','June','July','August','September','October','November','December']};
const MONTH_GEN={ru:['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'],
 en:MONTH_NOM.en};
const MONTH_SHORT={ru:['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек'],
 en:['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']};
/* «к 31 окт» / «by Oct 31»; m is 1-based */
function dayMon(d,m){return LANG()==='en'?MONTH_SHORT.en[m-1]+' '+d:d+' '+MONTH_SHORT.ru[m-1]}
/* GiB for figures: one decimal under 10, whole above */
function gibs(n){const v=(+n||0)/GIB;return v>0&&v<10?v.toFixed(1):String(Math.round(v))}
function nowTs(s){s=s||WG.state;return +s.now||Math.round(Date.now()/1000)}
function mode(s){return WG.dashboard?WG.dashboard.mode(s):(s.offline?'offline':s.stale?'stale':s.loaded?'live':'loading')}
function exitInfo(s,k){return WG.dashboard.exitInfo(s,k)}
const isUnknownMode=m=>m==='offline'||m==='stale'||m==='loading';
function noDot(s){return String(s||'').replace(/\.\s*$/,'')}
/* «Квота исчерпана» → «квота исчерпана» for a detail line; acronyms (NL, US) stay */
function lcFirst(s){s=String(s||'');return/^.[a-zа-яё]/.test(s)?s.charAt(0).toLowerCase()+s.slice(1):s}
function errText(e,unavailable,generic){return e&&e.status===503?tr(unavailable):tr(generic)}
function plural(n,forms){return WG.plural(n,forms)}
const P_FAILS_ROW={ru:{one:'{n} проверка подряд без ответа',few:'{n} проверки подряд без ответа',many:'{n} проверок подряд без ответа',other:'{n} проверки подряд без ответа'},
 en:{one:'{n} check in a row failed',other:'{n} checks in a row failed'}};
const P_OKS_ROW={ru:{one:'{n} успешная проверка подряд',few:'{n} успешные проверки подряд',many:'{n} успешных проверок подряд',other:'{n} успешной проверки подряд'},
 en:{one:'{n} successful check in a row',other:'{n} successful checks in a row'}};
const P_MOVED={ru:{one:'{n} клиент переведён {from} → {to}',few:'{n} клиента переведены {from} → {to}',many:'{n} клиентов переведены {from} → {to}',other:'{n} клиента переведены {from} → {to}'},
 en:{one:'{n} client moved {from} → {to}',other:'{n} clients moved {from} → {to}'}};
const P_LOGIN_FAILS={ru:{one:'{n} неудачная попытка входа в панель',few:'{n} неудачные попытки входа в панель',many:'{n} неудачных попыток входа в панель',other:'{n} неудачной попытки входа в панель'},
 en:{one:'{n} failed sign-in attempt',other:'{n} failed sign-in attempts'}};
const P_ENTRIES={ru:{one:'{n} запись',few:'{n} записи',many:'{n} записей',other:'{n} записи'},en:{one:'{n} entry',other:'{n} entries'}};

function pageHead(eyebrow,title,tools,id){
 return'<header class="pg-h"><div class="pg-ht"><div class="eyebrow">'+esc(eyebrow)+'</div>'
  +'<h1 class="pg-title"'+(id?' id="'+id+'"':'')+'>'+esc(title)+'</h1></div>'+(tools?'<div class="pg-tools">'+tools+'</div>':'')+'</header>';
}
function msgHTML(text,retryAct,note){
 return'<div class="pg-msg"><p>'+esc(text)+'</p>'+(note?'<p class="pg-msg-n">'+esc(note)+'</p>':'')
  +(retryAct?'<button type="button" class="btn btn-sm btn-outline" data-act="'+retryAct+'">'+icon('refresh',14)+esc(tr('Retry'))+'</button>':'')+'</div>';
}
/* innerHTML only when the markup changed: keeps focus and avoids flicker on every poll */
function patcher(){
 const sig={};
 return(key,el,html)=>{if(!el||sig[key]===html)return;sig[key]=html;el.innerHTML=html};
}
function csvCell(v){
 if(v==null)return'';
 let s=String(v);
 if(typeof v==='string'&&/^[=+\-@\t\r]/.test(s))s="'"+s;      /* no formulas from names in spreadsheets */
 return/[",;\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;
}
function toCSV(rows){return rows.map(r=>r.map(csvCell).join(',')).join('\r\n')+'\r\n'}
function download(name,text){
 try{
  const blob=new Blob(['﻿'+text],{type:'text/csv;charset=utf-8'});
  const url=URL.createObjectURL(blob),a=doc.createElement('a');
  a.href=url;a.download=name;a.hidden=true;doc.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),2000);
 }catch(e){}
}
function isoMinute(ts){const d=new Date(ts*1000);return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+' '+pad(d.getHours())+':'+pad(d.getMinutes())}

/* ================================================================ exits (B3 / E5) */
function wireWidth(share){return share>0?Math.max(3,Math.round(2+8*share)):2}
function diagramModel(s){
 const m=mode(s),u=isUnknownMode(m),peers=s.peers||[];
 const xs=WG.EXITS.map(k=>exitInfo(s,k)),sum=xs.reduce((a,x)=>a+x.clients,0);
 const mainKey=xs[0].clients>=xs[1].clients?xs[0].key:xs[1].key;
 return{m,u,loaded:!!s.loaded,total:peers.length,online:peers.filter(p=>p.online).length,rud:!!s.rud,
  thr:(s.thr&&s.thr.cur)||null,host:s.host||null,
  exits:xs.map(x=>({key:x.key,clients:x.clients,health:x.health,ratio:x.ratio,used:x.used,quota:x.quota,t:x.t,
   main:x.key===mainKey&&x.clients>0,w:wireWidth(sum?x.clients/sum:0),
   tone:u?'u':x.health==='down'?'bad':x.health==='ok'?'ink':'u'}))};
}
function exitChip(e,s){
 const t=e.t||{};
 if(e.health==='ok')return'<span class="xs-st is-ok">● '+esc(tr('checked {t}',{t:WG.fmtAgo(+t.checked_age,{suffix:false})}))+'</span>';
 if(e.health==='down'){
  const since=+t.health_since?nowTs(s)-t.health_since:-1;
  return'<span class="xs-st is-bad">× '+esc(since>=0?tr('no answer {t}',{t:WG.fmtAgo(since,{suffix:false})}):tr('no answer'))+'</span>';
 }
 if(e.health==='warn')return'<span class="xs-st is-warn">! '+esc(tr('check {n}/3',{n:Math.min(FAIL_PROBES,+t.fails||1)}))+'</span>';
 const age=+t.checked_age>=0?+t.checked_age:-1;
 return'<span class="xs-st is-u">? '+esc(age>=0?tr('check {t}',{t:WG.fmtAgo(age)}):tr('no checks yet'))+'</span>';
}
function bar10(e,u){
 const n=10,filled=e.ratio>0?Math.min(n,Math.max(1,Math.round(e.ratio*n))):0;
 const tone=u?'is-u':e.ratio>=1?'is-bad':e.ratio>=.7?'is-warn':'is-on';
 let h='<span class="bar xs-bar" aria-hidden="true">';
 for(let i=0;i<n;i++)h+='<i class="'+(i<filled?tone:'')+((i+1)/n>.9?' z-bad':(i+1)/n>.8?' z-warn':'')+'"></i>';
 return h+'</span>';
}
function quotaLine(e,s,u){
 const mi=new Date(nowTs(s)*1000).getMonth(),mon=LANG()==='en'?MONTH_NOM.en[mi]:MONTH_NOM.ru[mi].toLowerCase();
 const warn=e.ratio>=.7;
 const txt=warn?tr('{u} / {q} {unit} · {p}%',{u:gibs(e.used),q:gibs(e.quota),unit:UNIT(),p:Math.floor(e.ratio*100)})
  :tr('{u} / {q} {unit} in {month}',{u:gibs(e.used),q:gibs(e.quota),unit:UNIT(),month:mon});
 return'<div class="xs-q'+(warn&&!u?' is-warn':'')+(e.ratio>=1&&!u?' is-bad':'')+'">'+esc(txt)+'</div>';
}
function speedText(md,unit){
 if(md.u||!md.thr)return'';
 const f=bps=>{const v=+WG.mbit(bps);return v>=10||v===0?String(Math.round(v)):v.toFixed(1)};
 return'↓'+f(md.thr.down)+' ↑'+f(md.thr.up)+(unit?' '+tr('Mbit/s'):'');
}
function entryState(md){
 if(md.m==='offline')return{tone:'u',text:'× '+tr('no connection')};
 if(md.m==='stale')return{tone:'u',text:'? '+tr('collection stuck')};
 if(md.m==='loading')return{tone:'u',text:tr('waiting…')};
 return{tone:'ok',text:'● '+tr('OK')};
}
function hostLine(h){
 if(!h)return'';
 const mem=((+h.mem_used||0)/GIB).toFixed(1)+'/'+((+h.mem_total||0)/GIB).toFixed(1)+' '+UNIT();
 return tr('CPU {c}% · memory {m}',{c:Math.round(+h.cpu||0),m:mem});
}
/* Desktop geometry: x in % of the panel width, y in px (the SVG stretches only horizontally). */
const XD={H:470,cy:200,dev:{l:1.5,w:16.5},entry:{l:33.5,w:19},exit:{l:66,w:18.5,cy:{nl:95,us:305}},net:{x:93.8},ru:{l:55.5,w:15,cy:420}};
function diagramDesktop(md,s){
 const X=p=>(p*10).toFixed(1),eR=XD.entry.l+XD.entry.w,exL=XD.exit.l,exR=XD.exit.l+XD.exit.w,cy=XD.cy;
 const wireTone=md.u?'u':'ink',wireW=md.total?10:2;
 const line=(d,tone,w,dash)=>'<path d="'+d+'" class="xd-ln is-'+tone+(dash?' is-dash':'')+'" style="stroke-width:'+w+'px"/>';
 let svg=line('M'+X(XD.dev.l+XD.dev.w-1)+' '+cy+'H'+X(XD.entry.l+1),wireTone,wireW);
 md.exits.forEach(e=>{
  const y=XD.exit.cy[e.key];
  svg+=line('M'+X(eR-1)+' '+cy+'H'+X(eR+2.5)+'L'+X(exL-5)+' '+y+'H'+X(exL+1),e.tone,e.w);
  svg+=line('M'+X(exR-1)+' '+y+'H'+X(exR+2)+'L'+X(XD.net.x)+' '+cy,e.tone,e.w);
 });
 if(md.rud){
  const ruTone=md.u?'u':'ink';
  svg+=line('M'+X(XD.entry.l+XD.entry.w/2)+' '+cy+'V'+XD.ru.cy+'H'+X(XD.ru.l+1),ruTone,2,true);
  svg+=line('M'+X(XD.ru.l+XD.ru.w-1)+' '+XD.ru.cy+'H'+X(88.5)+'L'+X(XD.net.x)+' '+cy,ruTone,2,true);
 }
 const es=entryState(md),spd=speedText(md,false);
 let h='<div class="xd'+(md.u?' is-u':'')+'" style="height:'+XD.H+'px">'
  +'<svg class="xd-svg" viewBox="0 0 1000 '+XD.H+'" preserveAspectRatio="none" aria-hidden="true" focusable="false">'+svg+'</svg>';
 h+='<span class="xd-lab" style="left:'+((XD.dev.l+XD.dev.w+XD.entry.l)/2)+'%;top:'+(cy-34)+'px;transform:translateX(-50%)">WireGuard'+(spd?' · '+esc(spd):'')+'</span>';
 md.exits.forEach(e=>{
  const y=XD.exit.cy[e.key],above=e.key==='nl';
  h+='<span class="xd-lab'+(e.clients?'':' is-faint')+'" style="right:'+(100-exL+1.2)+'%;top:'+(above?y-30:y+12)+'px">AmneziaWG · '+esc(WG.count(e.clients,'client'))+'</span>';
 });
 if(md.rud)h+='<span class="xd-lab is-faint" style="right:'+(100-XD.ru.l+1)+'%;top:'+(XD.ru.cy+8)+'px">'+esc(tr('split: RU straight from a RU IP'))+'</span>';
 h+='<div class="xd-box xs-dev" style="left:'+XD.dev.l+'%;width:'+XD.dev.w+'%;top:'+cy+'px">'
  +'<div class="label">'+esc(tr('Devices'))+'</div><div class="xs-big">'+esc(WG.count(md.total,'client'))+'</div>'
  +'<div class="xs-on'+(md.u?' is-u':'')+'">'+(md.u?esc(tr('online: ?')):'● '+esc(tr('{n} online',{n:md.online})))+'</div></div>';
 h+='<div class="xd-box xs-entry" style="left:'+XD.entry.l+'%;width:'+XD.entry.w+'%;top:'+cy+'px">'
  +'<div class="xs-bh"><span class="label">'+esc(tr('Entry · Russia'))+'</span><span class="xs-st is-'+es.tone+'">'+esc(es.text)+'</span></div>'
  +'<div class="xs-big">'+esc(tr('Russia'))+'</div>'
  +(md.host?'<div class="xs-meta">'+esc(hostLine(md.host))+'</div>':'')
  +'<div class="xs-meta'+(md.rud&&!md.u?' is-amber':'')+'">'+esc(tr(md.rud?'RU split: on':'RU split: off'))+'</div></div>';
 md.exits.forEach(e=>{
  h+='<div class="xd-box xs-exit'+(e.main?' is-main':'')+(e.tone==='bad'?' is-bad':'')+'" data-exit="'+e.key+'" style="left:'+exL+'%;width:'+XD.exit.w+'%;top:'+XD.exit.cy[e.key]+'px">'
   +'<div class="xs-bh"><span class="label">'+esc(tr('Exit {exit}',{exit:XL(e.key)}))+'</span>'+exitChip(e,s)+'</div>'
   +'<div class="xs-big">'+esc(WG.exitCity(e.key))+'</div>'+bar10(e,md.u)+quotaLine(e,s,md.u)+'</div>';
 });
 h+='<div class="xd-box xs-ru'+(md.rud?'':' is-off')+'" style="left:'+XD.ru.l+'%;width:'+XD.ru.w+'%;top:'+XD.ru.cy+'px">'
  +'<div class="label">'+esc(tr('Directly'))+'</div><div class="xs-mid">'+esc(tr('RU sites'))+'</div>'
  +(md.rud?'':'<div class="xs-meta">'+esc(tr('split off: RU sites go through the exits too'))+'</div>')+'</div>';
 h+='<div class="xd-net" style="left:'+XD.net.x+'%;top:'+cy+'px">'+icon('internet',22)+'<span>'+esc(tr('Internet'))+'</span></div>';
 return h+'</div>';
}
function diagramVertical(md,s){
 const es=entryState(md),spd=speedText(md,true);
 const stem=(w,tone,dash)=>'<span class="xv-stem"><i class="xv-l is-'+tone+(dash?' is-dash':'')+'" style="width:'+w+'px"></i></span>';
 let h='<div class="xv'+(md.u?' is-u':'')+'">'
  +'<div class="xv-card"><div><div class="label">'+esc(tr('Devices'))+'</div><div class="xs-big">'+esc(WG.count(md.total,'client'))+'</div></div>'
  +'<div class="xs-on'+(md.u?' is-u':'')+'">'+(md.u?esc(tr('online: ?')):esc(tr('{n} online',{n:md.online})))+'</div></div>'
  +'<div class="xv-wire"><i class="xv-l is-'+(md.u?'u':'ink')+'" style="width:'+(md.total?10:2)+'px"></i><span class="xv-lab">WireGuard'+(spd?' · '+esc(spd):'')+'</span></div>'
  +'<div class="xv-entry"><div><div class="label">'+esc(tr('Entry · Russia'))+'</div><div class="xs-big">'+esc(tr('Russia'))+'</div></div>'
  +'<div class="xv-est"><span class="xs-st is-'+es.tone+'">'+esc(es.text)+'</span>'
  +(md.host&&!md.u?'<span class="xv-cpu">'+esc(tr('CPU {c}%',{c:Math.round(+md.host.cpu||0)}))+'</span>':'')+'</div></div>'
  +'<div class="xv-fork">'+md.exits.map(e=>stem(e.w,e.tone)).join('')+(md.rud?stem(2,md.u?'u':'ink',true):'<span class="xv-stem"></span>')+'</div>'
  +'<div class="xv-ends">';
 md.exits.forEach(e=>{
  const st=e.health==='ok'?['is-ok',tr('ok')+' · '+WG.fmtAgo(+(e.t&&e.t.checked_age),{suffix:false})]
   :e.health==='down'?['is-bad',tr('no answer')]:e.health==='warn'?['is-warn',tr('check {n}/3',{n:Math.min(FAIL_PROBES,+(e.t&&e.t.fails)||1)})]
   :['is-u','?'];
  const q=e.ratio>=.7?Math.floor(e.ratio*100)+'%':gibs(e.used)+' '+UNIT();
  h+='<div class="xv-end'+(e.main?' is-main':'')+(e.tone==='bad'?' is-bad':'')+'" data-exit="'+e.key+'"><div class="xv-k">'+XL(e.key)+'</div>'
   +'<div class="xv-city">'+esc(WG.exitCity(e.key))+'</div><div class="xv-st xs-st '+st[0]+'">'+esc(st[1])+'</div>'
   +'<div class="xv-q'+(e.ratio>=.7&&!md.u?' is-warn':'')+'">'+esc(tr('{n} cl',{n:e.clients}))+' · '+esc(q)+'</div></div>';
 });
 h+='<div class="xv-end is-ru'+(md.rud?'':' is-off')+'"><div class="xv-k">'+esc(tr('RU'))+'</div><div class="xv-city">'+esc(tr('Directly'))+'</div>'
  +'<div class="xv-st">'+esc(tr(md.rud?'split on':'split off'))+'</div>'+(md.rud?'<div class="xv-q">'+esc(tr('RU IP'))+'</div>':'')+'</div>';
 h+='</div><div class="xv-net"><span>'+icon('internet',18)+esc(tr('Internet'))+'</span></div>'
  +'<p class="xv-note">'+esc(tr('Line thickness — how many clients use the exit. Dashed — traffic to RU sites leaves straight from the entry.'))+'</p></div>';
 return h;
}
function legendHTML(){
 return'<ul class="xs-legend" aria-hidden="true"><li><i class="lg-thick"></i>'+esc(tr('thickness = clients'))+'</li>'
  +'<li><i class="lg-dash"></i>'+esc(tr('direct RU traffic'))+'</li><li><i class="lg-bad"></i>'+esc(tr('not working'))+'</li></ul>';
}
function distText(xs){
 const total=xs.reduce((a,x)=>a+x.clients,0);
 const all=xs.find(x=>x.clients===total&&total>0);
 if(all&&total>1)return tr('All {n} on {exit}',{n:WG.count(total,'client'),exit:XL(all.key)});
 const byKey={};xs.forEach(x=>{byKey[x.key]=x.clients});
 return tr('{a} on NL, {b} on US',{a:byKey.nl||0,b:byKey.us||0});
}
/* «Сейчас»: one sentence about the current situation plus what can be done about it. */
function situation(s){
 const m=mode(s),now=nowTs(s),pol=s.exit_policy||{},xs=WG.EXITS.map(k=>exitInfo(s,k));
 if(m==='loading')return{tone:'u',text:tr('Waiting for the first data…')};
 if(m==='offline')return{tone:'u',text:tr('No connection with the panel: the scheme shows {t}; actions are off.',{t:WG.fmtTime(s.dataAt)})};
 if(m==='stale')return{tone:'u',text:tr('Data is stale: the scheme shows the state at {t}; things may be different now.',{t:WG.fmtTime(s.dataAt)})};
 const dist=distText(xs);
 const down=xs.filter(x=>x.health==='down');
 if(down.length===xs.length){
  const since=Math.max.apply(null,xs.map(x=>+(x.t&&x.t.health_since)||0));
  return{tone:'bad',text:tr('Both exits do not answer since {t}: clients reach the entry but not the internet',{t:since?WG.fmtTime(since):'—'})
   +(s.rud?tr(' — only RU sites work (split).'):'.')};
 }
 if(down.length){
  const x=down[0],since=+(x.t&&x.t.health_since)||0,n=+(x.t&&x.t.affected_clients)||0;
  const other=' '+xs.filter(e=>e.key!==x.key).map(WG.dashboard.exitStatusText).join(' · ')+'.';
  if(!n)return{tone:'warn',text:tr('{exit} does not answer since {t}; no enabled clients are on it.',{exit:XL(x.key),t:since?WG.fmtTime(since):'—'})+other};
  let text=tr('{exit} does not answer since {t}: {n} without an exit.',{exit:XL(x.key),t:since?WG.fmtTime(since):'—',n:WG.count(n,'client')});
  text+=other;
  if(n&&pol.health_failover===false)text+=' '+tr('Automatic failover is off — move the clients by hand.');
  else if(n&&pol.health_blocked)text+=' '+tr('Automatic switch did not run: {r}',{r:WG.reasonText(pol.health_blocked.code||pol.health_blocked)});
  return{tone:'bad',text};
 }
 const unverified=xs.filter(x=>x.health==='warn'||x.health==='unknown');
 if(unverified.length)return{tone:unverified.some(x=>x.health==='warn')?'warn':'u',
  text:dist+'. '+unverified.map(WG.dashboard.exitStatusText).join(' · ')+'.'};
 const ls=pol.last_switch;
 if(ls&&typeof ls==='object'&&!ls.revert_of&&+ls.changed>0&&+ls.ts>0&&now-ls.ts<SWITCH_RECENT_S
  &&(ls.reason==='health'||ls.reason==='quota')&&WG.EXITS.indexOf(ls.source)>=0&&WG.EXITS.indexOf(ls.target)>=0){
  const n=+ls.members_count||+ls.changed||0,from=XL(ls.source),to=XL(ls.target),src=exitInfo(s,ls.source),at=WG.fmtTime(ls.ts);
  if(ls.reason==='health'){
   let text=tr('{dist}: at {at} {from} failed its checks, {n} moved automatically.',{dist,at,from,n:WG.count(n,'client')});
   const since=src.t&&+src.t.health_since;
   text+=' '+(src.health==='ok'?tr('{exit} healthy again since {t}.',{exit:from,t:since?WG.fmtTime(since):'—'}):tr('{exit} still does not answer.',{exit:from}));
   const can=src.health==='ok'&&+ls.members_count>0&&+ls.event_id>0;
   return{tone:'warn',text,revert:can?{id:+ls.event_id,n:+ls.members_count,exit:from}:null};
  }
  return{tone:'warn',text:tr('{dist}: at {at} the {from} quota ran out, {n} moved to {to}.',{dist,at,from,to,n:WG.count(n,'client')})};
 }
 const hot=xs.filter(x=>x.quota&&x.ratio>=.9&&x.clients)[0];
 if(hot){
  const other=XL(hot.key==='us'?'nl':'us');
  return{tone:'warn',text:dist+'. '+tr('{exit} used {p}% of its quota.',{exit:XL(hot.key),p:Math.floor(hot.ratio*100)})+' '
   +(pol.auto_switch===false?tr('Switching by quota is off.'):tr('At 100% its clients move to {other} automatically.',{other}))};
 }
 return{tone:'ok',text:tr('{dist}. Both exits pass their checks',{dist})+(s.rud?tr(', RU sites open straight from the entry.'):'.')};
}
function situationHTML(s){
 const st=situation(s),off=WG.unknown();
 return'<div class="xs-now-in is-'+st.tone+'"><span class="tag xs-now-tag">'+esc(tr('Now'))+'</span>'
  +'<p class="xs-now-t">'+esc(st.text)+'</p><div class="xs-now-acts">'
  +(st.revert?'<button type="button" class="btn btn-sm btn-primary" data-act="xs-revert" data-id="'+st.revert.id+'" data-live'+(off?' disabled':'')+'>'
   +icon('switch-exit',14)+esc(tr('Move {n} back to {exit}',{n:st.revert.n,exit:st.revert.exit}))+'</button>':'')
  +'<button type="button" class="btn btn-sm btn-outline" data-act="xs-settings" data-live'+(off?' disabled':'')+'>'+icon('edit',14)+esc(tr('Exit settings'))+'</button>'
  +'</div></div>';
}
/* 24 hourly buckets → tones; an hour with no probes is «no data», never «ok». */
function healthCells(list){
 return(Array.isArray(list)?list:[]).map(b=>{
  const ok=+b.ok||0,fail=+b.fail||0,total=ok+fail;
  return{ts:+b.ts||0,ok,fail,total,tone:!total?'none':!fail?'ok':fail*2>=total?'bad':'warn'};
 });
}
/* «22 ч без сбоев · 2 ч нет данных» / «сбой 03:00–05:00» (C3) */
function healthSummary(cells){
 const none=cells.filter(c=>c.tone==='none').length,clean=cells.filter(c=>c.tone==='ok').length;
 const ranges=[];
 cells.forEach((c,i)=>{
  if(!c.fail)return;
  const last=ranges[ranges.length-1];
  if(last&&last.to===i-1)last.to=i;else ranges.push({from:i,to:i});
 });
 const hh=ts=>pad(new Date(ts*1000).getHours())+':00';
 const parts=[];
 if(ranges.length){
  const r=ranges.slice(-2).map(x=>hh(cells[x.from].ts)+'–'+hh(cells[x.to].ts+3600));
  parts.push(tr(ranges.length>1?'failures {r}':'failure {r}',{r:r.join(', ')})+(ranges.length>2?' '+tr('and {n} more',{n:ranges.length-2}):''));
 }else if(clean)parts.push(tr('{n} h without failures',{n:clean}));
 if(none)parts.push(none===cells.length?tr('no data'):tr('{n} h no data',{n:none}));
 return parts.join(' · ');
}
let _hh={data:null,err:null,at:0,loading:null};
function loadHealth(force){
 if(_hh.loading)return _hh.loading;
 if(!force&&_hh.at&&Date.now()-_hh.at<60000)return Promise.resolve();
 _hh.loading=WG.api('/api/health-history').then(d=>{_hh.data=d&&typeof d==='object'?d:null;_hh.err=null;_hh.at=Date.now()},e=>{_hh.err=e||new Error('failed')})
  .then(()=>{_hh.loading=null});
 return _hh.loading;
}
function healthHTML(){
 if(!_hh.data){
  if(_hh.err)return msgHTML(errText(_hh.err,'Check history is unavailable.','Check history is unavailable.'),'xs-hh-retry');
  return'<p class="pg-loading">'+esc(tr('Loading…'))+'</p>';
 }
 const ex=_hh.data.exits||{};
 let rows='',anyGap=false;
 WG.EXITS.forEach(k=>{
  const cells=healthCells(ex[k]),total=cells.reduce((a,c)=>a+c.total,0),fails=cells.reduce((a,c)=>a+c.fail,0);
  if(cells.some(c=>c.tone==='none'))anyGap=true;
  const sum=healthSummary(cells);
  rows+='<div class="hh-row"><span class="hh-k">'+XL(k)+'</span>'
   +'<div class="hh-cells" role="img" aria-label="'+esc(tr('{exit}: {n} checks in 24 h, {f} failed',{exit:XL(k),n:total,f:fails}))+'">'
   +cells.map(c=>{const hr=pad(new Date(c.ts*1000).getHours());
    return'<i class="is-'+c.tone+'" title="'+esc(c.total?tr('{h}:00 — {n} checks, {f} failed',{h:hr,n:c.total,f:c.fail}):tr('{h}:00 — no checks',{h:hr}))+'"></i>'}).join('')
   +'</div><span class="hh-sum'+(fails?' is-bad':'')+'">'+esc(sum)+'</span></div>';
 });
 return rows+'<div class="hh-axis" aria-hidden="true"><span>'+esc(tr('24 h ago'))+'</span><span>'+esc(tr('12 h'))+'</span><span>'+esc(tr('now'))+'</span></div>'
  +(anyGap?'<p class="hh-note">'+esc(tr('hatched — the panel was not running'))+'</p>':'');
}
function protectionText(probe,pol){
 let t=probe>0?tr('Exits are checked every ~{n} s.',{n:probe}):tr('Exits are checked all the time.');
 const hf=pol.health_failover!==false,qs=pol.auto_switch!==false;
 t+=' '+(hf&&qs?tr('{n} failures in a row or a used-up quota move clients to the other exit. Back — by hand.',{n:FAIL_PROBES})
  :hf?tr('{n} failures in a row move clients to the other exit; quota switching is off. Back — by hand.',{n:FAIL_PROBES})
  :qs?tr('A used-up quota moves clients to the other exit; on a failure they stay — move them by hand.')
  :tr('Automatic switching is off: clients move only by hand.'));
 return t;
}
function howHTML(s){
 const probe=_hh.data&&+_hh.data.probe_s||0,pol=s.exit_policy||{};
 const items=[['solid','Entry','Devices connect to the server in Russia over WireGuard. From outside it is a plain connection to a Russian IP.'],
  ['solid','Exit','The entry forwards traffic to the client’s exit — NL or US — over AmneziaWG, a tunnel masked against blocking.'],
  ['dash','Split',s.rud||!s.loaded?'RU subnets do not go abroad: they leave straight from the entry, and Russian sites see a Russian IP.':'Split is off now: all traffic, RU sites too, goes through the exits.'],
  ['amber','Protection',null]];
 return'<h2 class="sr-only">'+esc(tr('How it works'))+'</h2><ol class="xs-how-l">'+items.map((it,i)=>'<li class="xs-how-i is-'+it[0]+'">'
  +'<div class="xs-how-h">'+(i+1)+' · '+esc(tr(it[1]))+'</div><p class="xs-how-p">'+esc(it[2]?tr(it[2]):protectionText(probe,pol))+'</p></li>').join('')+'</ol>';
}
let _exitsUpd=null;
function renderExits(el,ctx){
 el.innerHTML='<div class="pg xs">'+pageHead(tr('Exits · how traffic flows'),tr('Cascade scheme'),legendHTML(),'xs-title')
  +'<section class="xs-panel" aria-labelledby="xs-title"><div class="xs-dia"></div></section>'
  +'<section class="xs-now" aria-live="polite"></section>'
  +'<section class="xs-hh" aria-labelledby="xs-hh-t"><div class="sec-h"><h2 class="sec-t" id="xs-hh-t">'+esc(tr('Health checks · 24 h'))+'</h2>'
  +'<span class="sec-note xs-hh-note"></span></div><div class="xs-hh-b"></div></section>'
  +'<section class="xs-how"></section></div>';
 const q=sel=>el.querySelector(sel),set=patcher();
 const ui={dia:q('.xs-dia'),now:q('.xs-now'),how:q('.xs-how'),hh:q('.xs-hh-b'),note:q('.xs-hh-note')};
 const upd=()=>{
  if(el.isConnected===false)return;
  const s=WG.state,md=diagramModel(s);
  set('d',ui.dia,'<div class="d-dia">'+diagramDesktop(md,s)+'</div><div class="m-dia">'+diagramVertical(md,s)+'</div>');
  set('n',ui.now,situationHTML(s));
  set('w',ui.how,howHTML(s));
  set('h',ui.hh,healthHTML());
  set('t',ui.note,_hh.at?esc(tr('as of {t}',{t:WG.fmtTime(Math.round(_hh.at/1000))}))
   +(_hh.err?' · '+esc(tr('could not refresh'))+' · <button type="button" class="linkbtn" data-act="xs-hh-retry">'+esc(tr('Retry'))+'</button>':''):'');
 };
 _exitsUpd=upd;
 ctx.on('status',upd);
 let sec=0;
 ctx.on('second',()=>{if(++sec%60===0)loadHealth().then(upd)});
 upd();
 loadHealth(true).then(upd);
}
WG.delegate('xs-revert',el=>{const id=+el.getAttribute('data-id');if(id>0)WG.actions.revertSwitch(id)});
WG.delegate('xs-settings',()=>WG.actions.exitsSettings());
WG.delegate('xs-hh-retry',()=>{const p=loadHealth(true);if(_exitsUpd)_exitsUpd();p.then(()=>{if(_exitsUpd)_exitsUpd()})});

/* ================================================================ usage (B1) */
function monthKey(ts){const d=new Date(ts*1000);return d.getFullYear()+'-'+pad(d.getMonth()+1)}
function shiftMonth(key,delta){
 let y=+key.slice(0,4),m=+key.slice(5,7)+delta;
 while(m<1){m+=12;y--}while(m>12){m-=12;y++}
 return y+'-'+pad(m);
}
function monthInfo(key,now){
 const y=+key.slice(0,4),m=+key.slice(5,7);
 const start=new Date(y,m-1,1).getTime()/1000,end=new Date(y,m,1).getTime()/1000,days=new Date(y,m,0).getDate();
 const current=now>=start&&now<end;
 return{key,y,m,days,start,end,current,past:now>=end,future:now<start,
  elapsed:current?Math.max((now-start)/DAY,1/24):now>=end?days:0,today:current?new Date(now*1000).getDate():0};
}
function monthTitle(info){return MONTH_NOM[LANG()][info.m-1]+' '+info.y}
/* inside a sentence: «за октябрь 2026» */
function monthPhrase(info){const n=MONTH_NOM[LANG()][info.m-1];return(LANG()==='ru'?n.toLowerCase():n)+' '+info.y}
function dayOfMonth(s,info){
 const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s||''));
 return m&&+m[1]===info.y&&+m[2]===info.m?+m[3]:0;
}
/* exits_daily {nl:[{day, rx, tx}], us:[…]} → one row per day of the month (bytes, rx+tx) */
function daySeries(exitsDaily,info){
 const out=[];
 for(let d=1;d<=info.days;d++)out.push({day:d,nl:0,us:0,has:false});
 WG.EXITS.forEach(k=>{
  const rows=exitsDaily&&exitsDaily[k];
  (Array.isArray(rows)?rows:[]).forEach(r=>{
   const d=dayOfMonth(r&&r.day,info);
   if(d){out[d-1][k]+=(+r.rx||0)+(+r.tx||0);out[d-1].has=true}
  });
 });
 return out;
}
/* Quota forecast, method «average so far»: rate = used / elapsed days of the month;
   the month ends at rate × days; the quota runs out on the day the same rate crosses it. */
function forecast(o){
 const info=o.info,used=+o.used||0,quota=+o.quota||0;
 const f={kind:'none',rate:0,projected:used,day:0};
 if(info.future)return f;
 const span=info.current?info.elapsed:info.days;
 f.rate=span>0?used/span:0;
 if(quota>0&&used>=quota){
  let acc=0;const s=o.series||[];
  for(let i=0;i<s.length;i++){acc+=+s[i]||0;if(acc>=quota){f.day=i+1;break}}
  f.kind='exhausted';return f;
 }
 if(!info.current){f.kind='final';return f}
 f.projected=Math.round(f.rate*info.days);
 if(quota>0&&f.rate>0&&f.projected>quota){
  const day=Math.floor(info.elapsed+(quota-used)/f.rate)+1;
  if(day<=info.days){f.kind='runs-out';f.day=day;return f}
 }
 f.kind='projection';return f;
}
function rateText(r){return gibs(r)+' '+UNIT()+tr('/day')}
function forecastText(f,o){
 const info=o.info,E=XL(o.key);
 const span=info.today>1?'1–'+dayMon(info.today,info.m):dayMon(1,info.m);
 const idle=o.clients===0&&(+o.used||0)>0?' · '+tr('now {exit} has {n}',{exit:E,n:WG.count(0,'client')}):'';
 if(f.kind==='exhausted')return f.day?tr('quota used up on {d}',{d:dayMon(f.day,info.m)}):tr('quota used up');
 if(f.kind==='final')return tr('month total · {r} on average',{r:rateText(f.rate)});
 if(f.kind==='runs-out')return tr(o.clients===0?'at the pace of {span} ({r}) it would run out ~{d}':'at the pace of {span} ({r}) runs out ~{d}',
  {span,r:rateText(f.rate),d:dayMon(f.day,info.m)})+idle;
 if(f.kind==='projection')return tr('average over {span} ({r}): by {end} ~{p} {unit}',{span,r:rateText(f.rate),end:dayMon(info.days,info.m),p:gibs(f.projected),unit:UNIT()})+idle;
 return'';
}
function niceMax(v){
 const g=(+v||0)/GIB;
 const steps=[1,2,5,10,20,25,50,100,200,250,500,1000,2000,5000];
 for(let i=0;i<steps.length;i++)if(g<=steps[i])return steps[i];
 return Math.ceil(g/1000)*1000;
}
/* Usage page rows for the client table: on the entry a client's rx is what the server got from
   the device (its upload), tx is what the device received. Name → pubkey via the live peers. */
function clientRows(clients,peers){
 const byName=new Map((peers||[]).map(p=>[p.name,p.pubkey]));
 return(Array.isArray(clients)?clients:[]).map(c=>{
  const up=+c.rx||0,down=+c.tx||0;
  return{name:String(c.name||''),pubkey:c.pubkey||byName.get(c.name)||'',down,up,total:up+down};
 }).sort((a,b)=>b.total-a.total);
}
function exitSwitches(events,info){
 return(Array.isArray(events)?events:[]).filter(e=>e&&e.kind==='exit_switch'&&+e.ts>=info.start&&+e.ts<info.end)
  .map(e=>({id:e.id,ts:+e.ts,day:new Date(e.ts*1000).getDate(),from:XL(e.data&&e.data.source),to:XL(e.data&&e.data.target),reason:e.data&&e.data.reason}));
}
const USAGE_ROWS=8;
let _u={month:null,cache:{},switches:null,expanded:false,tok:0};
let _usageUpd=null;
function loadMonth(key,force){
 const c=_u.cache[key];
 if(c&&c.loading)return c.loading;
 if(c&&c.data&&!force&&Date.now()-c.at<60000)return Promise.resolve();
 const entry=_u.cache[key]=Object.assign({data:null,err:null,at:0},c||{});
 entry.loading=WG.api('/api/history?month='+encodeURIComponent(key)).then(d=>{entry.data=d&&typeof d==='object'?d:{};entry.err=null;entry.at=Date.now()},
  e=>{entry.err=e||new Error('failed')}).then(()=>{entry.loading=null});
 return entry.loading;
}
function loadSwitches(){
 if(_u.switches)return Promise.resolve();
 return WG.api('/api/events?kind=exit_switch&limit=100').then(d=>{_u.switches=Array.isArray(d&&d.events)?d.events:[]},()=>{});
}
function monthNav(info,cur){
 const prev=shiftMonth(info.key,-1),next=shiftMonth(info.key,1),nextOff=next>cur;
 const nm=k=>MONTH_NOM[LANG()][+k.slice(5,7)-1];
 return'<div class="seg us-months" role="group" aria-label="'+esc(tr('Month'))+'">'
  +'<button type="button" class="seg-b" data-act="us-month" data-m="'+prev+'" aria-label="'+esc(tr('Previous month'))+'">← <span class="d-only">'+esc(nm(prev))+'</span></button>'
  +'<button type="button" class="seg-b" aria-pressed="true" data-act="us-month" data-m="'+info.key+'">'+esc(nm(info.key))+'</button>'
  +'<button type="button" class="seg-b" data-act="us-month" data-m="'+next+'"'+(nextOff?' disabled':'')+' aria-label="'+esc(tr('Next month'))+'"><span class="d-only">'+esc(nm(next))+'</span> →</button></div>';
}
function cardsHTML(data,info,s){
 const pol=(s.exit_policy&&s.exit_policy.exits)||{},em=data.exits_month||{},series=daySeries(data.exits_daily,info);
 let rx=0,tx=0,h='';
 WG.EXITS.forEach(k=>{
  const used=(+(em[k]&&em[k].rx)||0)+(+(em[k]&&em[k].tx)||0),quota=+(pol[k]&&pol[k].quota)||0,clients=pol[k]?+pol[k].clients||0:-1;
  rx+=+(em[k]&&em[k].rx)||0;tx+=+(em[k]&&em[k].tx)||0;
  const ratio=quota>0?used/quota:0,tone=ratio>=1?'bad':ratio>=.7?'warn':'';
  const o={key:k,used,quota,clients,info,series:series.map(d=>d[k])},f=forecast(o);
  h+='<div class="us-card is-'+k+(tone?' is-'+tone:'')+'"><div class="us-ch"><span class="label"><i class="us-sw is-'+k+'" aria-hidden="true"></i>'+XL(k)+' · '+esc(WG.exitCity(k))+'</span>'
   +'<span class="us-quota">'+esc(quota?tr('quota {q} {unit}',{q:gibs(quota),unit:UNIT()}):s.loaded?tr('no quota set'):'')+'</span></div>'
   +'<div class="us-fig"><span class="us-num">'+gibs(used)+'</span><span class="us-unit">'+UNIT()+(quota?' · '+Math.floor(ratio*100)+'%':'')+'</span></div>'
   +(quota?'<div class="us-meter" role="meter" aria-valuemin="0" aria-valuemax="'+Math.round(quota/GIB)+'" aria-valuenow="'+Math.round(used/GIB)+'" aria-label="'+esc(XL(k))+'">'
    +'<i style="width:'+Math.min(100,ratio*100).toFixed(1)+'%"></i></div>':'')
   +'<p class="us-fc">'+esc(forecastText(f,o))+'</p></div>';
 });
 const total=rx+tx,span=info.current?info.elapsed:info.days;
 h+='<div class="us-card is-total"><div class="us-ch"><span class="label">'+esc(tr('Through the exits this month'))+'</span></div>'
  +'<div class="us-fig"><span class="us-num">'+gibs(total)+'</span><span class="us-unit">'+UNIT()+'</span></div>'
  +'<p class="us-dir">↓ '+esc(gibs(rx)+' '+UNIT())+' · ↑ '+esc(gibs(tx)+' '+UNIT())+'</p>'
  +(span>0?'<p class="us-fc">'+esc(tr('on average {r} a day',{r:gibs(total/span)+' '+UNIT()}))+'</p>':'')+'</div>';
 return h;
}
function chartHTML(data,info){
 const series=daySeries(data.exits_daily,info),N=info.days,H=200;
 const top=niceMax(Math.max.apply(null,[0].concat(series.map(d=>d.nl+d.us))))*GIB,sc=v=>v/top*(H-4);
 const sw=exitSwitches(_u.switches,info);
 let svg='';
 for(let i=1;i<=4;i++){const y=(H-(H-4)*i/4).toFixed(1);svg+='<line class="uc-grid" x1="0" x2="'+N*10+'" y1="'+y+'" y2="'+y+'"/>'}
 series.forEach((d,i)=>{
  const x=i*10+1.5,future=info.current?d.day>info.today:info.future;
  if(future||!d.has){svg+='<rect class="uc-fut" x="'+x+'" y="'+(H-3)+'" width="7" height="3"/>';return}
  const hu=sc(d.us),hn=sc(d.nl);
  svg+='<g><title>'+esc(dayMon(d.day,info.m)+': NL '+gibs(d.nl)+' '+UNIT()+', US '+gibs(d.us)+' '+UNIT())+'</title>'
   +(hu>0?'<rect class="uc-us" x="'+x+'" y="'+(H-hu).toFixed(1)+'" width="7" height="'+hu.toFixed(1)+'"/>':'')
   +(hn>0?'<rect class="uc-nl" x="'+x+'" y="'+(H-hu-hn).toFixed(1)+'" width="7" height="'+hn.toFixed(1)+'"/>':'')+'</g>';
 });
 sw.forEach(e=>{const x=(e.day-1)*10+5;svg+='<line class="uc-sw" x1="'+x+'" x2="'+x+'" y1="0" y2="'+H+'"><title>'+esc(dayMon(e.day,info.m))+'</title></line>'});
 svg+='<line class="uc-base" x1="0" x2="'+N*10+'" y1="'+H+'" y2="'+H+'"/>';
 const last=sw[0];
 const swLabel=last?tr('{d} · {what}',{d:dayMon(last.day,info.m),what:tr(last.reason==='health'||last.reason==='quota'?'automatic switch {from} → {to}':'switch {from} → {to}',{from:last.from,to:last.to})}):'';
 let labels='';
 series.forEach(d=>{
  const today=info.current&&d.day===info.today,show=d.day===1||d.day%5===1||today||d.day===N;
  labels+='<span class="'+(today?'is-today':'')+(show&&!today&&d.day%10!==1&&d.day!==N?' is-minor':'')+'">'+(show?d.day:'')+'</span>';
 });
 const rows=series.filter(d=>d.has).map(d=>'<tr><th scope="row">'+esc(dayMon(d.day,info.m))+'</th><td>'+esc(WG.fmtBytes(d.nl))+'</td><td>'+esc(WG.fmtBytes(d.us))+'</td><td>'+esc(WG.fmtBytes(d.nl+d.us))+'</td></tr>').join('');
 return'<div class="sec-h"><h2 class="sec-t">'+esc(tr('By day'))+'</h2><ul class="uc-legend">'
  +'<li><i class="us-sw is-nl" aria-hidden="true"></i>NL</li><li><i class="us-sw is-us" aria-hidden="true"></i>US</li>'
  +(swLabel?'<li class="uc-lg-sw"><i aria-hidden="true"></i>'+esc(swLabel)+'</li>':'')
  +'<li class="uc-scale">'+esc(tr('scale 0–{m} {unit}',{m:top/GIB,unit:UNIT()}))+'</li>'
  +'<li><button type="button" class="linkbtn uc-csv" data-act="us-day-csv" aria-label="'+esc(tr('Download the daily table as CSV'))+'">↓ CSV</button></li></ul></div>'
  +'<div class="uc"><svg class="uc-svg" viewBox="0 0 '+N*10+' '+H+'" preserveAspectRatio="none" aria-hidden="true" focusable="false">'+svg+'</svg>'
  +'<div class="uc-x" aria-hidden="true" style="grid-template-columns:repeat('+N+',minmax(0,1fr))">'+labels+'</div>'
  +'<table class="sr-only"><caption>'+esc(tr('Usage by day through the exits, {month}',{month:monthPhrase(info)}))+'</caption>'
  +'<thead><tr><th scope="col">'+esc(tr('Day'))+'</th><th scope="col">NL</th><th scope="col">US</th><th scope="col">'+esc(tr('Total'))+'</th></tr></thead>'
  +'<tbody>'+rows+'</tbody></table></div>';
}
function clientsHTML(data,s){
 const rows=clientRows(data.clients,s.peers);
 if(!rows.length)return'';
 const max=Math.max.apply(null,rows.map(r=>r.total))||1,shown=_u.expanded?rows:rows.slice(0,USAGE_ROWS),rest=rows.length-shown.length;
 const row=r=>{
  const name=r.pubkey?'<button type="button" class="linkbtn uc-name" data-act="us-client" data-pk="'+esc(r.pubkey)+'" aria-label="'+esc(tr('Open the usage of {name}',{name:r.name}))+'">'+esc(r.name)+'</button>'
   :'<span class="uc-name is-gone">'+esc(r.name)+' <span class="uc-gone">'+esc(tr('deleted'))+'</span></span>';
  return'<div class="ut-row" role="row"><span role="cell" class="ut-n">'+name+'</span>'
   +'<span role="cell" class="ut-bar" aria-hidden="true"><i class="is-down" style="width:'+(r.down/max*100).toFixed(1)+'%"></i><i class="is-up" style="width:'+(r.up/max*100).toFixed(1)+'%"></i></span>'
   +'<span role="cell" class="ut-d">'+esc(WG.fmtBytes(r.down))+'</span><span role="cell" class="ut-u">'+esc(WG.fmtBytes(r.up))+'</span>'
   +'<span role="cell" class="ut-t">'+esc(WG.fmtBytes(r.total))+'</span></div>';
 };
 return'<div class="sec-h"><h2 class="sec-t" id="ut-t">'+esc(tr('By client'))+'</h2><span class="sec-note">'+esc(tr('client traffic at the entry for the month, RU direct included'))+'</span></div>'
  +'<div class="ut" role="table" aria-labelledby="ut-t"><div class="ut-row ut-head" role="row"><span role="columnheader">'+esc(tr('Client'))+'</span>'
  +'<span role="columnheader" class="ut-bar">'+esc(tr('Usage'))+', '+UNIT()+'</span><span role="columnheader" class="ut-d">'+esc(tr('↓ Received'))+'</span>'
  +'<span role="columnheader" class="ut-u">'+esc(tr('↑ Sent'))+'</span><span role="columnheader" class="ut-t">'+esc(tr('Total'))+'</span></div>'
  +shown.map(row).join('')+'</div>'
  +'<div class="ut-foot">'+(rest>0?'<button type="button" class="linkbtn ut-more" data-act="us-more">'+esc(tr('+ {n} more ↓',{n:WG.count(rest,'client')}))+'</button>'
   :rows.length>USAGE_ROWS?'<button type="button" class="linkbtn ut-more" data-act="us-more">'+esc(tr('Show less ↑'))+'</button>':'<span></span>')
  +'<button type="button" class="linkbtn ut-csv" data-act="us-csv" aria-label="'+esc(tr('Download the client table as CSV'))+'">↓ CSV</button></div>';
}
function usageBodyHTML(entry,info,s){
 const data=entry&&entry.data;
 if(!data){
  if(entry&&entry.err)return msgHTML(errText(entry.err,'The usage database is unavailable.','Could not load the usage.'),'us-retry');
  return'<p class="pg-loading">'+esc(tr('Loading…'))+'</p>';
 }
 const series=daySeries(data.exits_daily,info),em=data.exits_month||{};
 const anyExit=series.some(d=>d.has)||WG.EXITS.some(k=>(+(em[k]&&em[k].rx)||0)+(+(em[k]&&em[k].tx)||0)>0);
 const clients=Array.isArray(data.clients)&&data.clients.length;
 let h=entry.err?'<p class="pg-warn">'+esc(tr('Showing the data loaded at {t}.',{t:WG.fmtTime(Math.round(entry.at/1000))}))+'</p>':'';
 if(!anyExit&&!clients)return h+msgHTML(tr('No traffic in {month}.',{month:monthPhrase(info)}),null,
  info.current?'':tr('The panel keeps daily usage for a limited time; older months may be empty.'));
 h+='<section class="us-cards">'+cardsHTML(data,info,s)+'</section>';
 h+='<section class="us-chart">'+chartHTML(data,info)+'</section>';
 h+='<section class="us-clients">'+clientsHTML(data,s)+'</section>';
 return h;
}
function renderUsage(el,ctx){
 const cur=monthKey(nowTs());
 if(!_u.month||_u.month>cur)_u.month=cur;
 el.innerHTML='<div class="pg us"><div class="us-head"></div><div class="us-body"></div></div>';
 const set=patcher(),head=el.querySelector('.us-head'),body=el.querySelector('.us-body');
 const upd=()=>{
  if(el.isConnected===false)return;
  const now=nowTs(),info=monthInfo(_u.month,now);
  set('h',head,pageHead(tr('Traffic usage'),monthTitle(info),monthNav(info,monthKey(now))));
  set('b',body,usageBodyHTML(_u.cache[_u.month],info,WG.state));
 };
 _usageUpd=upd;
 const load=force=>{const p=loadMonth(_u.month,force);upd();return p.then(upd)};
 _u.load=load;
 ctx.on('status',upd);
 let sec=0;
 ctx.on('second',()=>{if(++sec%60===0&&_u.month===monthKey(nowTs()))load(true)});
 _u.switches=null;
 loadSwitches().then(upd);
 load(false);
}
WG.delegate('us-month',el=>{
 const m=el.getAttribute('data-m'),cur=monthKey(nowTs());
 if(!/^\d{4}-\d{2}$/.test(m||'')||m>cur||m===_u.month)return;
 _u.month=m;_u.expanded=false;
 if(_u.load)_u.load(false);
});
WG.delegate('us-retry',()=>{if(_u.load)_u.load(true)});
WG.delegate('us-more',()=>{_u.expanded=!_u.expanded;if(_usageUpd)_usageUpd()});
WG.delegate('us-client',el=>{const pk=el.getAttribute('data-pk');if(pk)WG.actions.showConfig(pk,{section:'history'})});
WG.delegate('us-csv',()=>{
 const e=_u.cache[_u.month];if(!e||!e.data)return;
 const rows=clientRows(e.data.clients,WG.state.peers);
 download('wg-usage-clients-'+_u.month+'.csv',toCSV([['client','received_bytes','sent_bytes','total_bytes']].concat(rows.map(r=>[r.name,r.down,r.up,r.total]))));
});
WG.delegate('us-day-csv',()=>{
 const e=_u.cache[_u.month];if(!e||!e.data)return;
 const info=monthInfo(_u.month,nowTs());
 const rows=daySeries(e.data.exits_daily,info).filter(d=>d.has);
 download('wg-usage-days-'+_u.month+'.csv',toCSV([['day','nl_bytes','us_bytes','total_bytes']].concat(rows.map(d=>[_u.month+'-'+pad(d.day),d.nl,d.us,d.nl+d.us]))));
});

/* ================================================================ journal (B2) */
const J_FILTERS=['all','exits','clients','access'];
const J_LABEL={all:'All',exits:'Exits',clients:'Clients',access:'Access'};
const J_KINDS={all:'',exits:'health,exit_switch,admin',clients:'admin',access:'login,logout_all,admin'};
const EXIT_OPS=['setexitall','revertswitch','setexitpolicy','splitsave','splitserver'];
const ADMIN_TAG={export:'Backup',setexitall:'Switch',revertswitch:'Switch',setexitpolicy:'Settings',splitsave:'Settings',splitserver:'Settings'};
function eventOp(ev){return String((ev.data&&ev.data.op)||ev.subject||'')}
function eventCat(ev){
 if(ev.kind==='health'||ev.kind==='exit_switch')return'exits';
 if(ev.kind==='login'||ev.kind==='logout_all')return'access';
 const op=eventOp(ev);
 if(EXIT_OPS.indexOf(op)>=0)return'exits';
 if(op==='export')return'access';
 return'clients';
}
function shortKey(pk){return pk?tr('key {k}',{k:String(pk).slice(0,8)+'…'}):tr('a client')}
function opWhat(op,d,name){
 const E=XL(d.exit);
 switch(op){
  case'add':return tr('creating {name}',{name});
  case'rename':return tr('renaming to {name}',{name});
  case'enabled':return tr(d.enabled?'turning on {name}':'turning off {name}',{name});
  case'delete':return tr('deleting {name}',{name});
  case'setexpiry':return tr('changing the expiry of {name}',{name});
  case'setexit':return tr('moving {name} to {exit}',{name,exit:E});
  case'setexitall':return tr('moving everyone to {exit}',{exit:E});
  case'revertswitch':return tr('moving clients back');
  case'setexitpolicy':return tr('exit settings');
  case'splitsave':return tr('split tunnel list');
  case'splitserver':return tr('split tunnel switch');
  case'export':return tr('config backup');
  default:return op;
 }
}
function failDetail(d){
 if(d.busy===true||d.error==='busy')return tr('another operation was running');
 if(d.committed==='unknown'||d.timeout||d.error==='timeout')return tr('the server did not answer in time — check the state');
 if(d.code)return lcFirst(noDot(WG.reasonText(d.code)));
 if(d.error==='wrong password')return tr('wrong password');
 return tr('the server refused the request');
}
function memberList(members){
 const names=(members||[]).map(m=>m&&m.name).filter(Boolean);
 if(!names.length)return'';
 return names.slice(0,6).join(', ')+(names.length>6?' '+tr('and {n} more',{n:names.length-6}):'');
}
/* One journal event → what a person reads. ctx: {peerName(pk), revertedAt(id) → ts|0, eventTs(id) → ts|0, now} */
function eventView(ev,ctx){
 ctx=ctx||{};
 const d=(ev&&ev.data&&typeof ev.data==='object')?ev.data:{},kind=ev.kind,now=ctx.now||nowTs();
 const peerName=pk=>(ctx.peerName&&pk&&ctx.peerName(pk))||'';
 const who=ev.actor==='system'?tr('system'):[ev.actor,ev.ip].filter(Boolean).join(' · ');
 const v={id:ev.id,ts:+ev.ts||0,kind,cat:eventCat(ev),tag:'',tone:'u',title:'',detail:'',who,revert:null,hide:false,hot:false};
 if(kind==='admin'){
  const op=eventOp(ev),name=d.name||peerName(d.pubkey)||shortKey(d.pubkey),E=XL(d.exit);
  v.tag=tr(ADMIN_TAG[op]||'Client');
  if(d.ok===false||d.ok===undefined&&(d.error||d.code)){
   const unknown=d.committed==='unknown'||d.timeout||d.error==='timeout',busy=d.busy===true||d.error==='busy';
   v.title=tr(unknown?'Result unknown: {what}':busy?'Not started: {what}':'Not applied: {what}',{what:opWhat(op,d,name)});
   v.detail=failDetail(d);v.tone=unknown?'warn':'bad';
   return v;
  }
  switch(op){
   case'add':v.title=tr('Client {name} created',{name});v.tone='ok';
    v.detail=[d.exit?tr('exit {exit}',{exit:E}):'',+d.expires?tr('until {d}',{d:WG.fmtDate(+d.expires)}):tr('no expiry')].filter(Boolean).join(' · ');break;
   case'rename':v.title=tr('Renamed to {name}',{name});break;
   case'enabled':v.title=tr(d.enabled?'{name} turned on':'{name} turned off',{name});v.detail=tr(d.enabled?'access restored':'access paused, keys kept');v.tone=d.enabled?'ok':'u';break;
   case'delete':v.title=tr('Client {name} deleted',{name});v.detail=tr('keys and config removed');v.tone='bad';break;
   case'setexpiry':v.title=+d.expires?tr('{name}: access until {d}',{name,d:WG.fmtDate(+d.expires)}):tr('{name}: no expiry now',{name});break;
   case'setexit':v.title=tr('{name} moved to {exit}',{name,exit:E});break;
   case'setexitall':
    if(+d.event_id>0){v.hide=true;break}       /* the exit_switch row tells who moved */
    v.title=tr(+d.changed>0?'Everyone moved to {exit}':'Everyone is already on {exit}',{exit:E});break;
   case'revertswitch':
    if(+d.event_id>0){v.hide=true;break}
    v.title=tr('Nobody left to move back');v.detail=tr('the clients were deleted or moved by hand');break;
   case'setexitpolicy':v.title=tr('Exit settings changed');v.detail=tr('quotas and automatic switching');break;
   case'splitsave':v.title=tr('Split tunnel list saved');
    v.detail=[d.entries!=null?plural(+d.entries||0,P_ENTRIES):'',d.refresh?tr('RU subnets refreshed'):''].filter(Boolean).join(' · ');break;
   case'splitserver':v.title=tr(d.split?'Split tunnel turned on':'Split tunnel turned off');v.detail=tr(d.split?'RU sites go straight from the entry':'all traffic goes through the exits');break;
   case'export':v.title=tr('Config backup downloaded');v.detail=tr('the archive holds every private key');v.tone='warn';break;
   default:v.title=tr('Operation {op}',{op});
  }
  return v;
 }
 if(kind==='health'){
  const E=XL(d.exit||ev.subject);
  v.tag=tr('Exit');
  if(d.to==='down'){
   v.title=tr('{exit} stopped answering',{exit:E});v.tone='bad';
   v.detail=d.from==='unknown'?tr('it was down right after the panel started'):plural(+d.fails||FAIL_PROBES,P_FAILS_ROW);
  }else{
   v.title=tr('{exit} passes its checks again',{exit:E});v.tone='ok';
   v.detail=plural(+d.oks||2,P_OKS_ROW)+' · '+tr('clients return by hand');
  }
  return v;
 }
 if(kind==='exit_switch'){
  const from=XL(d.source),to=XL(d.target),members=Array.isArray(d.members)?d.members:[],n=+d.changed||members.length;
  v.tag=tr('Switch');v.tone='warn';
  v.title=plural(n,P_MOVED).replace('{from}',from).replace('{to}',to);
  const reason=d.reason==='health'?tr('{from} failed its checks',{from}):d.reason==='quota'?tr('the {from} quota ran out',{from})
   :d.reason==='revert'?(ctx.eventTs&&ctx.eventTs(+d.revert_of)?tr('back after the switch at {t}',{t:WG.fmtTime(ctx.eventTs(+d.revert_of))}):tr('back after an earlier switch'))
   :tr('by hand');
  const parts=[memberList(members),reason];
  if(d.reason==='health'&&now<v.ts+HEALTH_COOLDOWN)parts.push(tr('next automatic switch not before {t}',{t:WG.fmtTime(v.ts+HEALTH_COOLDOWN)}));
  const back=ctx.revertedAt?ctx.revertedAt(+ev.id):0;
  if(back)parts.push(tr('moved back at {t}',{t:WG.fmtTime(back)}));
  v.detail=parts.filter(Boolean).join(' · ');
  if(members.length&&!d.revert_of&&!back&&WG.EXITS.indexOf(d.source)>=0){v.revert={id:+ev.id,n:members.length,exit:from};v.hot=true}
  return v;
 }
 if(kind==='login'){
  v.tag=tr('Sign-in');
  if(d.ok){v.title=tr('Signed in to the panel');return v}
  v.tone='bad';v.who=tr('protection');v.loginFail=true;v.count=1;v.throttled=d.reason==='throttled';
  if(d.reason==='session_gen'){v.title=tr('Sign-in failed on the server');v.detail=tr('could not create a session');v.loginFail=false;return v}
  v.title=tr('Failed sign-in attempt');
  v.detail=[ev.ip?tr('from {ip}',{ip:ev.ip}):'',v.throttled?tr('sign-in from this address is blocked for a while'):''].filter(Boolean).join(' · ');
  return v;
 }
 if(kind==='logout_all'){v.tag=tr('Access');v.title=tr('Signed out on all devices');v.detail=tr('every session ended');return v}
 v.title=String(kind||'');
 return v;
}
function dayKey(ts){const d=new Date(ts*1000);return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())}
/* Failed sign-ins in a row from one address on one day fold into a single row. */
function collapseLogins(views){
 const out=[];
 views.forEach(v=>{
  const last=out[out.length-1];
  if(v.loginFail&&last&&last.loginFail&&last.ip===v.ip&&dayKey(last.ts)===dayKey(v.ts)){
   last.count++;last.throttled=last.throttled||v.throttled;last.first=v.ts;
   last.title=plural(last.count,P_LOGIN_FAILS);
   last.detail=[last.ip?tr('from {ip}',{ip:last.ip}):'',last.throttled?tr('sign-in from this address is blocked for a while'):''].filter(Boolean).join(' · ');
   return;
  }
  out.push(v);
 });
 return out;
}
function dayLabel(ts,now){
 const d=new Date(ts*1000),k=dayKey(ts),today=dayKey(now),yest=dayKey(now-DAY);
 const long=LANG()==='en'?MONTH_NOM.en[d.getMonth()]+' '+d.getDate():d.getDate()+' '+MONTH_GEN.ru[d.getMonth()];
 const y=d.getFullYear()!==new Date(now*1000).getFullYear()?' '+d.getFullYear():'';
 return k===today?tr('Today')+' · '+long:k===yest?tr('Yesterday')+' · '+long:long+y;
}
function groupByDay(views,now){
 const groups=[];
 views.forEach(v=>{
  const k=dayKey(v.ts),g=groups[groups.length-1];
  if(g&&g.key===k)g.items.push(v);else groups.push({key:k,label:dayLabel(v.ts,now),items:[v]});
 });
 return groups;
}
/* Whole pipeline: raw events (newest first) → visible views for a filter. */
function journalViews(events,filter,opts){
 opts=opts||{};
 const list=Array.isArray(events)?events:[],byId=new Map(list.map(e=>[+e.id,e])),revertedAt=new Map();
 list.forEach(e=>{
  const d=e&&e.data||{};
  if(e.kind==='exit_switch'&&+d.revert_of>0)revertedAt.set(+d.revert_of,+e.ts);
  if(e.kind==='admin'&&eventOp(e)==='revertswitch'&&d.ok&&+d.revert_of>0&&!revertedAt.has(+d.revert_of))revertedAt.set(+d.revert_of,+e.ts);
 });
 const ls=opts.lastSwitch;
 if(ls&&+ls.revert_of>0&&!revertedAt.has(+ls.revert_of))revertedAt.set(+ls.revert_of,+ls.ts||1);
 const ctx={now:opts.now,peerName:opts.peerName,revertedAt:id=>revertedAt.get(id)||0,eventTs:id=>{const e=byId.get(id);return e?+e.ts:0}};
 const views=list.map(e=>Object.assign(eventView(e,ctx),{ip:e.ip||''})).filter(v=>!v.hide&&(filter==='all'||!filter||v.cat===filter));
 return collapseLogins(views);
}
let _j={filter:'all',events:[],next:null,err:null,loading:false,tok:0,at:0};
let _journalUpd=null;
function jLoad(more){
 const tok=++_j.tok,f=_j.filter,kinds=J_KINDS[f];
 _j.loading=true;_j.err=null;
 if(_journalUpd)_journalUpd();
 const url='/api/events?limit=50'+(kinds?'&kind='+kinds:'')+(more&&_j.next?'&before='+_j.next:'');
 return WG.api(url).then(d=>{
  if(tok!==_j.tok)return;
  const evs=Array.isArray(d&&d.events)?d.events:[];
  _j.events=more?_j.events.concat(evs):evs;_j.next=d&&d.next_before||null;_j.at=Date.now();
 },e=>{if(tok===_j.tok)_j.err=e||new Error('failed')}).then(()=>{
  if(tok!==_j.tok)return;
  _j.loading=false;
  /* a filter that drops most rows (admin ops of one kind) must not leave a near-empty page */
  if(!_j.err&&_j.next&&visibleJournal().length<12&&(_j.auto=(_j.auto||0)+1)<=4)return jLoad(true);
  _j.auto=0;
  if(_journalUpd)_journalUpd();
 });
}
/* New events since the last load are merged on top (every 30 s while the page is open). */
function jRefreshTop(){
 if(_j.loading||!_j.events.length)return Promise.resolve();
 const f=_j.filter,kinds=J_KINDS[f],tok=_j.tok,maxId=Math.max.apply(null,_j.events.map(e=>+e.id||0));
 return WG.api('/api/events?limit=50'+(kinds?'&kind='+kinds:'')).then(d=>{
  if(tok!==_j.tok||f!==_j.filter)return;
  const evs=Array.isArray(d&&d.events)?d.events:[];
  const fresh=evs.filter(e=>+e.id>maxId);
  if(!fresh.length)return;
  if(evs.length&&Math.min.apply(null,evs.map(e=>+e.id))>maxId){_j.events=evs;_j.next=d.next_before||null}
  else _j.events=fresh.concat(_j.events);
  _j.at=Date.now();
  if(_journalUpd)_journalUpd();
 },()=>{});
}
function visibleJournal(){
 const s=WG.state;
 return journalViews(_j.events,_j.filter,{now:nowTs(s),lastSwitch:s.exit_policy&&s.exit_policy.last_switch,peerName:pk=>{const p=WG.peer(pk);return p?p.name:''}});
}
function journalRowHTML(v){
 const off=WG.unknown();
 return'<li class="jr-row'+(v.hot?' is-hot':'')+'"><time class="jr-t" datetime="'+esc(new Date(v.ts*1000).toISOString())+'">'+esc(WG.fmtTime(v.ts))+'</time>'
  +'<span class="jr-tagw"><span class="tag jr-tag is-'+v.tone+'">'+esc(v.tag)+'</span></span>'
  +'<div class="jr-main"><p class="jr-title">'+esc(v.title)+'</p>'+(v.detail?'<p class="jr-detail">'+esc(v.detail)+'</p>':'')+'</div>'
  +'<div class="jr-side">'+(v.revert?'<button type="button" class="jr-revert" data-act="jr-revert" data-id="'+v.revert.id+'" data-live'+(off?' disabled':'')
   +' aria-label="'+esc(tr('Move these clients back'))+': '+esc(v.title)+'">'+esc(tr('Move {n} back →',{n:v.revert.n}))+'</button>':'')
  +(v.who?'<span class="jr-who">'+esc(v.who)+'</span>':'')+'</div></li>';
}
function journalBodyHTML(){
 const views=visibleJournal();
 if(!_j.events.length||!views.length&&!_j.next){
  if(_j.err)return msgHTML(errText(_j.err,'The journal is unavailable.','Could not load the journal.'),'jr-retry');
  if(_j.loading)return'<p class="pg-loading">'+esc(tr('Loading…'))+'</p>';
  return msgHTML(tr(_j.filter==='all'?'No events yet.':'No events of this type.'));
 }
 const groups=groupByDay(views,nowTs());
 let h=groups.map(g=>'<section class="jr-day" aria-label="'+esc(g.label)+'"><h2 class="jr-dh">'+esc(g.label)+'</h2><ul class="jr-list">'
  +g.items.map(journalRowHTML).join('')+'</ul></section>').join('');
 h+='<div class="jr-foot">';
 if(_j.err)h+=msgHTML(errText(_j.err,'The journal is unavailable.','Could not load the journal.'),'jr-retry');
 else if(_j.next)h+='<button type="button" class="btn btn-outline" data-act="jr-more"'+(_j.loading?' disabled':'')+'>'+esc(_j.loading?tr('Loading…'):tr('Show more'))+'</button>';
 else h+='<p class="jr-end">'+esc(tr('That is the whole journal.'))+'</p>';
 return h+'</div>';
}
function journalTools(){
 return'<div class="seg jr-filter" role="group" aria-label="'+esc(tr('Event type'))+'">'
  +J_FILTERS.map(f=>'<button type="button" class="seg-b" data-act="jr-filter" data-f="'+f+'" aria-pressed="'+(f===_j.filter)+'">'+esc(tr(J_LABEL[f]))+'</button>').join('')+'</div>'
  +'<button type="button" class="btn btn-sm btn-outline jr-export" data-act="jr-export" aria-label="'+esc(tr('Download the loaded events as CSV'))+'">'+icon('download',14)+esc(tr('Export'))+'</button>';
}
function renderJournal(el,ctx){
 el.innerHTML='<div class="pg jr"><div class="jr-head"></div><div class="jr-body" aria-live="polite" aria-busy="false"></div></div>';
 const set=patcher(),head=el.querySelector('.jr-head'),body=el.querySelector('.jr-body');
 const upd=()=>{
  if(el.isConnected===false)return;
  set('h',head,pageHead(tr('Event journal'),tr('What happened'),journalTools()));
  set('b',body,journalBodyHTML());
  body.setAttribute('aria-busy',String(!!_j.loading));
 };
 _journalUpd=upd;
 ctx.on('status',upd);
 let sec=0;
 ctx.on('second',()=>{if(++sec%30===0)jRefreshTop()});
 upd();
 jLoad(false);
}
WG.delegate('jr-filter',el=>{
 const f=el.getAttribute('data-f');
 if(J_FILTERS.indexOf(f)<0||f===_j.filter)return;
 _j.filter=f;_j.events=[];_j.next=null;_j.auto=0;
 jLoad(false);
});
WG.delegate('jr-more',()=>{if(!_j.loading&&_j.next){_j.auto=0;jLoad(true)}});
WG.delegate('jr-retry',()=>jLoad(!!_j.events.length&&!!_j.next));
WG.delegate('jr-revert',el=>{const id=+el.getAttribute('data-id');if(id>0)WG.actions.revertSwitch(id)});
WG.delegate('jr-export',()=>{
 const rows=visibleJournal();
 download('wg-journal-'+dayKey(nowTs())+'.csv',toCSV([['time','type','event','details','who']].concat(rows.map(v=>[isoMinute(v.ts),v.tag,v.title,v.detail,v.who]))));
});

/* ================================================================ split */
let _prevRoute=null;
WG.on('route',name=>{_prevRoute=name});
function splitHTML(s){
 const m=mode(s),u=isUnknownMode(m),on=!!s.rud,off=WG.unknown();
 const state=u?['u',tr('State unknown: no fresh data.')]:on?['ok',tr('On: RU subnets leave straight from the entry with a Russian IP.')]:['off',tr('Off: all traffic goes through the NL and US exits.')];
 return pageHead(tr('Split tunnel'),tr('RU sites directly'),'<button type="button" class="btn btn-primary" data-act="sp-open" data-live'+(off?' disabled':'')+'>'+icon('split',16)+esc(tr('Configure split'))+'</button>')
  +'<section class="sp-state is-'+state[0]+'"><span class="dot is-'+(state[0]==='ok'?'on':state[0]==='u'?'u':'off')+'" aria-hidden="true"></span><p>'+esc(state[1])+'</p></section>'
  +'<section class="sp-how"><p class="prose">'+esc(tr('Banks, government services and other Russian sites often refuse foreign IPs. With the split on, the entry sends traffic to RU subnets straight to the internet, so those sites see a Russian address, while everything else goes through the exit.'))+'</p>'
  +'<p class="prose muted">'+esc(tr('The list of subnets and the server switch live in the split settings window.'))+'</p></section>';
}
function renderSplit(el,ctx){
 el.innerHTML='<div class="pg sp"></div>';
 const box=el.firstChild,set=patcher();
 const upd=()=>{if(el.isConnected!==false)set('s',box,splitHTML(WG.state))};
 ctx.on('status',upd);
 upd();
 /* opened from the navigation: go straight to the settings window (not on a cold load of #/split) */
 if(_prevRoute&&_prevRoute!=='split'&&!WG.unknown())setTimeout(()=>{if(el.isConnected!==false&&WG.router.current()==='split'&&!WG.unknown())WG.actions.splitSettings()},0);
}
WG.delegate('sp-open',()=>WG.actions.splitSettings());

/* ================================================================ routes */
WG.router.register('exits',{title:tr('Exits'),icon:'exits',mobileTab:true,render:renderExits,leave(){_exitsUpd=null}});
WG.router.register('split',{title:tr('Split'),icon:'split',render:renderSplit});
WG.router.register('usage',{title:tr('Usage'),icon:'usage',mobileTab:true,render:renderUsage,leave(){_usageUpd=null;_u.load=null}});
WG.router.register('journal',{title:tr('Journal'),icon:'journal',render:renderJournal,leave(){_journalUpd=null}});

WG.pages={diagramModel,situation,healthCells,healthSummary,protectionText,monthKey,shiftMonth,monthInfo,daySeries,forecast,forecastText,
 niceMax,clientRows,exitSwitches,toCSV,csvCell,eventCat,eventView,collapseLogins,groupByDay,dayLabel,journalViews,wireWidth};
})();
