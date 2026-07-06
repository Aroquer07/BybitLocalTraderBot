# Encerra todas as instâncias do BybitBot (main.py), incluindo processos filho do venv.
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "SilentlyContinue"
$pidFile = Join-Path $ProjectRoot ".run\bot.pid"
$killed = [System.Collections.Generic.HashSet[int]]::new()

function Stop-Tree([int]$ProcessId) {
    if ($ProcessId -le 0 -or $killed.Contains($ProcessId)) { return }
    [void]$killed.Add($ProcessId)
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" |
        ForEach-Object { Stop-Tree $_.ProcessId }
    Write-Host "  PID $ProcessId"
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Test-BybitBotProcess([string]$CommandLine, [string]$ExecutablePath) {
    if ($CommandLine -notmatch 'main\.py') { return $false }
    $root = $ProjectRoot
    return ($CommandLine -like "*$root*") -or ($ExecutablePath -like "*$root*")
}

# 1) PID gravado pelo main.py
if (Test-Path $pidFile) {
    $raw = (Get-Content $pidFile -Raw).Trim()
    if ($raw -match '^\d+$') {
        Write-Host "  via bot.pid -> $raw"
        Stop-Tree ([int]$raw)
    }
}

# 2) Varredura — pega venv shim, filho do Python e caminhos relativos
Get-CimInstance Win32_Process -Filter "name='python.exe'" | ForEach-Object {
    if (Test-BybitBotProcess $_.CommandLine $_.ExecutablePath) {
        Stop-Tree $_.ProcessId
    }
}

if ($killed.Count -eq 0) {
    Write-Host "  Nenhum processo main.py encontrado."
} else {
    Write-Host "  Encerrados: $($killed.Count) processo(s)."
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
