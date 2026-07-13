import builtins
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import stat
import sys
import tempfile
import types
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
        self.old_lock = wgadmin.LOCKFILE
        wgadmin.CLIENTS_JSON = os.path.join(self.tmp.name, "clients.json")
        wgadmin.EXIT_POLICY = os.path.join(self.tmp.name, "exit-policy.json")
        wgadmin.LOCKFILE = os.path.join(self.tmp.name, "admin.lock")
        self.addCleanup(setattr, wgadmin, "CLIENTS_JSON", self.old_clients)
        self.addCleanup(setattr, wgadmin, "EXIT_POLICY", self.old_policy)
        self.addCleanup(setattr, wgadmin, "LOCKFILE", self.old_lock)

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
        policy_path = pathlib.Path(wgadmin.EXIT_POLICY)
        saved = json.loads(policy_path.read_text())
        self.assertTrue(saved["auto_switch"])
        self.assertEqual(saved["quota_bytes"]["us"], 750 * 1024 ** 3)
        self.assertEqual(result["quotas_gib"], {"nl": 250, "us": 750})
        self.assertEqual(stat.S_IMODE(policy_path.stat().st_mode), 0o640)

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

    def test_rollback_restores_exact_registry_bytes(self):
        original_text = '[ { "name" : "a", "ip" : "10.10.0.2", "enabled" : true } ]\n'
        pathlib.Path(wgadmin.CLIENTS_JSON).write_text(original_text)
        sync_calls = []

        def sync():
            sync_calls.append("sync")
            if len(sync_calls) == 1:
                raise RuntimeError("route apply exploded")

        self.patch("run_exit_sync_or_raise", sync)
        with self.assertRaisesRegex(RuntimeError, "route apply exploded"):
            wgadmin.setexitall_data("us", "manual")
        self.assertEqual(pathlib.Path(wgadmin.CLIENTS_JSON).read_bytes(), original_text.encode())

    def test_rollback_failure_reports_apply_and_rollback_causes(self):
        self.write_clients([{"name": "a", "ip": "10.10.0.2", "enabled": True}])
        errors = iter((RuntimeError("apply route cause"), RuntimeError("restore route cause")))
        self.patch("run_exit_sync_or_raise", lambda: (_ for _ in ()).throw(next(errors)))
        with self.assertRaises(RuntimeError) as raised:
            wgadmin.setexitall_data("us", "manual")
        message = str(raised.exception)
        self.assertIn("apply route cause", message)
        self.assertIn("rollback failed", message)
        self.assertIn("restore route cause", message)

    def test_flushes_only_changed_enabled_clients(self):
        self.write_clients([
            {"name": "enabled", "ip": "10.10.0.2", "enabled": True},
            {"name": "legacy-enabled", "ip": "10.10.0.3"},
            {"name": "disabled", "ip": "10.10.0.4", "enabled": False},
            {"name": "unchanged", "ip": "10.10.0.5", "enabled": True, "exit": "us"},
        ])
        flushed = []
        self.patch("run_exit_sync_or_raise", lambda: None)
        self.patch("flush_exit_conntrack", flushed.append)
        self.patch("audit", lambda op, detail: None)
        result = wgadmin.setexitall_data("us", "quota")
        self.assertEqual(result["changed"], 3)
        self.assertEqual(flushed, ["10.10.0.2", "10.10.0.3"])

    def test_conntrack_failure_does_not_falsify_committed_switch(self):
        self.write_clients([{"name": "a", "ip": "10.10.0.2", "enabled": True}])
        calls = []
        self.patch("run_exit_sync_or_raise", lambda: calls.append("sync"))
        self.patch("flush_exit_conntrack", lambda ip: (_ for _ in ()).throw(RuntimeError("conntrack unavailable")))
        self.patch("audit", lambda op, detail: calls.append((op, detail)))
        result = wgadmin.setexitall_data("us", "manual")
        self.assertEqual(result["changed"], 1)
        self.assertEqual(json.loads(pathlib.Path(wgadmin.CLIENTS_JSON).read_text())[0]["exit"], "us")
        self.assertEqual(calls.count("sync"), 1)

    def test_noop_does_not_sync_flush_or_audit(self):
        self.write_clients([
            {"name": "a", "ip": "10.10.0.2", "enabled": True, "exit": "us"},
            {"name": "b", "ip": "10.10.0.3", "enabled": False, "exit": "us"},
        ])
        calls = []
        self.patch("run_exit_sync_or_raise", lambda: calls.append("sync"))
        self.patch("flush_exit_conntrack", lambda ip: calls.append(("flush", ip)))
        self.patch("audit", lambda op, detail: calls.append((op, detail)))
        result = wgadmin.setexitall_data("us", "manual")
        self.assertEqual(result, {"exit": "us", "changed": 0, "source_counts": {"nl": 0, "us": 2}})
        self.assertEqual(calls, [])

    def test_policy_validation_does_not_replace_existing_file(self):
        policy_path = pathlib.Path(wgadmin.EXIT_POLICY)
        policy_path.write_text("keep-me\n")
        self.patch("set_policy_owner", lambda path: None)
        for values in (("2", "250", "750"), ("1", "0", "750"), ("1", "250", "1000001"), ("1", "2.5", "750")):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    wgadmin.setexitpolicy_data(*values)
                self.assertEqual(policy_path.read_text(), "keep-me\n")

    def test_policy_owner_is_root_wgui(self):
        calls = []
        old_getgrnam = wgadmin.grp.getgrnam
        old_chown = wgadmin.os.chown
        wgadmin.grp.getgrnam = lambda name: types.SimpleNamespace(gr_gid=4321)
        wgadmin.os.chown = lambda path, uid, gid: calls.append((path, uid, gid))
        self.addCleanup(setattr, wgadmin.grp, "getgrnam", old_getgrnam)
        self.addCleanup(setattr, wgadmin.os, "chown", old_chown)
        wgadmin.set_policy_owner("/tmp/policy")
        self.assertEqual(calls, [("/tmp/policy", 0, 4321)])

    def test_new_cli_operations_require_exact_arity(self):
        calls = []
        open_locks = []

        def tracked_open(*args, **kwargs):
            lock = builtins.open(*args, **kwargs)
            open_locks.append(lock)
            return lock

        wgadmin.open = tracked_open
        self.addCleanup(lambda: [lock.close() for lock in open_locks])
        self.addCleanup(delattr, wgadmin, "open")

        def call_main():
            try:
                wgadmin.main()
            finally:
                open_locks.pop().close()

        def record(kind):
            def operation(*args):
                calls.append((kind, args))
                raise SystemExit
            return operation

        self.patch("op_setexitall", record("all"))
        self.patch("op_setexitpolicy", record("policy"))
        old_argv = sys.argv
        self.addCleanup(setattr, sys, "argv", old_argv)

        sys.argv = ["wg-admin.py", "setexitall", "us", "manual"]
        with self.assertRaises(SystemExit):
            call_main()
        sys.argv = ["wg-admin.py", "setexitpolicy", "1", "250", "750"]
        with self.assertRaises(SystemExit):
            call_main()
        self.assertEqual(calls, [("all", ("us", "manual")), ("policy", ("1", "250", "750"))])

        for argv in (
            ["wg-admin.py", "setexitall", "us"],
            ["wg-admin.py", "setexitall", "us", "manual", "force"],
            ["wg-admin.py", "setexitpolicy", "1", "250"],
            ["wg-admin.py", "setexitpolicy", "1", "250", "750", "extra"],
        ):
            with self.subTest(argv=argv):
                sys.argv = argv
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
                    call_main()
                self.assertEqual(json.loads(output.getvalue()), {"ok": False, "error": "bad operation or arguments"})

    def test_bulk_wrapper_preserves_structured_json(self):
        self.patch("setexitall_data", lambda target, reason: {"exit": target, "changed": 4})
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            wgadmin.op_setexitall("us", "manual")
        self.assertEqual(json.loads(output.getvalue()), {"ok": True, "exit": "us", "changed": 4})

    def test_single_client_route_sync_keeps_structured_error(self):
        self.patch("run_exit_sync_or_raise", lambda: (_ for _ in ()).throw(RuntimeError("route failed")))
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            wgadmin.sync_exit_routes("10.10.0.2")
        self.assertEqual(json.loads(output.getvalue()), {"ok": False, "error": "route failed"})


if __name__ == "__main__":
    unittest.main()
