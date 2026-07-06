@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\.."

if not exist ".run" mkdir ".run"

echo.
echo ========================================
echo   BybitBot em execucao
echo ========================================
echo   Log completo: .run\bot.log
echo   Ctrl+C para encerrar esta janela
echo   (o bot para junto)
echo ========================================
echo.

".venv\Scripts\python.exe" -X utf8 -u main.py 2>&1 | powershell -NoProfile -Command "$input | ForEach-Object { $_; Add-Content -Path '.run\bot.log' -Value $_ -Encoding utf8 }"

set EXIT_CODE=%ERRORLEVEL%
echo.
if %EXIT_CODE% neq 0 (
    echo ERRO: BybitBot encerrou com codigo %EXIT_CODE%
) else (
    echo BybitBot encerrou.
)
pause
exit /b %EXIT_CODE%
