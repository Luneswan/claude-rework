#!/usr/bin/env python3
"""Install recall into ~/.claude.

    python install.py                 everything: skill, hooks, first index build
    python install.py --no-hooks      skill only, settings.json untouched
    python install.py --no-build      install but skip the first index build
    python install.py --mcp-config    print the Claude desktop app config and exit
    python install.py --uninstall     remove everything this installer added

After this, you do not type recall commands. Four hooks make it work on its own:

    SessionStart      prints what is still open, so a new session starts oriented
    UserPromptSubmit  when you ask about the past, looks the answer up first
    PostToolUse       records what was actually edited and run
    PreCompact        saves the decisions before compaction can drop them

Your settings.json is backed up before it is touched, existing hooks are left
alone, and running this twice changes nothing the second time.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

REPO_ZIP = "https://github.com/Luneswan/claude-recall/archive/refs/heads/main.zip"


def _locate_repo():
    """Where the files to install live.

    Normally: next to this script. But this script is also meant to be run as
    one line -  `curl ... | python -`  - and then there is no repo on disk and
    no __file__ at all. In that case fetch the repo ourselves, once, into a
    temp dir, and install from there. Same code path either way after this.
    """
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = ""
    if here and os.path.exists(os.path.join(here, "skills", "recall", "SKILL.md")):
        return here
    import io
    import tempfile
    import urllib.request
    import zipfile
    print("  fetching claude-recall from GitHub (one-time, ~100 KB) ...")
    data = urllib.request.urlopen(REPO_ZIP, timeout=60).read()
    tmp = tempfile.mkdtemp(prefix="claude-recall-")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(tmp)
    for name in os.listdir(tmp):
        cand = os.path.join(tmp, name)
        if os.path.exists(os.path.join(cand, "skills", "recall", "SKILL.md")):
            return cand
    raise SystemExit("  ! downloaded archive did not contain the skill")


HERE = _locate_repo()
CLAUDE = os.environ.get("RECALL_HOME") or os.path.join(os.path.expanduser("~"), ".claude")
SKILL_DST = os.path.join(CLAUDE, "skills", "recall")
HOOKS_DST = os.path.join(CLAUDE, "hooks")
MCP_DST = os.path.join(CLAUDE, "recall_mcp")
SETTINGS = os.path.join(CLAUDE, "settings.json")

# (event, matcher, script, what it buys you)
HOOK_SPECS = [
    ("SessionStart", None, "recall_session_start.py",
     "start each session knowing what is still open"),
    ("UserPromptSubmit", None, "recall_auto.py",
     "answer 'did we already do this?' before Claude guesses"),
    ("PostToolUse", "Edit|Write|MultiEdit|NotebookEdit|Bash", "capture_events.py",
     "record what was actually edited and run"),
    ("PreCompact", None, "recall_precompact.py",
     "save decisions before compaction drops them"),
]


def _fwd(p):
    """Forward slashes, always.

    Claude Code runs hook commands through a shell. On Windows that shell is
    bash, which treats a backslash as an escape - so "C:\\Python\\python.exe"
    arrives as "C:Pythonpython.exe" and the hook dies with exit 127, silently,
    forever. This is not a style preference.
    """
    return p.replace("\\", "/")


def hook_command(script):
    return '"%s" "%s"' % (_fwd(sys.executable), _fwd(os.path.join(HOOKS_DST, script)))


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print("  ! settings.json exists but will not parse (%s)" % exc)
        print("    fix or move it, then re-run. Refusing to overwrite it.")
        sys.exit(1)


def _registered(settings, event, script):
    for group in settings.get("hooks", {}).get(event, []):
        for h in group.get("hooks", []):
            if script in (h.get("command") or ""):
                return True
    return False


def backup():
    if os.path.exists(SETTINGS):
        dst = SETTINGS + ".bak." + time.strftime("%Y%m%d-%H%M%S")
        shutil.copy(SETTINGS, dst)
        print("  backed up settings.json -> " + os.path.basename(dst))


def install_hooks():
    settings = load_settings()
    todo = [(e, m, s, w) for e, m, s, w in HOOK_SPECS
            if not _registered(settings, e, s)]
    if not todo:
        print("  all four hooks already registered - left as is")
        return
    backup()
    for event, matcher, script, why in todo:
        entry = {"hooks": [{"type": "command", "command": hook_command(script)}]}
        if matcher:
            entry["matcher"] = matcher
        settings.setdefault("hooks", {}).setdefault(event, []).append(entry)
        print("  + %-17s %s" % (event, why))
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)


def remove_hooks():
    settings = load_settings()
    ours = {s for _, _, s, _ in HOOK_SPECS}
    removed = 0
    for event in list(settings.get("hooks", {})):
        kept = []
        for g in settings["hooks"][event]:
            hooks = [h for h in g.get("hooks", [])
                     if not any(s in (h.get("command") or "") for s in ours)]
            removed += len(g.get("hooks", [])) - len(hooks)
            if hooks:
                g["hooks"] = hooks
                kept.append(g)
        if kept:
            settings["hooks"][event] = kept
        else:
            settings["hooks"].pop(event, None)
    if not removed:
        print("  no recall hooks found in settings.json")
        return
    backup()
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
    print("  removed %d recall hook entr%s" % (removed, "y" if removed == 1 else "ies"))


def copy_tree():
    os.makedirs(os.path.dirname(SKILL_DST), exist_ok=True)
    src = os.path.join(HERE, "skills", "recall")
    if os.path.exists(SKILL_DST):
        # keep anything the user generated; replace only what we ship
        for sub in ("scripts", "tests", "reference"):
            dst = os.path.join(SKILL_DST, sub)
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(os.path.join(src, sub), dst)
        shutil.copy(os.path.join(src, "SKILL.md"), SKILL_DST)
        print("  updated " + SKILL_DST)
    else:
        shutil.copytree(src, SKILL_DST)
        print("  installed " + SKILL_DST)

    os.makedirs(HOOKS_DST, exist_ok=True)
    for _, _, script, _ in HOOK_SPECS:
        shutil.copy(os.path.join(HERE, "hooks", script), HOOKS_DST)
    print("  installed %d hook script(s) in %s" % (len(HOOK_SPECS), HOOKS_DST))

    os.makedirs(MCP_DST, exist_ok=True)
    shutil.copy(os.path.join(HERE, "mcp", "recall_mcp.py"), MCP_DST)


def mcp_block():
    return json.dumps({"mcpServers": {"recall": {
        "command": _fwd(sys.executable),
        "args": [_fwd(os.path.join(MCP_DST, "recall_mcp.py"))]}}}, indent=2)


def print_mcp():
    print("  Claude desktop app / Cowork (optional - Claude Code does not need it):")
    print()
    print("  Add to claude_desktop_config.json, then restart the app:")
    print("    macOS   ~/Library/Application Support/Claude/claude_desktop_config.json")
    print("    Windows %APPDATA%\\Claude\\claude_desktop_config.json")
    print()
    for line in mcp_block().splitlines():
        print("    " + line)
    print()
    print("  Claude then calls recall itself when you ask about the past.")


def _importable(mod):
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def check_deps():
    missing = [m for m in ("numpy", "model2vec") if not _importable(m)]
    if missing:
        print()
        print("  optional, for semantic ranking: pip install " + " ".join(missing))
        print("  recall works without them, using lexical scoring only.")
    return not missing


def build():
    scripts = os.path.join(SKILL_DST, "scripts")
    print()
    print("  indexing the transcripts already in ~/.claude/projects ...")
    r = subprocess.run([sys.executable, os.path.join(scripts, "recall_index.py"),
                        "--build"], text=True)
    if r.returncode != 0:
        print("  index build reported an error; recall still runs on a live scan")
        return
    if not (_importable("numpy") and _importable("model2vec")):
        print("  skipping vectors (numpy/model2vec not installed)")
        return
    print()
    print("  embedding (one ~36 MB model download, then fully offline) ...")
    subprocess.run([sys.executable, os.path.join(scripts, "recall_embed.py"),
                    "--build"], text=True)


def uninstall():
    remove_hooks()
    for path in (SKILL_DST, MCP_DST):
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
            print("  removed " + path)
    for _, _, script, _ in HOOK_SPECS:
        p = os.path.join(HOOKS_DST, script)
        if os.path.exists(p):
            os.remove(p)
    print("  removed hook scripts")
    print()
    print("  Left in place on purpose (delete by hand if you want them gone):")
    for f in ("recall_corpus.jsonl", "recall_corpus.df.json", "recall_corpus.vec.npy",
              "recall_corpus.vec.meta.json", "recall_corpus.manifest.json",
              "events.jsonl", "recall_tuning.json", "recall_handoffs"):
        p = os.path.join(CLAUDE, f)
        if os.path.exists(p):
            print("    " + p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-hooks", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--mcp-config", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()

    if a.mcp_config:
        print(mcp_block())
        return 0

    print("recall installer")
    print("  target: " + CLAUDE)
    if not os.path.isdir(CLAUDE):
        print("  ! %s does not exist - is Claude Code installed for this user?" % CLAUDE)
        return 1
    print()

    if a.uninstall:
        uninstall()
        return 0

    copy_tree()
    if a.no_hooks:
        print("  --no-hooks: settings.json untouched (nothing runs automatically)")
    else:
        install_hooks()
    check_deps()
    if not a.no_build:
        build()

    print()
    print("  Done. It runs on its own now - you do not need to type anything.")
    print("  Open a new Claude Code session and ask, in plain English:")
    print('      "what did we decide about the retry logic?"')
    print('      "where did we leave off yesterday?"')
    print()
    print("  Manual use, if you want it:")
    print('      python %s "<question>"'
          % _fwd(os.path.join(SKILL_DST, "scripts", "recall.py")))
    print()
    print_mcp()
    return 0


if __name__ == "__main__":
    sys.exit(main())
