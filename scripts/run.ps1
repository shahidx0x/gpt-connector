param(
    [string]$HostName = $env:LOCALCONTROL_BIND_HOST,
    [int]$Port = $(if ($env:LOCALCONTROL_PORT) { [int]$env:LOCALCONTROL_PORT } else { 8765 }),
    [switch]$AllowAll
)

if (-not $HostName) {
    $HostName = "127.0.0.1"
}

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
} else {
    $python = "python"
}

if ($AllowAll) {
    $env:LOCALCONTROL_ALLOW_ALL = "1"
    Write-Host "WARNING: approval prompts are disabled for dangerous operations (--allow-all)."
}

& $python -m uvicorn localcontrol.main:app --host $HostName --port $Port
