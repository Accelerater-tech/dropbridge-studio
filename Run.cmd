@echo off
rem DropBridge Studio launcher (ASCII only on purpose: cmd reads .cmd as GBK)
setlocal
cd /d "%~dp0"
set "PYW=C:\Users\50174\AppData\Local\Programs\Python\Python312\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" -m app.main
exit /b 0
