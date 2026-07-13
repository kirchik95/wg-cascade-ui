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
COMMENT = "wgui-exit-us"
MARK = "0x65"
CORRECT_POLICY = "1100: from all fwmark 0x65 lookup 65"


class TestExitRoute(unittest.TestCase):
    def _executable(self, path, body):
        path.write_text(textwrap.dedent(body).lstrip())
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_sync(
        self,
        clients,
        iface_up,
        initial_marks=(),
        initial_policy=(),
        initial_route=None,
        failures=(),
        silent_applies=(),
        quote_comments=False,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            bindir = root / "bin"
            bindir.mkdir()
            registry = root / "clients.json"
            registry.write_text(json.dumps(clients))
            marks = root / "marks"
            mark_rows = []
            for mark in initial_marks:
                if isinstance(mark, str):
                    mark = (mark, COMMENT, MARK)
                mark_rows.append("|".join(mark))
            marks.write_text("".join(f"{row}\n" for row in mark_rows))
            policy = root / "policy"
            policy.write_text("".join(f"{rule}\n" for rule in initial_policy))
            route = root / "route"
            route.write_text("" if initial_route is None else "|".join(initial_route) + "\n")
            forward = root / "forward"
            forward.write_text("")
            nat = root / "nat"
            nat.write_text("")
            rule_show_count = root / "rule-show-count"
            rule_show_count.write_text("0")
            self._executable(
                bindir / "ip",
                r'''
                    #!/usr/bin/env python3
                    import os
                    import pathlib
                    import sys

                    args = sys.argv[1:]
                    failures = set(filter(None, os.environ["FAKE_FAILURES"].split(",")))
                    silent = set(filter(None, os.environ["FAKE_SILENT_APPLIES"].split(",")))
                    policy = pathlib.Path(os.environ["FAKE_POLICY_STATE"])
                    route = pathlib.Path(os.environ["FAKE_ROUTE_STATE"])
                    rule_show_count = pathlib.Path(os.environ["FAKE_RULE_SHOW_COUNT"])

                    if args == ["link", "show", "wg-us"]:
                        sys.exit(0 if os.environ["FAKE_IFACE_UP"] == "1" else 1)
                    if args in (
                        ["route", "replace", "default", "dev", "wg-us", "table", "65"],
                        ["route", "add", "default", "dev", "wg-us", "table", "65"],
                    ):
                        if "route" in failures:
                            sys.exit(1)
                        if "route" not in silent:
                            route.write_text("wg-us|65\n")
                        sys.exit(0)
                    if args == ["rule", "show"]:
                        count = int(rule_show_count.read_text()) + 1
                        rule_show_count.write_text(str(count))
                        if "rule_inspect" in failures or ("rule_verify" in failures and count >= 2):
                            sys.exit(1)
                        sys.stdout.write(policy.read_text())
                        sys.exit(0)
                    if args == ["rule", "add", "fwmark", "0x65", "lookup", "65", "priority", "1100"]:
                        if "rule" in failures:
                            sys.exit(1)
                        if "rule" not in silent:
                            with policy.open("a") as f:
                                f.write("1100: from all fwmark 0x65 lookup 65\n")
                        sys.exit(0)
                    if args == ["route", "show", "table", "65"]:
                        if "route_inspect" in failures:
                            sys.exit(1)
                        value = route.read_text().strip()
                        if value:
                            iface, table = value.split("|")
                            if table == "65":
                                print(f"default dev {iface}")
                        sys.exit(0)
                    print("unmodeled ip command: " + " ".join(args), file=sys.stderr)
                    sys.exit(64)
                ''',
            )
            self._executable(
                bindir / "iptables",
                r'''
                    #!/usr/bin/env python3
                    import os
                    import pathlib
                    import sys

                    args = sys.argv[1:]
                    failures = set(filter(None, os.environ["FAKE_FAILURES"].split(",")))
                    silent = set(filter(None, os.environ["FAKE_SILENT_APPLIES"].split(",")))
                    marks = pathlib.Path(os.environ["FAKE_MARK_STATE"])
                    forward = pathlib.Path(os.environ["FAKE_FORWARD_STATE"])
                    nat = pathlib.Path(os.environ["FAKE_NAT_STATE"])

                    def lines(path):
                        return [line for line in path.read_text().splitlines() if line]

                    def write_lines(path, values):
                        path.write_text("".join(f"{value}\n" for value in values))

                    if args == ["-t", "mangle", "-L", "PREROUTING", "-n", "-v", "--line-numbers"]:
                        for number, row in enumerate(lines(marks), 1):
                            ip, comment, mark = row.split("|")
                            print(f"{number} 0 0 MARK all -- * * {ip}/32 0.0.0.0/0 /* {comment} */ MARK set {mark}")
                        sys.exit(0)
                    if args == ["-t", "mangle", "-S", "PREROUTING"]:
                        if "mark_inspect" in failures:
                            sys.exit(1)
                        for row in lines(marks):
                            ip, comment, mark = row.split("|")
                            if os.environ["FAKE_QUOTE_COMMENTS"] == "1":
                                comment = f'"{comment}"'
                            print(f"-A PREROUTING -s {ip}/32 -m comment --comment {comment} -j MARK --set-mark {mark}")
                        sys.exit(0)
                    if args[:4] == ["-t", "mangle", "-D", "PREROUTING"] and len(args) == 5:
                        number = int(args[4])
                        values = lines(marks)
                        if 1 <= number <= len(values):
                            del values[number - 1]
                        write_lines(marks, values)
                        sys.exit(0)
                    if args[:4] in (
                        ["-t", "mangle", "-C", "PREROUTING"],
                        ["-t", "mangle", "-A", "PREROUTING"],
                    ) and len(args) == 14:
                        op = args[2]
                        expected = ["-s", args[5], "-m", "comment", "--comment", "wgui-exit-us", "-j", "MARK", "--set-mark", "0x65"]
                        if args[4:] != expected or not args[5].endswith("/32"):
                            sys.exit(64)
                        row = f"{args[5][:-3]}|wgui-exit-us|0x65"
                        if op == "-C":
                            sys.exit(0 if row in lines(marks) else 1)
                        if "mark" in failures:
                            sys.exit(1)
                        if "mark" not in silent:
                            with marks.open("a") as f:
                                f.write(row + "\n")
                        sys.exit(0)

                    forward_out_check = ["-C", "FORWARD", "-i", "wg-cl", "-o", "wg-us", "-j", "ACCEPT"]
                    forward_out_add = ["-I", "FORWARD", "1", "-i", "wg-cl", "-o", "wg-us", "-j", "ACCEPT"]
                    forward_return_check = ["-C", "FORWARD", "-i", "wg-us", "-o", "wg-cl", "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"]
                    forward_return_add = ["-I", "FORWARD", "1", "-i", "wg-us", "-o", "wg-cl", "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"]
                    if args in (forward_out_check, forward_return_check):
                        key = "out" if args == forward_out_check else "return"
                        sys.exit(0 if key in lines(forward) else 1)
                    if args in (forward_out_add, forward_return_add):
                        if "forward" in failures:
                            sys.exit(1)
                        key = "out" if args == forward_out_add else "return"
                        if "forward" not in silent and key not in lines(forward):
                            with forward.open("a") as f:
                                f.write(key + "\n")
                        sys.exit(0)

                    nat_check = ["-t", "nat", "-C", "POSTROUTING", "-o", "wg-us", "-j", "MASQUERADE"]
                    nat_add = ["-t", "nat", "-A", "POSTROUTING", "-o", "wg-us", "-j", "MASQUERADE"]
                    if args == nat_check:
                        sys.exit(0 if "wg-us" in lines(nat) else 1)
                    if args == nat_add:
                        if "nat" in failures:
                            sys.exit(1)
                        if "nat" not in silent and "wg-us" not in lines(nat):
                            with nat.open("a") as f:
                                f.write("wg-us\n")
                        sys.exit(0)
                    print("unmodeled iptables command: " + " ".join(args), file=sys.stderr)
                    sys.exit(64)
                ''',
            )
            self._executable(bindir / "conntrack", "#!/bin/sh\nexit 0\n")
            env = dict(
                os.environ,
                PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                WGUI_CLIENTS=str(registry),
                WGUI_US_IFACE="wg-us",
                FAKE_IFACE_UP="1" if iface_up else "0",
                FAKE_FAILURES=",".join(failures),
                FAKE_SILENT_APPLIES=",".join(silent_applies),
                FAKE_MARK_STATE=str(marks),
                FAKE_POLICY_STATE=str(policy),
                FAKE_ROUTE_STATE=str(route),
                FAKE_FORWARD_STATE=str(forward),
                FAKE_NAT_STATE=str(nat),
                FAKE_RULE_SHOW_COUNT=str(rule_show_count),
                FAKE_QUOTE_COMMENTS="1" if quote_comments else "0",
            )
            result = subprocess.run(
                ["bash", str(SCRIPT), "sync"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result, {
                "marks": [tuple(row.split("|")) for row in marks.read_text().splitlines()],
                "policy": policy.read_text().splitlines(),
                "route": route.read_text().strip(),
                "forward": forward.read_text().splitlines(),
                "nat": nat.read_text().splitlines(),
            }

    def test_us_clients_and_missing_iface_fails(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wg-us is down", result.stderr)

    def test_no_us_clients_and_missing_iface_clears_stale_rules(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "enabled": True}],
            iface_up=False,
            initial_marks=("10.10.0.99",),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["marks"], [])

    def test_no_us_clients_fail_when_mark_rules_cannot_be_inspected(self):
        result, _ = self.run_sync([], iface_up=False, failures=("mark_inspect",))
        self.assertNotEqual(result.returncode, 0)

    def test_route_command_failure_propagates(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            failures=("route",),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_rule_command_failure_propagates(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            failures=("rule",),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_forward_command_failure_propagates(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            failures=("forward",),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_nat_command_failure_propagates(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            failures=("nat",),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_mark_command_failure_propagates(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            failures=("mark",),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_successful_us_sync_verifies_one_mark(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["marks"], [("10.10.0.2", COMMENT, MARK)])
        self.assertEqual(state["policy"], [CORRECT_POLICY])
        self.assertEqual(state["route"], "wg-us|65")
        self.assertEqual(state["forward"], ["out", "return"])
        self.assertEqual(state["nat"], ["wg-us"])
        self.assertIn("synced 1 US client", result.stdout)

    def test_quoted_exact_comment_is_owned(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            quote_comments=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sync_fails_when_applied_mark_is_not_observable(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            silent_applies=("mark",),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state["marks"], [])
        self.assertIn("expected 1 mark rule(s), found 0", result.stderr)

    def test_wrong_table_policy_rule_does_not_suppress_correct_rule(self):
        wrong = "1100: from all fwmark 0x65 lookup 66"
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_policy=(wrong,),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["policy"], [wrong, CORRECT_POLICY])

    def test_wrong_interface_does_not_satisfy_route_verification(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_route=("wg-us-backup", "65"),
            silent_applies=("route",),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("US default route missing", result.stderr)

    def test_extra_comment_is_not_owned_or_deleted(self):
        extra = ("10.10.0.99", "wgui-exit-us-extra", MARK)
        result, state = self.run_sync([], iface_up=False, initial_marks=(extra,))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["marks"], [extra])

    def test_rule_verification_query_failure_propagates(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            failures=("rule_verify",),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_route_verification_query_failure_propagates(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            failures=("route_inspect",),
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
