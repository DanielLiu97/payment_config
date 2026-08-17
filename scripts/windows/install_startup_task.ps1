param(
    [string]$TaskName = "PaymentConfigCheckerWeb",
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$scriptPath = Join-Path $ProjectRoot "scripts\windows\start_web_service.ps1"
if (-not (Test-Path $scriptPath)) {
    throw "Start script not found: $scriptPath"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -RunLevel Limited -Force | Out-Null
Write-Output "Startup task installed: $TaskName"
