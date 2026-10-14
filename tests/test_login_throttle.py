import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
os.environ.setdefault("WGUI_SESSION_SECRET", "login-throttle-test-secret-0123456789ab")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-login-throttle.gen"))

import auth  # noqa: E402

spec = importlib.util.spec_from_file_location("wgui_login_throttle", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)


class TestLoginState(unittest.TestCase):
    IP = "203.0.113.45"

    def setUp(self):
        with auth._fails_lock:
            auth._fails.clear()

    def tearDown(self):
        with auth._fails_lock:
            auth._fails.clear()

    def test_counts_down_attempts(self):
        self.assertEqual(auth.login_state(self.IP), (auth.LOGIN_MAX, 0))
        with auth._fails_lock:
            auth._fails[self.IP] = [1000.0, 1010.0]
        self.assertEqual(auth.login_state(self.IP, now=1020.0), (auth.LOGIN_MAX - 2, 0))

    def test_retry_is_when_the_oldest_blocking_failure_leaves_the_window(self):
        fails = [1000.0, 1100.0, 1200.0, 1300.0, 1400.0]
        with auth._fails_lock:
            auth._fails[self.IP] = list(fails)
        left, retry = auth.login_state(self.IP, now=1500.0)
        self.assertEqual(left, 0)
        self.assertEqual(retry, int(1000 + auth.LOGIN_WIN - 1500))
        # one more failure than the limit: the block lasts until the 2nd oldest expires
        with auth._fails_lock:
            auth._fails[self.IP] = fails + [1450.0]
        self.assertEqual(auth.login_state(self.IP, now=1500.0)[1], int(1100 + auth.LOGIN_WIN - 1500))

    def test_expired_failures_do_not_count(self):
        with auth._fails_lock:
            auth._fails[self.IP] = [0.0] * auth.LOGIN_MAX
        self.assertEqual(auth.login_state(self.IP, now=auth.LOGIN_WIN + 1.0), (auth.LOGIN_MAX, 0))

    def test_retry_never_rounds_to_zero_while_blocked(self):
        with auth._fails_lock:
            auth._fails[self.IP] = [1000.0] * auth.LOGIN_MAX
        self.assertEqual(auth.login_state(self.IP, now=1000.0 + auth.LOGIN_WIN - 0.2)[1], 1)


class TestLoginRedirects(unittest.TestCase):
    IP = "198.51.100.7"

    def setUp(self):
        with auth._fails_lock:
            auth._fails.clear()

    def tearDown(self):
        with auth._fails_lock:
            auth._fails.clear()

    def post(self, body=b"username=admin&password=nope"):
        import io

        class Fake(wgui.H):
            def __init__(self):
                self.path = "/login"
                self.command = "POST"
                self.client_address = (TestLoginRedirects.IP, 1)
                self.headers = {"Content-Length": str(len(body))}
                self.rfile = io.BytesIO(body)
                self._code = None
                self._hdrs = {}

            def send_response(self, code):
                self._code = code

            def send_header(self, key, value):
                self._hdrs[key] = value

            def end_headers(self):
                pass

        class Writer:
            def write(self, data):
                pass

        h = Fake()
        h.wfile = Writer()
        with mock.patch.object(wgui, "creds_ok", return_value=False), \
             mock.patch.object(wgui.time, "sleep"):
            h.do_POST()
        return h._code, h._hdrs.get("Location")

    def test_wrong_password_reports_attempts_left(self):
        code, loc = self.post()
        self.assertEqual(code, 303)
        self.assertEqual(loc, "/login?e=1&left=%d" % (auth.LOGIN_MAX - 1))

    def test_last_failure_and_blocked_requests_report_retry(self):
        for _ in range(auth.LOGIN_MAX - 1):
            self.post()
        code, loc = self.post()
        self.assertTrue(loc.startswith("/login?e=2&retry="), loc)
        code, loc = self.post()          # throttled before the password is checked
        self.assertTrue(loc.startswith("/login?e=2&retry="), loc)
        retry = int(loc.rsplit("=", 1)[1])
        self.assertTrue(0 < retry <= auth.LOGIN_WIN)


LOGIN_JS = (APP / "login.js").read_text()
HELPERS = LOGIN_JS[LOGIN_JS.index("function plural"):LOGIN_JS.index("if(typeof module")]


@unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
class TestLoginMessages(unittest.TestCase):
    def messages(self, cases):
        script = HELPERS + "\nconsole.log(JSON.stringify(%s.map(c=>loginMessage(c[0],c[1]))));" % json.dumps(cases)
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_russian_plurals_and_english(self):
        got = self.messages([
            ["?e=1&left=1", True], ["?e=1&left=3", True], ["?e=1&left=0", True], ["?e=1&left=11", True],
            ["?e=2&retry=61", True], ["?e=2&retry=300", True], ["?e=2&retry=1260", True],
            ["?e=1&left=1", False], ["?e=1&left=4", False], ["?e=2&retry=30", False],
            ["?e=1", True], ["?e=2", False], ["?e=1&left=abc", True], ["", True],
        ])
        self.assertEqual(got, [
            "Неверный логин или пароль · осталось 1 попытка",
            "Неверный логин или пароль · осталось 3 попытки",
            "Неверный логин или пароль · осталось 0 попыток",
            "Неверный логин или пароль · осталось 11 попыток",
            "Слишком много попыток. Повторите через 2 минуты",
            "Слишком много попыток. Повторите через 5 минут",
            "Слишком много попыток. Повторите через 21 минуту",
            "Invalid username or password · 1 attempt left",
            "Invalid username or password · 4 attempts left",
            "Too many attempts. Try again in 1 minute",
            "Неверный логин или пароль",
            "Too many attempts — try again in a few minutes",
            "Неверный логин или пароль",
            "",
        ])


if __name__ == "__main__":
    unittest.main()
