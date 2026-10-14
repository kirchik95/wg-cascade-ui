/* Windows of the Tablo Light UI (stage 2B) — the real WG.actions:
 *  addClient      C1 → C2 (E2 on a phone): name check with a transliteration hint, exit
 *                 cards with their state, access term; then QR, .conf, copy, share.
 *  showConfig     C2 for an existing client, plus its history (daily traffic, connections).
 *  editClient     C5: name, term (keep / +7 / +30 / no expiry, counted from the current
 *                 term), exit. Changes run as one operation of up to three steps.
 *  toggleEnabled  at once; turning off offers «Отменить» in the operations strip for 10 s.
 *  deleteClient   C6: type the name to confirm; «Выключить вместо».
 *  switchExit     confirmation with the target's state; the server checks the target again.
 *  exitsSettings  C3: quotas, switches, 24 h of health checks, the last switch, «Всех на …» (C6).
 *  revertSwitch   C6: the journaled group — who returns, who is skipped and why.
 *  splitSettings  C4: the switch is a draft, lines are checked one by one, apply = two steps.
 *  backup         E4: password, the archive, share / download.
 * Long operations go through WG.ops.run: a window shows only the elapsed time, may be closed,
 * and the outcome stays in the operations strip (D1). Pure helpers: WG.modalKit (tests). */
