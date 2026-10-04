#!/usr/bin/env bash
# Tests deploy/secrets.sh's transport with a THROWAWAY VAPID keypair (never the real one, no vault needed):
# vault-shaped KEY=VALUE lines -> install-lines (ssh stdin) -> ubox0 env-file -> a scratch container.
# Asserts: 0600 + owner, merge keeps other keys, malformed lines refused, value intact in the container
# (compared by sha256, never printed), and the value appears in no journal/container log.
#   deploy/tests/secrets-plumbing.sh        Exit 0 pass, 1 fail.
set -uo pipefail   # no -e: every assertion must run and report
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$here/../secrets.sh"; host="${CW_DEPLOY_HOST:-ubox0}"
F="~/creekwatch/test-app-$$.env"; fails=0; bad() { echo "FAIL: $*"; fails=$((fails+1)); }
start=$(ssh "$host" "date '+%F %T'")
cleanup() { ssh "$host" "rm -f $F; docker rm -f cw-sectest-$$ >/dev/null 2>&1" || true; }
trap cleanup EXIT

gen() { uv run -q --with cryptography python3 -c '
import base64, hashlib, sys
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
k = ec.generate_private_key(ec.SECP256R1())
priv = b64(k.private_numbers().private_value.to_bytes(32, "big"))
pub = b64(k.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
print(f"CREEKWATCH_VAPID_PRIVATE={priv}\nCREEKWATCH_VAPID_PUBLIC={pub}\nCREEKWATCH_VAPID_SUBJECT=mailto:test@example.invalid")
print(hashlib.sha256(priv.encode()).hexdigest(), file=sys.stderr)'; }

# 1) pre-existing unrelated line must survive
ssh "$host" "umask 077; echo CREEKWATCH_OTHER=keepme > $F"
want=$( { gen | CW_APP_ENV_REMOTE="$F" CW_NO_APPLY=1 "$S" install-lines; } 2>&1 >/dev/null | grep -E '^[0-9a-f]{64}$' )
[ -n "$want" ] || bad "no throwaway key hash captured"

mode=$(ssh "$host" "stat -c '%a %U' $F"); me=$(ssh "$host" whoami)
[ "$mode" = "600 $me" ] || bad "env-file is '$mode', want '600 $me'"
names=$(ssh "$host" "cut -d= -f1 $F | sort | tr '\n' ' '")
[ "$names" = "CREEKWATCH_OTHER CREEKWATCH_VAPID_PRIVATE CREEKWATCH_VAPID_PUBLIC CREEKWATCH_VAPID_SUBJECT " ] || bad "names: $names"
got=$(ssh "$host" "grep ^CREEKWATCH_VAPID_PRIVATE= $F | cut -d= -f2- | tr -d '\n' | sha256sum | cut -d' ' -f1")
[ "$got" = "$want" ] || bad "private value changed in transit"

# 2) re-install replaces (no duplicate lines)
{ gen | CW_APP_ENV_REMOTE="$F" CW_NO_APPLY=1 "$S" install-lines; } >/dev/null 2>&1
[ "$(ssh "$host" "wc -l < $F")" = 4 ] || bad "re-install duplicated lines"

# 3) malformed input refused, file unchanged
before=$(ssh "$host" "sha256sum < $F")
printf 'CREEKWATCH_VAPID_PRIVATE=has space\n' | CW_APP_ENV_REMOTE="$F" CW_NO_APPLY=1 "$S" install-lines >/dev/null 2>&1 && bad "malformed line accepted"
[ "$(ssh "$host" "sha256sum < $F")" = "$before" ] || bad "file changed after a refused write"

# 4) value reaches a hardened scratch container intact; 5) never in logs
want=$(ssh "$host" "grep ^CREEKWATCH_VAPID_PRIVATE= $F | cut -d= -f2- | tr -d '\n' | sha256sum | cut -d' ' -f1")
ssh "$host" "img=\$(docker inspect -f '{{.Config.Image}}' creekwatch)
  docker run -d --name cw-sectest-$$ --network none --cap-drop ALL --security-opt no-new-privileges --env-file $F \$img >/dev/null; sleep 4"
inside=$(ssh "$host" "docker exec cw-sectest-$$ sh -c 'printf %s \"\$CREEKWATCH_VAPID_PRIVATE\" | sha256sum' | cut -d' ' -f1")
[ -n "$inside" ] && [ "$inside" = "$want" ] || bad "container sees a different/empty private value ($inside)"
leaks=$(ssh "$host" "v=\$(grep ^CREEKWATCH_VAPID_PRIVATE= $F | cut -d= -f2-)
  { sudo journalctl --since '$start' --no-pager -o cat; docker logs cw-sectest-$$ 2>&1; } | grep -cF -f <(printf '%s\n' \"\$v\") || true")
[ "$leaks" = 0 ] || bad "private value found $leaks time(s) in journal/container logs"

[ $fails = 0 ] && echo "PASS: transport via ssh stdin, 0600+owner, merge keeps other keys, re-install replaces, malformed refused, value intact in a hardened container, 0 log leaks"
[ $fails = 0 ]
