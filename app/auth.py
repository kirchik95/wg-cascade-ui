"""Auth, sessions, CSRF, login throttle, body-size checks for wg-ui."""
import base64, hashlib, hmac, os, threading, time

USER        = os.environ.get("WGUI_USER", "admin")
SALT        = os.environ.get("WGUI_SALT", "")
PASS_SHA    = os.environ.get("WGUI_PASS_SHA256", "")
PASS_PBKDF2 = os.environ.get("WGUI_PASS_PBKDF2", "")
SECRET      = os.environ.get("WGUI_SESSION_SECRET", "").encode()
GEN_FILE    = os.environ.get("WGUI_GEN", "/var/lib/wg-ui/session.gen")
SESSION_TTL = int(os.environ.get("WGUI_SESSION_TTL", str(7 * 24 * 3600)))

LOGIN_MAX, LOGIN_WIN = 5, 900
_FAILS_MAX_IPS = 1000
_fails = {}
_fails_lock = threading.Lock()

BODY_LOGIN_MAX = 64 * 1024
BODY_ADMIN_MAX = 256 * 1024


def creds_ok(u, p):
    if PASS_PBKDF2:
        try:
            it, hx = PASS_PBKDF2.split("$", 1)
            dk = hashlib.pbkdf2_hmac("sha256", p.encode(), SALT.encode(), int(it)).hex()
            good = hmac.compare_digest(dk, hx)
        except Exception:
            good = False
    else:
        ph = hashlib.sha256((SALT + p).encode()).hexdigest()
        good = hmac.compare_digest(ph, PASS_SHA) and bool(PASS_SHA)
    return hmac.compare_digest(u, USER) and good


def _b64e(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def session_gen():
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


def check_body_length(n, limit):
    if n < 0 or n > limit:
        raise ValueError("body too large")
    return n


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
        while len(_fails) >= _FAILS_MAX_IPS and ip not in _fails:
            _fails.pop(next(iter(_fails)))
        _fails.setdefault(ip, []).append(time.time())


def login_ok(ip):
    with _fails_lock:
        _fails.pop(ip, None)
