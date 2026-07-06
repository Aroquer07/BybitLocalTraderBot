# Inicia ollama serve sem janela visivel.
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) { exit 1 }

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $ollama.Source
$psi.Arguments = "serve"
$psi.WorkingDirectory = $ProjectRoot
$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$psi.CreateNoWindow = $true
$psi.UseShellExecute = $false
[void][System.Diagnostics.Process]::Start($psi)

$flag = Join-Path $ProjectRoot ".run\ollama_started_by_bybitbot.flag"
$runDir = Split-Path $flag -Parent
if (-not (Test-Path $runDir)) { New-Item -ItemType Directory -Path $runDir | Out-Null }
Set-Content -Path $flag -Value (Get-Date -Format "o") -Encoding UTF8
