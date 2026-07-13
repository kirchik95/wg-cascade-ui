# Bulk and Automatic Exit Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-action NL/US switching for the full client registry and optional server-side switching when the active exit reaches its configurable calendar-month quota.

**Architecture:** Measure quota usage from `wg-do` and `wg-us` peer counters, persist per-exit deltas in the existing SQLite database, and make switching decisions in a pure `exit_policy.py` module called by the sampler. Keep writes behind `wg-admin.py`: policy updates are atomic, and bulk registry updates use one routing sync plus compensating rollback.

**Tech Stack:** Python 3 standard library, SQLite, `unittest`, Bash, WireGuard/iptables/iproute2/conntrack, vanilla JavaScript, HTML, and CSS. No new runtime dependencies or build step.

## Global Constraints

- Support exactly two exits: `nl` through `wg-do` and `us` through `wg-us`.
- Quota means calendar-month RX + TX from the exit WireGuard peer counter.
- Accept whole-GiB quotas from 1 through 1,000,000; default each exit to 500 GiB.
- Trigger automatic switching at `used >= quota`, without a reserve threshold.
- Move the complete registry, including disabled clients; do not return to NL at month rollover.
- Keep traffic on the current exit when the target is unhealthy, stale for more than 60 seconds, or exhausted.
- Manual and automatic bulk switches use the same preconditions; there is no force option.
- Preserve the privileged-helper boundary: `wg-ui.py` reads and orchestrates; `wg-admin.py` performs persistent/routing writes.
- Preserve existing authentication, CSRF, EN/RU, mobile, focus, and reduced-motion behavior.
- Do not add packages, daemons, systemd units, or provider billing API integration.
- Implement behavior test-first and commit only the files named by each task.

## File Map

- Create `app/exit_policy.py`: policy defaults, validation, file loading, target guards, and pure auto-switch decisions.
- Modify `app/wg-ui.py`: exit counter collection, SQLite migration/accounting, policy status, auto evaluator, and admin API orchestration.
- Modify `app/wg-admin.py`: atomic policy writes and transactional `setexitall`.
- Modify `app/exit-route.sh`: strict failures and postcondition verification.
- Modify `app/index.html`: policy alert mount and accessible quota buttons.
- Modify `app/app.js`: policy rendering, modal, confirmation, save, and bulk actions.
- Modify `app/app.css`: quota states, policy modal, progress, and critical banner.
- Modify `app/sw.js`: shell cache version bump after frontend changes.
- Create `tests/test_exit_policy.py`: pure policy tests.
- Create `tests/test_exit_accounting.py`: exit counter, migration, and monthly accounting tests.
- Create `tests/test_exit_route.py`: non-root routing-script failure tests with command stubs.
- Create `tests/test_exit_switching.py`: helper transaction and server orchestration tests.
- Modify `tests/test_frontend_monthly.py`: server-provided quota rendering and policy UI tests.
- Modify `README.md` and `docs/SETUP.md`: operator behavior and persisted policy path.

---

### Task 1: Pure Exit Policy Model

**Files:**
- Create: `app/exit_policy.py`
- Create: `tests/test_exit_policy.py`

**Interfaces:**
- Produces: `default_policy() -> dict`
- Produces: `policy_from_gib(auto_switch: bool, nl_gib: object, us_gib: object) -> dict`
- Produces: `load_policy(path: str) -> tuple[dict, str | None]`
- Produces: `target_block(target: str, policy: dict, usage: dict, health: dict) -> dict | None`
- Produces: `evaluate_auto(policy: dict, usage: dict, assignments: dict, health: dict) -> dict`

- [ ] **Step 1: Write failing policy tests**

Create `tests/test_exit_policy.py`:

```python
import json
import pathlib
import sys
import tempfile
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
import exit_policy


class TestExitPolicy(unittest.TestCase):
    def test_defaults_and_whole_gib_validation(self):
        p = exit_policy.default_policy()
        self.assertFalse(p["auto_switch"])
        self.assertEqual(p["quota_bytes"], {"nl": 500 * 1024 ** 3, "us": 500 * 1024 ** 3})
        self.assertEqual(exit_policy.policy_from_gib(True, "25", 750)["quota_bytes"]["nl"], 25 * 1024 ** 3)
        for value in (0, -1, 1.5, "2.5", 1_000_001, True):
            with self.assertRaises(ValueError):
                exit_policy.policy_from_gib(True, value, 500)

    def test_load_policy_fails_safe(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "policy.json"
            policy, warning = exit_policy.load_policy(str(path))
            self.assertEqual(warning, "missing_policy")
            self.assertFalse(policy["auto_switch"])
            path.write_text("{bad json")
            policy, warning = exit_policy.load_policy(str(path))
            self.assertEqual(warning, "invalid_policy")
            self.assertFalse(policy["auto_switch"])

    def test_target_guards_health_freshness_and_quota(self):
        p = exit_policy.policy_from_gib(True, 1, 1)
        usage = {"nl": 1024 ** 3, "us": 0}
        self.assertEqual(exit_policy.target_block("us", p, usage, {"us": {"ok": True, "checked_age": 61}})["code"], "target_stale")
        self.assertEqual(exit_policy.target_block("us", p, usage, {"us": {"ok": False, "checked_age": 1}})["code"], "target_unhealthy")
        usage["us"] = 1024 ** 3
        self.assertEqual(exit_policy.target_block("us", p, usage, {"us": {"ok": True, "checked_age": 1}})["code"], "target_exhausted")

    def test_auto_action_and_no_ping_pong(self):
        p = exit_policy.policy_from_gib(True, 1, 1)
        health = {
            "nl": {"ok": True, "checked_age": 1},
            "us": {"ok": True, "checked_age": 1},
        }
        d = exit_policy.evaluate_auto(p, {"nl": 1024 ** 3, "us": 0}, {"nl": 14, "us": 0}, health)
        self.assertEqual(d["action"], {"source": "nl", "target": "us", "reason": "quota"})
        d = exit_policy.evaluate_auto(p, {"nl": 1024 ** 3, "us": 1024 ** 3}, {"nl": 0, "us": 14}, health)
        self.assertIsNone(d["action"])
        self.assertEqual(d["blocked"]["code"], "target_exhausted")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the policy tests and verify RED**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_exit_policy.py' -v
```

Expected: import failure for missing `exit_policy`.

- [ ] **Step 3: Implement the pure policy module**

Create `app/exit_policy.py` with these exact constants and decision rules:

```python
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
```

- [ ] **Step 4: Run the policy tests and full suite**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_exit_policy.py' -v
python3 -m unittest discover -s tests -q
```

Expected: policy tests pass; existing 42 tests still pass.

- [ ] **Step 5: Commit the policy model**

```bash
git add app/exit_policy.py tests/test_exit_policy.py
git commit -m "feat: add exit quota policy model"
```

---

### Task 2: Per-Exit Traffic Accounting and Migration

**Files:**
- Modify: `app/wg-ui.py:104-130,243-275,395-516,771-781`
- Create: `tests/test_exit_accounting.py`

**Interfaces:**
- Consumes: `exit_policy.EXITS`
- Produces: `_peer_from_dump(lines) -> dict | None` including `rx` and `tx`
- Produces: `record_exit_usage(cur: dict[str, tuple[int, int]], day: str | None = None) -> None`
- Produces: `exit_usage_month(now: float | None = None) -> dict[str, dict[str, int]]`
- Produces: `seed_exit_usage(registry: list[dict]) -> bool`

- [ ] **Step 1: Write failing accounting and migration tests**

Create `tests/test_exit_accounting.py` with this loader and the assertions below:

```python
import importlib.util
import os
import pathlib
import sys
import tempfile
import time
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
os.environ.setdefault("WGUI_SESSION_SECRET", "exit-accounting-test-secret-0123456789")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-exit-accounting.gen"))

