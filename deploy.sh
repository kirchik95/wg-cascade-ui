#!/usr/bin/env bash
# Deploy wg-ui CODE to the VDSina entry node.
#
# Ships only app/ -> /opt/wg-ui/. Secrets (cert/key/env) and data (clients.json,
# split lists, history.db) live in /etc/wg-ui and /var/lib/wg-ui on the server
# and are NEVER touched by this script. Set WGUI_HOST (and WGUI_SSH_KEY if the
# key is not the default) before running.
set -euo pipefail

HOST="${WGUI_HOST:?set WGUI_HOST=user@entry-node-ip}"
KEY="${WGUI_SSH_KEY:-$HOME/.ssh/id_ed25519}"
DIR="$(cd "$(dirname "$0")" && pwd)"
SSH=(ssh -o IdentitiesOnly=yes -i "$KEY" -o ConnectTimeout=15)

echo "→ preflight: syntax + unit tests"
python3 -m py_compile "$DIR"/app/*.py
bash -n "$DIR"/app/*.sh "$DIR"/deploy.sh
(cd "$DIR" && python3 -m unittest discover -s tests -q)

echo "→ snapshotting current version → /opt/wg-ui.prev"
"${SSH[@]}" "${HOST}" 'rm -rf /opt/wg-ui.prev && cp -a /opt/wg-ui /opt/wg-ui.prev'

echo "→ syncing app/ → /opt/wg-ui/ on ${HOST}"
rsync -a --delete -e "ssh -o IdentitiesOnly=yes -i $KEY" "$DIR/app/" "${HOST}":/opt/wg-ui/

echo "→ fixing perms, restarting, health-checking"
"${SSH[@]}" "${HOST}" '
  set -e
  chmod 755 /opt/wg-ui/*.py /opt/wg-ui/*.sh
  systemctl restart wg-ui.service
  sleep 2
  if ! systemctl is-active --quiet wg-ui.service; then
    echo "  ✗ service failed to start — rolling back to /opt/wg-ui.prev"
    rsync -a --delete /opt/wg-ui.prev/ /opt/wg-ui/
    systemctl restart wg-ui.service
    systemctl is-active wg-ui.service
    exit 1
  fi
  printf "  service: %s\n" "$(systemctl is-active wg-ui.service)"
  curl -sk --max-time 8 -o /dev/null -w "  https local: %{http_code} in %{time_total}s\n" https://127.0.0.1/login
  curl -sk --max-time 5 -o /dev/null -w "  healthz: %{http_code}\n" https://127.0.0.1/healthz
'
echo "✓ deployed"
