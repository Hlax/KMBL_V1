#!/usr/bin/env sh
# Requires cloudflared on PATH.
# Usage: ./tunnel-cloudflared.sh [port]
set -e
PORT="${1:-8010}"
echo "Forwarding http://127.0.0.1:${PORT} (start uvicorn on this port first). Ctrl+C to stop."
exec cloudflared tunnel --url "http://127.0.0.1:${PORT}"
