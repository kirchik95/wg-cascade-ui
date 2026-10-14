"""Auth, sessions, CSRF, login throttle, body-size checks for wg-ui."""
import base64, hashlib, hmac, math, os, threading, time

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


_GEN_CHARS = frozenset("0123456789abcdef")
_gen_lock = threading.Lock()


def _write_gen(value, exclusive=False):
    """Atomically publish a generation; exclusive=True only creates a missing file."""
    if exclusive:
        fd = os.open(GEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(value)
        return
    tmp = "%s.tmp.%d" % (GEN_FILE, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, GEN_FILE)


def session_gen():
    """Current session generation, or None when it cannot be trusted.

    A missing file gets a fresh random epoch, so deleting the file never revives
    sessions revoked earlier (a counter would restart at a reused value).
    """
    try:
        with open(GEN_FILE) as f:
            g = f.read().strip()
    except FileNotFoundError:
        with _gen_lock:
            try:
                _write_gen(os.urandom(8).hex(), exclusive=True)
            except FileExistsError:
                pass
            except OSError:
                return None
        return session_gen()
    except OSError:
        return None
    if not g or len(g) > 32 or not set(g) <= _GEN_CHARS:
        return None
    return g


def bump_session_gen():
    with _gen_lock:
        g = os.urandom(8).hex()
        _write_gen(g)
    return g


def make_token(user, exp):
    gen = session_gen()
    if gen is None:
        raise RuntimeError("session generation unavailable")
    msg = ("%s|%d|%s" % (user, exp, gen)).encode()
    return _b64e(msg) + "." + _b64e(hmac.new(SECRET, msg, hashlib.sha256).digest())


def check_token(tok):
    try:
        m, s = tok.split(".", 1)
        msg = _b64d(m)
        if not hmac.compare_digest(_b64d(s), hmac.new(SECRET, msg, hashlib.sha256).digest()):
            return None
        user, exp, gen = msg.decode().split("|")
        current = session_gen()
        if current is None or not hmac.compare_digest(gen, current):
            return None
        return user if int(exp) > int(time.time()) else None
    except Exception:
        return None


def csrf_for(user):
    msg = "csrf|%s|%s" % (user, session_gen() or "unavailable")
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


def login_state(ip, now=None):
    """(attempts left, seconds until unblocked) for `ip` in the sliding window.

    The block lifts when the failures inside the window drop below LOGIN_MAX,
    i.e. when the LOGIN_MAX-th newest failure leaves it — not a fixed delay from
    the last attempt. Blocked attempts are not recorded, so they do not extend it.
    """
    now = time.time() if now is None else now
    with _fails_lock:
        ts = sorted(t for t in _fails.get(ip, []) if now - t < LOGIN_WIN)
    left = max(0, LOGIN_MAX - len(ts))
    retry = 0
    if len(ts) >= LOGIN_MAX:
        retry = max(1, int(math.ceil(ts[len(ts) - LOGIN_MAX] + LOGIN_WIN - now)))
    return left, retry


def login_failed(ip):
    with _fails_lock:
        while len(_fails) >= _FAILS_MAX_IPS and ip not in _fails:
            _fails.pop(next(iter(_fails)))
        _fails.setdefault(ip, []).append(time.time())


def login_ok(ip):
    with _fails_lock:
        _fails.pop(ip, None)