(function(){
'use strict';
const root=typeof globalThis!=='undefined'?globalThis:window;
const WG=root.WG;
const {tr,esc,icon}=WG;

WG.addStrings('ru',{
 'Step 1 of 2':'Шаг 1 из 2','Step 2 of 2 · created':'Шаг 2 из 2 · создан','New client':'Новый клиент',
 'Name':'Имя','Exit':'Выход','Access term':'Срок доступа','No expiry':'Бессрочно','Cancel':'Отмена','Close':'Закрыть',
 'Create and show QR':'Создать и показать QR','Creating…':'Создаю…','Saving…':'Сохраняю…','Applying…':'Применяю…',
 'The IP is assigned after creation':'IP назначится после создания',
 'Enter a name':'Введите имя','Fix the name':'Исправьте имя','No connection':'Нет связи','{exit} is unavailable':'{exit} недоступен',
 '{exit} quota is used up':'Квота {exit} исчерпана','{exit} is not checked':'{exit} не проверен',
 'Latin letters, digits, «-» and «_», starting with a letter or a digit':'латиница, цифры, «-» и «_», первый символ — буква или цифра',
 'hint: «{a}» → {b}':'подсказка: «{a}» → {b}',
 'only Latin letters, digits, «-» and «_»':'только латиница, цифры, «-» и «_»',
 'the first character is a letter or a digit':'первый символ — буква или цифра',
 'no longer than {n} characters':'не длиннее {n} символов','«{name}» is already taken':'имя «{name}» уже занято',
 'use: {name}':'подставить: {name}',
 'OK':'ОК','DOWN':'НЕТ ОТВЕТА','QUOTA':'КВОТА',
 'working · {u}/{q} GiB':'работает · {u}/{q} ГиБ','working · {p}% of quota':'работает · {p}% квоты',
 'quota used up · {u}/{q} GiB':'квота исчерпана · {u}/{q} ГиБ','down — the server will refuse':'недоступен — сервер откажет',
 'check failed {n}/3':'проверка не прошла {n}/3','not checked yet':'ещё не проверен','state unknown — the data is old':'состояние неизвестно — данные устарели',
 '{exit} is down: the server will refuse it. Choose the other exit.':'{exit} недоступен — сервер откажет. Выберите другой выход.',
 '{exit} quota is used up: the server will refuse it. Choose the other exit.':'Квота {exit} исчерпана — сервер откажет. Выберите другой выход.',
 'Creating {name}':'Создаю {name}','{name} created':'{name} создан',
 'You can close the window — the result stays in the operations line at the top.':'окно можно закрыть — итог останется в строке операций вверху панели',
 'No connection to the server — nothing was sent.':'Нет связи с сервером — ничего не отправлено.',
 'Wait for fresh data':'Дождитесь свежих данных',
 'Fresh data is required — nothing was sent.':'Нужны свежие данные — ничего не отправлено.',
 'Wait for the current change to finish':'Дождитесь окончания текущего изменения',
 'Check the client list before creating it again.':'Проверьте список клиентов, прежде чем создавать снова.',
 'Config and QR':'Конфиг и QR','History':'История','Client':'Клиент',
 'Install WireGuard on the device':'Установите WireGuard на устройство',
 '«Add tunnel» → «Scan QR code»':'«Добавить туннель» → «Сканировать QR»',
 'Connect — the client row shows the time of the last connection':'Подключитесь — в строке клиента появится время последней связи',
 'exit {exit}':'выход {exit}','no expiry':'бессрочно','until {d}':'до {d}','expired {d}':'истёк {d}',
 'all IPv4 and IPv6 — through the tunnel':'весь IPv4 и IPv6 — через туннель','all IPv4 — through the tunnel':'весь IPv4 — через туннель',
 '{n} networks through the tunnel (split in the config)':'{n} сетей через туннель (сплит в конфиге)',
 'QR code of the {name} config':'QR-код конфига {name}',
 'The config is too big for a QR code — import the .conf file.':'Конфиг не помещается в QR-код — импортируйте файл .conf.',
 'Copy':'Копировать','Copied':'Скопировано','Share':'Поделиться','Done':'Готово',
 'Could not copy — download the .conf instead.':'Не удалось скопировать — скачайте .conf.',
 'Created, but: {m}':'Создан, но: {m}',
 'Loading the config…':'Загружаю конфиг…','Loading the history…':'Загружаю историю…','Retry':'Повторить',
 'The server did not answer. Try again.':'Сервер не ответил. Попробуйте ещё раз.',
 'The server is busy with another operation. Try again in a minute.':'Сервер занят другой операцией. Повторите через минуту.',
 'Could not load the history. Try again later.':'Не удалось загрузить историю. Попробуйте позже.',
 'Traffic by day':'Расход по дням','Connections':'Подключения','No traffic this month yet.':'В этом месяце трафика ещё не было.',
 'No connections recorded yet.':'Подключений пока не записано.','{n} days: {t} · peak {p} ({d})':'за {n} дн.: {t} · пик {p} ({d})',
 'Daily traffic of {name}: {s}':'Расход {name} по дням: {s}','Part of the history did not load.':'Часть истории не загрузилась.',
 'Edit client':'Изменить клиента','Keep':'Оставить','now: {t}':'сейчас: {t}','will be: {t}':'будет: {t}','no change':'без изменений',
 'until {d} ({n})':'до {d} ({n})','Save':'Сохранить','No changes':'Нет изменений',
 'name: {a} → {b}':'имя: {a} → {b}','term: {t}':'срок: {t}','exit: {a} → {b}':'выход: {a} → {b}',
 '{name}: renaming':'{name}: переименовываю','{name}: extending access':'{name}: продлеваю доступ','{name}: changing the term':'{name}: меняю срок',
 '{name}: moving to {exit}':'{name}: перевожу на {exit}','{name}: saving changes':'{name}: сохраняю изменения',
 '{name}: saved':'{name}: сохранено','{name}: access {t}':'{name}: доступ {t}',
 'Client not found':'Клиент не найден',
 'It is not in the list anymore — maybe it was deleted. The list refreshes in a few seconds.':'Его больше нет в списке — возможно, его удалили. Список обновится через несколько секунд.',
 'Turning off {name}':'Выключаю {name}','Turning on {name}':'Включаю {name}','{name} is off':'{name} выключен','{name} is on':'{name} включён',
 'Irreversible':'Необратимо','Delete {name}?':'Удалить {name}?',
 'The client keys are deleted and the device will not connect anymore. Getting it back means a new client and a new QR code.':'Ключи клиента будут удалены, устройство больше не подключится. Вернуть можно только созданием нового клиента и новым QR.',
 'If it is temporary, choose «Turn off» — that can be undone.':'Если нужно временно — выберите «Выключить», это можно отменить.',
 'Type the name to confirm':'Введите имя, чтобы подтвердить','Turn off instead':'Выключить вместо','Delete':'Удалить',
 'Deleting {name}':'Удаляю {name}','{name} deleted':'{name} удалён',
 'Change exit':'Смена выхода','Move {name} to {exit}?':'Перевести {name} на {exit}?','Move to {exit}':'Перевести на {exit}',
 'state of {exit}':'состояние {exit}','quota of {exit}':'квота {exit}','{u} of {q} GiB · {l} left':'{u} из {q} ГиБ · осталось {l}',
 'checked {t}':'проверено {t}','no answer · {t}':'нет ответа · {t}',
 'The device reconnects — a break of a few seconds. The server checks the exit again before the move.':'Устройство переподключится — разрыв на несколько секунд. Перед переводом сервер ещё раз проверит выход.',
 '{name} is already on {exit}.':'{name} уже на {exit}.','{name} → {exit}':'{name} → {exit}','{name} is on {exit} now':'{name} теперь на {exit}',
 'Routing':'Маршрутизация','working':'работает','Exits':'Выходы','Monthly quota':'Квота в месяц','GiB · used {u}':'ГиБ · израсходовано {u}',
 'a whole number from 1 to 1 000 000':'целое число от 1 до 1 000 000','Fix the quota':'Исправьте квоту',
 'by hour for 24 h':'по часам за 24 ч','{n} h without failures':'{n} ч без сбоев','{n} h no data':'{n} ч нет данных',
 'failure {r}':'сбой {r}','failures: {n} times · last {r}':'сбоев: {n} · последний {r}','no check history yet':'истории проверок пока нет',
 'Checks of {exit} for 24 hours: {s}':'Проверки {exit} за 24 часа: {s}','loading':'загрузка','Could not load the check history.':'Не удалось загрузить историю проверок.',
 'Switch when the quota runs out':'Переключать при исчерпании квоты','clients move to the other exit if it is healthy':'клиенты уходят на второй выход, если он в норме',
 'Switch on failure':'Переключать при сбое','3 failed checks in a row · back by hand':'3 неудачные проверки подряд · назад вручную',
 'Last switch':'Последнее переключение','no switches yet':'переключений не было','today {t}':'сегодня {t}',
 'check failures':'сбой проверок','quota':'квота','by hand':'вручную','move back':'возврат',
 'Move {n} back to {exit} →':'Вернуть {n} на {exit} →','Attention':'Внимание',
 'The {exit} quota becomes used up: {u} GiB used with the new quota of {q} GiB.':'Квота {exit} станет исчерпанной: израсходовано {u} ГиБ при новой квоте {q} ГиБ.',
 'The {exit} quota is used up: {u} GiB of {q} GiB.':'Квота {exit} исчерпана: израсходовано {u} ГиБ из {q} ГиБ.',
 '{exit} has 0 clients now — nobody to move.':'Сейчас на {exit} 0 клиентов — переключать некого.',
 '{n} on {exit} move to {o} at the next check if {o} is healthy.':'{n} с {exit} перейдут на {o} при следующей проверке, если {o} в норме.',
 'Switching by quota is off — {n} stay on {exit}.':'Переключение по квоте выключено — {n} останутся на {exit}.',
 'The server refuses new assignments to {exit} until the month ends or the quota grows.':'Новые назначения на {exit} сервер будет отклонять до конца месяца или до увеличения квоты.',
 'All {n} already on {exit}':'Все {n} уже на {exit}','All {n} to {exit}…':'Всех {n} на {exit}…',
 'Saving exit settings':'Сохраняю настройки выходов','Exit settings saved':'Настройки выходов сохранены',
 'The server did not send the exit settings. Try again in a minute.':'Сервер не прислал настройки выходов. Попробуйте через минуту.',
 'Bulk switch':'Массовое переключение','All {n} to {exit}?':'Всех {n} на {exit}?','will move':'переедут',
 '{n}, {k} of them off':'{n}, из них {k}','Move {n} to {exit}':'Перевести {n} на {exit}',
 'At the current rate (~{r} GiB/day) the {exit} quota lasts until the end of the month.':'При текущем расходе (~{r} ГиБ/день) квоты {exit} хватит до конца месяца.',
 'At the current rate (~{r} GiB/day) the {exit} quota lasts about {d}, then the automatic switch moves them back to {o}.':'При текущем расходе (~{r} ГиБ/день) квоты {exit} хватит примерно на {d}, потом сработает автопереключение обратно на {o}.',
 'At the current rate (~{r} GiB/day) the {exit} quota lasts about {d}; switching by quota is off, so they stay on {exit}.':'При текущем расходе (~{r} ГиБ/день) квоты {exit} хватит примерно на {d}; переключение по квоте выключено — клиенты останутся на {exit}.',
 'estimate: traffic of all clients this month ÷ days passed':'оценка: расход всех клиентов за месяц ÷ прошедшие дни',
 'Moving everyone to {exit}':'Перевожу всех на {exit}','{n} moved to {exit}':'{n} — теперь на {exit}',
 'Move clients back':'Возврат клиентов','Move clients back to {exit}?':'Вернуть клиентов на {exit}?',
 'After the automatic switch {t}':'После автопереключения {t}','After the switch {t}':'После переключения {t}',
 'Loading the switch from the journal…':'Загружаю переключение из журнала…',
 'Could not load the switch from the journal.':'Не удалось загрузить переключение из журнала.',
 '{exit} works since {t}':'{exit} работает с {t}','{exit} works':'{exit} работает','quota {u}/{q} GiB ({p}%)':'квота {u}/{q} ГиБ ({p}%)',
 'skipped · client deleted':'пропуск · клиент удалён','skipped · already on {exit}':'пропуск · уже на {exit}',
 'Devices reconnect — a break of a few seconds.':'Устройства переподключатся — разрыв на несколько секунд.',
 'Move {n} back to {exit}':'Вернуть {n} на {exit}','Nobody to move back':'Возвращать некого',
 'Moving {n} back to {exit}':'Возвращаю {n} на {exit}','{n} back on {exit}':'{n} — снова на {exit}',
 'client deleted':'клиент удалён','already on {exit}':'уже на {exit}','moved by hand':'переведён вручную',
 'Nobody to move back: the clients were deleted or moved by hand. Nothing changed.':'Возвращать некого: клиентов удалили или перевели вручную. Ничего не изменилось.',
 'This switch was recorded without its client list — move clients back one by one.':'Это переключение записано без списка клиентов — верните их по одному.',
 'This switch is no longer in the journal.':'Этого переключения уже нет в журнале.',
 'For all clients at once':'Для всех клиентов сразу','Split tunnel':'Сплит-туннель','Loading the split settings…':'Загружаю настройки сплита…',
 'RU subnets':'подсети РФ','everything else':'всё остальное','all traffic':'весь трафик','entry · RU IP':'вход · RU IP',
 'client exit · NL / US':'выход клиента · NL / US','Send RU traffic directly':'Пускать РФ-трафик напрямую',
 '{a} RU subnets · {b} in the set · built {d}':'{a} подсети РФ · {b} в наборе · собран {d}',
 'Also direct':'Также напрямую','IPv4, subnets or domains · domains turn into IPv4 when the list is built':'IPv4, подсети или домены · домены превращаются в IPv4 при сборке',
 'line {n}: «{e}» — {why}. Fix it to apply.':'строка {n}: «{e}» — {why}. Исправьте, чтобы применить.',' and {n} more':' и ещё {n}',
 'two dots in a row':'две точки подряд','does not look like a domain':'не похоже на домен','only Latin letters, digits, «.» and «-»':'только латиница, цифры, «.» и «-»',
 'IPv6 is not supported — IPv4 only':'IPv6 не поддерживается — только IPv4','a number above 255 is not IPv4':'число больше 255 — это не IPv4',
 'the mask is above /32':'маска больше /32','does not look like IPv4':'не похоже на IPv4','a mask only fits an IPv4 subnet':'маска бывает только у IPv4-подсети',
 'a space inside the line':'пробел внутри строки','the line is too long':'слишком длинная строка',
 'Fix line {n}':'Исправьте строку {n}','No more than 500 lines':'Не больше 500 строк','Apply to all':'Применить ко всем',
 'Refresh the RU list':'Обновить список РФ','Refreshing the RU list':'Обновляю список РФ','RU list refreshed':'Список РФ обновлён',
 'Applying the split tunnel':'Применяю сплит-туннель','Split tunnel applied':'Сплит-туннель применён',
 'RU direct: on':'РФ напрямую: вкл','RU direct: off':'РФ напрямую: выкл','list: {n}':'список: {n}',
 'Config backup':'Бэкап конфигураций',
 'The archive holds the private keys of all {n}, the exit settings and the traffic history. Keep it like a password.':'Архив содержит приватные ключи всех {n}, настройки выходов и историю расхода. Храните его так же, как пароль.',
 'last backup: {d}, {a}':'прошлый бэкап: {d}, {a}','no backups in the journal':'прошлых бэкапов в журнале нет',
 'Panel password':'Пароль от панели','The archive is made after the password check.':'Архив сформируется после проверки пароля.',
 'Make the archive':'Сформировать архив','Making the archive…':'Формирую архив…','Enter the password':'Введите пароль',
 'archive ready · {s}':'архив сформирован · {s}','not in the archive: {list}':'нет в архиве: {list}',
 'Share / save to Files':'Поделиться / сохранить в файлы','Download':'Скачать','Download again':'Скачать ещё раз',
 'the link works while the window is open':'ссылка действует, пока окно открыто',
 'The server did not answer — the archive was not received. Try again.':'Сервер не ответил — архив не получен. Попробуйте ещё раз.',
 'Wrong password. The archive was not created.':'Неверный пароль. Архив не создан.',
 'Too many password attempts — wait a few minutes. The archive was not created.':'Слишком много попыток ввода пароля — подождите несколько минут. Архив не создан.',
 'This name is already taken. Nothing changed.':'Это имя уже занято. Ничего не изменилось.',
 'The server did not accept the name: Latin letters, digits, «-» and «_» only. Nothing changed.':'Сервер не принял имя: только латиница, цифры, «-» и «_». Ничего не изменилось.',
 'The server did not accept a line of the list ({e}). Nothing changed.':'Сервер не принял строку списка ({e}). Ничего не изменилось.',
 'No more than 500 lines. Nothing changed.':'Не больше 500 строк. Ничего не изменилось.',
 'The list was saved but could not be rebuilt — the server may still use the old one. Try again.':'Список сохранён, но не пересобрался — сервер может работать по старому. Повторите.',
 'The split tunnel could not be switched. Nothing changed.':'Не удалось переключить сплит-туннель. Ничего не изменилось.',
 'The client is gone — maybe it was deleted. Nothing changed.':'Клиента уже нет — возможно, его удалили. Ничего не изменилось.',
 'The client config file is missing on the server.':'На сервере нет файла конфига этого клиента.',
 'result unknown':'результат неизвестен','server busy':'сервер занят','not applied':'не применено','not started':'не начато',
 'Applied: {list}. Then: {m}':'Применено: {list}. Дальше: {m}','the server refused':'сервер отклонил',
 'Result unknown':'Результат неизвестен','Not applied':'Не применено','Server busy':'Сервер занят','Partially':'Частично'
});

const GIB=1073741824,DAY=86400,NAME_MAX=32;
const nowS=()=>Math.round(Date.now()/1000);
const X=k=>String(k||'').toUpperCase();
const otherExit=k=>k==='us'?'nl':'us';
const exitOf=p=>p&&p.exit==='us'?'us':'nl';
const gib=n=>Math.round((+n||0)/GIB);
const peersNow=()=>WG.state.peers||[];
const LINES={ru:{one:'{n} строка',few:'{n} строки',many:'{n} строк',other:'{n} строки'},en:{one:'{n} line',other:'{n} lines'}};
const OFF={ru:{one:'{n} выключен',few:'{n} выключены',many:'{n} выключены',other:'{n} выключены'},en:{one:'{n} off',other:'{n} off'}};

/* ------------------------------------------------------------ names (C1, C5) */
const NAME_RE=/^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/;          /* = wg-admin.py NAME_RE */
/* '' when the name is fine; else empty | chars | first | long | taken (case-insensitive,
   like the helper). self = the pubkey of the client being renamed. */
function nameProblem(raw,peers,self){
 const n=String(raw==null?'':raw).trim();
 if(!n)return'empty';
 if(!/^[A-Za-z0-9_-]+$/.test(n))return'chars';
 if(!/^[A-Za-z0-9]/.test(n))return'first';
 if(n.length>NAME_MAX)return'long';
 const low=n.toLowerCase();
 if((peers||[]).some(p=>p&&p.pubkey!==self&&String(p.name||'').toLowerCase()===low))return'taken';
 return NAME_RE.test(n)?'':'chars';
}
function nameText(code,raw){
 if(code==='chars')return tr('only Latin letters, digits, «-» and «_»');
 if(code==='first')return tr('the first character is a letter or a digit');
 if(code==='long')return tr('no longer than {n} characters',{n:NAME_MAX});
 if(code==='taken')return tr('«{name}» is already taken',{name:String(raw||'').trim()});
 return'';
}
const TRANSLIT={'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m',
 'н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'',
 'э':'e','ю':'yu','я':'ya','і':'i','ї':'yi','є':'ye','ґ':'g'};
/* «Аня телефон» → anya-telefon: Cyrillic → Latin, anything else → «-», trimmed to 32. */
function translit(s){
 let out='';
 for(const ch of String(s==null?'':s).toLowerCase()){
  if(Object.prototype.hasOwnProperty.call(TRANSLIT,ch))out+=TRANSLIT[ch];
  else if(/[a-z0-9_-]/.test(ch))out+=ch;
  else out+='-';
 }
 out=out.replace(/-{2,}/g,'-').replace(/^[-_]+/,'').replace(/[-_]+$/,'');
 return out.slice(0,NAME_MAX).replace(/[-_]+$/,'');
}
/* A valid, free name to offer instead of a typed one ('' when there is nothing better). */
function suggestName(raw,peers,self){
 const base=translit(raw);
 if(!base||base===String(raw==null?'':raw).trim())return'';
 if(!nameProblem(base,peers,self))return base;
 if(nameProblem(base,[],self))return'';
 for(let i=2;i<10;i++){
  const c=base.slice(0,NAME_MAX-2).replace(/[-_]+$/,'')+'-'+i;
  if(!nameProblem(c,peers,self))return c;
 }
 return'';
}

/* ------------------------------------------------------------ access term (C1, C5) */
function addTerm(days,now){return(+days||0)>0?now+(+days)*DAY:0}
/* keep → as is; never → 0; '+7'/'+30' → from the current term while it runs, else from now. */
function termAfter(choice,cur,now){
 cur=+cur||0;
 if(choice==='keep')return cur;
 if(choice==='never')return 0;
 const days=parseInt(String(choice).replace(/^\+/,''),10)||0;
 return(cur>now?cur:now)+days*DAY;
}
function termText(exp,now){
 exp=+exp||0;
 if(!exp)return tr('no expiry');
 if(exp<=now)return tr('expired {d}',{d:WG.fmtDate(exp)});
 return tr('until {d}',{d:WG.fmtDate(exp)});
}

/* ------------------------------------------------------------ split list (C4) */
const ENTRY_RE=/^[A-Za-z0-9][A-Za-z0-9.\-]{0,253}(\/\d{1,2})?$/;  /* = wg-admin.py ENTRY_RE */
function entryProblem(e){
 if(e.length>254)return'long';
 if(/\s/.test(e))return'space';
 if(e.indexOf(':')>=0)return'ipv6';
 const m=/^(\d{1,3}(?:\.\d{1,3}){3})(?:\/(\d{1,2}))?$/.exec(e);
 if(m){
  if(m[1].split('.').some(o=>+o>255))return'octet';
  if(m[2]!=null&&+m[2]>32)return'mask';
  return'';
 }
 if(/^[\d./]+$/.test(e))return'ip';
 if(e.indexOf('/')>=0)return'mask_on_domain';
 if(e.indexOf('..')>=0)return'dots';
 if(!ENTRY_RE.test(e))return'chars';
 if(e.indexOf('.')<0||/[.-]$/.test(e)||/\.-|-\./.test(e))return'domain';
 return'';
}
const ENTRY_TEXT={dots:'two dots in a row',domain:'does not look like a domain',chars:'only Latin letters, digits, «.» and «-»',
 ipv6:'IPv6 is not supported — IPv4 only',octet:'a number above 255 is not IPv4',mask:'the mask is above /32',ip:'does not look like IPv4',
 mask_on_domain:'a mask only fits an IPv4 subnet',space:'a space inside the line',long:'the line is too long'};
/* Lines → {entries (deduplicated, comments dropped), errors [{line, entry, code}], tooMany}. */
function parseSplit(text){
 const entries=[],errors=[],seen=new Set();
 String(text==null?'':text).split(/\r?\n/).forEach((raw,i)=>{
  const e=raw.trim();
  if(!e||e[0]==='#')return;
  const code=entryProblem(e);
  if(code){errors.push({line:i+1,entry:e,code});return}
  const k=e.toLowerCase();
  if(!seen.has(k)){seen.add(k);entries.push(e)}
 });
 return{entries,errors,tooMany:entries.length>500};
}
function splitErrorText(errors){
 if(!errors.length)return'';
 const e=errors[0],more=errors.length>1?tr(' and {n} more',{n:errors.length-1}):'';
 const shown=e.entry.length>40?e.entry.slice(0,39)+'…':e.entry;
 return tr('line {n}: «{e}» — {why}. Fix it to apply.',{n:e.line,e:shown,why:tr(ENTRY_TEXT[e.code]||'does not look like a domain')})+more;
}

/* ------------------------------------------------------------ exit policy (C3) */
function wholeGiB(v){
 const raw=String(v==null?'':v).trim();
 if(!/^[0-9]+$/.test(raw))return null;
 const n=Number(raw);
 return Number.isSafeInteger(n)&&n>=1&&n<=1000000?n:null;
}
function policyBody(auto,failover,nl,us){
 const a=wholeGiB(nl),b=wholeGiB(us);
 if(a===null||b===null)return null;
 return{op:'setexitpolicy',auto_switch:!!auto,health_failover:!!failover,quotas_gib:{nl:a,us:b}};
}
/* Why a bulk move to target would be refused — the same rules as exit_policy.target_block. */
function bulkBlock(pol,target){
 const e=pol&&pol.exits&&pol.exits[target];
 if(WG.EXITS.indexOf(target)<0||!e)return'invalid_target';
 if(e.exhausted||(+e.quota>0&&+e.used>=+e.quota))return'target_exhausted';
 if(!(+e.checked_age>=0)||+e.checked_age>60)return'target_stale';
 if(e.healthy!==true)return'target_unhealthy';
 return'';
}
/* setexitall moves every client that is not on target yet, disabled ones too. */
function moving(peers,target){
 const list=(peers||[]).filter(p=>p&&exitOf(p)!==target);
 return{n:list.length,off:list.filter(p=>!p.enabled).length,total:(peers||[]).length};
}
/* Days the target quota lasts if every client uses it at this month's average rate. */
function forecast(peers,pol,target,now){
 const e=pol&&pol.exits&&pol.exits[target];
 if(!e||!(+e.quota>0))return null;
 const d=new Date(now*1000);
 const passed=Math.max(1,d.getDate()-1+(d.getHours()*3600+d.getMinutes()*60)/DAY);
 const monthDays=new Date(d.getFullYear(),d.getMonth()+1,0).getDate();
 const total=(peers||[]).reduce((n,p)=>n+(+p.mrx||0)+(+p.mtx||0),0);
 const perDay=total/passed,left=Math.max(0,+e.quota-(+e.used||0));
 return{perDay,left,days:perDay>0?left/perDay:Infinity,monthLeft:Math.max(0,monthDays-passed)};
}

/* ------------------------------------------------------------ health history (C3) */
function healthBuckets(hours){
 return(hours||[]).slice(-24).map(h=>{
  const ok=Math.max(0,+(h&&h.ok)||0),fail=Math.max(0,+(h&&h.fail)||0);
  const st=ok+fail===0?'none':fail===0?'ok':fail*2>=ok+fail?'bad':'warn';
  return{ts:+(h&&h.ts)||0,ok,fail,st};
 });
}
function healthSummary(b){
 if(!b||!b.length)return tr('no check history yet');
 const bad=x=>x.st==='bad'||x.st==='warn';
 const none=b.filter(x=>x.st==='none').length,fails=b.filter(bad).length;
 if(!fails){
  const parts=[];
  if(b.length-none)parts.push(tr('{n} h without failures',{n:b.length-none}));
  if(none)parts.push(tr('{n} h no data',{n:none}));
  return parts.join(' · ');
 }
 let runs=0;b.forEach((x,i)=>{if(bad(x)&&!(i&&bad(b[i-1])))runs++});
 let end=b.length-1;while(end>=0&&!bad(b[end]))end--;
 let start=end;while(start>0&&bad(b[start-1]))start--;
 const r=WG.fmtTime(b[start].ts)+'–'+WG.fmtTime(b[end].ts+3600);
 return runs>1?tr('failures: {n} times · last {r}',{n:runs,r}):tr('failure {r}',{r});
}

/* ------------------------------------------------------------ revert (C6) */
/* Who of a journaled switch would return now: move | deleted | already (on the way-back exit). */
function revertPlan(ev,peers){
 const d=(ev&&ev.data)||{},from=d.target==='us'?'us':'nl';
 const to=WG.EXITS.indexOf(d.source)>=0&&d.source!==from?d.source:otherExit(from);
 const by=new Map((peers||[]).map(p=>[p.pubkey,p]));
 const rows=(Array.isArray(d.members)?d.members:[]).map(m=>{
  const pk=typeof m==='string'?m:m&&m.pubkey,p=by.get(pk);
  const name=p?p.name:(m&&m.name)||'—';
  if(!p)return{pubkey:pk,name,state:'deleted'};
  return{pubkey:pk,name,state:exitOf(p)===from?'move':'already'};
 });
 return{id:+(ev&&ev.id)||0,ts:+(ev&&ev.ts)||0,reason:d.reason,from,to,rows,count:rows.filter(r=>r.state==='move').length};
}
const SKIP_TEXT={deleted:'client deleted',already_on_target:'already on {exit}',reassigned:'moved by hand'};
/* Expected skips (deleted / already back / moved by hand) were shown before confirming:
   they keep the outcome «ok». Any other skip is a real «partial». */
function revertOutcome(out,plan){
 const d=(out&&out.data)||{},to=X(plan&&plan.to);
 if(!out||(out.kind!=='ok'&&out.kind!=='partial'&&out.kind!=='warn'))return out;
 if(d.noop)return{kind:'failed',data:d,message:tr('Nobody to move back: the clients were deleted or moved by hand. Nothing changed.')};
 const skipped=Array.isArray(d.skipped)?d.skipped:[];
 const odd=skipped.filter(x=>!(x&&SKIP_TEXT[x.reason]));
 if(!odd.length)return d.cleanup_warning?Object.assign({},out,{kind:'warn',message:out.message||tr('Cleanup after the change did not finish.')})
  :Object.assign({},out,{kind:'ok',message:''});
 const steps=(Array.isArray(d.changed)?d.changed:[]).map(x=>({state:'ok',text:((x&&x.name)||'')+' → '+to}))
  .concat(skipped.map(x=>{
   const known=SKIP_TEXT[x&&x.reason];
   return{state:known?'skipped':'failed',text:((x&&x.name)||'')+': '+(known?tr(known,{exit:to}):WG.reasonText(x&&x.reason))};
  }));
 return Object.assign({},out,{kind:'partial',steps});
}

/* ------------------------------------------------------------ outcomes */
/* Human text for the server's free-form errors (codes are handled by core.js). */
function serverText(d){
 const e=String((d&&d.error)||''),code=String((d&&d.code)||'');
 if(code==='event_not_revertable'||e==='event_not_revertable')return tr('This switch was recorded without its client list — move clients back one by one.');
 if(code==='event_not_found'||e==='event_not_found')return tr('This switch is no longer in the journal.');
 if(/already exists/i.test(e))return tr('This name is already taken. Nothing changed.');
 if(/^invalid name/i.test(e))return tr('The server did not accept the name: Latin letters, digits, «-» and «_» only. Nothing changed.');
 if(e==='wrong password'||e==='password required')return tr('Wrong password. The archive was not created.');
 if(e==='too many attempts')return tr('Too many password attempts — wait a few minutes. The archive was not created.');
 if(/^invalid entry/i.test(e))return tr('The server did not accept a line of the list ({e}). Nothing changed.',{e:e.replace(/^invalid entry:\s*/i,'')});
 if(/too many custom entries|bad entries/i.test(e))return tr('No more than 500 lines. Nothing changed.');
 if(/rebuild failed|reload failed/i.test(e))return tr('The list was saved but could not be rebuilt — the server may still use the old one. Try again.');
 if(/toggle failed/i.test(e))return tr('The split tunnel could not be switched. Nothing changed.');
 if(/client not found/i.test(e))return tr('The client is gone — maybe it was deleted. Nothing changed.');
 if(/config file unavailable/i.test(e))return tr('The client config file is missing on the server.');
 return'';
}
function explain(out){
 if(!out||out.kind!=='failed')return out;
 const t=serverText(out.data);
 return t?Object.assign({},out,{message:t}):out;
}
/* Reads (getconf, splitinfo, export) change nothing: a lost answer is just «try again». */
function readError(out){
 if(!out)return tr('The server did not answer. Try again.');
 if(out.kind==='unknown')return tr('The server did not answer. Try again.');
 if(out.kind==='busy')return tr('The server is busy with another operation. Try again in a minute.');
 return explain(out).message||tr('The server did not answer. Try again.');
}
function stepReason(o){
 const d=o&&o.data,code=d&&(d.code||d.error);
 if(o.kind==='unknown')return tr('result unknown');
 if(o.kind==='busy')return tr('server busy');
 return(code&&WG.targetText(code))||serverText(d).replace(/\s*(Nothing changed|Ничего не изменилось)\.$/,'')||tr('the server refused');
}
/* Several admin calls as one operation; stops at the first that does not apply. Before
   anything applied, the outcome is that call's own. After: «partial» (or «unknown») with
   every step listed — applied, failed, not started. step: {text, call, apply?(data)}. */
async function runSteps(steps){
 const done=[],warns=[];let last=null;
 for(let i=0;i<steps.length;i++){
  const s=steps[i];
  let o;
  try{o=explain(await live(s.call)())}catch(e){o={kind:'unknown',data:null,message:tr('The connection dropped. The change may have applied — check before repeating.')}}
  if(o&&(o.kind==='ok'||o.kind==='warn')){
   done.push(s);last=o.data;
   if(o.kind==='warn'&&o.message)warns.push(o.message);
   if(typeof s.apply==='function')s.apply(o.data);
   continue;
  }
  if(!done.length)return o;
  const list=done.map(x=>({state:'ok',text:x.text}))
   .concat([{state:o.kind==='unknown'?'skipped':'failed',text:s.text+' — '+stepReason(o)}])
   .concat(steps.slice(i+1).map(x=>({state:'skipped',text:x.text+' — '+tr('not started')})));
  if(o.kind==='unknown')return{kind:'unknown',data:o.data,steps:list,
   message:tr('Applied: {list}. Then: {m}',{list:done.map(x=>x.text).join('; '),m:o.message})};
  return{kind:'partial',data:o.data,message:o.message,steps:list};
 }
 return warns.length?{kind:'warn',data:last,message:warns.join(' ')}:{kind:'ok',data:last,message:''};
}
const mutationBlock=()=>WG.unknown()?(WG.state.offline?tr('No connection'):tr('Wait for fresh data')):'';
const live=fn=>()=>WG.unknown()
 ?Promise.resolve({kind:'failed',data:null,message:tr(WG.state.offline?'No connection to the server — nothing was sent.':'Fresh data is required — nothing was sent.')}):fn();

/* ------------------------------------------------------------ exit state for choosers */
function exitView(k,s){
 s=s||WG.state;
 const D=WG.dashboard,m=D.mode(s),x=D.exitInfo(s,k);
 const unknown=m==='offline'||m==='stale'||m==='loading';
 const pct=Math.floor(x.ratio*100),u=gib(x.used),q=gib(x.quota),K=X(k);
 let tone,text,short,blocked='';
 if(x.exhausted){tone='bad';blocked='target_exhausted';text=tr('quota used up · {u}/{q} GiB',{u,q});short=K+' · '+tr('QUOTA')+' 100%'}
 else if(unknown){tone='u';text=tr('state unknown — the data is old');short=K+' · ?'}
 else if(x.health==='down'){tone='bad';blocked='target_unhealthy';text=tr('down — the server will refuse');short=K+' · '+tr('DOWN')}
 else if(x.health==='warn'){tone='warn';text=tr('check failed {n}/3',{n:Math.min(3,+(x.t&&x.t.fails)||1)});short=K+' · !'}
 else if(x.health==='unknown'){tone='u';text=tr('not checked yet');short=K+' · ?'}
 else{
  tone=x.ratio>=.7?'warn':'ok';
  text=x.ratio>=.7?tr('working · {p}% of quota',{p:pct}):tr('working · {u}/{q} GiB',{u,q});
  short=K+' · '+tr('OK')+(x.ratio>=.7?' · '+pct+'%':'');
 }
 return{k,x,tone,text,short,blocked,pct,u,q,unknown};
}
function blockedLabel(v){
 return v.blocked==='target_exhausted'?tr('{exit} quota is used up',{exit:X(v.k)}):tr('{exit} is unavailable',{exit:X(v.k)});
}
function quotaBar(v,n){
 const filled=v.x.ratio>0?Math.min(n,Math.max(1,Math.round(v.x.ratio*n))):0;
 const tone=v.unknown?'is-u':v.x.ratio>=1?'is-bad':v.x.ratio>=.7?'is-warn':'is-on';
 let h='<span class="qb" aria-hidden="true">';
 for(let i=0;i<n;i++)h+='<i'+(i<filled?' class="'+tone+'"':'')+'></i>';
 return h+'</span>';
}
function checkedText(k,s){
 s=s||WG.state;
 const t=s.tunnel&&s.tunnel.exits&&s.tunnel.exits[k],v=exitView(k,s);
 if(!t)return{tone:'u',text:'?'};
 if(v.unknown)return{tone:'u',text:'? '+tr('checked {t}',{t:WG.fmtAgo(+t.checked_age)})};
 if(t.ok)return{tone:'ok',text:'● '+tr('checked {t}',{t:WG.fmtAgo(+t.checked_age)})};
 if(t.health==='down')return{tone:'bad',text:'× '+tr('no answer · {t}',{t:WG.fmtAgo(Math.max(0,(+s.now||nowS())-(+t.health_since||0)),{suffix:false})})};
 return{tone:'warn',text:'! '+tr('check failed {n}/3',{n:Math.min(3,+t.fails||1)})};
}

/* ------------------------------------------------------------ window kit */
function win(o){
 const offs=[];
 const h=WG.modal.open(Object.assign({},o,{onClose(r){offs.splice(0).forEach(f=>{try{f()}catch(e){}});if(typeof o.onClose==='function')o.onClose(r)}}));
 h.on=(evt,fn)=>{const off=WG.on(evt,fn);offs.push(off);return off};
 h.q=sel=>h.el.querySelector(sel);
 h.click=fn=>h.el.addEventListener('click',e=>{
  const b=e.target&&e.target.closest&&e.target.closest('[data-m]');
  if(!b||b.disabled||!h.el.contains(b)||b.getAttribute('aria-disabled')==='true')return;
  fn(b.getAttribute('data-m'),b,e);
 });
 h.setEyebrow=(text,tone)=>{
  const eb=h.q('.eyebrow');if(!eb)return;
  eb.className='eyebrow'+(tone?' is-'+tone:'');
  eb.innerHTML=(tone==='ok'?'<i class="eb-dot" aria-hidden="true"></i>':'')+esc(text);
 };
 h.setTitle=t=>{const el=h.q('.dlg-title');if(el)el.textContent=t};
 if(o.cls)h.el.classList.add(o.cls);
 return h;
}
/* innerHTML only when it changed; focus stays on the same [data-m] control. */
const keyOf=n=>(n.getAttribute('data-m')||'')+':'+(n.getAttribute('data-k')||n.getAttribute('data-d')||'');
function patch(el,html){
 if(!el||el._html===html)return;
 const a=document.activeElement,key=a&&a!==el&&el.contains(a)&&a.getAttribute?keyOf(a):null;
 el.innerHTML=html;el._html=html;
 if(key){const n=[...el.querySelectorAll('[data-m]')].find(x=>keyOf(x)===key);if(n){try{n.focus()}catch(e){}}}
}
function btn(m,label,o){
 o=o||{};
 return'<button type="button" class="btn'+(o.cls?' '+o.cls:'')+'" data-m="'+m+'"'+(o.k?' data-k="'+esc(o.k)+'"':'')
  +(o.disabled?' disabled':'')+(o.af?' autofocus':'')+'>'+(o.ic?icon(o.ic,16):'')+'<span>'+esc(label)+'</span>'+(o.arrow?icon('arrow-right',16):'')+'</button>';
}
const closeBtn=label=>'<button class="btn btn-primary" type="button" data-act="modal-close">'+esc(label||tr('Close'))+'</button>';
function foot(note,buttons){return'<div class="mf-note">'+(note||'')+'</div><div class="mf-btns">'+buttons+'</div>'}
function setFoot(h,html){h.footer.hidden=false;h.footer.classList.remove('is-busy');patch(h.footer,html)}
const loadingHTML=t=>'<div class="m-load" role="status"><span class="mf-bar" aria-hidden="true"></span><span>'+esc(t)+'</span></div>';
function outHTML(out,extra){
 const tone=out.kind==='unknown'?'unknown':out.kind==='busy'?'busy':out.kind==='warn'?'warn':'failed';
 const tag={failed:'Not applied',unknown:'Result unknown',busy:'Server busy',warn:'Applied, but',partial:'Partially'}[out.kind]||'Not applied';
 const steps=out.steps&&out.steps.length?'<ul class="m-steps">'+out.steps.map(s=>'<li class="is-'+esc(s.state)+'">'+(s.state==='ok'?'✓ ':s.state==='failed'?'× ':'— ')+esc(s.text)+'</li>').join('')+'</ul>':'';
 return'<div class="m-out is-'+tone+'" role="alert"><b class="m-out-t">'+esc(tr(tag))+'</b> '+esc(out.message||'')+steps
  +(extra?'<div class="m-out-s">'+esc(extra)+'</div>':'')+'</div>';
}
function showOut(h,out,extra){const box=h.q('.m-out-box');if(!box)return;box.hidden=!out;box.innerHTML=out?outHTML(out,extra):''}
/* An operation started from a window (C5): the footer shows the action and the elapsed
   time only — no percent — and that the window may be closed: the outcome lands in the
   operations strip either way. Resolves with the outcome. */
function runInWindow(h,o){
 const start=Date.now(),f=h.footer;
 f.hidden=false;f.classList.add('is-busy');f._html=null;
 f.innerHTML='<div class="mf-busy" role="status"><div class="mf-bt">'+esc(o.label)+'… <span class="mf-time">0:00</span></div>'
  +'<span class="mf-bar" aria-hidden="true"></span>'
  +'<div class="mf-hint">'+esc(tr('You can close the window — the result stays in the operations line at the top.'))+'</div></div>'
  +'<div class="mf-btns"><button class="btn is-busy" type="button" disabled>'+esc(o.busy||tr('Saving…'))+'</button></div>';
 const a=document.activeElement;
 if(!a||a.isConnected===false||!h.el.contains(a)){try{h.el.focus()}catch(e){}}
 const t=f.querySelector('.mf-time');
 const off=h.on('second',()=>{if(t)t.textContent=WG.fmtClock((Date.now()-start)/1000)});
 return WG.ops.run({key:o.key,label:o.label,done:o.done,undo:o.undo,call:o.call}).then(out=>{off();if(h.alive())f.classList.remove('is-busy');return out});
}
function setLocked(h,on){h.el.querySelectorAll('.m-lockable').forEach(el=>{el.disabled=!!on})}
function missing(){
 win({title:tr('Client not found'),size:'sm',
  body:'<p class="prose">'+esc(tr('It is not in the list anymore — maybe it was deleted. The list refreshes in a few seconds.'))+'</p>',
  footer:closeBtn()});
}
function segHTML(items,cls,label,name){
 return'<div class="mseg '+cls+'" role="radiogroup"'+(label?' aria-labelledby="'+label+'"':' aria-label="'+esc(name||'')+'"')+'>'+items.map(it=>'<button type="button" role="radio" class="mseg-b" data-m="'+it.m+'" data-k="'+esc(it.k)+'"'
  +' aria-checked="'+!!it.on+'"'+(it.disabled?' aria-disabled="true"':'')+(it.title?' title="'+esc(it.title)+'"':'')+'>'+esc(it.label)+'</button>').join('')+'</div>';
}
function checkSeg(box,m,k){box.querySelectorAll('[data-m="'+m+'"]').forEach(x=>x.setAttribute('aria-checked',String(x.getAttribute('data-k')===String(k))))}

/* ------------------------------------------------------------ new client (C1 → C2, E2) */
function pickExit(){
 const nl=exitView('nl');
 return nl.blocked&&!exitView('us').blocked?'us':'nl';
}
function exitCard(k,sel){
 const v=exitView(k);
 return'<button type="button" role="radio" class="xc'+(sel?' is-sel':'')+(v.blocked?' is-blocked':'')+'" data-m="exit" data-k="'+k+'" aria-checked="'+sel+'"'
  +(v.blocked?' aria-disabled="true"':'')+' aria-label="'+esc(X(k)+' · '+WG.exitCity(k)+' — '+v.text)+'">'
  +'<span class="xc-top"><span class="xc-name">'+esc(X(k))+' · '+esc(WG.exitCity(k))+'</span><span class="xc-short">'+esc(v.short)+'</span>'
  +'<span class="xc-radio" aria-hidden="true"></span></span>'+quotaBar(v,10)
  +'<span class="xc-st is-'+v.tone+'"><i class="xc-dot" aria-hidden="true"></i>'+esc(v.text)+'</span></button>';
}
function addClient(){
 const st={exit:pickExit(),days:0,busy:false};
 const sample='Аня телефон';
 const h=win({eyebrow:tr('Step 1 of 2'),title:tr('New client'),size:'md',cls:'m-add',footer:' ',
  body:'<div class="m-form">'
   +'<div class="m-grp"><label class="field-l" for="m-name">'+esc(tr('Name'))+'</label>'
   +'<div class="m-input"><input class="input m-name m-lockable" id="m-name" type="text" autocomplete="off" autocapitalize="none" spellcheck="false" maxlength="64" aria-describedby="m-name-h" autofocus>'
   +'<span class="m-count" aria-hidden="true">0/'+NAME_MAX+'</span></div>'
   +'<div class="m-hint m-name-h" id="m-name-h" aria-live="polite"></div><div class="m-sug" hidden></div></div>'
   +'<div class="m-grp"><span class="field-l" id="m-exit-l">'+esc(tr('Exit'))+'</span><div class="xc-grid" role="radiogroup" aria-labelledby="m-exit-l"></div>'
   +'<div class="m-hint is-err m-exit-h" hidden></div></div>'
   +'<div class="m-grp"><span class="field-l" id="m-term-l">'+esc(tr('Access term'))+'</span>'
   +segHTML([0,1,7,30].map(d=>({m:'term',k:d,label:d?WG.count(d,'day'):tr('No expiry'),on:d===0})),'is-fill','m-term-l')+'</div>'
   +'<div class="m-out-box" hidden></div></div>'});
 const inp=h.q('.m-name');
 function paintName(){
  const v=inp.value,prob=nameProblem(v,peersNow()),bad=prob&&prob!=='empty';
  const cnt=h.q('.m-count');cnt.textContent=v.trim().length+'/'+NAME_MAX;cnt.classList.toggle('is-bad',v.trim().length>NAME_MAX);
  inp.setAttribute('aria-invalid',String(!!bad));
  const hint=h.q('.m-name-h');
  const text=bad?nameText(prob,v):tr('Latin letters, digits, «-» and «_», starting with a letter or a digit')
   +(WG.lang==='ru'?' · '+tr('hint: «{a}» → {b}',{a:sample,b:translit(sample)}):'');
  if(hint.textContent!==text)hint.textContent=text;
  hint.classList.toggle('is-err',!!bad);
  const sug=prob==='chars'||prob==='first'||prob==='long'?suggestName(v,peersNow()):'';
  const box=h.q('.m-sug');
  box.hidden=!sug;
  patch(box,sug?'<button type="button" class="m-chip m-lockable" data-m="suggest" data-k="'+esc(sug)+'">'+esc(tr('use: {name}',{name:sug}))+'</button>':'');
 }
 function paintExits(){
  patch(h.q('.xc-grid'),WG.EXITS.map(k=>exitCard(k,k===st.exit)).join(''));
  const v=exitView(st.exit),eh=h.q('.m-exit-h');
  eh.hidden=!v.blocked;
  eh.textContent=v.blocked?tr(v.blocked==='target_exhausted'?'{exit} quota is used up: the server will refuse it. Choose the other exit.':'{exit} is down: the server will refuse it. Choose the other exit.',{exit:X(st.exit)}):'';
 }
 function why(){
  const prob=nameProblem(inp.value,peersNow()),v=exitView(st.exit);
  if(mutationBlock())return mutationBlock();
  if(prob==='empty')return tr('Enter a name');
  if(prob)return tr('Fix the name');
  if(v.blocked)return blockedLabel(v);
  return'';
 }
 function paintFoot(){
  if(st.busy)return;
  const w=why();
  setFoot(h,foot(esc(tr('The IP is assigned after creation')),
   btn('cancel',tr('Cancel'))+btn('create',w||tr('Create and show QR'),{cls:'btn-primary',disabled:!!w,arrow:!w})));
 }
 function paint(){paintName();paintExits();paintFoot()}
 async function create(){
  if(st.busy||why())return;
  const name=inp.value.trim(),exit=st.exit,expires=addTerm(st.days,nowS());
  st.busy=true;setLocked(h,true);showOut(h,null);
  const out=await runInWindow(h,{key:'add:'+name.toLowerCase(),label:tr('Creating {name}',{name}),done:tr('{name} created',{name}),busy:tr('Creating…'),
   call:live(()=>WG.admin({op:'add',name,expires,exit}).then(explain))});
  st.busy=false;
  if(!h.alive())return;
  if(out.kind==='ok'||out.kind==='warn'){
   configWindow({fresh:true,data:Object.assign({name,exit,expires},out.data||{}),warning:out.kind==='warn'?out.message:''});
   return;
  }
  setLocked(h,false);
  showOut(h,out,out.kind==='unknown'?tr('Check the client list before creating it again.'):'');
  paint();
 }
 h.click((m,b)=>{
  if(st.busy)return;
  if(m==='cancel')return h.close();
  if(m==='create')return create();
  if(m==='suggest'){inp.value=b.getAttribute('data-k');paint();try{inp.focus()}catch(e){}return}
  if(m==='exit'){st.exit=b.getAttribute('data-k')==='us'?'us':'nl';paint();return}
  if(m==='term'){st.days=+b.getAttribute('data-k')||0;checkSeg(h.el,'term',st.days)}
 });
 h.el.addEventListener('input',e=>{if(e.target===inp){showOut(h,null);paintName();paintFoot()}});
 h.el.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target===inp){e.preventDefault();create()}});
 h.on('status',()=>{if(!st.busy){paintExits();paintFoot()}});
 paint();
 return h;
}

