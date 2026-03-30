# Requires cloudflared on PATH: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
param(
    [int] $Port = 8010,
    [string] $ListenHost = "127.0.0.1"
)
$ErrorActionPreference = "Stop"
$url = "http://${ListenHost}:${Port}"
Write-Host "Forwarding $url (start uvicorn on this port first). Ctrl+C to stop." -ForegroundColor Cyan
& cloudflared tunnel --url $url
