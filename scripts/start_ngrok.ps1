# Expõe o dashboard (Vite :5173) via ngrok — sem OAuth por padrão.
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [int]$Port = 5173,
    [int]$WaitSeconds = 60
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "ngrok_lib.ps1")

$runDir = Join-Path $ProjectRoot ".run"
if (-not (Test-Path $runDir)) {
    New-Item -ItemType Directory -Path $runDir | Out-Null
}

$envFile = Read-DotEnv (Join-Path $ProjectRoot ".env")
$token = $envFile["NGROK_TOKEN"]
$enabledRaw = $envFile["NGROK_ENABLED"]
$oauthRaw = $envFile["NGROK_OAUTH"]
$enabled = $true
$useOAuth = $false
if ($enabledRaw) {
    $enabled = $enabledRaw -notin @("0", "false", "False", "no", "NO")
}
if ($oauthRaw) {
    $useOAuth = $oauthRaw -notin @("0", "false", "False", "no", "NO")
}

if (-not $enabled) {
    Write-Host "  ngrok desabilitado (NGROK_ENABLED=false)."
    exit 0
}
if (-not $token) {
    Write-Host "  AVISO: NGROK_TOKEN ausente no .env - dashboard apenas local."
    exit 0
}

$ngrokExe = Resolve-NgrokExe
if (-not $ngrokExe) {
    Write-Host "  AVISO: ngrok nao encontrado."
    Write-Host "         Instale: https://ngrok.com/download e adicione ao PATH"
    exit 0
}

& (Join-Path $PSScriptRoot "stop_ngrok.ps1") -ProjectRoot $ProjectRoot | Out-Null
Start-Sleep -Seconds 1

$adminEmail = $null
$adminFile = Join-Path $ProjectRoot "data\admin.json"
if (Test-Path $adminFile) {
    try {
        $adminJson = Get-Content $adminFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($adminJson.email) {
            $adminEmail = [string]$adminJson.email
            Write-Host "  Admin OAuth: $adminEmail"
        }
    } catch {}
}

# ngrok 3.20+ — traffic policy (flag --oauth deprecada)
$proc = Start-NgrokProcess -NgrokExe $ngrokExe -ProjectRoot $ProjectRoot -RunDir $runDir -Port $Port -Token $token -AdminEmail $adminEmail -UseOAuth:($useOAuth)
$proc.Id | Out-File -FilePath (Join-Path $runDir "ngrok.pid") -Encoding ascii -NoNewline
"" | Out-File -FilePath (Join-Path $runDir "ngrok_started.flag") -Encoding ascii

$publicUrl = Wait-NgrokPublicUrl -Process $proc -WaitSeconds $WaitSeconds

if (-not $publicUrl -and $proc.HasExited) {
    Write-Host "  ngrok OAuth falhou - tentando sem OAuth..."
    & (Join-Path $PSScriptRoot "stop_ngrok.ps1") -ProjectRoot $ProjectRoot | Out-Null
    Start-Sleep -Seconds 1
    $proc = Start-NgrokProcess -NgrokExe $ngrokExe -ProjectRoot $ProjectRoot -RunDir $runDir -Port $Port -Token $token
    $proc.Id | Out-File -FilePath (Join-Path $runDir "ngrok.pid") -Encoding ascii -NoNewline
    "" | Out-File -FilePath (Join-Path $runDir "ngrok_started.flag") -Encoding ascii
    $publicUrl = Wait-NgrokPublicUrl -Process $proc -WaitSeconds $WaitSeconds
}

if (-not $publicUrl) {
    Write-Host "  AVISO: ngrok nao obteve URL publica. Veja .run\ngrok.log"
    exit 0
}

Write-UrlFile -Path (Join-Path $runDir "ngrok_url.txt") -Url $publicUrl
@{
    url = $publicUrl
    port = $Port
    oauth = $(if ($useOAuth) { "google" } else { "off" })
    admin_email = $adminEmail
    started_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json | Out-File -FilePath (Join-Path $runDir "ngrok_url.json") -Encoding utf8

Write-Host "  ngrok OK: $publicUrl"
