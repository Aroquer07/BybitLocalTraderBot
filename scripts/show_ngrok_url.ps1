# Mostra a URL publica do ngrok (se ativo).
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

. (Join-Path $PSScriptRoot "ngrok_lib.ps1")

$runDir = Join-Path $ProjectRoot ".run"
$urlFile = Join-Path $runDir "ngrok_url.txt"

if (Test-Path $urlFile) {
    $url = Read-UrlFile -Path $urlFile
    if ($url) {
        Write-Host $url
        exit 0
    }
}

try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 3
    $tunnel = $resp.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1
    if (-not $tunnel) { $tunnel = $resp.tunnels | Select-Object -First 1 }
    if ($tunnel -and $tunnel.public_url) {
        Write-Host $tunnel.public_url
        exit 0
    }
} catch {}

$ngrokExe = Resolve-NgrokExe
if (-not $ngrokExe) {
    Write-Host "ngrok nao instalado ou nao esta no PATH."
} else {
    Write-Host "ngrok instalado mas tunel inativo. Rode start.bat"
}
exit 1
