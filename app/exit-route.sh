#!/usr/bin/env bash
# Per-client exit routing for the cascade.
# Clients with exit=us in /etc/wg-ui/clients.json get fwmark 0x65 → table 65 → wg-us.
# The per-client MARK rules live in our own mangle chain WGUI-EXIT, rebuilt in one
# `iptables-restore --noflush` per sync (no per-rule fork/scan as clients grow).
# PREROUTING holds a single jump into it, taken only by still-unmarked packets
# from the client iface: RU-direct (split-server.sh, mark 0x64, pri 1000) keeps
# priority whichever of the two scripts appended its PREROUTING rule first.
# Everyone else keeps the default path through wg-do (NL).
#
# Idempotent. State is derived from clients.json on every sync — no separate state file.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
US_IFACE="${WGUI_US_IFACE:-wg-us}"
CL_IFACE="${WGUI_IFACE:-wg-cl}"
CLIENTS_JSON="${WGUI_CLIENTS:-/etc/wg-ui/clients.json}"
MARK="0x65"
TABLE=65
PRI=1100
COMMENT="wgui-exit-us"          # per-client MARK rules (now only inside $CHAIN)
CHAIN="WGUI-EXIT"
JUMP_COMMENT="wgui-exit-jump"   # the single PREROUTING → $CHAIN rule
SUBNET="10.10.0.0/24"
# RPDB contract shared with split-server.sh and the wg-do tunnel config:
#   1000  fwmark 0x64 → main        RU-direct (split-server.sh)
#   1100  fwmark 0x65 → table 65    US exit (this script)
#   32765 from $SUBNET → table 200  NL cascade (wg-do PostUp)
# No other rule may sit below 1100 and steer client traffic first.
SPLIT_MARK="0x64"
NL_TABLE=200
NL_PRI=32765

us_ips() {
    python3 - "$CLIENTS_JSON" <<'PY'
import json, sys, re
path = sys.argv[1]

def fail(detail):
    print("exit-route: client registry " + detail, file=sys.stderr)
    sys.exit(1)

try:
    with open(path) as registry:
        clients = json.load(registry)
except FileNotFoundError:
    fail("is missing")
except json.JSONDecodeError:
    fail("contains malformed JSON")
except OSError:
    fail("is unreadable")
if not isinstance(clients, list):
    fail("must contain a list")
ip_re = re.compile(r"^10\.10\.0\.([2-9]|[1-9]\d|1\d\d|2[0-4]\d|25[0-4])$")
for index, c in enumerate(clients):
    if not isinstance(c, dict):
        fail("record %d must be an object" % index)
    exit_name = c.get("exit", "nl")
    if exit_name not in ("nl", "us"):
        fail("record %d has an invalid exit" % index)
    if exit_name != "us":
        continue
    if not c.get("enabled", True):
        continue
    ip = c.get("ip")
    if not isinstance(ip, str) or not ip_re.fullmatch(ip):
        fail("record %d has an invalid US client IP" % index)
    print(ip)
PY
}

ensure_table() {
    local rc
    ip route replace default dev "$US_IFACE" table "$TABLE" 2>/dev/null \
        || ip route add default dev "$US_IFACE" table "$TABLE"
    if policy_rule_present; then
        return 0
    else
        rc=$?
        [ "$rc" -eq 1 ] || return "$rc"
    fi
    ip rule add fwmark "$MARK" lookup "$TABLE" priority "$PRI"
}

ensure_forward() {
    # Accept US path above the kill-switch DROP (same pattern as split-server.sh).
    iptables -C FORWARD -i "$CL_IFACE" -o "$US_IFACE" -j ACCEPT 2>/dev/null \
        || iptables -I FORWARD 1 -i "$CL_IFACE" -o "$US_IFACE" -j ACCEPT
    iptables -C FORWARD -i "$US_IFACE" -o "$CL_IFACE" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
        || iptables -I FORWARD 1 -i "$US_IFACE" -o "$CL_IFACE" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
    iptables -t nat -C POSTROUTING -o "$US_IFACE" -j MASQUERADE 2>/dev/null \
        || iptables -t nat -A POSTROUTING -o "$US_IFACE" -j MASQUERADE
}

