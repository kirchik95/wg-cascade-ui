# From-scratch setup

Bring the panel up on a fresh Debian/Ubuntu **entry node** (the box that runs the
cascade's `wg-cl` interface — VDSina in the reference deploy). Everything below is
run as `root`. Reference values in comments match the live deploy; substitute your
own IP.

```sh
IP=203.0.113.10        # this node's public IP (used for the TLS cert)
```

---

## 0. Prerequisite: the cascade already exists

The panel **reads and manages** the cascade — it does not create it. Before you
start, this node must already have the two WireGuard tunnels up via `wg-quick@`:

- **`wg-cl`** — device → this entry node (clients connect here; the panel adds/
  removes their `[Peer]` blocks in `/etc/wireguard/wg-cl.conf`).
- **`wg-do`** — this entry node → the NL exit node (default cascade hop).
- **`wg-us`** — (optional, dual-exit) this entry node → the US exit node.

So `/etc/wireguard/wg-cl.conf` and `wg-do.conf` must exist and be active
(`wg show wg-cl` works). For dual-exit, `wg-us.conf` must also be up. Building
the cascade itself (keys, kill-switch, policy routing) is out of scope here.

---

## 1. Packages

Pure Python stdlib — **no pip packages**. Only system tools:

```sh
apt update
apt install -y python3 wireguard-tools ipset conntrack qrencode openssl
# reference: python3 3.12, wireguard-tools 1.0.x, ipset 7.x, conntrack 1.4.x, qrencode 4.x
```

`ipset` + `conntrack` are only needed if you use the server-side split-tunnel
(step 9); the rest are required.

---

## 2. Service user

Unprivileged system user that runs the read-only web service (it can only *read*;
all writes go through the root helper via sudo — step 7):

```sh
useradd --system --home /home/wgui --shell /usr/sbin/nologin wgui
# reference: uid 999, gid 988, nologin
```

---

## 3. Directories & ownership

```sh
install -d -o root -g root  -m 755 /opt/wg-ui          # code (world-readable)
install -d -o root -g wgui  -m 750 /etc/wg-ui          # config + secrets (wgui reads)
install -d -o wgui -g wgui  -m 750 /var/lib/wg-ui      # history.db + audit.log
```

| Dir | Owner | Mode | Holds |
| --- | --- | --- | --- |
| `/opt/wg-ui` | `root:root` | 755 | the code (from `app/`) |
| `/etc/wg-ui` | `root:wgui` | 750 | `cert.pem`, `key.pem`, `wg-ui.env`, `clients.json`, split data |
| `/var/lib/wg-ui` | `wgui:wgui` | 750 | `history.db` (service), `audit.log` (helper, as root) |

---

## 4. Deploy the code

From your workstation (has the repo):

```sh
git clone git@github.com:kirchik95/wg-cascade-ui.git
cd wg-cascade-ui
WGUI_HOST=root@$IP ./deploy.sh          # scp app/* → /opt/wg-ui, chmod +x, (re)start
```

`deploy.sh` also restarts the service and health-checks it — but the service unit,
env, cert and sudoers below don't exist yet on a first run, so on the very first
deploy just copy the files and continue:

```sh
scp app/* root@$IP:/opt/wg-ui/ && ssh root@$IP 'chmod 755 /opt/wg-ui/*.py /opt/wg-ui/*.sh'
```

---

## 5. TLS certificate (self-signed)

10-year self-signed cert, CN + SAN = this node's IP (browsers warn once, then you
accept it):

```sh
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout /etc/wg-ui/key.pem -out /etc/wg-ui/cert.pem \
  -subj "/CN=${IP}" -addext "subjectAltName=IP:${IP}"

chown root:wgui /etc/wg-ui/cert.pem /etc/wg-ui/key.pem
chmod 644 /etc/wg-ui/cert.pem      # public
chmod 640 /etc/wg-ui/key.pem       # wgui reads it to serve TLS; not world-readable
```

---

## 6. Credentials & env file

The password is never stored — only a PBKDF2-HMAC-SHA256 hash (200k iterations).
Generate the secrets and write `/etc/wg-ui/wg-ui.env`:

