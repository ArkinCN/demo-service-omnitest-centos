@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-dependencies.ps1" %*
exit /b %errorlevel%
