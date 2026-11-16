@echo off
rem English-name launcher (same as the Chinese one) - avoids zip name encoding issues.
setlocal
cd /d "%~dp0"
start "" "%~dp0pythonw.exe" "%~dp0runstudio.py"
