"""Health failover: debounced exit health, failover decisions, probes, readiness."""
import importlib.util
import os
import pathlib
import sys
import tempfile
import time
import types
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

os.environ.setdefault("WGUI_SESSION_SECRET", "health-failover-test-secret-0123456789")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-health-failover.gen"))
spec = importlib.util.spec_from_file_location("wgui_health_failover", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)
import exit_policy

GIB = exit_policy.GIB


def states(nl="up", us="up", at=None):
    at = int(time.time()) if at is None else at
    return {"nl": {"state": nl, "at": at}, "us": {"state": us, "at": at}}


class TestHealthState(unittest.TestCase):
    def test_debounce_requires_consecutive_failures_and_successes(self):
        st = None
        for _ in range(exit_policy.OK_PROBES):
            st = exit_policy.next_health_state(st, True, 100)
        self.assertEqual(st["state"], "up")
        for i in range(exit_policy.FAIL_PROBES - 1):
            st = exit_policy.next_health_state(st, False, 101 + i)
            self.assertEqual(st["state"], "up")
        st = exit_policy.next_health_state(st, True, 110)       # a blip resets the fail streak
        for i in range(exit_policy.FAIL_PROBES - 1):
            st = exit_policy.next_health_state(st, False, 111 + i)
        self.assertEqual(st["state"], "up")
        st = exit_policy.next_health_state(st, False, 120)
        self.assertEqual(st["state"], "down")
        self.assertEqual(st["since"], 120)
        st = exit_policy.next_health_state(st, True, 130)
        self.assertEqual(st["state"], "down")
        st = exit_policy.next_health_state(st, True, 140)
        self.assertEqual(st["state"], "up")

    def test_starts_unknown(self):
        st = exit_policy.next_health_state(None, False, 1)
        self.assertEqual(st["state"], "unknown")


class TestEvaluateHealth(unittest.TestCase):
    policy = exit_policy.policy_from_gib(False, 500, 500)

    def decide(self, st, assignments, usage=None, last=None, policy=None):
        return exit_policy.evaluate_health(policy or self.policy, usage or {"nl": 0, "us": 0},
                                           assignments, st, int(time.time()), last)

    def test_moves_clients_off_down_exit_even_with_quota_auto_switch_off(self):
        d = self.decide(states(nl="up", us="down"), {"nl": 0, "us": 17})
        self.assertEqual(d["action"], {"source": "us", "target": "nl", "reason": "health"})

    def test_no_action_when_down_exit_is_unused(self):
        d = self.decide(states(nl="up", us="down"), {"nl": 17, "us": 0})
        self.assertEqual(d, {"action": None, "blocked": None})

    def test_unknown_state_is_not_a_failure(self):
        d = self.decide(states(nl="up", us="unknown"), {"nl": 0, "us": 17})
        self.assertIsNone(d["action"])
        self.assertIsNone(d["blocked"])

    def test_blocks_when_target_not_confirmed_up(self):
        for target_state in ("down", "unknown"):
            with self.subTest(target_state=target_state):
                d = self.decide(states(nl=target_state, us="down"), {"nl": 1, "us": 17})
                self.assertIsNone(d["action"])
        d = self.decide(states(nl="unknown", us="down"), {"nl": 0, "us": 17})
        self.assertEqual(d["blocked"]["code"], "target_unhealthy")
        d = self.decide(states(nl="down", us="down"), {"nl": 1, "us": 17})
        self.assertEqual(d["blocked"]["code"], "both_unhealthy")

    def test_blocks_on_stale_target_state(self):
        old = int(time.time()) - exit_policy.HEALTH_MAX_AGE - 5
        st = {"nl": {"state": "up", "at": old}, "us": {"state": "down", "at": int(time.time())}}
        self.assertEqual(self.decide(st, {"nl": 0, "us": 3})["blocked"]["code"], "target_unhealthy")

    def test_blocks_on_exhausted_target_and_cooldown(self):
        d = self.decide(states(us="down"), {"nl": 0, "us": 3}, usage={"nl": 500 * GIB, "us": 0})
        self.assertEqual(d["blocked"]["code"], "target_exhausted")
        d = self.decide(states(us="down"), {"nl": 0, "us": 3}, last=int(time.time()) - 10)
        self.assertEqual(d["blocked"]["code"], "failover_cooldown")
        d = self.decide(states(us="down"), {"nl": 0, "us": 3},
                        last=int(time.time()) - exit_policy.HEALTH_COOLDOWN - 1)
        self.assertEqual(d["action"]["target"], "nl")

    def test_disabled_by_policy(self):
        off = exit_policy.policy_from_gib(False, 500, 500, health_failover=False)
        self.assertEqual(self.decide(states(us="down"), {"nl": 0, "us": 3}, policy=off),
                         {"action": None, "blocked": None})

    def test_legacy_policy_without_flag_defaults_on(self):
        raw = {"version": 1, "auto_switch": False, "quota_bytes": {"nl": 500 * GIB, "us": 500 * GIB}}
        self.assertTrue(exit_policy.validate_policy(raw)["health_failover"])


