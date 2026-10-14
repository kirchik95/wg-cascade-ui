#!/usr/bin/env bash
# Server-side GLOBAL split-tunnel for the cascade.
# Client traffic destined to the RU set (ipset, built from RU zone + extras) is
# routed DIRECTLY out VDSina's WAN (exits with VDSina's RU IP); everything else
# keeps going through the cascade (-> DO). Applies to ALL clients; no per-client
# config. Idempotent. State in /etc/wg-ui/split-server.state.
#
# Every step is checked: a failed apply exits non-zero and never records state
# it did not reach. The ipset is rebuilt aside and swapped in, so the live set
# is never empty or half-filled while clients use it.
set -uo pipefail
# The WGUI_* overrides below exist for tests; production runs under sudo with a
# clean environment and uses the defaults.
ENV_FILE="${WGUI_ENV_FILE:-/etc/wg-ui/wg-ui.env}"
# WAN iface for RU-direct MASQUERADE / FORWARD — must be set in /etc/wg-ui/wg-ui.env
# (sudo strips the environment, so we read the file directly).
IFACE=$(python3 - "$ENV_FILE" <<'PY'
import re, sys
vals = {}
try:
    for line in open(sys.argv[1]):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip().strip("\"").strip("'")
except Exception:
    pass
iface = vals.get("WGUI_WAN_IFACE", "")
if not re.match(r"^[A-Za-z0-9_-]{1,15}$", iface or ""):
    sys.stderr.write("split-server: WGUI_WAN_IFACE unset/invalid in %s\n" % sys.argv[1])
    sys.exit(1)
print(iface)
PY
) || exit 1
SUBNET="10.10.0.0/24"
MARK="0x64"
PRI=1000
SET="ru-direct"
TMP_SET="ru-direct-new"
DIRECT_LIST="${WGUI_SPLIT_DIRECT:-/etc/wg-ui/split-direct.txt}"
STATE="${WGUI_SPLIT_STATE:-/etc/wg-ui/split-server.state}"

fail() { echo "split-server: $*" >&2; exit 1; }

count() { ipset save "$SET" 2>/dev/null | grep -c '^add' || true; }

state() { cat "$STATE" 2>/dev/null || echo off; }

write_state() {
    { echo "$1" > "$STATE.tmp" && mv -f "$STATE.tmp" "$STATE"; } \
        || fail "cannot write state $STATE"
}

populate() {
    [ -r "$DIRECT_LIST" ] || fail "direct list $DIRECT_LIST is unreadable"
    ipset create "$SET" hash:net family inet -exist || fail "cannot create ipset $SET"
    ipset destroy "$TMP_SET" 2>/dev/null
    ipset create "$TMP_SET" hash:net family inet || fail "cannot create ipset $TMP_SET"
    if ! awk 'NF{print "add '"$TMP_SET"' "$0" -exist"}' "$DIRECT_LIST" | ipset restore; then
        ipset destroy "$TMP_SET" 2>/dev/null
        fail "loading $DIRECT_LIST failed — live set left unchanged"
    fi
    if ! ipset swap "$TMP_SET" "$SET"; then
        ipset destroy "$TMP_SET" 2>/dev/null
        fail "ipset swap failed — live set left unchanged"
    fi
    ipset destroy "$TMP_SET" || echo "split-server: warning: stale $TMP_SET left behind" >&2
}

mangle_rule() {   # usage: mangle_rule -C|-A|-D
    iptables -t mangle "$1" PREROUTING -s "$SUBNET" -m set --match-set "$SET" dst -j MARK --set-mark "$MARK"
}

nat_rule() {      # usage: nat_rule -C|-A|-D
    iptables -t nat "$1" POSTROUTING -s "$SUBNET" -o "$IFACE" -j MASQUERADE
}

egress_rule() {   # usage: egress_rule -C|-D|-I 1
    iptables "$1" FORWARD ${2:+"$2"} -s "$SUBNET" -m set --match-set "$SET" dst -o "$IFACE" -j ACCEPT
}

return_rule() {   # usage: return_rule -C|-D|-I 1
    iptables "$1" FORWARD ${2:+"$2"} -d "$SUBNET" -i "$IFACE" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
}

