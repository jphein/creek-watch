#!/usr/bin/env bash
# One-time (idempotent) install on ubox0: copies redeploy.sh to ~/creekwatch/bin and enables the poll timer.
#   deploy/install.sh            (run from a checkout on any host; re-execs on ubox0)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
host="${CW_DEPLOY_HOST:-ubox0}"
if [ "$(hostname -s)" != "$host" ]; then
  ssh "$host" 'mkdir -p ~/creekwatch/bin ~/creekwatch/units'
  scp -q "$here/redeploy.sh" "$host:creekwatch/bin/redeploy.sh"
  scp -q "$here/creekwatch-redeploy.service" "$here/creekwatch-redeploy.timer" "$host:creekwatch/units/"
  exec ssh "$host" 'chmod +x ~/creekwatch/bin/redeploy.sh &&
    sudo install -m 644 ~/creekwatch/units/creekwatch-redeploy.* /etc/systemd/system/ &&
    sudo systemctl daemon-reload && sudo systemctl enable --now creekwatch-redeploy.timer &&
    systemctl list-timers creekwatch-redeploy.timer --no-pager'
fi
