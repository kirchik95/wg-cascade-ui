#!/usr/bin/env bash
# Deploy wg-ui CODE to the VDSina entry node.
#
# Ships only app/ -> /opt/wg-ui/. Secrets (cert/key/env) and data (clients.json,
# split lists, history.db) live in /etc/wg-ui and /var/lib/wg-ui on the server
# and are NEVER touched by this script. Override host/key via env if needed.
set -euo pipefail

HOST="${WGUI_HOST:-root@203.0.113.10}"
KEY="${WGUI_SSH_KEY:-$HOME/.ssh/id_ed25519}"
DIR="$(cd "$(dirname "$0")" && pwd)"
SSH=(ssh -o IdentitiesOnly=yes -i "$KEY" -o ConnectTimeout=15)

echo "→ syncing app/ → /opt/wg-ui/ on ${HOST}"
scp -q -o IdentitiesOnly=yes -i "$KEY" "$DIR"/app/* "${HOST}":/opt/wg-ui/

echo "→ fixing perms, restarting, health-checking"
"${SSH[@]}" "${HOST}" '
  set -e
  chmod 755 /opt/wg-ui/*.py /opt/wg-ui/*.sh
  systemctl restart wg-ui.service
  sleep 2
  printf "  service: %s\n" "$(systemctl is-active wg-ui.service)"
  curl -sk --max-time 8 -o /dev/null -w "  https local: %{http_code} in %{time_total}s\n" https://127.0.0.1/login
'
echo "✓ deployed"
