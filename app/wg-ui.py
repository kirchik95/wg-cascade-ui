#!/usr/bin/env python3
"""WireGuard cascade dashboard + client manager.
HTTPS, form login (signed session cookie), light/dark theme.
Read: per-client status, cascade (wg-do) tunnel health, live throughput chart.
Write (via narrow root helper /opt/wg-ui/wg-admin.py): add / rename / enable /
disable / delete clients, fetch config+QR. CSRF-protected.
"""
import os, re, ssl, json, time, hmac, sqlite3, subprocess, threading, sys, ipaddress, contextlib, socket
import http.client
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
from exit_model import client_exit, normalize_exit
import exit_policy
import auth
from auth import (
    BODY_ADMIN_MAX, BODY_LOGIN_MAX, LOGIN_MAX, SESSION_TTL,
    bump_session_gen, check_body_length, check_token, creds_ok, csrf_for,
    login_blocked, login_failed, login_ok, login_state, make_token,
)

# Re-export auth mutables so existing tests can patch wgui.USER / SECRET / …
USER = auth.USER
SALT = auth.SALT
PASS_SHA = auth.PASS_SHA
PASS_PBKDF2 = auth.PASS_PBKDF2
SECRET = auth.SECRET
GEN_FILE = auth.GEN_FILE
_fails = auth._fails
_fails_lock = auth._fails_lock
_FAILS_MAX_IPS = auth._FAILS_MAX_IPS

PORT        = int(os.environ.get("WGUI_PORT", "443"))
CERT        = os.environ.get("WGUI_CERT", "/etc/wg-ui/cert.pem")
KEY         = os.environ.get("WGUI_KEY", "/etc/wg-ui/key.pem")
CLIENTS     = os.environ.get("WGUI_CLIENTS", "/etc/wg-ui/clients.json")
IFACE       = os.environ.get("WGUI_IFACE", "wg-cl")
DO_IFACE    = os.environ.get("WGUI_DO_IFACE", "wg-do")
US_IFACE    = os.environ.get("WGUI_US_IFACE", "wg-us")
AWG_IFACES  = set(os.environ.get("WGUI_AWG_IFACES", "").split())    # ifaces run by AmneziaWG (read via awg)
EXIT_IP     = os.environ.get("WGUI_EXIT_IP", "")                    # expected NL egress (empty = skip probe match)
US_EXIT_IP  = os.environ.get("WGUI_US_EXIT_IP", "")                 # expected US egress (empty = skip probe match)
SRC_IP      = os.environ.get("WGUI_SRC_IP", "10.10.0.1")            # source for NL egress probe
ONLINE_S    = int(os.environ.get("WGUI_ONLINE_SECS", "180"))
SAMPLE_S    = int(os.environ.get("WGUI_SAMPLE_SECS", "5"))
PROBE_S     = int(os.environ.get("WGUI_PROBE_SECS", "10"))         # exit health probe interval
ADMIN       = ["sudo", "-n", "/usr/bin/python3", "/opt/wg-ui/wg-admin.py"]
DB          = os.environ.get("WGUI_DB", "/var/lib/wg-ui/history.db")
EXIT_POLICY = os.environ.get("WGUI_EXIT_POLICY", "/etc/wg-ui/exit-policy.json")
SPLIT_STATE = os.environ.get("WGUI_SPLIT_STATE", "/etc/wg-ui/split-server.state")
AUDIT_LOG   = os.environ.get("WGUI_AUDIT", "/var/log/wg-ui/audit.log")
MAX_CONN    = int(os.environ.get("WGUI_MAX_CONN", "64"))
_STARTED_AT = time.monotonic()        # uptime/grace: monotonic, immune to wall-clock jumps
CONTROL_S   = 60                       # expiry + quota auto-switch cadence (control loop)
MAINT_S     = 3600                     # DB retention cadence
if SAMPLE_S <= 0 or PROBE_S <= 0:
    raise SystemExit("wg-ui: WGUI_SAMPLE_SECS and WGUI_PROBE_SECS must be positive")

def log_event(event, **fields):
    """Structured JSON log line to stderr (picked up by journald under systemd)."""
    row = {"ts": int(time.time()), "event": event}
    row.update(fields)
    try:
        sys.stderr.write(json.dumps(row, separators=(",", ":")) + "\n")
        sys.stderr.flush()
    except Exception:
        pass

def healthz():
    """Process liveness for deploy/monitoring — no auth, no secrets."""
    return {
        "ok": True,
        "uptime_s": int(time.monotonic() - _STARTED_AT),
        "sampler": sampler_info(),
        "threads": {"max_conn": MAX_CONN},
    }

def readyz():
    """Readiness of the panel itself (not of the exits): the deploy gate.

    Exit outages must not fail this check, or every deploy during an exit outage
    would roll back. Ready = sampler collecting, persistence healthy, health loop
    alive, status snapshot built. A just-started process gets a grace period.
    """
    now = int(time.time())
    mono = time.monotonic()
    up = int(mono - _STARTED_AT)
    grace = up < 3 * max(SAMPLE_S, PROBE_S) + 15
    with _lock:
        collection = dict(_sampler_meta["collection"])
        persistence = dict(_sampler_meta["persistence"])
        loop_at = _health_runtime["loop_at"]
        snap_ok_at = _snap_meta["ok_mono"]
        control_at = _control_meta["loop_mono"]
    sampler_age = now - collection["ok_at"] if collection.get("ok_at") else -1
    checks = {
        "sampler": 0 <= sampler_age <= 3 * SAMPLE_S + 10,
        "persistence": not persistence.get("err"),
        "health_loop": bool(loop_at) and now - loop_at <= 3 * PROBE_S + 30,
        # a snapshot that stopped refreshing must not keep serving "all online / up"
        "status": bool(snap_ok_at) and mono - snap_ok_at <= SNAP_STALE_S,
        "control_loop": bool(control_at) and mono - control_at <= 3 * CONTROL_S,
    }
    ready = all(checks.values())
    return {"ready": ready or (grace and checks["persistence"]), "starting": grace and not ready,
            "checks": checks, "sampler_age": sampler_age, "uptime_s": up}


# ------------------------------------------------------------- data collection
def _dump(iface):
    tool = "/usr/bin/awg" if iface in AWG_IFACES else "/usr/bin/wg"
    r = subprocess.run(["sudo", "-n", tool, "show", iface, "dump"],
                       capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "wg show failed").strip())
    return r.stdout.strip().split("\n")

def validate_registry(registry):
    """Validate the on-disk client source used by status, migration, and switches."""
    if not isinstance(registry, list):
        raise RuntimeError("client registry must contain a list")
    seen = set()
    for index, client in enumerate(registry):
        if not isinstance(client, dict):
            raise RuntimeError("client registry record %d must be an object" % index)
        for field in ("pubkey", "name", "ip"):
            value = client.get(field)
            if not isinstance(value, str) or not value.strip():
                raise RuntimeError(
                    "client registry record %d has an invalid %s" % (index, field)
                )
        if client["pubkey"] in seen:
            raise RuntimeError("client registry contains duplicate pubkey")
        seen.add(client["pubkey"])
        if "exit" in client and client["exit"] not in exit_policy.EXITS:
            raise RuntimeError("client registry record %d has an invalid exit" % index)
        if "enabled" in client and type(client["enabled"]) is not bool:
            raise RuntimeError("client registry record %d has an invalid enabled value" % index)
    return registry


def _read_registry_file():
    try:
        with open(CLIENTS) as f:
            registry = json.load(f)
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise RuntimeError("client registry is unreadable or malformed") from exc
    return validate_registry(registry)


def load_registry():
    try:
        return _read_registry_file()
    except FileNotFoundError as exc:
        raise RuntimeError("client registry is missing") from exc


def ensure_client_registry():
    """Materialize a missing registry through the privileged, flocked helper."""
    try:
        return _read_registry_file()
    except FileNotFoundError as exc:
        if os.path.lexists(CLIENTS):
            raise RuntimeError("client registry exists but is unreadable") from exc
    result = call_admin(["list"])
    if not isinstance(result, dict) or not result.get("ok"):
        detail = (result.get("error", "helper failed")
                  if isinstance(result, dict) else "helper failed")
        raise RuntimeError("client registry bootstrap failed: %s" % detail)
    try:
        return _read_registry_file()
    except FileNotFoundError as exc:
        raise RuntimeError("client registry bootstrap did not create the registry") from exc
    except RuntimeError as exc:
        raise RuntimeError("client registry bootstrap created an invalid registry: %s" % exc) from exc

