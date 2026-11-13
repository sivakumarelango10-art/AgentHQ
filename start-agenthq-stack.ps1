[CmdletBinding()]
param(
    [string]$Hermes3DPath = "E:\Hermes3D",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$BackendPath = Join-Path $PSScriptRoot "backend"
$BackendRunner = Join-Path $BackendPath "run.ps1"

function Test-TcpPort {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($pending)
        return $true
    }
    catch { return $false }
    finally { $client.Dispose() }
}

function Test-AgentHQApi {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method Get -TimeoutSec 4
        return ($health.ok -eq $true -and $health.runtime -eq "AgentHQ")
    }
    catch { return $false }
}

function Test-Hermes3DPage {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:3000/office" -Method Get -TimeoutSec 5
        return ($response.StatusCode -eq 200 -and $response.Content -match "HERMES3D|Next.js|office")
    }
    catch { return $false }
}

function Start-ServiceTerminal {
    param([string]$WorkingDirectory, [string]$Command)

    $escapedDirectory = $WorkingDirectory.Replace("'", "''")
    $terminalCommand = "Set-Location -LiteralPath '$escapedDirectory'; $Command"
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($terminalCommand))
    $arguments = "-NoExit -NoProfile -ExecutionPolicy Bypass -EncodedCommand $encodedCommand"
    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -WorkingDirectory $WorkingDirectory | Out-Null
}

function Wait-ForService {
    param([scriptblock]$Check, [string]$ServiceName, [int]$TimeoutSeconds = 120)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Check) {
            Write-Host "$ServiceName is ready." -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "$ServiceName did not become ready within $TimeoutSeconds seconds. Check its PowerShell terminal."
}

if (-not (Test-Path $BackendRunner)) { throw "AgentHQ backend runner not found: $BackendRunner" }
if (-not (Test-Path $Hermes3DPath)) { throw "Hermes3D folder not found: $Hermes3DPath. Pass the correct folder using -Hermes3DPath." }
if (-not (Test-Path (Join-Path $Hermes3DPath "package.json"))) { throw "Hermes3D package.json not found in $Hermes3DPath" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm was not found. Install Node.js and reopen PowerShell." }

Write-Host ""
Write-Host "AgentHQ - Hermes3D-first startup" -ForegroundColor Cyan
Write-Host "Backend:  $BackendPath"
Write-Host "Studio:   $Hermes3DPath"
Write-Host "UI:       http://127.0.0.1:3000/office"
Write-Host ""

# Ollama is checked but not launched here; the installed Ollama service owns its lifecycle.
try {
    $ollama = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 3
    $hasQwen = @($ollama.models | Where-Object { $_.name -like "qwen3:4b*" }).Count -gt 0
    if ($hasQwen) {
        Write-Host "Ollama and qwen3:4b are available." -ForegroundColor Green
    }
    else {
        Write-Warning "Ollama is reachable, but qwen3:4b was not found in /api/tags."
    }
}
catch {
    Write-Warning "Ollama is not reachable at 127.0.0.1:11434. Chat will not work until Ollama is started."
}

# Start AgentHQ's data/runtime API only. Do not start the legacy Vite UI.
if (Test-AgentHQApi) {
    Write-Host "AgentHQ API is already running on port 8000." -ForegroundColor Green
}
elseif (Test-TcpPort -Port 8000) {
    throw "Port 8000 is occupied, but /health did not identify AgentHQ. Inspect that process before continuing."
}
else {
    Write-Host "Starting AgentHQ FastAPI in a new terminal..." -ForegroundColor Yellow
    Start-ServiceTerminal -WorkingDirectory $BackendPath -Command "Set-ExecutionPolicy -Scope Process Bypass -Force; .\run.ps1"
    Wait-ForService -Check { Test-AgentHQApi } -ServiceName "AgentHQ API" -TimeoutSeconds 90
}

# Start Hermes3D as the only browser application.
if (Test-Hermes3DPage) {
    Write-Host "Hermes3D Studio is already serving /office on port 3000." -ForegroundColor Green
}
elseif (Test-TcpPort -Port 3000) {
    throw "Port 3000 is occupied, but it did not serve the Hermes3D office page. Inspect that process before continuing."
}
else {
    Write-Host "Starting Hermes3D Studio in a new terminal..." -ForegroundColor Yellow
    Start-ServiceTerminal -WorkingDirectory $Hermes3DPath -Command "npm run dev"
    Wait-ForService -Check { Test-Hermes3DPage } -ServiceName "Hermes3D Studio" -TimeoutSeconds 180
}

Write-Host ""
Write-Host "Startup checks complete." -ForegroundColor Green
Write-Host "Use Hermes3D as the AgentHQ application: http://127.0.0.1:3000/office" -ForegroundColor Cyan
Write-Host "Connect its Custom backend to http://127.0.0.1:8000." -ForegroundColor Cyan
Write-Host "The old AgentHQ Vite UI on port 5173 is intentionally not started." -ForegroundColor DarkGray

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:3000/office"
}
