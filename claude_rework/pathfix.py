#!/usr/bin/env python3
"""Put the `claude-rework` command on PATH, permanently, without breaking PATH.

A pip `--user` install on Windows drops `claude-rework.exe` into
`%APPDATA%\\Python\\Python3xx\\Scripts`, which is not on PATH by default. The
package is installed correctly and the command still looks missing. Telling a
non-technical user to "add it to PATH" is not a fix; doing it for them is.

Why this does not shell out to `setx`
-------------------------------------
The obvious one-liner is the dangerous one:

    setx PATH "%PATH%;C:\\...\\Scripts"

`%PATH%` in a live shell is the *machine* PATH concatenated with the *user*
PATH. Writing that back into the user variable duplicates the whole machine
PATH into it, and `setx` silently truncates its value at 1024 characters, so a
long PATH comes back cut in half. People have destroyed their PATH this way.

Instead we read the user's own `Path` value straight out of
`HKEY_CURRENT_USER\\Environment`, append one entry if it is missing, write it
back with its original type (`REG_EXPAND_SZ` is preserved so `%VAR%` references
inside it keep working), and broadcast `WM_SETTINGCHANGE` so newly launched
programs pick it up. The machine PATH is never read and never written, and
nothing needs administrator rights.

On macOS and Linux the equivalent is a line appended to the shell profile. That
cannot take effect in the shell that is already open, which is why the caller
also prints the one-line `export` for the current session.
"""
from __future__ import annotations
import os
import sys

MARKER = "# added by claude-rework (PATH for the claude-rework command)"

# Which directory *we* put on PATH, so uninstall removes ours and never the
# user's. Without this, someone who had already added their scripts directory
# by hand would have their own entry deleted by our uninstall: on Windows a
# registry PATH carries no comments, so there is nowhere to leave a mark except
# beside our own state.
RECEIPT = "recall_pathfix.json"


def _receipt_path():
    root = os.environ.get("RECALL_HOME") or os.path.join(
        os.path.expanduser("~"), ".claude")
    return os.path.join(root, RECEIPT)


def _write_receipt(directory):
    path = _receipt_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import json
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"added": directory}, fh)
    except OSError:
        pass


