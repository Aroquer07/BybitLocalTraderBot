# Encerra API e UI do dashboard BybitBot (processos por PID — nao mata navegador).
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "SilentlyContinue"
$runDir = Join-Path $ProjectRoot ".run"
$killed = 0

. (Join-Path $PSScriptRoot "process_lib.ps1")

foreach ($name in @("api.pid", "dashboard.pid")) {
    $pidFile = Join-Path $runDir $name
    if (Test-Path $pidFile) {
        $raw = (Get-Content $pidFile -Raw).Trim()
        if ($raw -match '^\d+$') {
            $processId = [int]$raw
            Write-Host "  Stopping $name -> $processId"
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            $killed++
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

# Nao usar taskkill por WINDOWTITLE — titulo "BybitBot Dashboard" no Opera seria fechado.

Get-CimInstance Win32_Process -Filter "name='python.exe'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($cmd -like "*run_dashboard_api.py*") {
        Write-Host "  Stopping dashboard API PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }
}

Get-CimInstance Win32_Process -Filter "name='node.exe'" | ForEach-Object {
    $cmd = [string]$_.CommandLine
    $isVite = $cmd -like "*vite*"
    $isOurDashboard = ($cmd -like "*$ProjectRoot*") -or ($cmd -like "*\dashboard\*") -or ($cmd -like "*vite.js*")
    if ($isVite -and $isOurDashboard) {
        Write-Host "  Stopping node PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }
}

$killed += Stop-ListenersOnPorts -Ports @(8765, 5173) -Label "dashboard listener"

if ($killed -eq 0) {
    Write-Host "  No dashboard processes found."
} else {
    Write-Host "  Dashboard stop complete."
}