policy_rule_present() {
    # Exact form only: priority, selector, mark and table must all match.
    local rules
    rules=$(ip -N rule show) || return 2
    awk -v mark="$MARK" -v priority="$PRI" '
        {
            p = $1
            sub(/:$/, "", p)
            if (NF == 7 && p == priority &&
                $2 == "from" && $3 == "all" &&
                $4 == "fwmark" && ($5 == mark || $5 == mark "/0xffffffff") &&
                ($6 == "lookup" || $6 == "table") && ($7 == "main" || $7 == "254"))
                found = 1
        }
        END { exit !found }
    ' <<< "$rules"
}

egress_above_drop() {
    local rules
    rules=$(iptables -S FORWARD) || return 1
    # Token match: iptables -S reorders options (-o is printed before -m set).
    awk -v subnet="$SUBNET" -v set="$SET" -v iface="$IFACE" '
        $1 == "-A" && $2 == "FORWARD" && $NF == "ACCEPT" && !accept &&
        index($0, " -s " subnet " ") && index($0, " -o " iface " ") &&
        index($0, " --match-set " set " dst ") { accept = NR }
        $NF == "DROP" && $(NF - 1) == "-j" && !drop { drop = NR }
        END { exit !(accept && (!drop || accept < drop)) }
    ' <<< "$rules"
}

add_rules() {
    local rc=0
    mangle_rule -C 2>/dev/null || mangle_rule -A || fail "cannot add mangle MARK rule"
    policy_rule_present || rc=$?
    case "$rc" in
        0) ;;
        1) ip rule add fwmark "$MARK" lookup main priority "$PRI" || fail "cannot add policy rule";;
        *) fail "cannot inspect policy rules";;
    esac
    nat_rule -C 2>/dev/null || nat_rule -A || fail "cannot add MASQUERADE rule"
    # RU egress + return — inserted ABOVE the kill-switch DROP
    egress_rule -C 2>/dev/null || egress_rule -I 1 || fail "cannot add FORWARD egress rule"
    return_rule -C 2>/dev/null || return_rule -I 1 || fail "cannot add FORWARD return rule"
}

verify_on() {
    ipset list -n "$SET" >/dev/null 2>&1 || fail "ipset $SET missing after apply"
    mangle_rule -C 2>/dev/null || fail "mangle MARK rule missing after apply"
    policy_rule_present || fail "policy rule (priority $PRI fwmark $MARK lookup main) missing after apply"
    nat_rule -C 2>/dev/null || fail "MASQUERADE rule missing after apply"
    return_rule -C 2>/dev/null || fail "FORWARD return rule missing after apply"
    egress_above_drop || fail "FORWARD egress rule missing or below the kill-switch DROP"
}

del_rules() {
    local i
    mangle_rule -D 2>/dev/null
    for i in 1 2 3 4 5 6 7 8; do   # drop duplicates too
        ip rule del fwmark "$MARK" lookup main priority "$PRI" 2>/dev/null || break
    done
    nat_rule -D 2>/dev/null
    egress_rule -D 2>/dev/null
    return_rule -D 2>/dev/null
    return 0
}

verify_off() {
    local rc=0
    mangle_rule -C 2>/dev/null && fail "mangle MARK rule still present"
    policy_rule_present || rc=$?
    case "$rc" in
        0) fail "policy rule still present";;
        1) ;;
        *) fail "cannot inspect policy rules";;
    esac
    egress_rule -C 2>/dev/null && fail "FORWARD egress rule still present"
    return 0
}

rules_ok() {
    mangle_rule -C 2>/dev/null && policy_rule_present
}

case "${1:-}" in
    on)     populate; add_rules; verify_on; write_state on; echo "split-server ON (ipset=$(count))";;
    off)    del_rules; verify_off; write_state off; echo "split-server OFF";;
    down)   del_rules; echo "rules removed (state kept: $(state))";;
    reload) if [ "$(state)" = on ]; then populate; echo "reloaded (ipset=$(count))"; else echo "off — nothing to reload"; fi;;
    apply)  if [ "$(state)" = on ]; then populate; add_rules; verify_on; echo "applied ON (ipset=$(count))"; else echo "state off"; fi;;
    status) r=$(rules_ok && echo yes || echo no)
            echo "{\"state\":\"$(state)\",\"ipset\":$(count),\"rules\":\"$r\"}";;
    *)      echo "usage: $0 {on|off|reload|apply|status}"; exit 1;;
esac
