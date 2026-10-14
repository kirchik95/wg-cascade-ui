"""Exit-switch events with membership, last_switch restore, and group revert."""
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

os.environ.setdefault("WGUI_SESSION_SECRET", "failover-events-secret-0123456789ab")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-failover-events.gen"))
spec = importlib.util.spec_from_file_location("wgui_failover_events", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)
admin_spec = importlib.util.spec_from_file_location("wgadmin_failover_events", str(APP / "wg-admin.py"))
wgadmin = importlib.util.module_from_spec(admin_spec)
admin_spec.loader.exec_module(wgadmin)
import exit_policy

PUBS = ["%s" % (chr(ord("A") + i) * 43) + "=" for i in range(6)]


def client(i, exit_="nl", enabled=True):
    c = {"name": "c%d" % i, "ip": "10.10.0.%d" % (i + 2), "pubkey": PUBS[i], "enabled": enabled}
    if exit_ != "nl":
        c["exit"] = exit_
    return c


class HelperCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in (("CLIENTS_JSON", os.path.join(self.tmp.name, "clients.json")),
                            ("LOCKFILE", os.path.join(self.tmp.name, "admin.lock"))):
            old = getattr(wgadmin, name)
            setattr(wgadmin, name, value)
            self.addCleanup(setattr, wgadmin, name, old)
        self.calls = []
        self.patch("run_exit_sync_or_raise", lambda: self.calls.append("sync"))
        self.patch("flush_exit_conntrack", lambda ips: self.calls.append(("flush", list(ips))) or None)
        self.patch("audit", lambda op, detail="": self.calls.append((op, detail)))

    def patch(self, name, value):
        old = getattr(wgadmin, name)
        setattr(wgadmin, name, value)
        self.addCleanup(setattr, wgadmin, name, old)

    def write(self, clients):
        pathlib.Path(wgadmin.CLIENTS_JSON).write_text(json.dumps(clients))

    def read(self):
        return json.loads(pathlib.Path(wgadmin.CLIENTS_JSON).read_text())


class TestSetExitAllMembership(HelperCase):
    def test_reports_who_moved_and_from_where(self):
        self.write([client(0, "us"), client(1, "nl"), client(2, "us", enabled=False)])
        result = wgadmin.setexitall_data("nl", "health")
        self.assertEqual(result["changed"], 2)
        self.assertEqual(result["changed_clients"], [
            {"pubkey": PUBS[0], "name": "c0", "from": "us"},
            {"pubkey": PUBS[2], "name": "c2", "from": "us"},
        ])
        self.assertTrue(all("exit" not in c for c in self.read()))


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_db = wgui.DB
        wgui.DB = os.path.join(self.tmp.name, "history.db")
        self.addCleanup(setattr, wgui, "DB", self.old_db)
        wgui.db_init()
        with wgui._lock:
            saved = (dict(wgui._exit_totals), dict(wgui._policy_runtime), dict(wgui._health_runtime))
            saved_health = {k: dict(v) for k, v in wgui._health.items()}
            saved_egress = {k: dict(v) for k, v in wgui._egress.items()}
            wgui._exit_totals.update({"nl": (0, 0), "us": (0, 0)})
            wgui._policy_runtime.update(blocked=None, last_switch=None)
            wgui._health_runtime.update(blocked=None, last_switch_at=0)

        def restore():
            with wgui._lock:
                for target, value in zip((wgui._exit_totals, wgui._policy_runtime, wgui._health_runtime), saved):
                    target.clear(); target.update(value)
                for k in saved_health:
                    wgui._health[k] = saved_health[k]
                    wgui._egress[k].clear(); wgui._egress[k].update(saved_egress[k])
        self.addCleanup(restore)

    def patch(self, name, value):
        old = getattr(wgui, name)
        setattr(wgui, name, value)
        self.addCleanup(setattr, wgui, name, old)

    @staticmethod
    def inputs(nl_ok=True, us_ok=True, nl_used=0, us_used=0, assignments=None):
        return (exit_policy.policy_from_gib(False, 500, 500),
                {"nl": nl_used, "us": us_used},
                assignments or {"nl": 3, "us": 2},
                {"nl": {"ok": nl_ok, "checked_age": 1}, "us": {"ok": us_ok, "checked_age": 1}},
                None)

    def switch_events(self):
        return [e for e in reversed(wgui.events_page(limit=200)) if e["kind"] == "exit_switch"]


