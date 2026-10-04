#!/usr/bin/env bash
# Creek Watch alert poller, one pass: runs `python -m creekwatch.alerts.poller --once` INSIDE the live
# container (its env, hardening and network), from creekwatch-poll.timer every 10 min.
# Why a timer and not the in-app poller (CREEKWATCH_POLLER=1): during a redeploy the staging container
# briefly runs beside the live one on the same DB, and two in-app pollers could double-send pushes.
# Push dedupe (alerts.last_pushed_severity) and per-source state (alert_sources) live in the DB, so
# separate --once processes are safe.
#   deploy/poll.sh              (on ubox0; re-execs there from other hosts)
set -euo pipefail
DEPLOY_HOST="${CW_DEPLOY_HOST:-ubox0}"
if [ "$(hostname -s)" != "$DEPLOY_HOST" ]; then
  exec ssh "$DEPLOY_HOST" "bash -s -- $(printf '%q ' "$@")" < "${BASH_SOURCE[0]}"
fi
main() {
exec </dev/null
NAME="${CW_CONTAINER:-creekwatch}"
LOCK="${CW_POLL_LOCK:-$HOME/creekwatch/.poll.lock}"
log() { printf '%s poll: %s\n' "$(date '+%F %T %Z')" "$*"; }
exec 9>"$LOCK"
flock -n 9 || { log "WARN: previous poll still running; this pass SKIPPED"; exit 75; }
for _ in $(seq 1 30); do   # e.g. a redeploy swap in progress
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ] && break; sleep 2
done
if ! docker exec "$NAME" python -c 'import creekwatch.alerts.poller' 2>/dev/null; then
  log "this build has no creekwatch.alerts.poller; nothing to do"; exit 0
fi
log "pass start"
timeout "${CW_POLL_TIMEOUT:-300}" docker exec "$NAME" python -m creekwatch.alerts.poller --once
log "pass done"
}
main "$@"
