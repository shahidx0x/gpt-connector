param(
    [string]$HostName = $env:LOCALCONTROL_BIND_HOST,
    [int]$Port = $(if ($env:LOCALCONTROL_PORT) { [int]$env:LOCALCONTROL_PORT } else { 8765 }),
    [switch]$AllowAll,
    [switch]$Tunnel,
    [string]$NgrokDomain = $env:LOCALCONTROL_NGROK_DOMAIN,
    [string]$PublicUrl = $env:LOCALCONTROL_PUBLIC_URL,
    [string]$NgrokExe = $(if ($env:LOCALCONTROL_NGROK_EXE) { $env:LOCALCONTROL_NGROK_EXE } else { "ngrok" }),
    [string]$NgrokDownloadUrl = $(if ($env:LOCALCONTROL_NGROK_DOWNLOAD_URL) { $env:LOCALCONTROL_NGROK_DOWNLOAD_URL } else { "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip" }),
    [string]$NgrokAuthtoken = $(if ($env:LOCALCONTROL_NGROK_AUTHTOKEN) { $env:LOCALCONTROL_NGROK_AUTHTOKEN } elseif ($env:NGROK_AUTHTOKEN) { $env:NGROK_AUTHTOKEN } else { "" }),
    [switch]$NoNgrokAutoInstall,
    [switch]$NoNgrokAuthPrompt,
    [int]$NgrokApiPort = $(if ($env:LOCALCONTROL_NGROK_API_PORT) { [int]$env:LOCALCONTROL_NGROK_API_PORT } else { 4040 }),
    [int]$NgrokUrlTimeoutSeconds = $(if ($env:LOCALCONTROL_NGROK_URL_TIMEOUT_SECONDS) { [int]$env:LOCALCONTROL_NGROK_URL_TIMEOUT_SECONDS } else { 180 })
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Import-LocalEnv {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        if ($line.StartsWith("export ")) {
            $line = $line.Substring(7).Trim()
        }
        $parts = $line.Split("=", 2)
        if ($parts.Count -ne 2) {
            continue
        }
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (($value.Length -ge 2) -and (($value[0] -eq "'" -and $value[-1] -eq "'") -or ($value[0] -eq '"' -and $value[-1] -eq '"'))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ($key -and -not [Environment]::GetEnvironmentVariable($key, "Process")) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function Get-LocalTargetHost {
    param([string]$Name)

    if ($Name -in @("0.0.0.0", "::", "[::]")) {
        return "127.0.0.1"
    }
    return $Name
}

function Wait-LocalControl {
    param(
        [string]$Url,
        [System.Diagnostics.Process]$Process
    )

    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        if ($Process.HasExited) {
            throw "LocalControl exited early with code $($Process.ExitCode)."
        }
        try {
            Invoke-RestMethod -Uri $Url -TimeoutSec 2 | Out-Null
            return
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Timed out waiting for LocalControl health at $Url."
}

function Get-NgrokPublicUrl {
    param(
        [string]$ConfiguredUrl,
        [int]$ApiPort,
        [System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds
    )

    if ($ConfiguredUrl) {
        return $ConfiguredUrl.TrimEnd("/")
    }

    $apiUrl = "http://127.0.0.1:$ApiPort/api/tunnels"
    $deadline = [DateTime]::UtcNow.AddSeconds([Math]::Max(10, $TimeoutSeconds))
    $startedAt = [DateTime]::UtcNow
    $lastStatus = "ngrok local API has not responded yet."
    $lastError = $null
    $lastProgressAt = [DateTime]::MinValue

    while ([DateTime]::UtcNow -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "ngrok exited early with code $($Process.ExitCode). Last status: $lastStatus"
        }
        try {
            $response = Invoke-RestMethod -Uri $apiUrl -TimeoutSec 2
            $httpsTunnel = $response.tunnels | Where-Object { $_.public_url -like "https://*" } | Select-Object -First 1
            if ($httpsTunnel.public_url) {
                return $httpsTunnel.public_url.TrimEnd("/")
            }

            $tunnels = @($response.tunnels)
            if ($tunnels.Count -eq 0) {
                $lastStatus = "ngrok local API is reachable, but no tunnel has been published yet."
            } else {
                $summaries = foreach ($tunnel in $tunnels) {
                    $publicUrl = if ($tunnel.public_url) { $tunnel.public_url } else { "(no public_url yet)" }
                    $proto = if ($tunnel.proto) { $tunnel.proto } else { "unknown-proto" }
                    $name = if ($tunnel.name) { $tunnel.name } else { "unnamed" }
                    "$name/$proto/$publicUrl"
                }
                $lastStatus = "ngrok tunnels: " + ($summaries -join "; ")
            }
            $lastError = $null
        } catch {
            $lastError = $_.Exception.Message
            $lastStatus = "ngrok local API error: $lastError"
        }

        if (([DateTime]::UtcNow - $lastProgressAt).TotalSeconds -ge 15) {
            $elapsed = [int]([DateTime]::UtcNow - $startedAt).TotalSeconds
            Write-Host "Waiting for ngrok public URL... ${elapsed}s/${TimeoutSeconds}s. $lastStatus"
            $lastProgressAt = [DateTime]::UtcNow
        }

        Start-Sleep -Seconds 1
    }

    $message = @(
        "ngrok did not publish an HTTPS tunnel URL within $TimeoutSeconds seconds.",
        "Last status: $lastStatus",
        "Check ngrok's web interface at http://127.0.0.1:$ApiPort, your authtoken/account status, and outbound network/firewall access.",
        "You can also set LOCALCONTROL_PUBLIC_URL or LOCALCONTROL_NGROK_DOMAIN to skip public URL discovery, or increase LOCALCONTROL_NGROK_URL_TIMEOUT_SECONDS."
    ) -join " "
    if ($lastError) {
        $message += " Last API error: $lastError"
    }
    throw $message
}

function Test-WindowsAppAlias {
    param([string]$Path)

    if (-not $Path) {
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

    if (-not $DownloadUrl) {
        throw "No ngrok download URL configured."
    }

    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("localcontrol-ngrok-" + [guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $tempRoot "ngrok.zip"

    try {
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        Write-Host "ngrok not found. Downloading ngrok for Windows..."
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
        Write-Host "Installed local ngrok: $localExe"
        return $localExe
    } finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Resolve-NgrokExecutable {
    param(
        [string]$RequestedExecutable,
        [string]$DownloadUrl,
        [switch]$DisableAutoInstall
    )

    $installDir = Join-Path $repo ".local-tools\ngrok"
    $localExe = Join-Path $installDir "ngrok.exe"

    if ($RequestedExecutable -and $RequestedExecutable -ne "ngrok") {
        $command = Get-Command $RequestedExecutable -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
        if (Test-Path -LiteralPath $RequestedExecutable) {
            return (Resolve-Path -LiteralPath $RequestedExecutable).Path
        }
        if ($DisableAutoInstall) {
            throw "Could not find ngrok at $RequestedExecutable."
        }
        return Install-LocalNgrok -DownloadUrl $DownloadUrl -InstallDir $installDir
    }

    if (Test-Path -LiteralPath $localExe) {
        return (Resolve-Path -LiteralPath $localExe).Path
    }

    $pathCommand = Get-Command "ngrok" -ErrorAction SilentlyContinue
    if ($pathCommand -and -not (Test-WindowsAppAlias $pathCommand.Source)) {
        return $pathCommand.Source
    }

    if ($DisableAutoInstall) {
        throw "Could not find ngrok. Install ngrok, add it to PATH, or set LOCALCONTROL_NGROK_EXE."
    }

    return Install-LocalNgrok -DownloadUrl $DownloadUrl -InstallDir $installDir
}

function Convert-SecureStringToPlainText {
    param([securestring]$SecureText)

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureText)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Get-NgrokConfigPaths {
    $paths = New-Object System.Collections.Generic.List[string]
    if ($env:NGROK_CONFIG) {
        foreach ($path in $env:NGROK_CONFIG.Split([IO.Path]::PathSeparator)) {
            if ($path) {
                $paths.Add($path)
            }
        }
    }
    if ($env:LOCALAPPDATA) {
        $paths.Add((Join-Path $env:LOCALAPPDATA "ngrok\ngrok.yml"))
    }
    if ($env:APPDATA) {
        $paths.Add((Join-Path $env:APPDATA "ngrok\ngrok.yml"))
    }
    if ($HOME) {
        $paths.Add((Join-Path $HOME ".config\ngrok\ngrok.yml"))
        $paths.Add((Join-Path $HOME ".ngrok2\ngrok.yml"))
    }
    return $paths | Select-Object -Unique
}

function Test-NgrokAuthtokenConfigured {
    foreach ($path in Get-NgrokConfigPaths) {
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }
        try {
            $content = Get-Content -LiteralPath $path -Raw -ErrorAction Stop
        } catch {
            continue
        }
        if ($content -match "(?m)^\s*authtoken\s*:" -or $content -match "(?ms)^\s*agent\s*:.*?^\s+authtoken\s*:") {
            return $true
        }
    }
    return $false
}

function Set-NgrokAuthtoken {
    param(
        [string]$NgrokPath,
        [string]$Token
    )

    if (-not $Token) {
        throw "ngrok authtoken was empty."
    }

    Write-Host "Saving ngrok authtoken..."
    & $NgrokPath config add-authtoken $Token *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "ngrok rejected the authtoken. Get a valid token from https://dashboard.ngrok.com/get-started/your-authtoken"
    }
}

function Ensure-NgrokAuthenticated {
    param(
        [string]$NgrokPath,
        [string]$Token,
        [switch]$DisablePrompt
    )

    if ($Token) {
        Set-NgrokAuthtoken -NgrokPath $NgrokPath -Token $Token
        return
    }

    if (Test-NgrokAuthtokenConfigured) {
        return
    }

    if ($DisablePrompt) {
        throw "ngrok is not authenticated. Set LOCALCONTROL_NGROK_AUTHTOKEN or run: ngrok config add-authtoken <TOKEN>"
    }

    Write-Host ""
    Write-Host "ngrok needs an authtoken before it can start a tunnel."
    Write-Host "Get one from: https://dashboard.ngrok.com/get-started/your-authtoken"
    $secureToken = Read-Host "Paste ngrok authtoken" -AsSecureString
    $plainToken = Convert-SecureStringToPlainText -SecureText $secureToken
    try {
        Set-NgrokAuthtoken -NgrokPath $NgrokPath -Token $plainToken
    } finally {
        $plainToken = $null
    }
}

function Start-Tunnel {
    param(
        [string]$Python,
        [string]$BindHost,
        [int]$BindPort,
        [string]$NgrokExecutable,
        [string]$DownloadUrl,
        [string]$Authtoken,
        [switch]$DisableNgrokAutoInstall,
        [switch]$DisableNgrokAuthPrompt,
        [string]$Domain,
        [string]$ConfiguredPublicUrl,
        [int]$ApiPort,
        [int]$UrlTimeoutSeconds
    )

    $ngrokPath = Resolve-NgrokExecutable -RequestedExecutable $NgrokExecutable -DownloadUrl $DownloadUrl -DisableAutoInstall:$DisableNgrokAutoInstall
    Ensure-NgrokAuthenticated -NgrokPath $ngrokPath -Token $Authtoken -DisablePrompt:$DisableNgrokAuthPrompt

    $targetHost = Get-LocalTargetHost $BindHost
    $localBaseUrl = "http://$($targetHost):$BindPort"
    $healthUrl = "$localBaseUrl/health"
    $apiProcess = $null
    $ngrokProcess = $null

    try {
        Write-Host "Starting LocalControl API..."
        $apiArgs = @("-m", "uvicorn", "localcontrol.main:app", "--host", $BindHost, "--port", "$BindPort")
        $apiProcess = Start-Process -FilePath $Python -ArgumentList $apiArgs -WorkingDirectory $repo -PassThru -WindowStyle Hidden
        Wait-LocalControl -Url $healthUrl -Process $apiProcess

        $ngrokArgs = @("http")
        if ($Domain) {
            $ngrokArgs += "--domain=$Domain"
            if (-not $ConfiguredPublicUrl) {
                $ConfiguredPublicUrl = "https://$Domain"
            }
        }
        $ngrokArgs += "$($targetHost):$BindPort"

        Write-Host "Starting ngrok..."
        $ngrokProcess = Start-Process -FilePath $ngrokPath -ArgumentList $ngrokArgs -WorkingDirectory $repo -PassThru -NoNewWindow
        $resolvedPublicUrl = Get-NgrokPublicUrl -ConfiguredUrl $ConfiguredPublicUrl -ApiPort $ApiPort -Process $ngrokProcess -TimeoutSeconds $UrlTimeoutSeconds

        Write-Host "Regenerating GPT Actions schema for $resolvedPublicUrl"
        & $Python scripts\export_openapi.py --server-url $resolvedPublicUrl
        if ($LASTEXITCODE -ne 0) {
            throw "OpenAPI export failed."
        }

        Write-Host ""
        Write-Host "LocalControl: $localBaseUrl"
        Write-Host "Public URL:   $resolvedPublicUrl"
        Write-Host "Schema URL:   $resolvedPublicUrl/gpt-actions.openapi.yaml"
        Write-Host ""
        Write-Host "Leave this window open while your GPT is using LocalControl. Press Ctrl+C to stop."
        Wait-Process -Id $ngrokProcess.Id
    } finally {
        if ($ngrokProcess -and -not $ngrokProcess.HasExited) {
            Stop-Process -Id $ngrokProcess.Id -Force -ErrorAction SilentlyContinue
        }
        if ($apiProcess -and -not $apiProcess.HasExited) {
            Stop-Process -Id $apiProcess.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

Import-LocalEnv -Path (Join-Path $repo ".env")

if (-not $PSBoundParameters.ContainsKey("HostName") -and $env:LOCALCONTROL_BIND_HOST) {
    $HostName = $env:LOCALCONTROL_BIND_HOST
}
if (-not $PSBoundParameters.ContainsKey("Port") -and $env:LOCALCONTROL_PORT) {
    $Port = [int]$env:LOCALCONTROL_PORT
}
if (-not $PSBoundParameters.ContainsKey("NgrokDomain") -and $env:LOCALCONTROL_NGROK_DOMAIN) {
    $NgrokDomain = $env:LOCALCONTROL_NGROK_DOMAIN
}
if (-not $PSBoundParameters.ContainsKey("PublicUrl") -and $env:LOCALCONTROL_PUBLIC_URL) {
    $PublicUrl = $env:LOCALCONTROL_PUBLIC_URL
}
if (-not $PSBoundParameters.ContainsKey("NgrokExe") -and $env:LOCALCONTROL_NGROK_EXE) {
    $NgrokExe = $env:LOCALCONTROL_NGROK_EXE
}
if (-not $PSBoundParameters.ContainsKey("NgrokDownloadUrl") -and $env:LOCALCONTROL_NGROK_DOWNLOAD_URL) {
    $NgrokDownloadUrl = $env:LOCALCONTROL_NGROK_DOWNLOAD_URL
}
if (-not $PSBoundParameters.ContainsKey("NgrokAuthtoken")) {
    if ($env:LOCALCONTROL_NGROK_AUTHTOKEN) {
        $NgrokAuthtoken = $env:LOCALCONTROL_NGROK_AUTHTOKEN
    } elseif ($env:NGROK_AUTHTOKEN) {
        $NgrokAuthtoken = $env:NGROK_AUTHTOKEN
    }
}
if (-not $PSBoundParameters.ContainsKey("NgrokApiPort") -and $env:LOCALCONTROL_NGROK_API_PORT) {
    $NgrokApiPort = [int]$env:LOCALCONTROL_NGROK_API_PORT
}
if (-not $PSBoundParameters.ContainsKey("NgrokUrlTimeoutSeconds") -and $env:LOCALCONTROL_NGROK_URL_TIMEOUT_SECONDS) {
    $NgrokUrlTimeoutSeconds = [int]$env:LOCALCONTROL_NGROK_URL_TIMEOUT_SECONDS
}
if (-not $HostName) {
    $HostName = "127.0.0.1"
}

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
} else {
    $python = "python"
}

if ($AllowAll) {
    $env:LOCALCONTROL_ALLOW_ALL = "1"
    Write-Host "WARNING: approval prompts are disabled for dangerous operations (--allow-all)."
}

if ($Tunnel) {
    Start-Tunnel -Python $python -BindHost $HostName -BindPort $Port -NgrokExecutable $NgrokExe -DownloadUrl $NgrokDownloadUrl -Authtoken $NgrokAuthtoken -DisableNgrokAutoInstall:$NoNgrokAutoInstall -DisableNgrokAuthPrompt:$NoNgrokAuthPrompt -Domain $NgrokDomain -ConfiguredPublicUrl $PublicUrl -ApiPort $NgrokApiPort -UrlTimeoutSeconds $NgrokUrlTimeoutSeconds
} else {
    & $python -m uvicorn localcontrol.main:app --host $HostName --port $Port
}