/* ------------------------------------------------------------ config + QR (C2) and history */
function confFacts(conf){
 const get=k=>{const m=new RegExp('^\\s*'+k+'\\s*=\\s*(.+)$','mi').exec(String(conf||''));return m?m[1].trim():''};
 return{address:get('Address'),dns:get('DNS'),allowed:get('AllowedIPs')};
}
function routeText(allowed){
 const a=String(allowed||'').split(',').map(s=>s.trim()).filter(Boolean);
 const v4=a.indexOf('0.0.0.0/0')>=0,v6=a.indexOf('::/0')>=0;
 if(v4&&v6)return tr('all IPv4 and IPv6 — through the tunnel');
 if(v4)return tr('all IPv4 — through the tunnel');
 return a.length?tr('{n} networks through the tunnel (split in the config)',{n:a.length}):'';
}
const B64=/^[A-Za-z0-9+/]+=*$/;
function confHTML(d,warning){
 const f=confFacts(d.conf),p=WG.peer(d.pubkey);
 const exit=d.exit||(p&&exitOf(p))||'nl',exp=d.expires!=null?d.expires:(p?p.expires:0);
 const ip=d.ip||(f.address||'').replace(/\/\d+$/,'');
 const qr=typeof d.qr==='string'&&d.qr&&B64.test(d.qr)
  ?'<img src="data:image/png;base64,'+d.qr+'" alt="'+esc(tr('QR code of the {name} config',{name:d.name||''}))+'" width="200" height="200">'
  :'<p class="cq-noqr">'+esc(tr('The config is too big for a QR code — import the .conf file.'))+'</p>';
 const line2=[routeText(f.allowed),f.dns?'DNS '+f.dns:''].filter(Boolean).join(' · ');
 return(warning?'<div class="m-out is-warn" role="status">'+esc(tr('Created, but: {m}',{m:warning}))+'</div>':'')
  +'<div class="cq"><div class="cq-qr">'+qr+'</div><div class="cq-side"><ol class="cq-steps">'
  +['Install WireGuard on the device','«Add tunnel» → «Scan QR code»','Connect — the client row shows the time of the last connection']
   .map((t,i)=>'<li><span class="cq-n" aria-hidden="true">'+(i+1)+'</span><span>'+esc(tr(t))+'</span></li>').join('')+'</ol>'
  +'<div class="cq-meta"><div>'+esc([tr('exit {exit}',{exit:X(exit)}),termText(exp,nowS()),ip].filter(Boolean).join(' · '))+'</div>'
  +(line2?'<div>'+esc(line2)+'</div>':'')+'</div></div></div>';
}
function dayLabel(day){
 const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(String(day||''));
 return m?WG.fmtDate(new Date(+m[1],+m[2]-1,+m[3],12).getTime()/1000):String(day||'');
}
function historyHTML(hist,name){
 const d=(hist.daily||[]).map(x=>({day:x.day,v:(+x.rx||0)+(+x.tx||0)}));
 let h='<section class="ch"><div class="m-lrow"><span class="field-l">'+esc(tr('Traffic by day'))+'</span>';
 if(d.length&&d.some(x=>x.v>0)){
  const total=d.reduce((n,x)=>n+x.v,0),peak=d.reduce((a,x)=>x.v>a.v?x:a,d[0]),max=peak.v||1;
  const sum=tr('{n} days: {t} · peak {p} ({d})',{n:d.length,t:WG.fmtBytes(total),p:WG.fmtBytes(peak.v),d:dayLabel(peak.day)});
  const W=560,H=110,slot=W/d.length,bw=Math.max(2,slot-3);
  h+='<span class="m-hint">'+esc(sum)+'</span></div>'
   +'<svg class="ch-bars" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" role="img" aria-label="'+esc(tr('Daily traffic of {name}: {s}',{name,s:sum}))+'">'
   +d.map((x,i)=>{const bh=Math.max(x.v>0?2:0,x.v/max*(H-6));return'<rect x="'+(i*slot+1).toFixed(1)+'" y="'+(H-bh).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+bh.toFixed(1)+'"><title>'+esc(dayLabel(x.day)+' · '+WG.fmtBytes(x.v))+'</title></rect>'}).join('')
   +'<line x1="0" y1="'+(H-.5)+'" x2="'+W+'" y2="'+(H-.5)+'"/></svg>'
   +'<div class="ch-axis" aria-hidden="true"><span>'+esc(dayLabel(d[0].day))+'</span><span>'+esc(dayLabel(d[d.length-1].day))+'</span></div>';
 }else h+='</div><p class="m-hint">'+esc(tr('No traffic this month yet.'))+'</p>';
 const c=(hist.conns||[]).slice(0,12);
 h+='</section><section class="ch"><span class="field-l">'+esc(tr('Connections'))+'</span>'
  +(c.length?'<ul class="ch-list">'+c.map(x=>'<li><span>'+esc(WG.fmtDate(x.ts)+' · '+WG.fmtTime(x.ts))+'</span><span class="mono">'+esc(x.endpoint||'—')+'</span></li>').join('')+'</ul>'
   :'<p class="m-hint">'+esc(tr('No connections recorded yet.'))+'</p>')+'</section>';
 if(hist.partial)h+='<p class="m-hint">'+esc(tr('Part of the history did not load.'))+'</p>';
 return h;
}
function canShareFiles(){
 try{return !!(navigator.share&&navigator.canShare&&typeof File!=='undefined'&&navigator.canShare({files:[new File(['x'],'x.conf',{type:'text/plain'})]}))}catch(e){return false}
}
function saveBlob(name,blob){
 const url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download=name;a.rel='noopener';document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>{try{URL.revokeObjectURL(url)}catch(e){}},2000);
}
async function copyText(text){
 try{if(navigator.clipboard&&navigator.clipboard.writeText){await navigator.clipboard.writeText(text);return true}}catch(e){}
 try{
  const ta=document.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');ta.className='sr-only';
  document.body.appendChild(ta);ta.select();const ok=document.execCommand&&document.execCommand('copy');ta.remove();return !!ok;
 }catch(e){return false}
}
function showConfig(pubkey,opts){
 opts=opts||{};
 const p=WG.peer(pubkey);
 if(!p)return missing();
 return configWindow({pubkey,name:p.name,section:opts.section});
}
function configWindow(o){
 const fresh=!!o.fresh;
 let data=o.data||null,tab=!fresh&&o.section==='history'?'history':'conf';
 let hist=null,histErr=false,histBusy=false,confErr='',confBusy=false,copied=0;
 const name=(data&&data.name)||o.name||'',pubkey=(data&&data.pubkey)||o.pubkey||'';
 const h=win({eyebrow:fresh?tr('Step 2 of 2 · created'):tr('Config and QR'),title:name,size:'md',cls:'m-conf',footer:' ',
  body:(fresh?'':'<div class="m-tabs">'+segHTML([{m:'tab',k:'conf',label:tr('Config and QR'),on:tab==='conf'},{m:'tab',k:'history',label:tr('History'),on:tab==='history'}],'is-fill is-sm','',name)+'</div>')+'<div class="m-pane"></div>'});
 if(fresh)h.setEyebrow(tr('Step 2 of 2 · created'),'ok');
 function paint(){
  let html;
  if(tab==='conf'){
   if(data)html=confHTML(data,o.warning);
   else if(confErr)html='<div class="m-out is-failed" role="alert">'+esc(confErr)+'</div><div class="m-retry">'+btn('retry-conf',tr('Retry'),{cls:'btn-outline btn-sm',ic:'refresh'})+'</div>';
   else html=loadingHTML(tr('Loading the config…'));
  }else{
   if(hist)html=historyHTML(hist,name);
   else if(histErr)html='<div class="m-out is-failed" role="alert">'+esc(tr('Could not load the history. Try again later.'))+'</div><div class="m-retry">'+btn('retry-hist',tr('Retry'),{cls:'btn-outline btn-sm',ic:'refresh'})+'</div>';
   else html=loadingHTML(tr('Loading the history…'));
  }
  patch(h.q('.m-pane'),html);
  const share=canShareFiles();
  const tools=tab==='conf'&&data?btn('dl','.conf',{cls:'btn-outline-l',ic:'download'})
   +btn('copy',copied===1?tr('Copied'):tr('Copy'),{cls:'btn-outline-l',ic:copied===1?'ok':'copy'})
   +(share?btn('share',tr('Share'),{cls:'btn-outline-l',ic:'share'}):''):'';
  setFoot(h,'<div class="mf-tools">'+tools+'</div><div class="mf-btns">'+btn('done',tr('Done'),{cls:'btn-primary',af:fresh})+'</div>'
   +(copied===2?'<div class="mf-err" role="alert">'+esc(tr('Could not copy — download the .conf instead.'))+'</div>':''));
 }
 async function loadConf(){
  if(data||confBusy)return;
  confBusy=true;confErr='';paint();
  const out=await WG.admin({op:'getconf',pubkey});
  confBusy=false;
  if(!h.alive())return;
  if(out.kind==='ok'||out.kind==='warn')data=Object.assign({pubkey},out.data||{});else confErr=readError(out);
  paint();
 }
 function loadHist(){
  if(hist||histBusy)return;
  histBusy=true;histErr=false;paint();
  const q='?pub='+encodeURIComponent(pubkey);
  Promise.all([h.api('/api/history'+q).catch(()=>null),h.api('/api/connections'+q).catch(()=>null)]).then(([u,c])=>{
   histBusy=false;
   if(!h.alive())return;
   if(!u&&!c)histErr=true;
   else hist={daily:(u&&u.daily)||[],conns:(c&&c.connections)||[],partial:!u||!c};
   paint();
  });
 }
 function show(){if(tab==='conf')loadConf();else loadHist();paint()}
 h.click(async(m,b)=>{
  if(m==='done')return h.close();
  if(m==='tab'){tab=b.getAttribute('data-k')==='history'?'history':'conf';checkSeg(h.el,'tab',tab);return show()}
  if(m==='retry-conf'){confErr='';return loadConf()}
  if(m==='retry-hist'){histErr=false;return loadHist()}
  if(!data)return;
  const file=(data.name||name||'client')+'.conf';
  if(m==='dl')return saveBlob(file,new Blob([data.conf||''],{type:'text/plain'}));
  if(m==='copy'){copied=await copyText(data.conf||'')?1:2;if(h.alive())paint();setTimeout(()=>{if(h.alive()&&copied===1){copied=0;paint()}},2000);return}
  if(m==='share'){
   try{await navigator.share({files:[new File([data.conf||''],file,{type:'text/plain'})],title:file})}catch(e){}
  }
 });
 show();
 return h;
}