```sh
SALT=$(openssl rand -hex 16)
SECRET=$(openssl rand -hex 32)
HASH=$(python3 -c 'import hashlib,getpass,sys;
print("200000$"+hashlib.pbkdf2_hmac("sha256",getpass.getpass("panel password: ").encode(),sys.argv[1].encode(),200000).hex())' "$SALT")

cat > /etc/wg-ui/wg-ui.env <<EOF
WGUI_USER=admin
WGUI_SALT=${SALT}
WGUI_PASS_PBKDF2=${HASH}
WGUI_SESSION_SECRET=${SECRET}
WGUI_PORT=443
WGUI_CERT=/etc/wg-ui/cert.pem
WGUI_KEY=/etc/wg-ui/key.pem
WGUI_IFACE=wg-cl
WGUI_EXIT_IP=198.51.100.10
EOF

chown root:wgui /etc/wg-ui/wg-ui.env
chmod 640 /etc/wg-ui/wg-ui.env
```

The service **refuses to start** if `WGUI_SESSION_SECRET` is missing, shorter
than 24 chars, or a placeholder — a guessable signing key would let anyone mint
a valid session cookie. Old env files with `WGUI_PASS_SHA256` (legacy salted
SHA-256) still work as a fallback; migrate by adding `WGUI_PASS_PBKDF2` as above.

`WGUI_EXIT_IP` is the expected cascade egress IP — the panel probes it to show the
tunnel as healthy. See `deploy/wg-ui.env.example` for every tunable and its
default; the block above is the minimum. The same file also carries the values
`wg-admin.py` bakes into generated client configs (`WGUI_SERVER_PUB`,
`WGUI_ENDPOINT`, `WGUI_CLIENT_DNS`, `WGUI_CLIENT_MTU`) — set them if your deploy
differs from the reference. (The live box also sets `WGUI_NAMES`, a leftover
from `refresh-names.sh` — the panel itself ignores it.)

---

## 7. sudoers — the security boundary

The web service runs as `wgui` and can do exactly three privileged things: read the
two `wg` dumps, and invoke the root helper. Nothing else.

```sh
cat > /etc/sudoers.d/wg-ui <<'EOF'
wgui ALL=(root) NOPASSWD: /usr/bin/wg show wg-cl dump
wgui ALL=(root) NOPASSWD: /usr/bin/wg show wg-do dump
wgui ALL=(root) NOPASSWD: /usr/bin/wg show wg-us dump
wgui ALL=(root) NOPASSWD: /usr/bin/python3 /opt/wg-ui/wg-admin.py *
EOF
chmod 440 /etc/sudoers.d/wg-ui
visudo -c -f /etc/sudoers.d/wg-ui        # must print "parsed OK"
```

`wg-admin.py` (root, 755, in `/opt/wg-ui`) is what actually mutates WireGuard — it
validates every name/pubkey against a regex before touching
`/etc/wireguard/wg-cl.conf`. Keep it root-owned and never writable by `wgui`.

> If you only have the NL exit yet, the `wg-us` line is harmless (the panel treats a
> missing iface as "US down"). Add it once `wg-us` exists so dual-exit health works.

---

## 8. systemd service

```sh
scp deploy/wg-ui.service root@$IP:/etc/systemd/system/wg-ui.service   # from the repo
# then on the server:
systemctl daemon-reload
systemctl enable --now wg-ui.service
systemctl status wg-ui.service --no-pager
```

The unit runs as `wgui`, loads secrets via `EnvironmentFile=/etc/wg-ui/wg-ui.env`
(no secrets inline), gets `CAP_NET_BIND_SERVICE` to bind 443, and — crucially —
sets `ReadWritePaths=/etc/wireguard /etc/wg-ui` so the sudo'd helper can write the
cascade config despite `ProtectSystem=full`. `NoNewPrivileges=false` is required so
sudo can escalate.

---

## 9. Server-side split-tunnel (optional)

Routes RU services (Wildberries, Ozon, Kinopoisk, …) directly out of the entry node
instead of through the cascade — one global toggle for all clients. Needs `ipset` +
`conntrack` (step 1).

`split-server.sh` and `build-split.py` already shipped with `app/` in step 4.

