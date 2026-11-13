[CmdletBinding()]
param(
    [switch]$Legacy
)

$ErrorActionPreference = "Stop"

if (-not $Legacy) {
    Write-Host "Starting AgentHQ with Hermes3D as the primary application..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "start-agenthq-stack.ps1")
    return
}

Write-Warning "You selected the legacy AgentHQ Vite dashboard. This is retained for reference only; normal use should start Hermes3D with .\start-agenthq-stack.ps1."
Set-Location (Join-Path $PSScriptRoot "frontend")
if (-not (Test-Path "node_modules")) {
    npm install
}
npm run dev
