#!/usr/bin/env bash
# Idempotent install on ubox0: copies redeploy.sh + backup.sh to ~/creekwatch/bin, enables the redeploy poll
# timer and the hourly backup timer. The alert-poll units are installed but NOT enabled (see README). Re-run to adopt changed scripts (they never self-update from main).
#   deploy/install.sh            (run from a checkout on any host; re-execs on ubox0)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
host="${CW_DEPLOY_HOST:-ubox0}"
if [ "$(hostname -s)" != "$host" ]; then
  ssh "$host" 'mkdir -p ~/creekwatch/bin ~/creekwatch/units'
  scp -q "$here/redeploy.sh" "$here/backup.sh" "$here/poll.sh" "$host:creekwatch/bin/"
  scp -q "$here"/creekwatch-redeploy.{service,timer} "$here"/creekwatch-backup.{service,timer} "$here"/creekwatch-poll.{service,timer} "$host:creekwatch/units/"
  exec ssh "$host" 'chmod +x ~/creekwatch/bin/redeploy.sh ~/creekwatch/bin/backup.sh ~/creekwatch/bin/poll.sh &&
    sudo install -m 644 ~/creekwatch/units/creekwatch-*.service ~/creekwatch/units/creekwatch-*.timer /etc/systemd/system/ &&
    sudo systemctl daemon-reload && sudo systemctl enable --now creekwatch-redeploy.timer creekwatch-backup.timer &&
    systemctl list-timers "creekwatch-*" --no-pager'
fi
