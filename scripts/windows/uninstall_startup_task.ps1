param(
    [string]$TaskName = "PaymentConfigCheckerWeb"
)

$ErrorActionPreference = "Stop"

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "Startup task removed: $TaskName"
