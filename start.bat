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

REM --- [1/5] Ambiente completo: venv + pip + npm (cria se faltar, sincroniza sempre) ---
echo [1/5] Preparando ambiente (venv + dependencias)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\ensure_environment.ps1"
if errorlevel 1 (
    echo ERRO: falha ao preparar ambiente. Veja mensagens acima.
    pause
    exit /b 1
)

REM --- [2/5] Ollama (opcional) ---
echo [2/5] Verificando Ollama...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -UseBasicParsing -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo       Ollama offline - iniciando...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_ollama_hidden.ps1"
    ping -n 6 127.0.0.1 >nul
) else (
    echo       Ollama OK
)

REM --- [3/5] Encerra instancias antigas (processos apenas — nao remove venv/node_modules) ---
echo [3/5] Encerrando instancias antigas...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_bot.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_dashboard.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_ngrok.ps1"
ping -n 4 127.0.0.1 >nul

if not exist ".run" mkdir ".run"

REM --- [4/5] Bot + API + dashboard + ngrok ---
echo [4/5] Subindo bot + API + dashboard + ngrok...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_services_hidden.ps1"
if errorlevel 1 (
    echo ERRO ao subir servicos. Veja mensagens acima.
    pause
    exit /b 1
)

REM --- [5/5] Health check rapido ---
echo [5/5] Verificando API e Dashboard...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/health' -UseBasicParsing -TimeoutSec 15; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
    echo       AVISO: API ainda nao respondeu em /api/health - aguarde ou veja .run\bot.log
) else (
    echo       API OK: http://127.0.0.1:8765/api/health
)
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 15; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
    echo       AVISO: Dashboard nao respondeu em :5173 - veja .run\dashboard.log
) else (
    echo       Dashboard OK: http://127.0.0.1:5173
)

echo.
echo   Bot log:  .run\bot.log
echo   API:      http://127.0.0.1:8765/api/health
echo   Backtest: POST http://127.0.0.1:8765/api/backtest
if exist ".run\ngrok_url.txt" (
    echo   Dashboard ^(ngrok^):
    type .run\ngrok_url.txt
    echo.
) else (
    echo   Dashboard: http://127.0.0.1:5173
    echo   ngrok inativo - verifique NGROK_TOKEN no .env
)
echo   Ver URL:  powershell -File scripts\show_ngrok_url.ps1
echo   Parar:    stop.bat  ^(para processos; nao desinstala nada^)
echo.

echo.
pause
