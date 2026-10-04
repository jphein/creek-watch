#!/usr/bin/env bash
# Regression test for the swap lock shared by poll.sh / backup.sh / redeploy.sh (backup-stage/.lock).
# Runs on ubox0 against SCRATCH containers only (never the live container, the live volume, or disks):
#   - cw-sl-app:  the live image, --network none, a scratch volume  -> target for backup.sh
#   - cw-sl-stub: the live image + a stub creekwatch.alerts.poller that sleeps 6 s (run as `sleep`)
#                 -> target for poll.sh
# redeploy.sh's take/release_backup_lock are extracted verbatim and exercised in isolation (a real
# redeploy would swap the prod container).
#   deploy/tests/swap-lock.sh [backup.sh] [poll.sh] [redeploy.sh]      (defaults: ../<name>)
# Exit: 0 pass · 1 a case failed · 2 precondition not met
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
B="${1:-$here/../backup.sh}"; P="${2:-$here/../poll.sh}"; R="${3:-$here/../redeploy.sh}"
host="${CW_DEPLOY_HOST:-ubox0}"; T="creekwatch/swaplock-$$"
# Extract redeploy's lock functions verbatim into a sourceable file.
fns=$(python3 - "$R" <<'PY'
import sys
s = open(sys.argv[1]).read()
def fn(n):
    i = s.index(f"{n}() {{"); j = s.index("\n}\n", i) + 3; return s[i:j]
print("log() { :; }\n" + fn("take_backup_lock") + fn("release_backup_lock"))
PY
)
ssh "$host" "mkdir -p ~/$T/shim"
scp -q "$here/docker-shim" "$host:$T/shim/docker"; scp -q "$B" "$host:$T/backup.sh"; scp -q "$P" "$host:$T/poll.sh"
printf '%s\n' "$fns" | ssh "$host" "cat > ~/$T/redeploy-lock-fns.sh"
ssh "$host" "T=\$HOME/$T bash -s" <<'REMOTE'
set -uo pipefail
cd "$T"; chmod +x shim/docker; mkdir -p stage dest ctx/alerts
APP=cw-sl-app-$$; STUB=cw-sl-stub-$$; VOL=cw-sl-vol-$$; SIMG=cw-sl-stubimg-$$
cleanup() { docker rm -f "$APP" "$STUB" >/dev/null 2>&1; docker volume rm "$VOL" >/dev/null 2>&1; docker rmi "$SIMG" >/dev/null 2>&1; rm -rf "$T"; }
trap cleanup EXIT
img=$(docker inspect -f '{{.Config.Image}}' creekwatch)
: > ctx/alerts/__init__.py
printf 'import time,sys\nif __name__ == "__main__":\n    time.sleep(6); print("{}"); sys.exit(0)\n' > ctx/alerts/poller.py
printf 'FROM %s\nCOPY alerts/ /app/backend/creekwatch/alerts/\n' "$img" > ctx/Dockerfile
docker build -q -t "$SIMG" ctx >/dev/null
docker run -d --name "$STUB" --network none --cap-drop ALL --security-opt no-new-privileges "$SIMG" sleep 1000000 >/dev/null
dd=$(docker image inspect -f '{{range $v, $_ := .Config.Volumes}}{{$v}}{{end}}' "$img")
docker run -d --name "$APP" --network none --cap-drop ALL --security-opt no-new-privileges -v "$VOL:$dd" "$img" >/dev/null
for _ in $(seq 1 30); do docker exec "$APP" test -f "$dd/creekwatch.db" 2>/dev/null && break; sleep 1; done
docker exec "$APP" test -f "$dd/creekwatch.db" || { echo "PRECONDITION: scratch app DB never appeared"; exit 2; }
[ "$(docker inspect -f '{{.State.Running}}' "$STUB")" = true ] || { echo "PRECONDITION: stub container not running"; exit 2; }

