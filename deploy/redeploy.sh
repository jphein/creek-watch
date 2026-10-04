#!/usr/bin/env bash
# Creek Watch redeploy: build main on ubox0, swap the container, health-gate, roll back on failure.
#
#   deploy/redeploy.sh                 # deploy origin/main (run from any host; re-execs itself on ubox0)
#   deploy/redeploy.sh <git-ref>       # deploy a branch/sha instead
#   deploy/redeploy.sh --if-changed    # no-op unless origin/main moved (used by the systemd timer)
#   deploy/redeploy.sh --rollback      # restart the previous container (creekwatch-prev)
#   deploy/redeploy.sh --status        # what's running
#
# Layout on ubox0 (all under ~/creekwatch, nothing secret in the repo):
#   src/             git checkout (remote: github-creekwatch alias -> read-only deploy key)
#   app.env          optional extra env for the container (host-only, never committed)
#   deployed.sha     sha of the image currently live
# Container: name creekwatch, 127.0.0.1:${CW_PORT} -> ${CW_APP_PORT}, named volume creekwatch-data at ${CW_VAR}.
set -euo pipefail

DEPLOY_HOST="${CW_DEPLOY_HOST:-ubox0}"
if [ "$(hostname -s)" != "$DEPLOY_HOST" ]; then
  fwd=$(for v in $(compgen -e | grep '^CW_' || true); do printf '%s=%q ' "$v" "${!v}"; done)
  exec ssh "$DEPLOY_HOST" "env $fwd bash -s -- $(printf '%q ' "$@")" < "${BASH_SOURCE[0]}"
fi

# Everything below runs inside main(): bash parses the whole function before running it, and
# stdin is then detached, so when this script arrives as `ssh host bash -s < script`, an inner
# ssh/docker/git that reads stdin can't swallow the rest of the script.
main() {
exec </dev/null
BASE="${CW_BASE:-$HOME/creekwatch}"
SRC="$BASE/src"
REPO="${CW_REPO:-github-creekwatch:jphein/creek-watch.git}"
NAME=creekwatch
PREV=creekwatch-prev
CW_PORT="${CW_PORT:-8442}"
CW_STAGE_PORT="${CW_STAGE_PORT:-8443}"
STAGE=creekwatch-stage
# Fallback contract; backend/tests/test_deploy_contract.py asserts the Dockerfile + compose.yaml match
# these three defaults. Change them together with the Dockerfile, in the same PR.
CW_APP_PORT="${CW_APP_PORT:-8080}"
CW_VAR="${CW_VAR:-/srv/creekwatch}"
VOLUME="${CW_VOLUME:-creekwatch-data}"
HOSTNAME_PUBLIC=creekwatch.realm.watch
HEALTH_TIMEOUT="${CW_HEALTH_TIMEOUT:-60}"
# Resource caps so a hostile/huge upload OOM-kills the container (restart: unless-stopped), not ubox0.
# Idle ~60 MB; one worst-case image decode measured ~600 MB maxrss (Oracle gate-13-17), so 1.5 GB fits two
# concurrent worst cases. pids: ~14 in use.
CW_MEMORY="${CW_MEMORY:-1536m}"
CW_PIDS="${CW_PIDS:-256}"

log() { printf '%s redeploy: %s\n' "$(date '+%F %T %Z')" "$*"; }
die() { log "FAIL: $*"; exit 1; }

exec 9>"$BASE/.redeploy.lock"
flock -n 9 || die "another redeploy is running"

healthy() {  # $1 = timeout s, $2 = port, $3 = 1 to also check through Caddy (the live path)
  local deadline=$(( $(date +%s) + $1 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if curl -fs -m 5 -o /dev/null "http://127.0.0.1:$2/healthz" &&
       { [ "${3:-0}" != 1 ] || curl -fs -m 5 -o /dev/null --resolve "${HOSTNAME_PUBLIC}:443:127.0.0.1" "https://${HOSTNAME_PUBLIC}/healthz"; }; then
      return 0
    fi
    sleep 2
  done
  return 1
}

run_app() {  # $1 = container name, $2 = host port, $3 = image, $4 = restart policy
  local envfile=(); [ -f "$BASE/app.env" ] && envfile=(--env-file "$BASE/app.env")
  docker run -d --name "$1" --restart "$4" \
    -p "127.0.0.1:$2:${CW_APP_PORT}" \
    -v "$VOLUME:$CW_VAR" \
    -e "GIT_SHA=$SHA" -e "CREEKWATCH_PUBLIC_URL=https://${HOSTNAME_PUBLIC}" \
    "${envfile[@]}" \
    --log-opt max-size=10m --log-opt max-file=3 \
    --memory "$CW_MEMORY" --memory-swap "$CW_MEMORY" --pids-limit "$CW_PIDS" \
    --security-opt no-new-privileges --cap-drop ALL \
    "$3" >/dev/null
}

status() {
  docker ps -a --filter "name=^/creekwatch" --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
  log "deployed.sha=$(cat "$BASE/deployed.sha" 2>/dev/null || echo none)"
}

rollback() {
  docker inspect "$PREV" >/dev/null 2>&1 || die "no $PREV container to roll back to"
  log "rolling back to $(docker inspect -f '{{.Config.Image}}' "$PREV")"
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker rename "$PREV" "$NAME"
  docker start "$NAME" >/dev/null
  healthy "$HEALTH_TIMEOUT" "$CW_PORT" 1 || die "rollback container is not healthy either: investigate by hand"
  docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$NAME" > "$BASE/deployed.sha" 2>/dev/null || true
  log "rollback OK"
}

case "${1:-}" in
  --status) status; exit 0 ;;
  --rollback) rollback; exit 0 ;;
esac

IF_CHANGED=0; REF=origin/main
case "${1:-}" in
  --if-changed) IF_CHANGED=1 ;;
  "") ;;
  *) REF="$1" ;;
