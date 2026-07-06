@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

title BybitBot - Start
echo.
echo ========================================
echo   BybitBot - Iniciando
echo ========================================
echo.

REM --- Python / venv ---
if exist ".venv\Scripts\python.exe" (
    echo [1/5] venv OK
) else (
    echo [1/5] Criando ambiente virtual...
    py -3 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
    if errorlevel 1 (
        echo ERRO: nao foi possivel criar o .venv
        pause
        exit /b 1
    )
    echo [1/5] Instalando dependencias Python...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

REM --- Ollama (opcional) ---
echo [2/5] Verificando Ollama...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -UseBasicParsing -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo       Ollama offline - iniciando...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_ollama_hidden.ps1"
    ping -n 6 127.0.0.1 >nul
) else (
    echo       Ollama OK
)

REM --- Encerra instancias antigas ---
echo [3/5] Encerrando instancias antigas...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_bot.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_dashboard.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_ngrok.ps1"
ping -n 4 127.0.0.1 >nul

if not exist ".run" mkdir ".run"

REM --- npm deps ---
where npm >nul 2>&1
if errorlevel 1 (
    echo       AVISO: npm nao encontrado - UI nao sera iniciada.
) else (
    if not exist "dashboard\node_modules" (
        echo       Instalando dependencias npm...
        pushd dashboard
        call npm install
        popd
    )
)

REM --- Bot + API + dashboard + ngrok ---
echo [4/5] Subindo bot + API + dashboard + ngrok...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_services_hidden.ps1"
if errorlevel 1 (
    echo ERRO ao subir servicos. Veja mensagens acima.
    pause
    exit /b 1
)

echo [5/5] Pronto.
echo.
echo   Bot log:  .run\bot.log
echo   API:      http://127.0.0.1:8765/api/health
if exist ".run\ngrok_url.txt" (
    echo   Dashboard ^(ngrok^):
    type .run\ngrok_url.txt
    echo.
) else (
    echo   Dashboard: http://127.0.0.1:5173
    echo   ngrok inativo - verifique NGROK_TOKEN no .env
)
echo   Ver URL:  powershell -File scripts\show_ngrok_url.ps1
echo   Parar:    stop.bat
echo.

REM Browser ja aberto por start_services_hidden.ps1

echo.
pause
