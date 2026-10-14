#!/usr/bin/env python3
"""deploy/remote-activate.sh against stubbed systemctl/curl/visudo/flock/chown.

The stubs answer based on which release is live (a VERSION file in the fake
/opt/wg-ui), so "new build is broken, old build is fine" plays out like it would
on the server: the rollback must put the old release back and re-check it.
Run from the repo root:  python3 -m unittest discover -s tests
"""
import os, pathlib, shutil, stat, subprocess, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ACTIVATE = ROOT / "deploy" / "remote-activate.sh"

STUBS = {
    "systemctl": r'''#!/bin/bash
echo "systemctl $*" >> "$CTL/calls"
ver=$(cat "$DEPLOY_PREFIX/opt/wg-ui/VERSION" 2>/dev/null || echo none)
case "$1" in
  is-active) [ -f "$CTL/inactive.$ver" ] && exit 3; exit 0 ;;
  start)     [ -f "$CTL/start-fails.$ver" ] && exit 1; exit 0 ;;
  *)         exit 0 ;;
esac
''',
    "curl": r'''#!/bin/bash
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w|--max-time) shift 2 ;;
    -*) shift ;;
    *)  url="$1"; shift ;;
  esac
done
path="${url#*://*/}"
ver=$(cat "$DEPLOY_PREFIX/opt/wg-ui/VERSION" 2>/dev/null || echo none)
f="$CTL/resp.$ver.$path"; [ -f "$f" ] || f="$CTL/resp.default.$path"
read -r code ex body < "$f"
[ -n "$out" ] && printf '%s' "$body" > "$out"
echo "curl /$path ($ver) -> $code/$ex" >> "$CTL/calls"
[ "$ex" != 0 ] && exit "$ex"
printf '%s' "$code"
''',
    "visudo": '#!/bin/bash\necho "visudo $*" >> "$CTL/calls"\n[ -f "$CTL/visudo-rejects" ] && exit 1; exit 0\n',
    "flock": '#!/bin/bash\n[ -f "$CTL/lock-busy" ] && exit 1; exit 0\n',
    "chown": '#!/bin/bash\nexit 0\n',
}


