"""Event journal: storage, paging, retention, privacy and the HTTP surfaces."""
import hashlib
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
from urllib.parse import urlencode

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

os.environ.setdefault("WGUI_SESSION_SECRET", "events-test-secret-0123456789abcdef")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-events.gen"))
spec = importlib.util.spec_from_file_location("wgui_events", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)
import exit_policy


class Writer:
    def __init__(self, handler):
        self.handler = handler

    def write(self, data):
        self.handler._body_bytes += data


def fake_handler(method, path, *, body=b"", user="admin", csrf=True, ip="192.0.2.50", headers=None):
    class Fake(wgui.H):
        def __init__(self):
            self.path = path
            self.command = method
            self.client_address = (ip, 1)
            hdrs = {"Content-Length": str(len(body))}
            if user and csrf:
                hdrs["X-CSRF"] = wgui.csrf_for(user)
            hdrs.update(headers or {})
            self.headers = hdrs
            self.rfile = io.BytesIO(body)
            self._code = None
            self._out = {}
            self._body_bytes = b""

        def _user(self):
            return user

        def send_response(self, code):
            self._code = code

        def send_header(self, key, value):
            self._out[key] = value

        def end_headers(self):
            pass

    h = Fake()
    h.wfile = Writer(h)
    return h


class DbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_db = wgui.DB
        wgui.DB = os.path.join(self.tmp.name, "history.db")
        self.addCleanup(setattr, wgui, "DB", self.old_db)
        wgui.db_init()

    def patch(self, name, value):
        old = getattr(wgui, name)
        setattr(wgui, name, value)
        self.addCleanup(setattr, wgui, name, old)

    def all_events(self):
        return list(reversed(wgui.events_page(limit=200)))

    def get(self, query):
        h = fake_handler("GET", "/api/events" + ("?" + query if query else ""))
        h.do_GET()
        return h._code, json.loads(h._body_bytes.decode())


class TestJournalStorage(DbCase):
    def test_record_and_page_newest_first(self):
        ids = [wgui.record_event("admin", subject="op%d" % i, actor="admin", ip="192.0.2.1",
                                 data={"n": i}) for i in range(5)]
        self.assertEqual(ids, sorted(ids))
        page = wgui.events_page(limit=2)
        self.assertEqual([e["subject"] for e in page], ["op4", "op3"])
        older = wgui.events_page(before=page[-1]["id"], limit=2)
        self.assertEqual([e["subject"] for e in older], ["op2", "op1"])
        self.assertEqual(older[0]["data"], {"n": 2})
        self.assertEqual(wgui.event_by_id(ids[0])["subject"], "op0")
        self.assertIsNone(wgui.event_by_id(10_000))

    def test_kind_filter(self):
        wgui.record_event("login", data={"ok": True})
        wgui.record_event("health", subject="us", data={"to": "down"})
        wgui.record_event("admin", subject="add")
        kinds = [e["kind"] for e in wgui.events_page(kinds=["health", "login"])]
        self.assertEqual(kinds, ["health", "login"])

    def test_unavailable_journal_never_raises(self):
        wgui.DB = os.path.join(self.tmp.name, "missing-dir", "history.db")
        self.assertIsNone(wgui.record_event("login", data={"ok": True}))

    def test_retention_by_age_and_row_cap(self):
        now = int(time.time())
        wgui.record_event("admin", subject="ancient", ts=now - (wgui.EVENTS_RETENTION_DAYS + 1) * 86400)
        for i in range(6):
            wgui.record_event("admin", subject="recent%d" % i, ts=now)
        self.patch("EVENTS_MAX_ROWS", 4)
        wgui.db_maintenance([], now=now)
        self.assertEqual([e["subject"] for e in self.all_events()],
                         ["recent2", "recent3", "recent4", "recent5"])


