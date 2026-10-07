#!/bin/sh
# Starts the server (page + API + scheduler) with the project venv; launchd (macOS) or systemd (Linux) keeps it running.
ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$ROOT/data"
cd "$ROOT" && exec "$ROOT/.venv/bin/python" -m core.server "$@" >> "$ROOT/data/server.log" 2>&1
