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

SPLIT_RULE = "-A PREROUTING -s 10.10.0.0/24 -m set --match-set ru-direct dst -j MARK --set-xmark 0x64/0xffffffff"


def mangle_mark(rules, src, iif, ru_dst):
    """Tiny netfilter model of mangle/PREROUTING MARK rules (-S form); returns final mark."""
    mark = 0
    for rule in rules:
        t = rule.split()
        i, ok, new = 2, True, None
        while i < len(t):
            if t[i] == "-s":
                net, _, bits = t[i + 1].partition("/")
                bits = int(bits or 32)
                as_int = lambda a: int.from_bytes(bytes(map(int, a.split("."))), "big")
                maskv = (0xffffffff << (32 - bits)) & 0xffffffff
                ok &= (as_int(src) & maskv) == (as_int(net) & maskv)
                i += 2
            elif t[i] == "-i":
                ok &= iif == t[i + 1]; i += 2
            elif t[i:i + 3] == ["-m", "mark", "--mark"]:
                ok &= mark == int(t[i + 3], 16); i += 4
            elif t[i:i + 3] == ["-m", "set", "--match-set"]:
                ok &= ru_dst; i += 5
            elif t[i:i + 3] == ["-m", "comment", "--comment"]:
                i += 4
            elif t[i] == "-j":
                i += 2
            elif t[i] in ("--set-xmark", "--set-mark"):
                new = int(t[i + 1].split("/")[0], 16); i += 2
            else:
                raise AssertionError("unmodeled token %r in %r" % (t[i], rule))
        if ok and new is not None:
            mark = new
    return mark


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
        table_alias=None,
        registry_mode="json",
    ):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            bindir = root / "bin"
            bindir.mkdir()
            registry = root / "clients.json"
            if registry_mode == "json":
                registry.write_text(json.dumps(clients))
            elif registry_mode == "raw":
                registry.write_text(clients)
            elif registry_mode == "directory":
                registry.mkdir()
            elif registry_mode != "missing":
                raise AssertionError("unknown registry mode")
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
                    if args in (["rule", "show"], ["-N", "rule", "show"]):
                        count = int(rule_show_count.read_text()) + 1
                        rule_show_count.write_text(str(count))
                        if "rule_inspect" in failures or ("rule_verify" in failures and count >= 2):
                            sys.exit(1)
                        rules = policy.read_text()
                        alias = os.environ["FAKE_TABLE_ALIAS"]
                        if args[0] == "-N" and alias:
                            rendered = []
                            for line in rules.splitlines():
                                tokens = line.split()
                                for i, token in enumerate(tokens[:-1]):
                                    if token in ("lookup", "table") and tokens[i + 1] == alias:
                                        tokens[i + 1] = "65"
                                rendered.append(" ".join(tokens))
                            rules = "".join(f"{line}\n" for line in rendered)
                        sys.stdout.write(rules)
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

                    # Rows: ip|comment|mark[|legacy]. Legacy rows model the pre-guard
                    # rule form (no iif / mark==0 match) left over from older releases.
                    def parse(row):
                        parts = row.split("|")
                        return parts[0], parts[1], parts[2], len(parts) > 3 and parts[3] == "legacy"

                    if args == ["-t", "mangle", "-L", "PREROUTING", "-n", "-v", "--line-numbers"]:
                        for number, row in enumerate(lines(marks), 1):
                            ip, comment, mark, legacy = parse(row)
                            match = "" if legacy else "mark match 0x0 "
                            print(f"{number} 0 0 MARK all -- wg-cl * {ip}/32 0.0.0.0/0 {match}/* {comment} */ MARK set {mark}")
                        sys.exit(0)
                    if args == ["-t", "mangle", "-S", "PREROUTING"]:
                        if "mark_inspect" in failures:
                            sys.exit(1)
                        for row in lines(marks):
                            ip, comment, mark, legacy = parse(row)
                            if os.environ["FAKE_QUOTE_COMMENTS"] == "1":
                                comment = f'"{comment}"'
                            guard = "" if legacy else "-i wg-cl "
                            match = "" if legacy else "-m mark --mark 0x0 "
                            print(f"-A PREROUTING {guard}-s {ip}/32 {match}-m comment --comment {comment} -j MARK --set-xmark {mark}/0xffffffff")
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
                    ) and len(args) == 20:
                        op = args[2]
                        expected = ["-i", "wg-cl", "-s", args[7], "-m", "mark", "--mark", "0",
                                    "-m", "comment", "--comment", "wgui-exit-us", "-j", "MARK", "--set-mark", "0x65"]
                        if args[4:] != expected or not args[7].endswith("/32"):
                            sys.exit(64)
                        row = f"{args[7][:-3]}|wgui-exit-us|0x65"
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
                FAKE_TABLE_ALIAS=table_alias or "",
            )
            result = subprocess.run(
                ["bash", str(SCRIPT), "sync"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            rendered = subprocess.run(
                [str(bindir / "iptables"), "-t", "mangle", "-S", "PREROUTING"],
                env=dict(env, FAKE_FAILURES=""), capture_output=True, text=True,
            ).stdout.splitlines()
            return result, {
                "mangle": rendered,
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

    def test_invalid_registry_fails_before_mark_mutation(self):
        cases = (
            ("missing", [], "missing"),
            ("raw", "{", "malformed"),
            ("json", {"ip": "10.10.0.2"}, "non-list"),
            ("json", ["not-a-record"], "malformed-record"),
            ("json", [{"ip": "10.10.0.2", "exit": "ca"}], "invalid-exit"),
            ("json", [{"exit": "us", "enabled": True}], "missing-us-ip"),
            ("json", [{"ip": "192.0.2.2", "exit": "us", "enabled": True}], "invalid-us-ip"),
            ("directory", [], "directory"),
        )
        original = ("10.10.0.99", COMMENT, MARK)
        for mode, clients, label in cases:
            with self.subTest(case=label):
                result, state = self.run_sync(
                    clients,
                    iface_up=True,
                    initial_marks=(original,),
                    registry_mode=mode,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("client registry", result.stderr)
                self.assertEqual(state["marks"], [original])
                self.assertEqual(state["policy"], [])
                self.assertEqual(state["route"], "")
                self.assertEqual(state["forward"], [])
                self.assertEqual(state["nat"], [])

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

    def test_legacy_us_client_without_enabled_is_active(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us"}],
            iface_up=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["marks"], [("10.10.0.2", COMMENT, MARK)])

    def test_disabled_us_client_does_not_require_ip_or_mark(self):
        result, state = self.run_sync(
            [{"exit": "us", "enabled": False}],
            iface_up=False,
            initial_marks=("10.10.0.99",),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["marks"], [])

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

    def test_restricted_source_policy_rule_does_not_suppress_global_rule(self):
        restricted = "1100: from 10.10.0.99 fwmark 0x65 lookup 65"
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_policy=(restricted,),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["policy"], [restricted, CORRECT_POLICY])

    def test_interface_selector_policy_rule_does_not_suppress_global_rule(self):
        restricted = "1100: from all iif wg-cl fwmark 0x65 lookup 65"
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_policy=(restricted,),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["policy"], [restricted, CORRECT_POLICY])

    def test_numeric_rule_output_recognizes_named_table_alias(self):
        named = "1100: from all fwmark 0x65 lookup cascade-us"
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_policy=(named,),
            table_alias="cascade-us",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["policy"], [named])

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

    def test_us_mark_rule_is_guarded_and_client_scoped(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        (rule,) = state["mangle"]
        self.assertIn("-i wg-cl ", rule)
        self.assertIn("-m mark --mark 0x0 ", rule)

    def test_ru_direct_wins_in_either_rule_order(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        us_rules = state["mangle"]
        for label, chain in (("split first", [SPLIT_RULE] + us_rules),
                             ("us first", us_rules + [SPLIT_RULE])):
            with self.subTest(order=label):
                self.assertEqual(mangle_mark(chain, "10.10.0.2", "wg-cl", ru_dst=True), 0x64)
                self.assertEqual(mangle_mark(chain, "10.10.0.2", "wg-cl", ru_dst=False), 0x65)
                self.assertEqual(mangle_mark(chain, "10.10.0.3", "wg-cl", ru_dst=False), 0)
                self.assertEqual(mangle_mark(chain, "10.10.0.2", "ens3", ru_dst=False), 0)

    def test_legacy_unguarded_mark_is_replaced_on_sync(self):
        legacy = ("10.10.0.2", COMMENT, MARK, "legacy")
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_marks=(legacy,),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["marks"], [("10.10.0.2", COMMENT, MARK)])
        self.assertTrue(all("--mark 0x0" in rule for rule in state["mangle"]))


if __name__ == "__main__":
    unittest.main()
