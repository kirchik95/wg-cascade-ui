#!/usr/bin/env python3
"""Unit tests for the pure logic of wg-ui.py / wg-admin.py / build-split.py.

No network, no WireGuard, no root — only validation, token, and set math.
Run from the repo root:  python3 -m unittest discover -s tests
"""
import contextlib, importlib.util, io, ipaddress, hashlib, os, pathlib, tempfile, time, unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
TMP = tempfile.mkdtemp(prefix="wgui-test-")
GEN = os.path.join(TMP, "session.gen")
TEST_SECRET = "unit-test-secret-abcdef0123456789"


def load(name, fname, env=None):
    for k, v in (env or {}).items():
        os.environ[k] = v
    spec = importlib.util.spec_from_file_location(name, str(APP / fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wgui = load("wgui", "wg-ui.py", {"WGUI_SESSION_SECRET": TEST_SECRET, "WGUI_GEN": GEN})
wgadmin = load("wgadmin", "wg-admin.py")
buildsplit = load("buildsplit", "build-split.py")

GOOD_PUB = "A" * 42 + "c="   # 43 base64 chars + '='


def quiet_exit(fn, *a):
    """Run fn expecting die() -> SystemExit; swallow its JSON stdout line."""
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            fn(*a)
        except SystemExit:
            return True
    return False


class TestAdminValidation(unittest.TestCase):
    def test_name_re(self):
        ok = ["iphone", "a", "Client_1", "x" * 32, "mac-book", "0led"]
        bad = ["", "-lead", "_lead", "имя", "a b", "x" * 33, "a/../b", "a;b", "a$(x)"]
        for n in ok:
            self.assertTrue(wgadmin.NAME_RE.match(n), n)
        for n in bad:
            self.assertFalse(wgadmin.NAME_RE.match(n), n)

    def test_pub_re(self):
        self.assertTrue(wgadmin.PUB_RE.match(GOOD_PUB))
        for p in ["", "A" * 43, "A" * 44 + "=", "A" * 42 + "!=", GOOD_PUB + "x"]:
            self.assertFalse(wgadmin.PUB_RE.match(p), p)

    def test_entry_re(self):
        ok = ["example.com", "sub.domain.co.uk", "1.2.3.0/24", "1.2.3.4", "wildberries.ru"]
        bad = ["-bad.com", "a b", "$(cmd)", "a;b", "/etc/passwd", ""]
        for e in ok:
            self.assertTrue(wgadmin.ENTRY_RE.match(e), e)
        for e in bad:
            self.assertFalse(wgadmin.ENTRY_RE.match(e), e)

    def test_find_missing_dies(self):
        self.assertTrue(quiet_exit(wgadmin.find, [], GOOD_PUB))

    def test_next_free_ip(self):
        self.assertEqual(wgadmin.next_free_ip([]), "10.10.0.2")
        used = [{"ip": "10.10.0.2"}, {"ip": "10.10.0.3"}, {"ip": "10.10.0.5"}]
        self.assertEqual(wgadmin.next_free_ip(used), "10.10.0.4")

    def test_client_conf(self):
        conf = wgadmin.client_conf("PRIV", "10.10.0.7")
        self.assertIn("Address = 10.10.0.7/32", conf)
        self.assertIn("AllowedIPs = 0.0.0.0/0", conf)
        self.assertIn("Endpoint = " + wgadmin.ENDPOINT, conf)
        self.assertIn("PublicKey = " + wgadmin.SERVER_PUB, conf)


class TestAdminConfParsing(unittest.TestCase):
    CONF = (
        "[Interface]\nAddress = 10.10.0.1/24\nPrivateKey = xxx\nListenPort = 51820\n"
        "PostUp = echo up\n\n"
        "[Peer]\n# phone\nPublicKey = " + GOOD_PUB + "\nAllowedIPs = 10.10.0.2/32\n\n"
        "[Peer]\nPublicKey = " + "B" * 42 + "k=" + "\nAllowedIPs = 10.10.0.5/32\n"
    )

    def setUp(self):
        self.path = os.path.join(TMP, "wg-test.conf")
        with open(self.path, "w") as f:
            f.write(self.CONF)
        self.orig = wgadmin.WG_CONF
        wgadmin.WG_CONF = self.path

    def tearDown(self):
        wgadmin.WG_CONF = self.orig

    def test_read_head_stops_at_first_peer(self):
        head = wgadmin.read_head()
        self.assertIn("[Interface]", head)
        self.assertIn("PostUp", head)
        self.assertNotIn("[Peer]", head)

    def test_bootstrap_names_and_fallback(self):
        clients = wgadmin.bootstrap_from_conf()
        self.assertEqual(len(clients), 2)
        self.assertEqual(clients[0], {"name": "phone", "ip": "10.10.0.2",
                                      "pubkey": GOOD_PUB, "enabled": True})
        self.assertEqual(clients[1]["name"], "client4")   # derived from .5 - 1
        self.assertEqual(clients[1]["ip"], "10.10.0.5")

    def test_peer_block(self):
        blk = wgadmin.peer_block({"name": "phone", "pubkey": GOOD_PUB, "ip": "10.10.0.2"})
        self.assertEqual(blk, "[Peer]\n# phone\nPublicKey = %s\nAllowedIPs = 10.10.0.2/32\n" % GOOD_PUB)


class TestTokens(unittest.TestCase):
    def setUp(self):
        try:
            os.unlink(GEN)
        except OSError:
            pass

    def test_roundtrip(self):
        tok = wgui.make_token("admin", int(time.time()) + 60)
        self.assertEqual(wgui.check_token(tok), "admin")

    def test_expired(self):
        tok = wgui.make_token("admin", int(time.time()) - 1)
        self.assertIsNone(wgui.check_token(tok))

    def test_tampered_signature(self):
        tok = wgui.make_token("admin", int(time.time()) + 60)
        m, s = tok.split(".", 1)
        bad = m + "." + ("A" + s[1:] if s[0] != "A" else "B" + s[1:])
        self.assertIsNone(wgui.check_token(bad))

    def test_legacy_two_field_token_rejected(self):
        msg = b"admin|9999999999"
        import hmac as _hmac
        sig = _hmac.new(wgui.SECRET, msg, hashlib.sha256).digest()
        tok = wgui._b64e(msg) + "." + wgui._b64e(sig)
        self.assertIsNone(wgui.check_token(tok))

    def test_gen_bump_revokes_sessions_and_rotates_csrf(self):
        tok = wgui.make_token("admin", int(time.time()) + 60)
        csrf_before = wgui.csrf_for("admin")
        self.assertEqual(wgui.check_token(tok), "admin")
        wgui.bump_session_gen()
        self.assertIsNone(wgui.check_token(tok))
        self.assertNotEqual(csrf_before, wgui.csrf_for("admin"))
        tok2 = wgui.make_token("admin", int(time.time()) + 60)
        self.assertEqual(wgui.check_token(tok2), "admin")


class TestCreds(unittest.TestCase):
    def setUp(self):
        self.saved = (wgui.USER, wgui.SALT, wgui.PASS_SHA, wgui.PASS_PBKDF2)
        wgui.USER, wgui.SALT = "admin", "s4lt"

    def tearDown(self):
        wgui.USER, wgui.SALT, wgui.PASS_SHA, wgui.PASS_PBKDF2 = self.saved

    def test_legacy_sha256(self):
        wgui.PASS_PBKDF2 = ""
        wgui.PASS_SHA = hashlib.sha256(b"s4ltpw123").hexdigest()
        self.assertTrue(wgui.creds_ok("admin", "pw123"))
        self.assertFalse(wgui.creds_ok("admin", "wrong"))
        self.assertFalse(wgui.creds_ok("root", "pw123"))

    def test_legacy_empty_hash_never_matches(self):
        wgui.PASS_PBKDF2, wgui.PASS_SHA = "", ""
        self.assertFalse(wgui.creds_ok("admin", ""))

    def test_pbkdf2_preferred(self):
        dk = hashlib.pbkdf2_hmac("sha256", b"pw123", b"s4lt", 1000).hex()
        wgui.PASS_PBKDF2 = "1000$" + dk
        wgui.PASS_SHA = ""
        self.assertTrue(wgui.creds_ok("admin", "pw123"))
        self.assertFalse(wgui.creds_ok("admin", "wrong"))

    def test_pbkdf2_malformed_rejects(self):
        wgui.PASS_PBKDF2 = "not-a-valid-value"
        self.assertFalse(wgui.creds_ok("admin", "pw123"))


class TestLoginThrottle(unittest.TestCase):
    def test_blocks_after_max_failures(self):
        ip = "203.0.113.7"
        self.assertFalse(wgui.login_blocked(ip))
        for _ in range(wgui.LOGIN_MAX):
            wgui.login_failed(ip)
        self.assertTrue(wgui.login_blocked(ip))
        self.assertFalse(wgui.login_blocked("203.0.113.8"))   # other IPs unaffected

    def test_success_clears(self):
        ip = "203.0.113.9"
        for _ in range(wgui.LOGIN_MAX):
            wgui.login_failed(ip)
        self.assertTrue(wgui.login_blocked(ip))
        wgui.login_ok(ip)
        self.assertFalse(wgui.login_blocked(ip))


class TestHistoryDB(unittest.TestCase):
    def test_usage_accrual_and_per_client_daily(self):
        saved = wgui.DB
        wgui.DB = os.path.join(TMP, "hist.db")
        try:
            wgui.db_init()
            wgui.record_usage({"PUB1": (100, 200)})    # first sample: baseline only
            wgui.record_usage({"PUB1": (150, 260)})    # +50 / +60
            wgui.record_usage({"PUB1": (30, 10)})      # counter reset -> delta = current
            rows = wgui.usage_daily_for("PUB1")
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["rx"], rows[0]["tx"]), (80, 70))
            self.assertEqual(wgui.usage_daily_for("OTHER"), [])
            month = wgui.usage_month()
            self.assertEqual(month["PUB1"], {"rx": 80, "tx": 70})
        finally:
            wgui.DB = saved


