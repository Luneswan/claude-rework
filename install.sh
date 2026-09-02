#!/usr/bin/env bash
# Linux / macOS terminal:   bash install.sh
# Same installer as install.command and install.ps1; this one does not pause.
set -e
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  exec python3 install.py "$@"
elif command -v python >/dev/null 2>&1; then
  exec python install.py "$@"
fi
echo "Python 3 was not found. Install it (apt install python3 / brew install python)"
echo "and run this again."
exit 1
