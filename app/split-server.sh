#!/usr/bin/env bash
# Server-side GLOBAL split-tunnel for the cascade.
# Client traffic destined to the RU set (ipset, built from RU zone + extras) is
# routed DIRECTLY out VDSina's WAN (exits with VDSina's RU IP); everything else
# keeps going through the cascade (-> DO). Applies to ALL clients; no per-client
# config. Idempotent. State in /etc/wg-ui/split-server.state.
set -u
IFACE="ens3"
SUBNET="10.10.0.0/24"
MARK="0x64"
PRI=1000
SET="ru-direct"
DIRECT_LIST="/etc/wg-ui/split-direct.txt"
STATE="/etc/wg-ui/split-server.state"

count() { ipset save "$SET" 2>/dev/null | grep -c '^add'; }

populate() {
    ipset create "$SET" hash:net family inet -exist
    { echo "flush $SET"
      awk 'NF{print "add '"$SET"' "$0" -exist"}' "$DIRECT_LIST"
    } | ipset restore
}

add_rules() {
    iptables -t mangle -C PREROUTING -s "$SUBNET" -m set --match-set "$SET" dst -j MARK --set-mark "$MARK" 2>/dev/null \
        || iptables -t mangle -A PREROUTING -s "$SUBNET" -m set --match-set "$SET" dst -j MARK --set-mark "$MARK"
    ip rule show | grep -q "fwmark $MARK " \
        || ip rule add fwmark "$MARK" lookup main priority "$PRI"
    iptables -t nat -C POSTROUTING -s "$SUBNET" -o "$IFACE" -j MASQUERADE 2>/dev/null \
        || iptables -t nat -A POSTROUTING -s "$SUBNET" -o "$IFACE" -j MASQUERADE
    # RU egress + return — inserted ABOVE the kill-switch DROP
    iptables -C FORWARD -s "$SUBNET" -m set --match-set "$SET" dst -o "$IFACE" -j ACCEPT 2>/dev/null \
        || iptables -I FORWARD 1 -s "$SUBNET" -m set --match-set "$SET" dst -o "$IFACE" -j ACCEPT
    iptables -C FORWARD -d "$SUBNET" -i "$IFACE" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
        || iptables -I FORWARD 1 -d "$SUBNET" -i "$IFACE" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
}

del_rules() {
    iptables -t mangle -D PREROUTING -s "$SUBNET" -m set --match-set "$SET" dst -j MARK --set-mark "$MARK" 2>/dev/null
    ip rule del fwmark "$MARK" lookup main priority "$PRI" 2>/dev/null
    iptables -t nat -D POSTROUTING -s "$SUBNET" -o "$IFACE" -j MASQUERADE 2>/dev/null
    iptables -D FORWARD -s "$SUBNET" -m set --match-set "$SET" dst -o "$IFACE" -j ACCEPT 2>/dev/null
    iptables -D FORWARD -d "$SUBNET" -i "$IFACE" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null
}

case "${1:-}" in
    on)     populate; add_rules; echo on > "$STATE"; echo "split-server ON (ipset=$(count))";;
    off)    del_rules; echo off > "$STATE"; echo "split-server OFF";;
    down)   del_rules; echo "rules removed (state kept: $(cat "$STATE" 2>/dev/null || echo off))";;
    reload) if [ "$(cat "$STATE" 2>/dev/null)" = on ]; then populate; echo "reloaded (ipset=$(count))"; else echo "off — nothing to reload"; fi;;
    apply)  if [ "$(cat "$STATE" 2>/dev/null)" = on ]; then populate; add_rules; echo "applied ON (ipset=$(count))"; else echo "state off"; fi;;
    status) st=$(cat "$STATE" 2>/dev/null || echo off)
            r=$(iptables -t mangle -C PREROUTING -s "$SUBNET" -m set --match-set "$SET" dst -j MARK --set-mark "$MARK" 2>/dev/null && echo yes || echo no)
            echo "{\"state\":\"$st\",\"ipset\":$(count),\"rules\":\"$r\"}";;
    *)      echo "usage: $0 {on|off|reload|apply|status}"; exit 1;;
esac
