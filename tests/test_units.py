#!/usr/bin/env python3
"""Unit tests for the pure logic of wg-ui.py / wg-admin.py / build-split.py.

No network, no WireGuard, no root — only validation, token, and set math.
Run from the repo root:  python3 -m unittest discover -s tests
"""
import contextlib, importlib.util, io, ipaddress, hashlib, json, os, pathlib, tempfile, time, unittest
from unittest import mock

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
# Auth state lives in auth.py — keep wgui.* aliases in sync for existing tests.
import auth as _auth
wgui.auth = _auth
# Point module-level names used by tests at the auth module attributes via helpers below.


GOOD_PUB = "A" * 42 + "c="   # 43 base64 chars + '='

# Seed deploy values so helper tests work without /etc/wg-ui/wg-ui.env
if not wgadmin.SERVER_PUB:
    wgadmin.SERVER_PUB = GOOD_PUB
if not wgadmin.ENDPOINT:
    wgadmin.ENDPOINT = "203.0.113.10:51820"
if not wgadmin.WAN_IFACE:
    wgadmin.WAN_IFACE = "eth0"


def quiet_exit(fn, *a):
    """Run fn expecting die() -> SystemExit; swallow its JSON stdout line."""
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            fn(*a)
        except SystemExit:
            return True
    return False


class TestThroughputDirection(unittest.TestCase):
    def test_down_is_what_clients_receive(self):
        # samples are (t, total peer rx, total peer tx): peer tx = bytes sent to clients = their download
        with mock.patch.object(wgui, "_samples", [(0, 0, 0), (10, 100, 5000)]):
            cur = wgui.throughput()["cur"]
        self.assertEqual(cur["down"], 500)
        self.assertEqual(cur["up"], 10)


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
            os.unlink(wgui.auth.GEN_FILE)
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
        sig = _hmac.new(wgui.auth.SECRET, msg, hashlib.sha256).digest()
        tok = wgui.auth._b64e(msg) + "." + wgui.auth._b64e(sig)
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

    def test_lost_gen_file_does_not_revive_revoked_tokens(self):
        tok = wgui.make_token("admin", int(time.time()) + 60)
        wgui.bump_session_gen()
        os.unlink(wgui.auth.GEN_FILE)
        self.assertIsNone(wgui.check_token(tok))
        self.assertEqual(wgui.check_token(wgui.make_token("admin", int(time.time()) + 60)), "admin")

    def test_legacy_counter_gen_still_valid(self):
        with open(wgui.auth.GEN_FILE, "w") as f:
            f.write("3\n")
        self.assertEqual(wgui.check_token(wgui.make_token("admin", int(time.time()) + 60)), "admin")

    def test_corrupt_gen_file_rejects_sessions(self):
        tok = wgui.make_token("admin", int(time.time()) + 60)
        with open(wgui.auth.GEN_FILE, "w") as f:
            f.write("not a generation")
        self.assertIsNone(wgui.check_token(tok))
        with self.assertRaises(RuntimeError):
            wgui.make_token("admin", int(time.time()) + 60)


class TestCreds(unittest.TestCase):
    def setUp(self):
        a = wgui.auth
        self.saved = (a.USER, a.SALT, a.PASS_SHA, a.PASS_PBKDF2)
        a.USER, a.SALT = "admin", "s4lt"

    def tearDown(self):
        a = wgui.auth
        a.USER, a.SALT, a.PASS_SHA, a.PASS_PBKDF2 = self.saved

    def test_legacy_sha256(self):
        a = wgui.auth
        a.PASS_PBKDF2 = ""
        a.PASS_SHA = hashlib.sha256(b"s4ltpw123").hexdigest()
        self.assertTrue(wgui.creds_ok("admin", "pw123"))
        self.assertFalse(wgui.creds_ok("admin", "wrong"))
        self.assertFalse(wgui.creds_ok("root", "pw123"))

    def test_legacy_empty_hash_never_matches(self):
        a = wgui.auth
        a.PASS_PBKDF2, a.PASS_SHA = "", ""
        self.assertFalse(wgui.creds_ok("admin", ""))

    def test_pbkdf2_preferred(self):
        a = wgui.auth
        dk = hashlib.pbkdf2_hmac("sha256", b"pw123", b"s4lt", 1000).hex()
        a.PASS_PBKDF2 = "1000$" + dk
        a.PASS_SHA = ""
        self.assertTrue(wgui.creds_ok("admin", "pw123"))
        self.assertFalse(wgui.creds_ok("admin", "wrong"))

    def test_pbkdf2_malformed_rejects(self):
        wgui.auth.PASS_PBKDF2 = "not-a-valid-value"
        self.assertFalse(wgui.creds_ok("admin", "pw123"))


