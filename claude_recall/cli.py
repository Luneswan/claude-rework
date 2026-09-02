"""The `recl` command (`claude-recall` is an alias).

    recl install [--no-hooks] [--no-build]
    recl uninstall
    recl mcp-config
    recl test [--known N] [--quick]
    recl "<question>" [--budget N]      anything else is passed to recall.py
    recl --brief --days 2

Once installed, you should rarely need this: the hooks run recall for you. The
passthrough exists for the times you want to ask directly.
"""
from __future__ import annotations
import os
import subprocess
import sys

from . import __version__
from . import installer

USAGE = __doc__


def _claude():
    return os.environ.get("RECALL_HOME") or os.path.join(os.path.expanduser("~"), ".claude")


def _installed(*parts):
    p = os.path.join(_claude(), "skills", "recall", *parts)
    return p if os.path.exists(p) else None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE.strip())
        return 0
    if argv[0] in ("-V", "--version", "version"):
        print("recl " + __version__)
        return 0

    cmd, rest = argv[0], argv[1:]
    if cmd == "install":
        return installer.main(rest)
    if cmd == "uninstall":
        return installer.main(["--uninstall"])
    if cmd == "mcp-config":
        return installer.main(["--mcp-config"])
    if cmd == "test":
        t = _installed("tests", "run_tests.py")
        if not t:
            print("recall is not installed - run: recl install")
            return 1
        return subprocess.call([sys.executable, t] + rest)

    recall = _installed("scripts", "recall.py")
    if not recall:
        print("recall is not installed - run: recl install")
        return 1
    return subprocess.call([sys.executable, recall] + argv)


if __name__ == "__main__":
    sys.exit(main())