spec = importlib.util.spec_from_file_location("wgui_exit_accounting", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)


class TestExitAccounting(unittest.TestCase):
    def setUp(self):
        self.old_db = wgui.DB
        self.tmp = tempfile.TemporaryDirectory()
        wgui.DB = os.path.join(self.tmp.name, "history.db")
        wgui.db_init()

    def tearDown(self):
        wgui.DB = self.old_db
        self.tmp.cleanup()

    def test_exit_peer_includes_transfer_counters(self):
        lines = ["priv\tpub\t51820\toff", "peer\t(none)\t1.2.3.4:51820\t0.0.0.0/0\t100\t123\t456\t25"]
        peer = wgui._peer_from_dump(lines)
        self.assertEqual((peer["rx"], peer["tx"]), (123, 456))

    def test_exit_usage_baseline_deltas_and_reset(self):
        wgui.record_exit_usage({"nl": (100, 200), "us": (10, 20)}, "2026-07-13")
        wgui.record_exit_usage({"nl": (150, 260), "us": (30, 50)}, "2026-07-13")
        wgui.record_exit_usage({"nl": (5, 7)}, "2026-07-13")
        month = wgui.exit_usage_month(time.mktime((2026, 7, 13, 0, 0, 0, 0, 0, -1)))
        self.assertEqual(month["nl"], {"rx": 55, "tx": 67})
        self.assertEqual(month["us"], {"rx": 20, "tx": 30})

    def test_seed_is_idempotent_and_uses_current_assignment(self):
        c = wgui._conn()
        c.execute("INSERT INTO usage(pubkey,day,rx,tx) VALUES('A','2026-07-01',10,20)")
        c.execute("INSERT INTO usage(pubkey,day,rx,tx) VALUES('B','2026-07-01',30,40)")
        c.commit(); c.close()
        registry = [{"pubkey": "A"}, {"pubkey": "B", "exit": "us"}]
        self.assertTrue(wgui.seed_exit_usage(registry, "2026-07-01"))
        self.assertFalse(wgui.seed_exit_usage(registry, "2026-07-01"))
        month = wgui.exit_usage_month(time.mktime((2026, 7, 13, 0, 0, 0, 0, 0, -1)))
        self.assertEqual(month["nl"], {"rx": 10, "tx": 20})
        self.assertEqual(month["us"], {"rx": 30, "tx": 40})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the accounting tests and verify RED**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_exit_accounting.py' -v
```

Expected: failures for missing `record_exit_usage`, `exit_usage_month`, and `seed_exit_usage`, plus missing peer RX/TX fields.

- [ ] **Step 3: Implement exit sampling, schema, migration, and queries**

In `app/wg-ui.py`:

```python
import exit_policy

_exit_totals = {"nl": None, "us": None}
_exit_month_usage = {"nl": {"rx": 0, "tx": 0}, "us": {"rx": 0, "tx": 0}}
```

Extend `_peer_from_dump()` with:

```python
return {
    "age": (int(time.time()) - hs) if hs else -1,
    "up": bool(hs and (int(time.time()) - hs) < ONLINE_S),
    "rx": int(p[5]),
    "tx": int(p[6]),
}
```

Extend `db_init()` with:

```python
c.execute("CREATE TABLE IF NOT EXISTS exit_usage(exit TEXT, day TEXT, rx INTEGER DEFAULT 0, "
          "tx INTEGER DEFAULT 0, PRIMARY KEY(exit, day))")
c.execute("CREATE TABLE IF NOT EXISTS exit_counters(exit TEXT PRIMARY KEY, rx INTEGER, tx INTEGER)")
c.execute("CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY, value TEXT)")
```

Then add:

```python
def record_exit_usage(cur, day=None):
    c = _conn()
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
    c.commit(); c.close()


def exit_usage_month(now=None):
    month = time.strftime("%Y-%m-01", time.localtime(now or time.time()))
    out = {key: {"rx": 0, "tx": 0} for key in exit_policy.EXITS}
    c = _conn()
    rows = c.execute("SELECT exit,SUM(rx) rx,SUM(tx) tx FROM exit_usage "
                     "WHERE day>=? GROUP BY exit", (month,)).fetchall()
    c.close()
    for row in rows:
        if row["exit"] in out:
            out[row["exit"]] = {"rx": row["rx"] or 0, "tx": row["tx"] or 0}
    return out


def seed_exit_usage(registry, month=None):
    month = month or time.strftime("%Y-%m-01")
    c = _conn()
    if c.execute("SELECT 1 FROM schema_meta WHERE key='exit_usage_v1_seeded'").fetchone():
        c.close(); return False
    assignments = {x.get("pubkey"): client_exit(x) for x in registry}
    rows = c.execute("SELECT pubkey,day,rx,tx FROM usage WHERE day>=?", (month,)).fetchall()
    for row in rows:
        key = assignments.get(row["pubkey"], "nl")
        c.execute("INSERT INTO exit_usage(exit,day,rx,tx) VALUES(?,?,?,?) "
                  "ON CONFLICT(exit,day) DO UPDATE SET rx=rx+?,tx=tx+?",
                  (key, row["day"], row["rx"], row["tx"], row["rx"], row["tx"]))
    c.execute("INSERT INTO schema_meta(key,value) VALUES('exit_usage_v1_seeded','1')")
    c.commit(); c.close(); return True
```

In `_sampler()`, replace the exit-peer loop and once-per-minute persistence with:

```python
for key, iface in (("nl", DO_IFACE), ("us", US_IFACE)):
    try:
        peer = _peer_from_dump(_dump(iface))
    except Exception:
        peer = None
    with _lock:
        _exit_peers[key] = peer
        _exit_totals[key] = (peer["rx"], peer["tx"]) if peer else None

if i % 12 == 0:
    try:
        if per:
            record_usage(per)
        with _lock:
            exit_totals = {key: value for key, value in _exit_totals.items() if value is not None}
        if exit_totals:
            record_exit_usage(exit_totals)
        client_month = usage_month()
        exit_month = exit_usage_month()
        with _lock:
            _month_usage.clear(); _month_usage.update(client_month)
            _exit_month_usage.clear(); _exit_month_usage.update(exit_month)
    except Exception as exc:
        _sampler_note(False, "usage persistence: %s" % exc)
