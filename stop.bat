@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title BybitBot - Stop
echo.
echo ========================================
echo   BybitBot - Parando tudo
echo ========================================
echo.
echo   Este script PARA processos em execucao.
echo   NAO desinstala: .venv, node_modules, pip, npm, codigo ou .env
echo.

echo [1/5] Encerrando BybitBot...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_bot.ps1"

echo [2/5] Encerrando Dashboard (API + Vite)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_dashboard.ps1"

echo [3/5] Encerrando ngrok...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_ngrok.ps1"

timeout /t 3 /nobreak >nul

echo [4/5] Servicos encerrados.
echo       Mantido: .venv, dashboard\node_modules, data\, .env
echo       Removido apenas: PIDs/flags em .run\ (estado de runtime)
echo       (Opera/navegador NAO e fechado)

echo [5/5] Verificando Ollama...
if exist ".run\ollama_started_by_bybitbot.flag" (
    echo       Parando Ollama iniciado pelo BybitBot...
    taskkill /IM ollama.exe /F >nul 2>&1
    del /f /q ".run\ollama_started_by_bybitbot.flag" >nul 2>&1
) else (
    echo       Ollama mantido em execucao ^(nao foi iniciado pelo start.bat^).
)

echo.
echo BybitBot parado. Para subir de novo: start.bat
echo.
pause