flush_legacy_marks() {
    # Remove per-IP MARK rules that older releases put straight into PREROUTING
    # (highest line number first). The jump rule has its own comment and stays.
    local nums n
    nums=$(iptables -t mangle -L PREROUTING -n -v --line-numbers 2>/dev/null \
        | awk -v c="$COMMENT" '
            {
                for (i = 2; i < NF; i++) {
                    if ($(i - 1) == "/*" && $i == c && $(i + 1) == "*/") {
                        print $1
                        next
                    }
                }
            }
        ' | sort -rn)
    for n in $nums; do
        iptables -t mangle -D PREROUTING "$n" 2>/dev/null || true
    done
}

jump_rule() {
    # usage: jump_rule -C|-A|-D. Only unmarked packets from the client iface enter
    # $CHAIN: a RU destination already marked 0x64 never gets overwritten.
    iptables -t mangle "$1" PREROUTING -i "$CL_IFACE" -m mark --mark 0 \
        -m comment --comment "$JUMP_COMMENT" -j "$CHAIN"
}

ensure_jump() {
    jump_rule -C 2>/dev/null || jump_rule -A
}

rebuild_chain() {
    # usage: rebuild_chain <newline-separated IPs>. Replaces $CHAIN's contents in
    # one atomic iptables-restore; --noflush leaves every other chain untouched.
    local wanted="$1" ip payload
    payload="*mangle"$'\n'":$CHAIN - [0:0]"$'\n'"-F $CHAIN"
    while IFS= read -r ip; do
        [ -z "$ip" ] && continue
        payload+=$'\n'"-A $CHAIN -s $ip/32 -m comment --comment $COMMENT -j MARK --set-xmark $MARK/0xffffffff"
    done <<< "$wanted"
    payload+=$'\n'"COMMIT"
    printf '%s\n' "$payload" | iptables-restore --noflush
}

valid_ipv4() {
    [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

flush_conntrack_many() {
    # usage: flush_conntrack_many <deadline-seconds> <ip>...
    # One process for the whole batch with a shared deadline; addresses left when
    # it runs out are reported (exit 2) instead of silently blowing the budget.
    local deadline="$1" start ip left skipped=() done_n=0
    shift
    start=$(date +%s)
    for ip in "$@"; do
        valid_ipv4 "$ip" || { echo "exit-route: invalid address $ip" >&2; return 1; }
    done
    for ip in "$@"; do
        left=$(( deadline - ($(date +%s) - start) ))
        if [ "$left" -le 0 ]; then
            skipped+=("$ip")
            continue
        fi
        if command -v timeout >/dev/null 2>&1; then
            timeout "$left" conntrack -D -s "$ip" >/dev/null 2>&1 || true
            timeout "$left" conntrack -D -d "$ip" >/dev/null 2>&1 || true
        else
            conntrack -D -s "$ip" >/dev/null 2>&1 || true
            conntrack -D -d "$ip" >/dev/null 2>&1 || true
        fi
        done_n=$((done_n + 1))
    done
    echo "exit-route: conntrack flushed for $done_n address(es)"
    if [ "${#skipped[@]}" -gt 0 ]; then
        echo "exit-route: conntrack deadline hit, skipped: ${skipped[*]}" >&2
        return 2
    fi
}

del_forward() {
    iptables -D FORWARD -i "$CL_IFACE" -o "$US_IFACE" -j ACCEPT 2>/dev/null || true
    iptables -D FORWARD -i "$US_IFACE" -o "$CL_IFACE" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
    iptables -t nat -D POSTROUTING -o "$US_IFACE" -j MASQUERADE 2>/dev/null || true
}

del_chain() {
    while jump_rule -D 2>/dev/null; do :; done
    iptables -t mangle -F "$CHAIN" 2>/dev/null || true
    iptables -t mangle -X "$CHAIN" 2>/dev/null || true
}

del_table() {
    ip rule del fwmark "$MARK" lookup "$TABLE" priority "$PRI" 2>/dev/null || true
    ip route flush table "$TABLE" 2>/dev/null || true
}

iface_up() {
    ip link show "$US_IFACE" >/dev/null 2>&1
}

check_mangle() {
    # usage: check_mangle <expected-count> <wanted-ips> < `iptables -t mangle -S`
    # One dump, every invariant: exactly one guarded jump, no legacy per-IP rules
    # left in PREROUTING, and $CHAIN holding exactly the wanted client marks.
    # Prints the number of rules in $CHAIN; problems go to stderr (exit 1).
    awk -v chain="$CHAIN" -v jc="$JUMP_COMMENT" -v c="$COMMENT" -v iface="$CL_IFACE" \
        -v mark="$MARK" -v expected="$1" -v wanted="$(tr '\n' ' ' <<< "$2")" '
        function comment(   i, v) {
            for (i = 1; i < NF; i++)
                if ($i == "--comment") { v = $(i + 1); gsub(/"/, "", v); return v }
            return ""
        }
        function has(seq) { return index(" " $0 " ", " " seq " ") > 0 }
        BEGIN {
            n = split(wanted, w, " ")
            for (i = 1; i <= n; i++)
                if (w[i] != "") { want[w[i] "/32"] = 1; nwant++ }
        }
        $1 == "-A" && $2 == "PREROUTING" {
            k = comment()
            if (k == c) legacy++
            else if (k == jc) {
                if (has("-i " iface) && (has("-m mark --mark 0x0") || has("-m mark --mark 0x0/0xffffffff")) \
                    && $(NF - 1) == "-j" && $NF == chain) jumps++
                else badjump++
            }
            next
        }
        $1 == "-A" && $2 == chain {
            found++
            src = ""
            for (i = 3; i < NF; i++) if ($i == "-s") src = $(i + 1)
            if (comment() == c && (src in want) && !(src in have) \
                && (has("--set-xmark " mark "/0xffffffff") || has("--set-mark " mark)))
                have[src] = 1
            else bad++
            next
        }
        END {
            err = 0
            if (found + 0 != expected + 0) {
                printf "exit-route: expected %d mark rule(s), found %d\n", expected, found > "/dev/stderr"; err = 1
            }
            if (legacy) { printf "exit-route: %d legacy per-client rule(s) left in PREROUTING\n", legacy > "/dev/stderr"; err = 1 }
            if (jumps != 1 || badjump) {
                printf "exit-route: expected one guarded jump to %s, found %d (+%d malformed)\n", chain, jumps, badjump > "/dev/stderr"; err = 1
            }
            if (bad) { printf "exit-route: %d unexpected rule(s) in %s\n", bad, chain > "/dev/stderr"; err = 1 }
            got = 0; for (k in have) got++
            if (got != nwant) { printf "exit-route: %d wanted client mark(s) missing\n", nwant - got > "/dev/stderr"; err = 1 }
            print found + 0
            exit err
        }
    '
}

policy_rule_present() {
    local rules
    rules=$(ip -N rule show) || return 2
    awk -v mark="$MARK" -v table="$TABLE" -v priority="$PRI" '
        {
            line_priority = $1
            sub(/:$/, "", line_priority)
            if (NF == 7 &&
                line_priority == priority &&
                $2 == "from" && $3 == "all" &&
                $4 == "fwmark" && ($5 == mark || $5 == mark "/0xffffffff") &&
                ($6 == "lookup" || $6 == "table") && $7 == table)
                found = 1
        }
        END { exit !found }
    ' <<< "$rules"
}

us_default_route_present() {
    local routes
    routes=$(ip route show table "$TABLE") || return 2
    awk -v iface="$US_IFACE" '
        $1 == "default" {
            for (i = 2; i < NF; i++) {
                if ($i == "dev" && $(i + 1) == iface)
                    found = 1
            }
        }
        END { exit !found }
    ' <<< "$routes"
}

rpdb_problems() {
    # Print every RPDB rule that breaks the contract above (one per line).
    local rules
    rules=$(ip -N rule show) || return 2
    awk -v us_pri="$PRI" -v split_mark="$SPLIT_MARK" -v subnet="$SUBNET" \
        -v nl_table="$NL_TABLE" -v nl_pri="$NL_PRI" '
        {
            pri = $1
            sub(/:$/, "", pri)
            pri += 0
            if (pri == 0)
                next
            mark = ""
            for (i = 2; i < NF; i++)
                if ($i == "fwmark") {
                    mark = $(i + 1)
                    sub(/\/0xffffffff$/, "", mark)
                }
            if (mark != "" && $2 != "not") {
                # Marked packets only: harmless unless split lands behind US.
                if (mark == split_mark && pri >= us_pri)
                    print "split rule must precede the US rule: " $0
                next
            }
            if (pri < us_pri)
                print "rule ahead of exit marks captures client traffic: " $0
            else if ($2 == "from" && $3 == subnet && ($4 == "lookup" || $4 == "table") &&
                     $5 == nl_table && pri != nl_pri)
                print "NL cascade rule expected at priority " nl_pri ": " $0
        }
    ' <<< "$rules"
}

verify_rpdb() {
    # usage: verify_rpdb <us-client-count>. Broken contract fails only while US
    # clients are requested: with none, refusing would also block an emergency
    # move of everyone to NL, so it is reported but not fatal.
    local problems rc=0
    problems=$(rpdb_problems) || rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "exit-route: unable to inspect policy rules" >&2
        return 1
    fi
    [ -z "$problems" ] && return 0
    while IFS= read -r line; do
        echo "exit-route: RPDB contract: $line" >&2
    done <<< "$problems"
    [ "$1" -eq 0 ]
}

verify_forward() {
    # Accept rules must exist and sit above any kill-switch DROP in FORWARD.
    local rules
    iptables -C FORWARD -i "$CL_IFACE" -o "$US_IFACE" -j ACCEPT 2>/dev/null \
        && iptables -C FORWARD -i "$US_IFACE" -o "$CL_IFACE" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || {
        echo "exit-route: FORWARD accept rules for $US_IFACE missing" >&2
        return 1
    }
    iptables -t nat -C POSTROUTING -o "$US_IFACE" -j MASQUERADE 2>/dev/null || {
        echo "exit-route: NAT rule for $US_IFACE missing" >&2
        return 1
    }
    rules=$(iptables -S FORWARD) || {
        echo "exit-route: unable to inspect FORWARD chain" >&2
        return 1
    }
    awk -v want="-A FORWARD -i $CL_IFACE -o $US_IFACE -j ACCEPT" '
        $0 == want && !accept { accept = NR }
        $NF == "DROP" && $(NF - 1) == "-j" && !drop { drop = NR }
        END { exit !(accept && (!drop || accept < drop)) }
    ' <<< "$rules" || {
        echo "exit-route: FORWARD accept for $US_IFACE sits below the kill-switch DROP" >&2
        return 1
    }
}

verify_sync() {
    local expected="$1" wanted="$2" dump
    if ! dump=$(iptables -t mangle -S 2>/dev/null); then
        echo "exit-route: unable to inspect mark rules" >&2
        return 1
    fi
    check_mangle "$expected" "$wanted" <<< "$dump" >/dev/null || return 1
    verify_rpdb "$expected" || return 1
    [ "$expected" -eq 0 ] && return 0
    policy_rule_present || {
        echo "exit-route: policy rule missing" >&2
        return 1
    }
    us_default_route_present || {
        echo "exit-route: US default route missing" >&2
        return 1
    }
}

sync_rules() {
    local wanted count
    if ! wanted=$(us_ips); then
        return 1
    fi
    count=$(grep -c . <<< "$wanted" || true)
    if ! iface_up; then
        if [ "$count" -gt 0 ]; then
            echo "exit-route: $US_IFACE is down while US clients are requested" >&2
            return 1
        fi
        rebuild_chain ""
        ensure_jump
        flush_legacy_marks
        verify_sync 0 "$wanted"
        echo "exit-route: $US_IFACE down — no US clients requested"
        return 0
    fi
    ensure_table
    ensure_forward
    verify_forward
    # Chain first, then the jump, then drop legacy rules: legacy and new rules set
    # the same mark, so a migrating client is never left unmarked in between.
    rebuild_chain "$wanted"
    ensure_jump
    flush_legacy_marks
    verify_sync "$count" "$wanted"
    echo "exit-route: synced $count US client(s) → $US_IFACE (mark $MARK table $TABLE)"
}

case "${1:-}" in
    sync|apply)
        sync_rules
        ;;
    flush-ct)
        # usage: exit-route.sh flush-ct [--deadline SECONDS] <ip> [<ip>...]
        shift
        deadline=20
        if [ "${1:-}" = "--deadline" ]; then
            deadline="${2:-}"
            [[ "$deadline" =~ ^[0-9]+$ ]] || { echo "usage: $0 flush-ct [--deadline SECONDS] <ip>..."; exit 1; }
            shift 2
        fi
        if [ $# -lt 1 ]; then echo "usage: $0 flush-ct [--deadline SECONDS] <ip>..."; exit 1; fi
        flush_conntrack_many "$deadline" "$@"
        ;;
    down)
        flush_legacy_marks
        del_chain
        del_forward
        del_table
        echo "exit-route: rules removed"
        ;;
    status)
        if ! wanted=$(us_ips); then exit 1; fi
        count=$(grep -c . <<< "$wanted" || true)
        rules=$(iptables -t mangle -S 2>/dev/null | awk -v chain="$CHAIN" '$1 == "-A" && $2 == chain { n++ } END { print n + 0 }')
        printf '{"iface":"%s","up":%s,"clients_us":%s,"mark_rules":%s}\n' \
            "$US_IFACE" \
            "$(iface_up && echo true || echo false)" \
            "${count:-0}" \
            "${rules:-0}"
        ;;
    *)
        echo "usage: $0 {sync|apply|flush-ct [--deadline S] <ip>...|down|status}"
        exit 1
        ;;
esac