export CW_BACKUP_STAGE=$T/stage CW_BACKUP_HOST=local CW_BACKUP_DIR=$T/dest
L=$T/stage/.lock; mkdir -p "$T/stage"; : >> "$L"
fails=0; bad() { echo "FAIL: $*"; fails=$((fails+1)); }
now() { date +%s.%N; }; el() { python3 -c "print(round($(now)-$1,1))"; }
ge() { python3 -c "import sys; sys.exit(0 if $1 >= $2 else 1)"; }
poll() { CW_CONTAINER=$STUB CW_POLL_LOCK=$T/$1.lock bash "$T/poll.sh" >/dev/null 2>&1; }
backup() { PATH=$T/shim:$PATH SHIM_MODE=slow SHIM_SLOW=5 CW_CONTAINER=$APP CW_VOLUME=$VOL bash "$T/backup.sh" >/dev/null 2>&1; }

# A: poll + poll (shared + shared) run concurrently
t=$(now); poll p1 & poll p2 & wait; e=$(el $t); echo "A  poll+poll concurrent:            ${e}s"; ge 9 "$e" || bad "A: two passes serialised (${e}s)"
# B: an exclusive holder (redeploy swap) makes the shared pass wait, then it runs
( flock -x "$L" sleep 6 ) & sleep 1; t=$(now); poll p1; rc=$?; e=$(el $t); wait
echo "B  swap 6 s, then poll:             rc=$rc ${e}s"; [ $rc = 0 ] && ge "$e" 9 || bad "B: pass did not wait or failed (rc=$rc, ${e}s)"
# C: an exclusive holder outlasting CW_POLL_SWAP_WAIT -> quiet skip, exit 0
( flock -x "$L" sleep 7 ) & sleep 1
out=$(CW_CONTAINER=$STUB CW_POLL_LOCK=$T/p1.lock CW_POLL_SWAP_WAIT=3 bash "$T/poll.sh" 2>&1); rc=$?; wait
echo "C  swap outlasts wait=3:            rc=$rc $(grep -oE 'skipped[^"]*|WARN.*' <<<"$out" | head -1)"
{ [ $rc = 0 ] && grep -q "skipped: swap/backup in progress" <<<"$out"; } || bad "C: timeout was not a quiet skip"
# D: redeploy's take/release (verbatim): held -> others locked out; released -> free
d=$( bash -c ". $T/redeploy-lock-fns.sh; take_backup_lock; flock -x -n $L true && echo free || echo LOCKED; release_backup_lock; flock -x -n $L true && echo free || echo LOCKED" | tr '\n' ' ')
echo "D  redeploy take/release:           $d"; [ "$d" = "LOCKED free " ] || bad "D: take/release semantics ($d)"
# T4: backup (shared swap lock) + poll (shared) run concurrently
t=$(now); backup & b=$!; sleep 0.5; poll p1; prc=$?; wait $b; brc=$?; e=$(el $t)
echo "T4 backup(5 s)+poll(6 s) concurrent: backup rc=$brc poll rc=$prc ${e}s"
{ [ $brc = 0 ] && [ $prc = 0 ] && ge 9.5 "$e"; } || bad "T4: backup blocked the poll or failed (${e}s)"
# T5: backup + backup serialise (each ~5 s)
t=$(now); backup & b1=$!; sleep 0.5; backup & b2=$!; wait $b1; r1=$?; wait $b2; r2=$?; e=$(el $t)
echo "T5 backup+backup:                   rc=$r1,$r2 ${e}s"; { [ $r1 = 0 ] && [ $r2 = 0 ] && ge "$e" 9.5; } || bad "T5: backups did not serialise (${e}s)"
# T6: a redeploy swap (exclusive) waits for a running backup
backup & b=$!; sleep 1; t=$(now); bash -c ". $T/redeploy-lock-fns.sh; take_backup_lock"; e=$(el $t); wait $b
echo "T6 swap waits for backup:           waited ${e}s"; ge "$e" 3 || bad "T6: swap did not wait for the backup (${e}s)"

if [ $fails = 0 ]; then echo "PASS: A B C D T4 T5 T6"; else echo "$fails case(s) failed"; exit 1; fi
REMOTE
