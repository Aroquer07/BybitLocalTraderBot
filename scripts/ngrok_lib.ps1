# Localiza ngrok.exe no PATH ou pastas comuns do Windows.
function Resolve-NgrokExe {
    $cmd = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "ngrok\ngrok.exe")
        (Join-Path $env:USERPROFILE "scoop\shims\ngrok.exe")
        "C:\ProgramData\chocolatey\bin\ngrok.exe"
        (Join-Path $env:ProgramFiles "ngrok\ngrok.exe")
        (Join-Path ${env:ProgramFiles(x86)} "ngrok\ngrok.exe")
        "C:\tools\ngrok\ngrok.exe"
    )
    $wingetRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $wingetRoot) {
        Get-ChildItem -Path $wingetRoot -Filter "ngrok.exe" -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 3 -ExpandProperty FullName |
            ForEach-Object { $candidates += $_ }
    }
    $wingetLink = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\ngrok.exe"
    if (Test-Path $wingetLink) { $candidates += $wingetLink }
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    return $null
}

function Read-DotEnv {
    param([string]$Path)
    $map = @{}
    if (-not (Test-Path $Path)) { return $map }
    $raw = Get-Content $Path -Raw -Encoding UTF8
    if ($raw.Length -gt 0 -and [int][char]$raw[0] -eq 0xFEFF) {
        $raw = $raw.Substring(1)
    }
    foreach ($line in ($raw -split "`r?`n")) {
        $line = $line.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { continue }
        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim()
        $map[$key] = $val
    }
    return $map
}

function Read-UrlFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return "" }
    $raw = [System.IO.File]::ReadAllText($Path).Trim()
    if ($raw.Length -gt 0 -and [int][char]$raw[0] -eq 0xFEFF) {
        $raw = $raw.Substring(1).Trim()
    }
    return $raw
}

function Write-UrlFile {
    param(
        [string]$Path,
        [string]$Url
    )
    [System.IO.File]::WriteAllText($Path, $Url.Trim(), [System.Text.UTF8Encoding]::new($false))
}

function Write-NgrokOAuthPolicy {
    param(
        [string]$Path,
        [string]$AdminEmail = ""
    )
    $base = Join-Path $PSScriptRoot "ngrok-oauth-policy.yaml"
    if (-not (Test-Path $base)) {
        throw "Policy base nao encontrada: $base"
    }
    $content = Get-Content $base -Raw -Encoding UTF8
    if ($AdminEmail) {
        $escaped = $AdminEmail.Replace("'", "''")
        $content += @"

  - expressions:
      - "actions.ngrok.oauth.identity.email != '$escaped'"
    actions:
      - type: deny
        config:
          status_code: 403
          body: Acesso negado. Apenas o administrador pode acessar.
"@
    }
    [System.IO.File]::WriteAllText($Path, $content.TrimEnd(), [System.Text.UTF8Encoding]::new($false))
}

function Start-NgrokProcess {
    param(
        [string]$NgrokExe,
        [string]$ProjectRoot,
        [string]$RunDir,
        [int]$Port,
        [string]$Token,
        [string]$AdminEmail = "",
        [switch]$UseOAuth
    )
    $logFile = Join-Path $RunDir "ngrok.log"
    $argList = @(
        "http", "$Port",
        "--authtoken=$Token",
        "--log=$logFile",
        "--log-level=info"
    )
    if ($UseOAuth) {
        $policyFile = Join-Path $RunDir "ngrok-policy.yaml"
        Write-NgrokOAuthPolicy -Path $policyFile -AdminEmail $AdminEmail
        $argList += "--traffic-policy-file=$policyFile"
    }

    return Start-Process `
        -FilePath $NgrokExe `
        -ArgumentList $argList `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru
}

function Wait-NgrokPublicUrl {
    param(
        [System.Diagnostics.Process]$Process,
        [int]$WaitSeconds = 60
    )
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 3
            $tunnel = $resp.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1
            if (-not $tunnel) { $tunnel = $resp.tunnels | Select-Object -First 1 }
            if ($tunnel -and $tunnel.public_url) {
                return $tunnel.public_url
            }
        } catch {}
        if ($Process.HasExited) { return $null }
        Start-Sleep -Seconds 2
    }
    return $null
}