class TestLoginThrottle(unittest.TestCase):
    def setUp(self):
        with wgui.auth._fails_lock:
            wgui.auth._fails.clear()

    def test_blocks_after_max_failures(self):
        ip = "203.0.113.7"
        self.assertFalse(wgui.login_blocked(ip))
        for _ in range(wgui.auth.LOGIN_MAX):
            wgui.login_failed(ip)
        self.assertTrue(wgui.login_blocked(ip))
        self.assertFalse(wgui.login_blocked("203.0.113.8"))   # other IPs unaffected

    def test_success_clears(self):
        ip = "203.0.113.9"
        for _ in range(wgui.auth.LOGIN_MAX):
            wgui.login_failed(ip)
        self.assertTrue(wgui.login_blocked(ip))
        wgui.login_ok(ip)
        self.assertFalse(wgui.login_blocked(ip))

    def test_flood_evicts_oldest_not_clear_all(self):
        """Under IP flood, keep recent lockouts — never wipe the whole map."""
        saved = wgui.auth._FAILS_MAX_IPS
        wgui.auth._FAILS_MAX_IPS = 3
        try:
            wgui.login_failed("10.0.0.1")
            wgui.login_failed("10.0.0.1")
            wgui.login_failed("10.0.0.1")
            wgui.login_failed("10.0.0.1")
            wgui.login_failed("10.0.0.1")  # blocked
            self.assertTrue(wgui.login_blocked("10.0.0.1"))
            wgui.login_failed("10.0.0.2")
            wgui.login_failed("10.0.0.3")
            wgui.login_failed("10.0.0.4")  # should evict oldest (0.1), not clear all
            with wgui.auth._fails_lock:
                self.assertLessEqual(len(wgui.auth._fails), 3)
                self.assertNotIn("10.0.0.1", wgui.auth._fails)
                self.assertIn("10.0.0.4", wgui.auth._fails)
        finally:
            wgui.auth._FAILS_MAX_IPS = saved


class TestBodyLimit(unittest.TestCase):
    def test_accepts_within_limit(self):
        self.assertEqual(wgui.check_body_length(100, 256), 100)
        self.assertEqual(wgui.check_body_length(0, 256), 0)

    def test_rejects_over_limit(self):
        with self.assertRaises(ValueError):
            wgui.check_body_length(257, 256)
        with self.assertRaises(ValueError):
            wgui.check_body_length(-1, 256)


class TestHealthz(unittest.TestCase):
    def test_health_payload_shape(self):
        h = wgui.healthz()
        self.assertEqual(h["ok"], True)
        self.assertIn("uptime_s", h)
        self.assertIn("sampler", h)
        self.assertIn("threads", h)

    def test_log_event_emits_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            wgui.log_event("test", path="/x", status=200, ms=12)
        line = buf.getvalue().strip()
        obj = json.loads(line)
        self.assertEqual(obj["event"], "test")
        self.assertEqual(obj["path"], "/x")
        self.assertEqual(obj["status"], 200)


