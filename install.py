#!/usr/bin/env python3
"""Install recall into ~/.claude.

    python install.py                 install skill + capture hook, then build
    python install.py --no-hooks      skill only, do not touch settings.json
    python install.py --no-build      install but skip the first corpus build
    python install.py --uninstall     remove what this installer added

What it does, and nothing else:

  1. copies skills/recall/  -> ~/.claude/skills/recall/
  2. copies hooks/capture_events.py -> ~/.claude/hooks/
  3. adds ONE PostToolUse hook entry to ~/.claude/settings.json
  4. builds the searchable corpus from transcripts you already have

Your settings.json is backed up before it is touched, existing hooks are left
alone, and running the installer twice changes nothing the second time.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.environ.get("RECALL_HOME") or os.path.join(os.path.expanduser("~"), ".claude")
SKILL_DST = os.path.join(CLAUDE, "skills", "recall")
HOOKS_DST = os.path.join(CLAUDE, "hooks")
SETTINGS = os.path.join(CLAUDE, "settings.json")
MATCHER = "Edit|Write|MultiEdit|NotebookEdit|Bash"


def hook_command():
    """Forward slashes, always.

    Claude Code runs hook commands through a shell. On Windows that shell is
    bash, which treats a backslash as an escape character - so
    "C:\\Python\\python.exe" arrives as "C:Pythonpython.exe" and the hook dies
    with exit 127, silently, forever. This is not a style preference.
    """
    py = sys.executable.replace("\\", "/")
    script = os.path.join(HOOKS_DST, "capture_events.py").replace("\\", "/")
    return '"%s" "%s"' % (py, script)


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


def already_installed(settings):
    for group in settings.get("hooks", {}).get("PostToolUse", []):
        for h in group.get("hooks", []):
            if "capture_events.py" in (h.get("command") or ""):
                return True
    return False


def install_hook():
    settings = load_settings()
    if already_installed(settings):
        print("  hook already registered - left as is")
        return False
    if os.path.exists(SETTINGS):
        backup = SETTINGS + ".bak." + time.strftime("%Y%m%d-%H%M%S")
        shutil.copy(SETTINGS, backup)
        print("  backed up settings.json -> " + os.path.basename(backup))
    settings.setdefault("hooks", {}).setdefault("PostToolUse", []).append(
        {"matcher": MATCHER,
         "hooks": [{"type": "command", "command": hook_command()}]})
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
    print("  registered PostToolUse hook for " + MATCHER)
    return True


def remove_hook():
    settings = load_settings()
    groups = settings.get("hooks", {}).get("PostToolUse", [])
    kept = []
    removed = 0
    for g in groups:
        hooks = [h for h in g.get("hooks", [])
                 if "capture_events.py" not in (h.get("command") or "")]
        removed += len(g.get("hooks", [])) - len(hooks)
        if hooks:
            g["hooks"] = hooks
            kept.append(g)
    if not removed:
        print("  no capture hook found in settings.json")
        return
    settings["hooks"]["PostToolUse"] = kept
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
    print("  removed %d capture hook entr%s" % (removed, "y" if removed == 1 else "ies"))


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
    shutil.copy(os.path.join(HERE, "hooks", "capture_events.py"), HOOKS_DST)
    print("  installed " + os.path.join(HOOKS_DST, "capture_events.py"))


def check_deps():
    missing = []
    for mod, why in (("numpy", "required for semantic ranking"),
                     ("model2vec", "required to build the embedding model")):
        try:
            __import__(mod)
        except Exception:
            missing.append((mod, why))
    if missing:
        print()
        print("  optional dependencies not found:")
        for mod, why in missing:
            print("    %-12s %s" % (mod, why))
        print("    install with:  pip install numpy model2vec")
        print("    recall works without them, using lexical ranking only.")
    return not missing


def build():
    scripts = os.path.join(SKILL_DST, "scripts")
    print()
    print("  building the corpus from transcripts already in ~/.claude/projects ...")
    r = subprocess.run([sys.executable, os.path.join(scripts, "recall_index.py"),
                        "--build"], text=True)
    if r.returncode != 0:
        print("  corpus build reported an error; recall still runs on a live scan")
        return
    try:
        import numpy, model2vec  # noqa: F401
    except Exception:
        print("  skipping vectors (numpy/model2vec not installed)")
        return
    print()
    print("  embedding the corpus (one ~36 MB model download, then fully offline) ...")
    subprocess.run([sys.executable, os.path.join(scripts, "recall_embed.py"),
                    "--build"], text=True)


def uninstall():
    remove_hook()
    if os.path.exists(SKILL_DST):
        shutil.rmtree(SKILL_DST, ignore_errors=True)
        print("  removed " + SKILL_DST)
    h = os.path.join(HOOKS_DST, "capture_events.py")
    if os.path.exists(h):
        os.remove(h)
        print("  removed " + h)
    print()
    print("  Left in place on purpose (delete by hand if you want them gone):")
    for f in ("recall_corpus.jsonl", "recall_corpus.df.json", "recall_corpus.vec.npy",
              "recall_corpus.vec.meta.json", "events.jsonl", "recall_tuning.json"):
        p = os.path.join(CLAUDE, f)
        if os.path.exists(p):
            print("    " + p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-hooks", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()

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
        print("  --no-hooks: settings.json untouched (no capture)")
    else:
        install_hook()
    check_deps()
    if not a.no_build:
        build()

    r = os.path.join(SKILL_DST, "scripts", "recall.py").replace("\\", "/")
    print()
    print("  Done. Try it:")
    print('    python "%s" "what did we decide about X" --budget 2000' % r)
    print('    python "%s" --stores' % r)
    print('    python "%s" --budget-report' % r)
    print()
    print("  The capture hook starts recording on your next Claude Code session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
