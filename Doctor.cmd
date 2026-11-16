@echo off
rem Environment doctor (ASCII only).
setlocal
cd /d "%~dp0"
set "PY=C:\Users\50174\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m app.cli doctor
echo.
pause
