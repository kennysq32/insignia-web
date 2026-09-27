#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Build the site on this computer and copy the project to the Mac mini.
#
#    deploy/publish.sh you@mac-mini.local
#
#  To skip the argument:     export INSIGNIA_HOST=you@mac-mini.local
#  Folder on the Mac:        ~/insignia-web  (change with INSIGNIA_REMOTE_DIR)
#
#  Needs Remote Login on the Mac (System Settings → General → Sharing).
#  The site updates the moment the copy finishes; nothing needs restarting.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HOST="${1:-${INSIGNIA_HOST:-}}"
REMOTE_DIR="${INSIGNIA_REMOTE_DIR:-insignia-web}"   # relative to the home folder on the Mac

if [ -z "$HOST" ]; then
  echo "Usage: deploy/publish.sh you@mac-mini.local" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

if grep -Eq '^base_url: *"?/' content/site.yaml; then
  echo "! base_url is set in content/site.yaml. For a site at the root of your domain it" >&2
  echo "  should be empty (base_url: \"\"), or links will point to the wrong place." >&2
fi

python3 build.py

rsync -az --delete \
  --exclude '.git/' --exclude 'tools/' --exclude '.dist-tmp*/' --exclude '.dist-old-*/' --exclude '.build.lock' --exclude '__pycache__/' --exclude '.DS_Store' \
  ./ "$HOST:$REMOTE_DIR/"

echo "✓ Published to $HOST:~/$REMOTE_DIR"