/* ------------------------------------------------------------ edit (C5) */
function editClient(pubkey){
 const p=WG.peer(pubkey);
 if(!p)return missing();
 const orig={name:p.name,exp:+p.expires||0,exit:exitOf(p)};
 const st={choice:'keep',exit:orig.exit,busy:false};
 const now0=nowS(),plus=orig.exp>now0?'+':'';
 const h=win({eyebrow:tr('Edit client'),title:p.name,size:'md',cls:'m-edit',footer:' ',
  body:'<div class="m-form">'
   +'<div class="m-grp"><label class="field-l" for="m-name">'+esc(tr('Name'))+'</label>'
   +'<input class="input m-name m-lockable" id="m-name" type="text" autocomplete="off" autocapitalize="none" spellcheck="false" maxlength="64" aria-describedby="m-name-h">'
   +'<div class="m-hint m-name-h" id="m-name-h" aria-live="polite" hidden></div><div class="m-sug" hidden></div></div>'
   +'<div class="m-grp"><div class="m-lrow"><span class="field-l" id="m-term-l">'+esc(tr('Access term'))+'</span><span class="m-now"></span></div>'
   +segHTML([{m:'term',k:'keep',label:tr('Keep'),on:true},{m:'term',k:'+7',label:plus+WG.count(7,'day')},{m:'term',k:'+30',label:plus+WG.count(30,'day')},{m:'term',k:'never',label:tr('No expiry')}],'is-fill','m-term-l')
   +'<div class="m-hint m-term-h"></div></div>'
   +'<div class="m-grp"><span class="field-l" id="m-exit-l">'+esc(tr('Exit'))+'</span><div class="m-exits"></div><div class="m-hint is-err m-exit-h" hidden></div></div>'
   +'<div class="m-out-box" hidden></div></div>'});
 const inp=h.q('.m-name');inp.value=orig.name;
 function changes(){
  const name=inp.value.trim(),now=nowS(),list=[];
  if(name!==orig.name)list.push({kind:'name',text:tr('name: {a} → {b}',{a:orig.name,b:name}),
   call:()=>WG.admin({op:'rename',pubkey,name}),apply:()=>{orig.name=name}});
  const exp=termAfter(st.choice,orig.exp,now);
  if(st.choice!=='keep'&&exp!==orig.exp)list.push({kind:'term',exp,text:tr('term: {t}',{t:exp?tr('until {d}',{d:WG.fmtDate(exp)}):tr('no expiry')}),
   call:()=>WG.admin({op:'setexpiry',pubkey,expires:exp}),apply:()=>{orig.exp=exp;st.choice='keep'}});
  if(st.exit!==orig.exit){const ex=st.exit;list.push({kind:'exit',text:tr('exit: {a} → {b}',{a:X(orig.exit),b:X(ex)}),
   call:()=>WG.admin({op:'setexit',pubkey,exit:ex}),apply:()=>{orig.exit=ex}})}
  return list;
 }
 function paintName(){
  const prob=nameProblem(inp.value,peersNow(),pubkey),bad=prob&&prob!=='empty';
  inp.setAttribute('aria-invalid',String(!!(prob)));
  const hint=h.q('.m-name-h');hint.hidden=!prob;hint.classList.toggle('is-err',!!prob);
  const text=prob==='empty'?tr('Enter a name'):bad?nameText(prob,inp.value):'';
  if(hint.textContent!==text)hint.textContent=text;
  const sug=prob==='chars'||prob==='first'||prob==='long'?suggestName(inp.value,peersNow(),pubkey):'';
  const box=h.q('.m-sug');box.hidden=!sug;
  patch(box,sug?'<button type="button" class="m-chip m-lockable" data-m="suggest" data-k="'+esc(sug)+'">'+esc(tr('use: {name}',{name:sug}))+'</button>':'');
 }
 function paintTerm(){
  const now=nowS(),e=orig.exp,left=e>now?Math.ceil((e-now)/DAY):0;
  const cur=!e?tr('no expiry'):e<=now?tr('expired {d}',{d:WG.fmtDate(e)}):tr('until {d} ({n})',{d:WG.fmtDate(e),n:WG.count(left,'day')});
  const nowEl=h.q('.m-now');nowEl.textContent=tr('now: {t}',{t:cur});nowEl.className='m-now'+(e&&(e<=now||left<7)?' is-warn':'');
  const exp=termAfter(st.choice,orig.exp,now);
  h.q('.m-term-h').textContent=tr('will be: {t}',{t:st.choice==='keep'||exp===orig.exp?tr('no change'):termText(exp,now)});
 }
 function paintExit(){
  const items=WG.EXITS.map(k=>{const v=exitView(k);return{m:'exit',k,label:v.short,on:k===st.exit,disabled:!!v.blocked&&k!==orig.exit,title:v.text}});
  patch(h.q('.m-exits'),segHTML(items,'is-ring','m-exit-l'));
  const v=exitView(st.exit),eh=h.q('.m-exit-h'),bad=st.exit!==orig.exit&&v.blocked;
  eh.hidden=!bad;eh.textContent=bad?tr(v.blocked==='target_exhausted'?'{exit} quota is used up: the server will refuse it. Choose the other exit.':'{exit} is down: the server will refuse it. Choose the other exit.',{exit:X(st.exit)}):'';
 }
 function why(){
  const prob=nameProblem(inp.value,peersNow(),pubkey);
  if(mutationBlock())return mutationBlock();
  if(WG.ops.running('edit:'+pubkey))return tr('Wait for the current change to finish');
  if(prob==='empty')return tr('Enter a name');
  if(prob)return tr('Fix the name');
  if(st.exit!==orig.exit&&exitView(st.exit).blocked)return blockedLabel(exitView(st.exit));
  if(!changes().length)return tr('No changes');
  return'';
 }
 function paintFoot(){
  if(st.busy)return;
  const w=why();
  setFoot(h,foot('',btn('cancel',tr('Cancel'))+btn('save',w||tr('Save'),{cls:'btn-primary',disabled:!!w})));
 }
 function paint(){paintName();paintTerm();paintExit();paintFoot()}
 function label(list,name){
  if(list.length>1)return tr('{name}: saving changes',{name});
  const c=list[0];
  if(c.kind==='name')return tr('{name}: renaming',{name});
  if(c.kind==='exit')return tr('{name}: moving to {exit}',{name,exit:X(st.exit)});
  return tr(c.exp===0||(orig.exp>0&&c.exp>orig.exp)?'{name}: extending access':'{name}: changing the term',{name});
 }
 async function save(){
  if(st.busy||why())return;
  const list=changes(),name=orig.name,next=inp.value.trim()||name;
  st.busy=true;setLocked(h,true);showOut(h,null);
  const one=list.length===1&&list[0].kind==='term';
  const out=await runInWindow(h,{key:'edit:'+pubkey,label:label(list,name),busy:tr('Saving…'),
   done:one?tr('{name}: access {t}',{name:next,t:list[0].exp?tr('until {d}',{d:WG.fmtDate(list[0].exp)}):tr('no expiry')}):tr('{name}: saved',{name:next}),
   call:live(()=>runSteps(list))});
  st.busy=false;
  if(!h.alive())return;
  if(out.kind==='ok'||out.kind==='warn')return h.close();
  setLocked(h,false);
  if(out.kind==='partial'||out.kind==='unknown')h.setTitle(orig.name);
  if(st.choice==='keep')checkSeg(h.el,'term','keep');
  showOut(h,out);paint();
 }
 h.click((m,b)=>{
  if(st.busy)return;
  if(m==='cancel')return h.close();
  if(m==='save')return save();
  if(m==='suggest'){inp.value=b.getAttribute('data-k');paint();try{inp.focus()}catch(e){}return}
  if(m==='term'){st.choice=b.getAttribute('data-k');checkSeg(h.el,'term',st.choice);paintTerm();paintFoot();return}
  if(m==='exit'){st.exit=b.getAttribute('data-k')==='us'?'us':'nl';paintExit();paintFoot()}
 });
 h.el.addEventListener('input',e=>{if(e.target===inp){showOut(h,null);paintName();paintFoot()}});
 h.el.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target===inp){e.preventDefault();save()}});
 h.on('status',()=>{if(!st.busy){paintExit();paintFoot()}});
 h.on('ops',paintFoot);
 h.on('second',()=>{if(!st.busy)paintTerm()});
 paint();
 setTimeout(()=>{if(h.alive()){try{inp.focus();inp.select()}catch(e){}}},0);
 return h;
}

