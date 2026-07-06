@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title BybitBot - Stop
echo.
echo ========================================
echo   BybitBot - Parando tudo
echo ========================================
echo.

echo [1/5] Encerrando BybitBot...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_bot.ps1"

echo [2/5] Encerrando Dashboard...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_dashboard.ps1"

echo [3/5] Encerrando ngrok...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_ngrok.ps1"

timeout /t 3 /nobreak >nul

echo [4/5] Servicos encerrados.
echo       (Opera/navegador NAO e fechado)

echo [5/5] Verificando Ollama...
if exist ".run\ollama_started_by_bybitbot.flag" (
    echo       Parando Ollama iniciado pelo BybitBot...
    taskkill /IM ollama.exe /F >nul 2>&1
    del /f /q ".run\ollama_started_by_bybitbot.flag" >nul 2>&1
) else (
    echo       Ollama mantido em execucao.
)

echo.
echo BybitBot parado.
echo.
pause
