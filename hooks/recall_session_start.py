#!/usr/bin/env python3
"""SessionStart hook: begin every session already knowing where you left off.

Without this, session two starts blank and you spend the first ten minutes
re-explaining session one. This prints the open threads - requests from the last
few days with no conclusion after them - so the first answer of a new session is
already oriented.

Costs about 600 tokens once per session. Re-reading the previous conversation to
get the same picture costs 30,000 to 80,000.

It also refreshes the index in the background, which is what keeps a query at
0.7s instead of minutes. That refresh is incremental, detached and silent.

Fails open: any error prints nothing and exits 0.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOOKS = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.path.dirname(HOOKS)
SCRIPTS = os.path.join(CLAUDE, "skills", "recall", "scripts")
RECALL = os.path.join(SCRIPTS, "recall.py")
INDEXER = os.path.join(SCRIPTS, "recall_index.py")
EMBED = os.path.join(SCRIPTS, "recall_embed.py")

DAYS = os.environ.get("RECALL_BRIEF_DAYS", "3")
TIMEOUT = float(os.environ.get("RECALL_BRIEF_TIMEOUT", "30"))
MAX_LINES = 6


def quiet_flags():
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            "startupinfo": si}


def quiet_python():
    """pythonw.exe has no console at all. python.exe is a console application, so
    Windows hands it one - and CREATE_NO_WINDOW is ignored when combined with
    DETACHED_PROCESS. Both halves are needed or the refresh flashes a window."""
    exe = sys.executable
    if os.name == "nt":
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(cand):
            return cand
    return exe


def refresh():
    """Detached and silent. The session must never wait on indexing."""
    for script in (INDEXER, EMBED):
        if not os.path.exists(script):
            continue
        try:
            subprocess.Popen([quiet_python(), script, "--build"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, close_fds=True,
                             **quiet_flags())
        except Exception:
            pass


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    if not os.path.exists(RECALL):
        return 0
    refresh()

    args = [sys.executable, RECALL, "--brief", "--days", DAYS]
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT, **quiet_flags())
    except Exception:
        return 0

    lines = [l for l in (p.stdout or "").splitlines() if l.strip()]
    body = [l for l in lines if l.strip().startswith(("-", "[", "*"))][:MAX_LINES]
    if not body:
        return 0

    print("WHERE YOU LEFT OFF (open threads from the last %s days, read from "
          "your local history):" % DAYS)
    for l in body:
        print(l[:220])
    print("Heuristic and possibly stale. Full picture: recall.py --brief   |   "
          "search: recall.py \"<question>\"")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