/* ------------------------------------------------------------ on / off, delete (C6) */
function setEnabled(pubkey,on){
 const p=WG.peer(pubkey);
 if(!p)return missing();
 const name=p.name;
 return WG.ops.run({key:'enabled:'+pubkey,
  label:on?tr('Turning on {name}',{name}):tr('Turning off {name}',{name}),done:on?tr('{name} is on',{name}):tr('{name} is off',{name}),
  call:live(()=>WG.admin({op:'enabled',pubkey,enabled:on}).then(explain)),undo:!on&&p.enabled?()=>setEnabled(pubkey,true):undefined});
}
function toggleEnabled(pubkey){
 const p=WG.peer(pubkey);
 return p?setEnabled(pubkey,!p.enabled):missing();
}
function deleteClient(pubkey){
 const p=WG.peer(pubkey);
 if(!p)return missing();
 const name=p.name;
 const h=win({eyebrow:tr('Irreversible'),title:tr('Delete {name}?',{name}),size:'sm',cls:'m-del',footer:' ',
  body:'<p class="prose">'+esc(tr('The client keys are deleted and the device will not connect anymore. Getting it back means a new client and a new QR code.'))+'</p>'
   +(p.enabled?'<p class="m-note">'+esc(tr('If it is temporary, choose «Turn off» — that can be undone.'))+'</p>':'')
   +'<div class="m-grp"><label class="field-l" for="m-del">'+esc(tr('Type the name to confirm'))+'</label>'
   +'<input class="input m-del-in" id="m-del" type="text" autocomplete="off" autocapitalize="none" spellcheck="false" autofocus></div>'});
 h.setEyebrow(tr('Irreversible'),'danger');
 const inp=h.q('.m-del-in');
 const ok=()=>inp.value.trim()===name&&!WG.unknown();
 function paintFoot(){
  setFoot(h,'<div class="mf-tools">'+(p.enabled?btn('off',tr('Turn off instead'),{cls:'btn-outline-l',disabled:WG.unknown()}):'')+'</div>'
   +'<div class="mf-btns">'+btn('cancel',tr('Cancel'))+btn('del',mutationBlock()||tr('Delete'),{cls:'btn-danger',disabled:!ok()})+'</div>');
 }
 function del(){
  if(!ok())return;
  h.close();
  return WG.ops.run({key:'delete:'+pubkey,label:tr('Deleting {name}',{name}),done:tr('{name} deleted',{name}),
   call:live(()=>WG.admin({op:'delete',pubkey}).then(explain))});
 }
 h.click(m=>{
  if(m==='cancel')return h.close();
  if(m==='del')return del();
  if(m==='off'){h.close();return setEnabled(pubkey,false)}
 });
 h.el.addEventListener('input',e=>{if(e.target===inp)paintFoot()});
 h.el.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target===inp){e.preventDefault();del()}});
 h.on('status',paintFoot);
 paintFoot();
 return h;
}

