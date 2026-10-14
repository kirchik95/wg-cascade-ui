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
CHAIN = "WGUI-EXIT"
CORRECT_POLICY = "1100: from all fwmark 0x65 lookup 65"

SPLIT_RULE = "-A PREROUTING -s 10.10.0.0/24 -m set --match-set ru-direct dst -j MARK --set-xmark 0x64/0xffffffff"
JUMP_ARGS = ["-i", "wg-cl", "-m", "mark", "--mark", "0", "-m", "comment",
             "--comment", "wgui-exit-jump", "-j", CHAIN]


def mangle_mark(rules, src, iif, ru_dst):
    """Tiny netfilter model of mangle MARK rules (`iptables -S` form): walks
    PREROUTING, follows jumps into user chains, returns the final mark."""
    chains = {}
    for rule in rules:
        t = rule.split()
        if len(t) > 1 and t[0] == "-A":
            chains.setdefault(t[1], []).append(t)

    def walk(chain, mark):
        for t in chains.get(chain, []):
            i, ok, new, jump = 2, True, None, None
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
                    ok &= mark == int(t[i + 3].split("/")[0], 16); i += 4
                elif t[i:i + 3] == ["-m", "set", "--match-set"]:
                    ok &= ru_dst; i += 5
                elif t[i:i + 3] == ["-m", "comment", "--comment"]:
                    i += 4
                elif t[i] == "-j":
                    if t[i + 1] != "MARK":
                        jump = t[i + 1]
                    i += 2
                elif t[i] in ("--set-xmark", "--set-mark"):
                    new = int(t[i + 1].split("/")[0], 16); i += 2
                else:
                    raise AssertionError("unmodeled token %r in %r" % (t[i], t))
            if not ok:
                continue
            if new is not None:
                mark = new
            if jump:
                mark = walk(jump, mark)
        return mark

    return walk("PREROUTING", 0)


IP_FAKE = r'''
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
'''

