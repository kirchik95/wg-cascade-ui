import json
import os
import pathlib
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "app" / "exit-route.sh"


class TestExitRoute(unittest.TestCase):
    def _executable(self, path, body):
        path.write_text(textwrap.dedent(body))
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_sync(
        self,
        clients,
        iface_up,
        fail_route=False,
        initial_marks=(),
        drop_mark_apply=False,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            bindir = root / "bin"
            bindir.mkdir()
            registry = root / "clients.json"
            registry.write_text(json.dumps(clients))
            state = root / "marks"
            state.write_text("".join(f"{ip}\n" for ip in initial_marks))
            self._executable(
                bindir / "ip",
                r'''#!/bin/sh
                    if [ "$1 $2" = "link show" ]; then
                        [ "$FAKE_IFACE_UP" = 1 ]
                        exit
                    fi
                    if [ "$1 $2" = "route replace" ] || [ "$1 $2" = "route add" ]; then
                        [ "$FAKE_FAIL_ROUTE" != 1 ]
                        exit
                    fi
                    if [ "$1 $2" = "rule show" ]; then
                        echo "1100: from all fwmark 0x65 lookup 65"
                        exit 0
                    fi
                    if [ "$1 $2" = "route show" ]; then
                        echo "default dev wg-us"
                        exit 0
                    fi
                    exit 0
                ''',
            )
            self._executable(
                bindir / "iptables",
                r'''#!/bin/sh
                    if [ "$1 $2 $3 $4" = "-t mangle -L PREROUTING" ]; then
                        n=1
                        while IFS= read -r ip; do
                            [ -z "$ip" ] || printf '%s 0 0 MARK all -- * * %s/32 0.0.0.0/0 /* wgui-exit-us */ MARK set 0x65\n' "$n" "$ip"
                            n=$((n + 1))
                        done < "$FAKE_MARK_STATE"
                        exit 0
                    fi
                    if [ "$1 $2 $3 $4" = "-t mangle -S PREROUTING" ]; then
                        while IFS= read -r ip; do
                            [ -z "$ip" ] || echo "-A PREROUTING -s $ip/32 -m comment --comment wgui-exit-us -j MARK --set-mark 0x65"
                        done < "$FAKE_MARK_STATE"
                        exit 0
                    fi
                    if [ "$1 $2 $3 $4" = "-t mangle -D PREROUTING" ]; then
                        tmp="$FAKE_MARK_STATE.tmp"
                        awk -v drop="$5" 'NR != drop' "$FAKE_MARK_STATE" > "$tmp"
                        mv "$tmp" "$FAKE_MARK_STATE"
                        exit 0
                    fi
                    if [ "$1" = "-t" ] && [ "$2" = "mangle" ] && { [ "$3" = "-C" ] || [ "$3" = "-A" ]; }; then
                        op="$3"
                        shift 4
                        ip=""
                        while [ "$#" -gt 0 ]; do
                            if [ "$1" = "-s" ]; then
                                ip="${2%/32}"
                                break
                            fi
                            shift
                        done
                        if [ "$op" = "-C" ]; then
                            grep -qx "$ip" "$FAKE_MARK_STATE"
                            exit
                        fi
                        [ "$FAKE_DROP_MARK_APPLY" = 1 ] || echo "$ip" >> "$FAKE_MARK_STATE"
                        exit 0
                    fi
                    exit 0
                ''',
            )
            self._executable(bindir / "conntrack", "#!/bin/sh\nexit 0\n")
            env = dict(
                os.environ,
                PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                WGUI_CLIENTS=str(registry),
                WGUI_US_IFACE="wg-us",
                FAKE_IFACE_UP="1" if iface_up else "0",
                FAKE_FAIL_ROUTE="1" if fail_route else "0",
                FAKE_MARK_STATE=str(state),
                FAKE_DROP_MARK_APPLY="1" if drop_mark_apply else "0",
            )
            result = subprocess.run(
                ["bash", str(SCRIPT), "sync"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result, state.read_text().splitlines()

    def test_us_clients_and_missing_iface_fails(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wg-us is down", result.stderr)

    def test_no_us_clients_and_missing_iface_clears_stale_rules(self):
        result, marks = self.run_sync(
            [{"ip": "10.10.0.2", "enabled": True}],
            iface_up=False,
            initial_marks=("10.10.0.99",),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marks, [])

    def test_route_command_failure_propagates(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            fail_route=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_successful_us_sync_verifies_one_mark(self):
        result, marks = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marks, ["10.10.0.2"])
        self.assertIn("synced 1 US client", result.stdout)

    def test_sync_fails_when_applied_mark_is_not_observable(self):
        result, marks = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            drop_mark_apply=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marks, [])
        self.assertIn("expected 1 mark rule(s), found 0", result.stderr)


if __name__ == "__main__":
    unittest.main()
