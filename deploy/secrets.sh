#!/usr/bin/env bash
# Creek Watch secrets: Vaultwarden is the source of truth; ubox0 gets a 0600 env-file OUTSIDE the repo.
# Secret values never appear in argv, logs, the repo, or the image: they only travel through pipes.
#
#   deploy/secrets.sh init        # one time: generate a VAPID P-256 keypair straight into a NEW vault item
#                                 #   "creekwatch VAPID" (refuses if it exists). Run where `bw` is unlocked.
#   deploy/secrets.sh install     # vault -> ubox0:~/creekwatch/app.env (0600), then redeploy to apply.
#   deploy/secrets.sh status      # which CREEKWATCH_* names are set on ubox0 and in the container (no values)
#   deploy/secrets.sh install-lines  # stdin KEY=VALUE lines -> ubox0 app.env (used by install; tests)
#   deploy/secrets.sh write-env   # on ubox0: merge KEY=VALUE lines from stdin into app.env
#
# Env contract (backend reads these): CREEKWATCH_VAPID_PRIVATE (raw 32-byte P-256 scalar, base64url, no pad),
# CREEKWATCH_VAPID_PUBLIC (65-byte uncompressed point, base64url, no pad), CREEKWATCH_VAPID_SUBJECT (https URL or mailto:).
set -euo pipefail

ITEM="${CW_VAPID_ITEM:-creekwatch VAPID}"
HOST="${CW_DEPLOY_HOST:-ubox0}"
SUBJECT="${CW_VAPID_SUBJECT:-https://creekwatch.realm.watch}"   # RFC 8292 allows https; no unmonitored mailbox
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log() { printf '%s secrets: %s\n' "$(date '+%F %T %Z')" "$*" >&2; }

item_exists() { bw list items --search "$ITEM" | python3 -c '
import sys, json; name = sys.argv[1]
sys.exit(0 if any(i.get("name") == name for i in json.load(sys.stdin)) else 1)' "$ITEM"; }

# Env-file writer (runs on ubox0). stdin = KEY=VALUE lines; replaces those keys, keeps others; atomic, 0600.
# Not secret itself, so it can travel as the ssh command; only the values ride on stdin.
WRITER='
import os, sys, re, tempfile
path = os.path.expanduser(sys.argv[1])
new = [l.rstrip("\n") for l in sys.stdin if l.strip()]
keys = set()
for l in new:
    if not re.fullmatch(r"CREEKWATCH_[A-Z0-9_]+=[^\s]+", l): sys.exit("refusing malformed env line")
    keys.add(l.split("=", 1)[0])
if not keys: sys.exit("no env lines on stdin")
old = []
if os.path.exists(path):
    with open(path) as fh:
        old = [l.rstrip("\n") for l in fh if l.strip() and l.split("=", 1)[0] not in keys]
d = os.path.dirname(path); os.makedirs(d, exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=d, prefix=".app.env.")
with os.fdopen(fd, "w") as fh:
    fh.write("\n".join(old + new) + "\n")
os.chmod(tmp, 0o600); os.replace(tmp, path)
print(f"wrote {path} (0600): set {sorted(keys)}; kept {len(old)} other line(s)", file=sys.stderr)
'

case "${1:-}" in
init)
  [ "$(bw status | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')" = unlocked ] \
    || { log "vault is locked: unlock it first (JP's master password)"; exit 1; }
  if item_exists; then log "vault item '$ITEM' already exists; refusing to overwrite (rotate deliberately)"; exit 1; fi
  # Template in, item JSON (with fresh keys) out; the private key exists only inside this pipe.
  bw get template item | uv run -q --with cryptography python3 -c '
import sys, json, base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
k = ec.generate_private_key(ec.SECP256R1())
priv = b64(k.private_numbers().private_value.to_bytes(32, "big"))
pub = b64(k.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
t = json.load(sys.stdin)
t.update(type=2, name=sys.argv[1], secureNote={"type": 0}, login=None,
         notes="Creek Watch Web Push VAPID keypair. Installed to ubox0 by deploy/secrets.sh install. "
               "Rotating invalidates every existing push subscription.",
         fields=[{"name": "CREEKWATCH_VAPID_PRIVATE", "value": priv, "type": 1},
                 {"name": "CREEKWATCH_VAPID_PUBLIC", "value": pub, "type": 0},
                 {"name": "CREEKWATCH_VAPID_SUBJECT", "value": sys.argv[2], "type": 0}])
print(json.dumps(t))' "$ITEM" "$SUBJECT" | bw encode | bw create item \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print("created vault item", d["id"], repr(d["name"]))'
  ;;
install)
  item_exists || { log "no vault item '$ITEM' (run: deploy/secrets.sh init)"; exit 1; }
  # Vault -> KEY=VALUE lines -> ssh stdin -> write-env on ubox0. Nothing is echoed.
  bw get item "$ITEM" | python3 -c '
import sys, json, re
f = {x["name"]: x["value"] for x in json.load(sys.stdin).get("fields", [])}
need = ["CREEKWATCH_VAPID_PRIVATE", "CREEKWATCH_VAPID_PUBLIC", "CREEKWATCH_VAPID_SUBJECT"]
for k in need:
    v = f.get(k) or ""
    if not v or re.search(r"[\s=\x00]", v): sys.exit(f"vault field {k} missing or malformed")
    print(f"{k}={v}")' | "$0" install-lines
  ;;
install-lines)
  # stdin = KEY=VALUE lines -> ubox0 env-file over ssh stdin (the values never touch argv), then apply.
  # CW_APP_ENV_REMOTE / CW_NO_APPLY exist for deploy/tests only.
  ssh "$HOST" "python3 -c $(printf '%q' "$WRITER") $(printf '%q' "${CW_APP_ENV_REMOTE:-~/creekwatch/app.env}")"
  [ -n "${CW_NO_APPLY:-}" ] && exit 0
  log "installed; applying with a redeploy of origin/main"
  "$here/redeploy.sh"
  ;;
write-env)
  # ubox0 side (manual use / tests). stdin = KEY=VALUE lines.
  python3 -c "$WRITER" "${CW_APP_ENV:-$HOME/creekwatch/app.env}"
  ;;
status)
  ssh "$HOST" 'f=~/creekwatch/app.env; [ -f "$f" ] && stat -c "app.env %a %U %s bytes" "$f" && cut -d= -f1 "$f" | sed "s/^/  file: /";
    docker exec creekwatch sh -c "env | cut -d= -f1 | grep ^CREEKWATCH_ | sort" | sed "s/^/  container: /"'
  ;;
*) sed -n '2,13p' "$0"; exit 2 ;;
esac
