"""wg-ui.py → wg-admin.py calls: per-op timeouts above the helper budget, honest
timeout/diagnostic results."""
import importlib.util
import os
import pathlib
import sys
import tempfile
import types
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
os.environ.setdefault("WGUI_SESSION_SECRET", "helper-calls-test-secret-0123456789")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-helper-calls.gen"))
spec = importlib.util.spec_from_file_location("wgui_helper_calls", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)
admin_spec = importlib.util.spec_from_file_location("wgadmin_helper_calls", str(APP / "wg-admin.py"))
wgadmin = importlib.util.module_from_spec(admin_spec)
admin_spec.loader.exec_module(wgadmin)


class Timeout(Exception):
    pass


class TestCallAdmin(unittest.TestCase):
    def fake(self, result=None, exc=None):
        seen = []

        def run(cmd, **kw):
            seen.append(kw["timeout"])
            if exc:
                raise exc
            return result
        old = wgui.subprocess
        wgui.subprocess = types.SimpleNamespace(run=run, TimeoutExpired=Timeout)
        self.addCleanup(setattr, wgui, "subprocess", old)
        return seen

    def test_web_timeout_exceeds_helper_budget_for_every_op(self):
        for op, budget in wgadmin.OP_BUDGETS.items():
            with self.subTest(op=op):
                self.assertGreaterEqual(wgui.ADMIN_TIMEOUTS.get(op, wgui.ADMIN_TIMEOUT_DEFAULT), budget + 10)
        self.assertGreaterEqual(wgui.ADMIN_TIMEOUT_DEFAULT, wgadmin.DEFAULT_BUDGET + 10)

    def test_timeout_is_chosen_per_operation(self):
        ok = types.SimpleNamespace(returncode=0, stdout='{"ok": true}\n', stderr="")
        seen = self.fake(ok)
        wgui.call_admin(["setexitall", "nl", "manual"])
        wgui.call_admin(["splitsave", "0"])
        wgui.call_admin(["list"])
        wgui.call_admin(["list"], timeout=5)
        self.assertEqual(seen, [90, 180, wgui.ADMIN_TIMEOUT_DEFAULT, 5])

    def test_timeout_reports_unknown_commit_state(self):
        self.fake(exc=Timeout())
        res = wgui.call_admin(["setexitall", "nl", "manual"])
        self.assertEqual(res["error"], "timeout")
        self.assertEqual(res["committed"], "unknown")
        self.assertFalse(res["ok"])

    def test_silent_helper_failure_carries_returncode_and_stderr(self):
        self.fake(types.SimpleNamespace(returncode=1, stdout="", stderr="sudo: a password is required\n"))
        res = wgui.call_admin(["list"])
        self.assertIn("rc=1", res["error"])
        self.assertIn("password is required", res["error"])

    def test_structured_helper_answer_passes_through(self):
        self.fake(types.SimpleNamespace(returncode=1, stdout='{"ok": false, "error": "busy", "busy": true}\n', stderr=""))
        self.assertEqual(wgui.call_admin(["setexitall", "nl", "manual"]),
                         {"ok": False, "error": "busy", "busy": True})


if __name__ == "__main__":
    unittest.main()