```sh
# on the server:
python3 /opt/wg-ui/build-split.py                 # downloads the RU zone, writes /etc/wg-ui/split-*
# install the boot-persistence unit (from the repo):
scp deploy/wg-split-server.service root@$IP:/etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wg-split-server.service    # applies ipset+iptables, re-applies on boot
```

After that, toggle it from the panel (**Split** button). The reference
`wg-split-server.service` is a `oneshot`/`RemainAfterExit` unit ordered
`After=wg-quick@wg-cl wg-quick@wg-do`, `ExecStart=/opt/wg-ui/split-server.sh apply`,
`ExecStop=… down`. Details of the routing (ipset `ru-direct` + fwmark `0x64` + `ip
rule` + masquerade out the WAN iface, kill-switch preserved) are in the project
notes.

> The kill-switch and policy routing live in the cascade, not this repo — the split
> script edits iptables/`ip rule` on a live box. Snapshot `iptables-save` +
> `ip rule` before enabling.

---

## 9b. Dual exit (NL + US) — per-client routing

Clients always dial the same entry (`wg-cl`). The panel assigns each client an
exit (`nl` default via `wg-do`, or `us` via `wg-us`) using fwmark policy routing
on the entry node. Client `.conf` files do **not** change.

### Prerequisites

- `wg-us` already up (`wg-quick@wg-us`), peer to the US VPS, with NAT/forwarding
  on the US side (same pattern as `wg-do`).
- Kill-switch on the entry node must allow `FORWARD`/`MASQUERADE` for `wg-us`
  (the `exit-route.sh` script also inserts ACCEPT/MASQUERADE rules above the DROP).

### Enable

```sh
# on the entry node — snapshot first
iptables-save > /root/iptables.before-dual-exit
ip rule > /root/ip-rule.before-dual-exit

# env: expected US egress IP (panel health check)
# edit /etc/wg-ui/wg-ui.env and add, e.g.:
#   WGUI_US_IFACE=wg-us
#   WGUI_US_EXIT_IP=198.51.100.20

# sudoers: allow reading wg-us (see step 7 — add the wg-us dump line)

scp deploy/wg-exit-route.service root@$IP:/etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wg-exit-route.service
/opt/wg-ui/exit-route.sh status
```

Priority order on the entry node:

1. RU-direct split (`fwmark 0x64`, pri 1000) — unchanged
2. US clients (`fwmark 0x65`, pri 1100, table 65 → `wg-us`)
3. Everyone else → default cascade via `wg-do` (NL)

Changing a client's exit in the panel calls `setexit` → `exit-route.sh sync` and
flushes that client's conntrack so existing flows don't stick to the old path.

---

## 10. Verify

```sh
# on the server
systemctl is-active wg-ui.service
curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1/login     # -> 200

# from anywhere
curl -sk -o /dev/null -w '%{http_code}\n' https://$IP/login           # -> 200
```

Then open `https://<IP>/` in a browser, accept the self-signed cert once, and log
in with `admin` + the password from step 6.

---

## Updating later

Edit under `app/` in the repo, commit (rollback point), then:

```sh
./deploy.sh          # preflight (py_compile + unit tests) → rsync app/ → restart → health-check
```

`deploy.sh` snapshots the previous version to `/opt/wg-ui.prev` on the server
and rolls back automatically if the service fails to come up after restart.

CSS/JS/HTML changes need no restart (served per-request from disk — just hard-
refresh, or bump the `wgui-shell-vN` cache in `sw.js`). `wg-ui.py` changes need
`systemctl restart wg-ui`. `wg-admin.py` is re-exec'd per call.

---

## Security notes

- This is a **public, write-capable** panel — it can create and revoke VPN access.
  Its only defenses are TLS + form login + CSRF + a signed session cookie. Use a
  strong password and consider binding writes to the VPN subnet if you harden it.
- **Do not enable UFW blindly** — it manages the same iptables chains the cascade's
  kill-switch relies on and can break the VPN or lock you out of SSH. The single
  open port (443) is the intended surface.
- The self-signed cert triggers a one-time browser warning; that's expected. For a
  trusted cert, point a hostname at the IP and use `nip.io` + Let's Encrypt.
