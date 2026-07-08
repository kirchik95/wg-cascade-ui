#!/usr/bin/env python3
"""Privileged WireGuard cascade client manager (runs as root via sudo).
Source of truth = /etc/wg-ui/clients.json. Regenerates the [Peer] section of
wg-cl.conf from it, preserving the [Interface] head (kill-switch / routing / MSS),
then `wg syncconf`. Strict input validation — this is the security boundary for
the unprivileged web service.

Usage: wg-admin.py <op> [args]
  list                         -> {clients:[...]}
  add <name> [expires] [exit]  -> {name,ip,pubkey,conf,qr,exit}
  rename <pubkey> <newname>    -> {}
  setenabled <pubkey> <0|1>    -> {}
  setexit <pubkey> <nl|us>     -> {name,exit}
  delete <pubkey>              -> {}
  getconf <pubkey>             -> {name,ip,conf,qr,exit}
  regenerate                   -> {}   (rewrite conf from clients.json, no change)
All output is a single JSON line: {"ok":true,...} or {"ok":false,"error":...}.
"""
import sys, os, re, json, time, base64, fcntl, shutil, tempfile, tarfile, io, subprocess

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
from exit_model import client_exit, normalize_exit as _normalize_exit

CLIENTS_JSON = "/etc/wg-ui/clients.json"
NAMES_JSON   = "/etc/wg-ui/names.json"
SPLIT_EXTRA  = "/etc/wg-ui/split-extra.txt"        # user extras (CIDR/IP/domain), one per line
SPLIT_META   = "/etc/wg-ui/split-meta.json"
BUILD_SPLIT  = "/opt/wg-ui/build-split.py"
SPLIT_SH     = "/opt/wg-ui/split-server.sh"        # server-side global RU-direct toggle
EXIT_SH      = "/opt/wg-ui/exit-route.sh"          # per-client NL/US exit routing
CLIENT_DIR   = "/etc/wireguard/clients"
LOCKFILE     = "/etc/wg-ui/.adminlock"
AUDIT_LOG    = "/var/lib/wg-ui/audit.log"          # append-only admin action log (UI reads it)
AUDIT_MAX_BYTES = 512 * 1024                       # rotate when larger — keep last half
SUBNET_PRE   = "10.10.0."
SERVER_IP    = 1                       # 10.10.0.1 reserved for the server

# Deployment values: defaults below match the reference deploy; override them in
# /etc/wg-ui/wg-ui.env (the same file the web service loads) so the code stays
# portable. sudo strips the environment, hence the file is parsed directly.
def _env_file(path="/etc/wg-ui/wg-ui.env"):
    vals = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    vals[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return vals

_ENV       = _env_file()
IFACE      = _ENV.get("WGUI_IFACE", "wg-cl")
if not re.match(r'^[A-Za-z0-9_-]{1,15}$', IFACE):
    IFACE = "wg-cl"
WG_CONF    = "/etc/wireguard/%s.conf" % IFACE
SERVER_PUB = _ENV.get("WGUI_SERVER_PUB", "")
ENDPOINT   = _ENV.get("WGUI_ENDPOINT", "")
DNS        = _ENV.get("WGUI_CLIENT_DNS", "1.1.1.1")
MTU        = _ENV.get("WGUI_CLIENT_MTU", "1420")
WAN_IFACE  = _ENV.get("WGUI_WAN_IFACE", "")   # used by split-server.sh via env; validated here for deploy sanity

NAME_RE  = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$')
PUB_RE   = re.compile(r'^[A-Za-z0-9+/]{43}=$')
ENTRY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.\-]{0,253}(/\d{1,2})?$')   # CIDR / IP / domain
ENDPOINT_RE = re.compile(r'^[A-Za-z0-9.:_-]{3,253}:\d{1,5}$')
IFACE_RE = re.compile(r'^[A-Za-z0-9_-]{1,15}$')

def die(msg):
    sys.stdout.write(json.dumps({"ok": False, "error": str(msg)}) + "\n")
    sys.exit(1)