```

In `main()`, initialize migration before starting the sampler:

```python
db_init()
seed_exit_usage(load_registry() or [])
threading.Thread(target=_sampler, daemon=True).start()
```

- [ ] **Step 4: Run accounting, existing history, and full tests**

```bash
python3 -m unittest discover -s tests -p 'test_exit_accounting.py' -v
python3 -m unittest discover -s tests -q
```

Expected: accounting tests pass and the full suite remains green.

- [ ] **Step 5: Commit exit accounting**

```bash
git add app/wg-ui.py tests/test_exit_accounting.py
git commit -m "feat: track monthly traffic by cascade exit"
```

---

### Task 3: Strict Exit Routing Application

**Files:**
- Modify: `app/exit-route.sh:8-113`
- Create: `tests/test_exit_route.py`

**Interfaces:**
- Produces: `exit-route.sh sync` returns nonzero if US clients are requested while `wg-us` is down.
- Produces: `verify_sync(expected_count)` verifies rules after apply.
- Preserves: `exit-route.sh sync` succeeds with zero US clients even if `wg-us` is absent, after removing stale marks.

- [ ] **Step 1: Write non-root failure-path tests**

Create `tests/test_exit_route.py`:

```python
import json
import os
import pathlib
import stat
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "app" / "exit-route.sh"


