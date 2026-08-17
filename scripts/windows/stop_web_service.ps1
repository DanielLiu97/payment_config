param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$serviceDir = Join-Path $ProjectRoot "web_data\service"
$pidFile = Join-Path $serviceDir "web.pid"

$stopped = $false
if (Test-Path $pidFile) {
    $pidText = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($pidText -and $pidText -match '^\d+$') {
        $pidValue = [int]$pidText
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $pidValue -Force
            Write-Output "Stopped service process PID=$pidValue"
            $stopped = $true
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

if (-not $stopped) {
    $port = 8010
    $ownerId = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess)
    if ($ownerId) {
        Stop-Process -Id $ownerId -Force
        Write-Output "Stopped listening process PID=$ownerId by port"
        $stopped = $true
    }
}

if (-not $stopped) {
    Write-Output "No running service process found"
}
