#!/usr/bin/env python3
"""Install claude-rework on every Claude surface this machine has.

    claude-rework install              detect everything, connect everything, build
    claude-rework install --no-hooks   skip Claude Code hooks
    claude-rework install --no-desktop skip the desktop app
    claude-rework install --no-build   skip the first index build
    claude-rework doctor               check every connection, report what is wrong
    claude-rework repair               fix what doctor found
    claude-rework update               newest version, then reconnect
    claude-rework uninstall            remove everything this installer added

The rule: never ask a question a probe can answer. Detection decides which
surfaces exist; the installer connects each one the only way it can be reached
(hooks for Claude Code, MCP for the desktop app), backs up any file before
touching it, and does nothing the second time it is run.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

from . import __version__
from . import detect as _detect

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "payload")
CLAUDE = _detect.claude_home()
SKILL_DST = os.path.join(CLAUDE, "skills", "recall")
HOOKS_DST = os.path.join(CLAUDE, "hooks")
MCP_DST = os.path.join(CLAUDE, "recall_mcp")
SETTINGS = os.path.join(CLAUDE, "settings.json")
MCP_KEY = "claude-rework"

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
HOOK_SCRIPTS = [s for _, _, s, _ in HOOK_SPECS]


# ----------------------------------------------------------------- helpers ---

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


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def _save_json(path, data):
    """Back up, then write. A config file is never overwritten without a copy."""
    if os.path.exists(path):
        dst = path + ".bak." + time.strftime("%Y%m%d-%H%M%S")
        shutil.copy(path, dst)
        print("  backed up %s -> %s" % (os.path.basename(path), os.path.basename(dst)))
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _registered(settings, event, script):
    for group in settings.get("hooks", {}).get(event, []):
        for h in group.get("hooks", []):
            if script in (h.get("command") or ""):
                return True
    return False


def _importable(mod):
    try:
        __import__(mod)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ files ---

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
        print("  updated skill      %s" % SKILL_DST)
    else:
        shutil.copytree(src, SKILL_DST)
        print("  installed skill    %s" % SKILL_DST)
    os.makedirs(HOOKS_DST, exist_ok=True)
    for s in HOOK_SCRIPTS:
        shutil.copy(os.path.join(HERE, "hooks", s), HOOKS_DST)
    os.makedirs(MCP_DST, exist_ok=True)
    shutil.copy(os.path.join(HERE, "mcp", "recall_mcp.py"), MCP_DST)
    print("  installed hooks    %s (%d scripts)" % (HOOKS_DST, len(HOOK_SCRIPTS)))
    print("  installed mcp      %s" % MCP_DST)


# ------------------------------------------------------ surface: claude code --

def connect_claude_code():
    try:
        settings = _load_json(SETTINGS)
    except Exception as exc:
        print("  ! settings.json will not parse (%s) - refusing to touch it" % exc)
        return False
    todo = [(e, m, s, w) for e, m, s, w in HOOK_SPECS if not _registered(settings, e, s)]
    if not todo:
        print("  claude code        already connected (4 hooks)")
        return True
    for event, matcher, script, _why in todo:
        entry = {"hooks": [{"type": "command", "command": hook_command(script)}]}
        if matcher:
            entry["matcher"] = matcher
        settings.setdefault("hooks", {}).setdefault(event, []).append(entry)
    _save_json(SETTINGS, settings)
    print("  claude code        connected via hooks:")
    for event, _m, _s, why in todo:
        print("      + %-17s %s" % (event, why))
    return True


def disconnect_claude_code():
    try:
        settings = _load_json(SETTINGS)
    except Exception:
        print("  settings.json will not parse - left alone")
        return
    removed = 0
    for event in list(settings.get("hooks", {})):
        kept = []
        for g in settings["hooks"][event]:
            hooks = [h for h in g.get("hooks", [])
                     if not any(s in (h.get("command") or "") for s in HOOK_SCRIPTS)]
            removed += len(g.get("hooks", [])) - len(hooks)
            if hooks:
                g["hooks"] = hooks
                kept.append(g)
        if kept:
            settings["hooks"][event] = kept
        else:
            settings["hooks"].pop(event, None)
    if removed:
        _save_json(SETTINGS, settings)
        print("  claude code        disconnected (%d hook entries removed)" % removed)
    else:
        print("  claude code        nothing to remove")


# ---------------------------------------------------- surface: desktop app ---

def mcp_entry():
    return {"command": _fwd(sys.executable),
            "args": [_fwd(os.path.join(MCP_DST, "recall_mcp.py"))]}


def mcp_block():
    return json.dumps({"mcpServers": {MCP_KEY: mcp_entry()}}, indent=2)


def connect_desktop(info):
    surf = info["surfaces"]["claude_desktop"]
    path = surf["config"]
    if not surf["present"]:
        print("  desktop app        not found (skipped)")
        return None
    if not surf["settings_parses"]:
        print("  ! %s will not parse - refusing to touch it" % path)
        return False
    cfg = _load_json(path)
    servers = cfg.setdefault("mcpServers", {})
    want = mcp_entry()
    if servers.get(MCP_KEY) == want:
        print("  desktop app        already connected (mcp)")
        return True
    servers[MCP_KEY] = want
    _save_json(path, cfg)
    print("  desktop app        connected via mcp - restart the app to load it")
    return True


def disconnect_desktop(info):
    path = info["surfaces"]["claude_desktop"]["config"]
    if not os.path.exists(path):
        return
    try:
        cfg = _load_json(path)
    except Exception:
        print("  desktop config will not parse - left alone")
        return
    if MCP_KEY in (cfg.get("mcpServers") or {}):
        del cfg["mcpServers"][MCP_KEY]
        _save_json(path, cfg)
        print("  desktop app        disconnected")


# ------------------------------------------------------------------ deps ----

def ensure_semantic(auto=True):
    """Semantic ranking needs numpy + model2vec. Try to install them quietly;
    fall back to lexical ranking if that cannot happen (offline, locked-down
    environment, no pip). Never fail the install over an optional extra."""
    if _importable("numpy") and _importable("model2vec"):
        print("  ranking            lexical + semantic")
        return True
    if not auto:
        print("  ranking            lexical only (--no-semantic)")
        return False
    print("  ranking            adding numpy + model2vec for semantic search ...")
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                            "numpy>=1.21", "model2vec>=0.3"],
                           capture_output=True, text=True, timeout=900)
        ok = r.returncode == 0 and _importable("numpy") and _importable("model2vec")
    except Exception:
        ok = False
    print("  ranking            %s"
          % ("lexical + semantic" if ok else
             "lexical only (the semantic extra could not be installed; "
             "everything still works)"))
    return ok


# ----------------------------------------------------------------- build ----

def build():
    scripts = os.path.join(SKILL_DST, "scripts")
    print("  index              reading transcripts in %s ..."
          % os.path.join(CLAUDE, "projects"))
    r = subprocess.run([sys.executable, os.path.join(scripts, "recall_index.py"),
                        "--build"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-1:]
    print("  index              %s"
          % (tail[0].strip() if tail else
             ("done" if r.returncode == 0
              else "build reported an error; live-scan fallback active")))
    if _importable("numpy") and _importable("model2vec"):
        r = subprocess.run([sys.executable, os.path.join(scripts, "recall_embed.py"),
                            "--build"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-1:]
        print("  vectors            %s" % (tail[0].strip() if tail else "done"))


# ---------------------------------------------------------------- doctor ----

def doctor(verbose=True):
    """Every connection, checked the way it will actually be used. Returns the
    list of problems; empty means healthy."""
    problems = []
    info = _detect.detect(HOOK_SCRIPTS, MCP_KEY)
    if verbose:
        print("claude-rework %s - doctor" % __version__)
        print(_detect.summary(info, HOOK_SCRIPTS))
        print()

    if not info["python"]["supported"]:
        problems.append(("python", "Python %s is too old; 3.9+ required"
                         % info["python"]["version"]))

    for s in HOOK_SCRIPTS:
        if not os.path.exists(os.path.join(HOOKS_DST, s)):
            problems.append(("files", "hook script missing: %s" % s))
    if not os.path.exists(os.path.join(SKILL_DST, "scripts", "recall.py")):
        problems.append(("files", "skill not installed at %s" % SKILL_DST))
    if not os.path.exists(os.path.join(MCP_DST, "recall_mcp.py")):
        problems.append(("files", "mcp server missing at %s" % MCP_DST))

    cc = info["surfaces"]["claude_code"]
    if cc["present"]:
        if not cc["settings_parses"]:
            problems.append(("claude_code", "settings.json does not parse"))
        else:
            settings = _load_json(SETTINGS)
            for event, _m, script, _w in HOOK_SPECS:
                if not _registered(settings, event, script):
                    problems.append(("claude_code", "%s hook not registered" % event))
            # a hook whose interpreter moved is a dead hook that fails silently
            for event, groups in settings.get("hooks", {}).items():
                for g in groups:
                    for h in g.get("hooks", []):
                        cmd = h.get("command") or ""
                        if not any(s in cmd for s in HOOK_SCRIPTS):
                            continue
                        if "\\" in cmd:
                            problems.append(
                                ("claude_code", "%s hook command contains backslashes "
                                                "(bash will eat them)" % event))
                        try:
                            exe = cmd.split('"')[1] if cmd.startswith('"') else cmd.split()[0]
                        except IndexError:
                            exe = ""
                        if exe and not os.path.exists(exe):
                            problems.append(
                                ("claude_code", "%s hook points at a Python that no "
                                                "longer exists: %s" % (event, exe)))

    dt = info["surfaces"]["claude_desktop"]
    if dt["present"]:
        if not dt["settings_parses"]:
            problems.append(("claude_desktop", "%s does not parse" % dt["config"]))
        elif not dt["installed"]:
            problems.append(("claude_desktop", "mcp server not registered"))
        else:
            entry = (_load_json(dt["config"]).get("mcpServers") or {}).get(MCP_KEY, {})
            if entry.get("command") and not os.path.exists(entry["command"]):
                problems.append(("claude_desktop",
                                 "mcp entry points at a Python that no longer exists"))

    if not info["index"]["corpus"]:
        problems.append(("index", "search index not built"))

    if verbose:
        if problems:
            print("  %d problem(s):" % len(problems))
            for area, msg in problems:
                print("    [%s] %s" % (area, msg))
            print()
            print("  fix them all with:  claude-rework repair")
        else:
            print("  healthy - every surface found is connected and every path resolves")
    return problems


def repair():
    """Re-run the idempotent connect steps. Anything already right is untouched;
    anything doctor flagged (missing file, moved Python, unregistered hook,
    missing index) is put back."""
    print("claude-rework %s - repair" % __version__)
    # A moved interpreter leaves hook entries pointing at nothing. Drop ours and
    # re-add them against the Python running now.
    try:
        settings = _load_json(SETTINGS)
        stale = False
        for _event, groups in settings.get("hooks", {}).items():
            for g in groups:
                for h in g.get("hooks", []):
                    cmd = h.get("command") or ""
                    if any(s in cmd for s in HOOK_SCRIPTS) and (
                            "\\" in cmd or _fwd(sys.executable) not in cmd):
                        stale = True
        if stale:
            print("  found hook entries pointing at another Python - rewriting them")
            disconnect_claude_code()
    except Exception:
        pass
    return main(["--repair"])


def update():
    """Newest version, then reconnect. pip if we came from pip; otherwise fetch
    the repo again the way the one-line installer does."""
    print("claude-rework %s - update" % __version__)
    try:
        import importlib.metadata as md
        md.version("claude-rework")
        via_pip = True
    except Exception:
        via_pip = False
    if via_pip:
        print("  upgrading via pip ...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--upgrade",
                            "claude-rework"], text=True)
        if r.returncode != 0:
            print("  pip upgrade failed - try: pip install --upgrade claude-rework")
            return 1
        # re-exec the NEW installer, not the one already imported
        return subprocess.call([sys.executable, "-m", "claude_rework.cli", "install",
                                "--no-build"])
    print("  fetching the latest installer from GitHub ...")
    import io
    import tempfile
    import urllib.request
    import zipfile
    url = "https://github.com/Luneswan/claude-rework/archive/refs/heads/main.zip"
    try:
        data = urllib.request.urlopen(url, timeout=60).read()
    except Exception as exc:
        print("  could not download (%r)" % (exc,))
        return 1
    tmp = tempfile.mkdtemp(prefix="claude-rework-update-")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(tmp)
    for name in os.listdir(tmp):
        cand = os.path.join(tmp, name, "install.py")
        if os.path.exists(cand):
            return subprocess.call([sys.executable, cand, "--no-build"])
    print("  downloaded archive had no installer")
    return 1


# ------------------------------------------------------------- uninstall ----

def uninstall():
    info = _detect.detect(HOOK_SCRIPTS, MCP_KEY)
    disconnect_claude_code()
    disconnect_desktop(info)
    for path in (SKILL_DST, MCP_DST):
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
            print("  removed            %s" % path)
    for s in HOOK_SCRIPTS:
        p = os.path.join(HOOKS_DST, s)
        if os.path.exists(p):
            os.remove(p)
    print("  removed            hook scripts")
    print()
    print("  Your memory is kept on purpose. Delete by hand if you want it gone:")
    for f in ("recall_corpus.jsonl", "recall_corpus.df.json", "recall_corpus.vec.npy",
              "recall_corpus.vec.meta.json", "recall_corpus.manifest.json",
              "events.jsonl", "recall_tuning.json", "recall_handoffs"):
        p = os.path.join(CLAUDE, f)
        if os.path.exists(p):
            print("    " + p)
    print("  Or carry it somewhere first:  claude-rework export memory.zip")


# ------------------------------------------------------------------ main ----

def main(argv=None):
    ap = argparse.ArgumentParser(prog="claude-rework install")
    ap.add_argument("--no-hooks", action="store_true", help="skip Claude Code")
    ap.add_argument("--no-desktop", action="store_true", help="skip the desktop app")
    ap.add_argument("--no-semantic", action="store_true", help="do not add extras")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--mcp-config", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--repair", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    if a.mcp_config:
        print(mcp_block())
        return 0

    print("claude-rework %s - %s" % (__version__, "repair" if a.repair else "install"))
    if not os.path.isdir(CLAUDE):
        print("  ! %s does not exist." % CLAUDE)
        print("    Open Claude Code once so it creates that folder, then run this again.")
        return 1

    info = _detect.detect(HOOK_SCRIPTS, MCP_KEY)
    print(_detect.summary(info, HOOK_SCRIPTS))
    print()

    if a.uninstall:
        uninstall()
        return 0

    copy_tree()
    if a.no_hooks:
        print("  claude code        skipped (--no-hooks)")
    elif info["surfaces"]["claude_code"]["present"]:
        connect_claude_code()
    if a.no_desktop:
        print("  desktop app        skipped (--no-desktop)")
    else:
        connect_desktop(info)
    ensure_semantic(auto=not a.no_semantic)
    if not a.no_build:
        build()

    print()
    print("  Done. Nothing else to configure.")
    print()
    print("  Open Claude - any surface - and ask in plain English:")
    print('      "what did we decide about the retry logic?"')
    print('      "where did we leave off yesterday?"')
    print()
    print("  Check any time:    claude-rework doctor")
    print("  Changing accounts: claude-rework export memory.zip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
