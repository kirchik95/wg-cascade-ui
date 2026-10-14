import importlib.util
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
os.environ.setdefault("WGUI_SESSION_SECRET", "health-history-test-secret-0123456789ab")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-health-history.gen"))

spec = importlib.util.spec_from_file_location("wgui_health_history", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)

HOUR = 1_790_000_000 - 1_790_000_000 % 3600   # an hour boundary


def get(path):
    class Fake(wgui.H):
        def __init__(self):
            self.path = path
            self.command = "GET"
            self.client_address = ("127.0.0.1", 1)
            self.headers = {}
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

    h = Fake()
    h.wfile = Writer(h)
    h.do_GET()
    return h._code, json.loads(h._out.decode())


class TestHealthHistory(unittest.TestCase):
    def setUp(self):
        self.old_db = wgui.DB
        self.tmp = tempfile.TemporaryDirectory()
        wgui.DB = os.path.join(self.tmp.name, "history.db")
        wgui.db_init()

    def tearDown(self):
        wgui.DB = self.old_db
        self.tmp.cleanup()

    def test_probes_fold_into_hourly_buckets(self):
        wgui.record_probe_history({"nl": (True, None), "us": (False, None)}, HOUR + 10)
        wgui.record_probe_history({"nl": (True, None), "us": (True, None)}, HOUR + 3599)
        wgui.record_probe_history({"nl": (False, None), "us": (True, None)}, HOUR + 3600)
        hist = wgui.health_history(24, now=HOUR + 3700)
        self.assertEqual(len(hist["nl"]), 24)
        self.assertEqual(hist["nl"][-1], {"ts": HOUR + 3600, "ok": 0, "fail": 1})
        self.assertEqual(hist["nl"][-2], {"ts": HOUR, "ok": 2, "fail": 0})
        self.assertEqual(hist["us"][-2], {"ts": HOUR, "ok": 1, "fail": 1})

    def test_gaps_are_empty_not_healthy(self):
        hist = wgui.health_history(24, now=HOUR)
        self.assertTrue(all(b["ok"] == 0 and b["fail"] == 0 for b in hist["nl"]))
        self.assertEqual(hist["nl"][0]["ts"], HOUR - 23 * 3600)
        self.assertEqual(hist["nl"][-1]["ts"], HOUR)

    def test_rows_outside_window_are_ignored(self):
        wgui.record_probe_history({"nl": (False, None), "us": (False, None)}, HOUR - 30 * 3600)
        hist = wgui.health_history(24, now=HOUR)
        self.assertEqual(sum(b["fail"] for b in hist["nl"]), 0)

    def test_maintenance_keeps_seven_days(self):
        wgui.record_probe_history({"nl": (True, None), "us": (True, None)}, HOUR - 8 * 86400)
        wgui.record_probe_history({"nl": (True, None), "us": (True, None)}, HOUR - 6 * 86400)
        wgui.db_maintenance(now=HOUR)
        c = wgui._conn()
        left = [r[0] for r in c.execute("SELECT hour_ts FROM health_hourly WHERE exit='nl'")]
        c.close()
        self.assertEqual(left, [HOUR - 6 * 86400])

    def test_health_tick_persists_probe_and_survives_db_errors(self):
        res = {"nl": (True, "192.0.2.10"), "us": (False, None)}
        with mock.patch.object(wgui, "_probe_egress", return_value=res), \
             mock.patch.object(wgui, "evaluate_health_failover", return_value=None):
            wgui.health_tick()
            with mock.patch.object(wgui, "record_probe_history",
                                   side_effect=sqlite3.OperationalError("locked")):
                wgui.health_tick()          # must not raise
        hist = wgui.health_history(1)
        self.assertEqual(hist["nl"][0]["ok"], 1)
        self.assertEqual(hist["us"][0]["fail"], 1)

    def test_exit_status_exposes_debounce_counters(self):
        with wgui._lock:
            saved = dict(wgui._health["us"])
            wgui._health["us"] = {"state": "up", "fails": 2, "oks": 0, "since": 1, "at": 1}
        try:
            st = wgui._exit_status("us", "wg-us", None, None)
        finally:
            with wgui._lock:
                wgui._health["us"] = saved
        self.assertEqual((st["fails"], st["oks"]), (2, 0))

    def test_route(self):
        wgui.record_probe_history({"nl": (True, None), "us": (True, None)}, wgui.time.time())
        code, body = get("/api/health-history")
        self.assertEqual(code, 200)
        self.assertEqual(body["probe_s"], wgui.PROBE_S)
        self.assertEqual(len(body["exits"]["us"]), 24)
        self.assertEqual(body["exits"]["nl"][-1]["ok"], 1)

    def test_route_db_failure_is_503(self):
        with mock.patch.object(wgui, "health_history", side_effect=sqlite3.OperationalError("x")):
            code, body = get("/api/health-history")
        self.assertEqual(code, 503)


if __name__ == "__main__":
    unittest.main()
