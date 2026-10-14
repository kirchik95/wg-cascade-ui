import importlib.util
import io
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
os.environ.setdefault("WGUI_SESSION_SECRET", "history-api-test-secret-0123456789abcd")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-history-api.gen"))

spec = importlib.util.spec_from_file_location("wgui_history_api", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)

REGISTRY = [{"pubkey": "A", "name": "phone", "ip": "10.10.0.2"},
            {"pubkey": "B", "name": "laptop", "ip": "10.10.0.3", "exit": "us"}]
JULY = time.mktime((2026, 7, 13, 12, 0, 0, 0, 0, -1))


def get(path, user="admin"):
    class Fake(wgui.H):
        def __init__(self):
            self.path = path
            self.command = "GET"
            self.client_address = ("127.0.0.1", 1)
            self.headers = {}
            self._code = None
            self._out = b""

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

        def write(self, data):
            self.handler._out += data

    h = Fake()
    h.wfile = Writer(h)
    h.do_GET()
    return h._code, (json.loads(h._out.decode()) if h._out else None)


class TestHistoryApi(unittest.TestCase):
    def setUp(self):
        self.old_db = wgui.DB
        self.tmp = tempfile.TemporaryDirectory()
        wgui.DB = os.path.join(self.tmp.name, "history.db")
        wgui.db_init()
        c = wgui._conn()
        rows = [("A", "2026-06-30", 1, 1), ("A", "2026-07-01", 10, 1), ("B", "2026-07-02", 40, 4),
                ("A", "2026-07-31", 5, 5), ("B", "2026-08-01", 900, 900)]
        c.executemany("INSERT INTO usage(pubkey,day,rx,tx) VALUES(?,?,?,?)", rows)
        exits = [("nl", "2026-06-30", 7, 7), ("nl", "2026-07-01", 10, 1), ("us", "2026-07-02", 40, 4),
                 ("nl", "2026-07-31", 5, 5), ("us", "2026-08-01", 900, 900)]
        c.executemany("INSERT INTO exit_usage(exit,day,rx,tx) VALUES(?,?,?,?)", exits)
        c.commit()
        c.close()
        self.reg = mock.patch.object(wgui, "load_registry", lambda: REGISTRY)
        self.reg.start()

    def tearDown(self):
        self.reg.stop()
        wgui.DB = self.old_db
        self.tmp.cleanup()

    def test_payload_for_explicit_month_is_calendar_bounded(self):
        body = wgui.history_payload(month="2026-07")
        self.assertEqual(body["month"], "2026-07")
        self.assertEqual([d["day"] for d in body["daily"]], ["2026-07-01", "2026-07-02", "2026-07-31"])
        self.assertEqual(body["exits_month"], {"nl": {"rx": 15, "tx": 6}, "us": {"rx": 40, "tx": 4}})
        self.assertEqual([d["day"] for d in body["exits_daily"]["nl"]], ["2026-07-01", "2026-07-31"])
        self.assertEqual(body["exits_daily"]["us"], [{"day": "2026-07-02", "rx": 40, "tx": 4}])
        self.assertEqual(body["clients"][0], {"name": "laptop", "rx": 40, "tx": 4})
        self.assertEqual(body["clients"][1], {"name": "phone", "rx": 15, "tx": 6})

    def test_payload_without_month_uses_current_month_for_exits(self):
        body = wgui.history_payload(now=JULY)
        self.assertEqual(body["month"], "2026-07")
        self.assertEqual(body["exits_month"]["nl"], {"rx": 15, "tx": 6})
        self.assertEqual(len(body["exits_daily"]["us"]), 1)
        # the rolling client window (current UI chart) is unchanged: last 30 days with data
        self.assertIn("2026-08-01", [d["day"] for d in body["daily"]])

    def test_empty_month_is_empty_not_error(self):
        body = wgui.history_payload(month="2025-01")
        self.assertEqual(body["daily"], [])
        self.assertEqual(body["exits_daily"], {"nl": [], "us": []})
        self.assertEqual(body["exits_month"], {"nl": {"rx": 0, "tx": 0}, "us": {"rx": 0, "tx": 0}})

    def test_route_accepts_month_param(self):
        code, body = get("/api/history?month=2026-07")
        self.assertEqual(code, 200)
        self.assertEqual(body["exits_month"]["us"], {"rx": 40, "tx": 4})

    def test_route_rejects_bad_month(self):
        for bad in ("2026-13", "26-07", "2026-7", "2026-07-01", "x' OR 1=1"):
            code, body = get("/api/history?month=" + bad)
            self.assertEqual(code, 400, bad)
            self.assertIn("month", body["error"])

    def test_route_reports_db_failure_as_503(self):
        with mock.patch.object(wgui, "history_payload", side_effect=sqlite3.OperationalError("locked")):
            code, body = get("/api/history")
        self.assertEqual(code, 503)
        self.assertEqual(body["error"], "history unavailable")

    def test_per_client_series_still_served(self):
        code, body = get("/api/history?pub=A")
        self.assertEqual(code, 200)
        self.assertEqual(len(body["daily"]), 3)


if __name__ == "__main__":
    unittest.main()
