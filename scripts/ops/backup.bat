@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%backup.ps1"

if not exist "%PS1%" (
  echo [ERROR] backup.ps1 not found: "%PS1%"
  pause
  exit /b 1
)

echo Running project backup...
powershell -ExecutionPolicy Bypass -File "%PS1%"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo [FAILED] Backup failed, exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [OK] Backup finished.
pause
exit /b 0
