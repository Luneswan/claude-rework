#!/usr/bin/env python3
"""Find every Claude surface on this machine, and what state it is in.

The installer should never ask a question a filesystem probe can answer. This
module answers all of them: which OS, where Claude keeps its config, which
surfaces exist, whether we are already installed on each, whether the optional
dependencies are importable, and whether the index has been built.

Read-only. Nothing here writes, so it is safe to run from `status`, `doctor`,
and the installer alike.

The surfaces, and how each one is reached:

  claude_code     ~/.claude + settings.json hooks   -> hooks (free until they fire)
  claude_desktop  claude_desktop_config.json        -> MCP server (cannot run hooks)
  cowork          the desktop app's Cowork tab      -> same MCP server
  vscode / jetbrains
                  extensions that drive the CLI     -> covered by claude_code

A surface is "supported" when we can configure it without the user editing
anything. Where a surface cannot take hooks, we fall back to MCP rather than
writing a paragraph in the README about the limitation.
"""
from __future__ import annotations
import json
import os
import platform
import shutil
import sys

HOME = os.path.expanduser("~")


def claude_home():
    """~/.claude, honouring RECALL_HOME so tests can point at a fixture."""
    env = os.environ.get("RECALL_HOME")
    if env:
        return env
    return os.path.join(HOME, ".claude")


def desktop_config_path():
    """Where the Claude desktop app keeps its MCP config, per OS."""
    s = platform.system()
    if s == "Darwin":
        return os.path.join(HOME, "Library", "Application Support", "Claude",
                            "claude_desktop_config.json")
    if s == "Windows":
        base = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
        return os.path.join(base, "Claude", "claude_desktop_config.json")
    # Linux: the app is Electron; XDG config is where it lands.
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
    return os.path.join(xdg, "Claude", "claude_desktop_config.json")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _cli_on_path():
    for exe in ("claude", "claude.cmd", "claude.exe"):
        p = shutil.which(exe)
        if p:
            return p
    return None


def python_info():
    exe = sys.executable
    quiet = exe
    if os.name == "nt":
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(cand):
            quiet = cand
    return {"executable": exe, "windowless": quiet,
            "version": "%d.%d.%d" % sys.version_info[:3],
            "supported": sys.version_info >= (3, 9)}


def command_on_path(name="claude-rework"):
    """Can the user type this in a fresh terminal, from any directory?

    pip drops the executable in its scripts directory. A --user install on
    Windows, or a system Python whose scripts directory was never added, leaves
    that directory off PATH - so the command looks missing while the package is
    installed fine. Detect it and hand back the directory plus the two fixes.
    """
    found = shutil.which(name)
    scripts = ""
    try:
        import sysconfig
        scripts = sysconfig.get_path("scripts") or ""
        if not os.path.exists(os.path.join(scripts, name + (".exe" if os.name == "nt" else ""))):
            for scheme in ("nt_user", "posix_user"):
                try:
                    cand = sysconfig.get_path("scripts", scheme)
                except Exception:
                    continue
                if cand and os.path.exists(os.path.join(
                        cand, name + (".exe" if os.name == "nt" else ""))):
                    scripts = cand
                    break
    except Exception:
        pass
    module_form = "%s -m claude_rework" % os.path.basename(sys.executable)
    return {"name": name, "on_path": bool(found), "resolved": found or "",
            "scripts_dir": scripts, "module_form": module_form}


def path_advice(cmd):
    """The lines install and doctor print when the command is not on PATH."""
    lines = ["  '%s' is installed but not on your PATH, so a new terminal will"
             % cmd["name"],
             "  not find it. Either works:",
             "",
             "    1. Use it through Python, which always works:",
             "         %s status" % cmd["module_form"],
             ""]
    if cmd["scripts_dir"]:
        lines.append("    2. Add its directory to PATH once:")
        if os.name == "nt":
            lines.append('         setx PATH "%%PATH%%;%s"' % cmd["scripts_dir"])
            lines.append("       then open a new terminal.")
        else:
            lines.append('         echo \'export PATH="$PATH:%s"\' >> ~/.profile'
                         % cmd["scripts_dir"])
            lines.append("       then open a new terminal.")
    return lines


def dependencies():
    out = {}
    for mod in ("numpy", "model2vec"):
        try:
            __import__(mod)
            out[mod] = True
        except Exception:
            out[mod] = False
    out["semantic_ready"] = all(out.get(m) for m in ("numpy", "model2vec"))
    return out