class TestAdminEventPrivacy(unittest.TestCase):
    def test_secrets_never_enter_the_journal(self):
        add = wgui.admin_event_data(
            "add", {"op": "add", "name": "phone", "exit": "us", "expires": 0},
            {"ok": True, "committed": True, "name": "phone", "conf": "[Interface]\nPrivateKey = x",
             "qr": "iVBOR", "pubkey": "K" * 43 + "=", "exit": "us"})
        self.assertEqual(add["name"], "phone")
        for leaked in ("conf", "qr", "PrivateKey"):
            self.assertNotIn(leaked, json.dumps(add))
        export = wgui.admin_event_data("export", {"op": "export", "password": "hunter2"},
                                       {"ok": True, "archive": "H4sI", "name": "backup.tgz"})
        self.assertNotIn("hunter2", json.dumps(export))
        self.assertNotIn("archive", export)
        split = wgui.admin_event_data("splitsave", {"op": "splitsave", "entries": ["a.example", "b.example"]},
                                      {"ok": False, "error": "x" * 500, "committed": False})
        self.assertEqual(split["entries"], 2)
        self.assertEqual(len(split["error"]), 200)
        self.assertFalse(split["committed"])


class TestEventsEndpoint(DbCase):
    def test_paging_contract(self):
        for i in range(3):
            wgui.record_event("admin", subject="op%d" % i)
        code, body = self.get(urlencode({"limit": 2}))
        self.assertEqual(code, 200)
        self.assertEqual([e["subject"] for e in body["events"]], ["op2", "op1"])
        code, body = self.get(urlencode({"limit": 2, "before": body["next_before"]}))
        self.assertEqual([e["subject"] for e in body["events"]], ["op0"])
        self.assertIsNone(body["next_before"])

    def test_single_event_and_errors(self):
        eid = wgui.record_event("exit_switch", subject="us->nl", data={"changed": 5})
        code, body = self.get("id=%d" % eid)
        self.assertEqual((code, body["event"]["data"]["changed"]), (200, 5))
        self.assertEqual(self.get("id=999999")[0], 404)
        for bad in ("kind=nope", "limit=0", "limit=9999", "before=-1", "id=abc"):
            with self.subTest(query=bad):
                self.assertEqual(self.get(bad)[0], 400)

    def test_storage_error_is_503_not_empty(self):
        def broken(*a, **kw):
            raise sqlite3.OperationalError("disk I/O error")
        self.patch("events_page", broken)
        code, body = self.get("")
        self.assertEqual(code, 503)
        self.assertEqual(body["error"], "events unavailable")

    def test_requires_session(self):
        h = fake_handler("GET", "/api/events", user=None)
        h.do_GET()
        self.assertEqual(h._code, 401)


