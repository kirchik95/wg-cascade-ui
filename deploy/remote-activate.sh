#!/usr/bin/env bash
# Runs ON the entry node (as root), invoked by deploy.sh with the staged release:
#
#   remote-activate.sh /opt/wg-ui.staging.<id>
#
# The staging dir holds app/ (the new code) and deploy/ (this script, sudoers,
# systemd units). Steps, all under one flock so two deploys can't interleave:
#
#   1. config  — sudoers (only after `visudo -cf`) and changed units, old copies
#                backed up for this run; skipped with DEPLOY_SKIP_CONFIG=1
#   2. code    — stop wg-ui, move live → .prev, staged app → live, root:root
#   3. ready   — start wg-ui and wait (deadline, not a fixed sleep) for: unit
#                active, /login 200, /readyz 200 (or /healthz ok on an old build
#                that answers /readyz with 404)
#   4. any failure in 2–3 → restore .prev and this run's config backups, start
#                the old version and re-check it
#
# No `set -e`: every step is checked explicitly so a failure always reaches the
# rollback branch instead of killing the shell first.
#
# Exit codes: 0 deployed · 1 failed, rolled back OK · 2 failed AND rollback
# failed · 3 bad staging / config rejected (nothing changed) · 75 deploy locked.
#
# DEPLOY_PREFIX / DEPLOY_URL / DEPLOY_READY_TIMEOUT / DEPLOY_POLL_INTERVAL exist
# for tests and odd setups; production uses the defaults.
set -uo pipefail

STAGE="${1:?usage: remote-activate.sh <staging-dir>}"
PREFIX="${DEPLOY_PREFIX:-}"
LIVE="$PREFIX/opt/wg-ui"
PREV="$PREFIX/opt/wg-ui.prev"
FAILED="$PREFIX/opt/wg-ui.failed"
UNIT_DIR="$PREFIX/etc/systemd/system"
SUDOERS="$PREFIX/etc/sudoers.d/wg-ui"
BACKUP="$PREFIX/var/backups/wg-ui-deploy/$(date +%Y%m%d-%H%M%S)-$$"
LOCK="$PREFIX/run/wg-ui-deploy.lock"
URL="${DEPLOY_URL:-https://127.0.0.1}"
READY_TIMEOUT="${DEPLOY_READY_TIMEOUT:-40}"
POLL="${DEPLOY_POLL_INTERVAL:-1}"
SKIP_CONFIG="${DEPLOY_SKIP_CONFIG:-0}"
SERVICE=wg-ui.service
why=""                # last readiness failure reason

say()  { printf '  %s\n' "$*"; }
fail() { printf '  ✗ %s\n' "$*" >&2; }

cleanup_stage() {     # only ever delete a dir that looks like our staging dir
    case "$STAGE" in */wg-ui.staging.*) rm -rf "$STAGE" ;; esac
}

# ---------------------------------------------------------------- lock
mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
if ! flock -n 9; then
    fail "another deploy holds $LOCK — try again later"
    exit 75                 # staging is removed by deploy.sh, not under someone else's lock
fi

if [ ! -d "$STAGE/app" ] || [ ! -f "$STAGE/app/wg-ui.py" ]; then
    fail "staging dir $STAGE has no app/wg-ui.py"
    cleanup_stage
    exit 3
fi

# ---------------------------------------------------------------- config
changed_units=()      # unit basenames installed by this run
sudoers_changed=0
had_sudoers=0

install_file() {      # src dst mode — copy, then fix mode/owner explicitly
    cp "$1" "$2.deploy-tmp" && chmod "$3" "$2.deploy-tmp" \
        && chown root:root "$2.deploy-tmp" && mv -f "$2.deploy-tmp" "$2"
}

