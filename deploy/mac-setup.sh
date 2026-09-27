#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  One-time setup on the Mac mini.
#
#  Serves this project's dist/ folder at http://127.0.0.1:8080 (this Mac only)
#  as a background service that starts at boot — no login needed — and can
#  install the Cloudflare Tunnel connector that puts it on the internet.
#
#    deploy/mac-setup.sh                  set up the web server
#    deploy/mac-setup.sh <TUNNEL_TOKEN>   …and connect it to Cloudflare Tunnel
#
#  Safe to run again (after moving the folder, changing the Caddyfile, etc.).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

LABEL="com.insignia.web"
PLIST="/Library/LaunchDaemons/$LABEL.plist"
PORT=8080
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$HOME/Library/Logs/insignia-web.log"
TOKEN="${1:-}"

step() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] || fail "Run this on the Mac mini (macOS)."

# macOS keeps background services out of Desktop, Documents, Downloads and iCloud Drive
case "$PROJECT" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*|"$HOME/Library/Mobile Documents"*)
    fail "The project is in a protected folder: $PROJECT
  Background services can't read files there. Move it to ~/insignia-web and run this again." ;;
esac

# Homebrew isn't on PATH in non-interactive SSH sessions
for prefix in /opt/homebrew /usr/local; do
  if [ -x "$prefix/bin/brew" ]; then eval "$("$prefix/bin/brew" shellenv)"; break; fi
done
command -v brew >/dev/null || fail "Homebrew is required. Install it from https://brew.sh and run this again."

step "Installing Caddy (web server) and cloudflared (tunnel connector)"
for formula in caddy cloudflared; do
  if brew list --formula "$formula" >/dev/null 2>&1; then
    echo "  $formula is already installed"
  else
    brew install "$formula"
  fi
done
CADDY="$(brew --prefix)/bin/caddy"
CLOUDFLARED="$(brew --prefix)/bin/cloudflared"

step "Checking the site"
[ -f "$PROJECT/dist/index.html" ] || fail "There is no built site in $PROJECT/dist
  Run deploy/publish.sh on the computer where you edit the site (or python3 build.py here)."
if ! out="$(cd "$PROJECT" && "$CADDY" validate --config deploy/Caddyfile --adapter caddyfile 2>&1)"; then
  echo "$out" | tail -n 5
  fail "deploy/Caddyfile has an error (above)."
fi
echo "  dist/ and deploy/Caddyfile look good"

step "Installing the web server as a service that starts at boot (asks for your Mac password)"
mkdir -p "$(dirname "$LOG")"
tmp="$(mktemp)"
cat > "$tmp" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>UserName</key>
  <string>$(id -un)</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT</string>
  <key>ProgramArguments</key>
  <array>
    <string>$CADDY</string>
    <string>run</string>
    <string>--config</string>
    <string>deploy/Caddyfile</string>
    <string>--adapter</string>
    <string>caddyfile</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>$HOME</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG</string>
  <key>StandardErrorPath</key>
  <string>$LOG</string>
</dict>
</plist>
EOF
plutil -lint "$tmp" >/dev/null || fail "The generated service file is invalid: $tmp"

sudo launchctl bootout "system/$LABEL" 2>/dev/null || true
sleep 1
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
  fail "Port $PORT is already used by the program above. Stop it, or change 8080 in deploy/Caddyfile and in this script."
fi
sudo install -m 644 -o root -g wheel "$tmp" "$PLIST"
rm -f "$tmp"
sudo launchctl enable "system/$LABEL"
sudo launchctl bootstrap system "$PLIST"

step "Testing"
ok=""
for _ in $(seq 1 20); do
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/"; then ok=1; break; fi
  sleep 0.5
done
if [ -z "$ok" ]; then
  tail -n 20 "$LOG" 2>/dev/null || true
  fail "The web server didn't start. Full log: $LOG"
fi
echo "  ✓ Serving $PROJECT/dist at http://127.0.0.1:$PORT (reachable from this Mac only)"

if [ -n "$TOKEN" ]; then
  step "Connecting to Cloudflare Tunnel"
  if [ -f /Library/LaunchDaemons/com.cloudflare.cloudflared.plist ]; then
    echo "  Replacing the cloudflared service that is already installed"
    sudo "$CLOUDFLARED" service uninstall || true
    sleep 1
  fi
  sudo "$CLOUDFLARED" service install "$TOKEN"
  echo "  ✓ Tunnel connector installed; it starts at boot."
  echo "    Logs: /Library/Logs/com.cloudflare.cloudflared.err.log"
  cat <<EOF

Last step, in the Cloudflare dashboard: open the tunnel → Routes → Add route →
Published application, pick your subdomain and domain, and set
    Service URL:  http://127.0.0.1:$PORT
EOF
else
  cat <<EOF

Next — put it on the internet (details in deploy/README.md):
  1. Cloudflare dashboard → Networking → Tunnels → Create a tunnel (Cloudflared).
  2. On the install screen choose macOS and copy the token: the long string after
     "service install". Keep it private — it lets anyone run your tunnel.
  3. On this Mac:  $PROJECT/deploy/mac-setup.sh <TOKEN>

Try it right now without a domain (temporary random address, Ctrl+C to stop):
     cloudflared tunnel --url http://127.0.0.1:$PORT
EOF
fi

cat <<EOF

Keep the Mac awake: System Settings → Energy → turn on "Prevent automatic sleeping
when the display is off" and "Start up automatically after a power failure".
EOF