def require_deploy_env(need_wan=False):
    """Fail fast when client-config / split deploy values are missing — never bake host IPs."""
    if not PUB_RE.match(SERVER_PUB or ""):
        die("WGUI_SERVER_PUB unset or invalid in /etc/wg-ui/wg-ui.env")
    if not ENDPOINT_RE.match(ENDPOINT or ""):
        die("WGUI_ENDPOINT unset or invalid (host:port) in /etc/wg-ui/wg-ui.env")
    if need_wan:
        if not IFACE_RE.match(WAN_IFACE or ""):
            die("WGUI_WAN_IFACE unset or invalid in /etc/wg-ui/wg-ui.env")
    elif WAN_IFACE and not IFACE_RE.match(WAN_IFACE):
        die("WGUI_WAN_IFACE invalid in /etc/wg-ui/wg-ui.env")

def ok(data=None):
    out = {"ok": True}
    if data:
        out.update(data)
    sys.stdout.write(json.dumps(out) + "\n")
    sys.exit(0)

def run(cmd, inp=None, timeout=15):
    return subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=timeout)

def write_atomic(path, data, mode):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d)
    try:
        os.write(fd, data.encode()); os.close(fd)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

# ------------------------------------------------------------------ conf model
def read_head():
    with open(WG_CONF) as f:
        txt = f.read()
    m = re.search(r'(?m)^\[Peer\]', txt)
    head = txt[:m.start()] if m else txt
    return head.rstrip("\n")

def bootstrap_from_conf():
    with open(WG_CONF) as f:
        txt = f.read()
    clients, name, pub, ip, in_peer = [], None, None, None, False
    for line in txt.splitlines():
        s = line.strip()
        if s == "[Peer]":
            in_peer, name, pub, ip = True, None, None, None
            continue
        if not in_peer:
            continue
        if s.startswith("#"):
            nm = s.lstrip("#").strip()
            if nm:
                name = nm
        elif s.startswith("PublicKey"):
            pub = s.split("=", 1)[1].strip()
        elif s.startswith("AllowedIPs"):
            ip = s.split("=", 1)[1].strip().split("/")[0]
        if pub and ip:
            if not name:
                try: name = "client%d" % (int(ip.split(".")[-1]) - 1)
                except Exception: name = pub[:8]
            clients.append({"name": name, "ip": ip, "pubkey": pub, "enabled": True})
            in_peer = False
    return clients

def load_clients():
    if os.path.exists(CLIENTS_JSON):
        with open(CLIENTS_JSON) as f:
            return json.load(f)
    c = bootstrap_from_conf()
    save_clients(c)
    return c

def save_clients(clients):
    write_atomic(CLIENTS_JSON, json.dumps(clients, indent=1), 0o644)

def peer_block(c):
    return "[Peer]\n# %s\nPublicKey = %s\nAllowedIPs = %s/32\n" % (
        c["name"], c["pubkey"], c["ip"])

def regenerate(clients):
    head = read_head()
    blocks = "\n".join(peer_block(c) for c in clients if c.get("enabled", True))
    new = head + "\n\n" + blocks
    if not new.endswith("\n"):
        new += "\n"
    try:
        shutil.copy2(WG_CONF, WG_CONF + ".bak")
    except Exception:
        pass
    write_atomic(WG_CONF, new, 0o600)
    write_atomic(NAMES_JSON, json.dumps({c["pubkey"]: c["name"] for c in clients}), 0o644)
    strip = run(["wg-quick", "strip", IFACE])
    if strip.returncode != 0:
        die("wg-quick strip failed: " + strip.stderr.strip())
    sync = run(["wg", "syncconf", IFACE, "/dev/stdin"], inp=strip.stdout)
    if sync.returncode != 0:
        die("wg syncconf failed: " + sync.stderr.strip())

# ----------------------------------------------------------------------- helpers
def next_free_ip(clients):
    used = {SERVER_IP}
    for c in clients:
        try: used.add(int(c["ip"].split(".")[-1]))
        except Exception: pass
    for n in range(2, 255):
        if n not in used:
            return SUBNET_PRE + str(n)
    die("no free addresses in subnet")

