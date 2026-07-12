param(
    [string]$TaskName = "LocalControl GPT Bridge",
    [switch]$Tunnel,
    [string]$NgrokDomain,
    [string]$PublicUrl,
    [string]$NgrokExe,
    [string]$NgrokDownloadUrl,
    [string]$NgrokAuthtoken,
    [int]$NgrokUrlTimeoutSeconds,
    [switch]$NoNgrokAutoInstall,
    [switch]$NoNgrokAuthPrompt
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo "scripts\run.ps1"

if (-not (Test-Path $script)) {
    throw "Could not find $script"
}

$arguments = "-NoProfile -ExecutionPolicy RemoteSigned -File `"$script`""
if ($Tunnel) {
    $arguments += " -Tunnel"
}
if ($NgrokDomain) {
    $arguments += " -NgrokDomain `"$NgrokDomain`""
}
if ($PublicUrl) {
    $arguments += " -PublicUrl `"$PublicUrl`""
}
if ($NgrokExe) {
    $arguments += " -NgrokExe `"$NgrokExe`""
}
if ($NgrokDownloadUrl) {
    $arguments += " -NgrokDownloadUrl `"$NgrokDownloadUrl`""
}
if ($NgrokAuthtoken) {
    $arguments += " -NgrokAuthtoken `"$NgrokAuthtoken`""
}
if ($NgrokUrlTimeoutSeconds) {
    $arguments += " -NgrokUrlTimeoutSeconds $NgrokUrlTimeoutSeconds"
}
if ($NoNgrokAutoInstall) {
    $arguments += " -NoNgrokAutoInstall"
}
if ($NoNgrokAuthPrompt) {
    $arguments += " -NoNgrokAuthPrompt"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DisallowStartIfOnBatteries:$false -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Starts the LocalControl FastAPI bridge at logon." -Force | Out-Null
Write-Host "Installed startup task: $TaskName"
