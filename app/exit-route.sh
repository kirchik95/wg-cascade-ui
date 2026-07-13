#!/usr/bin/env bash
# Per-client exit routing for the cascade.
# Clients with exit=us in /etc/wg-ui/clients.json get fwmark 0x65 → table 65 → wg-us.
# RU-direct (split-server.sh, mark 0x64, pri 1000) stays higher priority.
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
COMMENT="wgui-exit-us"
SUBNET="10.10.0.0/24"

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

flush_marks() {
    # Remove only our tagged per-IP MARK rules (highest line number first).
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

add_mark() {
    local ip="$1"
    iptables -t mangle -C PREROUTING -s "$ip/32" -m comment --comment "$COMMENT" -j MARK --set-mark "$MARK" 2>/dev/null \
        || iptables -t mangle -A PREROUTING -s "$ip/32" -m comment --comment "$COMMENT" -j MARK --set-mark "$MARK"
}

flush_conntrack() {
    local ip="$1"
    conntrack -D -s "$ip" >/dev/null 2>&1 || true
    conntrack -D -d "$ip" >/dev/null 2>&1 || true
}

del_forward() {
    iptables -D FORWARD -i "$CL_IFACE" -o "$US_IFACE" -j ACCEPT 2>/dev/null || true
    iptables -D FORWARD -i "$US_IFACE" -o "$CL_IFACE" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
    iptables -t nat -D POSTROUTING -o "$US_IFACE" -j MASQUERADE 2>/dev/null || true
}

del_table() {
    ip rule del fwmark "$MARK" lookup "$TABLE" priority "$PRI" 2>/dev/null || true
    ip route flush table "$TABLE" 2>/dev/null || true
}

iface_up() {
    ip link show "$US_IFACE" >/dev/null 2>&1
}

count_owned_marks() {
    awk -v c="$COMMENT" '
        {
            for (i = 1; i < NF; i++) {
                value = $(i + 1)
                sub(/^"/, "", value)
                sub(/"$/, "", value)
                if ($i == "--comment" && value == c) {
                    count++
                    next
                }
            }
        }
        END { print count + 0 }
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

verify_sync() {
    local expected="$1" wanted="$2" mark_rules actual ip
    if ! mark_rules=$(iptables -t mangle -S PREROUTING 2>/dev/null); then
        echo "exit-route: unable to inspect mark rules" >&2
        return 1
    fi
    actual=$(count_owned_marks <<< "$mark_rules")
    [ "$actual" -eq "$expected" ] || {
        echo "exit-route: expected $expected mark rule(s), found $actual" >&2
        return 1
    }
    [ "$expected" -eq 0 ] && return 0
    policy_rule_present || {
        echo "exit-route: policy rule missing" >&2
        return 1
    }
    us_default_route_present || {
        echo "exit-route: US default route missing" >&2
        return 1
    }
    while IFS= read -r ip; do
        [ -z "$ip" ] || iptables -t mangle -C PREROUTING -s "$ip/32" \
            -m comment --comment "$COMMENT" -j MARK --set-mark "$MARK"
    done <<< "$wanted"
}

sync_rules() {
    local wanted ip count=0
    if ! wanted=$(us_ips); then
        return 1
    fi
    if ! iface_up; then
        if [ -n "$wanted" ]; then
            echo "exit-route: $US_IFACE is down while US clients are requested" >&2
            return 1
        fi
        flush_marks
        verify_sync 0 "$wanted"
        echo "exit-route: $US_IFACE down — no US clients requested"
        return 0
    fi
    ensure_table
    ensure_forward
    flush_marks
    while IFS= read -r ip; do
        [ -z "$ip" ] && continue
        add_mark "$ip"
        count=$((count + 1))
    done <<< "$wanted"
    verify_sync "$count" "$wanted"
    echo "exit-route: synced $count US client(s) → $US_IFACE (mark $MARK table $TABLE)"
}

case "${1:-}" in
    sync|apply)
        sync_rules
        ;;
    flush-ct)
        # usage: exit-route.sh flush-ct 10.10.0.5
        if [ -z "${2:-}" ]; then echo "usage: $0 flush-ct <ip>"; exit 1; fi
        flush_conntrack "$2"
        echo "exit-route: conntrack flushed for $2"
        ;;
    down)
        flush_marks
        del_forward
        del_table
        echo "exit-route: rules removed"
        ;;
    status)
        if ! wanted=$(us_ips); then exit 1; fi
        count=$(grep -c . <<< "$wanted" || true)
        mark_rules=$(iptables -t mangle -S PREROUTING 2>/dev/null || true)
        rules=$(count_owned_marks <<< "$mark_rules")
        printf '{"iface":"%s","up":%s,"clients_us":%s,"mark_rules":%s}\n' \
            "$US_IFACE" \
            "$(iface_up && echo true || echo false)" \
            "${count:-0}" \
            "${rules:-0}"
        ;;
    *)
        echo "usage: $0 {sync|apply|flush-ct <ip>|down|status}"
        exit 1
        ;;
esac
