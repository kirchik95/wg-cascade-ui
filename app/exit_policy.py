"""Pure configuration and decision logic for NL/US exit quota switching."""
import json

EXITS = ("nl", "us")
GIB = 1024 ** 3
DEFAULT_QUOTA_GIB = 500
MIN_QUOTA_GIB = 1
MAX_QUOTA_GIB = 1_000_000
HEALTH_MAX_AGE = 60


def default_policy():
    return {
        "version": 1,
        "auto_switch": False,
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


def policy_from_gib(auto_switch, nl_gib, us_gib):
    if not isinstance(auto_switch, bool):
        raise ValueError("auto_switch must be boolean")
    return {
        "version": 1,
        "auto_switch": auto_switch,
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
    if not isinstance(auto, bool) or not isinstance(quotas, dict):
        raise ValueError("invalid exit policy")
    out = {"version": 1, "auto_switch": auto, "quota_bytes": {}}
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
