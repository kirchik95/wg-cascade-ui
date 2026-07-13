import copy
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
os.environ.setdefault("WGUI_SESSION_SECRET", "exit-accounting-test-secret-0123456789")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-exit-accounting.gen"))

spec = importlib.util.spec_from_file_location("wgui_exit_accounting", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)


class TestExitAccounting(unittest.TestCase):
    def setUp(self):
        self.old_db = wgui.DB
        self.old_sampler_meta = copy.deepcopy(wgui._sampler_meta)
        self.tmp = tempfile.TemporaryDirectory()
        wgui.DB = os.path.join(self.tmp.name, "history.db")
        wgui.db_init()

    def tearDown(self):
        wgui.DB = self.old_db
        with wgui._lock:
            wgui._sampler_meta.clear()
            wgui._sampler_meta.update(self.old_sampler_meta)
        self.tmp.cleanup()

    def test_exit_peer_includes_transfer_counters(self):
        lines = ["priv\tpub\t51820\toff", "peer\t(none)\t1.2.3.4:51820\t0.0.0.0/0\t100\t123\t456\t25"]
        peer = wgui._peer_from_dump(lines)
        self.assertEqual((peer["rx"], peer["tx"]), (123, 456))

    def test_exit_usage_baseline_deltas_and_reset(self):
        wgui.record_exit_usage({"nl": (100, 200), "us": (10, 20)}, "2026-07-13")
        wgui.record_exit_usage({"nl": (150, 260), "us": (30, 50)}, "2026-07-13")
        wgui.record_exit_usage({"nl": (5, 7)}, "2026-07-13")
        month = wgui.exit_usage_month(time.mktime((2026, 7, 13, 0, 0, 0, 0, 0, -1)))
        self.assertEqual(month["nl"], {"rx": 55, "tx": 67})
        self.assertEqual(month["us"], {"rx": 20, "tx": 30})

    def test_seed_is_idempotent_and_uses_current_assignment(self):
        c = wgui._conn()
        c.execute("INSERT INTO usage(pubkey,day,rx,tx) VALUES('A','2026-07-01',10,20)")
        c.execute("INSERT INTO usage(pubkey,day,rx,tx) VALUES('B','2026-07-01',30,40)")
        c.commit(); c.close()
        registry = [{"pubkey": "A"}, {"pubkey": "B", "exit": "us"}]
        self.assertTrue(wgui.seed_exit_usage(registry, "2026-07-01"))
        self.assertFalse(wgui.seed_exit_usage(registry, "2026-07-01"))
        month = wgui.exit_usage_month(time.mktime((2026, 7, 13, 0, 0, 0, 0, 0, -1)))
        self.assertEqual(month["nl"], {"rx": 10, "tx": 20})
        self.assertEqual(month["us"], {"rx": 30, "tx": 40})

    def test_exit_usage_month_excludes_next_month(self):
        c = wgui._conn()
        c.execute("INSERT INTO exit_usage(exit,day,rx,tx) VALUES('nl','2026-07-31',10,20)")
        c.execute("INSERT INTO exit_usage(exit,day,rx,tx) VALUES('nl','2026-08-01',100,200)")
        c.commit(); c.close()
        month = wgui.exit_usage_month(time.mktime((2026, 7, 13, 0, 0, 0, 0, 0, -1)))
        self.assertEqual(month["nl"], {"rx": 10, "tx": 20})

    def test_seed_exit_usage_excludes_next_month(self):
        c = wgui._conn()
        c.execute("INSERT INTO usage(pubkey,day,rx,tx) VALUES('A','2026-07-31',10,20)")
        c.execute("INSERT INTO usage(pubkey,day,rx,tx) VALUES('A','2026-08-01',100,200)")
        c.commit(); c.close()
        self.assertTrue(wgui.seed_exit_usage([{"pubkey": "A"}], "2026-07-01"))
        c = wgui._conn()
        rows = c.execute("SELECT day,rx,tx FROM exit_usage ORDER BY day").fetchall()
        c.close()
        self.assertEqual([(row["day"], row["rx"], row["tx"]) for row in rows],
                         [("2026-07-31", 10, 20)])

    def test_exit_usage_month_accepts_epoch_zero(self):
        c = wgui._conn()
        c.execute("INSERT INTO exit_usage(exit,day,rx,tx) VALUES('nl','1970-01-01',1,2)")
        c.execute("INSERT INTO exit_usage(exit,day,rx,tx) VALUES('nl','2026-07-01',100,200)")
        c.commit(); c.close()
        month = wgui.exit_usage_month(0)
        self.assertEqual(month["nl"], {"rx": 1, "tx": 2})

    def test_missing_registry_with_current_month_history_does_not_consume_seed_marker(self):
        c = wgui._conn()
        c.execute("INSERT INTO usage(pubkey,day,rx,tx) VALUES('A','2026-07-13',10,20)")
        c.commit(); c.close()
        old_clients = wgui.CLIENTS
        wgui.CLIENTS = os.path.join(self.tmp.name, "missing-clients.json")
        try:
            bootstrap = getattr(wgui, "seed_exit_usage_from_registry", None)
            self.assertIsNotNone(bootstrap)
            with self.assertRaisesRegex(RuntimeError, "registry unavailable"):
                bootstrap("2026-07-01")
            c = wgui._conn()
            marker = c.execute(
                "SELECT value FROM schema_meta WHERE key='exit_usage_v1_seeded'"
            ).fetchone()
            c.close()
            self.assertIsNone(marker)
        finally:
            wgui.CLIENTS = old_clients

    def test_fresh_install_missing_registry_completes_startup_bootstrap(self):
        class StartupReachedSampler(Exception):
            pass

        old_clients = wgui.CLIENTS
        old_secret = wgui.auth.SECRET
        old_pass_sha = wgui.auth.PASS_SHA
        wgui.CLIENTS = os.path.join(self.tmp.name, "missing-clients.json")
        wgui.auth.SECRET = b"fresh-install-startup-secret"
        wgui.auth.PASS_SHA = "configured"
        try:
            with mock.patch.object(wgui.threading, "Thread") as thread_class:
                thread_class.return_value.start.side_effect = StartupReachedSampler
                with self.assertRaises(StartupReachedSampler):
                    wgui.main()
            c = wgui._conn()
            marker = c.execute(
                "SELECT value FROM schema_meta WHERE key='exit_usage_v1_seeded'"
            ).fetchone()
            c.close()
            self.assertEqual(marker["value"], "1")
        finally:
            wgui.CLIENTS = old_clients
            wgui.auth.SECRET = old_secret
            wgui.auth.PASS_SHA = old_pass_sha

    def test_missing_registry_retains_live_peer_fallback_after_bootstrap(self):
        old_clients = wgui.CLIENTS
        wgui.CLIENTS = os.path.join(self.tmp.name, "missing-clients.json")
        with wgui._lock:
            old_live = dict(wgui._live)
            wgui._live.clear()
            wgui._live["PUB"] = {
                "ep": "198.51.100.2:51820", "ip": "10.10.0.2",
                "hs": int(time.time()), "rx": 10, "tx": 20,
            }
        try:
            self.assertTrue(wgui.seed_exit_usage_from_registry("2026-07-01"))
            peers = wgui.clients_status()
            self.assertEqual(len(peers), 1)
            self.assertEqual(peers[0]["name"], "client1")
            self.assertEqual(peers[0]["pubkey"], "PUB")
        finally:
            wgui.CLIENTS = old_clients
            with wgui._lock:
                wgui._live.clear()
                wgui._live.update(old_live)

    def test_malformed_registry_with_empty_history_does_not_consume_seed_marker(self):
        old_clients = wgui.CLIENTS
        clients = os.path.join(self.tmp.name, "clients.json")
        with open(clients, "w") as f:
            f.write("{")
        wgui.CLIENTS = clients
        try:
            with self.assertRaisesRegex(RuntimeError, "registry"):
                wgui.seed_exit_usage_from_registry("2026-07-01")
            c = wgui._conn()
            marker = c.execute(
                "SELECT value FROM schema_meta WHERE key='exit_usage_v1_seeded'"
            ).fetchone()
            c.close()
            self.assertIsNone(marker)
        finally:
            wgui.CLIENTS = old_clients

    def test_structurally_malformed_registry_fails_closed_with_empty_history(self):
        old_clients = wgui.CLIENTS
        clients = os.path.join(self.tmp.name, "clients.json")
        try:
            for registry in (None, {}, ["not-a-record"], [{"pubkey": "A", "exit": "ca"}]):
                with self.subTest(registry=registry):
                    with open(clients, "w") as f:
                        f.write(json.dumps(registry))
                    wgui.CLIENTS = clients
                    with self.assertRaisesRegex(RuntimeError, "registry"):
                        wgui.seed_exit_usage_from_registry("2026-07-01")
                    c = wgui._conn()
                    marker = c.execute(
                        "SELECT value FROM schema_meta WHERE key='exit_usage_v1_seeded'"
                    ).fetchone()
                    c.close()
                    self.assertIsNone(marker)
                c = wgui._conn()
                c.execute("DELETE FROM schema_meta WHERE key='exit_usage_v1_seeded'")
                c.execute("DELETE FROM exit_usage")
                c.commit(); c.close()
        finally:
            wgui.CLIENTS = old_clients

    def test_valid_empty_registry_completes_seed(self):
        old_clients = wgui.CLIENTS
        clients = os.path.join(self.tmp.name, "clients.json")
        with open(clients, "w") as f:
            f.write("[]")
        wgui.CLIENTS = clients
        try:
            bootstrap = getattr(wgui, "seed_exit_usage_from_registry", None)
            self.assertIsNotNone(bootstrap)
            self.assertTrue(bootstrap("2026-07-01"))
            c = wgui._conn()
            marker = c.execute(
                "SELECT value FROM schema_meta WHERE key='exit_usage_v1_seeded'"
            ).fetchone()
            c.close()
            self.assertEqual(marker["value"], "1")
        finally:
            wgui.CLIENTS = old_clients

    def test_completed_seed_does_not_require_registry(self):
        c = wgui._conn()
        c.execute("INSERT INTO schema_meta(key,value) VALUES('exit_usage_v1_seeded','original')")
        c.commit(); c.close()
        malformed = os.path.join(self.tmp.name, "malformed-clients.json")
        with open(malformed, "w") as f:
            f.write("{")
        old_clients = wgui.CLIENTS
        try:
            for clients in (os.path.join(self.tmp.name, "missing-clients.json"), malformed):
                with self.subTest(clients=clients):
                    wgui.CLIENTS = clients
                    try:
                        result = wgui.seed_exit_usage_from_registry("2026-07-01")
                    except Exception as exc:
                        self.fail("completed seed required registry: %s" % exc)
                    self.assertFalse(result)
                    c = wgui._conn()
                    marker = c.execute(
                        "SELECT value FROM schema_meta WHERE key='exit_usage_v1_seeded'"
                    ).fetchone()
                    c.close()
                    self.assertEqual(marker["value"], "original")
        finally:
            wgui.CLIENTS = old_clients

    def test_collection_success_preserves_persistence_error(self):
        persistence_note = getattr(wgui, "_sampler_persistence_note", None)
        self.assertIsNotNone(persistence_note)
        wgui._sampler_note(True)
        persistence_note(True)
        persistence_note(False, "usage persistence: disk full")
        wgui._sampler_note(True)
        self.assertEqual(wgui.sampler_info()["err"], "usage persistence: disk full")

    def test_persistence_success_clears_persistence_error(self):
        persistence_note = getattr(wgui, "_sampler_persistence_note", None)
        self.assertIsNotNone(persistence_note)
        wgui._sampler_note(True)
        persistence_note(False, "usage persistence: disk full")
        persistence_note(True)
        self.assertIsNone(wgui.sampler_info()["err"])


if __name__ == "__main__":
    unittest.main()
