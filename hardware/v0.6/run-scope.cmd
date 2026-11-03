@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-scope.ps1" %*
exit /b %errorlevel%
