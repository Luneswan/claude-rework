#!/usr/bin/env python3
"""One-line install, no pip required.

    curl -fsSL https://raw.githubusercontent.com/Luneswan/claude-rework/main/install.py | python3 -
    iwr -useb  https://raw.githubusercontent.com/Luneswan/claude-rework/main/install.py | python -

Also works as `python install.py` from a clone. Either way it ends up running
claude_rework.installer, which is what `pip install claude-rework` followed by
`python -m claude_rework install` runs too. One code path, three ways in.

When run from stdin there is no repo on disk and no __file__; this fetches the
repository once into a temp dir and installs from there.
"""
from __future__ import annotations
import os
import sys

REPO_ZIP = "https://github.com/Luneswan/claude-rework/archive/refs/heads/main.zip"


def _repo_root():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = ""
    if here and os.path.exists(os.path.join(here, "claude_rework", "installer.py")):
        return here
    import io
    import tempfile
    import urllib.request
    import zipfile
    print("  fetching claude-rework from GitHub (one-time, ~100 KB) ...")
    data = urllib.request.urlopen(REPO_ZIP, timeout=60).read()
    tmp = tempfile.mkdtemp(prefix="claude-rework-")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(tmp)
    for name in os.listdir(tmp):
        cand = os.path.join(tmp, name)
        if os.path.exists(os.path.join(cand, "claude_rework", "installer.py")):
            return cand
    raise SystemExit("  ! downloaded archive did not contain the installer")


def main():
    root = _repo_root()
    sys.path.insert(0, root)
    from claude_rework.installer import main as install
    return install(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