esac

mkdir -p "$BASE"
# A stalled GitHub connection once hung `git fetch` for 12+ min, and a hung run blocks the timer
# (OnUnitActiveSec never re-arms). Bound it; a network failure is NOT recorded as a failed sha.
export GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"
[ -d "$SRC/.git" ] || timeout 120 git clone -q "$REPO" "$SRC" || die "git clone failed or timed out"
timeout 90 git -C "$SRC" fetch -q --prune origin || die "git fetch failed or timed out (network?); will retry next tick"
SHA=$(git -C "$SRC" rev-parse --verify "${REF}^{commit}" 2>/dev/null || git -C "$SRC" rev-parse --verify "origin/${REF}^{commit}")
SHORT=${SHA:0:12}

if [ "$IF_CHANGED" = 1 ]; then
  [ "$(cat "$BASE/deployed.sha" 2>/dev/null)" = "$SHA" ] && exit 0
  # Don't retry a sha that already failed every 2 minutes; a new merge (new sha) or a manual run retries.
  grep -qx "$SHA" "$BASE/failed.shas" 2>/dev/null && exit 0
fi
fail() { echo "$SHA" >> "$BASE/failed.shas"; die "$@"; }
log "deploying $REF @ $SHORT"
git -C "$SRC" checkout -q --detach "$SHA"
[ -f "$SRC/Dockerfile" ] || fail "no Dockerfile at $SHORT (API lane not merged yet?)"

IMAGE="creekwatch:$SHORT"
docker build -q -t "$IMAGE" -t creekwatch:latest \
  --label "org.opencontainers.image.revision=$SHA" \
  --build-arg "GIT_SHA=$SHORT" --build-arg "GIT_BRANCH=${REF#origin/}" --build-arg "BUILT=$(date -u +%FT%TZ)" "$SRC" >/dev/null || fail "docker build failed; live container untouched"
log "built $IMAGE"

docker volume inspect "$VOLUME" >/dev/null 2>&1 || docker volume create "$VOLUME" >/dev/null

# Follow the image's own contract (EXPOSE / VOLUME) so an app-side port or data-dir change can't strand
# deploys; the SAME named volume is always mounted, so reports and photos carry across contract changes.
img_port=$(docker image inspect -f '{{range $p, $_ := .Config.ExposedPorts}}{{$p}} {{end}}' "$IMAGE" | tr ' ' '\n' | grep -m1 /tcp | cut -d/ -f1 || true)
img_vol=$(docker image inspect -f '{{range $v, $_ := .Config.Volumes}}{{$v}} {{end}}' "$IMAGE" | xargs -n1 2>/dev/null | head -1 || true)
[ -n "$img_port" ] && CW_APP_PORT="$img_port"
[ -n "$img_vol" ] && CW_VAR="$img_vol"
log "contract: app port $CW_APP_PORT, volume $VOLUME at $CW_VAR"

# 1) Stage: boot the new image on a side port (same volume) while the old one keeps serving.
docker rm -f "$STAGE" >/dev/null 2>&1 || true
run_app "$STAGE" "$CW_STAGE_PORT" "$IMAGE" no || fail "docker run (stage) failed; live container untouched"
if ! healthy "$HEALTH_TIMEOUT" "$CW_STAGE_PORT" 0; then
  log "staged container failed /healthz; live container untouched. Last logs:"
  docker logs --tail 30 "$STAGE" 2>&1 | sed 's/^/  | /'
  docker rm -f "$STAGE" >/dev/null
  fail "staging health check failed for $SHORT"
fi
docker rm -f "$STAGE" >/dev/null
log "staged OK; swapping"

# 2) Swap: keep the old container (stopped) as $PREV so rollback is one `docker start`. Gap is ~1-2 s.
docker rm -f "$PREV" >/dev/null 2>&1 || true
if docker inspect "$NAME" >/dev/null 2>&1; then
  docker stop -t 10 "$NAME" >/dev/null
  docker rename "$NAME" "$PREV"
fi
run_app "$NAME" "$CW_PORT" "$IMAGE" unless-stopped || { log "docker run failed"; rollback; fail "swap failed"; }

if healthy "$HEALTH_TIMEOUT" "$CW_PORT" 1; then
  echo "$SHA" > "$BASE/deployed.sha"
  log "LIVE $IMAGE (https://${HOSTNAME_PUBLIC})"
  # Deliberately NO self-update of ~/creekwatch/bin/redeploy.sh from main: that copy runs on the host as a
  # docker-group user (root-equivalent), so a merge must only ever change what runs INSIDE the container.
  # Updating the host script is an explicit `deploy/install.sh`.
  if [ -f "$SRC/deploy/redeploy.sh" ] && [ -f "$BASE/bin/redeploy.sh" ] && ! cmp -s "$SRC/deploy/redeploy.sh" "$BASE/bin/redeploy.sh"; then
    log "note: deploy/redeploy.sh on $SHORT differs from the installed copy; run deploy/install.sh to adopt it"
  fi
  # Keep the 3 newest creekwatch:<sha> images; prune the rest (in-use images refuse removal).
  docker images creekwatch --format '{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}' | sort -r \
    | awk -F'\t' '$2!="creekwatch:latest"{print $2}' | tail -n +4 | xargs -r docker rmi >/dev/null 2>&1 || true
else
  log "new container failed health check after swap; last logs:"
  docker logs --tail 30 "$NAME" 2>&1 | sed 's/^/  | /'
  docker rm -f "$NAME" >/dev/null
  rollback
  fail "post-swap health check failed for $SHORT (rolled back)"
fi
}
main "$@"
