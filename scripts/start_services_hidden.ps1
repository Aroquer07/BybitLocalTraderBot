# Sobe bot, API, dashboard e ngrok; abre browser na URL publica quando disponivel.
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$StartDashboard = $true,
    [switch]$OpenBrowser = $true
)

$ErrorActionPreference = "Continue"

function Start-HiddenProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string]$ArgumentList = "",
        [string]$WorkingDirectory = $ProjectRoot
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $ArgumentList
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.CreateNoWindow = $true
    $psi.UseShellExecute = $false
    [void][System.Diagnostics.Process]::Start($psi)
}

function Wait-HttpOk {
    param([string]$Uri, [int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3 | Out-Null
            return $true
        } catch {}
        Start-Sleep -Seconds 2
    }
    return $false
}

$runDir = Join-Path $ProjectRoot ".run"
if (-not (Test-Path $runDir)) {
    New-Item -ItemType Directory -Path $runDir | Out-Null
}

. (Join-Path $PSScriptRoot "ngrok_lib.ps1")

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python venv nao encontrado: $python"
}

# Bot -> log em .run\bot.log
$botCmd = Join-Path $ProjectRoot "scripts\run_bot_background.cmd"
Start-HiddenProcess -FilePath "cmd.exe" -ArgumentList "/c `"$botCmd`"" -WorkingDirectory $ProjectRoot

# API dashboard
Start-HiddenProcess `
    -FilePath $python `
    -ArgumentList "-X utf8 `"$(Join-Path $ProjectRoot 'scripts\run_dashboard_api.py')`"" `
    -WorkingDirectory $ProjectRoot

# UI Vite (dashboard React)
$dashboardReady = $false
if ($StartDashboard) {
    $dashDir = Join-Path $ProjectRoot "dashboard"
    $viteBin = Join-Path $dashDir "node_modules\vite\bin\vite.js"
    if (-not (Test-Path $viteBin)) {
        Write-Host "  AVISO: dashboard sem node_modules - rode start.bat para npm install."
    } else {
        $dashCmd = Join-Path $ProjectRoot "scripts\run_dashboard_dev.cmd"
        Start-HiddenProcess `
            -FilePath "cmd.exe" `
            -ArgumentList "/c `"$dashCmd`"" `
            -WorkingDirectory $ProjectRoot
        $dashboardReady = Wait-HttpOk -Uri "http://127.0.0.1:5173" -TimeoutSeconds 90
        if ($dashboardReady) {
            Write-Host "  Dashboard OK: http://127.0.0.1:5173"
            Start-Sleep -Seconds 2
        } else {
            Write-Host "  AVISO: Dashboard nao respondeu em :5173 - veja .run\dashboard.log"
        }
    }
}

# ngrok so depois do Vite estar pronto
$dashboardUrl = "http://127.0.0.1:5173"
if ($StartDashboard -and $dashboardReady) {
    Start-Sleep -Seconds 2
    $ngrokScript = Join-Path $ProjectRoot "scripts\start_ngrok.ps1"
    if (Test-Path $ngrokScript) {
        & $ngrokScript -ProjectRoot $ProjectRoot
    }
    $ngrokFile = Join-Path $runDir "ngrok_url.txt"
    if (Test-Path $ngrokFile) {
        $remote = Read-UrlFile -Path $ngrokFile
        if ($remote) {
            $dashboardUrl = $remote
        }
    }
}

if ($OpenBrowser) {
    try {
        $openScript = Join-Path $ProjectRoot "scripts\open_dashboard.ps1"
        & $openScript -Url $dashboardUrl
    } catch {
        Write-Host "  AVISO: nao foi possivel abrir o browser: $_"
    }
} elseif (-not $dashboardReady -and $StartDashboard) {
    Write-Host "  Browser nao aberto: dashboard indisponivel."
}

# Grava URL final para o start.bat
Write-UrlFile -Path (Join-Path $runDir "dashboard_url.txt") -Url $dashboardUrl

# Garante ngrok_url no dashboard_url se existir
$ngrokFile = Join-Path $runDir "ngrok_url.txt"
if (Test-Path $ngrokFile) {
    $remote = Read-UrlFile -Path $ngrokFile
    if ($remote) {
        $dashboardUrl = $remote
        Write-UrlFile -Path (Join-Path $runDir "dashboard_url.txt") -Url $dashboardUrl
    }
}

exit 0