class TestAdminRequiredEnv(unittest.TestCase):
    def test_require_deploy_env_ok(self):
        saved = (wgadmin.SERVER_PUB, wgadmin.ENDPOINT, wgadmin.WAN_IFACE)
        try:
            wgadmin.SERVER_PUB = "A" * 43 + "="
            wgadmin.ENDPOINT = "1.2.3.4:51820"
            wgadmin.WAN_IFACE = "eth0"
            wgadmin.require_deploy_env()  # must not die
        finally:
            wgadmin.SERVER_PUB, wgadmin.ENDPOINT, wgadmin.WAN_IFACE = saved

    def test_require_deploy_env_rejects_placeholder(self):
        saved = (wgadmin.SERVER_PUB, wgadmin.ENDPOINT, wgadmin.WAN_IFACE)
        try:
            wgadmin.SERVER_PUB = ""
            wgadmin.ENDPOINT = "1.2.3.4:51820"
            wgadmin.WAN_IFACE = "eth0"
            self.assertTrue(quiet_exit(wgadmin.require_deploy_env))
            wgadmin.SERVER_PUB = "A" * 43 + "="
            wgadmin.ENDPOINT = ""
            self.assertTrue(quiet_exit(wgadmin.require_deploy_env))
            wgadmin.ENDPOINT = "1.2.3.4:51820"
            wgadmin.WAN_IFACE = ""
            self.assertTrue(quiet_exit(wgadmin.require_deploy_env, True))  # need_wan
        finally:
            wgadmin.SERVER_PUB, wgadmin.ENDPOINT, wgadmin.WAN_IFACE = saved


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
        saved_peers = dict(wgui._exit_peers)
        try:
            with wgui._lock:
                wgui._egress["nl"].update(ok=True, seen="1.1.1.1", at=int(time.time()))
                wgui._egress["us"].update(ok=False, seen=None, at=int(time.time()))
                wgui._exit_peers["nl"] = {"age": 5, "up": True}
                wgui._exit_peers["us"] = {"age": -1, "up": False}
            t = wgui.tunnel()
            self.assertEqual(t["state"], "up")          # NL ok → overall up
            self.assertIn("exits", t)
            self.assertNotIn("exit_ip", t)              # flat NL fields removed
            self.assertNotIn("wg_up", t)
            self.assertTrue(t["exits"]["nl"]["ok"])
            self.assertFalse(t["exits"]["us"]["ok"])
            self.assertEqual(t["exits"]["nl"]["exit_ip"], wgui.EXIT_IP or None)
            with wgui._lock:
                wgui._egress["nl"].update(ok=False, seen=None)
                wgui._exit_peers["nl"] = {"age": -1, "up": False}
                wgui._exit_peers["us"] = {"age": -1, "up": False}
            self.assertEqual(wgui.tunnel()["state"], "down")
            with wgui._lock:
                wgui._exit_peers["nl"] = {"age": 3, "up": True}
            self.assertEqual(wgui.tunnel()["state"], "degraded")
        finally:
            with wgui._lock:
                for k, v in saved_eg.items():
                    wgui._egress[k].clear()
                    wgui._egress[k].update(v)
                wgui._exit_peers.clear()
                wgui._exit_peers.update(saved_peers)


class TestStatusCache(unittest.TestCase):
    def setUp(self):
        with wgui._lock:
            wgui._live.clear()
            wgui._exit_peers.clear()
            wgui._exit_peers.update({"nl": None, "us": None})
            wgui._month_usage.clear()
            wgui._status_snap = None

    def test_clients_status_reads_live_cache_without_dump(self):
        def boom(*a, **k):
            raise AssertionError("wg dump must not run on request path")
        orig = wgui._dump
        wgui._dump = boom
        try:
            with wgui._lock:
                wgui._live[GOOD_PUB] = {
                    "ep": "1.2.3.4:51820", "ip": "10.10.0.2",
                    "hs": int(time.time()) - 10, "rx": 100, "tx": 50,
                }
                wgui._month_usage[GOOD_PUB] = {"rx": 1, "tx": 2}
            registry = [{
                "name": "client1", "ip": "10.10.0.2", "pubkey": GOOD_PUB,
                "enabled": True,
            }]
            with mock.patch.object(wgui, "load_registry", return_value=registry):
                peers = wgui.clients_status()
            self.assertEqual(len(peers), 1)
            self.assertEqual(peers[0]["pubkey"], GOOD_PUB)
            self.assertTrue(peers[0]["online"])
            self.assertEqual(peers[0]["mrx"], 1)
        finally:
            wgui._dump = orig

    def test_dump_uses_awg_for_amneziawg_ifaces(self):
        done = mock.Mock(returncode=0, stdout="line\n", stderr="")
        with mock.patch.object(wgui, "AWG_IFACES", {"wg-do"}), \
             mock.patch.object(wgui.subprocess, "run", return_value=done) as run:
            wgui._dump("wg-do")
            wgui._dump("wg-cl")
        self.assertEqual(run.call_args_list[0].args[0][2], "/usr/bin/awg")
        self.assertEqual(run.call_args_list[1].args[0][2], "/usr/bin/wg")

    def test_status_serves_snapshot(self):
        snap = {"now": int(time.time()), "tunnel": {"state": "up"}, "host": None,
                "rud": False, "peers": [], "thr": {"series": [], "cur": {"down": 0, "up": 0}}}
        with wgui._lock:
            wgui._status_snap = snap
        out = wgui.status()
        self.assertEqual(out["tunnel"]["state"], "up")
        self.assertIsNot(out, snap)  # return a copy

    def test_refresh_status_cache_builds_snap(self):
        with wgui._lock:
            wgui._live.clear()
            wgui._exit_peers["nl"] = {"age": 1, "up": True}
            wgui._egress["nl"].update(ok=True, seen="9.9.9.9", at=int(time.time()))
        with mock.patch.object(wgui, "load_registry", return_value=[]):
            wgui.refresh_status_cache()
        with wgui._lock:
            self.assertIsNotNone(wgui._status_snap)
            self.assertEqual(wgui._status_snap["tunnel"]["state"], "up")
            self.assertIn("sampler", wgui._status_snap)
            self.assertIn("exit_policy", wgui._status_snap)


