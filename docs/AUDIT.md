# WG Cascade / wg-ui — сводный аудит

Дата сведения: 13 июля 2026  
Источники: [аудит 9 июля](audit-2026-07-09.md) · [аудит 10 июля](AUDIT_REPORT.md)  
Область: UX, frontend, a11y, backend, безопасность, WireGuard-маршрутизация, PWA, deploy, эксплуатация, тесты.

## Итог

Для zero-dependency панели одного оператора фундамент сильный: граница привилегий `wgui` + sudo `wg-admin.py`, PBKDF2/HMAC-сессии, CSRF, CSP/HSTS, кэшированный `/api/status`, инкрементальный UI, preflight-тесты перед деплоем.

Главный риск — не RCE/XSS, а **целостность состояния**: registry, WireGuard live state, firewall/routing и UI могут разойтись после частичного сбоя.

Подтверждённых P0 и удалённого RCE не найдено. XSS через `built_at` — локальная щель при компрометации helper/файла (P1, однострочный фикс).

| Метрика | Значение |
|---------|----------|
| P1 | 14 |
| P2 | 18 |
| P3 | 3 |
| UI-техника | 14/20 |
| Nielsen UX | 24/40 |
| Unit-тесты | 42/42 |
| UI-детектор | 0 находок |

### Архитектура

| Компонент | Роль |
|-----------|------|
| `app/wg-ui.py` | HTTPS API, sampler, статус, SQLite |
| `app/auth.py` | пароль, сессии, CSRF, throttling |
| `app/wg-admin.py` | root-helper (единственная привилегированная точка) |
| `app/split-server.sh`, `exit-route.sh` | ipset / iptables / policy routing |
| `app/app.js`, `clients.js`, `cascade.js` | UI, polling, клиенты, каскад |
| `/etc/wg-ui` | конфиг и registry |
| `/etc/wireguard` | WG-конфиги и ключи |
| `/var/lib/wg-ui` | history, session generation, audit |

### Что сделано хорошо

- Auth: PBKDF2, HMAC-сессии, generation revoke, Secure/HttpOnly/SameSite=Strict, CSRF на POST.
- Headers: CSP, HSTS, nosniff, frame deny, referrer policy; лимиты body/timeout/threads.
- Commands без `shell=True`; строгая regex-валидация в helper.
- Status из sampler-кэша, не `wg dump` на каждый запрос; инкрементальные карточки.
- Zero runtime deps; secrets вне каталога приложения; deploy snapshot + rollback при inactive service.
- UX: предметный каскад, loading/empty/offline/stale/degraded, focus rings, reduced motion, safe-area.

---

## P1 — до следующего production-релиза

### 1. Audit log: symlink-атака через root-helper

`docs/SETUP.md:62,69` · `wg-admin.py:223-240`

`/var/lib/wg-ui` принадлежит `wgui`. Скомпрометированный web-процесс может подменить `audit.log` symlink-ом; root-helper следует за ним и делает `chmod` по pathname.

**Фикс:** root-owned каталог; `O_APPEND|O_CREAT|O_NOFOLLOW`; `fstat` (owner, regular file, nlink); `0640 root:wgui`; без `chmod` по path после open.

### 2. Deploy не гарантирует root ownership кода

`deploy.sh:23,28` · `SETUP.md:169-171`

`rsync -a` может сохранить UID workstation. Mode меняется, owner — нет. При доступном UID скомпрометированный пользователь может править `wg-admin.py` / `exit_model.py` и запускать через sudo.

**Фикс:** `--chown=root:root`, immutable release dir, проверка owner/mode/hash перед активацией.

### 3. Admin-операции не транзакционны

`wg-admin.py:154-178, 261-360`

Registry/конфиг пишутся до успешного `wg syncconf` и sync маршрутов. При ошибке: клиент «удалён» в UI, но жив в kernel; add оставляет ключи без конфига; registry ≠ live ≠ routing.