/* ------------------------------------------------------------ change exit */
function stateRows(k){
 const v=exitView(k),c=checkedText(k),K=X(k);
 const left=Math.max(0,v.q-v.u);
 const t=v.unknown?v.text:c.tone==='ok'?c.text.replace('● ','● '+tr('working')+' · '):c.text;
 return'<dl class="kv"><dt>'+esc(tr('state of {exit}',{exit:K}))+'</dt><dd class="is-'+c.tone+'">'+esc(t)+'</dd>'
  +'<dt>'+esc(tr('quota of {exit}',{exit:K}))+'</dt><dd class="'+(v.x.ratio>=.7?'is-warn':'')+'">'+esc(tr('{u} of {q} GiB · {l} left',{u:v.u,q:v.q,l:left}))+'</dd></dl>';
}
function switchExit(pubkey,target){
 const p=WG.peer(pubkey);
 if(!p)return missing();
 target=target==='us'?'us':'nl';
 const name=p.name,K=X(target);
 if(exitOf(p)===target){
  return win({eyebrow:tr('Change exit'),title:name,size:'sm',body:'<p class="prose">'+esc(tr('{name} is already on {exit}.',{name,exit:K}))+'</p>',footer:closeBtn()});
 }
 const h=win({eyebrow:tr('Change exit'),title:tr('Move {name} to {exit}?',{name,exit:K}),size:'sm',cls:'m-switch',footer:' ',
  body:'<div class="m-rows"></div><p class="m-note">'+esc(tr('The device reconnects — a break of a few seconds. The server checks the exit again before the move.'))+'</p>'});
 function paint(){
  patch(h.q('.m-rows'),stateRows(target));
  const v=exitView(target),w=mutationBlock()||(v.blocked?blockedLabel(v):'');
  setFoot(h,foot('',btn('cancel',tr('Cancel'),{af:true})+btn('go',w||tr('Move to {exit}',{exit:K}),{cls:'btn-primary',disabled:!!w})));
 }
 h.click(m=>{
  if(m==='cancel')return h.close();
  if(m!=='go')return;
  h.close();
  WG.ops.run({key:'exit:'+pubkey,label:tr('{name} → {exit}',{name,exit:K}),done:tr('{name} is on {exit} now',{name,exit:K}),
   call:live(()=>WG.admin({op:'setexit',pubkey,exit:target}).then(explain))});
 });
 h.on('status',paint);
 paint();
 return h;
}

