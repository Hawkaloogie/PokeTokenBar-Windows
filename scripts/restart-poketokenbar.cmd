@echo off
REM ---------------------------------------------------------------------
REM  Restart PokeTokenBar.
REM
REM  Double-click this any time you want the app to come back up cleanly -
REM  after changing settings, after it stops responding, or after an update.
REM
REM  Settings changes do NOT need a restart to take effect. The generation
REM  filter is read at hatch time, so picking Gen 1 applies to your next egg
REM  immediately. This is here for when you just want a clean restart.
REM
REM  ASCII only on purpose: Windows PowerShell 5.1 reads UTF-8 files as ANSI
REM  and mangles non-ASCII characters into parse errors.
REM ---------------------------------------------------------------------

setlocal
set "APPDIR=%~dp0.."
set "PYW=%APPDIR%\.venv\Scripts\pythonw.exe"

if not exist "%PYW%" (
    echo.
    echo ERROR: Could not find PokeTokenBar's Python at:
    echo   %PYW%
    echo.
    echo The app may have been moved or its virtual environment removed.
    echo.
    pause
    exit /b 1
)

echo Stopping PokeTokenBar...
REM Only stop pythonw processes running THIS app - never a stray pythonw
REM belonging to something else the user has open.
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*poketokenbar_windows*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

REM Give Windows a moment to release the tray icon before re-adding it.
powershell -NoProfile -Command "Start-Sleep -Seconds 2"

echo Starting PokeTokenBar...
start "" "%PYW%" -m poketokenbar_windows

powershell -NoProfile -Command "Start-Sleep -Seconds 3"

powershell -NoProfile -Command ^
  "$p = @(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*poketokenbar_windows*' }); if ($p.Count -gt 0) { Write-Host ''; Write-Host 'PokeTokenBar is running. Look for it in the system tray.' -ForegroundColor Green } else { Write-Host ''; Write-Host 'PokeTokenBar did NOT start. Run this to see the error:' -ForegroundColor Red; Write-Host '  %APPDIR%\.venv\Scripts\python.exe -m poketokenbar_windows' }"

echo.
REM `timeout` needs a real console and hangs when output is redirected,
REM so pause only when this was double-clicked (no args), never in a pipe.
if "%~1"=="" powershell -NoProfile -Command "Start-Sleep -Seconds 4"
endlocal
