import json
import os
import pathlib
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "app" / "split-server.sh"
SPLIT_RULE = "1000: from all fwmark 0x64 lookup main"

# One JSON state file models ipset sets, iptables chains and the RPDB.
FAKES = {
    "ipset": r'''
        #!/usr/bin/env python3
        import json, os, sys
        path = os.environ["FAKE_STATE"]
        st = json.load(open(path))
        fail = set(filter(None, os.environ["FAKE_FAILURES"].split(",")))
        args = sys.argv[1:]
        sets = st["sets"]
        def save():
            json.dump(st, open(path, "w"))
        st["ops"].append(" ".join(args))
        if args[0] == "create":
            if args[1] in sets and "-exist" not in args:
                sys.exit(1)
            sets.setdefault(args[1], [])
        elif args[0] == "destroy":
            if args[1] not in sets:
                sys.exit(1)
            del sets[args[1]]
        elif args[0] == "restore":
            if "restore" in fail:
                sys.exit(1)
            for line in sys.stdin.read().splitlines():
                op, name, entry = line.split()[:3]
                assert op == "add", line
                if entry not in sets[name]:
                    sets[name].append(entry)
        elif args[0] == "swap":
            if "swap" in fail:
                sys.exit(1)
            sets[args[1]], sets[args[2]] = sets[args[2]], sets[args[1]]
        elif args[0] == "save":
            if args[1] not in sets:
                sys.exit(1)
            print("create %s hash:net family inet" % args[1])
            for entry in sets[args[1]]:
                print("add %s %s" % (args[1], entry))
        elif args[:2] == ["list", "-n"]:
            sys.exit(0 if args[2] in sets else 1)
        else:
            print("unmodeled ipset: " + " ".join(args), file=sys.stderr)
            sys.exit(64)
        save()
    ''',
    "iptables": r'''
        #!/usr/bin/env python3
        import json, os, sys
        path = os.environ["FAKE_STATE"]
        st = json.load(open(path))
        fail = set(filter(None, os.environ["FAKE_FAILURES"].split(",")))
        silent = set(filter(None, os.environ["FAKE_SILENT"].split(",")))
        args = sys.argv[1:]
        table = "filter"
        if args[0] == "-t":
            table, args = args[1], args[2:]
        op, chain, rest = args[0], args[1], args[2:]
        key = table + ":" + chain
        rules = st["chains"].setdefault(key, [])
        # Render like real iptables -S: -o precedes -m set.
        def render(spec):
            s = " ".join(spec)
            return s.replace("-m set --match-set ru-direct dst -o ens3", "-o ens3 -m set --match-set ru-direct dst")
        if op == "-S":
            print("-P %s ACCEPT" % chain)
            for rule in rules:
                print("-A %s %s" % (chain, rule))
            sys.exit(0)
        pos = None
        if op == "-I":
            pos, rest = int(rest[0]), rest[1:]
        rule = render(rest)
        kind = {"mangle": "mangle", "nat": "nat"}.get(table, "forward")
        if op == "-C":
            sys.exit(0 if rule in rules else 1)
        if op in ("-A", "-I"):
            if kind + "_add" in fail:
                sys.exit(1)
            if kind + "_add" not in silent:
                rules.insert(pos - 1 if pos else len(rules), rule)
        elif op == "-D":
            if kind + "_del" in silent:
                sys.exit(0)
            if rule not in rules:
                sys.exit(1)
            rules.remove(rule)
        else:
            sys.exit(64)
        json.dump(st, open(path, "w"))
    ''',
    "ip": r'''
        #!/usr/bin/env python3
        import json, os, sys
        path = os.environ["FAKE_STATE"]
        st = json.load(open(path))
        fail = set(filter(None, os.environ["FAKE_FAILURES"].split(",")))
        silent = set(filter(None, os.environ["FAKE_SILENT"].split(",")))
        args = sys.argv[1:]
        if args == ["-N", "rule", "show"]:
            if "rule_inspect" in fail:
                sys.exit(1)
            for rule in st["rules"]:
                print(rule.replace("lookup main", "lookup 254"))
            sys.exit(0)
        if args == ["rule", "add", "fwmark", "0x64", "lookup", "main", "priority", "1000"]:
            if "rule_add" in fail:
                sys.exit(1)
            if "rule_add" not in silent:
                st["rules"].append("1000: from all fwmark 0x64 lookup main")
        elif args == ["rule", "del", "fwmark", "0x64", "lookup", "main", "priority", "1000"]:
            if "rule_del" in silent:
                sys.exit(0)
            match = [r for r in st["rules"] if r.startswith("1000: ") and "fwmark 0x64 lookup main" in r]
            if not match:
                sys.exit(2)
            st["rules"].remove(match[0])
        else:
            print("unmodeled ip: " + " ".join(args), file=sys.stderr)
            sys.exit(64)
        json.dump(st, open(path, "w"))
    ''',
}

