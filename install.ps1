# Windows: right-click this file -> "Run with PowerShell".
#
# Finds Python, runs the installer, keeps the window open so you can read the
# result. If Python is missing it offers to install it with winget (built into
# Windows 10 and 11) and then continues.

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
Write-Host "claude-rework - one-click install"
Write-Host ""

function Find-Python {
  foreach ($name in @("python", "python3", "py")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) {
      $v = & $cmd.Source --version 2>&1
      if ("$v" -match "Python 3\.(9|1\d)") { return $cmd.Source }
    }
  }
  return $null
}

$py = Find-Python
if (-not $py) {
  Write-Host "Python 3 was not found."
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($winget) {
    $answer = Read-Host "Install Python 3.12 now with winget? [Y/n]"
    if ($answer -eq "" -or $answer -match "^[Yy]") {
      winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
      $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                  [System.Environment]::GetEnvironmentVariable("Path", "User")
      $py = Find-Python
    }
  }
  if (-not $py) {
    Write-Host "Install Python from https://www.python.org/downloads/windows/ and run this again."
    Read-Host "Press Enter to close"
    exit 1
  }
}

& $py install.py @args
Write-Host ""
Read-Host "Press Enter to close this window"
