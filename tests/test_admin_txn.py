"""wg-admin single-client operations commit or roll back as a unit (F10)."""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
spec = importlib.util.spec_from_file_location("wgadmin_txn", str(APP / "wg-admin.py"))
wgadmin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgadmin)

PUB = "A" * 42 + "c="
HEAD = "[Interface]\nPrivateKey = x\nListenPort = 51820\n"


class TxnCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
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
        self.kernel = []
        self.route_fail = False
        self.patch("read_head", lambda: HEAD.rstrip("\n"))
        self.patch("sync_kernel", lambda: self.kernel.append(pathlib.Path(wgadmin.WG_CONF).read_text()))
        self.patch("run_exit_sync_or_raise", self.route_sync)
        self.patch("flush_exit_conntrack", lambda ip: None)
        self.patch("audit", lambda *a, **k: None)
        self.snapshot = {p: pathlib.Path(p).read_bytes()
                         for p in (wgadmin.CLIENTS_JSON, wgadmin.WG_CONF, wgadmin.NAMES_JSON)}

    def route_sync(self):
        if self.route_fail:
            self.route_fail = False      # rollback's re-sync succeeds
            raise RuntimeError("exit-route sync failed: boom")

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


class TestTransactions(TxnCase):
    def test_disable_rolls_back_registry_conf_and_kernel_on_route_failure(self):
        self.route_fail = True
        res = self.call(wgadmin.op_setenabled, PUB, "0")
        self.assertFalse(res["ok"])
        self.assertIn("rolled back", res["error"])
        self.assert_unchanged()
        self.assertIn(PUB, self.kernel[-1])      # kernel re-synced with the restored peer

    def test_setexit_failure_keeps_old_exit(self):
        self.route_fail = True
        res = self.call(wgadmin.op_setexit, PUB, "us")
        self.assertFalse(res["ok"])
        self.assertNotIn("exit", json.loads(pathlib.Path(wgadmin.CLIENTS_JSON).read_text())[0])

    def test_setexit_retry_on_same_value_reconciles_routes(self):
        calls = []
        self.patch("run_exit_sync_or_raise", lambda: calls.append("sync"))
        res = self.call(wgadmin.op_setexit, PUB, "nl")
        self.assertTrue(res["ok"])
        self.assertEqual(calls, ["sync"])

    def test_rename_failure_moves_config_files_back(self):
        conf = os.path.join(wgadmin.CLIENT_DIR, "phone.conf")
        pathlib.Path(conf).write_text("conf")
        self.route_fail = True
        res = self.call(wgadmin.op_rename, PUB, "tablet")
        self.assertFalse(res["ok"])
        self.assertTrue(os.path.exists(conf))
        self.assertFalse(os.path.exists(os.path.join(wgadmin.CLIENT_DIR, "tablet.conf")))
        self.assert_unchanged()

    def test_delete_keeps_config_files_when_apply_fails(self):
        conf = os.path.join(wgadmin.CLIENT_DIR, "phone.conf")
        pathlib.Path(conf).write_text("conf")
        self.route_fail = True
        self.assertFalse(self.call(wgadmin.op_delete, PUB)["ok"])
        self.assertTrue(os.path.exists(conf))
        self.assert_unchanged()

    def test_rollback_failure_is_reported(self):
        def always_fail():
            raise RuntimeError("exit-route sync failed: down")
        self.patch("run_exit_sync_or_raise", always_fail)
        res = self.call(wgadmin.op_setenabled, PUB, "0")
        self.assertIn("rollback failed", res["error"])

    def test_success_commits(self):
        self.assertTrue(self.call(wgadmin.op_setenabled, PUB, "0")["ok"])
        self.assertFalse(json.loads(pathlib.Path(wgadmin.CLIENTS_JSON).read_text())[0]["enabled"])
        self.assertNotIn(PUB, self.kernel[-1])


class TestIPv6AndExport(TxnCase):
    def test_new_client_config_routes_ipv6_into_tunnel(self):
        self.assertIn("AllowedIPs = 0.0.0.0/0, ::/0", wgadmin.client_conf("priv", "10.10.0.9"))

    def test_blockipv6_updates_only_full_tunnel_configs(self):
        full = pathlib.Path(wgadmin.CLIENT_DIR, "phone.conf")
        split = pathlib.Path(wgadmin.CLIENT_DIR, "legacy.conf")
        full.write_text("[Peer]\nAllowedIPs = 0.0.0.0/0\n")
        split.write_text("[Peer]\nAllowedIPs = 1.0.0.0/8, 2.0.0.0/7\n")
        res = self.call(wgadmin.op_blockipv6)
        self.assertEqual(res["updated"], ["phone"])
        self.assertIn("::/0", full.read_text())
        self.assertNotIn("::/0", split.read_text())
        self.assertEqual(self.call(wgadmin.op_blockipv6)["updated"], [])   # idempotent

    def test_export_has_manifest_and_consistent_history(self):
        import base64, sqlite3, tarfile
        db = os.path.join(self.tmp.name, "history.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE t(x)"); con.execute("INSERT INTO t VALUES (42)"); con.commit(); con.close()
        self.patch("HISTORY_DB", db)
        res = self.call(wgadmin.op_export)
        with tarfile.open(fileobj=io.BytesIO(base64.b64decode(res["archive"])), mode="r:gz") as tar:
            names = tar.getnames()
            manifest = json.load(tar.extractfile("manifest.json"))
            restored = os.path.join(self.tmp.name, "restored.db")
            pathlib.Path(restored).write_bytes(tar.extractfile("extra/history.db").read())
        self.assertIn("clients.json", names)
        self.assertEqual(sqlite3.connect(restored).execute("SELECT x FROM t").fetchone(), (42,))
        present = {f["name"]: f["present"] for f in manifest["files"]}
        self.assertTrue(present["extra/history.db"])
        self.assertFalse(present["extra/wg-ui.env"])
        self.assertIn("extra/wg-ui.env", res["missing"])


if __name__ == "__main__":
    unittest.main()
