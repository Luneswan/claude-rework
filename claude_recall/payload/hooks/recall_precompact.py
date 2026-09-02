#!/usr/bin/env python3
"""PreCompact hook: save the decisions before the context holding them is dropped.

Compaction is where long sessions quietly lose things. The summary keeps the
narrative and drops the specifics - the exact flag that worked, the number you
measured, the approach you already ruled out - and an hour later you re-derive
something you had already settled.

This fires just before compaction and does two things:

  1. writes a handoff to ~/.claude/recall_handoffs/<session>.md, on disk, so it
     survives the compaction that is about to happen
  2. prints it, so the compactor sees it and is likely to carry it forward

The handoff is derived from the index, not by re-reading the conversation, so it
costs about 600 tokens rather than 30,000.

Fails open: any error prints nothing and exits 0. A hook must never be able to
block a compaction that is already needed.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOOKS = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.path.dirname(HOOKS)
RECALL = os.path.join(CLAUDE, "skills", "recall", "scripts", "recall.py")
OUT_DIR = os.path.join(CLAUDE, "recall_handoffs")
TIMEOUT = float(os.environ.get("RECALL_HANDOFF_TIMEOUT", "40"))
MAX_CHARS = 2400


def quiet_flags():
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            "startupinfo": si}


def run(args):
    try:
        p = subprocess.run([sys.executable, RECALL] + args, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=TIMEOUT, **quiet_flags())
        return (p.stdout or "").strip()
    except Exception:
        return ""


def session_id(payload):
    t = payload.get("transcript_path") or ""
    name = os.path.splitext(os.path.basename(t))[0] if t else ""
    name = re.sub(r"[^A-Za-z0-9_-]", "", name)[:40]
    return name or time.strftime("%Y%m%d-%H%M%S")


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    if not os.path.exists(RECALL):
        return 0

    handoff = run(["--handoff"])
    decisions = run(["--decisions", "--days", "3"])
    parts = []
    if handoff:
        parts.append("## Must survive this compaction\n" + handoff[:MAX_CHARS])
    if decisions:
        parts.append("## Decisions in the last 3 days\n" + decisions[:MAX_CHARS])
    if not parts:
        return 0
    body = "\n\n".join(parts)

    saved = ""
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        saved = os.path.join(OUT_DIR, session_id(payload) + ".md")
        with open(saved, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# recall handoff - %s (trigger: %s)\n\n%s\n"
                     % (time.strftime("%Y-%m-%d %H:%M:%S"),
                        payload.get("trigger", "?"), body))
    except Exception:
        saved = ""

    print("RECALL HANDOFF - carry these forward through the compaction:")
    print(body)
    if saved:
        print("Also written to %s, so it survives on disk even if the summary "
              "drops it." % saved.replace("\\", "/"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