class ServerCase(unittest.TestCase):
    def setUp(self):
        with wgui._lock:
            saved = ({k: dict(v) for k, v in wgui._egress.items()},
                     {k: dict(v) for k, v in wgui._health.items()},
                     dict(wgui._health_runtime), dict(wgui._exit_totals),
                     dict(wgui._policy_runtime))

        def restore():
            with wgui._lock:
                for target, value in zip((wgui._egress, wgui._health, wgui._health_runtime,
                                          wgui._exit_totals, wgui._policy_runtime), saved):
                    target.clear()
                    target.update(value)
        self.addCleanup(restore)

    def patch(self, name, value):
        old = getattr(wgui, name)
        setattr(wgui, name, value)
        self.addCleanup(setattr, wgui, name, old)

    def set_health(self, nl_ok, us_ok, nl_state, us_state):
        now = int(time.time())
        with wgui._lock:
            wgui._egress["nl"].update(ok=nl_ok, seen=None, at=now)
            wgui._egress["us"].update(ok=us_ok, seen=None, at=now)
            wgui._health["nl"] = {"state": nl_state, "fails": 0, "oks": 0, "since": now, "at": now}
            wgui._health["us"] = {"state": us_state, "fails": 0, "oks": 0, "since": now, "at": now}


class TestFailoverExecution(ServerCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.patch("call_admin", lambda argv, timeout=30: self.calls.append(argv) or {"ok": True, "changed": 17})
        self.patch("load_exit_policy", lambda: (exit_policy.policy_from_gib(False, 500, 500), None))
        self.patch("load_registry", lambda: [{"name": "c%d" % i, "exit": "us"} for i in range(17)])
        with wgui._lock:
            wgui._health_runtime.update(blocked=None, last_switch_at=0)

    def test_down_us_moves_everyone_to_nl_without_us_counters(self):
        self.set_health(True, False, "up", "down")
        with wgui._lock:
            wgui._exit_totals.update({"nl": (0, 0), "us": None})   # wg-us iface gone
        result = wgui.evaluate_health_failover()
        self.assertTrue(result["ok"])
        self.assertEqual(self.calls, [["setexitall", "nl", "health"]])
        self.assertEqual(wgui._policy_runtime["last_switch"]["reason"], "health")
        # cooldown: an immediate second evaluation does not call the helper again
        self.calls.clear()
        self.assertFalse(wgui.evaluate_health_failover()["ok"])
        self.assertEqual(self.calls, [])

    def test_target_without_counters_is_blocked(self):
        self.set_health(True, False, "up", "down")
        with wgui._lock:
            wgui._exit_totals.update({"nl": None, "us": (0, 0)})
        result = wgui.evaluate_health_failover()
        self.assertFalse(result["ok"])
        self.assertEqual(self.calls, [])
        self.assertEqual(wgui._health_runtime["blocked"]["code"], "counter_unavailable")

    def test_manual_switch_off_dead_exit_needs_only_target_counters(self):
        self.set_health(True, False, "up", "down")
        with wgui._lock:
            wgui._exit_totals.update({"nl": (0, 0), "us": None})
        result = wgui.guarded_exit_switch("nl", "manual")
        self.assertTrue(result["ok"])
        self.assertEqual(self.calls, [["setexitall", "nl", "manual"]])

    def test_helper_failure_surfaces_as_health_block(self):
        self.patch("call_admin", lambda argv, timeout=30: {"ok": False, "error": "boom"})
        self.set_health(True, False, "up", "down")
        with wgui._lock:
            wgui._exit_totals.update({"nl": (0, 0), "us": (0, 0)})
        self.assertFalse(wgui.evaluate_health_failover()["ok"])
        self.assertEqual(wgui._health_runtime["blocked"]["code"], "helper_failed")
        self.assertEqual(wgui._health_runtime["last_switch_at"], 0)

    def test_health_tick_debounces_before_switching(self):
        with wgui._lock:
            wgui._exit_totals.update({"nl": (0, 0), "us": (0, 0)})
            for key in ("nl", "us"):
                wgui._health[key] = {"state": "up", "fails": 0, "oks": 2, "since": 0, "at": int(time.time())}
        self.patch("_probe_egress", lambda: {"nl": (True, "192.0.2.1"), "us": (False, None)})
        for _ in range(exit_policy.FAIL_PROBES - 1):
            wgui.health_tick()
        self.assertEqual(self.calls, [])
        wgui.health_tick()
        self.assertEqual(self.calls, [["setexitall", "nl", "health"]])


class TestProbe(ServerCase):
    def run_with(self, results):
        it = iter(results)
        self.patch("subprocess", types.SimpleNamespace(
            run=lambda *a, **k: next(it), TimeoutExpired=Exception))

    def test_html_error_page_is_not_an_ip(self):
        self.run_with([types.SimpleNamespace(returncode=0, stdout="<html>bad gateway</html>"),
                       types.SimpleNamespace(returncode=0, stdout="<html>x</html>")])
        self.assertEqual(wgui._probe_via("wg-us", None), (False, None))

    def test_curl_failure_falls_through_to_next_url(self):
        self.run_with([types.SimpleNamespace(returncode=22, stdout="192.0.2.9"),
                       types.SimpleNamespace(returncode=0, stdout="192.0.2.10\n")])
        self.assertEqual(wgui._probe_via("wg-us", None), (True, "192.0.2.10"))

    def test_expected_ip_mismatch_is_unhealthy(self):
        self.run_with([types.SimpleNamespace(returncode=0, stdout="192.0.2.9"),
                       types.SimpleNamespace(returncode=0, stdout="192.0.2.9")])
        self.assertEqual(wgui._probe_via("wg-us", "198.51.100.1"), (False, "192.0.2.9"))


class TestStatusSemantics(ServerCase):
    def test_all_clients_on_failing_exit_is_down_even_if_other_exit_ok(self):
        self.set_health(True, False, "up", "down")
        t = wgui.tunnel([{"exit": "us"}, {"exit": "us", "enabled": True}, {"exit": "us", "enabled": False}])
        self.assertEqual(t["state"], "down")
        self.assertEqual(t["affected_clients"], 2)
        self.assertEqual(t["exits"]["us"]["affected_clients"], 2)

    def test_partial_impact_is_degraded_and_unused_dead_exit_is_up(self):
        self.set_health(True, False, "up", "down")
        self.assertEqual(wgui.tunnel([{"exit": "us"}, {}])["state"], "degraded")
        self.assertEqual(wgui.tunnel([{}, {}])["state"], "up")

    def test_stale_success_is_not_ok(self):
        self.set_health(True, True, "up", "up")
        with wgui._lock:
            wgui._egress["nl"]["at"] = int(time.time()) - exit_policy.HEALTH_MAX_AGE - 1
        self.assertFalse(wgui.tunnel([])["exits"]["nl"]["ok"])

    def test_cached_snapshot_ages_on_read(self):
        snap = {"now": 1000, "tunnel": {"exits": {"nl": {"ok": True, "checked_age": 5}}},
                "exit_policy": {"exits": {"nl": {"healthy": True, "checked_age": 5}}}}
        out = wgui._age_snapshot(snap, 1000 + exit_policy.HEALTH_MAX_AGE)
        self.assertFalse(out["tunnel"]["exits"]["nl"]["ok"])
        self.assertFalse(out["exit_policy"]["exits"]["nl"]["healthy"])
        self.assertEqual(out["now"], 1000 + exit_policy.HEALTH_MAX_AGE)


class TestReadyz(ServerCase):
    def setUp(self):
        super().setUp()
        with wgui._lock:
            self.saved_meta = {k: dict(v) for k, v in wgui._sampler_meta.items()}
            self.saved_snap = wgui._status_snap
        def restore():
            with wgui._lock:
                for k, v in self.saved_meta.items():
                    wgui._sampler_meta[k].clear()
                    wgui._sampler_meta[k].update(v)
                wgui._status_snap = self.saved_snap
        self.addCleanup(restore)
        self.patch("_STARTED_AT", time.time() - 3600)

    def set_ready(self, sampler_age=1, loop_age=1, persist_err=None):
        now = int(time.time())
        with wgui._lock:
            wgui._sampler_meta["collection"].update(ok_at=now - sampler_age, err=None)
            wgui._sampler_meta["persistence"].update(err=persist_err)
            wgui._health_runtime["loop_at"] = now - loop_age
            wgui._status_snap = {"now": now}

    def test_ready_ignores_exit_outage(self):
        self.set_ready()
        self.set_health(False, False, "down", "down")
        self.assertTrue(wgui.readyz()["ready"])

    def test_stalled_sampler_or_health_loop_is_not_ready(self):
        self.set_ready(sampler_age=600)
        self.assertFalse(wgui.readyz()["ready"])
        self.set_ready(loop_age=600)
        self.assertFalse(wgui.readyz()["ready"])
        self.set_ready(persist_err="disk full")
        self.assertFalse(wgui.readyz()["ready"])

    def test_startup_grace(self):
        self.patch("_STARTED_AT", time.time())
        with wgui._lock:
            wgui._sampler_meta["collection"].update(ok_at=0)
            wgui._sampler_meta["persistence"].update(err=None)
            wgui._health_runtime["loop_at"] = 0
        r = wgui.readyz()
        self.assertTrue(r["ready"])
        self.assertTrue(r["starting"])


if __name__ == "__main__":
    unittest.main()
