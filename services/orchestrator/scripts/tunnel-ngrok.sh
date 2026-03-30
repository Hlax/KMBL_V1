#!/usr/bin/env sh
# Requires ngrok on PATH.
# Usage: ./tunnel-ngrok.sh [port]
set -e
PORT="${1:-8010}"
echo "Forwarding port ${PORT} (start uvicorn first). Ctrl+C to stop."
exec ngrok http "$PORT"