# Mangle model: FAKE_MARK_STATE holds per-IP rules that older releases put
# straight into PREROUTING (rows ip|comment|mark[|legacy]); FAKE_JUMP_STATE one
# line per PREROUTING jump rule; FAKE_CHAIN_STATE the WGUI-EXIT rows (ip|comment|mark),
# present as a file only once the chain exists.
IPTABLES_FAKE = r'''
    #!/usr/bin/env python3
    import os
    import pathlib
    import sys

    args = sys.argv[1:]
    failures = set(filter(None, os.environ["FAKE_FAILURES"].split(",")))
    silent = set(filter(None, os.environ["FAKE_SILENT_APPLIES"].split(",")))
    marks = pathlib.Path(os.environ["FAKE_MARK_STATE"])
    jumps = pathlib.Path(os.environ["FAKE_JUMP_STATE"])
    chain = pathlib.Path(os.environ["FAKE_CHAIN_STATE"])
    forward = pathlib.Path(os.environ["FAKE_FORWARD_STATE"])
    nat = pathlib.Path(os.environ["FAKE_NAT_STATE"])
    quote = os.environ["FAKE_QUOTE_COMMENTS"] == "1"
    JUMP = ["-i", "wg-cl", "-m", "mark", "--mark", "0", "-m", "comment",
            "--comment", "wgui-exit-jump", "-j", "WGUI-EXIT"]

    def lines(path):
        return [line for line in path.read_text().splitlines() if line] if path.exists() else []

    def write_lines(path, values):
        path.write_text("".join(f"{value}\n" for value in values))

    def parse(row):
        parts = row.split("|")
        return parts[0], parts[1], parts[2], len(parts) > 3 and parts[3] == "legacy"

    def q(comment):
        return f'"{comment}"' if quote else comment

    if args == ["-t", "mangle", "-L", "PREROUTING", "-n", "-v", "--line-numbers"]:
        number = 0
        for row in lines(marks):
            number += 1
            ip, comment, mark, legacy = parse(row)
            match = "" if legacy else "mark match 0x0 "
            print(f"{number} 0 0 MARK all -- wg-cl * {ip}/32 0.0.0.0/0 {match}/* {comment} */ MARK set {mark}")
        for _ in lines(jumps):
            number += 1
            print(f"{number} 0 0 WGUI-EXIT all -- wg-cl * 0.0.0.0/0 0.0.0.0/0 mark match 0x0 /* wgui-exit-jump */")
        sys.exit(0)
    if args == ["-t", "mangle", "-S"]:
        if "mark_inspect" in failures:
            sys.exit(1)
        print("-P PREROUTING ACCEPT")
        if chain.exists():
            print("-N WGUI-EXIT")
        for row in lines(marks):
            ip, comment, mark, legacy = parse(row)
            guard = "" if legacy else "-i wg-cl "
            match = "" if legacy else "-m mark --mark 0x0 "
            print(f"-A PREROUTING {guard}-s {ip}/32 {match}-m comment --comment {q(comment)} -j MARK --set-xmark {mark}/0xffffffff")
        for _ in lines(jumps):
            print(f"-A PREROUTING -i wg-cl -m mark --mark 0x0 -m comment --comment {q('wgui-exit-jump')} -j WGUI-EXIT")
        for row in lines(chain):
            ip, comment, mark, _ = parse(row)
            print(f"-A WGUI-EXIT -s {ip}/32 -m comment --comment {q(comment)} -j MARK --set-xmark {mark}/0xffffffff")
        sys.exit(0)
    if args[:4] == ["-t", "mangle", "-D", "PREROUTING"] and len(args) == 5:
        number = int(args[4])
        legacy_rows, jump_rows = lines(marks), lines(jumps)
        if 1 <= number <= len(legacy_rows):
            del legacy_rows[number - 1]
        elif len(legacy_rows) < number <= len(legacy_rows) + len(jump_rows):
            jump_rows.pop()
        write_lines(marks, legacy_rows)
        write_lines(jumps, jump_rows)
        sys.exit(0)
    if len(args) == 4 + len(JUMP) and args[:2] == ["-t", "mangle"] and args[3] == "PREROUTING" \
            and args[4:] == JUMP and args[2] in ("-C", "-A", "-D"):
        rows = lines(jumps)
        if args[2] == "-C":
            sys.exit(0 if rows else 1)
        if args[2] == "-D":
            if not rows:
                sys.exit(1)
            write_lines(jumps, rows[:-1])
            sys.exit(0)
        if "jump" in failures:
            sys.exit(1)
        if not chain.exists():
            print("iptables: Couldn't load target `WGUI-EXIT'", file=sys.stderr)
            sys.exit(2)
        write_lines(jumps, rows + ["jump"])
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
            write_lines(forward, [key] + lines(forward))
        sys.exit(0)
    if args == ["-S", "FORWARD"]:
        if "forward_inspect" in failures:
            sys.exit(1)
        render = {
            "out": "-A FORWARD -i wg-cl -o wg-us -j ACCEPT",
            "return": "-A FORWARD -i wg-us -o wg-cl -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT",
            "drop": "-A FORWARD -s 10.10.0.0/24 ! -d 10.10.0.0/24 ! -o wg-do -j DROP",
        }
        print("-P FORWARD ACCEPT")
        for key in lines(forward):
            print(render[key])
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
'''

# iptables-restore --noflush: accepts only a rebuild of our own chain.
RESTORE_FAKE = r'''
    #!/usr/bin/env python3
    import os
    import pathlib
    import sys

    failures = set(filter(None, os.environ["FAKE_FAILURES"].split(",")))
    silent = set(filter(None, os.environ["FAKE_SILENT_APPLIES"].split(",")))
    chain = pathlib.Path(os.environ["FAKE_CHAIN_STATE"])
    log = pathlib.Path(os.environ["FAKE_RESTORE_LOG"])
    payload = sys.stdin.read()
    with log.open("a") as f:
        f.write(payload + "\0")
    if sys.argv[1:] != ["--noflush"]:
        print("restore without --noflush would wipe foreign chains", file=sys.stderr)
        sys.exit(64)
    rows = [line for line in payload.splitlines() if line]
    if rows[:3] != ["*mangle", ":WGUI-EXIT - [0:0]", "-F WGUI-EXIT"] or rows[-1] != "COMMIT":
        print("unexpected restore payload", file=sys.stderr)
        sys.exit(64)
    new = []
    for row in rows[3:-1]:
        t = row.split()
        if (len(t) != 12 or t[:3] != ["-A", "WGUI-EXIT", "-s"] or not t[3].endswith("/32")
                or t[4:] != ["-m", "comment", "--comment", "wgui-exit-us", "-j", "MARK", "--set-xmark", "0x65/0xffffffff"]):
            print("unexpected restore rule: " + row, file=sys.stderr)
            sys.exit(64)
        new.append(f"{t[3][:-3]}|wgui-exit-us|0x65")
    if "mark" in failures:
        sys.exit(1)
    if "mark" in silent:
        if not chain.exists():
            chain.write_text("")
        sys.exit(0)
    chain.write_text("".join(f"{row}\n" for row in new))
    sys.exit(0)
'''


