#!/usr/bin/env python3
"""Privileged WireGuard cascade client manager (runs as root via sudo).
Source of truth = /etc/wg-ui/clients.json. Regenerates the [Peer] section of
wg-cl.conf from it, preserving the [Interface] head (kill-switch / routing / MSS),
then `wg syncconf`. Strict input validation — this is the security boundary for
the unprivileged web service.

Usage: wg-admin.py <op> [args]
  list                         -> {clients:[...]}
  add <name>                   -> {name,ip,pubkey,conf,qr}
  rename <pubkey> <newname>    -> {}
  setenabled <pubkey> <0|1>    -> {}
  delete <pubkey>              -> {}
  getconf <pubkey>             -> {name,ip,conf,qr}
  regenerate                   -> {}   (rewrite conf from clients.json, no change)
All output is a single JSON line: {"ok":true,...} or {"ok":false,"error":...}.
"""
import sys, os, re, json, time, base64, fcntl, shutil, tempfile, tarfile, io, subprocess

WG_CONF      = "/etc/wireguard/wg-cl.conf"
CLIENTS_JSON = "/etc/wg-ui/clients.json"
NAMES_JSON   = "/etc/wg-ui/names.json"
SPLIT_FILE   = "/etc/wg-ui/split-allowedips.txt"   # complement(RU+LAN+extras); built by build-split.py
SPLIT_EXTRA  = "/etc/wg-ui/split-extra.txt"        # user extras (CIDR/IP/domain), one per line
SPLIT_META   = "/etc/wg-ui/split-meta.json"
BUILD_SPLIT  = "/opt/wg-ui/build-split.py"
SPLIT_SH     = "/opt/wg-ui/split-server.sh"        # server-side global RU-direct toggle
CLIENT_DIR   = "/etc/wireguard/clients"
LOCKFILE     = "/etc/wg-ui/.adminlock"
AUDIT_LOG    = "/var/lib/wg-ui/audit.log"          # append-only admin action log (UI reads it)
IFACE        = "wg-cl"
SUBNET_PRE   = "10.10.0."
SERVER_IP    = 1                       # 10.10.0.1 reserved for the server
SERVER_PUB   = "HoGl+zFzr1b6ldatws6PqYr2n74Rk3+e4ZPgf0Fb5F8="
ENDPOINT     = "203.0.113.10:51820"
DNS          = "1.1.1.1"
MTU          = "1420"

NAME_RE  = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$')
PUB_RE   = re.compile(r'^[A-Za-z0-9+/]{43}=$')
ENTRY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.\-]{0,253}(/\d{1,2})?$')   # CIDR / IP / domain

def die(msg):
    sys.stdout.write(json.dumps({"ok": False, "error": str(msg)}) + "\n")
    sys.exit(1)

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

def split_allowed():
    """AllowedIPs for split-tunnel clients = everything except RU + LAN (so those go direct)."""
    try:
        with open(SPLIT_FILE) as f:
            s = f.read().strip()
        return s or "0.0.0.0/0"
    except Exception:
        return "0.0.0.0/0"

def client_conf(priv, ip, split=False):
    allowed = split_allowed() if split else "0.0.0.0/0"
    return ("[Interface]\nPrivateKey = %s\nAddress = %s/32\nDNS = %s\nMTU = %s\n\n"
            "[Peer]\nPublicKey = %s\nEndpoint = %s\nAllowedIPs = %s\n"
            "PersistentKeepalive = 25\n" % (priv, ip, DNS, MTU, SERVER_PUB, ENDPOINT, allowed))

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
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps({"ts": int(time.time()), "op": op, "detail": detail}) + "\n")
        os.chmod(AUDIT_LOG, 0o644)
    except Exception:
        pass

# ---------------------------------------------------------------------- ops
def op_add(name, expires="0"):
    name = name.strip()
    if not NAME_RE.match(name):
        die("invalid name (allowed: letters, digits, _ - ; max 32)")
    try:
        exp = int(expires)
    except Exception:
        exp = 0
    clients = load_clients()
    if any(c["name"].lower() == name.lower() for c in clients):
        die("a client named '%s' already exists" % name)
    ip = next_free_ip(clients)
    priv, pub = genkeypair()
    conf = client_conf(priv, ip)
    cpath, ppath = paths(name)
    write_atomic(cpath, conf, 0o600)
    qr = qr_b64(cpath, ppath)
    entry = {"name": name, "ip": ip, "pubkey": pub, "enabled": True, "split": False}
    if exp > 0:
        entry["expires"] = exp
    clients.append(entry)
    save_clients(clients)
    regenerate(clients)
    audit("add", name + (" (temporary)" if exp else ""))
    ok({"name": name, "ip": ip, "pubkey": pub, "conf": conf, "qr": qr})

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
    audit("enable" if val == "1" else "disable", c["name"])
    ok()