**Фикс:** desired state во временных файлах → validate → apply live → verify → commit registry; rollback всех артефактов. Долгосрочно: operation journal + idempotent reconciler.

### 4. US routing fail-open → NL

`exit-route.sh:97-112` · `wg-admin.py:344-360`

Если `wg-us` недоступен, марки очищаются и скрипт возвращает успех — клиенты с US уходят в default NL без явного сигнала.

**Фикс:** fail-closed (blackhole/unreachable) или видимый confirmed fallback; `setexit` не ok до проверки фактического маршрута.

### 5. Приоритет RU-direct vs US зависит от порядка iptables

`split-server.sh:43-47` · `exit-route.sh:70-73` · `SETUP.md:259-263`

Оба PREROUTING-правила пишут mark без terminal action — побеждает последний применённый rule, не задокументированный `ip rule`.

**Фикс:** единая decision chain с terminal actions или атомарный nftables ruleset.

### 6. Routing-скрипты: ложный успех и race-окна

`split-server.sh:7,36-70` · `exit-route.sh:8,27-28,43-113,105-110`

- нет надёжного `set -e` / проверки каждого шага;
- `ipset flush` до repopulate — окно пустого набора (RU → cascade);
- нет файла `split-direct.txt` → flush без add;
- битый `clients.json` → `sys.exit(0)` и молчаливый сброс US;
- flush_marks → add_mark — окно без US-роутинга.

**Фикс:** строгий режим + postconditions; `ipset restore` во временный набор + `swap`; guard на отсутствующий/битый вход; rollback частичных правил; file lock.

### 7. Health-check принимает сломанный релиз

`deploy.sh:19-41` · `wg-ui.py:64-71`

Rollback только при inactive service. `curl` без `--fail`; `/healthz` всегда `ok: true` даже при мёртвом sampler/DB.

**Фикс:** liveness vs readiness; `curl --fail-with-body`; проверка sampler freshness / DB / helper; rollback trap после snapshot; re-check восстановленного релиза. Первый деплой не должен падать на отсутствующем `/opt/wg-ui`.

### 8. XSS: `built_at` без `esc()`

`app.js:522`

`m.built_at` из `split-meta.json` в `innerHTML` без экранирования. При компрометации helper/файла — исполнение в админ-сессии.

**Фикс:** одна строка — `esc(m.built_at)`.

### 9. Истёкшие временные клиенты отключаются с задержкой

`wg-ui.py:269-279` · `wg-admin.py:393-405`

Expiry ~раз в час в sampler, не на startup; ошибка helper игнорируется.

**Фикс:** minutely systemd timer + startup; проверка результата; readiness fail при overdue enabled clients.

### 10. Контраст WCAG нарушен

`app.css:2-10,65-75,197-205,321-325,356-359,448-450`

Измерено: white/accent 2.53:1; white/danger 3.35:1; alert text 4.15–4.37:1; control border 1.26–1.43:1. Нужно 4.5:1 текст, 3:1 controls.

**Фикс:** theme-specific tokens + автотесты контраста.

### 11. Keyboard / dialog / chart / mobile a11y

`app.css:126-138,401-404,433` · `app.js:320-348,376-395,603-614` · `index.html:53-56`

Touch targets < 44px (фильтры, ghost, password toggle); tooltips только `:hover` (на mobile отключены); modal backdrop не `inert`; `role="menu"` без ARIA keyboard pattern; chart только pointer; password toggle без корректного focus-visible.

**Фикс:** targets ≥44px, mobile labels, `inert`, menu или disclosure, data table для charts.

### 12. Admin request: ложное состояние UI

`app.js:366-370,410-412,536-540,588-590` · `clients.js:162-169`

Нет единого wrapper: `response.ok`, parse, timeout; кнопки остаются disabled; «Sign out all» редиректит на login даже при 401/500.