class TestExitRoute(unittest.TestCase):
    def _executable(self, path, body):
        path.write_text(textwrap.dedent(body))
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_sync(self, clients, iface_up, fail_route=False):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            bindir = root / "bin"
            bindir.mkdir()
            registry = root / "clients.json"
            registry.write_text(json.dumps(clients))
            state = root / "marks"
            state.write_text("")
            self._executable(bindir / "ip", r'''#!/bin/sh
                if [ "$1 $2" = "link show" ]; then [ "$FAKE_IFACE_UP" = 1 ]; exit; fi
                if [ "$1 $2" = "route replace" ] || [ "$1 $2" = "route add" ]; then
                    [ "$FAKE_FAIL_ROUTE" != 1 ]; exit
                fi
                if [ "$1 $2" = "rule show" ]; then echo "1100: from all fwmark 0x65 lookup 65"; exit 0; fi
                if [ "$1 $2" = "route show" ]; then echo "default dev wg-us"; exit 0; fi
                exit 0
            ''')
            self._executable(bindir / "iptables", r'''#!/bin/sh
                if [ "$1 $2 $3 $4" = "-t mangle -L PREROUTING" ]; then exit 0; fi
                if [ "$1 $2 $3 $4" = "-t mangle -S PREROUTING" ]; then
                    while IFS= read -r ip; do
                        [ -z "$ip" ] || echo "-A PREROUTING -s $ip/32 -m comment --comment wgui-exit-us -j MARK --set-mark 0x65"
                    done < "$FAKE_MARK_STATE"
                    exit 0
                fi
                if [ "$1" = "-t" ] && [ "$2" = "mangle" ] && { [ "$3" = "-C" ] || [ "$3" = "-A" ]; }; then
                    op="$3"; shift 4; ip=""
                    while [ "$#" -gt 0 ]; do
                        if [ "$1" = "-s" ]; then ip="${2%/32}"; break; fi
                        shift
                    done
                    if [ "$op" = "-C" ]; then grep -qx "$ip" "$FAKE_MARK_STATE"; exit; fi
                    echo "$ip" >> "$FAKE_MARK_STATE"; exit 0
                fi
                exit 0
            ''')
            self._executable(bindir / "conntrack", "#!/bin/sh\nexit 0\n")
            env = dict(os.environ,
                       PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                       WGUI_CLIENTS=str(registry),
                       WGUI_US_IFACE="wg-us",
                       FAKE_IFACE_UP="1" if iface_up else "0",
                       FAKE_FAIL_ROUTE="1" if fail_route else "0",
                       FAKE_MARK_STATE=str(state))
            return subprocess.run(["bash", str(SCRIPT), "sync"], cwd=ROOT,
                                  env=env, capture_output=True, text=True, timeout=10)

    def test_us_clients_and_missing_iface_fails(self):
        result = self.run_sync([{"ip": "10.10.0.2", "exit": "us", "enabled": True}], iface_up=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wg-us is down", result.stderr)

    def test_no_us_clients_and_missing_iface_clears_stale_rules(self):
        result = self.run_sync([{"ip": "10.10.0.2", "enabled": True}], iface_up=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_route_command_failure_propagates(self):
        result = self.run_sync([{"ip": "10.10.0.2", "exit": "us", "enabled": True}], iface_up=True, fail_route=True)
        self.assertNotEqual(result.returncode, 0)

    def test_successful_us_sync_verifies_one_mark(self):
        result = self.run_sync([{"ip": "10.10.0.2", "exit": "us", "enabled": True}], iface_up=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("synced 1 US client", result.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the routing tests and verify RED**

```bash
python3 -m unittest discover -s tests -p 'test_exit_route.py' -v
```

Expected: the missing-US test fails because the current script returns success after clearing marks.

- [ ] **Step 3: Harden the script and add postcondition verification**

Change the strict mode and `sync_rules()` shape to:

```bash
set -euo pipefail

verify_sync() {
    local expected="$1" actual ip
    actual=$(iptables -t mangle -S PREROUTING 2>/dev/null | grep -c -- "--comment $COMMENT" || true)
    [ "$actual" -eq "$expected" ] || {
        echo "exit-route: expected $expected mark rule(s), found $actual" >&2
        return 1
    }
    [ "$expected" -eq 0 ] && return 0
    ip rule show | grep -q "fwmark $MARK" || {
        echo "exit-route: policy rule missing" >&2
        return 1
    }
    ip route show table "$TABLE" | grep -q "default.*dev $US_IFACE" || {
        echo "exit-route: US default route missing" >&2
        return 1
    }
    while IFS= read -r ip; do
        [ -z "$ip" ] || iptables -t mangle -C PREROUTING -s "$ip/32" \
            -m comment --comment "$COMMENT" -j MARK --set-mark "$MARK"
    done < <(us_ips)
}

sync_rules() {
    local wanted ip count=0
    wanted=$(us_ips)
    if ! iface_up; then
        if [ -n "$wanted" ]; then
            echo "exit-route: $US_IFACE is down while US clients are requested" >&2
            return 1
        fi
        flush_marks
        verify_sync 0
        echo "exit-route: $US_IFACE down — no US clients requested"
        return 0
    fi
    ensure_table
    ensure_forward
    flush_marks
    while IFS= read -r ip; do
        [ -z "$ip" ] && continue
        add_mark "$ip"
        count=$((count + 1))
    done <<< "$wanted"
    verify_sync "$count"
    echo "exit-route: synced $count US client(s) → $US_IFACE (mark $MARK table $TABLE)"
}
```

Keep deletion paths explicitly tolerant with `|| true`; allow all apply-path failures to propagate.

- [ ] **Step 4: Run shell syntax, routing tests, and full tests**

```bash
bash -n app/exit-route.sh
python3 -m unittest discover -s tests -p 'test_exit_route.py' -v
python3 -m unittest discover -s tests -q
```

Expected: syntax check and all tests pass.

- [ ] **Step 5: Commit routing hardening**

```bash
git add app/exit-route.sh tests/test_exit_route.py
git commit -m "fix: fail closed when applying US exit routes"
```

---

### Task 4: Transactional Bulk Helper and Policy Persistence

**Files:**
- Modify: `app/wg-admin.py:19-35,96-109,146-178,242-260,344-360,474-500`
- Create: `tests/test_exit_switching.py`

**Interfaces:**
- Consumes: `exit_policy.policy_from_gib()`
- Produces: `setexitall_data(target: str, reason: str) -> dict`
- Produces: `setexitpolicy_data(enabled: str, nl_gib: str, us_gib: str) -> dict`
- Produces CLI: `setexitall <nl|us> <manual|quota>` and `setexitpolicy <0|1> <nl-gib> <us-gib>`

- [ ] **Step 1: Write failing helper transaction tests**

Create `tests/test_exit_switching.py` with this initial fixture and test class:

```python
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

spec = importlib.util.spec_from_file_location("wgadmin_exit_switching", str(APP / "wg-admin.py"))
wgadmin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgadmin)


class TestBulkAdmin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_clients = wgadmin.CLIENTS_JSON
        self.old_policy = wgadmin.EXIT_POLICY
        wgadmin.CLIENTS_JSON = os.path.join(self.tmp.name, "clients.json")
        wgadmin.EXIT_POLICY = os.path.join(self.tmp.name, "exit-policy.json")
        self.addCleanup(setattr, wgadmin, "CLIENTS_JSON", self.old_clients)
        self.addCleanup(setattr, wgadmin, "EXIT_POLICY", self.old_policy)

    def patch(self, name, value):
        old = getattr(wgadmin, name)
        setattr(wgadmin, name, value)
        self.addCleanup(setattr, wgadmin, name, old)

    def write_clients(self, clients):
        pathlib.Path(wgadmin.CLIENTS_JSON).write_text(json.dumps(clients))

    def test_bulk_updates_disabled_clients_and_syncs_once(self):
        self.write_clients([
            {"name": "a", "ip": "10.10.0.2", "pubkey": "A", "enabled": True},
            {"name": "b", "ip": "10.10.0.3", "pubkey": "B", "enabled": False, "exit": "us"},
        ])
        calls = []
        self.patch("run_exit_sync_or_raise", lambda: calls.append("sync"))
        self.patch("flush_exit_conntrack", lambda ip: calls.append(("flush", ip)))
        self.patch("audit", lambda op, detail: calls.append((op, detail)))
        result = wgadmin.setexitall_data("us", "manual")
        clients = json.loads(pathlib.Path(wgadmin.CLIENTS_JSON).read_text())
        self.assertEqual([x.get("exit") for x in clients], ["us", "us"])
        self.assertEqual(result["changed"], 1)
        self.assertEqual(calls.count("sync"), 1)
        self.assertIn(("flush", "10.10.0.2"), calls)

    def test_bulk_rolls_back_registry_and_routes(self):
        original = [{"name": "a", "ip": "10.10.0.2", "pubkey": "A", "enabled": True}]
        self.write_clients(original)
        calls = []
        def sync():
            calls.append("sync")
            if len(calls) == 1:
                raise RuntimeError("apply failed")
        self.patch("run_exit_sync_or_raise", sync)
        with self.assertRaisesRegex(RuntimeError, "rolled back"):
            wgadmin.setexitall_data("us", "quota")
        self.assertEqual(json.loads(pathlib.Path(wgadmin.CLIENTS_JSON).read_text()), original)
        self.assertEqual(calls, ["sync", "sync"])

    def test_policy_file_is_validated_and_atomic(self):
        self.patch("set_policy_owner", lambda path: None)
        result = wgadmin.setexitpolicy_data("1", "250", "750")
        saved = json.loads(pathlib.Path(wgadmin.EXIT_POLICY).read_text())
        self.assertTrue(saved["auto_switch"])
        self.assertEqual(saved["quota_bytes"]["us"], 750 * 1024 ** 3)
        self.assertEqual(result["quotas_gib"], {"nl": 250, "us": 750})

    def test_rollback_failure_is_explicit(self):
        self.write_clients([{"name": "a", "ip": "10.10.0.2", "pubkey": "A", "enabled": True}])
        self.patch("run_exit_sync_or_raise", lambda: (_ for _ in ()).throw(RuntimeError("sync failed")))
        with self.assertRaisesRegex(RuntimeError, "rollback failed"):
            wgadmin.setexitall_data("us", "quota")

    def test_switching_all_to_nl_removes_explicit_exit(self):
        self.write_clients([{"name": "a", "ip": "10.10.0.2", "pubkey": "A", "enabled": False, "exit": "us"}])
        self.patch("run_exit_sync_or_raise", lambda: None)
        self.patch("flush_exit_conntrack", lambda ip: None)
        self.patch("audit", lambda op, detail: None)
        wgadmin.setexitall_data("nl", "manual")
        self.assertNotIn("exit", json.loads(pathlib.Path(wgadmin.CLIENTS_JSON).read_text())[0])

    def test_bulk_reason_is_restricted(self):
        with self.assertRaisesRegex(ValueError, "reason"):
            wgadmin.setexitall_data("us", "browser-supplied")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run helper tests and verify RED**

```bash
python3 -m unittest discover -s tests -p 'test_exit_switching.py' -v
```

Expected: missing helper operation functions.

- [ ] **Step 3: Implement policy writes and compensating bulk transaction**

In `app/wg-admin.py`, import `grp` and `exit_policy`, define `EXIT_POLICY = "/etc/wg-ui/exit-policy.json"`, and add:

```python
def run_exit_sync_or_raise():
    r = run([EXIT_SH, "sync"], timeout=30)
    if r.returncode != 0:
        raise RuntimeError("exit-route sync failed: " + ((r.stderr or r.stdout) or "").strip()[-200:])


def flush_exit_conntrack(ip):
    run([EXIT_SH, "flush-ct", ip], timeout=10)


def set_policy_owner(path):
    try:
        gid = grp.getgrnam("wgui").gr_gid
    except KeyError:
        if os.geteuid() == 0:
            raise RuntimeError("wgui group not found")
        return
    os.chown(path, 0, gid)


def setexitpolicy_data(enabled, nl_gib, us_gib):
    if enabled not in ("0", "1"):
        raise ValueError("auto switch must be 0 or 1")
    policy = exit_policy.policy_from_gib(enabled == "1", nl_gib, us_gib)
    write_atomic(EXIT_POLICY, json.dumps(policy, indent=1) + "\n", 0o640)
    set_policy_owner(EXIT_POLICY)
    return {
        "auto_switch": policy["auto_switch"],
        "quotas_gib": {key: policy["quota_bytes"][key] // exit_policy.GIB for key in exit_policy.EXITS},
    }


def setexitall_data(target, reason):
    target = _normalize_exit(target)
    if reason not in ("manual", "quota"):
        raise ValueError("invalid switch reason")
    with open(CLIENTS_JSON) as f:
        original_text = f.read()
    clients = json.loads(original_text)
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
            write_atomic(CLIENTS_JSON, original_text, 0o644)
            run_exit_sync_or_raise()
        except Exception as rollback_error:
            raise RuntimeError("apply failed: %s; rollback failed: %s" % (apply_error, rollback_error))
        raise RuntimeError("apply failed and rolled back: %s" % apply_error)
    for client in changed:
        flush_exit_conntrack(client["ip"])
    direction = "%s -> %s" % ("mixed" if source_counts[target] else ("us" if target == "nl" else "nl"), target)
    audit("setexitall", "%s %s %d client(s)" % (reason, direction, len(changed)))
    return {"exit": target, "changed": len(changed), "source_counts": source_counts}
```

Wrap and dispatch with exact arity:

```python
def op_setexitall(target, reason):
    ok(setexitall_data(target, reason))


def op_setexitpolicy(enabled, nl_gib, us_gib):
    ok(setexitpolicy_data(enabled, nl_gib, us_gib))

# inside main dispatch
elif op == "setexitall" and len(a) == 2: op_setexitall(a[0], a[1])
elif op == "setexitpolicy" and len(a) == 3: op_setexitpolicy(a[0], a[1], a[2])
```

Refactor the existing single-client wrapper so its JSON behavior remains stable:

```python
def sync_exit_routes(flush_ip=None):
    try:
        run_exit_sync_or_raise()
    except RuntimeError as exc:
        die(str(exc))
    if flush_ip:
        flush_exit_conntrack(flush_ip)
```

- [ ] **Step 4: Run helper, syntax, and full tests**

```bash
python3 -m py_compile app/exit_policy.py app/wg-admin.py
python3 -m unittest discover -s tests -p 'test_exit_switching.py' -v
python3 -m unittest discover -s tests -q
```

Expected: helper transaction tests and full suite pass.

- [ ] **Step 5: Commit helper operations**

```bash
git add app/wg-admin.py tests/test_exit_switching.py
git commit -m "feat: add transactional bulk exit switching"
```

---

### Task 5: Server Policy Status, Automatic Evaluation, and API

**Files:**
- Modify: `app/wg-ui.py:35-52,120-168,243-305,371-393,589-765`
- Modify: `tests/test_exit_switching.py`
- Modify: `tests/test_units.py:372-421`

**Interfaces:**
- Consumes: accounting functions from Task 2 and policy decisions from Task 1.
- Consumes helper CLI: `setexitall` and `setexitpolicy` from Task 4.
- Produces: `exit_policy_status(tunnel_data=None, peers=None) -> dict`
- Produces: `guarded_exit_switch(target: str, reason: str) -> dict`
- Produces: `evaluate_auto_switch() -> dict`
- Produces API status field: `exit_policy`

- [ ] **Step 1: Add failing orchestration and status tests**

Insert the following loader and class before the existing `if __name__ == "__main__"` block in `tests/test_exit_switching.py`:

```python
os.environ.setdefault("WGUI_SESSION_SECRET", "exit-switching-test-secret-0123456789")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-exit-switching.gen"))
wgui_spec = importlib.util.spec_from_file_location("wgui_exit_switching", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(wgui_spec)
wgui_spec.loader.exec_module(wgui)
import exit_policy


class TestServerPolicy(unittest.TestCase):
    def patch(self, name, value):
        old = getattr(wgui, name)
        setattr(wgui, name, value)
        self.addCleanup(setattr, wgui, name, old)

    def test_status_contains_server_exit_usage_and_assignments(self):
        self.patch("policy_inputs", lambda: (
            exit_policy.policy_from_gib(True, 500, 750),
            {"nl": 30, "us": 7},
            {"nl": 1, "us": 1},
            {"nl": {"ok": True, "checked_age": 1}, "us": {"ok": True, "checked_age": 1}},
            None,
        ))
        status = wgui.exit_policy_status()
        self.assertEqual(status["exits"]["nl"]["used"], 30)
        self.assertEqual(status["exits"]["us"]["quota"], 750 * 1024 ** 3)
        self.assertEqual(status["exits"]["us"]["clients"], 1)

    def test_guarded_manual_switch_rejects_unhealthy_target(self):
        self.patch("policy_inputs", lambda: (
            exit_policy.policy_from_gib(True, 1, 1),
            {"nl": 0, "us": 0},
            {"nl": 1, "us": 0},
            {"nl": {"ok": True, "checked_age": 1}, "us": {"ok": False, "checked_age": 1}},
            None,
        ))
        result = wgui.guarded_exit_switch("us", "manual")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "target_unhealthy")
        self.assertEqual(result["http_status"], 409)

    def test_auto_switch_calls_bulk_helper_once(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True, "changed": 14, "exit": "us"})
        self.patch("policy_inputs", lambda: (
            exit_policy.policy_from_gib(True, 1, 1),
            {"nl": 1024 ** 3, "us": 0},
            {"nl": 14, "us": 0},
            {"nl": {"ok": True, "checked_age": 1}, "us": {"ok": True, "checked_age": 1}},
            None,
        ))
        result = wgui.evaluate_auto_switch()
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [["setexitall", "us", "quota"]])

    def test_new_admin_ops_remain_behind_csrf(self):
        class Fake(wgui.H):
            def __init__(self):
                self.path = "/api/admin"
                self.command = "POST"
                self.client_address = ("127.0.0.1", 1)
                self.headers = {"X-CSRF": "wrong"}
                self._code = None
                self._body = b""
            def _user(self): return "admin"
            def send_response(self, code): self._code = code
            def send_header(self, key, value): pass
            def end_headers(self): pass
        class Writer:
            def __init__(self, handler): self.handler = handler
            def write(self, body): self.handler._body += body
        handler = Fake()
        handler.wfile = Writer(handler)
        handler.do_POST()
        self.assertEqual(handler._code, 403)
```

Update `TestStatusCache.test_refresh_status_cache_builds_snap` to assert `exit_policy` is present.

- [ ] **Step 2: Run orchestration tests and verify RED**

```bash
python3 -m unittest discover -s tests -p 'test_exit_switching.py' -v
```

Expected: missing policy status and evaluator functions.

- [ ] **Step 3: Implement policy state and auto/manual orchestration**

In `app/wg-ui.py`, define:

```python
EXIT_POLICY = os.environ.get("WGUI_EXIT_POLICY", "/etc/wg-ui/exit-policy.json")
_policy_lock = threading.Lock()
_policy_runtime = {"blocked": None, "last_switch": None}


def load_exit_policy():
    return exit_policy.load_policy(EXIT_POLICY)


def assignment_counts(registry=None):
    out = {key: 0 for key in exit_policy.EXITS}
    for client in registry if registry is not None else (load_registry() or []):
        out[client_exit(client)] += 1
    return out


def policy_inputs():
    policy, warning = load_exit_policy()
    with _lock:
        month = {key: sum(_exit_month_usage[key].values()) for key in exit_policy.EXITS}
        health = {key: {"ok": bool(_egress[key].get("ok")),
                        "checked_age": int(time.time()) - _egress[key]["at"] if _egress[key].get("at") else -1}
                  for key in exit_policy.EXITS}
    return policy, month, assignment_counts(), health, warning


def exit_policy_status(tunnel_data=None, peers=None):
    policy, usage, assignments, health, warning = policy_inputs()
    with _lock:
        runtime = json.loads(json.dumps(_policy_runtime))
    exits = {}
    for key in exit_policy.EXITS:
        exits[key] = {
            "used": usage[key],
            "quota": policy["quota_bytes"][key],
            "clients": assignments[key],
            "healthy": health[key]["ok"] and 0 <= health[key]["checked_age"] <= exit_policy.HEALTH_MAX_AGE,
            "checked_age": health[key]["checked_age"],
            "exhausted": usage[key] >= policy["quota_bytes"][key],
        }
    return {"auto_switch": policy["auto_switch"], "exits": exits,
            "blocked": runtime["blocked"], "last_switch": runtime["last_switch"],
            "warning": warning}


def guarded_exit_switch(target, reason):
    with _policy_lock:
        policy, usage, assignments, health, warning = policy_inputs()
        if assignments.get(target, 0) == sum(assignments.values()):
            return {"ok": True, "exit": target, "changed": 0}
        blocked = exit_policy.target_block(target, policy, usage, health)
        if blocked:
            return dict({"ok": False, "error": blocked["code"], "http_status": 409}, **blocked)
        result = call_admin(["setexitall", target, reason])
        if result.get("ok"):
            event = {"ts": int(time.time()), "source": "us" if target == "nl" else "nl",
                     "target": target, "reason": reason, "changed": result.get("changed", 0)}
            with _lock:
                _policy_runtime["blocked"] = None
                _policy_runtime["last_switch"] = event
        elif reason == "quota":
            with _lock:
                _policy_runtime["blocked"] = {"code": "helper_failed", "target": target,
                                              "error": result.get("error", "helper failed")}
        log_event("exit_switch", ok=bool(result.get("ok")), reason=reason,
                  target=target, changed=result.get("changed", 0),
                  error=result.get("error"))
        return result


def evaluate_auto_switch():
    policy, usage, assignments, health, warning = policy_inputs()
    decision = exit_policy.evaluate_auto(policy, usage, assignments, health)
    if decision["blocked"]:
        with _lock:
            _policy_runtime["blocked"] = decision["blocked"]
        return {"ok": False, **decision["blocked"]}
    if not decision["action"]:
        with _lock:
            _policy_runtime["blocked"] = None
        return {"ok": True, "changed": 0}
    return guarded_exit_switch(decision["action"]["target"], "quota")
```

After exit usage is committed and `_exit_month_usage` refreshed in `_sampler()`, call outside `_lock`:

```python
try:
    evaluate_auto_switch()
except Exception as exc:
    log_event("exit_auto_switch", ok=False, error=str(exc)[:200])
```

Build `refresh_status_cache()` from one tunnel snapshot:

```python
tunnel_data = tunnel()
peers = clients_status()
snap = {"now": int(time.time()), "tunnel": tunnel_data, "host": host(),
        "rud": rud_on(), "peers": peers, "thr": throughput(),
        "sampler": sampler_info(), "exit_policy": exit_policy_status(tunnel_data, peers)}
```

In `/api/admin`:

```python
elif op == "setexitall":
    target = str(b.get("exit") or "").strip().lower()
    try:
        target = normalize_exit(target)
    except ValueError as e:
        return self._json(400, {"ok": False, "error": str(e)})
    res = guarded_exit_switch(target, "manual")
    log_event("admin", op=op, ok=bool(res.get("ok")), user=user,
              ip=self.client_address[0], name=None)
    return self._json(res.pop("http_status", 200 if res.get("ok") else 400), res)
elif op == "setexitpolicy":
    quotas = b.get("quotas_gib")
    try:
        validated = exit_policy.policy_from_gib(b.get("auto_switch"), quotas["nl"], quotas["us"])
    except (KeyError, TypeError, ValueError) as e:
        return self._json(400, {"ok": False, "error": str(e)})
    argv = ["setexitpolicy", "1" if validated["auto_switch"] else "0",
            str(validated["quota_bytes"]["nl"] // exit_policy.GIB),
            str(validated["quota_bytes"]["us"] // exit_policy.GIB)]
```

Keep normal CSRF/auth checks ahead of both branches. In the shared helper result path, refresh policy status after a save:

```python
res = call_admin(argv, 180 if op in ("splitsave", "splitserver") else 30)
if op == "setexitpolicy" and res.get("ok"):
    refresh_status_cache()
log_event("admin", op=op, ok=bool(res.get("ok")), user=user,
          ip=self.client_address[0], name=name or None)
return self._json(200 if res.get("ok") else 400, res)
```

- [ ] **Step 4: Run orchestration, API-adjacent, and full tests**

```bash
python3 -m py_compile app/*.py
python3 -m unittest discover -s tests -p 'test_exit_switching.py' -v
python3 -m unittest discover -s tests -q
```

Expected: orchestration and full tests pass with `exit_policy` in status.

- [ ] **Step 5: Commit server orchestration**

```bash
git add app/wg-ui.py tests/test_exit_switching.py tests/test_units.py
git commit -m "feat: automate exit switching at monthly quota"
```

---

### Task 6: Exit Policy UI and Manual Bulk Controls

**Files:**
- Modify: `app/index.html:5-10,25-28`
- Modify: `app/app.js:87-111,118-205,349-365,397-647`
- Modify: `app/app.css:31-75,365-405,409-457`
- Modify: `app/sw.js:1`
- Modify: `tests/test_frontend_monthly.py`

**Interfaces:**
- Consumes: `/api/status.exit_policy` from Task 5.
- Sends: `{op:"setexitpolicy",auto_switch,quotas_gib:{nl,us}}`.
- Sends: `{op:"setexitall",exit:"nl"|"us"}` after confirmation.
- Produces: `renderExitPolicy(policy)`, `openExitRouting()`, `saveExitPolicy()`, `confirmExitAll(target)`, and `doExitAll(target)`.

- [ ] **Step 1: Replace frontend expectations with failing server-policy tests**

Update `tests/test_frontend_monthly.py` so the HTML assertion requires quota controls to be buttons and a policy alert mount:

```python
self.assertIn('button class="pill monthpill" id="monthuse-nl"', html)
self.assertIn('button class="pill monthpill" id="monthuse-us"', html)
self.assertIn('id="policyalert"', html)
```

Expose these helpers from the Node VM:

```javascript
globalThis.__policyTest = {
  monthExitHTML, renderExitPolicy, exitPolicyRowHTML,
  exitSwitchConfirmHTML, policyRequestBody, bulkTargetBlock
};
```

Use this status fixture:

```javascript
const policy = {
  auto_switch: true,
  exits: {
    nl: {used: 495 * 1024 ** 3, quota: 500 * 1024 ** 3, clients: 14, healthy: true, checked_age: 1, exhausted: false},
    us: {used: 0, quota: 750 * 1024 ** 3, clients: 0, healthy: false, checked_age: 1, exhausted: false}
  },
  blocked: {code: 'target_unhealthy', source: 'nl', target: 'us'},
  last_switch: null
};
helpers.renderExitPolicy(policy);
if(!element('monthuse-nl').innerHTML.includes('495.0 GiB') || !element('monthuse-nl').classList.contains('warn')) throw new Error('NL warning missing');
if(!element('policyalert').classList.contains('show')) throw new Error('blocked banner missing');
if(helpers.bulkTargetBlock(policy, 'us') !== 'target_unhealthy') throw new Error('unhealthy target must be blocked');
const body = helpers.policyRequestBody(true, '500', '750');
if(body.quotas_gib.nl !== 500 || body.quotas_gib.us !== 750) throw new Error('bad policy payload');
const row = helpers.exitPolicyRowHTML('us', policy.exits.us);
if(!row.includes('disabled') || !row.includes('target_unhealthy')) throw new Error('blocked target row missing');
const confirm = helpers.exitSwitchConfirmHTML('us', 14);
if(!confirm.includes('14') || !confirm.includes('briefly reconnect')) throw new Error('confirmation copy missing');
```

Replace the VM fake's `classList` with a Set-backed implementation so state assertions are real:

```javascript
const classes=new Set();
classList:{
 add(...xs){xs.forEach(x=>classes.add(x));},
 remove(...xs){xs.forEach(x=>classes.delete(x));},
 contains(x){return classes.has(x);},
 toggle(x,on){if(on===undefined)on=!classes.has(x);on?classes.add(x):classes.delete(x);return on;}
}
```

The fake elements used by action delegation also expose `closest(){return this;}` and the quota inputs expose string `value` fields.

- [ ] **Step 2: Run the frontend tests and verify RED**

```bash
python3 -m unittest discover -s tests -p 'test_frontend_monthly.py' -v
```

Expected: failures because quota pills are spans and policy helpers do not exist.

- [ ] **Step 3: Implement accessible status, modal, confirmation, and actions**

In `app/index.html`, replace the quota spans and add the alert mount:

```html
<button class="pill monthpill" id="monthuse-nl" type="button" data-act="exit-policy" aria-label="NL exit routing settings">…</button>
<button class="pill monthpill" id="monthuse-us" type="button" data-act="exit-policy" aria-label="US exit routing settings">…</button>
<div class="alert bad policyalert" id="policyalert" style="display:none" role="alert"></div>
```

In `app/app.js`, keep `_exitPolicy` as the last status value and replace peer regrouping for header pills:

```javascript
let _exitPolicy=null,_lastSwitchTs=0;
function monthExitHTML(label,e){
 const total=+e.used||0,quota=+e.quota||1;
 return '<span class="mlbl">'+esc(label)+'</span> <span class="msum"><b>'+fmtB(total)+'</b> <span class="mq">/ '+fmtB(quota)+'</span></span>';
}
function renderExitPolicy(policy){
 _exitPolicy=policy||null;
 if(!policy)return;
 EXITS.forEach(ex=>{
  const el=document.getElementById('monthuse-'+ex),e=policy.exits[ex],ratio=e.quota?e.used/e.quota:0;
  if(!el)return;
  el.innerHTML=monthExitHTML(ex.toUpperCase(),e);
  el.classList.toggle('warn',ratio>=.9&&ratio<1);
  el.classList.toggle('critical',ratio>=1);
 });
 const alert=document.getElementById('policyalert'),issue=policy.blocked||(policy.warning?{code:policy.warning}:null);
 if(issue){alert.innerHTML=ic('warn')+'<b>'+tr(policy.blocked?'Automatic exit switch blocked':'Exit policy warning')+'</b> · '+tr(issue.code);alert.style.display='flex';alert.classList.add('show');}
 else{alert.style.display='none';alert.classList.remove('show');}
 if(policy.last_switch&&policy.last_switch.reason==='quota'&&policy.last_switch.ts>_lastSwitchTs){
  _lastSwitchTs=policy.last_switch.ts;
  toast(tr('All clients switched to')+' '+policy.last_switch.target.toUpperCase()+': '+tr('quota reached'));
 }
}
function bulkTargetBlock(policy,target){
 const e=policy&&policy.exits&&policy.exits[target];
 if(!e)return'invalid_target';
 if(e.exhausted)return'target_exhausted';
 if(e.checked_age<0||e.checked_age>60)return'target_stale';
 if(!e.healthy)return'target_unhealthy';
 return'';
}
function policyRequestBody(enabled,nl,us){
 return{op:'setexitpolicy',auto_switch:!!enabled,quotas_gib:{nl:+nl,us:+us}};
}
function exitSwitchConfirmHTML(target,affected){
 return '<div class="mtitle" id="mtitle">'+tr('Switch all to')+' '+target.toUpperCase()+'?</div>'
  +'<p class="mtext">'+affected+' '+tr('clients will change exit')+'. '+tr('Active connections will briefly reconnect')+'.</p>'
  +'<div class="merr" id="xperr" role="alert"></div>'
  +'<div class="mrow"><button class="ghost" type="button" data-act="close">'+tr('Cancel')+'</button><button class="primary" type="button" data-act="exit-all" data-exit="'+target+'">'+tr('Switch all')+'</button></div>';
}
```

Change `tick()` to call `renderExitPolicy(d.exit_policy)`, then add these modal helpers:

```javascript
function exitPolicyRowHTML(key,e){
 const pct=Math.max(0,Math.min(100,e.quota?e.used*100/e.quota:0));
 const total=EXITS.reduce((n,x)=>n+(+_exitPolicy.exits[x].clients||0),0);
 const affected=Math.max(0,total-(+e.clients||0));
 const blocked=bulkTargetBlock(_exitPolicy,key),disabled=blocked||!affected;
 return '<section class="xprow"><div class="xph"><b>'+key.toUpperCase()+'</b>'
  +'<span class="'+(e.healthy?'ok':'bad')+'">'+tr(e.healthy?'healthy':'unavailable')+'</span></div>'
  +'<div class="xpmeta">'+fmtB(e.used)+' / '+fmtB(e.quota)+' · '+e.clients+' '+tr('clients')+'</div>'
  +'<div class="xpbar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="'+Math.round(pct)+'"><i class="xpfill" style="width:'+pct.toFixed(1)+'%"></i></div>'
  +'<label class="fl">'+tr('Monthly quota (GiB)')+'<input id="xpq-'+key+'" type="number" min="1" max="1000000" step="1" value="'+Math.round(e.quota/1073741824)+'"></label>'
  +'<button class="ghost" type="button" data-act="exit-all-confirm" data-exit="'+key+'" '+(disabled?'disabled':'')+'>'+tr('Switch all to')+' '+key.toUpperCase()+'</button>'
  +(blocked?'<div class="xpreason">'+tr(blocked)+'</div>':'')+'</section>';
}
function openExitRouting(){
 if(!_exitPolicy){toast('Exit policy unavailable');return;}
 openModal('<div class="mtitle" id="mtitle">'+tr('Exit routing')+'</div>'
  +'<div class="xpolicy">'+EXITS.map(x=>exitPolicyRowHTML(x,_exitPolicy.exits[x])).join('')+'</div>'
  +'<label class="xptoggle"><input id="xpauto" type="checkbox" '+(_exitPolicy.auto_switch?'checked':'')+'><span><b>'+tr('Auto switch')+'</b><small>'+tr('Switch when quota is reached')+'</small></span></label>'
  +'<div class="merr" id="xperr" role="alert"></div>'
  +'<div class="mrow"><button class="ghost" type="button" data-act="close">'+tr('Close')+'</button><button class="primary" type="button" data-act="exit-policy-save">'+tr('Save')+'</button></div>');
}
async function saveExitPolicy(){
 const nl=document.getElementById('xpq-nl').value,us=document.getElementById('xpq-us').value;
 const vals=[+nl,+us],err=document.getElementById('xperr');
 if(vals.some(v=>!Number.isInteger(v)||v<1||v>1000000)){err.textContent=tr('Quota must be a whole number from 1 to 1000000');return;}
 const r=await admin(policyRequestBody(document.getElementById('xpauto').checked,nl,us));
 if(!r||!r.ok){err.textContent=tr((r&&r.error)||'failed');return;}
 closeModal();toast('Exit policy saved');await tick();
}
function confirmExitAll(target){
 const total=EXITS.reduce((n,x)=>n+(+_exitPolicy.exits[x].clients||0),0);
 const affected=Math.max(0,total-(+_exitPolicy.exits[target].clients||0));
 openModal(exitSwitchConfirmHTML(target,affected));
}
async function doExitAll(target){
 const err=document.getElementById('xperr'),r=await admin({op:'setexitall',exit:target});
 if(!r||!r.ok){err.textContent=tr((r&&(r.code||r.error))||'failed');return;}
 closeModal();toast('All clients switched to '+target.toUpperCase());await tick();
}
```

Add action delegation branches:

```javascript
if(a==='exit-policy'){openExitRouting();return;}
if(a==='exit-policy-save'){saveExitPolicy();return;}
if(a==='exit-all-confirm'){confirmExitAll(t.getAttribute('data-exit'));return;}
if(a==='exit-all'){doExitAll(t.getAttribute('data-exit'));return;}
```

Add these translations to `RU`:

```javascript
'Exit routing':'Маршрутизация выходов','Monthly quota (GiB)':'Месячная квота (GiB)',
'Auto switch':'Автопереключение','Switch when quota is reached':'Переключать при достижении квоты',
'Switch all to':'Переключить всех на','Switch all':'Переключить всех','clients':'клиентов',
'clients will change exit':'клиентов сменят выход','Active connections will briefly reconnect':'Активные соединения кратковременно переподключатся',
'Exit policy unavailable':'Политика выходов недоступна','Exit policy saved':'Настройки выходов сохранены',
'Quota must be a whole number from 1 to 1000000':'Квота должна быть целым числом от 1 до 1000000',
'Automatic exit switch blocked':'Автопереключение выхода заблокировано',
'Exit policy warning':'Предупреждение настроек выходов',
'target_unhealthy':'целевой выход недоступен','target_stale':'проверка целевого выхода устарела',
'target_exhausted':'квота целевого выхода исчерпана','both_exhausted':'квоты обоих выходов исчерпаны','helper_failed':'ошибка применения маршрутизации',
'missing_policy':'настройки ещё не сохранены','invalid_policy':'файл настроек повреждён',
'healthy':'работает','unavailable':'недоступен','All clients switched to':'Все клиенты переключены на','quota reached':'квота достигнута'
```

Add these concrete styles to `app/app.css` and include `.monthpill` in the existing focus-visible selector:

```css
.monthpill{appearance:none;cursor:pointer}.monthpill.warn{border-color:rgba(210,153,34,.65);color:var(--amber)}
.monthpill.critical{border-color:rgba(248,81,73,.7);color:var(--red)}
.policyalert{margin-bottom:12px}.xpolicy{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
.xprow{border:1px solid var(--line);background:var(--panel2);border-radius:11px;padding:12px;min-width:0}
.xph{display:flex;align-items:center;justify-content:space-between;gap:8px}.xph .ok{color:var(--green)}.xph .bad{color:var(--red)}
.xpmeta,.xpreason{font-size:11.5px;color:var(--dim);margin-top:4px}.xpreason{color:var(--red)}
.xpbar{height:7px;background:var(--panel);border-radius:999px;overflow:hidden;margin:9px 0}.xpfill{display:block;height:100%;background:var(--accent)}
.xptoggle{display:flex;align-items:center;gap:10px;border:1px solid var(--line);border-radius:11px;padding:11px 12px;margin-bottom:14px}
.xptoggle span{display:flex;flex-direction:column}.xptoggle small{color:var(--dim)}
.xprow button[disabled]{opacity:.45;cursor:not-allowed}
@media(max-width:560px){.xpolicy{grid-template-columns:1fr}}
```

Bump `app/sw.js` from `wgui-shell-v22` to `wgui-shell-v23`.

- [ ] **Step 4: Run frontend, full, and syntax verification**

```bash
python3 -m unittest discover -s tests -p 'test_frontend_monthly.py' -v
python3 -m unittest discover -s tests -q
python3 -m py_compile app/*.py
bash -n app/*.sh deploy.sh
```

Expected: frontend tests, full suite, Python compilation, and shell syntax pass.

- [ ] **Step 5: Commit the policy UI**

```bash
git add app/index.html app/app.js app/app.css app/sw.js tests/test_frontend_monthly.py
git commit -m "feat: add bulk exit policy controls"
```

---

### Task 7: Operator Documentation and End-to-End Verification

**Files:**
- Modify: `README.md:10-16,36-68`
- Modify: `docs/SETUP.md:57-69,230-312`

**Interfaces:**
- Documents: `/etc/wg-ui/exit-policy.json`, direct exit-counter semantics, manual safeguards, automatic behavior, and month rollover.

- [ ] **Step 1: Update operator documentation**

Add to `README.md` after the dual-exit description:

```markdown
The exit quota controls can move the complete client registry in one operation.
Optional Auto switch moves all clients to the other healthy, non-exhausted exit
when the current exit reaches its configured calendar-month RX+TX quota. Quota
usage comes from the `wg-do` / `wg-us` WireGuard peer counters; the browser does
not need to remain open.
```

Add `/etc/wg-ui/exit-policy.json` to the secrets/data table as root-owned
auto-switch and per-exit quota configuration.

In `docs/SETUP.md` dual-exit section, document:

```markdown
The NL and US quota pills open **Exit routing**. A manual bulk switch is allowed
only when the target exit has a fresh successful egress probe and remaining
monthly quota. Auto switch uses the same checks, includes disabled clients in
the registry update, and leaves assignments unchanged at month rollover.
```

- [ ] **Step 2: Run the complete automated verification from a clean process**

```bash
python3 -m py_compile app/*.py
bash -n app/*.sh deploy.sh
python3 -m unittest discover -s tests -q
git diff --check
```

Expected: compilation and shell syntax succeed, all tests pass, and `git diff --check` prints nothing.

- [ ] **Step 3: Perform focused manual UI verification**

Run the application against a redacted/mock status fixture and verify both desktop and narrow viewport behavior:

```text
1. NL/US header controls show server-provided usage and configured quotas.
2. 90% usage shows warning text/state; 100% shows critical text/state.
3. Exit routing opens by mouse and keyboard and traps focus.
4. Unhealthy, stale, and exhausted targets are disabled with a visible reason.
5. Confirmation names the target, client count, and reconnect effect.
6. Auto switch and both quota inputs persist after save and the next status poll.
7. A blocked automatic switch remains visible on the main screen.
8. EN/RU, light/dark, reduced motion, and mobile layouts remain usable.
```

Record the viewport sizes and observed result in the implementation handoff; do not include live IPs, keys, client names, or credentials in screenshots.

- [ ] **Step 4: Review the final change set against acceptance criteria**

```bash
git diff --stat HEAD~6..HEAD
git log --oneline -7
```

Confirm the diff includes the policy model, exit accounting, strict routing,
transactional helper, server evaluator/API, UI, tests, and documentation; confirm
no unrelated untracked files were staged.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md docs/SETUP.md
git commit -m "docs: explain exit quota switching"
```

After this commit, rerun:

```bash
python3 -m py_compile app/*.py
bash -n app/*.sh deploy.sh
python3 -m unittest discover -s tests -q
git status --short
```

Expected: all verification commands pass; `git status --short` lists only the user's pre-existing unrelated untracked files.
