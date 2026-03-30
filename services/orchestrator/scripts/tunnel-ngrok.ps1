# Requires ngrok on PATH: https://ngrok.com/download
param([int] $Port = 8010)
$ErrorActionPreference = "Stop"
Write-Host "Forwarding port $Port (start uvicorn first). Ctrl+C to stop." -ForegroundColor Cyan
& ngrok http $Port
