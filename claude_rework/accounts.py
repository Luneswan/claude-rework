#!/usr/bin/env python3
"""Which Claude account is signed in, so a bundle can say where it came from.

Moving memory between accounts used to produce a pile of identically named
`claude-rework-memory.zip` files with no way to tell which account each one
held. This reads the signed-in account and turns it into a short label, so an
export lands as `claude-rework-alex-20260903.zip` and `inspect` can tell you
whose history is inside before you import it.

Where the account lives
-----------------------
Claude Code keeps it in `~/.claude.json` - note the dot-json file *beside* the
`~/.claude` directory, not inside it - under `oauthAccount`:

    {"oauthAccount": {"emailAddress": "alex@example.com",
                      "accountUuid": "...", "organizationName": "..."}}

Only the part of the address before the `@` becomes the label. The full address,
the account UUID and the organization UUID are never written into a bundle or a
filename: the local part is enough to tell two of your own accounts apart, which
is the whole job. If you would rather it were not there at all, pass an explicit
name - `claude-rework export mine.zip` - and nothing is derived.

Signing out and into another account rewrites this file, so the label follows
the switch with no state of our own to keep in sync.
"""
from __future__ import annotations
import json
import os
import re

FALLBACK = "unknown-account"


def _candidates(root=None):
    """Where `.claude.json` might be, most specific first.

    RECALL_HOME points tests (and anyone relocating state) at a fixture
    directory; its sibling is checked first so a fixture account wins over the
    real signed-in one.
    """
    home = os.path.expanduser("~")
    if root:
        # An explicit root means "look here, not at whoever is signed in".
        # Falling through to ~ would let a fixture - or a relocated state
        # directory - report the real account, which is exactly the leak a
        # fixture exists to avoid. The normal case still resolves, because the
        # sibling of ~/.claude *is* ~/.claude.json.
        out = [os.path.join(os.path.dirname(os.path.abspath(root)),
                            ".claude.json"),
               os.path.join(root, ".claude.json")]
    else:
        out = [os.path.join(home, ".claude.json")]
    seen, uniq = set(), []
    for p in out:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def read_account(root=None):
    """{email, local, uuid, organization, source} - values absent when unknown.

    Never raises: a missing or unparseable file just means we do not know, and
    every caller has a sensible answer for that.
    """
    for path in _candidates(root):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        acct = data.get("oauthAccount") or {}
        email = (acct.get("emailAddress") or "").strip()
        if not (email or acct.get("accountUuid")):
            continue
        return {"email": email,
                "local": email.split("@")[0] if email else "",
                "uuid": acct.get("accountUuid") or "",
                "organization": acct.get("organizationName") or "",
                "source": path}
    return {"email": "", "local": "", "uuid": "", "organization": "",
            "source": ""}


def label(root=None, account=None):
    """A short, filesystem-safe token identifying the account.

    Derived from the email local part. Falls back to the account UUID's first
    block, then to a fixed string, so a filename is always produced.
    """
    account = account or read_account(root)
    raw = account.get("local") or ""
    if not raw and account.get("uuid"):
        raw = account["uuid"].split("-")[0]
    if not raw:
        return FALLBACK
    # Keep letters, digits, dot, dash and underscore; collapse the rest.
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._")
    clean = re.sub(r"-{2,}", "-", clean)
    return (clean or FALLBACK)[:48]


def describe(root=None, account=None):
    """One line for `status` and the export banner."""
    account = account or read_account(root)
    if not (account.get("email") or account.get("uuid")):
        return "not signed in (or ~/.claude.json not readable)"
    who = account.get("email") or account.get("uuid")[:8]
    org = account.get("organization")
    # An organization named after the address itself adds nothing to read.
    if org and account.get("email") and not org.startswith(account["email"]):
        return "%s  (%s)" % (who, org)
    return who


def suggest_export_name(root=None, account=None, when=None, directory=""):
    """`claude-rework-<account>-<YYYYMMDD>.zip`, unique against what exists.

    The date makes successive exports from one account sortable rather than
    overwriting; a `-2` suffix is only reached if two run on the same day.
    """
    import datetime
    stamp = (when or datetime.date.today()).strftime("%Y%m%d")
    base = "claude-rework-%s-%s" % (label(root, account), stamp)
    name = base + ".zip"
    n = 2
    while os.path.exists(os.path.join(directory, name) if directory else name):
        name = "%s-%d.zip" % (base, n)
        n += 1
    return os.path.join(directory, name) if directory else name


if __name__ == "__main__":
    acct = read_account()
    print(json.dumps({"describe": describe(account=acct),
                      "label": label(account=acct),
                      "suggested": suggest_export_name(account=acct),
                      "found_in": acct.get("source") or "(nothing found)"},
                     indent=2))
