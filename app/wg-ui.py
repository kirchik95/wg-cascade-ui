#!/usr/bin/env python3
"""WireGuard cascade dashboard + client manager.
HTTPS, form login (signed session cookie), light/dark theme.
Read: per-client status, cascade (wg-do) tunnel health, live throughput chart.
Write (via narrow root helper /opt/wg-ui/wg-admin.py): add / rename / enable /
disable / delete clients, fetch config+QR. CSRF-protected.
"""
import os, ssl, json, time, base64, hmac, hashlib, sqlite3, subprocess, threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

USER        = os.environ.get("WGUI_USER", "admin")
SALT        = os.environ.get("WGUI_SALT", "")
PASS_SHA    = os.environ.get("WGUI_PASS_SHA256", "")          # legacy scheme, fallback
PASS_PBKDF2 = os.environ.get("WGUI_PASS_PBKDF2", "")          # "iterations$hexdigest", preferred
SECRET      = os.environ.get("WGUI_SESSION_SECRET", "").encode()
PORT        = int(os.environ.get("WGUI_PORT", "443"))
CERT        = os.environ.get("WGUI_CERT", "/etc/wg-ui/cert.pem")
KEY         = os.environ.get("WGUI_KEY", "/etc/wg-ui/key.pem")
CLIENTS     = os.environ.get("WGUI_CLIENTS", "/etc/wg-ui/clients.json")
IFACE       = os.environ.get("WGUI_IFACE", "wg-cl")
DO_IFACE    = os.environ.get("WGUI_DO_IFACE", "wg-do")
EXIT_IP     = os.environ.get("WGUI_EXIT_IP", "198.51.100.10")
SRC_IP      = os.environ.get("WGUI_SRC_IP", "10.10.0.1")
ONLINE_S    = int(os.environ.get("WGUI_ONLINE_SECS", "180"))
SESSION_TTL = int(os.environ.get("WGUI_SESSION_TTL", str(7 * 24 * 3600)))
SAMPLE_S    = int(os.environ.get("WGUI_SAMPLE_SECS", "5"))
ADMIN       = ["sudo", "-n", "/usr/bin/python3", "/opt/wg-ui/wg-admin.py"]
DB          = os.environ.get("WGUI_DB", "/var/lib/wg-ui/history.db")
SPLIT_STATE = os.environ.get("WGUI_SPLIT_STATE", "/etc/wg-ui/split-server.state")
AUDIT_LOG   = os.environ.get("WGUI_AUDIT", "/var/lib/wg-ui/audit.log")
GEN_FILE    = os.environ.get("WGUI_GEN", "/var/lib/wg-ui/session.gen")
MAX_CONN    = int(os.environ.get("WGUI_MAX_CONN", "64"))

# ---------------------------------------------------------------- auth helpers
def creds_ok(u, p):
    if PASS_PBKDF2:
        try:
            it, hx = PASS_PBKDF2.split("$", 1)
            dk = hashlib.pbkdf2_hmac("sha256", p.encode(), SALT.encode(), int(it)).hex()
            good = hmac.compare_digest(dk, hx)
        except Exception:
            good = False
    else:   # legacy: single salted SHA-256 (kept so existing env files still work)
        ph = hashlib.sha256((SALT + p).encode()).hexdigest()
        good = hmac.compare_digest(ph, PASS_SHA) and bool(PASS_SHA)
    return hmac.compare_digest(u, USER) and good

