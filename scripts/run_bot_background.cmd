@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\.."
if not exist ".run" mkdir ".run"
".venv\Scripts\python.exe" -X utf8 -u main.py >> ".run\bot.log" 2>&1