class TestSwitchEvents(ServerCase):
    def test_switch_journals_members_and_links_last_switch(self):
        members = [{"pubkey": PUBS[0], "name": "c0", "from": "us"},
                   {"pubkey": PUBS[1], "name": "c1", "from": "us"}]
        self.patch("policy_inputs", lambda *a, **k: self.inputs())
        self.patch("call_admin", lambda argv, timeout=None: {
            "ok": True, "committed": True, "changed": 2, "changed_clients": members})
        result = wgui.guarded_exit_switch("nl", "manual", actor="admin", ip="192.0.2.5")
        self.assertTrue(result["ok"])
        [ev] = self.switch_events()
        self.assertEqual(result["event_id"], ev["id"])
        self.assertEqual((ev["actor"], ev["ip"], ev["subject"]), ("admin", "192.0.2.5", "us->nl"))
        self.assertEqual(ev["data"]["members"], members)
        last = wgui.exit_policy_status(
            {"exits": {"nl": {"ok": True, "checked_age": 1}, "us": {"ok": True, "checked_age": 1}}},
            [{"exit": "nl"}])["last_switch"]
        self.assertEqual((last["event_id"], last["members_count"], last["reason"]), (ev["id"], 2, "manual"))
        self.assertNotIn("members", last)

    def test_health_failover_event_is_system_and_has_members(self):
        self.patch("load_exit_policy", lambda: (exit_policy.policy_from_gib(False, 500, 500), None))
        self.patch("load_registry", lambda: [client(i, "us") for i in range(3)])
        now = int(time.time())
        with wgui._lock:
            wgui._egress["nl"].update(ok=True, at=now); wgui._egress["us"].update(ok=False, at=now)
            wgui._health["nl"] = {"state": "up", "fails": 0, "oks": 2, "since": now, "at": now}
            wgui._health["us"] = {"state": "down", "fails": 3, "oks": 0, "since": now, "at": now}
        moved = [{"pubkey": PUBS[i], "name": "c%d" % i, "from": "us"} for i in range(3)]
        self.patch("call_admin", lambda argv, timeout=None: {"ok": True, "changed": 3, "changed_clients": moved})
        self.assertTrue(wgui.evaluate_health_failover()["ok"])
        [ev] = self.switch_events()
        self.assertEqual((ev["actor"], ev["data"]["reason"], len(ev["data"]["members"])), ("system", "health", 3))

    def test_older_helper_without_membership_is_not_revertable(self):
        self.patch("policy_inputs", lambda *a, **k: self.inputs())
        self.patch("call_admin", lambda argv, timeout=None: {"ok": True, "changed": 4})
        wgui.guarded_exit_switch("nl", "manual")
        last = wgui._policy_runtime["last_switch"]
        self.assertEqual((last["changed"], last["members_count"]), (4, 0))

    def test_noop_switch_writes_no_event(self):
        self.patch("policy_inputs", lambda *a, **k: self.inputs())
        self.patch("call_admin", lambda argv, timeout=None: {"ok": True, "changed": 0})
        wgui.guarded_exit_switch("nl", "manual")
        self.assertEqual(self.switch_events(), [])
        self.assertIsNone(wgui._policy_runtime["last_switch"]["event_id"])

    def test_restart_restores_last_switch_and_health_cooldown(self):
        now = int(time.time())
        eid = wgui.record_event("exit_switch", subject="us->nl", actor="system", ts=now - 60,
                                data={"source": "us", "target": "nl", "reason": "health", "changed": 2,
                                      "members": [{"pubkey": PUBS[0], "name": "c0", "from": "us"},
                                                  {"pubkey": PUBS[1], "name": "c1", "from": "us"}]})
        value = wgui.restore_last_switch(now=now)
        self.assertEqual(value["event_id"], eid)
        self.assertEqual(wgui._policy_runtime["last_switch"]["members_count"], 2)
        # cooldown survives the restart: ~60 s elapsed, still inside HEALTH_COOLDOWN
        elapsed = time.monotonic() - wgui._health_runtime["last_switch_at"]
        self.assertAlmostEqual(elapsed, 60, delta=2)

    def test_restore_ignores_old_health_cooldown_and_empty_journal(self):
        self.assertIsNone(wgui.restore_last_switch())
        now = int(time.time())
        wgui.record_event("exit_switch", ts=now - exit_policy.HEALTH_COOLDOWN - 5,
                          data={"source": "us", "target": "nl", "reason": "health", "changed": 1, "members": []})
        wgui.restore_last_switch(now=now)
        self.assertEqual(wgui._health_runtime["last_switch_at"], 0)


if __name__ == "__main__":
    unittest.main()