**Фикс:** wrapper с timeout, typed errors, `finally`, подтверждение `{ok:true}` до success flow.

### 13. Нет HTTP keep-alive

Handler не задаёт `protocol_version = "HTTP/1.1"` → HTTP/1.0: каждый poll `/api/status` = новый TCP + полный TLS-handshake на 1 vCPU.

**Фикс:** одна строка `protocol_version = "HTTP/1.1"` (`Content-Length` уже есть).

### 14. Root systemd units без hardening

`wg-split-server.service`, `wg-exit-route.service` — без `ProtectSystem`, `PrivateTmp`, `CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW`.

**Фикс:** минимальный hardening-набор + ограничение capabilities.

---

## P2 — следующий обязательный этап

### Безопасность и auth

| # | Проблема | Где | Фикс |
|---|----------|-----|------|
| 1 | Один фактор на публичной VPN-админке; сессия 7 дней без idle / per-session revoke | `auth.py` | TOTP или mTLS/IP allowlist; idle-timeout; индивидуальный revoke |
| 2 | Self-signed TLS приучает кликать сквозь warning | cert / SETUP | Let's Encrypt DNS-01 или pin fingerprint |
| 3 | Export всех private keys без step-up; архив не шифрован | `wg-admin.py:407-418`, `app.js:439-446` | re-auth + age/openssl enc + audit requester |
| 4 | CSP `style-src 'unsafe-inline'`; cookie без `__Host-`; CSRF статичен до generation | `wg-ui.py`, `auth.py` | ужесточить headers / ротация CSRF |
| 5 | Admin API: не object JSON, expiry→0, `"false"` truthy | `wg-ui.py:713-757` | exact schema, strict types, reject unknown |

### Routing / данные / monitoring

| # | Проблема | Где | Фикс |
|---|----------|-----|------|
| 6 | Внешний RU feed без лимитов/delta — напрямую в privileged routing | `build-split.py` | last-known-good, size/coverage bounds, confirm anomalies; graceful fail без кэша |
| 7 | Только liveness, нет readiness | `wg-ui.py:64-71` | `/readyz` → 503 по sampler/DB/helper/WG/routing |
| 8 | Egress probe: HTTP body может отметить US healthy; нет `--fail` / IP parse | `wg-ui.py:195-220` | curl --fail + `ipaddress` + обязательный expected IP |
| 9 | Monthly quota по exit неверна после NL↔US | `wg-ui.py:405-407,466-495` | хранить effective exit с каждым delta |
| 10 | Environment contract разъехался (web overrides / helper hardcode / unit без env) | `wg-ui.py`, `wg-admin.py`, `exit-route.sh`, units | единый валидируемый config |
| 11 | Нет scheduled backup; UI-export ≠ DR (нет history/audit/TLS/units) | deploy / ops | encrypted off-host backup `/etc/wg-ui`+`/var/lib/wg-ui`, restore drill |
| 12 | Нет мониторинга/алертов | ops | внешняя проба + alert на `tunnel.state=down` |

### Frontend / PWA

| # | Проблема | Где | Фикс |
|---|----------|-----|------|
| 13 | Polling race: parallel fetch, out-of-order | `app.js:349-364`, `clients.js:206-210` | in-flight / AbortController / sequence / backoff |
| 14 | i18n: ~15 EN-строк в RU UI (`Degraded`, loading, split, delete confirm…) | `app.js`, `clients.js` | единый catalog + interpolation; lang на login |
| 15 | SW: ручной bump `wgui-shell-v22`; кеш любого non-API GET (в т.ч. auth HTML) | `sw.js` | allowlist assets; версия при деплое; честный offline contract |
| 16 | `inter.woff2` 352 KB (~77% статики) | fonts | subset latin+cyrillic нужных весов (−200 KB+) |
| 17 | Mobile: скрыты подписи/egress; hierarchy не status-first | `app.css:414-433` | один health verdict, вторичные метрики ниже |

