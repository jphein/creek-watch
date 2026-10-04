#!/usr/bin/env bash
# Failure-mode tests for deploy/backup.sh against the LIVE container on ubox0 (read-only for the app;
# writes a snapshot to disks like a normal run). Needs >= 2 photos in uploads for the "partial" case.
#   deploy/tests/backup-failure-modes.sh      (run from a checkout on any host)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ssh ubox0 'mkdir -p ~/creekwatch/test-shim ~/creekwatch/test-bin'
scp -q "$here/docker-shim" ubox0:creekwatch/test-shim/docker
scp -q "$here/../backup.sh" ubox0:creekwatch/test-bin/backup.sh
ssh ubox0 'set +e; chmod +x ~/creekwatch/test-shim/docker
B="bash $HOME/creekwatch/test-bin/backup.sh"; M="ssh -n disks ls /mnt/raid/backups/ubox0/creekwatch/uploads"
before=$($M | wc -l); pass=1
PATH=$HOME/creekwatch/test-shim:$PATH SHIM_MODE=partial $B >/dev/null 2>&1 && { echo "FAIL: partial stream was accepted"; pass=0; }
[ "$($M | wc -l)" = "$before" ] || { echo "FAIL: mirror changed after partial stream"; pass=0; }
PATH=$HOME/creekwatch/test-shim:$PATH SHIM_MODE=sparse $B >/dev/null 2>&1 && { echo "FAIL: sparse member was accepted"; pass=0; }
[ "$($M | wc -l)" = "$before" ] || { echo "FAIL: mirror changed after sparse archive"; pass=0; }
$B >/dev/null || { echo "FAIL: normal run failed"; pass=0; }
rm -rf ~/creekwatch/test-shim ~/creekwatch/test-bin
[ $pass = 1 ] && echo "PASS: partial stream + sparse member rejected, mirror untouched ($before photos), normal run OK"; [ $pass = 1 ]'
