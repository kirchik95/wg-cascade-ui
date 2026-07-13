import importlib.util
import os
import pathlib
import sys
import tempfile
import time
import unittest

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
        self.tmp = tempfile.TemporaryDirectory()
        wgui.DB = os.path.join(self.tmp.name, "history.db")
        wgui.db_init()

    def tearDown(self):
        wgui.DB = self.old_db
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


if __name__ == "__main__":
    unittest.main()
