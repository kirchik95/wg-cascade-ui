#!/usr/bin/env bash
# Deploy wg-ui to the VDSina entry node.
#
#   WGUI_HOST=root@<entry-ip> ./deploy.sh [--skip-config]
#
# Ships app/ (code) plus deploy/sudoers.wgui and deploy/*.service (config) into a
# per-run staging dir on the server, then runs deploy/remote-activate.sh there.
# That script holds a lock, installs changed config (sudoers only after
# `visudo -cf`), swaps the code in with root ownership, waits for readiness and
# rolls everything back on any failure. See its header for details and exit codes.
#
# --skip-config ships code only (sudoers and units are left as they are).
#
# Secrets (cert/key/env), data (clients.json, split lists, history.db) and the
# tunnel configs (/etc/wireguard, /etc/amnezia/amneziawg) live on the server and
# are NEVER touched — see docs/TUNNELS.md. Set WGUI_SSH_KEY if the key is not the
# default.
set -euo pipefail

HOST="${WGUI_HOST:?set WGUI_HOST=user@entry-node-ip}"
KEY="${WGUI_SSH_KEY:-$HOME/.ssh/id_ed25519}"
DIR="$(cd "$(dirname "$0")" && pwd)"
SSH=(ssh -o IdentitiesOnly=yes -i "$KEY" -o ConnectTimeout=15)
SKIP_CONFIG=0
for arg in "$@"; do
    case "$arg" in
        --skip-config) SKIP_CONFIG=1 ;;
        *) echo "usage: $0 [--skip-config]" >&2; exit 64 ;;
    esac
done

echo "→ preflight: syntax + unit tests"
python3 -m py_compile "$DIR"/app/*.py
bash -n "$DIR"/app/*.sh "$DIR"/deploy.sh "$DIR"/deploy/remote-activate.sh
(cd "$DIR" && python3 -m unittest discover -s tests -q)

STAGE="/opt/wg-ui.staging.$(date +%Y%m%d-%H%M%S).$$"
echo "→ staging release → ${HOST}:${STAGE}"
"${SSH[@]}" "${HOST}" "mkdir -p '$STAGE/app' '$STAGE/deploy'"
RSYNC_SSH="ssh -o IdentitiesOnly=yes -i $KEY"
rsync -a --delete -e "$RSYNC_SSH" "$DIR/app/" "${HOST}:$STAGE/app/"
rsync -a -e "$RSYNC_SSH" "$DIR/deploy/remote-activate.sh" "$DIR/deploy/sudoers.wgui" \
    "$DIR"/deploy/*.service "${HOST}:$STAGE/deploy/"

echo "→ activating (lock · config · swap · readiness · rollback on failure)"
set +e
"${SSH[@]}" "${HOST}" "DEPLOY_SKIP_CONFIG=$SKIP_CONFIG bash '$STAGE/deploy/remote-activate.sh' '$STAGE'"
rc=$?
set -e
case "$rc" in
    0)  echo "✓ deployed" ;;
    1)  echo "✗ deploy failed — previous version restored and serving" >&2 ;;
    2)  echo "✗ deploy failed AND rollback failed — check the server now" >&2 ;;
    3)  echo "✗ release or config rejected — nothing changed" >&2 ;;
    75) echo "✗ another deploy is running — try again later" >&2
        "${SSH[@]}" "${HOST}" "rm -rf '$STAGE'" || true ;;
    *)  echo "✗ activation exited with $rc (ssh/transport?) — check the server" >&2 ;;
esac
exit "$rc"