def _hooks_installed(settings, scripts):
    """Which of our hook scripts are registered, by event."""
    found = {}
    for event, groups in (settings or {}).get("hooks", {}).items():
        for g in groups or []:
            for h in g.get("hooks", []) or []:
                cmd = h.get("command") or ""
                for s in scripts:
                    if s in cmd:
                        found.setdefault(event, []).append(s)
    return found


def _count_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except Exception:
        return 0


def detect(hook_scripts=(), mcp_key="claude-rework"):
    """Everything the installer needs, in one dict."""
    root = claude_home()
    settings_path = os.path.join(root, "settings.json")
    settings = _read_json(settings_path)
    desktop_path = desktop_config_path()
    desktop_cfg = _read_json(desktop_path)

    corpus = os.path.join(root, "recall_corpus.jsonl")
    projects = os.path.join(root, "projects")
    transcripts = 0
    if os.path.isdir(projects):
        try:
            for name in os.listdir(projects):
                d = os.path.join(projects, name)
                if os.path.isdir(d):
                    transcripts += sum(1 for f in os.listdir(d)
                                       if f.endswith(".jsonl"))
        except OSError:
            pass

    surfaces = {}

    # Claude Code: the directory is the surface. Hooks are how we reach it.
    installed_events = _hooks_installed(settings, hook_scripts)
    surfaces["claude_code"] = {
        "name": "Claude Code (terminal, VS Code, JetBrains)",
        "present": os.path.isdir(root),
        "integration": "hooks",
        "config": settings_path,
        "cli": _cli_on_path(),
        "installed": bool(installed_events),
        "installed_events": sorted(installed_events),
        "settings_parses": settings is not None or not os.path.exists(settings_path),
    }

    # Claude desktop app / Cowork: no hooks, so MCP.
    dir_exists = os.path.isdir(os.path.dirname(desktop_path))
    mcp_servers = (desktop_cfg or {}).get("mcpServers") or {}
    surfaces["claude_desktop"] = {
        "name": "Claude desktop app / Cowork",
        "present": dir_exists,
        "integration": "mcp",
        "config": desktop_path,
        "installed": mcp_key in mcp_servers,
        "settings_parses": desktop_cfg is not None or not os.path.exists(desktop_path),
    }

    return {
        "os": {"system": platform.system(), "release": platform.release(),
               "machine": platform.machine()},
        "python": python_info(),
        "command": command_on_path(),
        "deps": dependencies(),
        "claude_home": root,
        "surfaces": surfaces,
        "index": {
            "corpus": os.path.exists(corpus),
            "corpus_lines": _count_lines(corpus),
            "vectors": os.path.exists(os.path.join(root, "recall_corpus.vec.npy")),
            "events": os.path.exists(os.path.join(root, "events.jsonl")),
            "transcripts": transcripts,
        },
    }


def summary(info=None, hook_scripts=()):
    """Human-readable, and the same text `status` and the installer both print."""
    info = info or detect(hook_scripts)
    lines = []
    o, p, d = info["os"], info["python"], info["deps"]
    lines.append("  system   %s %s (%s), Python %s%s"
                 % (o["system"], o["release"], o["machine"], p["version"],
                    "" if p["supported"] else "  ! needs 3.9+"))
    for key, s in info["surfaces"].items():
        if not s["present"]:
            state = "not found"
        elif s["installed"]:
            state = "connected via %s" % s["integration"]
        else:
            state = "found, not connected"
        lines.append("  %-16s %s" % (key, state))
        if s["present"] and not s.get("settings_parses", True):
            lines.append("      ! %s will not parse - fix or move it" % s["config"])
    ix = info["index"]
    lines.append("  index    %s, %d transcript file(s)%s"
                 % ("%d entries" % ix["corpus_lines"] if ix["corpus"] else "not built",
                    ix["transcripts"],
                    ", vectors ready" if ix["vectors"] else ""))
    if not d["semantic_ready"]:
        missing = [m for m in ("numpy", "model2vec") if not d.get(m)]
        lines.append("  ranking  lexical only (pip install %s for semantic)"
                     % " ".join(missing))
    else:
        lines.append("  ranking  lexical + semantic")
    cmd = info.get("command") or {}
    if cmd:
        lines.append("  command  %s"
                     % ("`%s` on PATH, usable from any directory" % cmd["name"]
                        if cmd["on_path"]
                        else "NOT on PATH - use `%s`" % cmd["module_form"]))
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
