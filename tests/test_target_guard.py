import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
os.environ.setdefault("WGUI_SESSION_SECRET", "target-guard-test-secret-0123456789abcd")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-target-guard.gen"))

import exit_policy  # noqa: E402

spec = importlib.util.spec_from_file_location("wgui_target_guard", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)

NOW = 1_790_000_000
GIB = 1 << 30


class TestTargetGuard(unittest.TestCase):
    def setUp(self):
        self.saved = {k: json.loads(json.dumps(getattr(wgui, k)))
                      for k in ("_egress", "_health", "_exit_month_usage")}
        self.patches = [
            mock.patch.object(wgui, "load_exit_policy",
                              lambda: (exit_policy.policy_from_gib(True, 1000, 500), None)),
            mock.patch.object(wgui.time, "time", lambda: NOW),
        ]
        for p in self.patches:
            p.start()
        self.calls = []

    def tearDown(self):
        for p in self.patches:
            p.stop()
        with wgui._lock:
            for k, v in self.saved.items():
                getattr(wgui, k).clear()
                getattr(wgui, k).update(v)

    def set_exit(self, key, *, ok=True, age=5, state="up", used_gib=0):
        with wgui._lock:
            wgui._egress[key] = {"ok": ok, "seen": None, "at": NOW - age if age >= 0 else 0}
            wgui._health[key] = {"state": state, "fails": 0, "oks": 0, "since": 0, "at": NOW}
            wgui._exit_month_usage[key] = {"rx": used_gib * GIB, "tx": 0}

    def request(self, body):
        raw = json.dumps(body).encode()

        class Fake(wgui.H):
            def __init__(self):
                self.path = "/api/admin"
                self.command = "POST"
                self.client_address = ("127.0.0.1", 1)
                self.headers = {"X-CSRF": wgui.csrf_for("admin"), "Content-Length": str(len(raw))}
                self.rfile = io.BytesIO(raw)
                self._code = None
                self._out = b""

            def _user(self):
                return "admin"

            def send_response(self, code):
                self._code = code

            def send_header(self, key, value):
                pass

            def end_headers(self):
                pass

        class Writer:
            def __init__(self, handler):
                self.handler = handler

            def write(self, data):
                self.handler._out += data

        def fake_admin(argv, timeout=None):
            self.calls.append(argv)
            return {"ok": True, "name": "phone"}

        h = Fake()
        h.wfile = Writer(h)
        with mock.patch.object(wgui, "call_admin", fake_admin):
            h.do_POST()
        return h._code, json.loads(h._out.decode())

    # --- assign_target_check -------------------------------------------------
    def test_healthy_target_passes_without_warning(self):
        self.set_exit("us")
        self.assertEqual(wgui.assign_target_check("us"), (None, None))

    def test_confirmed_down_target_is_blocked(self):
        self.set_exit("us", ok=False, state="down")
        block, warn = wgui.assign_target_check("us")
        self.assertEqual(block["code"], "target_unhealthy")
        self.assertIsNone(warn)

    def test_exhausted_target_is_blocked_even_when_healthy(self):
        self.set_exit("us", used_gib=501)
        self.assertEqual(wgui.assign_target_check("us")[0]["code"], "target_exhausted")

    def test_single_failed_probe_only_warns(self):
        self.set_exit("us", ok=False, state="up")
        self.assertEqual(wgui.assign_target_check("us"), (None, "target_unverified"))

    def test_unknown_health_after_restart_only_warns(self):
        self.set_exit("nl", ok=False, age=-1, state="unknown")
        self.assertEqual(wgui.assign_target_check("nl"), (None, "target_stale"))

    def test_old_probe_only_warns(self):
        self.set_exit("nl", ok=True, age=exit_policy.HEALTH_MAX_AGE + 30)
        self.assertEqual(wgui.assign_target_check("nl"), (None, "target_stale"))

    # --- /api/admin ---------------------------------------------------------
    def test_add_to_down_exit_is_409_and_helper_not_called(self):
        self.set_exit("us", ok=False, state="down")
        code, body = self.request({"op": "add", "name": "phone", "exit": "us"})
        self.assertEqual(code, 409)
        self.assertEqual((body["ok"], body["code"], body["target"]), (False, "target_unhealthy", "us"))
        self.assertEqual(self.calls, [])

    def test_setexit_to_exhausted_exit_is_409(self):
        self.set_exit("us", used_gib=600)
        code, body = self.request({"op": "setexit", "pubkey": "A" * 43 + "=", "exit": "us"})
        self.assertEqual(code, 409)
        self.assertEqual(body["code"], "target_exhausted")
        self.assertEqual(self.calls, [])

    def test_add_with_stale_health_succeeds_with_warning(self):
        self.set_exit("nl", ok=False, age=-1, state="unknown")
        code, body = self.request({"op": "add", "name": "phone", "exit": "nl"})
        self.assertEqual(code, 200)
        self.assertEqual(body["warning"], "target_stale")
        self.assertEqual(self.calls[0][0], "add")

    def test_healthy_setexit_has_no_warning(self):
        self.set_exit("us")
        code, body = self.request({"op": "setexit", "pubkey": "A" * 43 + "=", "exit": "us"})
        self.assertEqual(code, 200)
        self.assertNotIn("warning", body)

    def test_other_ops_are_not_guarded(self):
        self.set_exit("us", ok=False, state="down")
        self.set_exit("nl", ok=False, state="down")
        code, body = self.request({"op": "rename", "pubkey": "A" * 43 + "=", "name": "phone2"})
        self.assertEqual(code, 200)
        self.assertNotIn("warning", body)


class TestTargetTexts(unittest.TestCase):
    def test_every_code_is_translated(self):
        src = (APP / "core.js").read_text()
        block = src[src.index("const TARGET_TEXT"):src.index("function targetText")]
        for code in ("target_unhealthy", "target_exhausted", "target_stale", "target_unverified"):
            self.assertEqual(block.count(code + ":"), 2, code)


if __name__ == "__main__":
    unittest.main()