def _parse_cl_dump(lines):
    """Parse wg-cl dump lines → (live, per, eps, rx_total, tx_total)."""
    live, per, eps = {}, {}, {}
    rx = tx = 0
    for ln in lines[1:]:
        p = ln.split("\t")
        if len(p) >= 7:
            r, t = int(p[5]), int(p[6])
            rx += r; tx += t; per[p[0]] = (r, t)
        if len(p) >= 8:
            live[p[0]] = {"ep": "" if p[2] == "(none)" else p[2], "ip": p[3].split("/")[0],
                          "hs": int(p[4]), "rx": int(p[5]), "tx": int(p[6])}
            eps[p[0]] = (live[p[0]]["ep"], int(p[4]))
    return live, per, eps, rx, tx

def _peer_from_dump(lines):
    """Handshake age / up for the first peer on a cascade exit dump."""
    if len(lines) < 2:
        return None
    p = lines[1].split("\t")
    hs = int(p[4])
    return {"age": (int(time.time()) - hs) if hs else -1,
            "up": bool(hs and (int(time.time()) - hs) < ONLINE_S),
            "rx": int(p[5]),
            "tx": int(p[6])}

def wg_peer(iface):
    """Handshake age / up for the first peer on a cascade exit iface (wg-do / wg-us)."""
    try:
        return _peer_from_dump(_dump(iface))
    except Exception:
        return None

# background sampler: throughput ring buffer + cached egress probe + host stats
_samples = deque(maxlen=120)          # (t, total_rx, total_tx)
_psamples = deque(maxlen=30)          # (t, {pubkey: (rx, tx)}) — for per-client sparklines
_egress = {                           # per-exit egress probe cache
    "nl": {"ok": False, "seen": None, "at": 0},
    "us": {"ok": False, "seen": None, "at": 0},
}
_host = {"cpu": 0, "prev": None}      # cpu% (computed from /proc/stat deltas)
_live = {}                            # pubkey -> {ep,ip,hs,rx,tx} from last wg-cl dump
_exit_peers = {"nl": None, "us": None}  # cached wg_peer() for cascade exits
_exit_totals = {"nl": None, "us": None}
_month_usage = {}                     # pubkey -> {rx,tx} calendar-month totals
_exit_month_usage = {"nl": {"rx": 0, "tx": 0}, "us": {"rx": 0, "tx": 0}}
_status_snap = None                   # last assembled /api/status payload
_sampler_meta = {
    "collection": {"ok_at": 0, "err": None, "err_at": 0},
    "persistence": {"ok_at": 0, "err": None, "err_at": 0},
}
_lock = threading.Lock()
_policy_lock = threading.Lock()
_policy_runtime = {"blocked": None, "last_switch": None}
_health = {key: {"state": "unknown", "fails": 0, "oks": 0, "since": 0, "at": 0}
           for key in exit_policy.EXITS}  # debounced per-exit health (exit_policy.next_health_state)
_health_runtime = {"blocked": None, "last_switch_at": 0, "loop_at": 0}  # last_switch_at: monotonic
_snap_meta = {"ok_mono": 0.0, "err": None, "err_at": 0, "logged": None}
_control_meta = {"loop_mono": 0.0, "expire_ok_at": 0, "expire_err": None, "maint_err": None}
_usage_refreshed = threading.Event()   # sampler → control loop: month totals are fresh


def load_exit_policy():
    return exit_policy.load_policy(EXIT_POLICY)


def assignment_counts(registry=None):
    counts = {key: 0 for key in exit_policy.EXITS}
    clients = registry if registry is not None else load_registry()
    for client in clients:
        counts[client_exit(client)] += 1
    return counts


def policy_inputs(tunnel_data=None, peers=None):
    policy, warning = load_exit_policy()
    with _lock:
        usage = {
            key: int((_exit_month_usage.get(key) or {}).get("rx", 0))
                 + int((_exit_month_usage.get(key) or {}).get("tx", 0))
            for key in exit_policy.EXITS
        }
        if tunnel_data is None:
            now = int(time.time())
            health = {
                key: {
                    "ok": bool((_egress.get(key) or {}).get("ok")),
                    "checked_age": now - int((_egress.get(key) or {}).get("at", 0))
                                   if (_egress.get(key) or {}).get("at") else -1,
                }
                for key in exit_policy.EXITS
            }
        else:
            health = None
    if tunnel_data is not None:
        exits = tunnel_data.get("exits", {}) if isinstance(tunnel_data, dict) else {}
        health = {
            key: {
                "ok": bool((exits.get(key) or {}).get("ok")),
                "checked_age": int((exits.get(key) or {}).get("checked_age", -1)),
            }
            for key in exit_policy.EXITS
        }
    return policy, usage, assignment_counts(peers), health, warning


_TARGET_MESSAGES = {
    "target_unhealthy": "The target exit is down: it failed several health checks in a row.",
    "target_exhausted": "The target exit monthly quota is exhausted.",
}

def assign_target_check(target, now=None):
    """Server-side guard for putting clients on `target` (add / setexit).

    Returns (block, warning). block = {"code", "error"} only for a confirmed-down
    (debounced health "down") or quota-exhausted target. Missing or old health
    evidence, or a single failed probe without a confirmed down, is a warning —
    right after a restart health is unknown and adding clients must keep working.
    """
    policy, _ = load_exit_policy()
    stamp = int(time.time()) if now is None else int(now)
    with _lock:
        u = _exit_month_usage.get(target) or {}
        usage = {target: int(u.get("rx", 0)) + int(u.get("tx", 0))}
        eg = dict(_egress.get(target) or {})
        state = (_health.get(target) or {}).get("state")
    age = stamp - int(eg["at"]) if eg.get("at") else -1
    found = exit_policy.target_block(target, policy, usage,
                                     {target: {"ok": bool(eg.get("ok")), "checked_age": age}})
    code = (found or {}).get("code")
    if code == "target_exhausted":
        return {"code": code, "error": _TARGET_MESSAGES[code]}, None
    if state == "down":
        return {"code": "target_unhealthy", "error": _TARGET_MESSAGES["target_unhealthy"]}, None
    if code == "target_stale":
        return None, "target_stale"
    if code == "target_unhealthy":
        return None, "target_unverified"
    return None, None


def exit_policy_status(tunnel_data=None, peers=None):
    policy, usage, assignments, health, warning = policy_inputs(tunnel_data, peers)
    with _lock:
        runtime = json.loads(json.dumps(_policy_runtime))
    exits = {}
    for key in exit_policy.EXITS:
        age = int(health[key]["checked_age"])
        exits[key] = {
            "used": usage[key],
            "quota": policy["quota_bytes"][key],
            "clients": assignments[key],
            "healthy": bool(health[key]["ok"] and 0 <= age <= exit_policy.HEALTH_MAX_AGE),
            "checked_age": age,
            "exhausted": usage[key] >= policy["quota_bytes"][key],
        }
    with _lock:
        health_blocked = _health_runtime["blocked"]
    return {
        "auto_switch": policy["auto_switch"],
        "health_failover": policy.get("health_failover", True),
        "exits": exits,
        "blocked": runtime["blocked"],
        "health_blocked": health_blocked,
        "last_switch": runtime["last_switch"],
        "warning": warning,
    }


_BLOCK_MESSAGES = {
    "invalid_target": "The requested exit is invalid.",
    "target_unhealthy": "The target exit health check failed.",
    "target_stale": "The target exit health check is stale.",
    "target_exhausted": "The target exit monthly quota is exhausted.",
    "both_exhausted": "Both exit monthly quotas are exhausted.",
    "counter_unavailable": "Current exit counter data is incomplete.",
    "helper_failed": "The exit switch helper failed.",
    "both_unhealthy": "Both exits are failing health checks.",
    "failover_cooldown": "A health failover ran recently; waiting before switching again.",
}


def _with_block_message(blocked):
    value = dict(blocked)
    value.setdefault("source", None)
    value.setdefault("target", None)
    value.setdefault("message", _BLOCK_MESSAGES.get(value.get("code"), "Exit switching is blocked."))
    return value


def _set_policy_block(blocked):
    value = _with_block_message(blocked)
    with _lock:
        _policy_runtime["blocked"] = value
    return value


def _clear_policy_block():
    with _lock:
        _policy_runtime["blocked"] = None


def _blocked_result(blocked):
    value = _with_block_message(blocked)
    return {"ok": False, "error": value["code"], "http_status": 409, **value}


def counter_availability():
    with _lock:
        return {key: _exit_totals.get(key) is not None for key in exit_policy.EXITS}


