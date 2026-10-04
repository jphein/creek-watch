#!/usr/bin/env bash
# Self-contained failure-mode tests for deploy/backup.sh. Runs on ubox0 against a SCRATCH container
# (the live image, --network none) with a SCRATCH volume seeded with 3 JPEGs, a scratch stage and a
# LOCAL scratch destination. Never touches the live container, the live volume, or disks.
#   deploy/tests/backup-failure-modes.sh [path/to/backup.sh]     (from any host; default ../backup.sh)
# Exit: 0 pass · 1 a case failed · 2 precondition not met (seeding failed)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="${1:-$here/../backup.sh}"
host="${CW_DEPLOY_HOST:-ubox0}"
T="creekwatch/bktest-$$"
ssh "$host" "mkdir -p ~/$T"
scp -q "$here/docker-shim" "$host:$T/docker-shim"
scp -q "$script" "$host:$T/backup.sh"
ssh "$host" "T=\$HOME/$T bash -s" <<'REMOTE'
set -uo pipefail
cd "$T"; mkdir -p shim stage dest; mv docker-shim shim/docker; chmod +x shim/docker
CTR=cw-bktest-$$; VOL=cw-bktest-vol-$$
cleanup() { docker rm -f "$CTR" >/dev/null 2>&1; docker volume rm "$VOL" >/dev/null 2>&1; rm -rf "$T"; }
trap cleanup EXIT
img=$(docker inspect -f '{{.Config.Image}}' creekwatch)
dd=$(docker image inspect -f '{{range $v, $_ := .Config.Volumes}}{{$v}}{{end}}' "$img")
docker run -d --name "$CTR" --network none -v "$VOL:$dd" "$img" >/dev/null
for _ in $(seq 1 30); do docker exec "$CTR" test -f "$dd/creekwatch.db" 2>/dev/null && break; sleep 1; done
docker exec "$CTR" python -c "
import os; from PIL import Image
d='$dd/uploads'; os.makedirs(d, exist_ok=True)
for i in range(3): Image.new('RGB',(640,480),(40*i,90,120)).save(f'{d}/seed-{i}.jpg')
" || true
n=$(docker exec "$CTR" sh -c "ls $dd/uploads 2>/dev/null | wc -l")
docker exec "$CTR" test -f "$dd/creekwatch.db" || { echo "PRECONDITION: scratch DB never appeared"; exit 2; }
[ "$n" -ge 2 ] || { echo "PRECONDITION: need >= 2 photos in the scratch volume, have $n"; exit 2; }

export CW_CONTAINER=$CTR CW_VOLUME=$VOL CW_BACKUP_HOST=local CW_BACKUP_DIR=$T/dest CW_BACKUP_STAGE=$T/stage
B="bash $T/backup.sh"; mirror() { ls "$T/dest/uploads" 2>/dev/null | wc -l; }
export SHIM_LOG=$T/shim.log; : > "$SHIM_LOG"
fails=0; bad() { echo "FAIL: $*"; fails=$((fails+1)); }

$B >/dev/null 2>&1 || bad "baseline run failed"
base=$(mirror); [ "$base" = "$n" ] || bad "baseline mirror has $base photos, expected $n"

PATH=$T/shim:$PATH SHIM_MODE=partial $B >/dev/null 2>&1 && bad "partial stream (docker cp died mid-archive) was accepted"
grep -q "files_in_cut=1" "$SHIM_LOG" || bad "partial case not exercised (shim log: $(tr '\n' ' ' < "$SHIM_LOG"))"
[ "$(mirror)" = "$base" ] || bad "mirror changed after partial stream ($(mirror) != $base)"

PATH=$T/shim:$PATH SHIM_MODE=sparse $B >/dev/null 2>&1 && bad "sparse member was accepted"
grep -q "sparse members= 1" "$SHIM_LOG" || bad "sparse case not exercised"
[ "$(mirror)" = "$base" ] || bad "mirror changed after sparse archive"

PATH=$T/shim:$PATH SHIM_MODE=many CW_BACKUP_MAX_FILES=1000 $B >/dev/null 2>&1 && bad "3000-member archive accepted with a 1000 cap"
grep -q "many members=3001" "$SHIM_LOG" || bad "member-flood case not exercised"
[ "$(mirror)" = "$base" ] || bad "mirror changed after member flood"

latest_before=$(cat "$T/dest/LATEST")
flock "$T/stage/.lock" sleep 6 & holder=$!; sleep 1
out=$($B 2>&1); rc=$?
wait $holder
{ [ $rc = 0 ] && grep -q "another backup is running" <<<"$out"; } || bad "lock not honoured (rc=$rc: $out)"

$B >/dev/null 2>&1 || bad "final normal run failed"
[ "$(mirror)" = "$base" ] || bad "final mirror has $(mirror), expected $base"

echo "shim log: $(tr '\n' ';' < "$SHIM_LOG")"
if [ $fails = 0 ]; then
  echo "PASS: $n seeded photos; partial stream, sparse member, member flood all rejected with the mirror unchanged; lock honoured; normal runs OK"
else
  echo "$fails case(s) failed"; exit 1
fi
REMOTE