class TestAuditRotate(unittest.TestCase):
    def test_audit_tail_reads_last_lines_only(self):
        saved = wgui.AUDIT_LOG
        path = os.path.join(TMP, "audit.log")
        wgui.AUDIT_LOG = path
        try:
            with open(path, "w") as f:
                for i in range(100):
                    f.write(json.dumps({"ts": i, "op": "x", "detail": str(i)}) + "\n")
            ev = wgui.audit_tail(5)
            self.assertEqual(len(ev), 5)
            self.assertEqual(ev[0]["detail"], "99")  # newest first
            self.assertEqual(ev[-1]["detail"], "95")
        finally:
            wgui.AUDIT_LOG = saved

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="audit-", dir=TMP)
        self.saved = (wgadmin.AUDIT_DIR, wgadmin.LEGACY_AUDIT, wgadmin.AUDIT_MAX_BYTES)
        wgadmin.AUDIT_DIR = self.dir
        wgadmin.LEGACY_AUDIT = os.path.join(TMP, "no-legacy.log")

    def tearDown(self):
        wgadmin.AUDIT_DIR, wgadmin.LEGACY_AUDIT, wgadmin.AUDIT_MAX_BYTES = self.saved

    def _path(self):
        return os.path.join(self.dir, "audit.log")

    def test_audit_rotate_trims(self):
        wgadmin.AUDIT_MAX_BYTES = 200
        for i in range(50):
            wgadmin.audit("op", "detail-%d" % i)
        self.assertTrue(os.path.getsize(self._path()) <= wgadmin.AUDIT_MAX_BYTES + 500)
        with open(self._path()) as f:
            rows = [json.loads(l) for l in f]
        self.assertEqual(rows[-1]["detail"], "detail-49")

    def test_audit_refuses_symlinked_log(self):
        victim = os.path.join(TMP, "victim.txt")
        with open(victim, "w") as f:
            f.write("keep")
        os.chmod(victim, 0o600)
        os.symlink(victim, self._path())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            wgadmin.audit("op", "x")
        self.assertIn("audit write failed", err.getvalue())
        with open(victim) as f:
            self.assertEqual(f.read(), "keep")
        self.assertEqual(os.stat(victim).st_mode & 0o777, 0o600)

    def test_audit_refuses_group_writable_dir(self):
        os.chmod(self.dir, 0o770)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            wgadmin.audit("op", "x")
        self.assertIn("audit write failed", err.getvalue())
        self.assertFalse(os.path.exists(self._path()))

    def test_audit_carries_over_legacy_log(self):
        legacy = os.path.join(TMP, "legacy-audit.log")
        with open(legacy, "w") as f:
            f.write(json.dumps({"ts": 1, "op": "old", "detail": ""}) + "\n")
        wgadmin.LEGACY_AUDIT = legacy
        wgadmin.audit("new", "")
        with open(self._path()) as f:
            ops = [json.loads(l)["op"] for l in f]
        self.assertEqual(ops, ["old", "new"])
        self.assertEqual(os.stat(self._path()).st_mode & 0o777, 0o640)


class TestHealthHandler(unittest.TestCase):
    def test_healthz_route_unauthenticated(self):
        """GET /healthz must answer without a session cookie."""
        class Fake(wgui.H):
            def __init__(self):
                self.path = "/healthz"
                self.command = "GET"
                self.client_address = ("127.0.0.1", 1)
                self.headers = {}
                self._code = None
                self._body = b""
                self._headers_out = {}
            def send_response(self, code):
                self._code = code
            def send_header(self, k, v):
                self._headers_out[k] = v
            def end_headers(self):
                pass
            def wfile_write(self, b):
                self._body += b
        # BaseHTTPRequestHandler writes via self.wfile — stub a tiny file-like
        class W:
            def __init__(self, h): self.h = h
            def write(self, b): self.h._body += b
        h = Fake()
        h.wfile = W(h)
        h.do_GET()
        self.assertEqual(h._code, 200)
        obj = json.loads(h._body.decode())
        self.assertTrue(obj["ok"])
        self.assertIn("sampler", obj)


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
