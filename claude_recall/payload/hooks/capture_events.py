#!/usr/bin/env python3
"""PostToolUse hook: record what was DONE, not only what was said.

Transcripts hold the conversation. They do not hold the work: which files changed,
which commands ran, what actually got built. Ask "what did we change in the
router" and a transcript-only memory returns the *description* of the change.

One compact line per event, appended. No parsing, no model, no network - the cost
is a file append, so this is capture without capture overhead.

Written to ~/.claude/events.jsonl:
  {"t": 1788230000, "k": "edit", "p": "webapp", "d": "src/net/fetcher.py"}
  {"t": 1788230012, "k": "run",  "p": "webapp", "d": "pytest tests/ -q"}

Secrets never reach the log: commands are scrubbed and truncated, and anything
resembling a token or key is replaced rather than recorded.
"""
from __future__ import annotations
import json
import os
import re
import sys
import time

HOOKS = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.path.dirname(HOOKS)
EVENTS = os.path.join(CLAUDE, "events.jsonl")
MAX_D = 200
MAX_LINES = 60000

# A command line is the one place a secret can land in a log by accident.
#
# The header branch must consume the SCHEME AND the credential. `Authorization:
# \s*\S+` looks right and leaks: in the overwhelmingly common
# `Authorization: Bearer <token>` form the single token it eats is "Bearer", and
# the credential survives verbatim. Caught by tests/run_tests.py suite_capture.
#
# The env-assignment branch anchors the keyword to the END of the identifier, so
# GITHUB_TOKEN= and HF_TOKEN= match while TOKENIZER_PATH= does not.
SECRET = re.compile(
    r"(?:sk-|ghp_|gho_|github_pat_|hf_|xox[baprs]-|AKIA|ASIA)[A-Za-z0-9_\-]{8,}"
    r"|--?(?:password|passwd|token|secret|api[-_]?key|auth)[= ]\S+"
    r"|(?:authorization|proxy-authorization|x-api-key|x-auth-token|cookie)\s*:\s*"
    r"(?:bearer|basic|token|digest|apikey)?\s*\S+"
    r"|\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY)\s*=\s*\S+",
    re.I)
NOISE = ("cat ", "ls ", "echo ", "pwd", "head ", "tail ", "wc ", "grep ",
         "printf ", "which ", "type ")


def scrub(text):
    return SECRET.sub("[redacted]", text or "")


def rel(path, cwd):
    try:
        if path and cwd and os.path.isabs(path):
            return os.path.relpath(path, cwd).replace("\\", "/")
    except Exception:
        pass
    return (path or "").replace("\\", "/")


def trim():
    """Bounded log: drop the oldest when it grows past the cap."""
    try:
        if os.path.getsize(EVENTS) < 8 * 1024 * 1024:
            return
        with open(EVENTS, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        if len(lines) > MAX_LINES:
            with open(EVENTS, "w", encoding="utf-8", newline="\n") as fh:
                fh.writelines(lines[-MAX_LINES:])
    except Exception:
        pass


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or ""
    project = os.path.basename(os.path.normpath(cwd)) if cwd else ""

    kind = detail = ""
    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        kind = "edit"
        detail = rel(ti.get("file_path") or ti.get("notebook_path") or "", cwd)
    elif tool == "Bash":
        cmd = (ti.get("command") or "").strip()
        if not cmd or cmd.lower().startswith(NOISE):
            return 0                      # read-only shell noise is not work
        kind = "run"
        detail = scrub(" ".join(cmd.split()))[:MAX_D]
    else:
        return 0

    if not detail:
        return 0

    try:
        with open(EVENTS, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"t": int(time.time()), "k": kind,
                                 "p": project, "d": detail[:MAX_D]},
                                ensure_ascii=False) + "\n")
        trim()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
