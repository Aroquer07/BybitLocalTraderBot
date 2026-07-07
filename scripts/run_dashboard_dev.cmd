@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\.."
if not exist ".run" mkdir ".run"
cd /d "%~dp0\..\dashboard"
call npm run dev >> "..\.run\dashboard.log" 2>&1
