"""wg-admin time budgets: bounded lock wait, per-stage subprocess caps, rollback
reserve, committed/cleanup_warning reporting, batched conntrack cleanup."""
import contextlib
import fcntl
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import time
import types
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
spec = importlib.util.spec_from_file_location("wgadmin_budget", str(APP / "wg-admin.py"))
wgadmin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgadmin)

PUB = "A" * 42 + "c="
HEAD = "[Interface]\nPrivateKey = x\nListenPort = 51820\n"


class BudgetCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(wgadmin.reset_budget)
        d = self.tmp.name
        for name, value in (("CLIENTS_JSON", "clients.json"), ("WG_CONF", "wg-cl.conf"),
                            ("NAMES_JSON", "names.json"), ("CLIENT_DIR", "clients"),
                            ("LOCKFILE", "lock")):
            self.patch(name, os.path.join(d, value))
        os.mkdir(wgadmin.CLIENT_DIR)
        self.clients = [{"name": "phone", "ip": "10.10.0.2", "pubkey": PUB, "enabled": True}]
        pathlib.Path(wgadmin.CLIENTS_JSON).write_text(json.dumps(self.clients, indent=1))
        pathlib.Path(wgadmin.WG_CONF).write_text(HEAD + "\n" + wgadmin.peer_block(self.clients[0]))
        pathlib.Path(wgadmin.NAMES_JSON).write_text(json.dumps({PUB: "phone"}))
        self.patch("read_head", lambda: HEAD.rstrip("\n"))
        self.patch("audit", lambda *a, **k: None)
        self.snapshot = {p: pathlib.Path(p).read_bytes()
                         for p in (wgadmin.CLIENTS_JSON, wgadmin.WG_CONF, wgadmin.NAMES_JSON)}

    def patch(self, name, value):
        old = getattr(wgadmin, name)
        setattr(wgadmin, name, value)
        self.addCleanup(setattr, wgadmin, name, old)

    def call(self, fn, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            fn(*args)
        return json.loads(out.getvalue().strip().splitlines()[-1])

    def assert_unchanged(self):
        for path, data in self.snapshot.items():
            self.assertEqual(pathlib.Path(path).read_bytes(), data, path)


class TestStageTimeouts(BudgetCase):
    def test_run_caps_subprocess_timeout_by_remaining_budget(self):
        seen = []
        self.patch("subprocess", types.SimpleNamespace(
            run=lambda *a, **k: seen.append(k["timeout"]) or types.SimpleNamespace(returncode=0),
            TimeoutExpired=Exception))
        wgadmin.start_budget("list")
        wgadmin._deadline = time.monotonic() + 7
        wgadmin.run(["true"], timeout=15)
        self.assertLessEqual(seen[-1], 7)
        with wgadmin.reserved(5):
            wgadmin.run(["true"], timeout=15)
        self.assertLessEqual(seen[-1], 2)
        with wgadmin.reserved(6.5), self.assertRaises(wgadmin.BudgetExceeded):
            wgadmin.run(["true"], timeout=15)

    def test_unbounded_without_an_operation(self):
        self.assertEqual(wgadmin.stage_timeout(15), 15)

    def test_budget_table_covers_mutating_ops_and_has_rollback_room(self):
        for op in ("setexitall", "rename", "setenabled", "delete", "setexit", "expire", "add",
                   "splitsave", "splitserver"):
            self.assertGreater(wgadmin.OP_BUDGETS[op], wgadmin.ROLLBACK_RESERVE + wgadmin.LOCK_WAIT)


class TestRollbackReserve(BudgetCase):
    def test_exhausted_apply_budget_rolls_back_inside_helper(self):
        kernel = []

        def kernel_sync():
            wgadmin.stage_timeout(15)          # what wgadmin.run does before spawning
            kernel.append(pathlib.Path(wgadmin.WG_CONF).read_text())
        self.patch("sync_kernel", kernel_sync)
        self.patch("run_exit_sync_or_raise", lambda: wgadmin.stage_timeout(30))
        wgadmin.start_budget("setenabled")
        # Less than the rollback reserve left: apply may not start a subprocess,
        # yet the rollback (reserve released) still has time to run.
        wgadmin._deadline = time.monotonic() + wgadmin.ROLLBACK_RESERVE + 0.5
        res = self.call(wgadmin.op_setenabled, PUB, "0")
        self.assertFalse(res["ok"])
        self.assertIs(res["committed"], False)
        self.assertIn("budget exhausted", res["error"])
        self.assertIn("rolled back", res["error"])
        self.assert_unchanged()
        self.assertIn(PUB, kernel[-1])          # rollback re-synced the restored peer

    def test_failed_rollback_reports_unknown(self):
        def boom():
            raise RuntimeError("exit-route sync failed: down")
        self.patch("sync_kernel", lambda: None)
        self.patch("run_exit_sync_or_raise", boom)
        wgadmin.start_budget("setenabled")
        res = self.call(wgadmin.op_setenabled, PUB, "0")
        self.assertEqual(res["committed"], "unknown")

    def test_success_reports_committed(self):
        self.patch("sync_kernel", lambda: None)
        self.patch("run_exit_sync_or_raise", lambda: None)
        self.patch("flush_exit_conntrack", lambda ips: None)
        wgadmin.start_budget("setenabled")
        res = self.call(wgadmin.op_setenabled, PUB, "0")
        self.assertTrue(res["ok"])
        self.assertIs(res["committed"], True)
        self.assertNotIn("cleanup_warning", res)

    def test_cleanup_shortfall_is_a_warning_not_a_failure(self):
        self.patch("sync_kernel", lambda: None)
        self.patch("run_exit_sync_or_raise", lambda: None)
        self.patch("flush_exit_conntrack", lambda ips: "conntrack cleanup incomplete: skipped 10.10.0.2")
        wgadmin.start_budget("delete")
        res = self.call(wgadmin.op_delete, PUB)
        self.assertTrue(res["ok"])
        self.assertIs(res["committed"], True)
        self.assertIn("skipped", res["cleanup_warning"])

    def test_bulk_rollback_failure_reports_unknown(self):
        calls = []

        def sync():
            calls.append("sync")
            raise RuntimeError("exit-route sync failed: boom")
        self.patch("run_exit_sync_or_raise", sync)
        wgadmin.start_budget("setexitall")
        res = self.call(wgadmin.op_setexitall, "us", "manual")
        self.assertEqual(res["committed"], "unknown")
        self.assertEqual(calls, ["sync", "sync"])

    def test_bulk_apply_failure_rolls_back(self):
        state = {"n": 0}

        def sync():
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("exit-route sync failed: boom")
        self.patch("run_exit_sync_or_raise", sync)
        wgadmin.start_budget("setexitall")
        res = self.call(wgadmin.op_setexitall, "us", "manual")
        self.assertIs(res["committed"], False)
        self.assertIn("rolled back", res["error"])
        self.assert_unchanged()


class TestRenameSkipsRoutes(BudgetCase):
    def test_rename_does_not_resync_exit_routes(self):
        routes = []
        self.patch("sync_kernel", lambda: None)
        self.patch("run_exit_sync_or_raise", lambda: routes.append("sync"))
        res = self.call(wgadmin.op_rename, PUB, "tablet")
        self.assertTrue(res["ok"])
        self.assertEqual(routes, [])
        self.assertEqual(json.loads(pathlib.Path(wgadmin.CLIENTS_JSON).read_text())[0]["name"], "tablet")


class TestLock(BudgetCase):
    def test_busy_lock_answers_quickly(self):
        holder = open(wgadmin.LOCKFILE, "w")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        wgadmin.start_budget("setexitall")
        started = time.monotonic()
        res = self.call(wgadmin.acquire_lock, wgadmin.LOCKFILE, 0.3)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(res["error"], "busy")
        self.assertTrue(res["busy"])
        self.assertIs(res["committed"], False)

    def test_free_lock_is_acquired(self):
        lock = wgadmin.acquire_lock(wgadmin.LOCKFILE, 0.3)
        self.addCleanup(lock.close)
        other = open(wgadmin.LOCKFILE, "w")
        self.addCleanup(other.close)
        with self.assertRaises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


class TestBatchCleanup(BudgetCase):
    def run_with(self, returncode=0, stderr=""):
        seen = []
        self.patch("run", lambda cmd, inp=None, timeout=15: seen.append((cmd, timeout)) or
                   types.SimpleNamespace(returncode=returncode, stdout="", stderr=stderr))
        return seen

    def test_one_call_for_all_addresses_with_inner_deadline(self):
        seen = self.run_with()
        self.assertIsNone(wgadmin.flush_exit_conntrack(["10.10.0.2", "10.10.0.3", None]))
        (cmd, timeout), = seen
        self.assertEqual(cmd[1:4], ["flush-ct", "--deadline", str(int(wgadmin.CLEANUP_BUDGET) - 1)])
        self.assertEqual(cmd[4:], ["10.10.0.2", "10.10.0.3"])
        self.assertEqual(timeout, wgadmin.CLEANUP_BUDGET)

    def test_partial_flush_becomes_warning(self):
        self.run_with(returncode=2, stderr="exit-route: conntrack deadline hit, skipped: 10.10.0.3")
        warning = wgadmin.flush_exit_conntrack(["10.10.0.2", "10.10.0.3"])
        self.assertIn("skipped: 10.10.0.3", warning)

    def test_no_addresses_no_call(self):
        seen = self.run_with()
        self.assertIsNone(wgadmin.flush_exit_conntrack([]))
        self.assertEqual(seen, [])

    def test_exhausted_budget_skips_cleanup_without_raising(self):
        seen = self.run_with()
        wgadmin.start_budget("setexitall")
        wgadmin._deadline = time.monotonic() + 0.2
        self.assertIn("skipped", wgadmin.flush_exit_conntrack(["10.10.0.2"]))
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