class RemoteActivate(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="wgui-deploy-"))
        self.prefix = self.tmp / "root"
        self.ctl = self.tmp / "ctl"
        self.stubs = self.tmp / "stubs"
        for d in (self.prefix, self.ctl, self.stubs):
            d.mkdir()
        for name, body in STUBS.items():
            p = self.stubs / name
            p.write_text(body)
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
        self.respond("default", "login", 200, 0, "ok")
        self.respond("default", "readyz", 200, 0, '{"ready": true}')
        self.respond("default", "healthz", 200, 0, '{"ok": true}')

        live = self.prefix / "opt" / "wg-ui"
        live.mkdir(parents=True)
        (live / "VERSION").write_text("old")
        (live / "wg-ui.py").write_text("# old\n")
        self.stage = self.prefix / "opt" / "wg-ui.staging.test"
        (self.stage / "app").mkdir(parents=True)
        (self.stage / "app" / "VERSION").write_text("new")
        (self.stage / "app" / "wg-ui.py").write_text("# new\n")
        (self.stage / "deploy").mkdir()
        (self.stage / "deploy" / "sudoers.wgui").write_text("new sudoers\n")
        (self.stage / "deploy" / "wg-ui.service").write_text("new unit\n")

        self.sudoers = self.prefix / "etc" / "sudoers.d" / "wg-ui"
        self.sudoers.parent.mkdir(parents=True)
        self.sudoers.write_text("old sudoers\n")
        self.unit = self.prefix / "etc" / "systemd" / "system" / "wg-ui.service"
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text("old unit\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def respond(self, version, path, code, exit_status, body):
        (self.ctl / ("resp.%s.%s" % (version, path))).write_text(
            "%s %s %s\n" % (code, exit_status, body))

    def run_activate(self, **env_extra):
        env = dict(os.environ,
                   PATH="%s:%s" % (self.stubs, os.environ["PATH"]),
                   CTL=str(self.ctl),
                   DEPLOY_PREFIX=str(self.prefix),
                   DEPLOY_READY_TIMEOUT="1",
                   DEPLOY_POLL_INTERVAL="0.1",
                   **env_extra)
        return subprocess.run(["bash", str(ACTIVATE), str(self.stage)],
                              env=env, capture_output=True, text=True, timeout=60)

    def live_version(self):
        return (self.prefix / "opt" / "wg-ui" / "VERSION").read_text()

    def calls(self):
        p = self.ctl / "calls"
        return p.read_text() if p.exists() else ""

    def assert_rolled_back(self, r):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.live_version(), "old")
        self.assertEqual((self.prefix / "opt" / "wg-ui.failed" / "VERSION").read_text(), "new")
        self.assertEqual(self.sudoers.read_text(), "old sudoers\n")
        self.assertEqual(self.unit.read_text(), "old unit\n")
        self.assertFalse(self.stage.exists())

    # ------------------------------------------------------------ success
    def test_happy_path_swaps_code_and_config(self):
        r = self.run_activate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.live_version(), "new")
        self.assertEqual((self.prefix / "opt" / "wg-ui.prev" / "VERSION").read_text(), "old")
        self.assertEqual(self.sudoers.read_text(), "new sudoers\n")
        self.assertEqual(oct(self.sudoers.stat().st_mode & 0o777), "0o440")
        self.assertEqual(self.unit.read_text(), "new unit\n")
        self.assertIn("systemctl daemon-reload", self.calls())
        self.assertIn("visudo -cf", self.calls())
        self.assertFalse(self.stage.exists())
        backups = list((self.prefix / "var" / "backups" / "wg-ui-deploy").iterdir())
        self.assertEqual((backups[0] / "sudoers").read_text(), "old sudoers\n")
        self.assertEqual((backups[0] / "units" / "wg-ui.service").read_text(), "old unit\n")

    def test_old_build_without_readyz_falls_back_to_healthz(self):
        self.respond("new", "readyz", 404, 0, "not found")
        r = self.run_activate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("curl /healthz (new) -> 200/0", self.calls())

    def test_unchanged_config_is_not_reinstalled(self):
        self.sudoers.write_text("new sudoers\n")
        self.unit.write_text("new unit\n")
        r = self.run_activate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("visudo", self.calls())
        self.assertNotIn("daemon-reload", self.calls())

    def test_skip_config_leaves_sudoers_and_units(self):
        r = self.run_activate(DEPLOY_SKIP_CONFIG="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.live_version(), "new")
        self.assertEqual(self.sudoers.read_text(), "old sudoers\n")
        self.assertEqual(self.unit.read_text(), "old unit\n")

    # ------------------------------------------------------------ rollback
    def test_start_failure_rolls_back(self):
        (self.ctl / "start-fails.new").touch()
        self.assert_rolled_back(self.run_activate())

    def test_inactive_unit_rolls_back(self):
        (self.ctl / "inactive.new").touch()
        self.assert_rolled_back(self.run_activate())

    def test_http_500_rolls_back(self):
        self.respond("new", "readyz", 500, 0, "boom")
        self.assert_rolled_back(self.run_activate())

    def test_not_ready_503_rolls_back(self):
        self.respond("new", "readyz", 503, 0, '{"ready": false}')
        self.assert_rolled_back(self.run_activate())

    def test_login_500_rolls_back(self):
        self.respond("new", "login", 500, 0, "boom")
        self.assert_rolled_back(self.run_activate())

    def test_curl_transport_error_rolls_back(self):
        self.respond("new", "login", "000", 7, "")
        self.assert_rolled_back(self.run_activate())

    def test_healthz_fallback_not_ok_rolls_back(self):
        self.respond("new", "readyz", 404, 0, "not found")
        self.respond("new", "healthz", 200, 0, '{"ok": false}')
        self.assert_rolled_back(self.run_activate())

    def test_failed_rollback_reports_exit_2(self):
        (self.ctl / "start-fails.new").touch()
        (self.ctl / "start-fails.old").touch()
        r = self.run_activate()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("ROLLBACK FAILED", r.stderr)
        self.assertEqual(self.live_version(), "old")

    # ------------------------------------------------------------ refusals
    def test_visudo_rejection_changes_nothing(self):
        (self.ctl / "visudo-rejects").touch()
        r = self.run_activate()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.live_version(), "old")
        self.assertEqual(self.sudoers.read_text(), "old sudoers\n")
        self.assertEqual(self.unit.read_text(), "old unit\n")
        self.assertNotIn("systemctl stop", self.calls())

    def test_busy_lock_refuses(self):
        (self.ctl / "lock-busy").touch()
        r = self.run_activate()
        self.assertEqual(r.returncode, 75, r.stdout + r.stderr)
        self.assertEqual(self.live_version(), "old")
        self.assertEqual(self.calls(), "")

    def test_scripts_parse(self):
        for script in (ACTIVATE, ROOT / "deploy.sh"):
            r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