class TestExitHelpers(unittest.TestCase):
    def test_normalize_exit(self):
        self.assertEqual(wgadmin.normalize_exit("nl"), "nl")
        self.assertEqual(wgadmin.normalize_exit("US"), "us")
        self.assertEqual(wgadmin.normalize_exit(""), "nl")
        self.assertTrue(quiet_exit(wgadmin.normalize_exit, "de"))
        self.assertTrue(quiet_exit(wgadmin.normalize_exit, "nl;rm"))

    def test_client_exit_default(self):
        self.assertEqual(wgadmin.client_exit({}), "nl")
        self.assertEqual(wgadmin.client_exit({"exit": "us"}), "us")
        self.assertEqual(wgadmin.client_exit({"exit": "bogus"}), "nl")

    def test_tunnel_state_with_exits(self):
        saved_eg = {k: dict(v) for k, v in wgui._egress.items()}
        orig_peer = wgui.wg_peer
        try:
            with wgui._lock:
                wgui._egress["nl"].update(ok=True, seen="1.1.1.1", at=int(time.time()))
                wgui._egress["us"].update(ok=False, seen=None, at=int(time.time()))
            wgui.wg_peer = lambda iface: (
                {"age": 5, "up": True} if iface == wgui.DO_IFACE
                else {"age": -1, "up": False})
            t = wgui.tunnel()
            self.assertEqual(t["state"], "up")          # NL ok → overall up
            self.assertIn("exits", t)
            self.assertNotIn("exit_ip", t)              # flat NL fields removed
            self.assertNotIn("wg_up", t)
            self.assertTrue(t["exits"]["nl"]["ok"])
            self.assertFalse(t["exits"]["us"]["ok"])
            self.assertEqual(t["exits"]["nl"]["exit_ip"], wgui.EXIT_IP)
            with wgui._lock:
                wgui._egress["nl"].update(ok=False, seen=None)
            wgui.wg_peer = lambda iface: {"age": -1, "up": False}
            self.assertEqual(wgui.tunnel()["state"], "down")
            wgui.wg_peer = lambda iface: {"age": 3, "up": True}
            self.assertEqual(wgui.tunnel()["state"], "degraded")
        finally:
            with wgui._lock:
                for k, v in saved_eg.items():
                    wgui._egress[k].clear()
                    wgui._egress[k].update(v)
            wgui.wg_peer = orig_peer


class TestComplement(unittest.TestCase):
    def test_covers_everything_except_excluded(self):
        excl = [ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("192.168.0.0/16")]
        comp = buildsplit.complement(excl)
        total = sum(n.num_addresses for n in comp)
        self.assertEqual(total, 2 ** 32 - 2 ** 24 - 2 ** 16)
        for n in comp:
            for e in excl:
                self.assertFalse(n.overlaps(e), "%s overlaps %s" % (n, e))

    def test_overlapping_input_collapsed(self):
        excl = [ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("10.1.0.0/16")]
        comp = buildsplit.complement(excl)
        self.assertEqual(sum(n.num_addresses for n in comp), 2 ** 32 - 2 ** 24)

    def test_parse_entry_cidr_and_ip(self):
        self.assertEqual(buildsplit.parse_entry("1.2.3.0/24"),
                         [ipaddress.ip_network("1.2.3.0/24")])
        self.assertEqual(buildsplit.parse_entry("1.2.3.4"),
                         [ipaddress.ip_network("1.2.3.4/32")])
        self.assertEqual(buildsplit.parse_entry("2001:db8::/32"), [])   # v6 dropped


if __name__ == "__main__":
    unittest.main()
