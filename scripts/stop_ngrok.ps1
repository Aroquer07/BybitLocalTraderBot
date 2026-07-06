# Encerra tunel ngrok do BybitBot.
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "SilentlyContinue"
$runDir = Join-Path $ProjectRoot ".run"
$pidFile = Join-Path $runDir "ngrok.pid"

if (Test-Path $pidFile) {
    $raw = (Get-Content $pidFile -Raw).Trim()
    if ($raw -match '^\d+$') {
        $processId = [int]$raw
        Write-Host "  Stopping ngrok PID $processId"
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path (Join-Path $runDir "ngrok_started.flag")) {
    Get-CimInstance Win32_Process -Filter "name='ngrok.exe'" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "  Stopping ngrok.exe PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Remove-Item (Join-Path $runDir "ngrok_started.flag") -Force -ErrorAction SilentlyContinue
}

Remove-Item (Join-Path $runDir "ngrok_url.txt") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $runDir "ngrok_url.json") -Force -ErrorAction SilentlyContinue
