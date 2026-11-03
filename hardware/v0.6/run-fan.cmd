@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-fan.ps1" %*
exit /b %errorlevel%
