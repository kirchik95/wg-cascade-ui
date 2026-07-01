#!/usr/bin/env bash
# Regenerate /etc/wg-ui/names.json (pubkey -> clientN) from wg-cl.conf.
# Run after adding/removing a client. UI picks it up live (no restart needed).
set -e
awk '/^# /{n=$2} /^PublicKey/{print $3"\t"n}' /etc/wireguard/wg-cl.conf \
 | python3 -c 'import sys,json; print(json.dumps(dict(l.split("\t") for l in sys.stdin.read().split("\n") if "\t" in l)))' \
 > /etc/wg-ui/names.json
chmod 644 /etc/wg-ui/names.json
echo "names.json refreshed:"; cat /etc/wg-ui/names.json