def _b64e(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")
def _b64d(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def session_gen():
    """Server-side session generation; bumping it invalidates every issued token."""
    try:
        with open(GEN_FILE) as f:
            return int(f.read().strip() or 0)
    except Exception:
        return 0

def bump_session_gen():
    g = session_gen() + 1
    with open(GEN_FILE, "w") as f:
        f.write(str(g))
    return g

def make_token(user, exp):
    msg = ("%s|%d|%d" % (user, exp, session_gen())).encode()
    return _b64e(msg) + "." + _b64e(hmac.new(SECRET, msg, hashlib.sha256).digest())

def check_token(tok):
    try:
        m, s = tok.split(".", 1)
        msg = _b64d(m)
        if not hmac.compare_digest(_b64d(s), hmac.new(SECRET, msg, hashlib.sha256).digest()):
            return None
        user, exp, gen = msg.decode().split("|")
        if int(gen) != session_gen():
            return None
        return user if int(exp) > int(time.time()) else None
    except Exception:
        return None

def csrf_for(user):
    msg = "csrf|%s|%d" % (user, session_gen())
    return hmac.new(SECRET, msg.encode(), hashlib.sha256).hexdigest()[:32]

# per-IP login throttle: max LOGIN_MAX failures per LOGIN_WIN, then locked out
LOGIN_MAX, LOGIN_WIN = 5, 900
_fails = {}                 # ip -> [fail_ts, ...]
_fails_lock = threading.Lock()

def login_blocked(ip):
    now = time.time()
    with _fails_lock:
        ts = [t for t in _fails.get(ip, []) if now - t < LOGIN_WIN]
        if ts:
            _fails[ip] = ts
        else:
            _fails.pop(ip, None)
        return len(ts) >= LOGIN_MAX

def login_failed(ip):
    with _fails_lock:
        if len(_fails) > 1000:      # bound memory under scanner floods
            _fails.clear()
        _fails.setdefault(ip, []).append(time.time())

def login_ok(ip):
    with _fails_lock:
        _fails.pop(ip, None)

# ------------------------------------------------------------- data collection
def _dump(iface):
    r = subprocess.run(["sudo", "-n", "/usr/bin/wg", "show", iface, "dump"],
                       capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "wg show failed").strip())
    return r.stdout.strip().split("\n")

def load_registry():
    try:
        with open(CLIENTS) as f:
            return json.load(f)
    except Exception:
        return None   # not bootstrapped yet

def clients_status():
    reg = load_registry()
    live = {}
    try:
        for ln in _dump(IFACE)[1:]:
            p = ln.split("\t")
            if len(p) >= 8:
                live[p[0]] = {"ep": "" if p[2] == "(none)" else p[2], "ip": p[3].split("/")[0],
                              "hs": int(p[4]), "rx": int(p[5]), "tx": int(p[6])}
    except Exception:
        pass
    now = int(time.time())
    if reg is None:   # registry not bootstrapped yet -> derive from live peers
        reg = []
        for pk, v in live.items():
            ip = v.get("ip", "")
            try:
                nm = "client%d" % (int(ip.split(".")[-1]) - 1)
            except Exception:
                nm = pk[:8]
            reg.append({"name": nm, "ip": ip, "pubkey": pk, "enabled": True})
    mu = usage_month()
    sp = client_sparks()
    out = []
    for c in reg:
        lv = live.get(c["pubkey"])
        en = c.get("enabled", True)
        hs = lv["hs"] if lv else 0
        age = now - hs if hs else -1
        m = mu.get(c["pubkey"], {})
        out.append({"name": c["name"], "ip": c.get("ip", ""), "pubkey": c["pubkey"],
                    "enabled": en, "endpoint": lv["ep"] if lv else "",
                    "age": age, "online": bool(en and 0 <= age < ONLINE_S),
                    "rx": lv["rx"] if lv else 0, "tx": lv["tx"] if lv else 0,
                    "mrx": m.get("rx", 0), "mtx": m.get("tx", 0),
                    "expires": c.get("expires", 0),
                    "spark": sp.get(c["pubkey"], [])[-24:]})
    out.sort(key=lambda x: (not x["online"], not x["enabled"], x["name"].lower()))
    return out

def wg_do():
    try:
        lines = _dump(DO_IFACE)
        if len(lines) < 2:
            return None
        p = lines[1].split("\t")
        hs = int(p[4])
        return {"age": (int(time.time()) - hs) if hs else -1,
                "up": bool(hs and (int(time.time()) - hs) < ONLINE_S)}
    except Exception:
        return None

# background sampler: throughput ring buffer + cached egress probe + host stats
_samples = deque(maxlen=120)          # (t, total_rx, total_tx)
_psamples = deque(maxlen=30)          # (t, {pubkey: (rx, tx)}) — for per-client sparklines
_egress = {"ok": False, "seen": None, "at": 0}
_host = {"cpu": 0, "prev": None}      # cpu% (computed from /proc/stat deltas)
_lock = threading.Lock()

def _read_cpu():
    with open("/proc/stat") as f:
        v = list(map(int, f.readline().split()[1:8]))   # user nice sys idle iowait irq softirq
    return v[3] + v[4], sum(v)                           # idle(+iowait), total

def host():
    try:
        with open("/proc/loadavg") as f:
            la = f.read().split()
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, rest = line.partition(":")
                mem[k] = int(rest.split()[0]) * 1024      # bytes
        used = mem["MemTotal"] - mem.get("MemAvailable", mem.get("MemFree", 0))
        with open("/proc/uptime") as f:
            up = int(float(f.read().split()[0]))
        with _lock:
            cpu = _host["cpu"]
        return {"cpu": cpu, "cores": os.cpu_count() or 1,
                "mem_used": used, "mem_total": mem["MemTotal"],
                "load": [float(la[0]), float(la[1]), float(la[2])], "uptime": up}
    except Exception:
        return None

EGRESS_URLS = ["https://api.ipify.org", "https://icanhazip.com"]

def _probe_egress():
    for url in EGRESS_URLS:      # fallback so one dead IP service can't fake "degraded"
        try:
            r = subprocess.run(["curl", "-s", "--max-time", "8", "--interface", SRC_IP, url],
                               capture_output=True, text=True, timeout=10)
            ip = r.stdout.strip()
            if ip:
                return (ip == EXIT_IP), ip
        except Exception:
            pass
    return False, None

def _sampler():
    i = 0
    while True:
        per = {}; eps = {}
        try:
            rx = tx = 0
            for ln in _dump(IFACE)[1:]:
                p = ln.split("\t")
                if len(p) >= 7:
                    r, t = int(p[5]), int(p[6])
                    rx += r; tx += t; per[p[0]] = (r, t)
                if len(p) >= 8:
                    eps[p[0]] = ("" if p[2] == "(none)" else p[2], int(p[4]))
            with _lock:
                ts = int(time.time())
                _samples.append((ts, rx, tx))
                if per:
                    _psamples.append((ts, per))
        except Exception:
            pass
        if eps:
            try: log_connections(eps)
            except Exception: pass
        if per and i % 12 == 0:        # persist per-client usage every ~60s
            try:
                record_usage(per)
            except Exception:
                pass
        if i and i % 720 == 0:         # auto-disable expired clients ~hourly
            try: call_admin(["expire"])
            except Exception: pass
        try:                           # entry-node CPU% from /proc/stat deltas
            idle, total = _read_cpu()
            with _lock:
                if _host["prev"]:
                    pi, pt = _host["prev"]; dt = total - pt
                    if dt > 0:
                        _host["cpu"] = max(0, min(100, round(100 * ((dt) - (idle - pi)) / dt)))
                _host["prev"] = (idle, total)
        except Exception:
            pass
        if i % 5 == 0:                 # egress probe every ~25s
            ok_, ip = _probe_egress()
            with _lock:
                _egress.update(ok=ok_, seen=ip, at=int(time.time()))
        i += 1
        time.sleep(SAMPLE_S)

def throughput():
    with _lock:
        s = list(_samples)
    series = []
    for a, b in zip(s, s[1:]):
        dt = b[0] - a[0]
        if dt <= 0:
            continue
        series.append({"t": b[0],
                       "down": max(0, b[1] - a[1]) // dt,
                       "up": max(0, b[2] - a[2]) // dt})
    cur = series[-1] if series else {"down": 0, "up": 0}
    return {"series": series[-60:], "cur": cur}

def client_sparks():
    """{pubkey: [bytes/sec total throughput, ...]} over the recent per-client samples."""
    with _lock:
        s = list(_psamples)
    out = {}
    for a, b in zip(s, s[1:]):
        dt = b[0] - a[0]
        if dt <= 0:
            continue
        pa, pb = a[1], b[1]
        for pub, cur in pb.items():
            prev = pa.get(pub)
            rate = max(0, (cur[0] - prev[0]) + (cur[1] - prev[1])) // dt if prev else 0
            out.setdefault(pub, []).append(rate)
    return out

def tunnel():
    do = wg_do()
    with _lock:
        eg = dict(_egress)
    wg_up = bool(do and do["up"])
    state = "up" if eg["ok"] else ("degraded" if wg_up else "down")
    return {"state": state, "wg_up": wg_up, "wg_age": do["age"] if do else -1,
            "exit_seen": eg["seen"], "exit_ip": EXIT_IP,
            "checked_age": (int(time.time()) - eg["at"]) if eg["at"] else -1}

def rud_on():
    try:
        with open(SPLIT_STATE) as f:
            return f.read().strip() == "on"
    except Exception:
        return False

def status():
    return {"now": int(time.time()), "tunnel": tunnel(), "host": host(), "rud": rud_on(),
            "peers": clients_status(), "thr": throughput()}

def call_admin(argv, timeout=30):
    try:
        r = subprocess.run(ADMIN + argv, capture_output=True, text=True, timeout=timeout)
        line = (r.stdout.strip().splitlines() or [""])[-1]
        return json.loads(line) if line else {"ok": False, "error": "no output from helper"}
    except Exception as e:
        return {"ok": False, "error": "helper call failed: %s" % e}

# -------------------------------------------------------- persistent history (SQLite)
def _conn():
    c = sqlite3.connect(DB, timeout=5)
    c.row_factory = sqlite3.Row
    return c

def db_init():
    try:
        c = _conn()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE IF NOT EXISTS usage(pubkey TEXT, day TEXT, rx INTEGER DEFAULT 0, "
                  "tx INTEGER DEFAULT 0, PRIMARY KEY(pubkey, day))")
        c.execute("CREATE TABLE IF NOT EXISTS counters(pubkey TEXT PRIMARY KEY, rx INTEGER, tx INTEGER)")
        c.execute("CREATE TABLE IF NOT EXISTS connections(pubkey TEXT, ts INTEGER, endpoint TEXT)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_conn ON connections(pubkey, ts)")
        c.commit(); c.close()
    except Exception:
        pass

_conn_prev = {}   # pubkey -> (online_bool, endpoint_ip) for connection-event detection

def log_connections(eps):
    """eps = {pubkey: (endpoint, handshake_ts)}; record a row on offline->online or roam (IP change)."""
    now = int(time.time())
    rows = []
    for pub, (ep, hs) in eps.items():
        online = bool(hs and (now - hs) < ONLINE_S)
        ipp = ep.rsplit(":", 1)[0] if ep else ""
        prev = _conn_prev.get(pub)
        if online and ep and prev is not None and (prev[0] is False or prev[1] != ipp):
            rows.append((pub, now, ep))
        _conn_prev[pub] = (online, ipp)
    if rows:
        try:
            c = _conn()
            c.executemany("INSERT INTO connections(pubkey, ts, endpoint) VALUES(?,?,?)", rows)
            for pub, _, _ in rows:        # keep last 40 per client
                c.execute("DELETE FROM connections WHERE pubkey=? AND ts NOT IN "
                          "(SELECT ts FROM connections WHERE pubkey=? ORDER BY ts DESC LIMIT 40)", (pub, pub))
            c.commit(); c.close()
        except Exception:
            pass

def connections_for(pub, limit=20):
    try:
        c = _conn()
        rows = c.execute("SELECT ts, endpoint FROM connections WHERE pubkey=? ORDER BY ts DESC LIMIT ?",
                         (pub, limit)).fetchall()
        c.close()
        return [{"ts": r["ts"], "endpoint": r["endpoint"]} for r in rows]
    except Exception:
        return []

def audit_tail(limit=50):
    try:
        with open(AUDIT_LOG) as f:
            lines = f.read().strip().splitlines()[-limit:]
        return [json.loads(l) for l in reversed(lines) if l.strip()]
    except Exception:
        return []

def record_usage(cur):
    """cur = {pubkey: (rx_total, tx_total)} cumulative; accumulate deltas into daily buckets,
    handling wg counter resets (current < previous => peer re-added / iface restarted)."""
    c = _conn()
    prev = {r["pubkey"]: (r["rx"], r["tx"]) for r in c.execute("SELECT pubkey, rx, tx FROM counters")}
    today = time.strftime("%Y-%m-%d")
    for pub, (rx, tx) in cur.items():
        p = prev.get(pub)
        if p:
            drx = rx - p[0]; dtx = tx - p[1]
            if drx < 0: drx = rx
            if dtx < 0: dtx = tx
        else:
            drx = dtx = 0
        if drx or dtx:
            c.execute("INSERT INTO usage(pubkey, day, rx, tx) VALUES(?,?,?,?) "
                      "ON CONFLICT(pubkey, day) DO UPDATE SET rx=rx+?, tx=tx+?",
                      (pub, today, drx, dtx, drx, dtx))
        c.execute("INSERT INTO counters(pubkey, rx, tx) VALUES(?,?,?) "
                  "ON CONFLICT(pubkey) DO UPDATE SET rx=?, tx=?", (pub, rx, tx, rx, tx))
    c.commit(); c.close()

def usage_month():
    try:
        c = _conn(); m = time.strftime("%Y-%m-01")
        rows = c.execute("SELECT pubkey, SUM(rx) rx, SUM(tx) tx FROM usage WHERE day>=? GROUP BY pubkey",
                         (m,)).fetchall()
        c.close()
        return {r["pubkey"]: {"rx": r["rx"] or 0, "tx": r["tx"] or 0} for r in rows}
    except Exception:
        return {}

def usage_daily(days=30):
    try:
        c = _conn()
        rows = c.execute("SELECT day, SUM(rx) rx, SUM(tx) tx FROM usage GROUP BY day "
                         "ORDER BY day DESC LIMIT ?", (days,)).fetchall()
        c.close()
        return [{"day": r["day"], "rx": r["rx"] or 0, "tx": r["tx"] or 0} for r in reversed(rows)]
    except Exception:
        return []

# ----------------------------------------------------------------------- views


# ---------------------------------------------------------- static assets (files)
ASSETS = os.path.dirname(os.path.abspath(__file__))
def asset(name):
    with open(os.path.join(ASSETS, name), "rb") as f:
        return f.read()


CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'self'")

class H(BaseHTTPRequestHandler):
    server_version = "wgui"
    timeout = 20

    def setup(self):
        # Run the TLS handshake here, inside the per-request worker thread,
        # rather than in the main accept loop. A half-open / stalled client
        # then blocks only its own thread (bounded by the socket timeout set
        # in get_request) instead of wedging the whole server. On failure,
        # ThreadingMixIn.shutdown_request still closes the socket.
        self.request.do_handshake()
        super().setup()

    def _send(self, code, body=b"", ctype="text/plain", extra=None):
        self.send_response(code)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Strict-Transport-Security", "max-age=15552000")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json", {"Cache-Control": "no-store"})

    def _user(self):
        for part in self.headers.get("Cookie", "").split(";"):
            part = part.strip()
            if part.startswith("wgui_session="):
                return check_token(part[len("wgui_session="):])
        return None

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        path = urlparse(self.path).path
        # PWA assets — public (no sensitive data), so the install/login page can load them
        _CT = {"/app.css": "text/css", "/app.js": "application/javascript",
               "/icon.svg": "image/svg+xml", "/manifest.webmanifest": "application/manifest+json"}
        if path in _CT:
            try:
                return self._send(200, asset(path.lstrip("/")), _CT[path], {"Cache-Control": "max-age=3600"})
            except Exception:
                return self._send(404, b"")
        if path == "/sw.js":
            try:
                return self._send(200, asset("sw.js"), "application/javascript", {"Cache-Control": "no-cache"})
            except Exception:
                return self._send(404, b"")
        if path in ("/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"):
            fn = "/opt/wg-ui/icon-192.png" if path == "/apple-touch-icon.png" else "/opt/wg-ui" + path
            try:
                with open(fn, "rb") as f:
                    return self._send(200, f.read(), "image/png", {"Cache-Control": "max-age=86400"})
            except Exception:
                return self._send(404, b"")
        if path == "/inter.woff2":
            try:
                with open("/opt/wg-ui/inter.woff2", "rb") as f:
                    return self._send(200, f.read(), "font/woff2", {"Cache-Control": "max-age=604800"})
            except Exception:
                return self._send(404, b"")
        if path == "/login":
            return self._send(200, asset("login.html").replace(b"__CSRF__", b""), "text/html; charset=utf-8")
        if path == "/logout":
            dead = "wgui_session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"
            return self._send(303, b"", None, {"Location": "/login", "Set-Cookie": dead})
        user = self._user()
        if path.startswith("/api/"):
            if not user:
                return self._json(401, {"error": "auth"})
            if path.startswith("/api/status"):
                try:
                    return self._json(200, status())
                except Exception as e:
                    return self._json(500, {"error": str(e)})
            if path.startswith("/api/history"):
                reg = load_registry() or []
                names = {c["pubkey"]: c["name"] for c in reg}
                mu = usage_month()
                cl = sorted([{"name": names.get(k, k[:8]), "rx": v["rx"], "tx": v["tx"]}
                             for k, v in mu.items()], key=lambda x: -(x["rx"] + x["tx"]))
                return self._json(200, {"month": time.strftime("%Y-%m"),
                                        "daily": usage_daily(30), "clients": cl})
            if path.startswith("/api/audit"):
                return self._json(200, {"events": audit_tail(60)})
            if path.startswith("/api/connections"):
                pub = parse_qs(urlparse(self.path).query).get("pub", [""])[0]
                return self._json(200, {"connections": connections_for(pub) if pub else []})
            return self._json(404, {"error": "not found"})
        if not user:
            return self._send(303, b"", None, {"Location": "/login"})
        if path == "/":
            self._send(200, asset("index.html").replace(b"__CSRF__", csrf_for(user).encode()), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found")

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/login":
            ip = self.client_address[0]
            if login_blocked(ip):
                return self._send(303, b"", None, {"Location": "/login?e=2"})
            form = parse_qs(self._body().decode("utf-8", "replace"))
            u = form.get("username", [""])[0]
            p = form.get("password", [""])[0]
            if creds_ok(u, p):
                login_ok(ip)
                tok = make_token(u, int(time.time()) + SESSION_TTL)
                cookie = ("wgui_session=%s; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=%d"
                          % (tok, SESSION_TTL))
                return self._send(303, b"", None, {"Location": "/", "Set-Cookie": cookie})
            login_failed(ip)
            time.sleep(1.0)
            return self._send(303, b"", None, {"Location": "/login?e=1"})
        if path == "/logout-all":
            user = self._user()
            if not user:
                return self._json(401, {"ok": False, "error": "auth"})
            if not hmac.compare_digest(self.headers.get("X-CSRF", ""), csrf_for(user)):
                return self._json(403, {"ok": False, "error": "bad csrf token"})
            try:
                bump_session_gen()
            except Exception as e:
                return self._json(500, {"ok": False, "error": "cannot bump session gen: %s" % e})
            return self._json(200, {"ok": True})
        if path == "/api/admin":
            user = self._user()
            if not user:
                return self._json(401, {"ok": False, "error": "auth"})
            if not hmac.compare_digest(self.headers.get("X-CSRF", ""), csrf_for(user)):
                return self._json(403, {"ok": False, "error": "bad csrf token"})
            try:
                b = json.loads(self._body() or b"{}")
            except Exception:
                return self._json(400, {"ok": False, "error": "bad json"})
            op = b.get("op")
            pub = str(b.get("pubkey", ""))
            name = str(b.get("name", ""))
            if op == "add":
                try: exp = max(0, int(b.get("expires") or 0))
                except Exception: exp = 0
                argv = ["add", name, str(exp)]
            elif op == "setexpiry":
                try: exp = max(0, int(b.get("expires") or 0))
                except Exception: exp = 0
                argv = ["setexpiry", pub, str(exp)]
            elif op == "export":
                argv = ["export"]
            elif op == "rename":
                argv = ["rename", pub, name]
            elif op == "enabled":
                argv = ["setenabled", pub, "1" if b.get("enabled") else "0"]
            elif op == "delete":
                argv = ["delete", pub]
            elif op == "getconf":
                argv = ["getconf", pub]
            elif op == "splitinfo":
                argv = ["splitinfo"]
            elif op == "splitsave":
                ents = b.get("entries", [])
                if not isinstance(ents, list) or len(ents) > 500:
                    return self._json(400, {"ok": False, "error": "bad entries"})
                argv = ["splitsave", "1" if b.get("refresh") else "0"] + [str(e)[:255] for e in ents]
            elif op == "splitserver":
                argv = ["splitserver", "1" if b.get("split") else "0"]
            else:
                return self._json(400, {"ok": False, "error": "unknown op"})
            # split ops run build-split (RU-zone download, up to 90 s) + ipset reload —
            # the default 30 s would kill the helper mid-operation
            res = call_admin(argv, 180 if op in ("splitsave", "splitserver") else 30)
            return self._json(200 if res.get("ok") else 400, res)
        self._send(404, b"not found")

    def log_message(self, *a):
        pass

def main():
    # Fail fast on a missing/placeholder signing key: with a guessable SECRET
    # anyone can mint a valid session cookie, so refusing to start is safer
    # than serving. Same for a missing password hash.
    if len(SECRET) < 24 or SECRET.startswith(b"change-me") or SECRET.startswith(b"replace-with"):
        raise SystemExit("wg-ui: WGUI_SESSION_SECRET is unset, too short (<24) or a placeholder — refusing to start")
    if not (PASS_PBKDF2 or PASS_SHA):
        raise SystemExit("wg-ui: no password hash configured (WGUI_PASS_PBKDF2 or WGUI_PASS_SHA256)")
    db_init()
    threading.Thread(target=_sampler, daemon=True).start()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(CERT, KEY)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        _sem = threading.BoundedSemaphore(MAX_CONN)

        # Cap concurrent handler threads: each connection (incl. half-open TLS
        # from scanners) holds a thread for up to `timeout` seconds; unbounded
        # threads on a 1 GB box is a trivial DoS. Excess connections are dropped.
        def process_request(self, request, client_address):
            if not self._sem.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                self._sem.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self._sem.release()

        def get_request(self):
            # Accept raw TCP and wrap WITHOUT handshaking, so the main accept
            # loop never blocks on TLS. settimeout bounds both the deferred
            # handshake (done in H.setup) and subsequent reads.
            sock, addr = self.socket.accept()
            sock.settimeout(20)
            return ctx.wrap_socket(sock, server_side=True,
                                   do_handshake_on_connect=False), addr

        def handle_error(self, request, client_address):
            # Half-open TLS, timeouts and resets from internet scanners are
            # OSError subclasses (ssl.SSLError, timeout, ConnectionReset) —
            # swallow them quietly; let real handler bugs surface as before.
            import sys
            if issubclass(sys.exc_info()[0] or Exception, OSError):
                return
            super().handle_error(request, client_address)

    httpd = Server(("0.0.0.0", PORT), H)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