/* ------------------------------------------------------------ exit settings (C3) */
let _exitsDraft=null;
function switchReason(r){return tr({health:'check failures',quota:'quota',manual:'by hand',revert:'move back'}[r]||'by hand')}
function whenText(ts){
 const d=new Date(ts*1000),n=new Date();
 return d.toDateString()===n.toDateString()?tr('today {t}',{t:WG.fmtTime(ts)}):WG.fmtDate(ts)+' '+WG.fmtTime(ts);
}
function exitsSettings(draft){
 const P=WG.state.exit_policy;
 if(!P||!P.exits||!P.exits.nl||!P.exits.us){
  return win({eyebrow:tr('Routing'),title:tr('Exits'),size:'sm',
   body:'<p class="prose">'+esc(tr('The server did not send the exit settings. Try again in a minute.'))+'</p>',footer:closeBtn()});
 }
 const base=()=>{const p=WG.state.exit_policy||P;return{auto:p.auto_switch!==false,fail:p.health_failover!==false,q:{nl:String(gib(p.exits.nl.quota)),us:String(gib(p.exits.us.quota))}}};
 const st=draft||base();
 let hist=null,histErr=false,busy=false;
 const card=k=>'<section class="xs" data-x="'+k+'"><div class="xs-h"><h3 class="xs-name">'+esc(X(k))+' · '+esc(WG.exitCity(k))+'</h3><span class="xs-st"></span></div>'
  +'<div class="hb" role="img"></div><div class="hb-c"></div>'
  +'<label class="field-l" for="m-q-'+k+'">'+esc(tr('Monthly quota'))+'</label>'
  +'<div class="qi"><input class="input m-q m-lockable" id="m-q-'+k+'" data-k="'+k+'" type="text" inputmode="numeric" autocomplete="off" aria-describedby="m-q-'+k+'-s m-q-'+k+'-h">'
  +'<span class="qi-s" id="m-q-'+k+'-s"></span></div><div class="m-hint is-err m-q-h" id="m-q-'+k+'-h" hidden></div><div class="xs-cl"></div></section>';
 const toggle=(m,t,s)=>'<div class="trow"><div class="trow-tx"><div class="trow-t" id="m-t-'+m+'">'+esc(t)+'</div><div class="trow-s">'+esc(s)+'</div></div>'
  +'<button type="button" class="tg m-lockable" role="switch" data-m="'+m+'" aria-labelledby="m-t-'+m+'" aria-checked="false"></button></div>';
 const h=win({eyebrow:tr('Routing'),title:tr('Exits'),size:'lg',cls:'m-exits',footer:' ',
  body:'<div class="xs-grid">'+card('nl')+card('us')+'</div><div class="wband-box"></div>'
   +'<div class="trows">'+toggle('auto',tr('Switch when the quota runs out'),tr('clients move to the other exit if it is healthy'))
   +toggle('fail',tr('Switch on failure'),tr('3 failed checks in a row · back by hand'))
   +'<div class="trow trow-last"><div class="trow-tx"><div class="trow-t">'+esc(tr('Last switch'))+'</div><div class="trow-s m-last"></div></div><div class="trow-x m-last-x"></div></div></div>'
   +'<div class="m-out-box" hidden></div>',
  onClose(r){if(r!=='replaced')_exitsDraft=null}});
 const cardEl=k=>h.q('[data-x="'+k+'"]');
 WG.EXITS.forEach(k=>{cardEl(k).querySelector('.m-q').value=st.q[k]});
 function quotaProblem(k){return wholeGiB(st.q[k])===null}
 function paintCards(){
  const pol=WG.state.exit_policy||P;
  WG.EXITS.forEach(k=>{
   const el=cardEl(k),e=pol.exits[k]||{},c=checkedText(k),u=gib(e.used),q=wholeGiB(st.q[k]);
   const stEl=el.querySelector('.xs-st');stEl.className='xs-st is-'+c.tone;stEl.textContent=c.text;
   const b=hist&&hist[k]?healthBuckets(hist[k]):null;
   const bar=el.querySelector('.hb');
   patch(bar,(b&&b.length?b:Array.from({length:24},()=>({st:'none',ts:0,ok:0,fail:0}))).map(x=>'<i class="is-'+x.st+'"'
    +(x.ts?' title="'+esc(WG.fmtTime(x.ts)+'–'+WG.fmtTime(x.ts+3600)+' · '+x.ok+' ✓ · '+x.fail+' ×')+'"':'')+'></i>').join(''));
   const sum=b?healthSummary(b):histErr?tr('Could not load the check history.'):tr('loading')+'…';
   bar.setAttribute('aria-label',tr('Checks of {exit} for 24 hours: {s}',{exit:X(k),s:sum}));
   el.querySelector('.hb-c').textContent=tr('by hour for 24 h')+' · '+sum;
   const warn=q!==null&&u>=q;
   el.querySelector('.qi').classList.toggle('is-warn',warn);
   el.querySelector('.qi-s').textContent=tr('GiB · used {u}',{u});
   const qh=el.querySelector('.m-q-h'),bad=quotaProblem(k);
   qh.hidden=!bad;qh.textContent=bad?tr('a whole number from 1 to 1 000 000'):'';
   el.querySelector('.m-q').setAttribute('aria-invalid',String(bad));
   el.querySelector('.xs-cl').textContent=WG.count(+e.clients||0,'client');
  });
 }
 function paintWarn(){
  const pol=WG.state.exit_policy||P,parts=[];
  WG.EXITS.forEach(k=>{
   const e=pol.exits[k]||{},q=wholeGiB(st.q[k]),u=gib(e.used),K=X(k),o=X(otherExit(k)),n=+e.clients||0;
   if(q===null||u<q)return;
   const changed=q!==gib(e.quota);
   let t=changed?tr('The {exit} quota becomes used up: {u} GiB used with the new quota of {q} GiB.',{exit:K,u,q})
    :tr('The {exit} quota is used up: {u} GiB of {q} GiB.',{exit:K,u,q});
   if(!n)t+=' '+tr('{exit} has 0 clients now — nobody to move.',{exit:K});
   else if(st.auto)t+=' '+tr('{n} on {exit} move to {o} at the next check if {o} is healthy.',{n:WG.count(n,'client'),exit:K,o});
   else t+=' '+tr('Switching by quota is off — {n} stay on {exit}.',{n:WG.count(n,'client'),exit:K});
   parts.push(t+' '+tr('The server refuses new assignments to {exit} until the month ends or the quota grows.',{exit:K}));
  });
  patch(h.q('.wband-box'),parts.length?'<div class="wband" role="status"><span class="tag is-amber">'+esc(tr('Attention'))+'</span><div class="wband-t">'
   +parts.map(t=>'<p>'+esc(t)+'</p>').join('')+'</div></div>':'');
 }
 function paintToggles(){
  h.q('[data-m="auto"]').setAttribute('aria-checked',String(!!st.auto));
  h.q('[data-m="fail"]').setAttribute('aria-checked',String(!!st.fail));
 }
 function paintLast(){
  const pol=WG.state.exit_policy||P,ls=pol.last_switch;
  let text=tr('no switches yet'),act='';
  if(ls&&+ls.ts>0&&WG.EXITS.indexOf(ls.source)>=0&&WG.EXITS.indexOf(ls.target)>=0){
   const n=+ls.members_count||(typeof ls.changed==='number'?ls.changed:0);
   text=[whenText(+ls.ts),X(ls.source)+' → '+X(ls.target),n?WG.count(n,'client'):'',switchReason(ls.reason)].filter(Boolean).join(' · ');
   const src=exitView(ls.source);
   if(+ls.event_id>0&&+ls.members_count>0&&!ls.revert_of&&!src.blocked&&!src.unknown&&src.x.health==='ok')
    act='<button type="button" class="lnk" data-m="revert" data-k="'+(+ls.event_id)+'">'+esc(tr('Move {n} back to {exit} →',{n:+ls.members_count,exit:X(ls.source)}))+'</button>';
  }
  h.q('.m-last').textContent=text;
  patch(h.q('.m-last-x'),act);
 }
 function dirty(){
  const b=base();
  return b.auto!==st.auto||b.fail!==st.fail||WG.EXITS.some(k=>String(wholeGiB(st.q[k]))!==b.q[k]);
 }
 function why(){
  if(mutationBlock())return mutationBlock();
  if(WG.EXITS.some(quotaProblem))return tr('Fix the quota');
  if(!dirty())return tr('No changes');
  return'';
 }
 function bulkButtons(){
  const pol=WG.state.exit_policy||P,peers=peersNow();
  return WG.EXITS.map(k=>{
   const mv=moving(peers,k),K=X(k),code=bulkBlock(pol,k);
   if(!mv.n)return btn('bulk',tr('All {n} already on {exit}',{n:mv.total,exit:K}),{cls:'btn-outline-l',k,disabled:true});
   if(WG.unknown())return btn('bulk',tr('All {n} to {exit}…',{n:mv.n,exit:K}),{cls:'btn-outline-l',k,disabled:true});
   if(code==='target_exhausted')return btn('bulk',tr('{exit} quota is used up',{exit:K}),{cls:'btn-outline-l',k,disabled:true});
   if(code==='target_stale')return btn('bulk',tr('{exit} is not checked',{exit:K}),{cls:'btn-outline-l',k,disabled:true});
   if(code)return btn('bulk',tr('{exit} is unavailable',{exit:K}),{cls:'btn-outline-l',k,disabled:true});
   return btn('bulk',tr('All {n} to {exit}…',{n:mv.n,exit:K}),{cls:'btn-outline-l',k});
  }).join('');
 }
 function paintFoot(){
  if(busy)return;
  const w=why();
  setFoot(h,'<div class="mf-tools">'+bulkButtons()+'</div><div class="mf-btns">'+btn('cancel',tr('Cancel'))+btn('save',w||tr('Save'),{cls:'btn-primary',disabled:!!w})+'</div>');
 }
 function paint(){paintCards();paintWarn();paintToggles();paintLast();paintFoot()}
 async function save(){
  if(busy||why())return;
  const body=policyBody(st.auto,st.fail,st.q.nl,st.q.us);
  if(!body)return;
  busy=true;setLocked(h,true);showOut(h,null);
  const out=await runInWindow(h,{key:'exit-policy',label:tr('Saving exit settings'),done:tr('Exit settings saved'),busy:tr('Saving…'),
   call:live(()=>WG.admin(body).then(explain))});
  busy=false;
  if(!h.alive())return;
  if(out.kind==='ok'||out.kind==='warn')return h.close();
  setLocked(h,false);showOut(h,out);paint();
 }
 h.click((m,b)=>{
  if(busy)return;
  if(m==='cancel')return h.close();
  if(m==='save')return save();
  if(m==='auto'||m==='fail'){st[m]=!st[m];paintToggles();paintWarn();paintFoot();return}
  if(m==='revert')return revertSwitch(+b.getAttribute('data-k'));
  if(m==='bulk'){_exitsDraft=st;return confirmBulk(b.getAttribute('data-k'),st)}
 });
 h.el.addEventListener('input',e=>{
  const t=e.target;
  if(t&&t.classList&&t.classList.contains('m-q')){st.q[t.getAttribute('data-k')]=t.value;showOut(h,null);paintCards();paintWarn();paintFoot()}
 });
 h.el.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target&&e.target.classList&&e.target.classList.contains('m-q')){e.preventDefault();save()}});
 h.on('status',()=>{if(!busy){paintCards();paintWarn();paintLast();paintFoot()}});
 h.api('/api/health-history').then(r=>{hist=(r&&r.exits)||{};if(h.alive())paintCards()},e=>{if(e&&e.name==='AbortError')return;histErr=true;if(h.alive())paintCards()});
 paint();
 return h;
}
function confirmBulk(target,draft){
 target=target==='us'?'us':'nl';
 const K=X(target),O=X(otherExit(target));
 const s=WG.state,P=s.exit_policy||{},mv=moving(s.peers,target);
 const back=()=>exitsSettings(draft||_exitsDraft||undefined);
 const h=win({eyebrow:tr('Bulk switch'),title:tr('All {n} to {exit}?',{n:mv.n,exit:K}),size:'md',cls:'m-bulk',footer:' ',
  body:'<div class="m-rows"></div><div class="m-fc"></div>'});
 function paint(){
  const s=WG.state,P=s.exit_policy||{},mv=moving(s.peers,target);
  const who=mv.off?tr('{n}, {k} of them off',{n:WG.count(mv.n,'client'),k:WG.plural(mv.off,OFF)}):WG.count(mv.n,'client');
  patch(h.q('.m-rows'),'<dl class="kv"><dt>'+esc(tr('will move'))+'</dt><dd><b>'+esc(who)+'</b></dd></dl>'+stateRows(target));
  const f=forecast(s.peers,P,target,+s.now||nowS());
  let fc='';
  if(f&&f.perDay>0){
   const r=Math.max(1,Math.round(f.perDay/GIB));
   fc=f.days>=f.monthLeft?tr('At the current rate (~{r} GiB/day) the {exit} quota lasts until the end of the month.',{r,exit:K})
    :P.auto_switch!==false?tr('At the current rate (~{r} GiB/day) the {exit} quota lasts about {d}, then the automatic switch moves them back to {o}.',{r,exit:K,o:O,d:WG.count(Math.max(1,Math.floor(f.days)),'day')})
    :tr('At the current rate (~{r} GiB/day) the {exit} quota lasts about {d}; switching by quota is off, so they stay on {exit}.',{r,exit:K,d:WG.count(Math.max(1,Math.floor(f.days)),'day')});
   fc='<p class="prose">'+esc(fc)+'</p><p class="m-note">'+esc(tr('estimate: traffic of all clients this month ÷ days passed'))+'</p>';
  }
  patch(h.q('.m-fc'),fc+'<p class="m-note">'+esc(tr('Devices reconnect — a break of a few seconds.'))+'</p>');
  const code=bulkBlock(P,target);
  const w=mutationBlock()||(!mv.n?tr('All {n} already on {exit}',{n:mv.total,exit:K})
   :code==='target_exhausted'?tr('{exit} quota is used up',{exit:K}):code==='target_stale'?tr('{exit} is not checked',{exit:K}):code?tr('{exit} is unavailable',{exit:K}):'');
  setFoot(h,foot('',btn('back',tr('Cancel'),{af:true})+btn('go',w||tr('Move {n} to {exit}',{n:mv.n,exit:K}),{cls:'btn-primary',disabled:!!w})));
 }
 h.click(m=>{
  if(m==='back')return back();
  if(m!=='go')return;
  const n=moving(WG.state.peers,target).n;
  _exitsDraft=null;h.close();
  WG.ops.run({key:'exit-all',label:tr('Moving everyone to {exit}',{exit:K}),done:tr('{n} moved to {exit}',{n:WG.count(n,'client'),exit:K}),
   call:live(()=>WG.admin({op:'setexitall',exit:target}).then(explain))});
 });
 h.on('status',paint);
 paint();
 return h;
}

/* ------------------------------------------------------------ move a switched group back (C6) */
function revertSwitch(eventId){
 eventId=+eventId;
 let ev=null,err=false;
 const h=win({eyebrow:tr('Move clients back'),title:tr('Move clients back'),size:'md',cls:'m-revert',footer:closeBtn(tr('Cancel')),
  body:loadingHTML(tr('Loading the switch from the journal…'))});
 function paint(){
  if(err){
   patch(h.body,'<div class="m-out is-failed" role="alert">'+esc(tr('Could not load the switch from the journal.'))+'</div>');
   setFoot(h,foot('',closeBtn()));return;
  }
  if(!ev)return;
  const plan=revertPlan(ev,peersNow()),K=X(plan.to),F=X(plan.from),v=exitView(plan.to);
  h.setEyebrow(plan.reason==='health'||plan.reason==='quota'?tr('After the automatic switch {t}',{t:WG.fmtTime(plan.ts)}):tr('After the switch {t}',{t:WG.fmtTime(plan.ts)}));
  h.setTitle(tr('Move clients back to {exit}?',{exit:K}));
  const t=WG.state.tunnel&&WG.state.tunnel.exits&&WG.state.tunnel.exits[plan.to],since=t&&+t.health_since;
  const band=v.unknown||v.blocked?'<span class="is-'+v.tone+'">'+esc(K+' · '+v.text)+'</span>'
   :'<span class="is-ok">● '+esc(since?tr('{exit} works since {t}',{exit:K,t:WG.fmtTime(since)}):tr('{exit} works',{exit:K}))+'</span> · '
    +esc(tr('quota {u}/{q} GiB ({p}%)',{u:v.u,q:v.q,p:v.pct}));
  patch(h.body,'<div class="sband">'+band+'</div><ul class="ml">'+plan.rows.map(r=>'<li class="is-'+r.state+'"><span class="ml-n">'+esc(r.name)+'</span><span class="ml-s">'
   +esc(r.state==='move'?F+' → '+K:r.state==='deleted'?tr('skipped · client deleted'):tr('skipped · already on {exit}',{exit:K}))+'</span></li>').join('')+'</ul>'
   +'<p class="m-note">'+esc(tr('Devices reconnect — a break of a few seconds.'))+'</p>');
  const w=mutationBlock()||(!plan.count?tr('Nobody to move back'):v.blocked?blockedLabel(v):'');
  setFoot(h,foot('',btn('cancel',tr('Cancel'),{af:true})+btn('go',w||tr('Move {n} back to {exit}',{n:plan.count,exit:K}),{cls:'btn-primary',disabled:!!w})));
 }
 h.click(m=>{
  if(m==='cancel')return h.close();
  if(m!=='go'||!ev)return;
  const plan=revertPlan(ev,peersNow()),K=X(plan.to);
  h.close();
  WG.ops.run({key:'revert:'+eventId,label:tr('Moving {n} back to {exit}',{n:plan.count,exit:K}),done:tr('{n} back on {exit}',{n:WG.count(plan.count,'client'),exit:K}),
   call:live(()=>WG.admin({op:'revertswitch',event_id:eventId}).then(o=>revertOutcome(explain(o),plan)))});
 });
 h.on('status',paint);
 h.api('/api/events?id='+encodeURIComponent(eventId)).then(r=>{
  ev=r&&r.event&&r.event.kind==='exit_switch'?r.event:null;err=!ev;if(h.alive())paint();
 },e=>{if(e&&e.name==='AbortError')return;err=true;if(h.alive())paint()});
 return h;
}

