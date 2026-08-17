param(
    [string]$SourceRoot = "",
    [string]$BackupRoot = "E:\project_backups\payment_config_checker",
    [int]$KeepSnapshots = 14,
    [switch]$MirrorLatest,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $SourceRoot) {
    $SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

if (-not (Test-Path $SourceRoot)) {
    throw "Source path not found: $SourceRoot"
}

New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$snapshotDir = Join-Path $BackupRoot ("snapshot-" + $timestamp)
New-Item -ItemType Directory -Path $snapshotDir -Force | Out-Null

$excludeDirs = @("__pycache__", ".git", "design_refs", ".venv", "venv")
$robocopyBase = @(
    $SourceRoot,
    $snapshotDir,
    "/E",
    "/R:2",
    "/W:2",
    "/XD"
) + $excludeDirs

if ($DryRun) {
    $robocopyBase += "/L"
}

Write-Output "Creating snapshot backup..."
& robocopy @robocopyBase | Out-Host

if ($MirrorLatest) {
    $latestDir = Join-Path $BackupRoot "latest"
    New-Item -ItemType Directory -Path $latestDir -Force | Out-Null
    $mirrorArgs = @(
        $SourceRoot,
        $latestDir,
        "/MIR",
        "/R:2",
        "/W:2",
        "/XD"
    ) + $excludeDirs
    if ($DryRun) {
        $mirrorArgs += "/L"
    }
    Write-Output "Updating latest mirror..."
    & robocopy @mirrorArgs | Out-Host
}

# cleanup old snapshots
$snapshots = Get-ChildItem -Path $BackupRoot -Directory -Filter "snapshot-*" |
    Sort-Object Name -Descending

if ($snapshots.Count -gt $KeepSnapshots) {
    $toDelete = $snapshots | Select-Object -Skip $KeepSnapshots
    foreach ($item in $toDelete) {
        if ($DryRun) {
            Write-Output ("[DryRun] Would delete old snapshot: " + $item.FullName)
        } else {
            Remove-Item -Path $item.FullName -Recurse -Force
            Write-Output ("Deleted old snapshot: " + $item.FullName)
        }
    }
}

Write-Output ("Backup done. Snapshot: " + $snapshotDir)
