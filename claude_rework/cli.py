"""The `claude-rework` command (`claude-recall` is an alias).

Setup, and keeping it working:

    claude-rework install          connect every Claude surface on this machine
    claude-rework status           what is connected, what is indexed
    claude-rework doctor           check every connection; say what is wrong
    claude-rework repair           fix what doctor found
    claude-rework update           newest version, reconnected
    claude-rework uninstall        remove everything; keep your memory

Moving between accounts and machines:

    claude-rework export FILE.zip  projects, paths, context, history, profile
    claude-rework import FILE.zip  merge a bundle into this machine
    claude-rework inspect FILE.zip see what a bundle holds before importing
    claude-rework import-web FILE  a Claude data export, for web/app history
    claude-rework profile          what Claude knows about you

Asking directly (you rarely need to - the hooks do it for you):

    claude-rework "<question>"     ask your history
    claude-rework --brief --days 2 what was asked, done, still open
    claude-rework test             run the bundled suites
    claude-rework mcp-config       print the desktop app config block
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

from . import __version__

USAGE = __doc__


def _claude():
    return os.environ.get("RECALL_HOME") or os.path.join(os.path.expanduser("~"),
                                                         ".claude")


def _installed(*parts):
    p = os.path.join(_claude(), "skills", "recall", *parts)
    return p if os.path.exists(p) else None


def _need_installed(what):
    print("claude-rework is not installed on this machine.")
    print("  run:  claude-rework install")
    print("  then: %s" % what)
    return 1


def _reindex():
    idx = _installed("scripts", "recall_index.py")
    if not idx:
        print("  (run `claude-rework install` here to search the merged history)")
        return
    print()
    print("  rebuilding the search index over the merged history ...")
    subprocess.call([sys.executable, idx, "--build"])
    emb = _installed("scripts", "recall_embed.py")
    if emb:
        subprocess.call([sys.executable, emb, "--build"])


def _show_profile():
    from . import portable
    prof = portable.build_profile(_claude())
    print("claude-rework %s - profile" % __version__)
    print()
    if prof.get("first_seen"):
        print("  history      %s to %s  (%d days)"
              % (prof["first_seen"], prof["last_seen"], prof.get("span_days", 0)))
    ident, prefs = prof.get("identity", []), prof.get("preferences", [])
    print("  about you    %d fact(s)" % len(ident))
    for e in ident[:6]:
        print("      - %s" % e["text"].replace("\n", " ")[:100])
    print("  preferences  %d" % len(prefs))
    for e in prefs[:6]:
        print("      - %s" % e["text"].replace("\n", " ")[:100])
    projects = prof.get("projects", [])
    print("  projects     %d with history" % len(projects))
    for p in projects[:10]:
        print("      %-40s %s" % (p["slug"][:40], p["path"]))
    if not (ident or prefs):
        print()
        print("  Nothing saved about you yet. Tell Claude something durable and it")
        print("  will keep it, or save one now:")
        print('      claude-rework --write "I prefer terse answers and no preamble" \\')
        print('          --name how-i-like-answers --type user')
    print()
    print("  This travels with `claude-rework export` so a new account knows you.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE.strip())
        return 0
    if argv[0] in ("-V", "--version", "version"):
        print("claude-rework " + __version__)
        return 0

    cmd, rest = argv[0], argv[1:]

    if cmd == "install":
        from . import installer
        return installer.main(rest)
    if cmd == "uninstall":
        from . import installer
        return installer.main(["--uninstall"])
    if cmd == "mcp-config":
        from . import installer
        return installer.main(["--mcp-config"])
    if cmd == "status":
        from . import detect, installer
        print("claude-rework %s" % __version__)
        print(detect.summary(hook_scripts=installer.HOOK_SCRIPTS))
        return 0
    if cmd == "doctor":
        from . import installer
        return 1 if installer.doctor() else 0
    if cmd == "repair":
        from . import installer
        return installer.repair()
    if cmd == "update":
        from . import installer
        return installer.update()
    if cmd == "profile":
        return _show_profile()

    if cmd == "export":
        from . import portable
        args = [a for a in rest if not a.startswith("-")]
        dest = args[0] if args else "claude-rework-memory.zip"
        return portable.export(dest, with_transcripts="--with-transcripts" in rest)
    if cmd == "import":
        if not rest:
            print("usage: claude-rework import FILE.zip")
            return 2
        from . import portable
        rc = portable.import_bundle(rest[0])
        if rc == 0:
            _reindex()
        return rc
    if cmd == "import-web":
        if not rest:
            print("usage: claude-rework import-web conversations.json")
            print()
            print("  For history that lives in the Claude web or desktop app rather")
            print("  than on disk. Get the file from Claude ->  Settings -> Privacy")
            print("  -> Export data; it arrives by email as a zip. Pass the zip or")
            print("  the conversations.json inside it.")
            return 2
        from . import portable
        rc = portable.import_web(rest[0])
        if rc == 0:
            _reindex()
        return rc
    if cmd == "inspect":
        if not rest:
            print("usage: claude-rework inspect FILE.zip")
            return 2
        from . import portable
        return portable.describe(rest[0])

    if cmd == "test":
        t = _installed("tests", "run_tests.py")
        if not t:
            return _need_installed("run the tests")
        return subprocess.call([sys.executable, t] + rest)

    recall = _installed("scripts", "recall.py")
    if not recall:
        return _need_installed("ask it anything")
    return subprocess.call([sys.executable, recall] + argv)


if __name__ == "__main__":
    sys.exit(main())