class TestJournalWriters(DbCase):
    def setUp(self):
        super().setUp()
        a = wgui.auth
        saved = (a.USER, a.SALT, a.PASS_SHA, a.PASS_PBKDF2)
        a.USER, a.SALT, a.PASS_PBKDF2 = "admin", "s4lt", ""
        a.PASS_SHA = hashlib.sha256(b"s4ltgood-pass").hexdigest()

        def restore():
            a.USER, a.SALT, a.PASS_SHA, a.PASS_PBKDF2 = saved
        self.addCleanup(restore)
        self.patch("time", type("T", (), {"time": staticmethod(time.time),
                                          "monotonic": staticmethod(time.monotonic),
                                          "sleep": staticmethod(lambda s: None),
                                          "strftime": staticmethod(time.strftime),
                                          "localtime": staticmethod(time.localtime)}))

    def login(self, user, password, ip):
        body = urlencode({"username": user, "password": password}).encode()
        h = fake_handler("POST", "/login", body=body, user=None, ip=ip)
        h.do_POST()
        return h._out.get("Location")

    def test_login_success_and_failure(self):
        self.assertEqual(self.login("admin", "good-pass", "192.0.2.61"), "/")
        self.assertEqual(self.login("admin", "typo-secret", "192.0.2.62"), "/login?e=1")
        rows = self.all_events()
        self.assertEqual([(r["kind"], r["data"]["ok"]) for r in rows], [("login", True), ("login", False)])
        self.assertEqual(rows[0]["actor"], "admin")
        self.assertEqual(rows[1]["ip"], "192.0.2.62")
        self.assertIsNone(rows[1]["actor"])
        self.assertNotIn("typo-secret", json.dumps(rows))

    def test_throttled_login_is_journaled(self):
        ip = "192.0.2.63"
        for _ in range(wgui.LOGIN_MAX):
            self.login("admin", "nope", ip)
        self.assertEqual(self.login("admin", "good-pass", ip), "/login?e=2")
        self.assertEqual(self.all_events()[-1]["data"], {"ok": False, "reason": "throttled"})

    def test_admin_op_records_actor_ip_and_verdict(self):
        self.patch("call_admin", lambda argv, timeout=None: {
            "ok": False, "error": "timeout", "committed": "unknown"})
        pub = "A" * 43 + "="
        body = json.dumps({"op": "rename", "pubkey": pub, "name": "phone-2"}).encode()
        h = fake_handler("POST", "/api/admin", body=body, ip="192.0.2.70")
        h.do_POST()
        self.assertEqual(h._code, 400)
        row = self.all_events()[-1]
        self.assertEqual((row["kind"], row["subject"], row["actor"], row["ip"]),
                         ("admin", "rename", "admin", "192.0.2.70"))
        self.assertEqual(row["data"]["committed"], "unknown")
        self.assertEqual(row["data"]["error"], "timeout")
        self.assertEqual(row["data"]["pubkey"], pub)

    def test_reads_are_not_journaled(self):
        self.patch("call_admin", lambda argv, timeout=None: {"ok": True, "conf": "secret", "qr": ""})
        h = fake_handler("POST", "/api/admin", body=json.dumps({"op": "getconf", "pubkey": "A" * 43 + "="}).encode())
        h.do_POST()
        self.assertEqual(self.all_events(), [])

    def test_logout_all_is_journaled(self):
        self.patch("bump_session_gen", lambda: None)
        h = fake_handler("POST", "/logout-all", ip="192.0.2.71")
        h.do_POST()
        self.assertEqual(h._code, 200)
        row = self.all_events()[-1]
        self.assertEqual((row["kind"], row["actor"], row["ip"]), ("logout_all", "admin", "192.0.2.71"))


class TestHealthJournal(DbCase):
    def setUp(self):
        super().setUp()
        with wgui._lock:
            saved = {k: dict(v) for k, v in wgui._health.items()}
            saved_eg = {k: dict(v) for k, v in wgui._egress.items()}

        def restore():
            with wgui._lock:
                for k in saved:
                    wgui._health[k] = saved[k]
                    wgui._egress[k].clear(); wgui._egress[k].update(saved_eg[k])
        self.addCleanup(restore)

    def test_transitions_up_down_up(self):
        now = int(time.time())
        with wgui._lock:
            for k in ("nl", "us"):
                wgui._health[k] = {"state": "unknown", "fails": 0, "oks": 0, "since": now, "at": now}
        ok = {"nl": (True, "192.0.2.10"), "us": (True, "192.0.2.20")}
        for _ in range(exit_policy.OK_PROBES):
            wgui._record_probe(ok, now)
        self.assertEqual(self.all_events(), [])          # unknown -> up is a quiet start
        bad = {"nl": (True, "192.0.2.10"), "us": (False, None)}
        for _ in range(exit_policy.FAIL_PROBES):
            wgui._record_probe(bad, now + 10)
        for _ in range(exit_policy.OK_PROBES):
            wgui._record_probe(ok, now + 20)
        rows = self.all_events()
        self.assertEqual([(r["subject"], r["data"]["from"], r["data"]["to"]) for r in rows],
                         [("us", "up", "down"), ("us", "down", "up")])
        self.assertEqual(rows[0]["actor"], "system")

    def test_start_already_down_is_recorded(self):
        now = int(time.time())
        with wgui._lock:
            wgui._health["us"] = {"state": "unknown", "fails": 0, "oks": 0, "since": now, "at": now}
            wgui._health["nl"] = {"state": "up", "fails": 0, "oks": 2, "since": now, "at": now}
        for _ in range(exit_policy.FAIL_PROBES):
            wgui._record_probe({"nl": (True, None), "us": (False, None)}, now)
        rows = self.all_events()
        self.assertEqual([(r["data"]["from"], r["data"]["to"]) for r in rows], [("unknown", "down")])


if __name__ == "__main__":
    unittest.main()
