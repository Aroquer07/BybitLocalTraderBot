# Garante ambiente local completo: .venv, pip deps, npm deps, pasta .run
# Nao desinstala nada - apenas cria/sincroniza o que falta ou mudou em requirements.
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

function Write-Step([string]$Message) {
    Write-Host "  $Message"
}

Write-Host "[env] Preparando ambiente em $ProjectRoot"

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $ProjectRoot "requirements.txt"

if (-not (Test-Path $requirements)) {
    throw "requirements.txt nao encontrado: $requirements"
}

if (-not (Test-Path $venvPython)) {
    Write-Step "Criando .venv..."
    $created = $false
    try {
        & py -3 -m venv (Join-Path $ProjectRoot ".venv")
        if ($LASTEXITCODE -eq 0) { $created = $true }
    } catch {}
    if (-not $created) {
        & python -m venv (Join-Path $ProjectRoot ".venv")
        if ($LASTEXITCODE -ne 0) {
            throw "Nao foi possivel criar .venv (instale Python 3.11+)"
        }
    }
}

if (-not (Test-Path $venvPython)) {
    throw "Python do venv nao encontrado: $venvPython"
}

Write-Step "Atualizando pip..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade falhou" }

Write-Step "Sincronizando dependencias Python (requirements.txt)..."
& $venvPython -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements.txt falhou" }

$runDir = Join-Path $ProjectRoot ".run"
if (-not (Test-Path $runDir)) {
    Write-Step "Criando pasta .run..."
    New-Item -ItemType Directory -Path $runDir | Out-Null
}

$npm = Get-Command npm -ErrorAction SilentlyContinue
$dashDir = Join-Path $ProjectRoot "dashboard"
$packageJson = Join-Path $dashDir "package.json"

if ($npm -and (Test-Path $packageJson)) {
    $nodeModules = Join-Path $dashDir "node_modules"
    if (Test-Path $nodeModules) {
        Write-Step "Sincronizando dependencias npm (dashboard)..."
    } else {
        Write-Step "Instalando dependencias npm (primeira vez)..."
    }
    Push-Location $dashDir
    try {
        & npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install falhou em dashboard/" }
    } finally {
        Pop-Location
    }
} else {
    Write-Step "AVISO: npm ou dashboard/package.json ausente - UI nao sera preparada."
}

Write-Host '[env] Ambiente pronto - .venv e deps sincronizados; nada foi desinstalado.'
exit 0
