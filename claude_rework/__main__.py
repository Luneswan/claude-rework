"""Run the CLI as a module: `python -m claude_rework <command>`.

pip installs a `claude-rework` executable into its scripts directory, and on
some setups - a --user install on Windows, or a system Python whose scripts
directory is not on PATH - that command appears missing even though the package
installed fine.

This entry point works wherever Python itself works, which is everywhere.
`install` and `doctor` detect the PATH problem and print both this form and the
directory to add.
"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
