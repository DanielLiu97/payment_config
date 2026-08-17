param(
    [string]$ProjectRoot = "",
    [string]$EnvFile = "",
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
if (-not $EnvFile) {
    $EnvFile = Join-Path $PSScriptRoot "web_service.env.ps1"
}

if (-not (Test-Path $EnvFile)) {
    throw "Missing env config: $EnvFile. Copy web_service.env.ps1.example to web_service.env.ps1 first."
}

. $EnvFile

if (-not $env:PAYMENT_ADMIN_COOKIE) {
    throw "PAYMENT_ADMIN_COOKIE is required."
}

Set-Location $ProjectRoot

$serviceDir = Join-Path $ProjectRoot "web_data\service"
New-Item -ItemType Directory -Path $serviceDir -Force | Out-Null

$pidFile = Join-Path $serviceDir "web.pid"
$stdoutFile = Join-Path $serviceDir "web.stdout.log"
$stderrFile = Join-Path $serviceDir "web.stderr.log"

if (Test-Path $pidFile) {
    $oldPidText = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($oldPidText -and $oldPidText -match '^\d+$') {
        $oldProc = Get-Process -Id ([int]$oldPidText) -ErrorAction SilentlyContinue
        if ($oldProc) {
            Write-Output "Service already running, PID=$oldPidText"
            exit 0
        }
    }
}

if ($Foreground) {
    Write-Output "Starting in foreground..."
    python run_web.py
    exit $LASTEXITCODE
}

$proc = Start-Process -FilePath "python" `
    -ArgumentList "run_web.py" `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $stdoutFile `
    -RedirectStandardError $stderrFile `
    -PassThru

Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii
Write-Output "Service started in background, PID=$($proc.Id)"
