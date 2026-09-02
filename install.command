#!/bin/bash
# macOS: double-click this file in Finder.
#
# Finds Python, runs the installer, and keeps the window open so you can read
# the result. If Python is missing, macOS offers to install the developer tools
# the first time `python3` is called - accept, then double-click this again.

cd "$(dirname "$0")" || exit 1
echo "claude-rework - one-click install"
echo

if command -v python3 >/dev/null 2>&1; then
  python3 install.py "$@"
elif command -v python >/dev/null 2>&1; then
  python install.py "$@"
else
  echo "Python 3 was not found."
  echo "Install it from https://www.python.org/downloads/ (one click), then"
  echo "double-click this file again."
fi

echo
read -r -p "Press Enter to close this window."
