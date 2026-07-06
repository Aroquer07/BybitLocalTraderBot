# Abre o dashboard no navegador (ngrok ou local). Nao espera OAuth responder.
param(
    [string]$Url = "",
    [int]$WaitApiSeconds = 60
)

$ErrorActionPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "ngrok_lib.ps1")
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$runDir = Join-Path $projectRoot ".run"
$ngrokFile = Join-Path $runDir "ngrok_url.txt"

# Prioridade: parametro > ngrok_url.txt > dashboard_url.txt > localhost
if (-not $Url) {
    if (Test-Path $ngrokFile) {
        $Url = Read-UrlFile -Path $ngrokFile
    }
}
if (-not $Url) {
    $dashFile = Join-Path $runDir "dashboard_url.txt"
    if (Test-Path $dashFile) {
        $Url = Read-UrlFile -Path $dashFile
    }
}
if (-not $Url) {
    $Url = "http://127.0.0.1:5173"
}

$isRemote = $Url -match "^https://"

# Espera so a API local
$deadline = (Get-Date).AddSeconds($WaitApiSeconds)
while ((Get-Date) -lt $deadline) {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
        break
    } catch {}
    Start-Sleep -Seconds 2
}

Write-Host "  Abrindo dashboard: $Url"

# start abre nova aba no navegador padrao (Opera se for default) sem fechar o resto
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "start", '""', $Url -WindowStyle Hidden