def _counter_block(source, target, availability=None):
    available = availability if availability is not None else counter_availability()
    missing = [key for key in exit_policy.EXITS if not available.get(key)]
    if not missing:
        return None
    return {
        "code": "counter_unavailable",
        "source": source,
        "target": target,
        "missing_exits": missing,
    }


def _finish_no_action(policy, assignments, availability):
    with _lock:
        blocked = _policy_runtime.get("blocked") or {}
        preserve_helper_failure = (
            blocked.get("code") == "helper_failed"
            and policy["auto_switch"]
            and not all(availability.values())
            and assignments.get(blocked.get("source"), 0) > 0
        )
        if not preserve_helper_failure:
            _policy_runtime["blocked"] = None


def _set_incomplete_policy_block(incomplete, assignments):
    value = _with_block_message(incomplete)
    with _lock:
        blocked = _policy_runtime.get("blocked") or {}
        preserve_helper_failure = (
            blocked.get("code") == "helper_failed"
            and blocked.get("source") == value["source"]
            and blocked.get("target") == value["target"]
            and assignments.get(value["source"], 0) > 0
        )
        if preserve_helper_failure:
            return dict(blocked)
        _policy_runtime["blocked"] = value
    return value


def _guarded_exit_switch_locked(target, reason, inputs=None):
    policy, usage, assignments, health, warning = inputs or policy_inputs()
    availability = counter_availability()
    source = "us" if target == "nl" else "nl"
    if reason == "quota":
        decision = exit_policy.evaluate_auto(policy, usage, assignments, health)
        if decision["blocked"]:
            blocked = _set_policy_block(decision["blocked"])
            return _blocked_result(blocked)
        action = decision["action"]
        if not action:
            _finish_no_action(policy, assignments, availability)
            return {"ok": True, "exit": target, "changed": 0}
        target = action["target"]
        source = action["source"]
    blocked = exit_policy.target_block(target, policy, usage, health)
    if blocked:
        if reason == "quota":
            blocked = _set_policy_block(dict(blocked, source=source))
        return _blocked_result(blocked)
    if assignments.get(target, 0) == sum(assignments.values()):
        _clear_policy_block()
        return {"ok": True, "exit": target, "changed": 0}
    if reason == "quota":
        incomplete = _counter_block(source, target, availability)
    else:
        # Leaving a broken exit must not depend on that exit's counters (its iface
        # may be gone); only the target's accounting has to be live.
        incomplete = _counter_block(source, target, {key: (availability.get(key) or key != target)
                                                     for key in exit_policy.EXITS})
    if incomplete:
        if reason == "quota":
            incomplete = _set_incomplete_policy_block(incomplete, assignments)
        return _blocked_result(incomplete)
    result = call_admin(["setexitall", target, reason])
    if result.get("ok"):
        event = {
            "ts": int(time.time()),
            "source": source,
            "target": target,
            "reason": reason,
            "changed": result.get("changed", 0),
        }
        with _lock:
            _policy_runtime["blocked"] = None
            _policy_runtime["last_switch"] = event
    elif reason == "quota":
        _set_policy_block({
            "code": "helper_failed",
            "source": source,
            "target": target,
            "error": result.get("error", "helper failed"),
        })
    log_event("exit_switch", ok=bool(result.get("ok")), reason=reason,
              target=target, changed=result.get("changed", 0),
              error=result.get("error"))
    return result


def guarded_exit_switch(target, reason):
    with _policy_lock:
        return _guarded_exit_switch_locked(target, reason)


def _evaluate_auto_switch_locked(inputs=None):
    inputs = inputs or policy_inputs()
    policy, usage, assignments, health, warning = inputs
    availability = counter_availability()
    decision = exit_policy.evaluate_auto(policy, usage, assignments, health)
    if decision["blocked"]:
        blocked = _set_policy_block(decision["blocked"])
        return {"ok": False, **blocked}
    if not decision["action"]:
        _finish_no_action(policy, assignments, availability)
        return {"ok": True, "changed": 0}
    action = decision["action"]
    incomplete = _counter_block(action["source"], action["target"], availability)
    if incomplete:
        blocked = _set_incomplete_policy_block(incomplete, assignments)
        return {"ok": False, **blocked}
    return _guarded_exit_switch_locked(action["target"], "quota", inputs)


def save_exit_policy(argv):
    """Persist and reconcile one policy version while switches are excluded."""
    with _policy_lock:
        result = call_admin(argv)
        if not result.get("ok"):
            return result
        inputs = policy_inputs()
        if inputs[0]["auto_switch"]:
            _evaluate_auto_switch_locked(inputs)
        else:
            _clear_policy_block()
        refresh_status_cache()
        return result


def evaluate_auto_switch():
    with _policy_lock:
        return _evaluate_auto_switch_locked()


def health_states():
    with _lock:
        return {key: dict(value) for key, value in _health.items()}


def _set_health_block(blocked):
    value = _with_block_message(blocked) if blocked else None
    with _lock:
        _health_runtime["blocked"] = value
    return value


def evaluate_health_failover():
    """Move clients off a confirmed-down exit (no automatic failback)."""
    with _policy_lock:
        inputs = policy_inputs()
        policy, usage, assignments, health, warning = inputs
        with _lock:
            last = _health_runtime["last_switch_at"]
        now = int(time.time())
        decision = exit_policy.evaluate_health(policy, usage, assignments, health_states(), now, last,
                                               mono_now=time.monotonic())
        if decision["blocked"]:
            blocked = _set_health_block(decision["blocked"])
            return {"ok": False, **blocked}
        if not decision["action"]:
            _set_health_block(None)
            return {"ok": True, "changed": 0}
        action = decision["action"]
        result = _guarded_exit_switch_locked(action["target"], "health", inputs)
        if result.get("ok"):
            with _lock:
                _health_runtime["last_switch_at"] = time.monotonic()
            _set_health_block(None)
            log_event("exit_failover", source=action["source"], target=action["target"],
                      changed=result.get("changed", 0))
        else:
            _set_health_block({"code": result.get("code") or "helper_failed",
                               "source": action["source"], "target": action["target"],
                               "error": result.get("error")})
        return result

def clients_status():
    """Assemble peer rows from sampler caches — no wg dump on the request path."""
    reg = load_registry()
    with _lock:
        live = dict(_live)
        mu = dict(_month_usage)
    now = int(time.time())
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
                    "exit": client_exit(c),
                    "spark": sp.get(c["pubkey"], [])[-24:]})
    out.sort(key=lambda x: (not x["online"], not x["enabled"], x["name"].lower()))
    return out

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

def _parse_ip(text):
    """The probe body must be exactly one IP address — an HTML error page is not."""
    try:
        return str(ipaddress.ip_address(text.strip()))
    except ValueError:
        return None

def _probe_via(iface_or_ip, expect_ip):
    """curl through iface_or_ip; ok only on curl success, HTTP 2xx and a valid IP that
    matches expect_ip (any valid IP when expect_ip is empty). Tries each URL in turn."""
    seen = None
    for url in EGRESS_URLS:
        try:
            r = subprocess.run(["curl", "-sf", "--max-time", "6", "--interface", iface_or_ip, url],
                               capture_output=True, text=True, timeout=8)
        except Exception:
            continue
        ip = _parse_ip(r.stdout) if r.returncode == 0 else None
        if not ip:
            continue
        seen = ip
        if not expect_ip or ip == expect_ip:
            return True, ip
    return False, seen

def _probe_us():
    # Only probe US when the iface exists; missing iface is not an error for NL-only deploys.
    try:
        subprocess.run(["ip", "link", "show", US_IFACE], capture_output=True, timeout=3, check=True)
    except Exception:
        return False, None
    return _probe_via(US_IFACE, US_EXIT_IP or None)