stage_config() {
    local src="$STAGE/deploy"
    [ -d "$src" ] || return 0
    mkdir -p "$BACKUP/units" || return 1

    if [ -f "$src/sudoers.wgui" ] && ! cmp -s "$src/sudoers.wgui" "$SUDOERS"; then
        if ! visudo -cf "$src/sudoers.wgui" >/dev/null; then
            fail "sudoers.wgui rejected by visudo — nothing changed"
            return 3
        fi
        if [ -f "$SUDOERS" ]; then
            had_sudoers=1
            cp -p "$SUDOERS" "$BACKUP/sudoers" || return 1
        fi
        mkdir -p "$(dirname "$SUDOERS")"
        install_file "$src/sudoers.wgui" "$SUDOERS" 440 || return 1
        sudoers_changed=1
        say "sudoers: installed $SUDOERS"
    fi

    local unit name
    for unit in "$src"/*.service; do
        [ -f "$unit" ] || continue
        name="$(basename "$unit")"
        cmp -s "$unit" "$UNIT_DIR/$name" && continue
        [ -f "$UNIT_DIR/$name" ] && { cp -p "$UNIT_DIR/$name" "$BACKUP/units/$name" || return 1; }
        mkdir -p "$UNIT_DIR"
        install_file "$unit" "$UNIT_DIR/$name" 644 || return 1
        changed_units+=("$name")
        say "unit: installed $name (not enabled/restarted — only $SERVICE restarts)"
    done
    if [ "${#changed_units[@]}" -gt 0 ]; then
        systemctl daemon-reload || return 1
    fi
    return 0
}

restore_config() {
    local rc=0 name
    if [ "$sudoers_changed" = 1 ]; then
        if [ "$had_sudoers" = 1 ]; then
            install_file "$BACKUP/sudoers" "$SUDOERS" 440 || rc=1
        else
            rm -f "$SUDOERS" || rc=1
        fi
    fi
    for name in "${changed_units[@]+"${changed_units[@]}"}"; do
        if [ -f "$BACKUP/units/$name" ]; then
            install_file "$BACKUP/units/$name" "$UNIT_DIR/$name" 644 || rc=1
        else
            rm -f "$UNIT_DIR/$name" || rc=1
        fi
    done
    if [ "${#changed_units[@]}" -gt 0 ]; then
        systemctl daemon-reload || rc=1
    fi
    return $rc
}

# ---------------------------------------------------------------- readiness
http_code() {         # path → prints status code ("000" on transport error)
    local code
    code="$(curl -sk --max-time 5 -o "$BODY" -w '%{http_code}' "$URL$1" 2>/dev/null)" || code="000"
    printf '%s' "${code:-000}"
}

ready_once() {
    systemctl is-active --quiet "$SERVICE" || { why="unit not active"; return 1; }
    local c
    c="$(http_code /login)"
    [ "$c" = 200 ] || { why="/login → $c"; return 1; }
    c="$(http_code /readyz)"
    if [ "$c" = 200 ]; then
        return 0
    elif [ "$c" = 404 ]; then           # build without /readyz: liveness is all we have
        c="$(http_code /healthz)"
        if [ "$c" = 200 ] && grep -q '"ok": *true' "$BODY"; then
            return 0
        fi
        why="/healthz → $c"
        return 1
    fi
    why="/readyz → $c"
    return 1
}

wait_ready() {
    local deadline=$(( $(date +%s) + READY_TIMEOUT ))
    why="not checked"
    while :; do
        ready_once && return 0
        [ "$(date +%s)" -ge "$deadline" ] && return 1
        sleep "$POLL"
    done
}

BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT

# ---------------------------------------------------------------- activate
if [ "$SKIP_CONFIG" != 1 ]; then
    stage_config
    rc=$?
    if [ "$rc" -ne 0 ]; then
        restore_config || fail "config restore after a failed config step also failed"
        cleanup_stage
        [ "$rc" = 3 ] && exit 3
        fail "config step failed — restored, code untouched"
        exit 3
    fi
fi

swapped=0             # 1 once the live release has been moved to .prev

rollback() {
    fail "$1 — rolling back"
    systemctl stop "$SERVICE" 2>/dev/null
    local ok=1
    if [ "$swapped" = 1 ]; then
        if [ -d "$PREV" ]; then
            rm -rf "$FAILED"
            [ -d "$LIVE" ] && mv "$LIVE" "$FAILED"
            mv "$PREV" "$LIVE" || ok=0
        else
            fail "no $PREV to roll back to"
            ok=0
        fi
    fi
    restore_config || ok=0
    systemctl start "$SERVICE" || ok=0
    if [ "$ok" = 1 ] && wait_ready; then
        say "rolled back; previous version is serving (failed release kept in $FAILED)"
        cleanup_stage
        exit 1
    fi
    fail "ROLLBACK FAILED ($why) — manual intervention needed"
    cleanup_stage
    exit 2
}

say "stopping $SERVICE"
systemctl stop "$SERVICE" || rollback "stop failed"

if [ -d "$LIVE" ]; then
    rm -rf "$PREV"
    mv "$LIVE" "$PREV" || rollback "could not move live release aside"
fi
swapped=1
if ! mv "$STAGE/app" "$LIVE"; then
    rollback "could not move staged release into place"
fi
chown -R root:root "$LIVE" && chmod 755 "$LIVE" \
    && find "$LIVE" -type f \( -name '*.py' -o -name '*.sh' \) -exec chmod 755 {} + \
    && find "$LIVE" -type f ! \( -name '*.py' -o -name '*.sh' \) -exec chmod 644 {} + \
    || rollback "could not set ownership/permissions"

say "starting $SERVICE"
systemctl start "$SERVICE" || rollback "start failed"
wait_ready || rollback "not ready after ${READY_TIMEOUT}s ($why)"

say "service: active · /login 200 · ready"
cleanup_stage
exit 0
