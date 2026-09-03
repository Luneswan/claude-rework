@echo off
rem Windows, Command Prompt: double-click this file, or run install.cmd.
rem
rem The PowerShell script next door does the same job. This exists because cmd
rem is what opens when someone types "cmd", and because the one-liner people
rem paste there used to fail twice over: `&&` is not available in Windows
rem PowerShell 5.1, and `claude-rework` is not on PATH in the shell that just
rem ran pip. Going through install.py sidesteps both.

setlocal enabledelayedexpansion
cd /d "%~dp0"
echo claude-rework - one-click install
echo.

set "PY="
for %%C in (py python python3) do (
  if not defined PY (
    where %%C >nul 2>nul && set "PY=%%C"
  )
)

if not defined PY (
  echo Python 3 was not found.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Install Python from https://www.python.org/downloads/windows/ and run
    echo this again. Tick "Add python.exe to PATH" in the installer.
  ) else (
    set /p "ANSWER=Install Python 3.12 now with winget? [Y/n] "
    if /i "!ANSWER!"=="n" goto :done
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    echo.
    echo Python installed. Close this window, open a new one, and run
    echo install.cmd again so the new PATH is picked up.
  )
  goto :done
)

rem "py" takes -3 to pick a modern interpreter; the others already are one.
if /i "%PY%"=="py" (
  py -3 install.py %*
) else (
  "%PY%" install.py %*
)

:done
echo.
pause
endlocal