def genkeypair():
    priv = run(["wg", "genkey"]).stdout.strip()
    pub = run(["wg", "pubkey"], inp=priv).stdout.strip()
    if not priv or not pub:
        die("key generation failed")
    return priv, pub

def client_conf(priv, ip):
    return ("[Interface]\nPrivateKey = %s\nAddress = %s/32\nDNS = %s\nMTU = %s\n\n"
            "[Peer]\nPublicKey = %s\nEndpoint = %s\nAllowedIPs = 0.0.0.0/0\n"
            "PersistentKeepalive = 25\n" % (priv, ip, DNS, MTU, SERVER_PUB, ENDPOINT))

def qr_b64(conf_path, png_path):
    r = run(["qrencode", "-t", "png", "-o", png_path, "-r", conf_path])
    if r.returncode != 0:
        return ""
    try:
        with open(png_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return ""

def find(clients, pub):
    for c in clients:
        if c["pubkey"] == pub:
            return c
    die("client not found")

def paths(name):
    return (os.path.join(CLIENT_DIR, name + ".conf"),
            os.path.join(CLIENT_DIR, name + ".png"))

def audit(op, detail=""):
    """Append-only admin-action log; the web service reads it for the UI Audit view."""
    try:
        try:
            if os.path.getsize(AUDIT_LOG) > AUDIT_MAX_BYTES:
                with open(AUDIT_LOG, "rb") as f:
                    f.seek(max(0, os.path.getsize(AUDIT_LOG) - AUDIT_MAX_BYTES // 2))
                    f.readline()  # drop partial first line
                    keep = f.read()
                with open(AUDIT_LOG, "wb") as f:
                    f.write(keep)
        except OSError:
            pass
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps({"ts": int(time.time()), "op": op, "detail": detail}) + "\n")
        os.chmod(AUDIT_LOG, 0o644)
    except Exception:
        pass

def normalize_exit(val):
    try:
        return _normalize_exit(val)
    except ValueError as e:
        die(str(e))

def sync_exit_routes(flush_ip=None):
    """Re-apply per-client US marks from clients.json; optionally flush conntrack for one IP.

    Always safe to call after client mutations — exit-route.sh sync is idempotent
    and derives state from clients.json (no separate was_us / exit==us branches).
    """
    r = run([EXIT_SH, "sync"], timeout=30)
    if r.returncode != 0:
        die("exit-route sync failed: " + ((r.stderr or r.stdout) or "").strip()[-200:])
    if flush_ip:
        run([EXIT_SH, "flush-ct", flush_ip], timeout=10)

# ---------------------------------------------------------------------- ops
def op_add(name, expires="0", exit_="nl"):
    name = name.strip()
    if not NAME_RE.match(name):
        die("invalid name (allowed: letters, digits, _ - ; max 32)")
    try:
        exp = int(expires)
    except Exception:
        exp = 0
    exit_ = normalize_exit(exit_)
    clients = load_clients()
    if any(c["name"].lower() == name.lower() for c in clients):
        die("a client named '%s' already exists" % name)
    ip = next_free_ip(clients)
    priv, pub = genkeypair()
    conf = client_conf(priv, ip)
    cpath, ppath = paths(name)
    write_atomic(cpath, conf, 0o600)
    qr = qr_b64(cpath, ppath)
    entry = {"name": name, "ip": ip, "pubkey": pub, "enabled": True}
    if exit_ != "nl":
        entry["exit"] = exit_   # absence == nl (keep JSON lean)
    if exp > 0:
        entry["expires"] = exp
    clients.append(entry)
    save_clients(clients)
    regenerate(clients)
    sync_exit_routes()
    audit("add", name + (" (temporary)" if exp else "") + (" → us" if exit_ == "us" else ""))
    ok({"name": name, "ip": ip, "pubkey": pub, "conf": conf, "qr": qr, "exit": exit_})

def op_rename(pub, newname):
    if not PUB_RE.match(pub):
        die("invalid pubkey")
    newname = newname.strip()
    if not NAME_RE.match(newname):
        die("invalid name")
    clients = load_clients()
    c = find(clients, pub)
    if any(x is not c and x["name"].lower() == newname.lower() for x in clients):
        die("a client named '%s' already exists" % newname)
    old = c["name"]
    oc, op_ = paths(old); nc, np_ = paths(newname)
    for src, dst in ((oc, nc), (op_, np_)):
        if os.path.exists(src):
            os.replace(src, dst)
    c["name"] = newname
    save_clients(clients)
    regenerate(clients)
    audit("rename", "%s -> %s" % (old, newname))
    ok()

def op_setenabled(pub, val):
    if not PUB_RE.match(pub):
        die("invalid pubkey")
    if val not in ("0", "1"):
        die("enabled must be 0 or 1")
    clients = load_clients()
    c = find(clients, pub)
    c["enabled"] = (val == "1")
    save_clients(clients)
    regenerate(clients)
    sync_exit_routes(flush_ip=c["ip"] if val == "0" else None)
    audit("enable" if val == "1" else "disable", c["name"])
    ok()

def op_delete(pub):
    if not PUB_RE.match(pub):
        die("invalid pubkey")
    clients = load_clients()
    c = find(clients, pub)
    cpath, ppath = paths(c["name"])
    nm = c["name"]
    ip = c["ip"]
    clients = [x for x in clients if x["pubkey"] != pub]
    save_clients(clients)
    regenerate(clients)
    for p in (cpath, ppath):
        try: os.unlink(p)
        except OSError: pass
    sync_exit_routes(flush_ip=ip)
    audit("delete", nm)
    ok()

def op_setexit(pub, exit_):
    if not PUB_RE.match(pub):
        die("invalid pubkey")
    exit_ = normalize_exit(exit_)
    clients = load_clients()
    c = find(clients, pub)
    old = client_exit(c)
    if old == exit_:
        ok({"name": c["name"], "exit": exit_})
    if exit_ == "nl":
        c.pop("exit", None)   # absence == nl (keep JSON lean)
    else:
        c["exit"] = exit_
    save_clients(clients)
    sync_exit_routes(flush_ip=c["ip"])
    audit("setexit", "%s %s -> %s" % (c["name"], old, exit_))
    ok({"name": c["name"], "exit": exit_})

def op_getconf(pub):
    if not PUB_RE.match(pub):
        die("invalid pubkey")
    clients = load_clients()
    c = find(clients, pub)
    cpath, ppath = paths(c["name"])
    if not os.path.exists(cpath):
        die("config file unavailable for this client")
    with open(cpath) as f:
        conf = f.read()
    qr = qr_b64(cpath, ppath) if len(conf) < 2500 else ""   # QR can't hold a big legacy split config
    ok({"name": c["name"], "ip": c["ip"], "conf": conf, "qr": qr,
        "split": c.get("split", False), "exit": client_exit(c)})

def op_setexpiry(pub, ts):
    if not PUB_RE.match(pub):
        die("invalid pubkey")
    try:
        exp = int(ts)
    except Exception:
        die("bad expiry")
    clients = load_clients()
    c = find(clients, pub)
    if exp > 0:
        c["expires"] = exp
    else:
        c.pop("expires", None)
    save_clients(clients)
    audit("expiry", "%s %s" % (c["name"], "set" if exp else "cleared"))
    ok({"name": c["name"], "expires": c.get("expires", 0)})

def op_expire():
    now = int(time.time())
    clients = load_clients()
    expired = [c for c in clients if c.get("expires", 0) and now > c["expires"] and c.get("enabled", True)]
    if expired:
        for c in expired:
            c["enabled"] = False
        save_clients(clients)
        regenerate(clients)
        sync_exit_routes()
        for c in expired:
            audit("expire", c["name"])
    ok({"expired": [c["name"] for c in expired]})

def op_export():
    """tar.gz of recovery-critical files (server + client keys, registry), returned base64. Sensitive."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in (WG_CONF, "/etc/wireguard/wg-do.conf", "/etc/wireguard/wg-us.conf",
                  CLIENTS_JSON, SPLIT_EXTRA):
            if os.path.exists(p):
                tar.add(p, arcname=os.path.basename(p))
        if os.path.isdir(CLIENT_DIR):
            tar.add(CLIENT_DIR, arcname="clients")
    audit("export", "backup downloaded")
    ok({"archive": base64.b64encode(buf.getvalue()).decode(), "name": "wg-cascade-backup.tar.gz"})

# -------------------------------------------------- global split-tunnel policy
def split_server_status():
    try:
        r = run([SPLIT_SH, "status"], timeout=15)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"state": "off", "ipset": 0, "rules": "no"}

def splitinfo_data():
    meta = {}
    try:
        with open(SPLIT_META) as f:
            meta = json.load(f)
    except Exception:
        pass
    extra = []
    try:
        with open(SPLIT_EXTRA) as f:
            extra = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except Exception:
        pass
    return {"meta": meta, "extra": extra, "server": split_server_status()}

def op_splitserver(val):
    if val not in ("0", "1"):
        die("value must be 0 or 1")
    r = run([SPLIT_SH, "on" if val == "1" else "off"], timeout=60)
    if r.returncode != 0:
        die("split-server toggle failed: " + ((r.stderr or r.stdout) or "").strip()[-200:])
    audit("split-server", "RU-direct " + ("ON" if val == "1" else "OFF"))
    ok(splitinfo_data())

def op_splitinfo():
    ok(splitinfo_data())

def op_splitsave(refresh, entries):
    clean = []
    for e in entries:
        e = e.strip()
        if not e:
            continue
        if not ENTRY_RE.match(e):
            die("invalid entry: %s" % e[:48])
        clean.append(e)
    if len(clean) > 500:
        die("too many custom entries (max 500)")
    write_atomic(SPLIT_EXTRA, ("\n".join(clean) + "\n") if clean else "", 0o644)
    r = run(["python3", BUILD_SPLIT] + (["--refresh"] if refresh == "1" else []), timeout=90)
    if r.returncode != 0:
        die("rebuild failed: " + ((r.stderr or r.stdout) or "").strip()[-200:])
    run([SPLIT_SH, "reload"], timeout=30)          # server-side: repopulate the ipset
    audit("split-list", ("refreshed RU + " if refresh == "1" else "") + "%d custom" % len(clean))
    ok(splitinfo_data())

def main():
    if len(sys.argv) < 2:
        die("no operation")
    op, a = sys.argv[1], sys.argv[2:]
    # Ops that bake client configs or touch routing need deploy values set explicitly.
    if op in ("add", "getconf", "regenerate"):
        require_deploy_env()
    elif op in ("splitserver", "splitsave"):
        require_deploy_env(need_wan=True)
    lock = open(LOCKFILE, "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    if   op == "list":                    ok({"clients": load_clients()})
    elif op == "add"        and len(a) >= 1: op_add(a[0], a[1] if len(a) >= 2 else "0",
                                                    a[2] if len(a) >= 3 else "nl")
    elif op == "setexpiry"  and len(a) >= 2: op_setexpiry(a[0], a[1])
    elif op == "setexit"    and len(a) >= 2: op_setexit(a[0], a[1])
    elif op == "expire":                  op_expire()
    elif op == "export":                  op_export()
    elif op == "rename"     and len(a) >= 2: op_rename(a[0], a[1])
    elif op == "setenabled" and len(a) >= 2: op_setenabled(a[0], a[1])
    elif op == "delete"     and len(a) >= 1: op_delete(a[0])
    elif op == "getconf"    and len(a) >= 1: op_getconf(a[0])
    elif op == "splitinfo":               op_splitinfo()
    elif op == "splitsave"  and len(a) >= 1: op_splitsave(a[0], a[1:])
    elif op == "splitserver" and len(a) >= 1: op_splitserver(a[0])
    elif op == "regenerate":              regenerate(load_clients()); ok()
    else:                                 die("bad operation or arguments")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        die("internal error: %s" % e)