KILL_SWITCH = "-s 10.10.0.0/24 ! -d 10.10.0.0/24 ! -o wg-do -j DROP"


class TestSplitServer(unittest.TestCase):
    def run_split(self, command, state=None, direct=("5.0.0.0/8", "77.88.0.0/18"),
                  sets=None, rules=(), chains=None, failures=(), silent=(),
                  env_text="WGUI_WAN_IFACE=ens3\n"):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            bindir = root / "bin"
            bindir.mkdir()
            for name, body in FAKES.items():
                path = bindir / name
                path.write_text(textwrap.dedent(body).lstrip())
                path.chmod(path.stat().st_mode | stat.S_IXUSR)
            fake_state = root / "fake.json"
            fake_state.write_text(json.dumps({
                "sets": dict(sets or {}),
                "ops": [],
                "chains": dict(chains or {"filter:FORWARD": [KILL_SWITCH]}),
                "rules": list(rules),
            }))
            env_file = root / "wg-ui.env"
            env_file.write_text(env_text)
            direct_list = root / "split-direct.txt"
            if direct is not None:
                direct_list.write_text("".join(f"{line}\n" for line in direct))
            state_file = root / "split-server.state"
            if state is not None:
                state_file.write_text(state + "\n")
            env = dict(
                os.environ,
                PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                WGUI_ENV_FILE=str(env_file),
                WGUI_SPLIT_DIRECT=str(direct_list),
                WGUI_SPLIT_STATE=str(state_file),
                FAKE_STATE=str(fake_state),
                FAKE_FAILURES=",".join(failures),
                FAKE_SILENT=",".join(silent),
            )
            result = subprocess.run(["bash", str(SCRIPT), command], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=20)
            out = json.loads(fake_state.read_text())
            out["state"] = state_file.read_text().strip() if state_file.exists() else None
            return result, out

    def test_on_applies_everything_and_records_state(self):
        result, st = self.run_split("on")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(st["state"], "on")
        self.assertEqual(st["sets"], {"ru-direct": ["5.0.0.0/8", "77.88.0.0/18"]})
        self.assertEqual(st["rules"], [SPLIT_RULE])
        self.assertEqual(len(st["chains"]["mangle:PREROUTING"]), 1)
        self.assertEqual(len(st["chains"]["nat:POSTROUTING"]), 1)
        forward = st["chains"]["filter:FORWARD"]
        self.assertEqual(forward[-1], KILL_SWITCH)
        self.assertIn("ipset=2", result.stdout)

    def test_reload_swaps_without_touching_live_set_contents(self):
        result, st = self.run_split("reload", state="on", sets={"ru-direct": ["1.2.3.0/24"]})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(st["sets"], {"ru-direct": ["5.0.0.0/8", "77.88.0.0/18"]})
        live_ops = [op for op in st["ops"] if op.split()[:2] != ["save", "ru-direct"]
                    and "ru-direct" in op.split()[1:2]]
        # The live set is only ever (re)declared with -exist; never flushed or refilled.
        self.assertEqual(live_ops, ["create ru-direct hash:net family inet -exist"])
        self.assertIn("swap ru-direct-new ru-direct", st["ops"])

    def test_failed_load_keeps_live_set_and_fails(self):
        result, st = self.run_split("reload", state="on", sets={"ru-direct": ["1.2.3.0/24"]},
                                    failures=("restore",))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(st["sets"], {"ru-direct": ["1.2.3.0/24"]})
        self.assertIn("live set left unchanged", result.stderr)

    def test_failed_swap_keeps_live_set_and_fails(self):
        result, st = self.run_split("on", sets={"ru-direct": ["1.2.3.0/24"]}, failures=("swap",))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(st["sets"], {"ru-direct": ["1.2.3.0/24"]})
        self.assertIsNone(st["state"])

    def test_empty_direct_list_is_valid(self):
        result, st = self.run_split("on", direct=())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(st["sets"], {"ru-direct": []})

    def test_missing_direct_list_fails_before_any_change(self):
        result, st = self.run_split("reload", state="on", direct=None,
                                    sets={"ru-direct": ["1.2.3.0/24"]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unreadable", result.stderr)
        self.assertEqual(st["sets"], {"ru-direct": ["1.2.3.0/24"]})
        self.assertEqual(st["ops"], [])

    def test_rule_failures_fail_and_do_not_record_on(self):
        for failure in ("mangle_add", "rule_add", "nat_add", "forward_add", "rule_inspect"):
            with self.subTest(failure=failure):
                result, st = self.run_split("on", state="off", failures=(failure,))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(st["state"], "off")

    def test_silently_missing_rules_fail_verification(self):
        for silent in ("mangle_add", "rule_add", "nat_add", "forward_add"):
            with self.subTest(silent=silent):
                result, st = self.run_split("on", silent=(silent,))
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, "after apply|below the kill-switch DROP")
                self.assertIsNone(st["state"])

    def test_policy_rule_check_is_exact(self):
        wrong = ("1000: from all fwmark 0x64 lookup 200", "2000: from all fwmark 0x64 lookup main",
                 "1000: from 10.10.0.0/24 fwmark 0x64 lookup main")
        result, st = self.run_split("on", rules=wrong)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(st["rules"], list(wrong) + [SPLIT_RULE])

    def test_existing_exact_rule_is_not_duplicated(self):
        result, st = self.run_split("on", rules=(SPLIT_RULE,))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(st["rules"], [SPLIT_RULE])

    def test_off_removes_rules_including_duplicates(self):
        _, on = self.run_split("on")
        result, st = self.run_split("off", state="on", sets=on["sets"],
                                    rules=(SPLIT_RULE, SPLIT_RULE), chains=on["chains"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(st["state"], "off")
        self.assertEqual(st["rules"], [])
        self.assertEqual(st["chains"]["mangle:PREROUTING"], [])
        self.assertEqual(st["chains"]["filter:FORWARD"], [KILL_SWITCH])

    def test_off_fails_when_rule_survives(self):
        _, on = self.run_split("on")
        result, st = self.run_split("off", state="on", sets=on["sets"], rules=on["rules"],
                                    chains=on["chains"], silent=("rule_del",))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(st["state"], "on")

    def test_egress_below_kill_switch_fails(self):
        egress = "-s 10.10.0.0/24 -o ens3 -m set --match-set ru-direct dst -j ACCEPT"
        result, st = self.run_split("on", chains={"filter:FORWARD": [KILL_SWITCH, egress]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("below the kill-switch DROP", result.stderr)
        self.assertIsNone(st["state"])

    def test_status_reports_exact_rule_state(self):
        _, on = self.run_split("on")
        result, _ = self.run_split("status", state="on", sets=on["sets"], rules=on["rules"],
                                   chains=on["chains"])
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]),
                         {"state": "on", "ipset": 2, "rules": "yes"})
        result, _ = self.run_split("status", state="on", sets=on["sets"], rules=(),
                                   chains=on["chains"])
        self.assertEqual(json.loads(result.stdout.splitlines()[-1])["rules"], "no")

    def test_invalid_wan_iface_fails(self):
        result, st = self.run_split("on", env_text="WGUI_WAN_IFACE=bad iface\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WGUI_WAN_IFACE", result.stderr)
        self.assertEqual(st["sets"], {})


if __name__ == "__main__":
    unittest.main()
