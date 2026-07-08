#!/usr/bin/env bash
# Per-client exit routing for the cascade.
# Clients with exit=us in /etc/wg-ui/clients.json get fwmark 0x65 → table 65 → wg-us.
# RU-direct (split-server.sh, mark 0x64, pri 1000) stays higher priority.
# Everyone else keeps the default path through wg-do (NL).
#
# Idempotent. State is derived from clients.json on every sync — no separate state file.
set -u
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
    python3 - "$CLIENTS_JSON" "$APP_DIR" <<'PY'
import json, sys, re
path, app = sys.argv[1], sys.argv[2]
sys.path.insert(0, app)
from exit_model import client_exit
try:
    clients = json.load(open(path))
except Exception:
    sys.exit(0)
ip_re = re.compile(r"^10\.10\.0\.([2-9]|[1-9]\d|1\d\d|2[0-4]\d|25[0-4])$")
for c in clients:
    if not isinstance(c, dict):
        continue
    if client_exit(c) != "us":
        continue
    if not c.get("enabled", True):
        continue
    ip = str(c.get("ip", ""))
    if ip_re.match(ip):
        print(ip)
PY
}

ensure_table() {
    ip route replace default dev "$US_IFACE" table "$TABLE" 2>/dev/null \
        || ip route add default dev "$US_IFACE" table "$TABLE"
    ip rule show | grep -q "fwmark $MARK " \
        || ip rule add fwmark "$MARK" lookup "$TABLE" priority "$PRI"
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
        | awk -v c="$COMMENT" 'index($0, c) {print $1}' | sort -rn)
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

sync_rules() {
    if ! iface_up; then
        flush_marks
        echo "exit-route: $US_IFACE down — marks cleared, nothing applied"
        return 0
    fi
    ensure_table
    ensure_forward
    flush_marks
    local n=0 ip
    while IFS= read -r ip; do
        [ -n "$ip" ] || continue
        add_mark "$ip"
        n=$((n + 1))
    done < <(us_ips)
    echo "exit-route: synced $n US client(s) → $US_IFACE (mark $MARK table $TABLE)"
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
        count=$(us_ips | grep -c . || true)
        rules=$(iptables -t mangle -S PREROUTING 2>/dev/null | grep -c -- "--comment $COMMENT" || true)
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