def _read_receipt():
    try:
        import json
        with open(_receipt_path(), encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("added") or ""
    except (OSError, ValueError):
        return ""


def _clear_receipt():
    try:
        os.remove(_receipt_path())
    except OSError:
        pass


def scripts_dir():
    """The directory pip put the console script in, or "" if not found."""
    import sysconfig
    exe = "claude-rework" + (".exe" if os.name == "nt" else "")
    candidates = []
    try:
        candidates.append(sysconfig.get_path("scripts"))
    except Exception:
        pass
    for scheme in ("nt_user", "posix_user"):
        try:
            candidates.append(sysconfig.get_path("scripts", scheme))
        except Exception:
            pass
    # The directory holding the interpreter is where a venv keeps its scripts.
    candidates.append(os.path.dirname(os.path.abspath(sys.executable)))
    for cand in candidates:
        if cand and os.path.exists(os.path.join(cand, exe)):
            return os.path.normpath(cand)
    # Nothing found: fall back to the first real directory so `repair` still has
    # something to report rather than an empty string.
    for cand in candidates:
        if cand and os.path.isdir(cand):
            return os.path.normpath(cand)
    return ""


def _norm(p):
    """Compare paths the way the OS does, so we never add a duplicate entry."""
    if not p:
        return ""
    p = os.path.expandvars(p).strip().strip('"')
    p = os.path.normpath(p)
    return os.path.normcase(p).rstrip("\\/")


# --------------------------------------------------------------- windows ----

def _win_read_user_path():
    """(value, type) of HKCU\\Environment\\Path. ("", None) when unset."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ) as key:
            try:
                value, kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                return "", None
            return (value or ""), kind
    except OSError:
        return "", None


def _win_read_machine_path():
    """The machine PATH, read-only.

    Needed only to answer "is this directory already persisted?". A system
    Python installed for all users puts its Scripts directory here, and then
    there is nothing for us to add. We never write to this key.
    """
    import winreg
    key_path = (r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0,
                            winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "Path")
            return value or ""
    except OSError:
        return ""


def _win_write_user_path(value, kind):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, kind or winreg.REG_EXPAND_SZ, value)


def _win_broadcast():
    """Tell running programs the environment changed.

    Without this, a shell opened from an existing Explorer window keeps the old
    block until the next sign-in. Failure here is cosmetic: the registry write
    already happened, so a new terminal after a sign-out sees it regardless.
    """
    try:
        import ctypes
        from ctypes import wintypes
        send = ctypes.windll.user32.SendMessageTimeoutW
        send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                         ctypes.c_wchar_p, wintypes.UINT, wintypes.UINT,
                         ctypes.POINTER(wintypes.DWORD)]
        result = wintypes.DWORD()
        send(0xFFFF, 0x001A, 0, "Environment", 0x0002, 2000,
             ctypes.byref(result))
        return True
    except Exception:
        return False


def _win_add(directory):
    current, kind = _win_read_user_path()
    entries = [e for e in current.split(os.pathsep) if e.strip()]
    # Check the machine PATH too. A Python installed for all users already has
    # its Scripts directory there; adding a second copy to the user PATH would
    # be a redundant entry we then have to explain in `uninstall`.
    machine = [e for e in _win_read_machine_path().split(os.pathsep) if e.strip()]
    if any(_norm(e) == _norm(directory) for e in entries + machine):
        return {"ok": True, "changed": False, "reason": "already on PATH"}
    entries.append(directory)
    try:
        _win_write_user_path(os.pathsep.join(entries), kind)
    except OSError as exc:
        return {"ok": False, "changed": False, "reason": str(exc)}
    _win_broadcast()
    return {"ok": True, "changed": True, "reason": "added to your user PATH",
            "entries": len(entries)}


# ----------------------------------------------------------------- posix ----

def _profiles():
    home = os.path.expanduser("~")
    shell = os.path.basename(os.environ.get("SHELL", ""))
    names = [".profile"]
    if shell == "zsh" or sys.platform == "darwin":
        names.insert(0, ".zshrc")
    if shell == "bash":
        names.insert(0, ".bashrc")
    return [os.path.join(home, n) for n in names]


def _posix_add(directory):
    line = 'export PATH="$PATH:%s"  %s' % (directory, MARKER)
    live = [_norm(p) for p in os.environ.get("PATH", "").split(os.pathsep)]
    for path in _profiles():
        try:
            existing = ""
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="replace") as fh:
                    existing = fh.read()
            if MARKER in existing or _norm(directory) in live:
                return {"ok": True, "changed": False,
                        "reason": "already on PATH or already in %s"
                                  % os.path.basename(path)}
            with open(path, "a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(line + "\n")
            return {"ok": True, "changed": True,
                    "reason": "added to %s" % os.path.basename(path),
                    "profile": path}
        except OSError:
            continue
    return {"ok": False, "changed": False, "reason": "no writable shell profile"}


# ------------------------------------------------------------------ api -----

def add_scripts_dir_to_path(directory=None):
    """Make `claude-rework` findable in a new terminal. Idempotent.

    Returns {ok, changed, reason, directory, activate}. `activate` is the line
    that makes it work in the terminal that is *already* open - no OS can
    retrofit an environment variable into a running process.
    """
    directory = directory or scripts_dir()
    if not directory:
        return {"ok": False, "changed": False, "directory": "",
                "reason": "could not locate the scripts directory",
                "activate": ""}
    if os.name == "nt":
        out = _win_add(directory)
        out["activate"] = '$env:Path += ";%s"' % directory
    else:
        out = _posix_add(directory)
        out["activate"] = 'export PATH="$PATH:%s"' % directory
    out["directory"] = directory
    if out.get("changed"):
        _write_receipt(directory)
    return out


def path_state(directory=None):
    """Is the scripts directory on PATH right now, and is it recorded?"""
    directory = directory or scripts_dir()
    live = [_norm(p) for p in os.environ.get("PATH", "").split(os.pathsep)]
    in_live = bool(directory) and _norm(directory) in live
    persisted = in_live
    if os.name == "nt" and directory:
        # Either registry key counts: a system-wide Python already has its
        # Scripts directory on the machine PATH, and there is nothing to add.
        recorded = os.pathsep.join([_win_read_user_path()[0],
                                    _win_read_machine_path()])
        persisted = any(_norm(e) == _norm(directory)
                        for e in recorded.split(os.pathsep) if e.strip())
    elif directory:
        for path in _profiles():
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    if MARKER in fh.read():
                        persisted = True
                        break
            except OSError:
                continue
    return {"directory": directory, "in_current_shell": in_live,
            "persisted": persisted}


def remove_from_path(directory=None):
    """Undo add_scripts_dir_to_path. Used by uninstall.

    Removes only what we recorded adding. A directory the user had already put
    on their own PATH is left exactly where it was - uninstalling one tool is
    not a licence to edit someone's environment on their behalf.
    """
    if directory is None:
        directory = _read_receipt()
        if not directory:
            return {"ok": True, "changed": False,
                    "reason": "we never added anything to PATH"}
    if not directory:
        return {"ok": True, "changed": False, "reason": "nothing to remove"}
    if os.name == "nt":
        current, kind = _win_read_user_path()
        entries = [e for e in current.split(os.pathsep) if e.strip()]
        keep = [e for e in entries if _norm(e) != _norm(directory)]
        if len(keep) == len(entries):
            return {"ok": True, "changed": False, "reason": "was not in user PATH"}
        try:
            _win_write_user_path(os.pathsep.join(keep), kind)
        except OSError as exc:
            return {"ok": False, "changed": False, "reason": str(exc)}
        _win_broadcast()
        _clear_receipt()
        return {"ok": True, "changed": True, "reason": "removed from user PATH"}
    removed = False
    for path in _profiles():
        try:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            keep = [ln for ln in lines if MARKER not in ln]
            if len(keep) != len(lines):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(keep)
                removed = True
        except OSError:
            continue
    if removed:
        _clear_receipt()
    return {"ok": True, "changed": removed,
            "reason": "removed from shell profile" if removed
                      else "was not in any shell profile"}


if __name__ == "__main__":
    import json
    print(json.dumps({"scripts_dir": scripts_dir(), "state": path_state()},
                     indent=2))