def op_delete(pub):
    if not PUB_RE.match(pub):
        die("invalid pubkey")
    clients = load_clients()
    c = find(clients, pub)
    cpath, ppath = paths(c["name"])
    nm = c["name"]
    clients = [x for x in clients if x["pubkey"] != pub]
    save_clients(clients)
    regenerate(clients)
    for p in (cpath, ppath):
        try: os.unlink(p)
        except OSError: pass
    audit("delete", nm)
    ok()

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
    qr = qr_b64(cpath, ppath) if len(conf) < 2500 else ""   # QR can't hold a big split config
    ok({"name": c["name"], "ip": c["ip"], "conf": conf, "qr": qr, "split": c.get("split", False)})

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
        for c in expired:
            audit("expire", c["name"])
    ok({"expired": [c["name"] for c in expired]})

def op_export():
    """tar.gz of recovery-critical files (server + client keys, registry), returned base64. Sensitive."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in (WG_CONF, "/etc/wireguard/wg-do.conf", CLIENTS_JSON, SPLIT_EXTRA):
            if os.path.exists(p):
                tar.add(p, arcname=os.path.basename(p))
        if os.path.isdir(CLIENT_DIR):
            tar.add(CLIENT_DIR, arcname="clients")
    audit("export", "backup downloaded")
    ok({"archive": base64.b64encode(buf.getvalue()).decode(), "name": "wg-cascade-backup.tar.gz"})

def op_setsplit(pub, val):
    if not PUB_RE.match(pub):
        die("invalid pubkey")
    if val not in ("0", "1"):
        die("split must be 0 or 1")
    clients = load_clients()
    c = find(clients, pub)
    cpath, ppath = paths(c["name"])
    if not os.path.exists(cpath):
        die("client config file unavailable")
    priv = ""
    with open(cpath) as f:
        for line in f:
            if line.strip().startswith("PrivateKey"):
                priv = line.split("=", 1)[1].strip(); break
    if not priv:
        die("could not read client private key")
    c["split"] = (val == "1")
    conf = client_conf(priv, c["ip"], c["split"])   # only the client .conf changes; server peer is untouched
    write_atomic(cpath, conf, 0o600)
    save_clients(clients)
    qr = qr_b64(cpath, ppath) if len(conf) < 2500 else ""
    ok({"name": c["name"], "ip": c["ip"], "split": c["split"], "conf": conf, "qr": qr})

# -------------------------------------------------- global split-tunnel policy
def _read_priv(cpath):
    with open(cpath) as f:
        for line in f:
            if line.strip().startswith("PrivateKey"):
                return line.split("=", 1)[1].strip()
    return ""

def _regen_split(clients):
    """Rewrite the .conf of every split-enabled client with the current AllowedIPs."""
    cnt = 0
    for c in clients:
        if not c.get("split"):
            continue
        cpath, _ = paths(c["name"])
        if not os.path.exists(cpath):
            continue
        priv = _read_priv(cpath)
        if priv:
            write_atomic(cpath, client_conf(priv, c["ip"], True), 0o600); cnt += 1
    return cnt

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
    return {"meta": meta, "extra": extra, "server": split_server_status(),
            "split_clients": sum(1 for c in load_clients() if c.get("split"))}

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
    n = _regen_split(load_clients())               # legacy client-side split (none after revert)
    audit("split-list", ("refreshed RU + " if refresh == "1" else "") + "%d custom" % len(clean))
    d = splitinfo_data(); d["regenerated"] = n
    ok(d)

def op_splitbulk(val):
    if val not in ("0", "1"):
        die("value must be 0 or 1")
    clients = load_clients()
    want = (val == "1")
    cnt = 0
    for c in clients:
        if c.get("split", False) != want:
            c["split"] = want
            cpath, _ = paths(c["name"])
            if os.path.exists(cpath):
                priv = _read_priv(cpath)
                if priv:
                    write_atomic(cpath, client_conf(priv, c["ip"], want), 0o600)
            cnt += 1
    save_clients(clients)
    ok({"changed": cnt, "split": want})

def main():
    if len(sys.argv) < 2:
        die("no operation")
    op, a = sys.argv[1], sys.argv[2:]
    lock = open(LOCKFILE, "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    if   op == "list":                    ok({"clients": load_clients()})
    elif op == "add"        and len(a) >= 1: op_add(a[0], a[1] if len(a) >= 2 else "0")
    elif op == "setexpiry"  and len(a) >= 2: op_setexpiry(a[0], a[1])
    elif op == "expire":                  op_expire()
    elif op == "export":                  op_export()
    elif op == "rename"     and len(a) >= 2: op_rename(a[0], a[1])
    elif op == "setenabled" and len(a) >= 2: op_setenabled(a[0], a[1])
    elif op == "delete"     and len(a) >= 1: op_delete(a[0])
    elif op == "getconf"    and len(a) >= 1: op_getconf(a[0])
    elif op == "setsplit"   and len(a) >= 2: op_setsplit(a[0], a[1])
    elif op == "splitinfo":               op_splitinfo()
    elif op == "splitsave"  and len(a) >= 1: op_splitsave(a[0], a[1:])
    elif op == "splitbulk"  and len(a) >= 1: op_splitbulk(a[0])
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
