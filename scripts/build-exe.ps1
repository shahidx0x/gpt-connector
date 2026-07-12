param(
    [switch]$OneFile,
    [switch]$SkipInstall,
    [switch]$NoBundleNgrok,
    [string]$NgrokExe = $(if ($env:LOCALCONTROL_NGROK_EXE) { $env:LOCALCONTROL_NGROK_EXE } else { "ngrok" }),
    [string]$NgrokDownloadUrl = $(if ($env:LOCALCONTROL_NGROK_DOWNLOAD_URL) { $env:LOCALCONTROL_NGROK_DOWNLOAD_URL } else { "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip" })
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
} else {
    $python = "python"
}

if (-not $SkipInstall) {
    & $python -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency install failed."
    }
    & $python -m pip install "pyinstaller>=6"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller install failed."
    }
}

function Test-WindowsAppAlias {
    param([string]$Path)

    if (-not $Path -or -not $env:LOCALAPPDATA) {
        return $false
    }
    $windowsApps = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
    return $Path.StartsWith($windowsApps, [System.StringComparison]::OrdinalIgnoreCase)
}

function Install-LocalNgrok {
    param(
        [string]$DownloadUrl,
        [string]$InstallDir
    )

    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("localcontrol-ngrok-build-" + [guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $tempRoot "ngrok.zip"
    try {
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        Write-Host "Downloading ngrok for bundled exe..."
        Write-Host "Source: $DownloadUrl"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $zipPath
        Expand-Archive -LiteralPath $zipPath -DestinationPath $tempRoot -Force
        $downloadedExe = Get-ChildItem -LiteralPath $tempRoot -Recurse -Filter "ngrok.exe" -File | Select-Object -First 1
        if (-not $downloadedExe) {
            throw "Downloaded archive did not contain ngrok.exe."
        }
        $localExe = Join-Path $InstallDir "ngrok.exe"
        Copy-Item -LiteralPath $downloadedExe.FullName -Destination $localExe -Force
        return $localExe
    } finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Resolve-NgrokForBundle {
    param(
        [string]$RequestedExecutable,
        [string]$DownloadUrl
    )

    $installDir = Join-Path $repo ".local-tools\ngrok"
    $localExe = Join-Path $installDir "ngrok.exe"

    if ($RequestedExecutable -and $RequestedExecutable -ne "ngrok") {
        $command = Get-Command $RequestedExecutable -ErrorAction SilentlyContinue
        if ($command -and -not (Test-WindowsAppAlias $command.Source)) {
            return $command.Source
        }
        if (Test-Path -LiteralPath $RequestedExecutable) {
            return (Resolve-Path -LiteralPath $RequestedExecutable).Path
        }
    }

    if (Test-Path -LiteralPath $localExe) {
        return (Resolve-Path -LiteralPath $localExe).Path
    }

    $pathCommand = Get-Command "ngrok" -ErrorAction SilentlyContinue
    if ($pathCommand -and -not (Test-WindowsAppAlias $pathCommand.Source)) {
        return $pathCommand.Source
    }

    return Install-LocalNgrok -DownloadUrl $DownloadUrl -InstallDir $installDir
}

$mode = if ($OneFile) { "--onefile" } else { "--onedir" }
$webAssets = Join-Path $repo "localcontrol\web"
$args = @(
    "--noconfirm",
    "--clean",
    $mode,
    "--console",
    "--name", "GPT-Connect",
    "--distpath", "dist",
    "--workpath", "build\pyinstaller-work",
    "--specpath", "build\pyinstaller-spec",
    "--collect-submodules", "localcontrol",
    "--collect-submodules", "uvicorn",
    "--collect-submodules", "fastapi",
    "--collect-submodules", "pydantic",
    "--collect-submodules", "starlette",
    "--collect-data", "fastapi",
    "--collect-data", "pydantic",
    "--add-data", "$webAssets;localcontrol\web",
    "--copy-metadata", "fastapi",
    "--copy-metadata", "pydantic",
    "--copy-metadata", "starlette",
    "--copy-metadata", "uvicorn",
    "localcontrol\cli.py"
)

if (-not $NoBundleNgrok) {
    $ngrokPath = Resolve-NgrokForBundle -RequestedExecutable $NgrokExe -DownloadUrl $NgrokDownloadUrl
    Write-Host "Bundling ngrok: $ngrokPath"
    $args = @(
        "--add-binary", "$ngrokPath;."
    ) + $args
}

& $python -m PyInstaller @args
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

if ($OneFile) {
    Write-Host "Built: $repo\dist\GPT-Connect.exe"
} else {
    Write-Host "Built: $repo\dist\GPT-Connect\GPT-Connect.exe"
}
