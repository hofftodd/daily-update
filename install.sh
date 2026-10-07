#!/usr/bin/env bash
# Sets up the venv, generates access tokens, and keeps the server running (starts at login, restarts on crash):
# a launchd agent on macOS, a systemd user service on Linux.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
OS="$(uname -s)"

[[ -d "$ROOT/.venv" ]] || python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
if [[ "$OS" == Darwin ]]; then
  command -v CoreLocationCLI >/dev/null || { command -v brew >/dev/null && brew install corelocationcli || true; }
fi
mkdir -p "$ROOT/data"
[[ -f "$ROOT/config.json" ]] || { cp "$ROOT/config.example.json" "$ROOT/config.json"; echo "Created config.json from config.example.json: edit places and interests."; }

# Shared secrets: DASH_TOKEN signs a browser in; LOCATION_TOKEN is for the phone's location Shortcut.
touch "$ROOT/.env" && chmod 600 "$ROOT/.env"
grep -q '^DASH_TOKEN=' "$ROOT/.env" || echo "DASH_TOKEN=$(openssl rand -hex 24)" >> "$ROOT/.env"
grep -q '^LOCATION_TOKEN=' "$ROOT/.env" || echo "LOCATION_TOKEN=$(openssl rand -hex 24)" >> "$ROOT/.env"

pkill -f "python -m core.server" 2>/dev/null || true  # a dev copy would hold the port

if [[ "$OS" == Darwin ]]; then
  LABEL=com.daily-update.server
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$ROOT/run.sh</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>$ROOT/data/launchd.log</string>
</dict>
</plist>
PL
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
else
  UNIT="$HOME/.config/systemd/user/daily-update.service"
  mkdir -p "$(dirname "$UNIT")"
  cat > "$UNIT" <<UN
[Unit]
Description=Daily Update: AI-written daily summaries dashboard
After=network-online.target llama-swap.service

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=$ROOT/run.sh
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UN
  systemctl --user daemon-reload
  systemctl --user enable daily-update.service >/dev/null
  systemctl --user restart daily-update.service
  # Without lingering, user services stop at logout and don't start at boot.
  [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" == yes ]] ||
    echo "Note: run 'sudo loginctl enable-linger $USER' so it runs at boot without a login."
fi

PORT=$(python3 -c "import json;print(json.load(open('$ROOT/config.json')).get('server',{}).get('port',8770))")
echo "Running: http://localhost:$PORT"
[[ -f "$ROOT/data/google/token.json" ]] || echo "Next: connect Google:  cd $ROOT && .venv/bin/python -m sources.google auth  (see README)."
echo "Phone: open http://$(hostname):$PORT/?token=<DASH_TOKEN from .env> once; it stays signed in."
