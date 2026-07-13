# WG Cascade — dashboard & client manager

A single-file-ish web panel to monitor and manage a **WireGuard cascade VPN**:

```
device ──wg-cl──▶ VDSina (entry, RU) ┬──wg-do──▶ NL exit ──▶ internet
                                    └──wg-us──▶ US exit ──▶ internet
```

Per-client exit is chosen in the panel (`nl` default / `us`); the client config
stays the same — routing is decided on the entry node via fwmark policy rules.
It shows per-client status, cascade tunnel health (both exits), live throughput, and traffic
history, and lets you add / rename / enable / disable / delete clients and fetch
their configs (with QR) — plus a **server-side global split-tunnel** that routes
RU services (Wildberries, Ozon, Kinopoisk, …) directly out of the entry node
instead of through the cascade.

The exit quota controls can move the complete client registry, including
disabled clients, in one confirmed operation. Manual and automatic moves both
require a fresh, healthy, non-exhausted target; there is no force option.
Optional **Auto switch** runs on the server and triggers exactly when
`used >= quota` for calendar-month RX+TX measured from the `wg-do` / `wg-us`
WireGuard peer counters, so the browser need not remain open. Each exit has an
independent whole-GiB quota (500 GiB by default) under **Exit routing**, opened
from either NL/US header quota control. A new month resets the usage window but
does not automatically return clients to NL.

## Design

- **Zero dependencies, no build step.** Pure Python standard library
  (`http.server`) over HTTPS, vanilla JS + CSS on the front end. Runs on a
  1-vCPU / 1 GB box and installs as a PWA that works offline.
- **API + client-side rendering.** The server ships a near-static HTML shell and
  a JSON `/api/status` polled every few seconds; the browser builds the DOM.
- **Privileged-helper security boundary.** The web service runs as the
  unprivileged `wgui` user and can only *read*. Every write (add/rename/enable/
  delete/split) goes through `wg-admin.py`, a narrow root helper invoked via
  `sudo` that validates all input (name/pubkey regex) before touching WireGuard.
- **Auth hardening.** PBKDF2 password hash, per-IP login throttling, capped
  handler threads, HSTS/CSP headers, revocable sessions ("logout all" bumps a
  server-side generation counter), and a fail-fast start if the session-signing
  secret is missing or a placeholder.
- **TLS handshake runs in the worker thread**, not the accept loop — a half-open
  connection from an internet scanner can't wedge the whole server.

## Layout

```
app/                    # deployed verbatim to /opt/wg-ui/ on the entry node
  wg-ui.py              # the HTTPS service (read-only: status, throughput, history)
  wg-admin.py           # root helper (the ONLY thing that writes; called via sudo)
  index.html login.html # HTML shells
  app.css app.js cascade.js clients.js  # front end (bento UI, i18n, charts, PWA)
  exit_model.py         # shared NL/US exit contract (admin + UI + exit-route)
  sw.js manifest.webmanifest icon*.png icon.svg inter.woff2   # PWA + self-hosted font
  build-split.py split-server.sh exit-route.sh refresh-names.sh   # split + per-client exit + helpers
deploy/
  wg-ui.service         # systemd unit (secrets via EnvironmentFile, none inline)
  wg-ui.env.example     # env template — copy to /etc/wg-ui/wg-ui.env and fill in
  wg-split-server.service
  wg-exit-route.service # re-applies per-client US marks on boot
tests/                  # stdlib unit tests (validation, tokens, split-set math)
deploy.sh               # preflight (py_compile + tests) → rsync app/ → restart → health-check, auto-rollback
```

## Secrets & data (never in this repo)

All sensitive and stateful files live on the server, outside the code dir:

| Path | What |
| --- | --- |
| `/etc/wg-ui/wg-ui.env` | `WGUI_SALT`, `WGUI_PASS_PBKDF2` (or legacy `WGUI_PASS_SHA256`), `WGUI_SESSION_SECRET` |
| `/etc/wg-ui/{cert,key}.pem` | TLS cert/key (self-signed) |
| `/etc/wg-ui/clients.json`, `names.json` | client registry |
| `/etc/wg-ui/exit-policy.json` | UI/helper-managed Auto switch and per-exit quotas (`root:wgui`, mode `0640`) |
| `/etc/wg-ui/split-*`, `ru-zone.cache` | generated split-tunnel data |
| `/var/lib/wg-ui/history.db`, `audit.log`, `session.gen` | traffic history + audit trail + session generation |

See `deploy/wg-ui.env.example` for how to generate the auth values.
Save policy changes through **Exit routing**; the privileged helper generates
and updates `exit-policy.json` atomically. Do not hand-edit the policy file.

## Deploy

```sh
./deploy.sh                       # to the default host
WGUI_HOST=root@example ./deploy.sh   # or override
```

Ships `app/` to `/opt/wg-ui/`, fixes perms, restarts `wg-ui.service`, and checks
that `https://localhost/login` answers. First-time server setup (the systemd
unit, env file, cert, and sudoers rule for the helper) is manual — see
`deploy/`.
