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
  setexitall <nl|us> <manual|quota|health> -> {exit,changed,source_counts}
  setexitpolicy <0|1 auto> <nl-gib> <us-gib> <0|1 failover> -> {auto_switch,health_failover,quotas_gib}
  delete <pubkey>              -> {}
  getconf <pubkey>             -> {name,ip,conf,qr,exit}
  regenerate                   -> {}   (rewrite conf from clients.json, no change)
  blockipv6                    -> {updated}  (add ::/0 to full-tunnel client configs)
  export                       -> {archive,name}  (full recovery bundle, base64 tar.gz)
All output is a single JSON line: {"ok":true,...} or {"ok":false,"error":...}.
"""
import sys, os, re, json, time, base64, fcntl, grp, shutil, tempfile, tarfile, io, subprocess, sqlite3, platform

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
from exit_model import client_exit, normalize_exit as _normalize_exit
import exit_policy

CLIENTS_JSON = "/etc/wg-ui/clients.json"
EXIT_POLICY  = "/etc/wg-ui/exit-policy.json"
NAMES_JSON   = "/etc/wg-ui/names.json"
SPLIT_EXTRA  = "/etc/wg-ui/split-extra.txt"        # user extras (CIDR/IP/domain), one per line
SPLIT_META   = "/etc/wg-ui/split-meta.json"
BUILD_SPLIT  = "/opt/wg-ui/build-split.py"
SPLIT_SH     = "/opt/wg-ui/split-server.sh"        # server-side global RU-direct toggle
EXIT_SH      = "/opt/wg-ui/exit-route.sh"          # per-client NL/US exit routing
CLIENT_DIR   = "/etc/wireguard/clients"
LOCKFILE     = "/etc/wg-ui/.adminlock"
AUDIT_DIR    = "/var/log/wg-ui"                    # root-owned: wgui can read but not swap entries
AUDIT_LOG    = os.path.join(AUDIT_DIR, "audit.log")  # append-only admin action log (UI reads it)
LEGACY_AUDIT = "/var/lib/wg-ui/audit.log"          # pre-2026-10 location (wgui-owned dir)
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

def write_atomic(path, data, mode, owner=None):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d)
    try:
        payload = data if isinstance(data, bytes) else data.encode()
        remaining = memoryview(payload)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("atomic write made no progress")
            remaining = remaining[written:]
        os.fsync(fd)
        os.fchmod(fd, mode)
        if owner is not None:
            os.fchown(fd, owner[0], owner[1])
        os.close(fd)
        fd = None
        os.replace(tmp, path)
    except Exception:
        if fd is not None:
            try: os.close(fd)
            except OSError: pass
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
    sync_kernel()

def sync_kernel():
    """Load wg-cl.conf peers into the kernel; raises RuntimeError on failure."""
    strip = run(["wg-quick", "strip", IFACE])
    if strip.returncode != 0:
        raise RuntimeError("wg-quick strip failed: " + strip.stderr.strip())
    sync = run(["wg", "syncconf", IFACE, "/dev/stdin"], inp=strip.stdout)
    if sync.returncode != 0:
        raise RuntimeError("wg syncconf failed: " + sync.stderr.strip())

def _txn_files():
    return ((CLIENTS_JSON, 0o644), (WG_CONF, 0o600), (NAMES_JSON, 0o644))

def _snapshot_files():
    snap = []
    for path, mode in _txn_files():
        try:
            with open(path, "rb") as f:
                snap.append((path, mode, f.read()))
        except FileNotFoundError:
            snap.append((path, mode, None))
    return snap

def _restore_files(snap):
    for path, mode, data in snap:
        if data is None:
            try: os.unlink(path)
            except FileNotFoundError: pass
        else:
            write_atomic(path, data, mode)

def apply_clients(clients, regen=True, on_fail=None):
    """Commit a registry change to disk, kernel peers and exit routes as one unit.

    Any failure restores clients.json / wg-cl.conf / names.json byte-for-byte,
    re-applies the restored state, runs on_fail (undo side files), and dies with
    an error that says whether the rollback itself worked.
    """
    snap = _snapshot_files()
    try:
        save_clients(clients)
        if regen:
            regenerate(clients)
        run_exit_sync_or_raise()
    except Exception as apply_error:
        try:
            _restore_files(snap)
            if regen:
                sync_kernel()
            run_exit_sync_or_raise()
        except Exception as rollback_error:
            die("apply failed: %s; rollback failed: %s" % (apply_error, rollback_error))
        finally:
            if on_fail:
                try: on_fail()
                except Exception: pass
        die("apply failed and rolled back: %s" % apply_error)

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
            "[Peer]\nPublicKey = %s\nEndpoint = %s\nAllowedIPs = 0.0.0.0/0, ::/0\n"
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

def _audit_dir_fd(audit_dir, gid):
    """Open the audit dir, creating it root:wgui 0750; refuse anything but a root-owned real dir."""
    try:
        os.mkdir(audit_dir, 0o750)
    except FileExistsError:
        pass
    dfd = os.open(audit_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    st = os.fstat(dfd)
    if st.st_uid != os.geteuid() or st.st_mode & 0o022:
        os.close(dfd)
        raise PermissionError("audit dir must be owned by the helper user and not group/world-writable")
    if st.st_gid != gid or st.st_mode & 0o777 != 0o750:
        os.fchown(dfd, -1, gid)
        os.fchmod(dfd, 0o750)
    return dfd

def _audit_gid():
    try:
        return grp.getgrnam("wgui").gr_gid
    except KeyError:
        return os.getegid()

def _read_nofollow(path, dir_fd=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    with os.fdopen(fd, "rb") as f:
        return f.read()

def audit(op, detail="", audit_dir=None):
    """Append-only admin-action log; the web service reads it for the UI Audit view.

    Runs as root, so every path step refuses symlinks (O_NOFOLLOW + dir fd) and
    rotation swaps a fresh file in via rename inside the root-owned directory.
    Failures go to stderr instead of vanishing silently.
    """
    audit_dir = audit_dir or AUDIT_DIR
    name = os.path.basename(AUDIT_LOG)
    line = (json.dumps({"ts": int(time.time()), "op": op, "detail": detail}) + "\n").encode()
    dfd = None
    try:
        gid = _audit_gid()
        dfd = _audit_dir_fd(audit_dir, gid)
        try:
            os.stat(name, dir_fd=dfd, follow_symlinks=False)
            exists = True
        except FileNotFoundError:
            exists = False
        keep = b""
        if not exists:
            try:  # one-time carry-over from the old wgui-owned location
                keep = _read_nofollow(LEGACY_AUDIT)[-AUDIT_MAX_BYTES // 2:]
            except OSError:
                keep = b""
        else:
            st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            if st.st_size > AUDIT_MAX_BYTES:
                data = _read_nofollow(name, dir_fd=dfd)
                keep = data[-AUDIT_MAX_BYTES // 2:]
                keep = keep[keep.find(b"\n") + 1:]  # drop partial first line
        if not exists or keep:
            tmp = name + ".tmp"
            try:
                os.unlink(tmp, dir_fd=dfd)
            except FileNotFoundError:
                pass
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640, dir_fd=dfd)
            with os.fdopen(fd, "wb") as f:
                os.fchown(f.fileno(), -1, gid)
                os.fchmod(f.fileno(), 0o640)
                f.write(keep)
            os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        fd = os.open(name, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=dfd)
        with os.fdopen(fd, "ab") as f:
            st = os.fstat(f.fileno())
            if st.st_uid != os.geteuid() or st.st_nlink != 1:
                raise PermissionError("audit log ownership/link count unexpected")
            f.write(line)
    except Exception as e:
        sys.stderr.write("wg-admin: audit write failed: %s\n" % e)
    finally:
        if dfd is not None:
            os.close(dfd)

def normalize_exit(val):
    try:
        return _normalize_exit(val)
    except ValueError as e:
        die(str(e))

def run_exit_sync_or_raise():
    r = run([EXIT_SH, "sync"], timeout=30)
    if r.returncode != 0:
        raise RuntimeError("exit-route sync failed: " + ((r.stderr or r.stdout) or "").strip()[-200:])

def flush_exit_conntrack(ip):
    run([EXIT_SH, "flush-ct", ip], timeout=10)

def sync_exit_routes(flush_ip=None):
    """Re-apply per-client US marks from clients.json; optionally flush conntrack for one IP.

    Always safe to call after client mutations — exit-route.sh sync is idempotent
    and derives state from clients.json (no separate was_us / exit==us branches).
    """
    try:
        run_exit_sync_or_raise()
    except RuntimeError as exc:
        die(str(exc))
    if flush_ip:
        flush_exit_conntrack(flush_ip)

def policy_owner_ids():
    euid = os.geteuid()
    try:
        gid = grp.getgrnam("wgui").gr_gid
    except KeyError:
        if euid == 0:
            raise RuntimeError("wgui group not found")
        return euid, os.getegid()
    if euid != 0:
        return euid, os.getegid()
    return 0, gid

def setexitpolicy_data(enabled, nl_gib, us_gib, failover):
    if enabled not in ("0", "1"):
        raise ValueError("auto switch must be 0 or 1")
    if failover not in ("0", "1"):
        raise ValueError("health failover must be 0 or 1")
    policy = exit_policy.policy_from_gib(enabled == "1", nl_gib, us_gib, failover == "1")
    owner = policy_owner_ids()
    write_atomic(EXIT_POLICY, json.dumps(policy, indent=1) + "\n", 0o640, owner=owner)
    return {
        "auto_switch": policy["auto_switch"],
        "health_failover": policy["health_failover"],
        "quotas_gib": {
            key: policy["quota_bytes"][key] // exit_policy.GIB
            for key in exit_policy.EXITS
        },
    }

def setexitall_data(target, reason):
    target = _normalize_exit(target)
    if reason not in ("manual", "quota", "health"):
        raise ValueError("invalid switch reason")
    with open(CLIENTS_JSON, "rb") as f:
        original_bytes = f.read()
    clients = json.loads(original_bytes)
    changed = []
    source_counts = {key: 0 for key in exit_policy.EXITS}
    for client in clients:
        old = client_exit(client)
        source_counts[old] += 1
        if old == target:
            continue
        changed.append(client)
        if target == "nl":
            client.pop("exit", None)
        else:
            client["exit"] = "us"
    if not changed:
        return {"exit": target, "changed": 0, "source_counts": source_counts}
    try:
        save_clients(clients)
        run_exit_sync_or_raise()
    except Exception as apply_error:
        try:
            write_atomic(CLIENTS_JSON, original_bytes, 0o644)
            run_exit_sync_or_raise()
        except Exception as rollback_error:
            raise RuntimeError(
                "apply failed: %s; rollback failed: %s" % (apply_error, rollback_error)
            )
        raise RuntimeError("apply failed and rolled back: %s" % apply_error)
    for client in changed:
        if not client.get("enabled", True):
            continue
        try:
            flush_exit_conntrack(client["ip"])
        except Exception:
            # Registry and verified routes are already committed. Conntrack
            # cleanup is best-effort and must not report that switch as failed.
            pass
    direction = "%s -> %s" % (
        "mixed" if source_counts[target] else ("us" if target == "nl" else "nl"),
        target,
    )
    audit("setexitall", "%s %s %d client(s)" % (reason, direction, len(changed)))
    return {"exit": target, "changed": len(changed), "source_counts": source_counts}

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

    def drop_files():
        for p_ in (cpath, ppath):
            try: os.unlink(p_)
            except OSError: pass
    apply_clients(clients, on_fail=drop_files)
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
    moved = []
    for src, dst in ((oc, nc), (op_, np_)):
        if os.path.exists(src):
            os.replace(src, dst)
            moved.append((src, dst))
    c["name"] = newname

    def unmove():
        for src, dst in reversed(moved):
            os.replace(dst, src)
    apply_clients(clients, on_fail=unmove)
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
    apply_clients(clients)
    if val == "0":
        flush_exit_conntrack(c["ip"])
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
    apply_clients(clients)
    for p in (cpath, ppath):        # only after the peer is really gone
        try: os.unlink(p)
        except OSError: pass
    flush_exit_conntrack(ip)
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
        sync_exit_routes()      # retry reconciles kernel state with the registry
        ok({"name": c["name"], "exit": exit_})
    if exit_ == "nl":
        c.pop("exit", None)   # absence == nl (keep JSON lean)
    else:
        c["exit"] = exit_
    apply_clients(clients, regen=False)
    flush_exit_conntrack(c["ip"])
    audit("setexit", "%s %s -> %s" % (c["name"], old, exit_))
    ok({"name": c["name"], "exit": exit_})

def op_setexitall(target, reason):
    ok(setexitall_data(target, reason))

def op_setexitpolicy(enabled, nl_gib, us_gib, failover):
    ok(setexitpolicy_data(enabled, nl_gib, us_gib, failover))

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
        apply_clients(clients)
        for c in expired:
            audit("expire", c["name"])
    ok({"expired": [c["name"] for c in expired]})

IPV6_BLOCK_OLD = "AllowedIPs = 0.0.0.0/0\n"
IPV6_BLOCK_NEW = "AllowedIPs = 0.0.0.0/0, ::/0\n"

def op_blockipv6():
    """Route IPv6 into the tunnel (where wg-cl drops it) so it cannot bypass the cascade.

    Only full-tunnel configs are touched; legacy client-side split configs with
    long AllowedIPs lists are left alone. Devices must re-import their config.
    """
    updated = []
    if os.path.isdir(CLIENT_DIR):
        for fn in sorted(os.listdir(CLIENT_DIR)):
            if not fn.endswith(".conf"):
                continue
            path = os.path.join(CLIENT_DIR, fn)
            with open(path) as f:
                conf = f.read()
            if IPV6_BLOCK_OLD in conf:
                write_atomic(path, conf.replace(IPV6_BLOCK_OLD, IPV6_BLOCK_NEW), 0o600)
                updated.append(fn[:-5])
    if updated:
        audit("ipv6-block", "%d client configs" % len(updated))
    ok({"updated": updated})

# Recovery bundle: (source path, archive name). Old names stay stable for restores
# made from earlier bundles; everything new goes under extra/.
_EXPORT_FILES = (
    ("WG_CONF", None), ("/etc/wireguard/wg-do.conf", None), ("/etc/wireguard/wg-us.conf", None),
    ("CLIENTS_JSON", None), ("SPLIT_EXTRA", None), ("EXIT_POLICY", None),
    ("/etc/amnezia/amneziawg/wg-do.conf", "awg-wg-do.conf"),
    ("/etc/amnezia/amneziawg/wg-us.conf", "awg-wg-us.conf"),
    ("NAMES_JSON", "extra/names.json"), ("SPLIT_META", "extra/split-meta.json"),
    ("/etc/wg-ui/split-server.state", "extra/split-server.state"),
    ("/etc/wg-ui/wg-ui.env", "extra/wg-ui.env"),
    ("/etc/wg-ui/cert.pem", "extra/cert.pem"), ("/etc/wg-ui/key.pem", "extra/key.pem"),
    ("/etc/sudoers.d/wg-ui", "extra/sudoers.wg-ui"),
    ("/etc/systemd/system/wg-ui.service", "extra/units/wg-ui.service"),
    ("/etc/systemd/system/wg-split-server.service", "extra/units/wg-split-server.service"),
    ("/etc/systemd/system/wg-exit-route.service", "extra/units/wg-exit-route.service"),
)
HISTORY_DB = "/var/lib/wg-ui/history.db"

def _tool_version(cmd):
    try:
        r = run(cmd, timeout=5)
        return (r.stdout or r.stderr).strip().splitlines()[0][:120] if r.returncode == 0 else None
    except Exception:
        return None

def op_export():
    """tar.gz recovery bundle (keys, registry, panel secrets/TLS, history, units), base64.

    Sensitive. A manifest.json lists every expected file and whether it was found,
    so a restore can tell a deliberate absence from a silently missing file.
    """
    buf = io.BytesIO()
    manifest = {"created": int(time.time()), "files": [],
                "versions": {"kernel": platform.release(),
                             "wg": _tool_version(["wg", "--version"]),
                             "awg": _tool_version(["awg", "--version"])}}
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for src, arc in _EXPORT_FILES:
            path = globals().get(src, src)
            name = arc or os.path.basename(path)
            present = os.path.isfile(path)
            if present:
                tar.add(path, arcname=name)
            manifest["files"].append({"name": name, "source": path, "present": present})
        if os.path.isdir(CLIENT_DIR):
            tar.add(CLIENT_DIR, arcname="clients")
        manifest["files"].append({"name": "clients/", "source": CLIENT_DIR,
                                  "present": os.path.isdir(CLIENT_DIR)})
        # Consistent SQLite copy (WAL-safe) via the backup API, not a raw file copy.
        db_present = False
        if os.path.isfile(HISTORY_DB):
            with tempfile.TemporaryDirectory() as td:
                tmp_db = os.path.join(td, "history.db")
                try:
                    src_db = sqlite3.connect("file:%s?mode=ro" % HISTORY_DB, uri=True, timeout=10)
                    dst_db = sqlite3.connect(tmp_db)
                    with dst_db:
                        src_db.backup(dst_db)
                    src_db.close(); dst_db.close()
                    tar.add(tmp_db, arcname="extra/history.db")
                    db_present = True
                except sqlite3.Error as e:
                    manifest["history_error"] = str(e)[:200]
        manifest["files"].append({"name": "extra/history.db", "source": HISTORY_DB, "present": db_present})
        data = json.dumps(manifest, indent=1).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size, info.mtime, info.mode = len(data), int(time.time()), 0o600
        tar.addfile(info, io.BytesIO(data))
    missing = [f["name"] for f in manifest["files"] if not f["present"]]
    audit("export", "backup downloaded")
    ok({"archive": base64.b64encode(buf.getvalue()).decode(), "name": "wg-cascade-backup.tar.gz",
        "missing": missing})

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
    r = run([SPLIT_SH, "reload"], timeout=30)      # server-side: repopulate the ipset
    if r.returncode != 0:
        die("split reload failed: " + ((r.stderr or r.stdout) or "").strip()[-200:])
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
    elif op == "setexitall" and len(a) == 2: op_setexitall(a[0], a[1])
    elif op == "setexitpolicy" and len(a) == 4: op_setexitpolicy(a[0], a[1], a[2], a[3])
    elif op == "expire":                  op_expire()
    elif op == "export":                  op_export()
    elif op == "blockipv6":               op_blockipv6()
    elif op == "rename"     and len(a) >= 2: op_rename(a[0], a[1])
    elif op == "setenabled" and len(a) >= 2: op_setenabled(a[0], a[1])
    elif op == "delete"     and len(a) >= 1: op_delete(a[0])
    elif op == "getconf"    and len(a) >= 1: op_getconf(a[0])
    elif op == "splitinfo":               op_splitinfo()
    elif op == "splitsave"  and len(a) >= 1: op_splitsave(a[0], a[1:])
    elif op == "splitserver" and len(a) >= 1: op_splitserver(a[0])
    elif op == "regenerate":              apply_clients(load_clients()); ok()
    else:                                  die("bad operation or arguments")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        die("internal error: %s" % e)
