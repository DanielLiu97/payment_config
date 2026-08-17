# Backup & Restore Guide

## 1) Create backup

From project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ops\backup.ps1
```

Optional:

- Keep a latest mirror (for quick rollback):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ops\backup.ps1 -MirrorLatest
```

- Dry run (no file changes):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ops\backup.ps1 -DryRun
```

## 2) Restore from a snapshot

1. Stop web service first:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\stop_web_service.ps1
```

2. Pick a snapshot folder under:

`E:\project_backups\payment_config_checker\snapshot-YYYYMMDD-HHMMSS`

3. Restore with robocopy:

```powershell
robocopy "E:\project_backups\payment_config_checker\snapshot-YYYYMMDD-HHMMSS" "E:\2026Test Project\海外新春活动\payment_config_checker_0910\payment_config_checker" /MIR /R:2 /W:2
```

4. Start service:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\start_web_service.ps1
```

## 3) Scope notes

- Backups exclude: `__pycache__`, `.git`, `design_refs`, `.venv`, `venv`.
- Templates, scripts, web UI code, task artifacts (`web_data`) are included.