/* ------------------------------------------------------------ split tunnel (C4) */
/* build-split.py writes built_at as local 'YYYY-MM-DD HH:MM' → '12 окт 03:00'. */
function builtText(v){
 const m=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(String(v||''));
 return m?WG.fmtDate(new Date(+m[1],+m[2]-1,+m[3],12).getTime()/1000)+' '+m[4]+':'+m[5]:(v?String(v):'—');
}
function splitSettings(){
 let info=null,orig=null,st=null,busy=false,loadErr='';
 const h=win({eyebrow:tr('For all clients at once'),title:tr('Split tunnel'),size:'lg',cls:'m-split',footer:closeBtn(tr('Cancel')),
  body:loadingHTML(tr('Loading the split settings…'))});
 async function load(){
  loadErr='';patch(h.body,loadingHTML(tr('Loading the split settings…')));
  const out=await WG.admin({op:'splitinfo'});
  if(!h.alive())return;
  if(out.kind!=='ok'&&out.kind!=='warn'){
   loadErr=readError(out);
   patch(h.body,'<div class="m-out is-failed" role="alert">'+esc(loadErr)+'</div><div class="m-retry">'+btn('reload',tr('Retry'),{cls:'btn-outline btn-sm',ic:'refresh'})+'</div>');
   return;
  }
  setInfo(out.data||{});
  st={on:orig.on,text:orig.entries.join('\n')};
  build();
 }
 function setInfo(d){
  info=d;
  orig={on:!!(d.server&&d.server.state==='on'),entries:parseSplit((d.extra||[]).join('\n')).entries};
 }
 function build(){
  h.body._html=null;
  h.body.innerHTML='<div class="sd" aria-hidden="true"></div>'
   +'<div class="trow trow-split"><div class="trow-tx"><div class="trow-t" id="m-t-on">'+esc(tr('Send RU traffic directly'))+'</div><div class="trow-s m-meta"></div></div>'
   +'<button type="button" class="tg m-lockable" role="switch" data-m="on" aria-labelledby="m-t-on" aria-checked="false"></button></div>'
   +'<div class="m-grp"><div class="m-lrow"><label class="field-l" for="m-sx">'+esc(tr('Also direct'))+'</label>'
   +'<span class="m-hint">'+esc(tr('IPv4, subnets or domains · domains turn into IPv4 when the list is built'))+'</span></div>'
   +'<textarea class="ta m-sx m-lockable" id="m-sx" rows="6" spellcheck="false" autocapitalize="none" autocomplete="off" aria-describedby="m-sx-h" placeholder="example.com&#10;203.0.113.0/24"></textarea>'
   +'<div class="m-hint is-err m-sx-h" id="m-sx-h" role="alert" hidden></div></div>'
   +'<div class="m-out-box" hidden></div>';
  h.q('.m-sx').value=st.text;
  paint();
 }
 function parsed(){return parseSplit(st.text)}
 function dirty(){
  const p=parsed();
  return st.on!==orig.on||p.entries.join('\n')!==orig.entries.join('\n');
 }
 function why(){
  const p=parsed();
  if(mutationBlock())return mutationBlock();
  if(p.errors.length)return tr('Fix line {n}',{n:p.errors[0].line});
  if(p.tooMany)return tr('No more than 500 lines');
  if(!dirty())return tr('No changes');
  return'';
 }
 function paint(){
  if(!st)return;
  const m=(info&&info.meta)||{},srv=(info&&info.server)||{};
  const n=v=>Number(+v||0).toLocaleString(WG.lang==='ru'?'ru-RU':'en-US');
  patch(h.q('.sd'),st.on
   ?'<span class="sd-l">'+esc(tr('RU subnets'))+'</span><span class="sd-line"></span><span class="sd-tag">'+esc(tr('entry · RU IP'))+'</span>'
    +'<span class="sd-l">'+esc(tr('everything else'))+'</span><span class="sd-line is-dash"></span><span class="sd-tag is-amber">'+esc(tr('client exit · NL / US'))+'</span>'
   :'<span class="sd-l">'+esc(tr('all traffic'))+'</span><span class="sd-line is-dash"></span><span class="sd-tag is-amber">'+esc(tr('client exit · NL / US'))+'</span>');
  h.q('.m-meta').textContent=tr('{a} RU subnets · {b} in the set · built {d}',{a:n(m.ru_count),b:n(srv.ipset||m.direct_count),d:builtText(m.built_at)});
  h.q('[data-m="on"]').setAttribute('aria-checked',String(!!st.on));
  const p=parsed(),eh=h.q('.m-sx-h'),t=splitErrorText(p.errors)||(p.tooMany?tr('No more than 500 lines. Nothing changed.').replace(/\s*(Nothing changed|Ничего не изменилось)\.$/,''):'');
  eh.hidden=!t;if(eh.textContent!==t)eh.textContent=t;
  h.q('.m-sx').setAttribute('aria-invalid',String(!!t));
  if(busy)return;
  const w=why(),valid=!WG.unknown();
  setFoot(h,'<div class="mf-tools">'+btn('refresh',tr('Refresh the RU list'),{cls:'btn-outline-l',ic:'refresh',disabled:!valid})+'</div>'
   +'<div class="mf-btns">'+btn('cancel',tr('Cancel'))+btn('apply',w||tr('Apply to all'),{cls:'btn-primary',disabled:!!w})+'</div>');
 }
 async function run(o){
  busy=true;setLocked(h,true);showOut(h,null);
  const out=await runInWindow(h,o);
  busy=false;
  if(!h.alive())return out;
  if(out.data&&out.data.server)setInfo(out.data);
  setLocked(h,false);
  if(out.kind!=='ok'&&out.kind!=='warn')showOut(h,out);
  paint();
  return out;
 }
 async function apply(){
  if(busy||why())return;
  const p=parsed(),steps=[];
  const keep=d=>{if(d&&d.server)setInfo(d)};
  if(st.on!==orig.on){const on=st.on;steps.push({text:on?tr('RU direct: on'):tr('RU direct: off'),call:()=>WG.admin({op:'splitserver',split:on}),apply:keep})}
  if(p.entries.join('\n')!==orig.entries.join('\n'))steps.push({text:tr('list: {n}',{n:WG.plural(p.entries.length,LINES)}),call:()=>WG.admin({op:'splitsave',refresh:false,entries:p.entries}),apply:keep});
  const out=await run({key:'split',label:tr('Applying the split tunnel'),done:tr('Split tunnel applied'),busy:tr('Applying…'),call:live(()=>runSteps(steps))});
  if(h.alive()&&(out.kind==='ok'||out.kind==='warn'))h.close();
 }
 h.click(m=>{
  if(m==='reload')return load();
  if(busy)return;
  if(m==='cancel')return h.close();
  if(m==='on'){st.on=!st.on;paint();return}
  if(m==='apply')return apply();
  if(m==='refresh'){
   const entries=orig.entries.slice();
   return run({key:'split-refresh',label:tr('Refreshing the RU list'),done:tr('RU list refreshed'),busy:tr('Applying…'),
    call:live(()=>WG.admin({op:'splitsave',refresh:true,entries}).then(explain))});
  }
 });
 h.el.addEventListener('input',e=>{if(st&&e.target&&e.target.classList&&e.target.classList.contains('m-sx')){st.text=e.target.value;showOut(h,null);paint()}});
 h.on('status',()=>{if(st&&!busy)paint()});
 load();
 return h;
}

/* ------------------------------------------------------------ backup (E4) */
function backupName(now){const d=new Date(now*1000),p=n=>(n<10?'0':'')+n;return'wg-cascade-'+d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'.tar.gz'}
function backup(){
 const n=peersNow().length;
 let file=null,blob=null,url='',busy=false;
 const h=win({title:tr('Config backup'),size:'sm',cls:'m-backup',footer:' ',
  body:'<p class="prose">'+esc(tr('The archive holds the private keys of all {n}, the exit settings and the traffic history. Keep it like a password.',{n:WG.count(n,'client')}))+'</p>'
   +'<p class="m-note m-last"></p><div class="m-step"></div>',
  onClose(){if(url){try{URL.revokeObjectURL(url)}catch(e){}}}});
 h.api('/api/events?kind=admin&limit=200').then(r=>{
  if(!h.alive())return;
  const e=((r&&r.events)||[]).find(x=>x&&x.subject==='export'&&x.data&&x.data.ok!==false);
  h.q('.m-last').textContent=e?tr('last backup: {d}, {a}',{d:WG.fmtDate(e.ts),a:WG.fmtAgo(nowS()-e.ts)}):tr('no backups in the journal');
 },()=>{});
 function step1(){
  patch(h.q('.m-step'),'<div class="m-grp"><label class="field-l" for="m-pw">'+esc(tr('Panel password'))+'</label>'
   +'<input class="input m-pw m-lockable" id="m-pw" type="password" autocomplete="current-password" aria-describedby="m-pw-h" autofocus>'
   +'<div class="m-hint" id="m-pw-h">'+esc(tr('The archive is made after the password check.'))+'</div></div><div class="m-out-box" hidden></div>');
  paintFoot();
 }
 function paintFoot(){
  if(busy||file)return;
  const pw=h.q('.m-pw'),w=mutationBlock()||(pw&&pw.value?'':tr('Enter the password'));
  setFoot(h,foot('',btn('cancel',tr('Cancel'))+btn('make',w||tr('Make the archive'),{cls:'btn-primary',disabled:!!w})));
 }
 function step2(missingList){
  const share=canShareFiles();
  patch(h.q('.m-step'),'<div class="bk-file" role="status"><span class="bk-ic" aria-hidden="true">'+icon('ok',18)+'</span><span><span class="bk-n">'+esc(file.name)+'</span>'
   +'<span class="bk-s">'+esc(tr('archive ready · {s}',{s:WG.fmtBytes(blob.size)}))+'</span>'
   +(missingList.length?'<span class="bk-s is-warn">'+esc(tr('not in the archive: {list}',{list:missingList.join(', ')}))+'</span>':'')+'</span></div>'
   +'<div class="m-stack">'+(share?btn('share',tr('Share / save to Files'),{cls:'btn-primary',ic:'share'})+btn('dl',tr('Download'),{cls:'btn-outline-l',ic:'download'})
    :btn('dl',tr('Download again'),{cls:'btn-outline-l',ic:'download'}))+'</div>'
   +'<p class="m-note m-center">'+esc(tr('the link works while the window is open'))+'</p>');
  setFoot(h,foot('',closeBtn(tr('Done'))));const first=h.q('.m-stack .btn');if(first){try{first.focus()}catch(e){}}
  if(!share)download();
 }
 function download(){
  if(!blob)return;
  if(!url)url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download=file.name;document.body.appendChild(a);a.click();a.remove();
 }
 async function make(){
  const pw=h.q('.m-pw');
  if(busy||!pw||!pw.value||WG.unknown())return;
  busy=true;setLocked(h,true);showOut(h,null);
  const start=Date.now(),f=h.footer;f._html=null;f.classList.add('is-busy');
  f.innerHTML='<div class="mf-busy" role="status"><div class="mf-bt">'+esc(tr('Making the archive…'))+' <span class="mf-time">0:00</span></div><span class="mf-bar" aria-hidden="true"></span></div>'
   +'<div class="mf-btns"><button class="btn is-busy" type="button" disabled>'+esc(tr('Making the archive…'))+'</button></div>';
  try{h.el.focus()}catch(e){}
  const off=h.on('second',()=>{const t=f.querySelector('.mf-time');if(t)t.textContent=WG.fmtClock((Date.now()-start)/1000)});
  const out=await WG.admin({op:'export',password:pw.value});
  off();busy=false;
  if(!h.alive())return;
  f.classList.remove('is-busy');
  const d=out.data||{};
  if((out.kind==='ok'||out.kind==='warn')&&typeof d.archive==='string'){
   try{
    const bin=atob(d.archive),arr=new Uint8Array(bin.length);
    for(let i=0;i<bin.length;i++)arr[i]=bin.charCodeAt(i);
    blob=new Blob([arr],{type:'application/gzip'});
    file={name:backupName(nowS())};
    step2(Array.isArray(d.missing)?d.missing.map(String):[]);
    return;
   }catch(e){}
  }
  setLocked(h,false);
  pw.value='';
  const msg=out.kind==='unknown'?tr('The server did not answer — the archive was not received. Try again.'):readError(out);
  showOut(h,{kind:out.kind==='busy'?'busy':'failed',message:msg});
  paintFoot();
  try{pw.focus()}catch(e){}
 }
 h.click(async m=>{
  if(m==='cancel')return h.close();
  if(m==='make')return make();
  if(m==='dl')return download();
  if(m==='share'&&blob){try{await navigator.share({files:[new File([blob],file.name,{type:'application/gzip'})],title:file.name})}catch(e){}}
 });
 h.el.addEventListener('input',e=>{if(e.target&&e.target.classList&&e.target.classList.contains('m-pw'))paintFoot()});
 h.el.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target&&e.target.classList&&e.target.classList.contains('m-pw')){e.preventDefault();make()}});
 h.on('status',paintFoot);
 step1();
 return h;
}

Object.assign(WG.actions,{addClient,showConfig,editClient,toggleEnabled,deleteClient,switchExit,exitsSettings,revertSwitch,splitSettings,backup});
WG.modalKit={nameProblem,nameText,translit,suggestName,addTerm,termAfter,termText,entryProblem,parseSplit,splitErrorText,wholeGiB,policyBody,
 bulkBlock,moving,forecast,healthBuckets,healthSummary,revertPlan,revertOutcome,runSteps,explain,readError,exitView,confFacts,routeText,backupName};
})();
