@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if /I "%~1"=="help" (
    call run.bat help
    exit /b %errorlevel%
)
call run.bat tunnel %*