### Backend perf / deploy / tests

| # | Проблема | Где | Фикс |
|---|----------|-----|------|
| 18 | Sampler: wg dump + curl-пробы + SQLite + expire последовательно (до ~40 с) | `wg-ui.py:243-305` | egress-пробы в отдельный тред |
| — | Тройная JSON-сериализация статуса | `wg-ui.py:378-385` | кэш готовых bytes |
| — | Deploy in-place rsync → смесь старых/новых файлов | `deploy.sh` | versioned release + atomic symlink |
| — | Нет CI; нет тестов shell/deploy/routing/HTTP e2e/helper failure injection | `tests/` | GitHub Actions + boundary layers |
| — | Несогласованные systemd hardening у `wg-ui.service`; юниты не деплоятся | deploy / units | hardening + деплой units |

---

## P3 — полировка

1. **Визуальная иерархия:** cascade verdict и affected exits — доминирующие; host/quota/chart — вторичные; меньше равнозначных pills/shimmer.
2. **Гигиена репо:** `.tmp*`, `.DS_Store` в `.gitignore`; `LICENSE`; довести `AGENTS.md` по спеке; убрать мёртвый `refresh-names.sh` из README.
3. **Мелочи кода:** мёртвый CSS; `_pv` leak; `window.__cf` globals; `audit_tail` падает целиком на битой строке; только IPv4 listen; реэкспорт auth для тестов; `time.sleep` на failed login держит worker.

---

## Рекомендуемый порядок работ

### Этап 1 — privilege boundary
1. Audit symlink  
2. Root ownership + immutable deploy  
3. Проверка live permissions на production  
4. `esc(built_at)`  

### Этап 2 — целостность control plane
1. Транзакционный helper  
2. Единый атомарный routing ruleset + fail-closed/fallback contract  
3. Guards/swap для ipset; строгие exit-коды скриптов  
4. Expiry → отдельный timer  

### Этап 3 — deploy и monitoring
1. Readiness `/readyz`  
2. Health-triggered rollback + HTTP fail  
3. Versioned releases + Git SHA в health  
4. HTTP/1.1 keep-alive  
5. Внешние alerts + scheduled encrypted backup  

### Этап 4 — test boundaries
1. CI: unittest + py_compile + bash -n + ShellCheck  
2. Failure injection helper  
3. Network-namespace routing tests  
4. HTTP auth/CSRF integration  
5. Browser a11y smoke  

### Этап 5 — UX и hardening
1. Контраст, keyboard, touch targets  
2. Полная RU localization  
3. Надёжный frontend request wrapper + polling  
4. Step-up + шифрование export  
5. Безопасный PWA cache; subset шрифта; TOTP/mTLS  

---

## Быстрые победы (эффект / усилия)

1. `protocol_version = "HTTP/1.1"`  
2. `esc(m.built_at)`  
3. Health-check: `--fail` + rollback  
4. `ipset restore` + swap + file guards  
5. Дозаполнить RU-словарь (~15 строк)  
6. Subset `inter.woff2`  
7. AbortController / in-flight в `tick()`  
8. `--chown=root:root` в deploy  
9. GitHub Actions на unittest  
10. O_NOFOLLOW + fstat для audit.log  

---

## Выполненные проверки (аудит 10 июля)

- `python3 -m unittest discover -s tests` — 42/42  
- `python3 -m py_compile app/*.py`  
- `bash -n app/*.sh deploy.sh`  
- `node --check app/*.js`  
- manifest JSON parse  
- детерминированный UI-scan `index.html` / `login.html` → `[]`  
- статический разбор privilege boundary  

## Ограничения

Не подтверждено в live environment:

- реальные owner/mode под `/opt/wg-ui`  
- production systemd security score  
- WireGuard/iptables failure injection  
- полный browser reflow/zoom pass  
- поведение на медленной сети  
- restore из backup  

Эти пункты — acceptance criteria следующего релиза.
