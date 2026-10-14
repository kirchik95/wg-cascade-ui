"""Pure configuration and decision logic for NL/US exit quota switching."""
import json

EXITS = ("nl", "us")
GIB = 1024 ** 3
DEFAULT_QUOTA_GIB = 500
MIN_QUOTA_GIB = 1
MAX_QUOTA_GIB = 1_000_000
HEALTH_MAX_AGE = 60
# Health failover: an exit is "down" after FAIL_PROBES consecutive failed probes and
# "up" again after OK_PROBES consecutive good ones; health switches are spaced by
# HEALTH_COOLDOWN seconds so a flapping target cannot bounce clients back and forth.
FAIL_PROBES = 3
OK_PROBES = 2
HEALTH_COOLDOWN = 300


def default_policy():
    return {
        "version": 1,
        "auto_switch": False,
        "health_failover": True,
        "quota_bytes": {key: DEFAULT_QUOTA_GIB * GIB for key in EXITS},
    }


def _whole_gib(value):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("quota must be a whole GiB value")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("quota must be a whole GiB value")
    if isinstance(value, str) and value.strip() != str(number):
        raise ValueError("quota must be a whole GiB value")
    if not MIN_QUOTA_GIB <= number <= MAX_QUOTA_GIB:
        raise ValueError("quota must be between 1 and 1000000 GiB")
    return number


def policy_from_gib(auto_switch, nl_gib, us_gib, health_failover=True):
    if not isinstance(auto_switch, bool):
        raise ValueError("auto_switch must be boolean")
    if not isinstance(health_failover, bool):
        raise ValueError("health_failover must be boolean")
    return {
        "version": 1,
        "auto_switch": auto_switch,
        "health_failover": health_failover,
        "quota_bytes": {
            "nl": _whole_gib(nl_gib) * GIB,
            "us": _whole_gib(us_gib) * GIB,
        },
    }


def validate_policy(raw):
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("unsupported exit policy")
    auto = raw.get("auto_switch")
    quotas = raw.get("quota_bytes")
    failover = raw.get("health_failover", True)   # absent in pre-failover policy files
    if not isinstance(auto, bool) or not isinstance(failover, bool) or not isinstance(quotas, dict):
        raise ValueError("invalid exit policy")
    out = {"version": 1, "auto_switch": auto, "health_failover": failover, "quota_bytes": {}}
    for key in EXITS:
        value = quotas.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value % GIB:
            raise ValueError("invalid %s quota" % key)
        gib = value // GIB
        if not MIN_QUOTA_GIB <= gib <= MAX_QUOTA_GIB:
            raise ValueError("invalid %s quota" % key)
        out["quota_bytes"][key] = value
    return out


def load_policy(path):
    try:
        with open(path) as f:
            return validate_policy(json.load(f)), None
    except FileNotFoundError:
        return default_policy(), "missing_policy"
    except Exception:
        return default_policy(), "invalid_policy"


def target_block(target, policy, usage, health):
    if target not in EXITS:
        return {"code": "invalid_target", "target": target}
    if int(usage.get(target, 0)) >= policy["quota_bytes"][target]:
        return {"code": "target_exhausted", "target": target}
    state = health.get(target) or {}
    age = int(state.get("checked_age", -1))
    if age < 0 or age > HEALTH_MAX_AGE:
        return {"code": "target_stale", "target": target}
    if not state.get("ok"):
        return {"code": "target_unhealthy", "target": target}
    return None


def evaluate_auto(policy, usage, assignments, health):
    result = {"action": None, "blocked": None}
    if not policy["auto_switch"]:
        return result
    sources = [key for key in EXITS
               if int(assignments.get(key, 0)) > 0
               and int(usage.get(key, 0)) >= policy["quota_bytes"][key]]
    if not sources:
        return result
    if len(sources) > 1:
        result["blocked"] = {"code": "both_exhausted"}
        return result
    source = sources[0]
    target = "us" if source == "nl" else "nl"
    blocked = target_block(target, policy, usage, health)
    if blocked:
        result["blocked"] = dict(blocked, source=source)
        return result
    result["action"] = {"source": source, "target": target, "reason": "quota"}
    return result


def next_health_state(prev, probe_ok, now):
    """Fold one probe result into an exit's debounced health state.

    State is "unknown" until enough consistent probes arrive, then "up"/"down";
    a single blip never flips a confirmed state.
    """
    st = dict(prev or {"state": "unknown", "fails": 0, "oks": 0, "since": now})
    if probe_ok:
        st["oks"] = st.get("oks", 0) + 1
        st["fails"] = 0
        if st["state"] != "up" and st["oks"] >= OK_PROBES:
            st["state"], st["since"] = "up", now
    else:
        st["fails"] = st.get("fails", 0) + 1
        st["oks"] = 0
        if st["state"] != "down" and st["fails"] >= FAIL_PROBES:
            st["state"], st["since"] = "down", now
    st["at"] = now
    return st


def evaluate_health(policy, usage, assignments, states, now, last_health_switch=None, mono_now=None):
    """Decide a health failover: move clients off a confirmed-down exit onto a healthy one.

    states: {exit: next_health_state(...) result}. There is no automatic failback;
    once moved, clients stay on the target until an operator moves them.
    """
    result = {"action": None, "blocked": None}
    if not policy.get("health_failover", True):
        return result
    sources = [key for key in EXITS
               if int(assignments.get(key, 0)) > 0
               and (states.get(key) or {}).get("state") == "down"]
    if not sources:
        return result
    if len(sources) > 1:
        result["blocked"] = {"code": "both_unhealthy"}
        return result
    source = sources[0]
    target = "us" if source == "nl" else "nl"
    tstate = states.get(target) or {}
    if tstate.get("state") != "up" or now - int(tstate.get("at", 0)) > HEALTH_MAX_AGE:
        result["blocked"] = {"code": "target_unhealthy", "source": source, "target": target}
        return result
    if int(usage.get(target, 0)) >= policy["quota_bytes"][target]:
        result["blocked"] = {"code": "target_exhausted", "source": source, "target": target}
        return result
    # Cooldown is measured on the clock last_health_switch came from: monotonic in
    # the server (mono_now), so a wall-clock jump cannot stretch or skip it.
    clock = now if mono_now is None else mono_now
    if last_health_switch and clock - last_health_switch < HEALTH_COOLDOWN:
        result["blocked"] = {"code": "failover_cooldown", "source": source, "target": target}
        return result
    result["action"] = {"source": source, "target": target, "reason": "health"}
    return result
