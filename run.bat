@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
set "MODE=serve"
set "PORT=8765"
set "ALLOW_ALL="

if /I "%~1"=="help" set "MODE=help"
if /I "%~1"=="stop" set "MODE=stop"
if /I "%~1"=="test" set "MODE=test"
if /I "%~1"=="schema" set "MODE=schema"
if /I "%~1"=="check" set "MODE=check"
if /I "%~1"=="build-exe" set "MODE=buildexe"
if /I "%~1"=="serve" set "MODE=serve"
if /I "%~1"=="tunnel" set "MODE=tunnel"
if /I "%~1"=="ngrok" set "MODE=tunnel"
if /I "%~1"=="--allow-all" set "ALLOW_ALL=1"
if /I "%~2"=="--allow-all" set "ALLOW_ALL=1"
if /I "%~3"=="--allow-all" set "ALLOW_ALL=1"

if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /I "%%A"=="LOCALCONTROL_PORT" set "PORT=%%B"
    )
)

if /I "%MODE%"=="help" goto :help
if /I "%MODE%"=="stop" goto :stop
if /I "%MODE%"=="test" goto :test
if /I "%MODE%"=="schema" goto :schema
if /I "%MODE%"=="check" goto :check
if /I "%MODE%"=="buildexe" goto :buildexe
if /I "%MODE%"=="serve" goto :serve
if /I "%MODE%"=="tunnel" goto :tunnel

echo Unknown command: %MODE%
goto :help

:ensure
if not exist ".env" (
    echo Missing .env. Create it before running LocalControl.
    exit /b 1
)

if not exist "%PY%" (
    echo Creating virtual environment...
    python -m venv .venv || exit /b 1
)

"%PY%" -m pip show windows-localcontrol >nul 2>nul
if errorlevel 1 (
    echo Installing LocalControl dependencies...
    "%PY%" -m pip install -e ".[dev]" || exit /b 1
)
exit /b 0

:serve
call :ensure || exit /b 1
call :stopport
if defined ALLOW_ALL (
    set "LOCALCONTROL_ALLOW_ALL=1"
    echo WARNING: approval prompts are disabled for dangerous operations ^(--allow-all^).
)
echo Starting Windows LocalControl GPT Bridge...
echo URL: http://127.0.0.1:%PORT%
echo Health: http://127.0.0.1:%PORT%/health
echo.
echo Press Ctrl+C to stop.
"%PY%" -m uvicorn localcontrol.main:app --host 127.0.0.1 --port %PORT%
exit /b %errorlevel%

:tunnel
call :ensure || exit /b 1
call :stopport
if defined ALLOW_ALL (
    set "LOCALCONTROL_ALLOW_ALL=1"
)
echo Starting LocalControl with ngrok tunnel...
set "PS_ARGS=-NoProfile -ExecutionPolicy Bypass -File scripts\run.ps1 -Tunnel -HostName 127.0.0.1 -Port %PORT%"
if defined ALLOW_ALL set "PS_ARGS=%PS_ARGS% -AllowAll"
powershell.exe %PS_ARGS%
exit /b %errorlevel%

:stop
call :stopport
exit /b %errorlevel%

:stopport
set "STOPPED=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    if not "%%P"=="0" (
        echo Stopping existing listener on port %PORT% ^(PID %%P^)...
        taskkill /PID %%P /F >nul 2>nul
        set "STOPPED=1"
    )
)
if "%STOPPED%"=="0" echo No existing listener found on port %PORT%.
exit /b 0

:test
call :ensure || exit /b 1
"%PY%" -m pytest
exit /b %errorlevel%

:schema
call :ensure || exit /b 1
"%PY%" scripts\export_openapi.py
exit /b %errorlevel%

:buildexe
call :ensure || exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\build-exe.ps1
exit /b %errorlevel%

:check
call :ensure || exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$keys = Get-Content -LiteralPath '.\localcontrol-keys.txt' | Where-Object { $_ -like 'LOCALCONTROL_API_KEY=*' }; " ^
  "$apiKey = ($keys -split '=',2)[1]; " ^
  "$headers = @{ Authorization = 'Bearer ' + $apiKey }; " ^
  "Write-Host 'Health:'; Invoke-RestMethod -Uri 'http://127.0.0.1:%PORT%/health' | ConvertTo-Json -Depth 4; " ^
  "Write-Host 'System info:'; Invoke-RestMethod -Headers $headers -Uri 'http://127.0.0.1:%PORT%/system/info' | ConvertTo-Json -Depth 4"
exit /b %errorlevel%

:help
echo Usage:
echo   run.bat          Start the LocalControl API server
echo   run.bat tunnel   Start the API server and ngrok tunnel
echo   run.bat ngrok    Alias for tunnel
echo                   Downloads ngrok to .local-tools\ngrok if missing
echo   run.bat --allow-all
echo   run.bat serve --allow-all
echo   run.bat tunnel --allow-all
echo   run.bat stop     Stop any process listening on the configured port
echo   run.bat check    Test health and authenticated system/info endpoint
echo   run.bat test     Run automated tests
echo   run.bat schema   Regenerate gpt-actions.openapi.yaml
echo   run.bat build-exe Build dist\LocalControl\LocalControl.exe
echo   run.bat help     Show this help
exit /b 0