def _probe_egress():
    """Probe NL (via SRC_IP → default cascade) and US (via wg-us) egress IPs in parallel."""
    out = {}
    def run(key, fn):
        try:
            out[key] = fn()
        except Exception:
            out[key] = (False, None)
    threads = [threading.Thread(target=run, args=("nl", lambda: _probe_via(SRC_IP, EXIT_IP)), daemon=True),
               threading.Thread(target=run, args=("us", _probe_us), daemon=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    return {key: out.get(key, (False, None)) for key in ("nl", "us")}

def _record_probe(res, now):
    with _lock:
        for key in ("nl", "us"):
            ok_, ip = res[key]
            _egress[key].update(ok=ok_, seen=ip, at=now)
            _health[key] = exit_policy.next_health_state(_health[key], ok_, now)

def _sampler_note(ok=True, err=None):
    with _lock:
        state = _sampler_meta["collection"]
        if ok:
            state["ok_at"] = int(time.time())
            state["err"] = None
        else:
            state["err"] = str(err)[:200] if err else "error"
            state["err_at"] = int(time.time())

def _sampler_persistence_note(ok=True, err=None):
    with _lock:
        state = _sampler_meta["persistence"]
        if ok:
            state["ok_at"] = int(time.time())
            state["err"] = None
        else:
            state["err"] = str(err)[:200] if err else "error"
            state["err_at"] = int(time.time())

def sampler_info():
    with _lock:
        collection = dict(_sampler_meta["collection"])
        persistence = dict(_sampler_meta["persistence"])
    error = persistence if persistence.get("err") else collection
    return {
        "ok_at": collection.get("ok_at", 0),
        "err": error.get("err"),
        "err_at": error.get("err_at", 0),
        "age": (int(time.time()) - collection["ok_at"]) if collection.get("ok_at") else -1,
    }

SNAP_STALE_S = 3 * SAMPLE_S + 10

def _next_slot(deadline, period, now):
    """Next future slot on a fixed grid; skips missed slots instead of bursting."""
    if now < deadline:
        return deadline
    return deadline + (int((now - deadline) // period) + 1) * period

def _persist_usage(per):
    """Write deltas and refresh month caches; on failure keep the old caches."""
    try:
        if per:
            record_usage(per)
        with _lock:
            exit_totals = {key: value for key, value in _exit_totals.items() if value is not None}
        if exit_totals:
            record_exit_usage(exit_totals)
        client_month = usage_month()
        exit_month = exit_usage_month()
    except Exception as exc:
        _sampler_persistence_note(False, "usage persistence: %s" % exc)
        return False
    with _lock:
        _month_usage.clear(); _month_usage.update(client_month)
        _exit_month_usage.clear(); _exit_month_usage.update(exit_month)
    _sampler_persistence_note(True)
    _usage_refreshed.set()
    return True

def _refresh_snapshot():
    try:
        refresh_status_cache()
    except Exception as exc:
        msg = str(exc)[:200]
        with _lock:
            _snap_meta.update(err=msg, err_at=int(time.time()))
            first = _snap_meta["logged"] != msg
            _snap_meta["logged"] = msg
        if first:                       # log each distinct failure once, not every 5 s
            log_event("status_refresh", ok=False, error=msg)
        return False
    with _lock:
        _snap_meta.update(ok_mono=time.monotonic(), err=None, logged=None)
    return True

def _sampler():
    """Collect every SAMPLE_S on a monotonic grid. Only collection and persistence
    live here — helper calls (expiry, quota switch) run in the control loop, so a
    slow helper can never stretch sampling or the status refresh."""
    next_tick = next_persist = time.monotonic()
    while True:
        per = {}; eps = {}
        try:
            live, per, eps, rx, tx = _parse_cl_dump(_dump(IFACE))
            with _lock:
                ts = int(time.time())
                _live.clear(); _live.update(live)
                _samples.append((ts, rx, tx))
                if per:
                    _psamples.append((ts, per))
            _sampler_note(True)
        except Exception as e:
            _sampler_note(False, e)
        # Cascade exit peer health — cached for tunnel(); request path never dumps.
        for key, iface in (("nl", DO_IFACE), ("us", US_IFACE)):
            try:
                peer = _peer_from_dump(_dump(iface))
            except Exception:
                peer = None
            with _lock:
                _exit_peers[key] = peer
                _exit_totals[key] = (peer["rx"], peer["tx"]) if peer else None
        if eps:
            try: log_connections(eps)
            except Exception: pass
        if time.monotonic() >= next_persist:     # persist usage every ~60s
            _persist_usage(per)
            next_persist = _next_slot(next_persist, 60, time.monotonic())
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
        _refresh_snapshot()
        next_tick = _next_slot(next_tick + SAMPLE_S, SAMPLE_S, time.monotonic())
        time.sleep(max(0.0, next_tick - time.monotonic()))

def run_expire():
    """Disable expired clients; a helper failure is recorded, not mistaken for success."""
    res = call_admin(["expire"])
    with _lock:
        if res.get("ok"):
            _control_meta.update(expire_ok_at=int(time.time()), expire_err=None)
        else:
            _control_meta["expire_err"] = str(res.get("error") or "expire failed")[:200]
    if not res.get("ok"):
        log_event("expire", ok=False, error=_control_meta["expire_err"])
    elif res.get("expired"):
        log_event("expire", ok=True, expired=res.get("expired"))
    return res

def control_tick(state, mono=None):
    """One control-loop step. state = {"next_expire", "next_maint"} (monotonic)."""
    mono = time.monotonic() if mono is None else mono
    if _usage_refreshed.is_set():
        _usage_refreshed.clear()
        try:
            evaluate_auto_switch()
        except Exception as exc:
            log_event("exit_auto_switch", ok=False, error=str(exc)[:200])
    if mono >= state["next_expire"]:
        try:
            ok_ = run_expire().get("ok")
        except Exception as exc:
            ok_ = False
            log_event("expire", ok=False, error=str(exc)[:200])
        # retry a failed expiry sooner than the regular cadence
        state["next_expire"] = mono + (CONTROL_S if ok_ else 15)
    if mono >= state["next_maint"]:
        try:
            db_maintenance(load_registry())
            with _lock:
                _control_meta["maint_err"] = None
        except Exception as exc:
            with _lock:
                _control_meta["maint_err"] = str(exc)[:200]
            log_event("db_maintenance", ok=False, error=str(exc)[:200])
        state["next_maint"] = _next_slot(state["next_maint"], MAINT_S, mono)
    with _lock:
        _control_meta["loop_mono"] = time.monotonic()

def _control_loop():
    """Expiry (immediately at start, then every CONTROL_S), quota auto-switch after
    each usage refresh, and hourly DB retention — all off the sampling path."""
    now = time.monotonic()
    state = {"next_expire": now, "next_maint": now + 300}
    while True:
        try:
            control_tick(state)
        except Exception as exc:
            log_event("control_tick", ok=False, error=str(exc)[:200])
        _usage_refreshed.wait(timeout=max(1.0, min(state["next_expire"], state["next_maint"]) - time.monotonic()))

def health_tick():
    """One health round: probe both exits, fold results, then consider a failover."""
    res = _probe_egress()
    now = int(time.time())
    _record_probe(res, now)
    try:
        record_probe_history(res, now)
    except sqlite3.Error as exc:
        log_event("health_history", ok=False, error=str(exc)[:200])
    with _lock:
        _health_runtime["loop_at"] = now
    return evaluate_health_failover()

def _health_loop():
    """Exit probes + health failover run apart from the sampler, so a slow probe
    (curl timeouts on a dead exit) never stalls throughput sampling or vice versa."""
    while True:
        started = time.monotonic()
        try:
            health_tick()
        except Exception as exc:
            log_event("health_tick", ok=False, error=str(exc)[:200])
        time.sleep(max(1, PROBE_S - (time.monotonic() - started)))

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

def _exit_status(key, iface, expect_ip, peer):
    with _lock:
        eg = dict(_egress.get(key) or {})
        hl = dict(_health.get(key) or {})
    wg_up = bool(peer and peer["up"])
    age = (int(time.time()) - eg["at"]) if eg.get("at") else -1
    # A success older than HEALTH_MAX_AGE is not evidence the exit works now.
    ok = bool(eg.get("ok")) and 0 <= age <= exit_policy.HEALTH_MAX_AGE
    return {
        "iface": iface,
        "wg_up": wg_up,
        "wg_age": peer["age"] if peer else -1,
        "exit_ip": expect_ip or None,
        "exit_seen": eg.get("seen"),
        "ok": ok,
        "health": hl.get("state", "unknown"),
        "health_since": hl.get("since", 0),
        "fails": int(hl.get("fails", 0)),    # consecutive failed probes (debounce progress)
        "oks": int(hl.get("oks", 0)),        # consecutive passed probes
        "checked_age": age,
    }

def _affected_clients(exits, clients):
    """Enabled clients routed to an exit that is not currently passing probes."""
    out = {key: 0 for key in exits}
    for c in clients or []:
        if c.get("enabled", True):
            key = client_exit(c)
            if key in exits and not exits[key]["ok"]:
                out[key] += 1
    return out

def tunnel(clients=None):
    with _lock:
        peers = {k: (dict(v) if isinstance(v, dict) else None) for k, v in _exit_peers.items()}
    exits = {
        "nl": _exit_status("nl", DO_IFACE, EXIT_IP, peers.get("nl")),
        "us": _exit_status("us", US_IFACE, US_EXIT_IP or None, peers.get("us")),
    }
    if clients is None:
        try:
            clients = load_registry()
        except Exception:
            clients = []
    return dict(_tunnel_state(exits, clients), exits=exits)

def _tunnel_state(exits, clients):
    """state + affected_clients from exit health and client assignments (also used
    to re-derive the state of an aged snapshot). Annotates exits in place."""
    affected = _affected_clients(exits, clients)
    for key, n in affected.items():
        exits[key]["affected_clients"] = n
    total_affected = sum(affected.values())
    enabled = sum(1 for c in clients if c.get("enabled", True))
    any_ok = any(e.get("ok") for e in exits.values())
    any_wg = any(e.get("wg_up") for e in exits.values())
    if not any_ok:
        state = "degraded" if any_wg else "down"
    elif total_affected and total_affected >= enabled:
        state = "down"          # every enabled client sits on a failing exit
    elif total_affected:
        state = "degraded"
    else:
        state = "up"
    return {"state": state, "affected_clients": total_affected}

def rud_on():
    try:
        with open(SPLIT_STATE) as f:
            return f.read().strip() == "on"
    except Exception:
        return False

def refresh_status_cache():
    """Build /api/status payload from caches; called by the sampler thread."""
    global _status_snap
    peers = clients_status()
    tunnel_data = tunnel(peers)
    snap = {"now": int(time.time()), "tunnel": tunnel_data, "host": host(), "rud": rud_on(),
            "peers": peers, "thr": throughput(), "sampler": sampler_info(),
            "exit_policy": exit_policy_status(tunnel_data, peers)}
    with _lock:
        _status_snap = snap
    return snap

def _age_snapshot(snap, now):
    """Advance time-relative fields of a cached snapshot to `now`, so a stalled
    sampler shows growing ages, offline peers and expired exit checks instead of a
    frozen 'all online / up'. snapshot_age/stale tell the UI how old the data is."""
    drift = max(0, now - int(snap.get("now", now)))
    snap["snapshot_age"] = drift
    snap["stale"] = drift > SNAP_STALE_S
    snap["now"] = now
    snap["sampler"] = sampler_info()
    if not drift:
        return snap
    for p in snap.get("peers") or []:
        if isinstance(p, dict) and p.get("age", -1) >= 0:
            p["age"] += drift
            p["online"] = bool(p.get("enabled", True) and p["age"] < ONLINE_S)
    tun = snap.get("tunnel") or {}
    for e in (tun.get("exits") or {}).values():
        if isinstance(e, dict) and e.get("wg_age", -1) >= 0:
            e["wg_age"] += drift
        if isinstance(e, dict) and e.get("checked_age", -1) >= 0:
            e["checked_age"] += drift
            if e["checked_age"] > exit_policy.HEALTH_MAX_AGE:
                e["ok"] = False
    if tun.get("exits"):
        tun.update(_tunnel_state(tun["exits"], snap.get("peers") or []))
    if snap["stale"] and tun:
        tun["state"] = "unknown"        # don't present old data as a verdict
    for e in (((snap.get("exit_policy") or {}).get("exits")) or {}).values():
        if isinstance(e, dict) and e.get("checked_age", -1) >= 0:
            e["checked_age"] += drift
            if e["checked_age"] > exit_policy.HEALTH_MAX_AGE:
                e["healthy"] = False
    return snap

def status():
    with _lock:
        snap = _status_snap
    if snap is None:
        snap = refresh_status_cache()
    return _age_snapshot(json.loads(json.dumps(snap)), int(time.time()))

# Seconds the web service waits for wg-admin.py: the helper's own budget
# (wg-admin.py OP_BUDGETS, lock wait and rollback included) plus ~10 s, so the
# helper decides how an operation ends and reports it, instead of being killed.
ADMIN_TIMEOUTS = {
    "setexitall": 90,
    "rename": 150, "setenabled": 150, "delete": 150, "setexit": 150,
    "expire": 150, "regenerate": 150,
    "add": 195,
    "splitsave": 180, "splitserver": 180,
    "export": 60,
}
ADMIN_TIMEOUT_DEFAULT = 70

def call_admin(argv, timeout=None):
    if timeout is None:
        timeout = ADMIN_TIMEOUTS.get(argv[0] if argv else "", ADMIN_TIMEOUT_DEFAULT)
    try:
        r = subprocess.run(ADMIN + argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # The helper may still have committed: say so instead of a plain failure.
        return {"ok": False, "error": "timeout", "committed": "unknown",
                "detail": "helper did not answer within %ds" % timeout}
    except Exception as e:
        return {"ok": False, "error": "helper call failed: %s" % e}
    line = (r.stdout.strip().splitlines() or [""])[-1]
    if line:
        try:
            return json.loads(line)
        except ValueError:
            pass
    tail = (r.stderr or "").strip()[-200:]
    return {"ok": False, "error": "helper failed (rc=%s)%s" % (r.returncode, ": " + tail if tail else "")}

# -------------------------------------------------------- persistent history (SQLite)
USAGE_RETENTION_DAYS = int(os.environ.get("WGUI_USAGE_RETENTION_DAYS", "400"))  # ~13 months
CONN_KEEP = 40                                   # connection events kept per client

def _conn():
    c = sqlite3.connect(DB, timeout=5)
    c.row_factory = sqlite3.Row
    return c

@contextlib.contextmanager
def _db(write=False):
    """One connection per unit of work: commit on success, roll back on error,
    and always close — a failed writer must not hold the WAL write lock until GC."""
    c = _conn()
    try:
        if write:
            c.execute("BEGIN IMMEDIATE")
        yield c
        if write:
            c.commit()
    except BaseException:
        if write:
            try: c.rollback()
            except sqlite3.Error: pass
        raise
    finally:
        c.close()

def db_init():
    try:
        c = _conn()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE IF NOT EXISTS usage(pubkey TEXT, day TEXT, rx INTEGER DEFAULT 0, "
                  "tx INTEGER DEFAULT 0, PRIMARY KEY(pubkey, day))")
        c.execute("CREATE TABLE IF NOT EXISTS counters(pubkey TEXT PRIMARY KEY, rx INTEGER, tx INTEGER)")
        c.execute("CREATE TABLE IF NOT EXISTS exit_usage(exit TEXT, day TEXT, rx INTEGER DEFAULT 0, "
                  "tx INTEGER DEFAULT 0, PRIMARY KEY(exit, day))")
        c.execute("CREATE TABLE IF NOT EXISTS exit_counters(exit TEXT PRIMARY KEY, rx INTEGER, tx INTEGER)")
        c.execute("CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY, value TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS connections(pubkey TEXT, ts INTEGER, endpoint TEXT)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_conn ON connections(pubkey, ts)")
        # Month/daily aggregates filter on day across all clients; the (pubkey, day)
        # PK cannot serve that, so without this index they scan the whole history.
        c.execute("CREATE INDEX IF NOT EXISTS ix_usage_day ON usage(day)")
        c.execute("CREATE TABLE IF NOT EXISTS health_hourly(exit TEXT, hour_ts INTEGER, "
                  "ok INTEGER DEFAULT 0, fail INTEGER DEFAULT 0, PRIMARY KEY(exit, hour_ts))")
        c.commit()
        c.execute("PRAGMA optimize")
        c.close()
    except Exception as exc:
        log_event("db_init", ok=False, error=str(exc)[:200])

_conn_prev = {}   # pubkey -> (online_bool, endpoint_ip) for connection-event detection

def log_connections(eps):
    """eps = {pubkey: (endpoint, handshake_ts)}; record a row on offline->online or roam (IP change).

    The previous state of a client with an event is advanced only after the row is
    committed, so a transient DB error retries the event next tick instead of losing it.
    """
    now = int(time.time())
    rows, nxt = [], {}
    for pub, (ep, hs) in eps.items():
        online = bool(hs and (now - hs) < ONLINE_S)
        ipp = ep.rsplit(":", 1)[0] if ep else ""
        prev = _conn_prev.get(pub)
        nxt[pub] = (online, ipp)
        if online and ep and prev is not None and (prev[0] is False or prev[1] != ipp):
            rows.append((pub, now, ep))
    event_pubs = {r[0] for r in rows}
    for pub, state in nxt.items():
        if pub not in event_pubs:
            _conn_prev[pub] = state
    for pub in list(_conn_prev):       # drop clients that left (no unbounded growth on churn)
        if pub not in nxt:
            del _conn_prev[pub]
    if not rows:
        return
    try:
        with _db(write=True) as c:
            c.executemany("INSERT INTO connections(pubkey, ts, endpoint) VALUES(?,?,?)", rows)
            for pub in event_pubs:     # keep the newest CONN_KEEP rows per client (rowid = strict cap)
                c.execute("DELETE FROM connections WHERE pubkey=? AND rowid NOT IN "
                          "(SELECT rowid FROM connections WHERE pubkey=? ORDER BY ts DESC, rowid DESC LIMIT ?)",
                          (pub, pub, CONN_KEEP))
    except sqlite3.Error as exc:
        _sampler_persistence_note(False, "connection log: %s" % exc)
        return
    for pub in event_pubs:
        _conn_prev[pub] = nxt[pub]

HEALTH_HISTORY_DAYS = 7

def record_probe_history(res, now):
    """Fold one probe round into hourly per-exit ok/fail counters (one upsert per exit)."""
    hour = int(now) - int(now) % 3600
    with _db(write=True) as c:
        for key in exit_policy.EXITS:
            if key not in res:
                continue
            ok_ = bool(res[key][0])
            c.execute("INSERT INTO health_hourly(exit,hour_ts,ok,fail) VALUES(?,?,?,?) "
                      "ON CONFLICT(exit,hour_ts) DO UPDATE SET ok=ok+?,fail=fail+?",
                      (key, hour, int(ok_), int(not ok_), int(ok_), int(not ok_)))

def health_history(hours=24, now=None):
    """{exit: [{ts, ok, fail}] * hours}, oldest first; the last bucket is the current
    hour. Hours without probes stay ok=0/fail=0 so gaps are not painted as healthy.
    Raises sqlite3.Error (callers answer 503)."""
    stamp = int(time.time() if now is None else now)
    last = stamp - stamp % 3600
    first = last - (hours - 1) * 3600
    out = {key: [{"ts": first + i * 3600, "ok": 0, "fail": 0} for i in range(hours)]
           for key in exit_policy.EXITS}
    with _db() as c:
        rows = c.execute("SELECT exit, hour_ts, ok, fail FROM health_hourly "
                         "WHERE hour_ts>=? AND hour_ts<=?", (first, last)).fetchall()
    for r in rows:
        if r["exit"] in out:
            slot = out[r["exit"]][(r["hour_ts"] - first) // 3600]
            slot["ok"], slot["fail"] = r["ok"] or 0, r["fail"] or 0
    return out

def connections_for(pub, limit=20):
    """Raises sqlite3.Error on failure — callers report 'unavailable', not 'no data'."""
    with _db() as c:
        rows = c.execute("SELECT ts, endpoint FROM connections WHERE pubkey=? ORDER BY ts DESC LIMIT ?",
                         (pub, limit)).fetchall()
    return [{"ts": r["ts"], "endpoint": r["endpoint"]} for r in rows]

def audit_tail(limit=50):
    """Read the last `limit` JSON lines without loading the whole file into memory."""
    try:
        with open(AUDIT_LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 4096
            data = b""
            while size > 0 and data.count(b"\n") <= limit:
                step = min(block, size)
                size -= step
                f.seek(size)
                data = f.read(step) + data
            lines = [l for l in data.decode("utf-8", "replace").splitlines() if l.strip()][-limit:]
        return [json.loads(l) for l in reversed(lines)]
    except Exception:
        return []

def record_usage(cur):
    """cur = {pubkey: (rx_total, tx_total)} cumulative; accumulate deltas into daily buckets,
    handling wg counter resets (current < previous => peer re-added / iface restarted)."""
    with _db(write=True) as c:
        _record_usage(c, cur)

def _record_usage(c, cur):
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

def record_exit_usage(cur, day=None):
    with _db(write=True) as c:
        _record_exit_usage(c, cur, day)

def _record_exit_usage(c, cur, day=None):
    previous = {r["exit"]: (r["rx"], r["tx"])
                for r in c.execute("SELECT exit,rx,tx FROM exit_counters")}
    day = day or time.strftime("%Y-%m-%d")
    for key in exit_policy.EXITS:
        pair = cur.get(key)
        if pair is None:
            continue
        rx, tx = map(int, pair)
        old = previous.get(key)
        drx = dtx = 0
        if old is not None:
            drx = rx - old[0] if rx >= old[0] else rx
            dtx = tx - old[1] if tx >= old[1] else tx
        if drx or dtx:
            c.execute("INSERT INTO exit_usage(exit,day,rx,tx) VALUES(?,?,?,?) "
                      "ON CONFLICT(exit,day) DO UPDATE SET rx=rx+?,tx=tx+?",
                      (key, day, drx, dtx, drx, dtx))
        c.execute("INSERT INTO exit_counters(exit,rx,tx) VALUES(?,?,?) "
                  "ON CONFLICT(exit) DO UPDATE SET rx=?,tx=?",
                  (key, rx, tx, rx, tx))


def _month_bounds(now=None, month=None):
    if month is None:
        stamp = time.time() if now is None else now
        current = time.localtime(stamp)
        year, number = current.tm_year, current.tm_mon
    else:
        year, number = map(int, month[:7].split("-"))
    start = "%04d-%02d-01" % (year, number)
    if number == 12:
        year, number = year + 1, 1
    else:
        number += 1
    return start, "%04d-%02d-01" % (year, number)


def exit_usage_month(now=None, month=None):
    month, next_month = _month_bounds(now=now, month=month)
    out = {key: {"rx": 0, "tx": 0} for key in exit_policy.EXITS}
    with _db() as c:
        rows = c.execute("SELECT exit,SUM(rx) rx,SUM(tx) tx FROM exit_usage "
                         "WHERE day>=? AND day<? GROUP BY exit", (month, next_month)).fetchall()
    for row in rows:
        if row["exit"] in out:
            out[row["exit"]] = {"rx": row["rx"] or 0, "tx": row["tx"] or 0}
    return out


def seed_exit_usage(registry, month=None):
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        return _seed_exit_usage(c, registry, month)
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def _seed_exit_usage(c, registry, month=None):
    month, next_month = _month_bounds(month=month)
    if c.execute("SELECT 1 FROM schema_meta WHERE key='exit_usage_v1_seeded'").fetchone():
        return False
    rows = c.execute("SELECT pubkey,day,rx,tx FROM usage WHERE day>=? AND day<?",
                     (month, next_month)).fetchall()
    assignments = {x.get("pubkey"): client_exit(x) for x in (registry or [])}
    for row in rows:
        key = assignments.get(row["pubkey"], "nl")
        c.execute("INSERT INTO exit_usage(exit,day,rx,tx) VALUES(?,?,?,?) "
                  "ON CONFLICT(exit,day) DO UPDATE SET rx=rx+?,tx=tx+?",
                  (key, row["day"], row["rx"], row["tx"], row["rx"], row["tx"]))
    c.execute("INSERT INTO schema_meta(key,value) VALUES('exit_usage_v1_seeded','1')")
    c.commit()
    return True


def seed_exit_usage_from_registry(month=None):
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        if c.execute(
                "SELECT 1 FROM schema_meta WHERE key='exit_usage_v1_seeded'").fetchone():
            return False
        try:
            registry = _read_registry_file()
        except FileNotFoundError as exc:
            raise RuntimeError(
                "client registry unavailable; exit usage migration not seeded"
            ) from exc
        return _seed_exit_usage(c, registry, month)
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


# The read helpers below raise sqlite3.Error instead of returning empty data:
# "the DB failed" must not look like "no traffic" (or zero the cached month totals).
def usage_month(now=None, month=None):
    month, next_month = _month_bounds(now=now, month=month)
    with _db() as c:
        rows = c.execute("SELECT pubkey, SUM(rx) rx, SUM(tx) tx FROM usage WHERE day>=? AND day<? "
                         "GROUP BY pubkey", (month, next_month)).fetchall()
    return {r["pubkey"]: {"rx": r["rx"] or 0, "tx": r["tx"] or 0} for r in rows}

def usage_daily(days=30):
    """Totals for the last `days` days that have data (index range scan on day)."""
    with _db() as c:
        cutoff = c.execute("SELECT day FROM (SELECT DISTINCT day FROM usage ORDER BY day DESC LIMIT ?) "
                           "ORDER BY day LIMIT 1", (days,)).fetchone()
        if not cutoff:
            return []
        rows = c.execute("SELECT day, SUM(rx) rx, SUM(tx) tx FROM usage WHERE day>=? GROUP BY day "
                         "ORDER BY day", (cutoff["day"],)).fetchall()
    return [{"day": r["day"], "rx": r["rx"] or 0, "tx": r["tx"] or 0} for r in rows]

def usage_daily_month(month):
    """Per-day client totals inside one calendar month ("YYYY-MM")."""
    start, end = _month_bounds(month=month)
    with _db() as c:
        rows = c.execute("SELECT day, SUM(rx) rx, SUM(tx) tx FROM usage WHERE day>=? AND day<? "
                         "GROUP BY day ORDER BY day", (start, end)).fetchall()
    return [{"day": r["day"], "rx": r["rx"] or 0, "tx": r["tx"] or 0} for r in rows]

def exit_usage_daily(now=None, month=None):
    """{exit: [{day, rx, tx}, ...]} for one calendar month, from the exit peer counters."""
    start, end = _month_bounds(now=now, month=month)
    out = {key: [] for key in exit_policy.EXITS}
    with _db() as c:
        rows = c.execute("SELECT exit, day, rx, tx FROM exit_usage WHERE day>=? AND day<? "
                         "ORDER BY day", (start, end)).fetchall()
    for r in rows:
        if r["exit"] in out:
            out[r["exit"]].append({"day": r["day"], "rx": r["rx"] or 0, "tx": r["tx"] or 0})
    return out

MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

def parse_month(value):
    """"YYYY-MM" -> the same string; anything else -> ValueError (the API answers 400)."""
    if not isinstance(value, str) or not MONTH_RE.match(value):
        raise ValueError("month must be YYYY-MM")
    return value

def history_payload(month=None, now=None):
    """/api/history body. Without `month` the client series keep their rolling
    30-day window (the current UI chart); the month totals and the exit series
    cover the current calendar month. Raises sqlite3.Error (callers answer 503)."""
    reg = load_registry()
    names = {c["pubkey"]: c["name"] for c in reg}
    if month is None:
        label = time.strftime("%Y-%m", time.localtime(time.time() if now is None else now))
        mu = usage_month(now=now)
        daily = usage_daily(30)
    else:
        label = month
        mu = usage_month(month=month)
        daily = usage_daily_month(month)
    clients = sorted([{"name": names.get(k, k[:8]), "rx": v["rx"], "tx": v["tx"]}
                      for k, v in mu.items()], key=lambda x: -(x["rx"] + x["tx"]))
    return {"month": label, "daily": daily, "clients": clients,
            "exits_daily": exit_usage_daily(now=now, month=month),
            "exits_month": exit_usage_month(now=now, month=month)}

def usage_daily_for(pub, days=30):
    with _db() as c:
        rows = c.execute("SELECT day, rx, tx FROM usage WHERE pubkey=? "
                         "ORDER BY day DESC LIMIT ?", (pub, days)).fetchall()
    return [{"day": r["day"], "rx": r["rx"] or 0, "tx": r["tx"] or 0} for r in reversed(rows)]

def db_maintenance(registry=None, now=None):
    """Retention: drop daily usage older than USAGE_RETENTION_DAYS (exit_usage too),
    and counters/connections of clients no longer in the registry. Cheap; run hourly."""
    stamp = time.time() if now is None else now
    cutoff = time.strftime("%Y-%m-%d", time.localtime(stamp - USAGE_RETENTION_DAYS * 86400))
    keep = None
    if registry is not None:
        keep = [c.get("pubkey") for c in registry if c.get("pubkey")]
    with _db(write=True) as c:
        c.execute("DELETE FROM usage WHERE day<?", (cutoff,))
        c.execute("DELETE FROM exit_usage WHERE day<?", (cutoff,))
        c.execute("DELETE FROM health_hourly WHERE hour_ts<?",
                  (int(stamp) - HEALTH_HISTORY_DAYS * 86400,))
        if keep:
            marks = ",".join("?" * len(keep))
            c.execute("DELETE FROM counters WHERE pubkey NOT IN (%s)" % marks, keep)
            c.execute("DELETE FROM connections WHERE pubkey NOT IN (%s)" % marks, keep)
    with _db() as c:
        c.execute("PRAGMA optimize")

# ----------------------------------------------------------------------- views


# ---------------------------------------------------------- static assets (files)
ASSETS = os.path.dirname(os.path.abspath(__file__))
def asset(name):
    with open(os.path.join(ASSETS, name), "rb") as f:
        return f.read()


CSP = ("default-src 'self'; script-src 'self'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'self'")

# Slow-drip clients: the socket timeout bounds each recv, not a whole request, so a
# client sending one byte every few seconds could hold a worker slot indefinitely.
# Whole-phase deadlines close such connections; header size is capped well below
# the stdlib's 100 lines × 64 KiB.
HEADER_DEADLINE_S = 10        # TLS handshake + request line + headers
BODY_DEADLINE_S = 15          # reading a (≤256 KiB) request body
http.client._MAXHEADERS = 40
http.client._MAXLINE = 8192

class H(BaseHTTPRequestHandler):
    server_version = "wgui"
    timeout = 20

    def _arm(self, seconds):
        self._disarm()
        t = threading.Timer(seconds, self._abort)
        t.daemon = True
        self._deadline = t
        t.start()

    def _disarm(self):
        t = getattr(self, "_deadline", None)
        if t is not None:
            t.cancel()
            self._deadline = None

    def _abort(self):
        try:
            self.request.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def setup(self):
        # Run the TLS handshake here, inside the per-request worker thread,
        # rather than in the main accept loop. A half-open / stalled client
        # then blocks only its own thread instead of wedging the whole server.
        # The header deadline covers handshake + request line + headers.
        # On failure, ThreadingMixIn.shutdown_request still closes the socket.
        self._arm(HEADER_DEADLINE_S)
        self.request.do_handshake()
        super().setup()

    def parse_request(self):
        try:
            return super().parse_request()
        finally:
            self._disarm()          # headers are in; handler time is not limited here

    def finish(self):
        self._disarm()
        super().finish()

    def _send(self, code, body=b"", ctype="text/plain", extra=None, _log=True):
        t0 = getattr(self, "_t0", None)
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
        if _log:
            path = urlparse(self.path).path
            # Skip noisy public assets + high-frequency status polls
            if path not in ("/api/status", "/healthz") and not path.startswith(
                    ("/app.", "/icon", "/inter.", "/sw.js", "/manifest", "/cascade.", "/clients.")):
                ms = int((time.time() - t0) * 1000) if t0 else None
                log_event("http", method=self.command, path=path, status=code,
                          ms=ms, ip=self.client_address[0])

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json", {"Cache-Control": "no-store"})

    def _user(self):
        for part in self.headers.get("Cookie", "").split(";"):
            part = part.strip()
            if part.startswith("wgui_session="):
                return check_token(part[len("wgui_session="):])
        return None

    def _body(self, limit=BODY_ADMIN_MAX):
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            raise ValueError("bad content-length")
        check_body_length(n, limit)
        if not n:
            return b""
        self._arm(BODY_DEADLINE_S)
        try:
            return self.rfile.read(n)
        finally:
            self._disarm()

    def do_GET(self):
        self._t0 = time.time()
        path = urlparse(self.path).path
        if path in ("/healthz", "/health"):
            return self._json(200, healthz())
        if path == "/readyz":
            r = readyz()
            return self._json(200 if r["ready"] else 503, r)
        # PWA assets — public (no sensitive data), so the install/login page can load them
        _CT = {"/app.css": "text/css",
               "/app.js": "application/javascript",
               "/boot.js": "application/javascript",
               "/theme.js": "application/javascript",
               "/login.js": "application/javascript",
               "/cascade.js": "application/javascript",
               "/clients.js": "application/javascript",
               "/icon.svg": "image/svg+xml",
               "/manifest.webmanifest": "application/manifest+json"}
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
                qs = parse_qs(urlparse(self.path).query)
                pub = qs.get("pub", [""])[0]
                month = None
                if "month" in qs:
                    try:
                        month = parse_month(qs["month"][0])
                    except ValueError as e:
                        return self._json(400, {"error": str(e)})
                try:
                    if pub:   # per-client daily series (config modal chart)
                        return self._json(200, {"daily": usage_daily_for(pub, 30)})
                    return self._json(200, history_payload(month=month))
                except sqlite3.Error as e:
                    return self._json(503, {"error": "history unavailable", "detail": str(e)[:120]})
            if path.startswith("/api/health-history"):
                try:
                    return self._json(200, {"probe_s": PROBE_S, "exits": health_history(24)})
                except sqlite3.Error as e:
                    return self._json(503, {"error": "history unavailable", "detail": str(e)[:120]})
            if path.startswith("/api/audit"):
                return self._json(200, {"events": audit_tail(60)})
            if path.startswith("/api/connections"):
                pub = parse_qs(urlparse(self.path).query).get("pub", [""])[0]
                try:
                    return self._json(200, {"connections": connections_for(pub) if pub else []})
                except sqlite3.Error as e:
                    return self._json(503, {"error": "history unavailable", "detail": str(e)[:120]})
            return self._json(404, {"error": "not found"})
        if not user:
            return self._send(303, b"", None, {"Location": "/login"})
        if path == "/":
            self._send(200, asset("index.html").replace(b"__CSRF__", csrf_for(user).encode()), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found")

    def do_POST(self):
        self._t0 = time.time()
        path = urlparse(self.path).path
        if path == "/login":
            ip = self.client_address[0]
            if login_blocked(ip):
                log_event("login", ok=False, reason="throttled", ip=ip)
                return self._send(303, b"", None,
                                  {"Location": "/login?e=2&retry=%d" % login_state(ip)[1]})
            try:
                form = parse_qs(self._body(BODY_LOGIN_MAX).decode("utf-8", "replace"))
            except ValueError:
                return self._send(413, b"payload too large")
            u = form.get("username", [""])[0]
            p = form.get("password", [""])[0]
            if creds_ok(u, p):
                login_ok(ip)
                try:
                    tok = make_token(u, int(time.time()) + SESSION_TTL)
                except RuntimeError as e:
                    log_event("login", ok=False, reason="session_gen", ip=ip, error=str(e))
                    return self._send(503, b"session state unavailable")
                cookie = ("wgui_session=%s; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=%d"
                          % (tok, SESSION_TTL))
                log_event("login", ok=True, user=u, ip=ip)
                return self._send(303, b"", None, {"Location": "/", "Set-Cookie": cookie})
            login_failed(ip)
            log_event("login", ok=False, reason="bad_creds", ip=ip)
            time.sleep(1.0)
            left, retry = login_state(ip)
            dest = ("/login?e=2&retry=%d" % retry) if retry else ("/login?e=1&left=%d" % left)
            return self._send(303, b"", None, {"Location": dest})
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
            log_event("logout_all", user=user, ip=self.client_address[0])
            return self._json(200, {"ok": True})
        if path == "/api/admin":
            user = self._user()
            if not user:
                return self._json(401, {"ok": False, "error": "auth"})
            if not hmac.compare_digest(self.headers.get("X-CSRF", ""), csrf_for(user)):
                return self._json(403, {"ok": False, "error": "bad csrf token"})
            try:
                raw = self._body(BODY_ADMIN_MAX)
            except ValueError:
                return self._json(413, {"ok": False, "error": "payload too large"})
            try:
                b = json.loads(raw or b"{}")
            except Exception:
                return self._json(400, {"ok": False, "error": "bad json"})
            if not isinstance(b, dict):
                return self._json(400, {"ok": False, "error": "request body must be an object"})
            op = b.get("op")
            pub = str(b.get("pubkey", ""))
            name = str(b.get("name", ""))
            target_warning = None
            if op == "add":
                try: exp = max(0, int(b.get("expires") or 0))
                except Exception: exp = 0
                exit_ = str(b.get("exit") or "nl").strip().lower()
                try:
                    exit_ = normalize_exit(exit_)
                except ValueError as e:
                    return self._json(400, {"ok": False, "error": str(e)})
                blocked, target_warning = assign_target_check(exit_)
                if blocked:
                    log_event("admin", op=op, ok=False, user=user, ip=self.client_address[0],
                              reason=blocked["code"])
                    return self._json(409, dict(blocked, ok=False, target=exit_))
                argv = ["add", name, str(exp), exit_]
            elif op == "setexpiry":
                try: exp = max(0, int(b.get("expires") or 0))
                except Exception: exp = 0
                argv = ["setexpiry", pub, str(exp)]
            elif op == "setexit":
                exit_ = str(b.get("exit") or "").strip().lower()
                try:
                    exit_ = normalize_exit(exit_)
                except ValueError as e:
                    return self._json(400, {"ok": False, "error": str(e)})
                blocked, target_warning = assign_target_check(exit_)
                if blocked:
                    log_event("admin", op=op, ok=False, user=user, ip=self.client_address[0],
                              reason=blocked["code"])
                    return self._json(409, dict(blocked, ok=False, target=exit_))
                argv = ["setexit", pub, exit_]
            elif op == "setexitall":
                raw_target = b.get("exit")
                if not isinstance(raw_target, str) or not raw_target.strip():
                    return self._json(400, {"ok": False, "error": "invalid exit"})
                target = raw_target.strip().lower()
                try:
                    target = normalize_exit(target)
                except ValueError as e:
                    return self._json(400, {"ok": False, "error": str(e)})
                res = guarded_exit_switch(target, "manual")
                log_event("admin", op=op, ok=bool(res.get("ok")), user=user,
                          ip=self.client_address[0], name=None)
                payload = dict(res)
                http_status = payload.pop("http_status", 200 if payload.get("ok") else 400)
                return self._json(http_status, payload)
            elif op == "setexitpolicy":
                auto_switch = b.get("auto_switch")
                failover = b.get("health_failover", True)
                quotas = b.get("quotas_gib")
                if (not isinstance(auto_switch, bool) or not isinstance(failover, bool)
                        or not isinstance(quotas, dict)
                        or set(quotas) != set(exit_policy.EXITS)
                        or any(type(quotas[key]) is not int for key in exit_policy.EXITS)):
                    return self._json(400, {"ok": False, "error": "invalid exit policy"})
                try:
                    validated = exit_policy.policy_from_gib(
                        auto_switch, quotas["nl"], quotas["us"], failover)
                except (KeyError, TypeError, ValueError) as e:
                    return self._json(400, {"ok": False, "error": str(e)})
                argv = [
                    "setexitpolicy",
                    "1" if validated["auto_switch"] else "0",
                    str(validated["quota_bytes"]["nl"] // exit_policy.GIB),
                    str(validated["quota_bytes"]["us"] // exit_policy.GIB),
                    "1" if validated["health_failover"] else "0",
                ]
            elif op == "export":
                # The bundle holds every private key: a stolen session alone must not be
                # enough, so re-check the password (with the login throttle).
                ip = self.client_address[0]
                if login_blocked(ip):
                    return self._json(429, {"ok": False, "error": "too many attempts"})
                pw = b.get("password")
                if not isinstance(pw, str) or not pw:
                    return self._json(403, {"ok": False, "error": "password required"})
                if not creds_ok(user, pw):
                    login_failed(ip)
                    log_event("admin", op=op, ok=False, user=user, ip=ip, reason="bad_password")
                    return self._json(403, {"ok": False, "error": "wrong password"})
                login_ok(ip)
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
            # Per-op timeouts (ADMIN_TIMEOUTS) cover split rebuilds (RU-zone download)
            # and bulk switches; the helper enforces its own, shorter budget.
            if op == "setexitpolicy":
                res = save_exit_policy(argv)
            else:
                res = call_admin(argv)
            if target_warning and res.get("ok"):
                res["warning"] = target_warning
            log_event("admin", op=op, ok=bool(res.get("ok")), user=user,
                      ip=self.client_address[0], name=name or None)
            return self._json(200 if res.get("ok") else 400, res)
        self._send(404, b"not found")

    def log_message(self, *a):
        pass  # structured logging via log_event / _send

def main():
    # Fail fast on a missing/placeholder signing key: with a guessable SECRET
    # anyone can mint a valid session cookie, so refusing to start is safer
    # than serving. Same for a missing password hash.
    if len(auth.SECRET) < 24 or auth.SECRET.startswith(b"change-me") or auth.SECRET.startswith(b"replace-with"):
        raise SystemExit("wg-ui: WGUI_SESSION_SECRET is unset, too short (<24) or a placeholder — refusing to start")
    if not (auth.PASS_PBKDF2 or auth.PASS_SHA):
        raise SystemExit("wg-ui: no password hash configured (WGUI_PASS_PBKDF2 or WGUI_PASS_SHA256)")
    db_init()
    ensure_client_registry()
    seed_exit_usage_from_registry()
    threading.Thread(target=_sampler, daemon=True).start()
    threading.Thread(target=_health_loop, daemon=True).start()
    threading.Thread(target=_control_loop, daemon=True).start()
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
