param(
    [int]$Hours = 24
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot
docker compose run --rm horizon --hours $Hours

Write-Host ""
Write-Host "Horizon summaries are written under F:\InforDetection\Horizon\data\summaries"
