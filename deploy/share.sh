#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Share the site from this computer with a temporary public link.
#
#    deploy/share.sh
#
#  Prints a random https://….trycloudflare.com address you can send to a friend.
#  Anyone with the link can view the site while this runs, and they see your edits
#  as you save them. Press Ctrl+C to stop sharing. You get a new address each time.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8000
CLOUDFLARED="$(command -v cloudflared || echo tools/cloudflared)"
if [ ! -x "$CLOUDFLARED" ]; then
  echo "cloudflared is not installed. Get it from" >&2
  echo "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" >&2
  exit 1
fi

# Start the preview server unless it is already running
if ! curl -fs -o /dev/null "http://127.0.0.1:$PORT/"; then
  python3 build.py serve --port "$PORT" &
  server=$!
  trap 'kill "$server" 2>/dev/null' EXIT
  for _ in $(seq 1 20); do curl -fs -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 0.5; done
fi

echo "Starting tunnel — look for the https://….trycloudflare.com address below."
"$CLOUDFLARED" tunnel --no-autoupdate --url "http://127.0.0.1:$PORT"
