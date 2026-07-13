import builtins
import base64
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import stat
import sys
import tempfile
import tarfile
import threading
import time
import types
import unittest
from unittest import mock

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

spec = importlib.util.spec_from_file_location("wgadmin_exit_switching", str(APP / "wg-admin.py"))
wgadmin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgadmin)

os.environ.setdefault("WGUI_SESSION_SECRET", "exit-switching-test-secret-0123456789")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-exit-switching.gen"))
wgui_spec = importlib.util.spec_from_file_location("wgui_exit_switching", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(wgui_spec)
wgui_spec.loader.exec_module(wgui)
import exit_policy


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
        with mock.patch.object(wgadmin.grp, "getgrnam", side_effect=KeyError), \
                mock.patch.object(wgadmin.os, "geteuid", return_value=501), \
                mock.patch.object(wgadmin.os, "getegid", return_value=20), \
                mock.patch.object(wgadmin.os, "fchown"):
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

    def test_rollback_preserves_crlf_registry_bytes(self):
        original = (
            b'[\r\n'
            b' {"name": "a", "ip": "10.10.0.2", "enabled": true}\r\n'
            b']\r\n'
        )
        pathlib.Path(wgadmin.CLIENTS_JSON).write_bytes(original)
        sync_calls = []

        def sync():
            sync_calls.append("sync")
            if len(sync_calls) == 1:
                raise RuntimeError("route apply exploded")

        self.patch("run_exit_sync_or_raise", sync)
        with self.assertRaisesRegex(RuntimeError, "rolled back"):
            wgadmin.setexitall_data("us", "manual")
        self.assertEqual(pathlib.Path(wgadmin.CLIENTS_JSON).read_bytes(), original)

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
        for values in (("2", "250", "750"), ("1", "0", "750"), ("1", "250", "1000001"), ("1", "2.5", "750")):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    wgadmin.setexitpolicy_data(*values)
                self.assertEqual(policy_path.read_text(), "keep-me\n")

    def test_missing_policy_group_preserves_existing_file(self):
        policy_path = pathlib.Path(wgadmin.EXIT_POLICY)
        original = b'{"old": true}\n'
        policy_path.write_bytes(original)
        with mock.patch.object(wgadmin.grp, "getgrnam", side_effect=KeyError), \
                mock.patch.object(wgadmin.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "wgui group not found"):
                wgadmin.setexitpolicy_data("1", "250", "750")
        self.assertEqual(policy_path.read_bytes(), original)
        self.assertEqual({path.name for path in policy_path.parent.iterdir()}, {policy_path.name})

    def test_policy_fchown_failure_preserves_existing_file_and_cleans_temp(self):
        policy_path = pathlib.Path(wgadmin.EXIT_POLICY)
        original = b'{"old": true}\n'
        policy_path.write_bytes(original)
        fail = PermissionError("fchown denied")
        with mock.patch.object(wgadmin.grp, "getgrnam", return_value=types.SimpleNamespace(gr_gid=4321)), \
                mock.patch.object(wgadmin.os, "geteuid", return_value=0), \
                mock.patch.object(wgadmin.os, "chown", side_effect=fail), \
                mock.patch.object(wgadmin.os, "fchown", side_effect=fail):
            with self.assertRaisesRegex(PermissionError, "fchown denied"):
                wgadmin.setexitpolicy_data("1", "250", "750")
        self.assertEqual(policy_path.read_bytes(), original)
        self.assertEqual({path.name for path in policy_path.parent.iterdir()}, {policy_path.name})

    def test_policy_metadata_is_set_on_temp_before_replace(self):
        events = []
        real_mkstemp = wgadmin.tempfile.mkstemp
        real_replace = wgadmin.os.replace

        def getgrnam(name):
            events.append("group")
            return types.SimpleNamespace(gr_gid=4321)

        def mkstemp(*args, **kwargs):
            events.append("mkstemp")
            return real_mkstemp(*args, **kwargs)

        def replace(source, destination):
            events.append("replace")
            return real_replace(source, destination)

        with mock.patch.object(wgadmin.grp, "getgrnam", side_effect=getgrnam), \
                mock.patch.object(wgadmin.os, "geteuid", return_value=0), \
                mock.patch.object(wgadmin.tempfile, "mkstemp", side_effect=mkstemp), \
                mock.patch.object(wgadmin.os, "fsync", side_effect=lambda fd: events.append("fsync")), \
                mock.patch.object(wgadmin.os, "fchmod", side_effect=lambda fd, mode: events.append("fchmod")), \
                mock.patch.object(wgadmin.os, "fchown", side_effect=lambda fd, uid, gid: events.append("fchown")), \
                mock.patch.object(wgadmin.os, "replace", side_effect=replace), \
                mock.patch.object(wgadmin.os, "chown", side_effect=lambda path, uid, gid: events.append("chown")):
            wgadmin.setexitpolicy_data("1", "250", "750")
        self.assertEqual(events, ["group", "mkstemp", "fsync", "fchmod", "fchown", "replace"])

    def test_missing_policy_group_uses_current_owner_for_non_root_tests(self):
        owners = []
        with mock.patch.object(wgadmin.grp, "getgrnam", side_effect=KeyError), \
                mock.patch.object(wgadmin.os, "geteuid", return_value=501), \
                mock.patch.object(wgadmin.os, "getegid", return_value=20), \
                mock.patch.object(wgadmin.os, "fchown", side_effect=lambda fd, uid, gid: owners.append((uid, gid))):
            result = wgadmin.setexitpolicy_data("0", "250", "750")
        self.assertFalse(result["auto_switch"])
        self.assertEqual(owners, [(501, 20)])

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

    def test_recovery_export_includes_optional_exit_policy_with_safe_name(self):
        root = pathlib.Path(self.tmp.name)
        server = root / "wg-cl.conf"
        clients = root / "clients.json"
        split_extra = root / "split-extra.txt"
        client_dir = root / "client-configs"
        policy_dir = root / "policy-state"
        policy = policy_dir / "committed-policy.json"
        server.write_text("server-private-key\n")
        clients.write_text("[]\n")
        split_extra.write_text("example.com\n")
        client_dir.mkdir()
        (client_dir / "phone.conf").write_text("client-private-key\n")
        policy_dir.mkdir()
        policy.write_text('{"auto_switch": true}\n')
        self.patch("WG_CONF", str(server))
        self.patch("CLIENTS_JSON", str(clients))
        self.patch("SPLIT_EXTRA", str(split_extra))
        self.patch("CLIENT_DIR", str(client_dir))
        self.patch("EXIT_POLICY", str(policy))
        audits = []
        self.patch("audit", lambda op, detail: audits.append((op, detail)))

        def exported_files():
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
                wgadmin.op_export()
            payload = json.loads(output.getvalue())
            with tarfile.open(fileobj=io.BytesIO(base64.b64decode(payload["archive"])), mode="r:gz") as archive:
                return {
                    member.name: archive.extractfile(member).read()
                    for member in archive.getmembers() if member.isfile()
                }

        files = exported_files()
        self.assertEqual(files["committed-policy.json"], b'{"auto_switch": true}\n')
        self.assertNotIn(str(policy), files)

        policy.unlink()
        files = exported_files()
        self.assertNotIn("committed-policy.json", files)
        self.assertEqual(audits, [
            ("export", "backup downloaded"),
            ("export", "backup downloaded"),
        ])


class TestServerPolicy(unittest.TestCase):
    def setUp(self):
        runtime = getattr(wgui, "_policy_runtime", None)
        with wgui._lock:
            self.saved_exit_totals = dict(wgui._exit_totals)
            self.saved_egress = {key: dict(value) for key, value in wgui._egress.items()}
            wgui._exit_totals.update({"nl": (0, 0), "us": (0, 0)})
            if runtime is not None:
                runtime["blocked"] = None
                runtime["last_switch"] = None
        self.addCleanup(self.restore_exit_totals)

    def restore_exit_totals(self):
        with wgui._lock:
            wgui._exit_totals.clear()
            wgui._exit_totals.update(self.saved_exit_totals)
            for key, value in self.saved_egress.items():
                wgui._egress[key].clear()
                wgui._egress[key].update(value)

    def set_counter_availability(self, nl=True, us=True):
        with wgui._lock:
            wgui._exit_totals.update({
                "nl": (0, 0) if nl else None,
                "us": (0, 0) if us else None,
            })

    def patch(self, name, value):
        old = getattr(wgui, name)
        setattr(wgui, name, value)
        self.addCleanup(setattr, wgui, name, old)

    @staticmethod
    def inputs(auto=True, nl_used=0, us_used=0, nl_clients=1, us_clients=0,
               nl_health=None, us_health=None):
        return (
            exit_policy.policy_from_gib(auto, 1, 1),
            {"nl": nl_used, "us": us_used},
            {"nl": nl_clients, "us": us_clients},
            {
                "nl": nl_health or {"ok": True, "checked_age": 1},
                "us": us_health or {"ok": True, "checked_age": 1},
            },
            None,
        )

    def request(self, body, *, csrf=True, user="admin"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()

        class Fake(wgui.H):
            def __init__(self):
                self.path = "/api/admin"
                self.command = "POST"
                self.client_address = ("127.0.0.1", 1)
                token = wgui.csrf_for(user) if csrf and user else "wrong"
                self.headers = {"X-CSRF": token, "Content-Length": str(len(raw))}
                self.rfile = io.BytesIO(raw)
                self._code = None
                self._body_bytes = b""

            def _user(self):
                return user

            def send_response(self, code):
                self._code = code

            def send_header(self, key, value):
                pass

            def end_headers(self):
                pass

        class Writer:
            def __init__(self, handler):
                self.handler = handler

            def write(self, body_bytes):
                self.handler._body_bytes += body_bytes

        handler = Fake()
        handler.wfile = Writer(handler)
        handler.do_POST()
        parsed = json.loads(handler._body_bytes.decode()) if handler._body_bytes else None
        return handler._code, parsed

    def test_status_contains_server_exit_usage_and_assignments(self):
        self.patch("policy_inputs", lambda *args, **kwargs: (
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

    def test_status_uses_existing_tunnel_and_peer_snapshot(self):
        self.patch("load_exit_policy", lambda: (exit_policy.policy_from_gib(True, 1, 1), None))
        self.patch("load_registry", lambda: (_ for _ in ()).throw(AssertionError("registry reread")))
        with wgui._lock:
            wgui._exit_month_usage.clear()
            wgui._exit_month_usage.update({"nl": {"rx": 20, "tx": 22}, "us": {"rx": 1, "tx": 2}})
        tunnel_data = {"exits": {
            "nl": {"ok": True, "checked_age": 60},
            "us": {"ok": False, "checked_age": 1},
        }}
        peers = [
            {"exit": "nl", "enabled": True},
            {"exit": "us", "enabled": False},
        ]
        status = wgui.exit_policy_status(tunnel_data, peers)
        self.assertEqual(status["exits"]["nl"]["used"], 42)
        self.assertEqual(status["exits"]["us"]["clients"], 1)
        self.assertTrue(status["exits"]["nl"]["healthy"])

    def test_assignment_counts_include_disabled_clients(self):
        clients = [
            {"exit": "us", "enabled": True},
            {"exit": "us", "enabled": False},
            {"enabled": False},
        ]
        self.assertEqual(wgui.assignment_counts(clients), {"nl": 1, "us": 2})

    def test_guarded_manual_switch_rejects_unhealthy_target(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(
            us_health={"ok": False, "checked_age": 1}))
        result = wgui.guarded_exit_switch("us", "manual")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "target_unhealthy")
        self.assertEqual(result["http_status"], 409)
        self.assertEqual(calls, [])

    def test_guarded_manual_switch_rejects_stale_and_exhausted_targets(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        cases = (
            (self.inputs(us_health={"ok": True, "checked_age": 61}), "target_stale"),
            (self.inputs(us_used=1024 ** 3), "target_exhausted"),
        )
        for inputs, code in cases:
            with self.subTest(code=code):
                self.patch("policy_inputs", lambda *args, _inputs=inputs, **kwargs: _inputs)
                result = wgui.guarded_exit_switch("us", "manual")
                self.assertEqual(result["code"], code)
                self.assertEqual(result["http_status"], 409)
        self.assertEqual(calls, [])

    def test_guarded_manual_switch_accepts_health_age_exactly_sixty(self):
        calls = []
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(
            us_health={"ok": True, "checked_age": 60}))
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or
                   {"ok": True, "changed": 1, "exit": "us"})
        result = wgui.guarded_exit_switch("us", "manual")
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [["setexitall", "us", "manual"]])

    def test_auto_switch_triggers_at_exact_quota(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or
                   {"ok": True, "changed": 14, "exit": "us"})
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(
            nl_used=1024 ** 3, nl_clients=14))
        result = wgui.evaluate_auto_switch()
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [["setexitall", "us", "quota"]])

    def test_auto_disabled_and_below_quota_do_not_call_helper(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        for inputs in (
            self.inputs(auto=False, nl_used=1024 ** 3),
            self.inputs(nl_used=1024 ** 3 - 1),
        ):
            with self.subTest(inputs=inputs):
                self.patch("policy_inputs", lambda *args, _inputs=inputs, **kwargs: _inputs)
                self.assertEqual(wgui.evaluate_auto_switch(), {"ok": True, "changed": 0})
        self.assertEqual(calls, [])

    def test_auto_does_not_ping_pong_when_alternate_is_exhausted(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(
            nl_used=1024 ** 3, us_used=1024 ** 3, nl_clients=1, us_clients=0))
        result = wgui.evaluate_auto_switch()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "target_exhausted")
        self.assertEqual(calls, [])
        with wgui._lock:
            self.assertEqual(wgui._policy_runtime["blocked"]["code"], "target_exhausted")

    def test_auto_both_exhausted_has_stable_block_shape(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(
            nl_used=1024 ** 3, us_used=1024 ** 3, nl_clients=1, us_clients=1))
        result = wgui.evaluate_auto_switch()
        self.assertEqual(result["code"], "both_exhausted")
        self.assertIn("source", result)
        self.assertIn("target", result)
        self.assertTrue(result["message"])
        self.assertEqual(calls, [])

    def test_auto_reports_health_block_when_either_counter_is_missing(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        cases = (
            (False, True, {"ok": False, "checked_age": 1}, "target_unhealthy"),
            (True, False, {"ok": True, "checked_age": 61}, "target_stale"),
        )
        for nl_ready, us_ready, target_health, expected in cases:
            with self.subTest(missing="nl" if not nl_ready else "us", expected=expected):
                self.set_counter_availability(nl_ready, us_ready)
                inputs = self.inputs(nl_used=1024 ** 3, us_health=target_health)
                self.patch("policy_inputs", lambda *args, _inputs=inputs, **kwargs: _inputs)
                result = wgui.evaluate_auto_switch()
                self.assertEqual(result["code"], expected)
                with wgui._lock:
                    self.assertEqual(wgui._policy_runtime["blocked"]["code"], expected)
        self.assertEqual(calls, [])

    def test_auto_blocks_incomplete_counter_data_before_helper(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(nl_used=1024 ** 3))
        for missing in ("nl", "us"):
            with self.subTest(missing=missing):
                self.set_counter_availability(nl=missing != "nl", us=missing != "us")
                result = wgui.evaluate_auto_switch()
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "counter_unavailable")
                self.assertEqual(result["source"], "nl")
                self.assertEqual(result["target"], "us")
                self.assertEqual(result["missing_exits"], [missing])
        self.assertEqual(calls, [])

    def test_auto_switches_when_missing_counters_recover(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or
                   {"ok": True, "changed": 1, "exit": "us"})
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(nl_used=1024 ** 3))
        self.set_counter_availability(nl=True, us=False)
        self.assertEqual(wgui.evaluate_auto_switch()["code"], "counter_unavailable")
        self.set_counter_availability(nl=True, us=True)
        self.assertTrue(wgui.evaluate_auto_switch()["ok"])
        self.assertEqual(calls, [["setexitall", "us", "quota"]])
        with wgui._lock:
            self.assertIsNone(wgui._policy_runtime["blocked"])

    def test_incomplete_no_action_does_not_create_block(self):
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(nl_used=1024 ** 3 - 1))
        self.set_counter_availability(nl=True, us=False)
        self.assertEqual(wgui.evaluate_auto_switch(), {"ok": True, "changed": 0})
        with wgui._lock:
            self.assertIsNone(wgui._policy_runtime["blocked"])

    def test_incomplete_no_action_preserves_helper_failure_for_assigned_source(self):
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(nl_used=1024 ** 3 - 1))
        self.set_counter_availability(nl=True, us=False)
        with wgui._lock:
            wgui._policy_runtime["blocked"] = {
                "code": "helper_failed", "source": "nl", "target": "us",
                "message": "The exit switch helper failed.",
            }
        self.assertEqual(wgui.evaluate_auto_switch(), {"ok": True, "changed": 0})
        with wgui._lock:
            self.assertEqual(wgui._policy_runtime["blocked"]["code"], "helper_failed")

    def test_incomplete_action_preserves_helper_failure_for_same_route(self):
        calls = []
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(nl_used=1024 ** 3))
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        self.set_counter_availability(nl=True, us=False)
        with wgui._lock:
            wgui._policy_runtime["blocked"] = {
                "code": "helper_failed", "source": "nl", "target": "us",
                "message": "The exit switch helper failed.", "error": "route apply failed",
            }
        result = wgui.evaluate_auto_switch()
        self.assertEqual(result["code"], "helper_failed")
        with wgui._lock:
            self.assertEqual(wgui._policy_runtime["blocked"]["code"], "helper_failed")
        self.assertEqual(calls, [])

    def test_auto_helper_failure_remains_critical_while_condition_persists(self):
        calls = []
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(nl_used=1024 ** 3))
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or
                   {"ok": False, "error": "route apply failed"})
        for _ in range(2):
            result = wgui.evaluate_auto_switch()
            self.assertFalse(result["ok"])
            with wgui._lock:
                blocked = dict(wgui._policy_runtime["blocked"])
            self.assertEqual(blocked["code"], "helper_failed")
            self.assertEqual(blocked["target"], "us")
        self.assertEqual(len(calls), 2)

    def test_auto_helper_failure_clears_after_recovered_evaluation(self):
        current = [self.inputs(nl_used=1024 ** 3)]
        self.patch("policy_inputs", lambda *args, **kwargs: current[0])
        self.patch("call_admin", lambda argv, timeout=30: {"ok": False, "error": "failed"})
        wgui.evaluate_auto_switch()
        current[0] = self.inputs(nl_used=1024 ** 3 - 1)
        self.assertEqual(wgui.evaluate_auto_switch(), {"ok": True, "changed": 0})
        with wgui._lock:
            self.assertIsNone(wgui._policy_runtime["blocked"])

    def test_concurrent_auto_evaluations_call_helper_at_most_once(self):
        assignments = {"nl": 2, "us": 0}
        state_lock = threading.Lock()
        start_barrier = threading.Barrier(2)

        def inputs():
            with state_lock:
                snapshot = dict(assignments)
            base = self.inputs(nl_used=1024 ** 3)
            return base[0], base[1], snapshot, base[3], base[4]

        calls = []

        def helper(argv, timeout=30):
            calls.append(argv)
            with state_lock:
                assignments.update(nl=0, us=2)
            return {"ok": True, "changed": 2, "exit": "us"}

        self.patch("policy_inputs", inputs)
        self.patch("call_admin", helper)
        results = []

        def evaluate():
            start_barrier.wait(timeout=2)
            results.append(wgui.evaluate_auto_switch())

        threads = [threading.Thread(target=evaluate) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(calls, [["setexitall", "us", "quota"]])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result["ok"] for result in results))

    def test_sampler_evaluates_after_usage_refresh_without_holding_cache_lock(self):
        events = []

        class StopSampling(Exception):
            pass

        self.patch("_parse_cl_dump", lambda lines: ({}, {"P": (1, 1)}, {}, 1, 1))
        self.patch("_dump", lambda iface: [iface])
        self.patch("_peer_from_dump", lambda lines: {"age": 1, "up": True, "rx": 10, "tx": 20})
        self.patch("record_usage", lambda per: events.append("client-persist"))
        self.patch("record_exit_usage", lambda totals: events.append("exit-persist"))
        self.patch("usage_month", lambda: {})
        self.patch("exit_usage_month", lambda: events.append("usage-refresh") or
                   {"nl": {"rx": 3, "tx": 4}, "us": {"rx": 5, "tx": 6}})
        self.patch("_read_cpu", lambda: (1, 2))
        self.patch("_probe_egress", lambda: {"nl": (True, "1.1.1.1"), "us": (True, "2.2.2.2")})
        self.patch("refresh_status_cache", lambda: None)
        self.patch("log_connections", lambda eps: None)

        def evaluate():
            acquired = wgui._lock.acquire(blocking=False)
            self.assertTrue(acquired)
            if acquired:
                wgui._lock.release()
            self.assertEqual(wgui._exit_month_usage["nl"], {"rx": 3, "tx": 4})
            events.append("evaluate")

        self.patch("evaluate_auto_switch", evaluate)
        self.patch("time", types.SimpleNamespace(
            time=time.time,
            sleep=lambda seconds: (_ for _ in ()).throw(StopSampling()),
        ))
        with self.assertRaises(StopSampling):
            wgui._sampler()
        self.assertLess(events.index("exit-persist"), events.index("usage-refresh"))
        self.assertLess(events.index("usage-refresh"), events.index("evaluate"))

    def test_sampler_persists_health_block_with_missing_exit_peer(self):
        calls = []

        class StopSampling(Exception):
            pass

        self.patch("_parse_cl_dump", lambda lines: ({}, {"P": (1, 1)}, {}, 1, 1))
        self.patch("_dump", lambda iface: [iface])
        self.patch("_peer_from_dump", lambda lines: None if lines[0] == wgui.US_IFACE else
                   {"age": 1, "up": True, "rx": 10, "tx": 20})
        self.patch("record_usage", lambda per: None)
        self.patch("record_exit_usage", lambda totals: None)
        self.patch("usage_month", lambda: {})
        self.patch("exit_usage_month", lambda: {
            "nl": {"rx": 1024 ** 3, "tx": 0}, "us": {"rx": 0, "tx": 0},
        })
        self.patch("load_exit_policy", lambda: (exit_policy.policy_from_gib(True, 1, 1), None))
        self.patch("load_registry", lambda: [{"exit": "nl", "enabled": False}])
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        self.patch("_read_cpu", lambda: (1, 2))
        self.patch("_probe_egress", lambda: {"nl": (True, "1.1.1.1"), "us": (False, None)})
        self.patch("refresh_status_cache", lambda: None)
        self.patch("log_connections", lambda eps: None)
        self.patch("time", types.SimpleNamespace(
            time=time.time,
            sleep=lambda seconds: (_ for _ in ()).throw(StopSampling()),
        ))
        with wgui._lock:
            wgui._egress["nl"].update(ok=True, seen="1.1.1.1", at=int(time.time()))
            wgui._egress["us"].update(ok=False, seen=None, at=int(time.time()))
        with self.assertRaises(StopSampling):
            wgui._sampler()
        with wgui._lock:
            blocked = dict(wgui._policy_runtime["blocked"] or {})
            self.assertIsNone(wgui._exit_totals["us"])
        self.assertEqual(blocked["code"], "target_unhealthy")
        self.assertEqual(calls, [])

    def test_new_admin_ops_remain_behind_csrf(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        code, body = self.request({"op": "setexitpolicy", "auto_switch": True,
                                   "quotas_gib": {"nl": 1, "us": 1}}, csrf=False)
        self.assertEqual(code, 403)
        self.assertEqual(body["error"], "bad csrf token")
        self.assertEqual(calls, [])

    def test_admin_rejects_non_object_body_and_strict_bulk_target(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        for body in ([], {"op": "setexitall"}, {"op": "setexitall", "exit": ""},
                     {"op": "setexitall", "exit": ["us"]}):
            with self.subTest(body=body):
                code, response = self.request(body)
                self.assertEqual(code, 400)
                self.assertFalse(response["ok"])
        self.assertEqual(calls, [])

    def test_admin_policy_requires_boolean_and_integer_quota_shape(self):
        calls = []
        self.patch("call_admin", lambda argv, timeout=30: calls.append(argv) or {"ok": True})
        invalid = (
            {"op": "setexitpolicy", "auto_switch": 1, "quotas_gib": {"nl": 1, "us": 1}},
            {"op": "setexitpolicy", "auto_switch": True, "quotas_gib": [1, 1]},
            {"op": "setexitpolicy", "auto_switch": True, "quotas_gib": {"nl": "1", "us": 1}},
            {"op": "setexitpolicy", "auto_switch": True, "quotas_gib": {"nl": True, "us": 1}},
            {"op": "setexitpolicy", "auto_switch": True, "quotas_gib": {"nl": 1}},
        )
        for body in invalid:
            with self.subTest(body=body):
                code, response = self.request(body)
                self.assertEqual(code, 400)
                self.assertFalse(response["ok"])
        self.assertEqual(calls, [])

    def test_admin_setexitpolicy_passes_only_validated_helper_args(self):
        calls = []
        refreshes = []
        shared = {"ok": True, "saved": True}
        self.patch("call_admin", lambda argv, timeout=30: calls.append((argv, timeout)) or shared)
        self.patch("policy_inputs", lambda *args, **kwargs: self.inputs(
            auto=True, nl_clients=0, us_clients=0))
        self.patch("refresh_status_cache", lambda: refreshes.append(True))
        code, response = self.request({
            "op": "setexitpolicy", "auto_switch": True,
            "quotas_gib": {"nl": 250, "us": 750}, "ignored": "value",
        })
        self.assertEqual(code, 200)
        self.assertEqual(response, shared)
        self.assertEqual(calls, [(["setexitpolicy", "1", "250", "750"], 30)])
        self.assertEqual(refreshes, [True])

    def test_policy_save_serializes_with_switch_and_switch_uses_committed_policy(self):
        old_policy = exit_policy.policy_from_gib(False, 2, 2)
        new_policy = exit_policy.policy_from_gib(False, 2, 1)
        committed = [old_policy]
        save_entered = threading.Event()
        release_save = threading.Event()
        switch_started = threading.Event()
        switch_done = threading.Event()
        calls = []

        def inputs(*args, **kwargs):
            return (
                committed[0],
                {"nl": 0, "us": 1024 ** 3},
                {"nl": 1, "us": 0},
                {"nl": {"ok": True, "checked_age": 1},
                 "us": {"ok": True, "checked_age": 1}},
                None,
            )

        def helper(argv, timeout=30):
            cache_lock_free = wgui._lock.acquire(blocking=False)
            self.assertTrue(cache_lock_free)
            if cache_lock_free:
                wgui._lock.release()
            calls.append(list(argv))
            if argv[0] == "setexitpolicy":
                save_entered.set()
                self.assertTrue(release_save.wait(timeout=2))
                committed[0] = new_policy
                return {"ok": True, "saved": True}
            return {"ok": True, "changed": 1, "exit": "us"}

        self.patch("policy_inputs", inputs)
        self.patch("call_admin", helper)
        self.patch("refresh_status_cache", lambda: None)
        save_result = []
        switch_result = []
        save_thread = threading.Thread(target=lambda: save_result.append(self.request({
            "op": "setexitpolicy", "auto_switch": False,
            "quotas_gib": {"nl": 2, "us": 1},
        })))

        def switch():
            switch_started.set()
            switch_result.append(wgui.guarded_exit_switch("us", "manual"))
            switch_done.set()

        switch_thread = threading.Thread(target=switch)
        save_thread.start()
        self.assertTrue(save_entered.wait(timeout=2))
        switch_thread.start()
        self.assertTrue(switch_started.wait(timeout=2))
        switch_escaped = switch_done.wait(timeout=0.2)
        release_save.set()
        save_thread.join(timeout=2)
        switch_thread.join(timeout=2)
        self.assertFalse(save_thread.is_alive())
        self.assertFalse(switch_thread.is_alive())
        self.assertFalse(switch_escaped, "switch escaped while policy save was in flight")
        self.assertEqual(save_result[0], (200, {"ok": True, "saved": True}))
        self.assertEqual(switch_result[0]["code"], "target_exhausted")
        self.assertEqual(calls, [["setexitpolicy", "0", "2", "1"]])

    def test_policy_save_serializes_with_auto_runtime_reconciliation(self):
        committed = [exit_policy.policy_from_gib(True, 1, 1)]
        save_entered = threading.Event()
        release_save = threading.Event()
        auto_started = threading.Event()
        auto_done = threading.Event()

        def inputs(*args, **kwargs):
            return (
                committed[0],
                {"nl": 1024 ** 3, "us": 1024 ** 3},
                {"nl": 1, "us": 1},
                {"nl": {"ok": True, "checked_age": 1},
                 "us": {"ok": True, "checked_age": 1}},
                None,
            )

        def helper(argv, timeout=30):
            save_entered.set()
            self.assertTrue(release_save.wait(timeout=2))
            committed[0] = exit_policy.policy_from_gib(False, 2, 2)
            return {"ok": True, "saved": True}

        self.patch("policy_inputs", inputs)
        self.patch("call_admin", helper)
        self.patch("refresh_status_cache", lambda: None)
        save_thread = threading.Thread(target=lambda: self.request({
            "op": "setexitpolicy", "auto_switch": False,
            "quotas_gib": {"nl": 2, "us": 2},
        }))

        def evaluate():
            auto_started.set()
            wgui.evaluate_auto_switch()
            auto_done.set()

        auto_thread = threading.Thread(target=evaluate)
        save_thread.start()
        self.assertTrue(save_entered.wait(timeout=2))
        auto_thread.start()
        self.assertTrue(auto_started.wait(timeout=2))
        auto_escaped = auto_done.wait(timeout=0.2)
        release_save.set()
        save_thread.join(timeout=2)
        auto_thread.join(timeout=2)
        self.assertFalse(save_thread.is_alive())
        self.assertFalse(auto_thread.is_alive())
        self.assertFalse(auto_escaped, "auto evaluation escaped while policy save was in flight")
        with wgui._lock:
            self.assertIsNone(wgui._policy_runtime["blocked"])

    def test_saved_disabled_or_recovered_policy_clears_stale_block_and_refreshes_status(self):
        committed = [exit_policy.policy_from_gib(True, 1, 1)]

        def inputs(*args, **kwargs):
            return (
                committed[0],
                {"nl": 1024 ** 3, "us": 0},
                {"nl": 1, "us": 0},
                {"nl": {"ok": True, "checked_age": 1},
                 "us": {"ok": True, "checked_age": 1}},
                None,
            )

        for auto_switch, expected_auto in ((False, False), (True, True)):
            with self.subTest(auto_switch=auto_switch):
                committed[0] = exit_policy.policy_from_gib(True, 1, 1)
                with wgui._lock:
                    wgui._policy_runtime["blocked"] = wgui._with_block_message({
                        "code": "target_exhausted", "source": "nl", "target": "us",
                    })
                refreshed = []

                def helper(argv, timeout=30):
                    committed[0] = exit_policy.policy_from_gib(auto_switch, 2, 2)
                    return {"ok": True, "saved": True}

                self.patch("policy_inputs", inputs)
                self.patch("call_admin", helper)
                self.patch("refresh_status_cache", lambda: refreshed.append(wgui.exit_policy_status()))
                code, response = self.request({
                    "op": "setexitpolicy", "auto_switch": auto_switch,
                    "quotas_gib": {"nl": 2, "us": 2},
                })
                self.assertEqual((code, response), (200, {"ok": True, "saved": True}))
                with wgui._lock:
                    self.assertIsNone(wgui._policy_runtime["blocked"])
                self.assertEqual(refreshed[-1]["auto_switch"], expected_auto)
                self.assertIsNone(refreshed[-1]["blocked"])

    def test_saved_auto_policy_reports_immediate_switch_failure_without_failing_save(self):
        committed = [exit_policy.policy_from_gib(False, 2, 2)]
        calls = []
        refreshed = []

        def inputs(*args, **kwargs):
            return (
                committed[0],
                {"nl": 1024 ** 3, "us": 0},
                {"nl": 1, "us": 0},
                {"nl": {"ok": True, "checked_age": 1},
                 "us": {"ok": True, "checked_age": 1}},
                None,
            )

        def helper(argv, timeout=30):
            cache_lock_free = wgui._lock.acquire(blocking=False)
            self.assertTrue(cache_lock_free)
            if cache_lock_free:
                wgui._lock.release()
            calls.append(list(argv))
            if argv[0] == "setexitpolicy":
                committed[0] = exit_policy.policy_from_gib(True, 1, 1)
                return {"ok": True, "saved": True}
            return {"ok": False, "error": "route apply failed"}

        self.patch("policy_inputs", inputs)
        self.patch("call_admin", helper)
        self.patch("refresh_status_cache", lambda: refreshed.append(wgui.exit_policy_status()))
        code, response = self.request({
            "op": "setexitpolicy", "auto_switch": True,
            "quotas_gib": {"nl": 1, "us": 1},
        })
        self.assertEqual((code, response), (200, {"ok": True, "saved": True}))
        self.assertEqual(calls, [
            ["setexitpolicy", "1", "1", "1"],
            ["setexitall", "us", "quota"],
        ])
        with wgui._lock:
            self.assertEqual(wgui._policy_runtime["blocked"]["code"], "helper_failed")
        self.assertEqual(refreshed[-1]["blocked"]["code"], "helper_failed")

    def test_admin_bulk_uses_409_without_mutating_guard_result(self):
        shared = {"ok": False, "code": "target_stale", "error": "target_stale", "http_status": 409}
        self.patch("guarded_exit_switch", lambda target, reason: shared)
        code, response = self.request({"op": "setexitall", "exit": "us"})
        self.assertEqual(code, 409)
        self.assertNotIn("http_status", response)
        self.assertEqual(shared["http_status"], 409)


if __name__ == "__main__":
    unittest.main()