class FakeHost:
    def __init__(self, test, root):
        self.root = root
        self.bindir = root / "bin"
        self.bindir.mkdir()
        test._executable(self.bindir / "ip", IP_FAKE)
        test._executable(self.bindir / "iptables", IPTABLES_FAKE)
        test._executable(self.bindir / "iptables-restore", RESTORE_FAKE)
        test._executable(self.bindir / "conntrack", textwrap.dedent('''
            #!/usr/bin/env bash
            echo "$*" >> "$FAKE_CONNTRACK_LOG"
            [ -n "${FAKE_CONNTRACK_SLEEP:-}" ] && sleep "$FAKE_CONNTRACK_SLEEP"
            exit 0
        '''))
        for name in ("marks", "jumps", "policy", "route", "forward", "nat", "restore-log", "conntrack-log"):
            (root / name).write_text("")
        (root / "rule-show-count").write_text("0")

    def env(self, **extra):
        root = self.root
        env = dict(
            os.environ,
            PATH=str(self.bindir) + os.pathsep + os.environ["PATH"],
            WGUI_US_IFACE="wg-us",
            FAKE_FAILURES="",
            FAKE_SILENT_APPLIES="",
            FAKE_IFACE_UP="1",
            FAKE_MARK_STATE=str(root / "marks"),
            FAKE_JUMP_STATE=str(root / "jumps"),
            FAKE_CHAIN_STATE=str(root / "chain"),
            FAKE_POLICY_STATE=str(root / "policy"),
            FAKE_ROUTE_STATE=str(root / "route"),
            FAKE_FORWARD_STATE=str(root / "forward"),
            FAKE_NAT_STATE=str(root / "nat"),
            FAKE_RULE_SHOW_COUNT=str(root / "rule-show-count"),
            FAKE_RESTORE_LOG=str(root / "restore-log"),
            FAKE_CONNTRACK_LOG=str(root / "conntrack-log"),
            FAKE_QUOTE_COMMENTS="0",
            FAKE_TABLE_ALIAS="",
        )
        env.update(extra)
        return env


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
        initial_forward=(),
        initial_jumps=0,
        initial_chain=None,
        runs=1,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            host = FakeHost(self, root)
            registry = root / "clients.json"
            if registry_mode == "json":
                registry.write_text(json.dumps(clients))
            elif registry_mode == "raw":
                registry.write_text(clients)
            elif registry_mode == "directory":
                registry.mkdir()
            elif registry_mode != "missing":
                raise AssertionError("unknown registry mode")
            mark_rows = []
            for mark in initial_marks:
                if isinstance(mark, str):
                    mark = (mark, COMMENT, MARK)
                mark_rows.append("|".join(mark))
            (root / "marks").write_text("".join(f"{row}\n" for row in mark_rows))
            (root / "jumps").write_text("jump\n" * initial_jumps)
            if initial_chain is not None:
                (root / "chain").write_text("".join(f"{ip}|{COMMENT}|{MARK}\n" for ip in initial_chain))
            (root / "policy").write_text("".join(f"{rule}\n" for rule in initial_policy))
            (root / "route").write_text("" if initial_route is None else "|".join(initial_route) + "\n")
            (root / "forward").write_text("".join(f"{row}\n" for row in initial_forward))
            env = host.env(
                WGUI_CLIENTS=str(registry),
                FAKE_IFACE_UP="1" if iface_up else "0",
                FAKE_FAILURES=",".join(failures),
                FAKE_SILENT_APPLIES=",".join(silent_applies),
                FAKE_QUOTE_COMMENTS="1" if quote_comments else "0",
                FAKE_TABLE_ALIAS=table_alias or "",
            )
            for _ in range(runs):
                result = subprocess.run(
                    ["bash", str(SCRIPT), "sync"],
                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=20,
                )
            rendered = subprocess.run(
                [str(host.bindir / "iptables"), "-t", "mangle", "-S"],
                env=dict(env, FAKE_FAILURES="", FAKE_QUOTE_COMMENTS="0"), capture_output=True, text=True,
            ).stdout.splitlines()
            chain = root / "chain"
            return result, {
                "mangle": [line for line in rendered if line.startswith("-A ")],
                "marks": [tuple(row.split("|")) for row in (root / "marks").read_text().splitlines()],
                "jumps": len((root / "jumps").read_text().splitlines()),
                "chain": ([tuple(row.split("|")) for row in chain.read_text().splitlines()]
                          if chain.exists() else None),
                "restores": [p for p in (root / "restore-log").read_text().split("\0") if p],
                "policy": (root / "policy").read_text().splitlines(),
                "route": (root / "route").read_text().strip(),
                "forward": (root / "forward").read_text().splitlines(),
                "nat": (root / "nat").read_text().splitlines(),
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
            initial_chain=("10.10.0.98",),
            initial_jumps=1,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["marks"], [])
        self.assertEqual(state["chain"], [])
        self.assertEqual(state["jumps"], 1)

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
                    initial_chain=("10.10.0.98",),
                    registry_mode=mode,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("client registry", result.stderr)
                self.assertEqual(state["marks"], [original])
                self.assertEqual(state["chain"], [("10.10.0.98", COMMENT, MARK)])
                self.assertEqual(state["restores"], [])
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

    def test_restore_failure_propagates_and_keeps_legacy_marks(self):
        legacy = ("10.10.0.2", COMMENT, MARK, "legacy")
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_marks=(legacy,),
            failures=("mark",),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state["marks"], [legacy])   # never torn down before the chain exists

    def test_jump_failure_propagates(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            failures=("jump",),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_successful_us_sync_verifies_one_mark(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["chain"], [("10.10.0.2", COMMENT, MARK)])
        self.assertEqual(state["jumps"], 1)
        self.assertEqual(state["marks"], [])
        self.assertEqual(state["policy"], [CORRECT_POLICY])
        self.assertEqual(state["route"], "wg-us|65")
        self.assertEqual(sorted(state["forward"]), ["out", "return"])
        self.assertEqual(state["nat"], ["wg-us"])
        self.assertIn("synced 1 US client", result.stdout)

    def test_many_clients_rebuild_in_one_restore(self):
        clients = [{"ip": "10.10.0.%d" % n, "exit": "us", "enabled": True} for n in range(2, 252)]
        result, state = self.run_sync(clients, iface_up=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(state["restores"]), 1)
        self.assertEqual(len(state["chain"]), 250)
        self.assertIn("synced 250 US client", result.stdout)

    def test_repeated_sync_does_not_duplicate_jump_and_replaces_chain(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_jumps=1,
            initial_chain=("10.10.0.77", "10.10.0.2"),
            runs=2,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["jumps"], 1)
        self.assertEqual(state["chain"], [("10.10.0.2", COMMENT, MARK)])

    def test_legacy_us_client_without_enabled_is_active(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us"}],
            iface_up=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["chain"], [("10.10.0.2", COMMENT, MARK)])

    def test_disabled_us_client_does_not_require_ip_or_mark(self):
        result, state = self.run_sync(
            [{"exit": "us", "enabled": False}],
            iface_up=False,
            initial_marks=("10.10.0.99",),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["marks"], [])
        self.assertEqual(state["chain"], [])

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
        self.assertEqual(state["chain"], [])
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

    def test_us_jump_is_guarded_and_client_scoped(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        (jump,) = [rule for rule in state["mangle"] if rule.startswith("-A PREROUTING")]
        self.assertIn("-i wg-cl ", jump)
        self.assertIn("-m mark --mark 0x0 ", jump)
        self.assertTrue(jump.endswith("-j " + CHAIN))

    def test_ru_direct_wins_in_either_rule_order(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        jump = [rule for rule in state["mangle"] if rule.startswith("-A PREROUTING")]
        chain = [rule for rule in state["mangle"] if rule.startswith("-A " + CHAIN)]
        for label, rules in (("split first", [SPLIT_RULE] + jump + chain),
                             ("us first", jump + [SPLIT_RULE] + chain)):
            with self.subTest(order=label):
                self.assertEqual(mangle_mark(rules, "10.10.0.2", "wg-cl", ru_dst=True), 0x64)
                self.assertEqual(mangle_mark(rules, "10.10.0.2", "wg-cl", ru_dst=False), 0x65)
                self.assertEqual(mangle_mark(rules, "10.10.0.3", "wg-cl", ru_dst=False), 0)
                self.assertEqual(mangle_mark(rules, "10.10.0.2", "ens3", ru_dst=False), 0)

    def test_legacy_per_client_rules_migrate_into_chain(self):
        rows = (("10.10.0.2", COMMENT, MARK, "legacy"), ("10.10.0.3", COMMENT, MARK),
                ("10.10.0.4", COMMENT, MARK))
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True},
             {"ip": "10.10.0.3", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_marks=rows,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["marks"], [])
        self.assertEqual(state["chain"], [("10.10.0.2", COMMENT, MARK), ("10.10.0.3", COMMENT, MARK)])
        self.assertEqual(state["jumps"], 1)

    def test_restore_payload_only_touches_own_chain(self):
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        (payload,) = state["restores"]
        self.assertEqual(payload.splitlines(), [
            "*mangle",
            ":WGUI-EXIT - [0:0]",
            "-F WGUI-EXIT",
            "-A WGUI-EXIT -s 10.10.0.2/32 -m comment --comment wgui-exit-us -j MARK --set-xmark 0x65/0xffffffff",
            "COMMIT",
        ])

    def test_early_nl_rule_fails_sync_with_us_clients(self):
        # 2026-10-14: wg-do re-added its rule without a priority and it landed at 999.
        early = "999: from 10.10.0.0/24 lookup 200"
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_policy=(early,),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RPDB contract", result.stderr)
        self.assertIn(early, result.stderr)

    def test_early_rule_only_warns_without_us_clients(self):
        early = "999: from 10.10.0.0/24 lookup 200"
        for iface_up in (True, False):
            with self.subTest(iface_up=iface_up):
                result, _ = self.run_sync([], iface_up=iface_up, initial_policy=(early,))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("RPDB contract", result.stderr)

    def test_full_contract_passes(self):
        contract = (
            "0: from all lookup local",
            "1000: from all fwmark 0x64 lookup main",
            CORRECT_POLICY,
            "32765: from 10.10.0.0/24 lookup 200",
            "32766: from all lookup main",
            "32767: from all lookup default",
        )
        result, state = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_policy=contract,
            initial_forward=("drop",),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RPDB", result.stderr)
        self.assertEqual(state["forward"][-1], "drop")

    def test_negated_fwmark_rule_ahead_of_marks_is_a_conflict(self):
        rule = "900: not from all fwmark 0xca6c lookup 51820"
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_policy=(rule,),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(rule, result.stderr)

    def test_split_rule_behind_us_rule_fails(self):
        late_split = "1200: from all fwmark 0x64 lookup main"
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_policy=(late_split,),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("split rule must precede", result.stderr)

    def test_nl_rule_at_unexpected_priority_is_reported(self):
        odd = "20000: from 10.10.0.0/24 lookup 200"
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_policy=(odd,),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected at priority 32765", result.stderr)

    def test_silently_missing_forward_accept_fails(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            silent_applies=("forward",),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FORWARD accept rules", result.stderr)

    def test_silently_missing_nat_fails(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            silent_applies=("nat",),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NAT rule", result.stderr)

    def test_forward_accept_below_kill_switch_fails(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            initial_forward=("drop", "out", "return"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("below the kill-switch DROP", result.stderr)

    def test_forward_inspect_failure_propagates(self):
        result, _ = self.run_sync(
            [{"ip": "10.10.0.2", "exit": "us", "enabled": True}],
            iface_up=True,
            failures=("forward_inspect",),
        )
        self.assertNotEqual(result.returncode, 0)


class TestConntrackFlush(unittest.TestCase):
    _executable = TestExitRoute._executable

    def flush(self, args, **env_extra):
        with tempfile.TemporaryDirectory() as td:
            host = FakeHost(self, pathlib.Path(td))
            result = subprocess.run(
                ["bash", str(SCRIPT), "flush-ct"] + args,
                cwd=ROOT, env=host.env(**env_extra), capture_output=True, text=True, timeout=30,
            )
            return result, (pathlib.Path(td) / "conntrack-log").read_text().splitlines()

    def test_batch_flushes_every_address_in_one_process(self):
        result, calls = self.flush(["10.10.0.2", "10.10.0.3"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["-D -s 10.10.0.2", "-D -d 10.10.0.2", "-D -s 10.10.0.3", "-D -d 10.10.0.3"])
        self.assertIn("flushed for 2 address(es)", result.stdout)

    def test_single_address_form_still_works(self):
        result, calls = self.flush(["10.10.0.5"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)

    def test_deadline_reports_skipped_addresses(self):
        result, calls = self.flush(["--deadline", "1", "10.10.0.2", "10.10.0.3", "10.10.0.4"],
                                   FAKE_CONNTRACK_SLEEP="0.6")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("deadline hit, skipped", result.stderr)
        self.assertIn("10.10.0.4", result.stderr)

    def test_rejects_non_address_arguments(self):
        result, calls = self.flush(["10.10.0.2", "--zone"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
