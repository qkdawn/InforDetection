Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot
docker compose up -d rsshub

Write-Host ""
Write-Host "RSSHub is starting at http://localhost:1200"
Write-Host "Health check: http://localhost:1200/healthz"
