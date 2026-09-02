#!/usr/bin/env python3
"""Take your memory with you: new account, new laptop, same Claude.

Switching Claude accounts gives you a clean `~/.claude`. Your transcripts stay
behind with the old account, so Claude forgets every decision you ever made,
every project you work on, and who you are. The same happens on a new machine,
a reinstall, or a work-to-personal move.

    claude-rework export memory.zip                 everything worth keeping
    claude-rework export memory.zip --with-transcripts   plus the raw sessions
    claude-rework import memory.zip                 merge it into this machine
    claude-rework inspect memory.zip                look before you import

What travels:

  the search index      every message and conclusion already extracted
  the project registry  every project, its real path on disk, its slug
  project context       each project's CLAUDE.md and memory notes
  the activity log      what was actually edited and run
  your profile          who you are, how you work, what you have told Claude
  raw transcripts       only with --with-transcripts (large, exact)

What never travels: settings.json, hooks, credentials, API keys, OAuth tokens,
or anything about the account itself. This is your *content*, not your
configuration - so a bundle is portable across accounts, machines and operating
systems, and it cannot leak a secret it never contained.

Import is a MERGE, never a replace. Records are keyed on
(source file, timestamp, text) - the same key the index builder dedupes on - so
importing the same bundle twice changes nothing, importing a colleague's export
adds to yours without destroying either, and a note you already wrote is never
overwritten.

Two rules hold, because this is the one feature that moves your actual words:
  - It only ever runs when you type it. Nothing exports on a schedule.
  - The bundle is a plain zip. Open it, read it, delete anything you would
    rather not carry, then import the rest.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import os
import zipfile

SCHEMA = 2
CORPUS = "recall_corpus.jsonl"
EVENTS = "events.jsonl"
DF = "recall_corpus.df.json"
PROJECTS = "projects"
CONTEXT_FILES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md")
REGISTRY = "recall_projects.json"


def _home():
    env = os.environ.get("RECALL_HOME")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), ".claude")


def _machine_id(root):
    """Stable, local, and not derived from anything identifying - it exists only
    so a merged corpus can say which bundle a record arrived in."""
    salt_path = os.path.join(root, "recall_card.salt")
    try:
        salt = open(salt_path, encoding="utf-8").read().strip()
    except Exception:
        salt = os.path.basename(os.path.normpath(root))
    return hashlib.sha256(salt.encode("utf-8", "replace")).hexdigest()[:8]


def slug_to_path(slug):
    """Claude Code names a project directory after its absolute path, with the
    separators replaced by dashes: C:\\Users\\me\\code\\api becomes
    C--Users-me-code-api. Recovering the path is a guess (a real dash in a
    folder name is indistinguishable from a separator), so the decoded value is
    a hint for a human, and the slug stays the key everything is stored under."""
    if not slug:
        return ""
    s = slug.replace("--", ":/", 1) if "--" in slug[:3] else slug
    return s.replace("-", "/")


def _project_registry(root):
    """Every project Claude has seen here: slug, decoded path, how much history."""
    base = os.path.join(root, PROJECTS)
    out = []
    if not os.path.isdir(base):
        return out
    for slug in sorted(os.listdir(base)):
        d = os.path.join(base, slug)
        if not os.path.isdir(d):
            continue
        try:
            names = os.listdir(d)
        except OSError:
            continue
        transcripts = [n for n in names if n.endswith(".jsonl")]
        mem = os.path.join(d, "memory")
        notes = ([n for n in os.listdir(mem) if n.endswith(".md")]
                 if os.path.isdir(mem) else [])
        ctx = [n for n in CONTEXT_FILES if os.path.exists(os.path.join(d, n))]
        out.append({"slug": slug, "path": slug_to_path(slug),
                    "transcripts": len(transcripts), "notes": len(notes),
                    "context_files": ctx})
    return out


def _iter_notes(root):
    """Curated notes: projects/<slug>/memory/*.md - the hand-written facts."""
    base = os.path.join(root, PROJECTS)
    if not os.path.isdir(base):
        return
    for slug in sorted(os.listdir(base)):
        mem = os.path.join(base, slug, "memory")
        if not os.path.isdir(mem):
            continue
        for name in sorted(os.listdir(mem)):
            if name.endswith(".md"):
                yield slug, name, os.path.join(mem, name)


def _iter_context(root):
    """Per-project CLAUDE.md and friends - the standing instructions that make
    Claude behave the same way in that repo on the new machine."""
    base = os.path.join(root, PROJECTS)
    if not os.path.isdir(base):
        return
    for slug in sorted(os.listdir(base)):
        d = os.path.join(base, slug)
        if not os.path.isdir(d):
            continue
        for name in CONTEXT_FILES:
            p = os.path.join(d, name)
            if os.path.exists(p):
                yield slug, name, p
    for name in CONTEXT_FILES:                    # the global one, if present
        p = os.path.join(root, name)
        if os.path.exists(p):
            yield "__global__", name, p


def _key(rec):
    return (rec.get("f", ""), rec.get("t", 0), rec.get("m", ""))


def _read_jsonl(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except OSError:
        return


def build_profile(root):
    """Who is using this, in the new account's words on day one.

    Assembled from what is already on disk - notes the user explicitly saved as
    `user` or `feedback`, the projects they work in, and how long the history
    runs. Nothing is inferred from the raw text of conversations, and nothing
    here leaves the machine unless the user runs `export` themselves.
    """
    profile = {"identity": [], "preferences": [], "projects": [], "span_days": 0,
               "generated": datetime.datetime.now().isoformat(timespec="seconds")}
    for slug, name, path in _iter_notes(root):
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        head = text[:1200]
        kind = ""
        for line in head.splitlines():
            ls = line.strip()
            if ls.startswith("type:"):
                kind = ls.split(":", 1)[1].strip()
                break
        body = text.split("---", 2)[-1].strip()
        entry = {"note": name[:-3], "project": slug, "text": body[:400]}
        if kind == "user":
            profile["identity"].append(entry)
        elif kind == "feedback":
            profile["preferences"].append(entry)

    reg = _project_registry(root)
    profile["projects"] = [{"slug": p["slug"], "path": p["path"],
                            "transcripts": p["transcripts"]}
                           for p in reg if p["transcripts"]]

    times = [r.get("t", 0) for r in _read_jsonl(os.path.join(root, CORPUS))
             if r.get("t")]
    if times:
        profile["span_days"] = int((max(times) - min(times)) / 86400)
        profile["first_seen"] = datetime.date.fromtimestamp(min(times)).isoformat()
        profile["last_seen"] = datetime.date.fromtimestamp(max(times)).isoformat()
    return profile


def write_profile_note(root, profile):
    """Land the profile where the session-start hook and search already look, so
    the new account knows the person from its very first message."""
    slug = "__global__"
    d = os.path.join(root, PROJECTS, slug, "memory")
    os.makedirs(d, exist_ok=True)
    lines = ["---", "name: who-i-am",
             "description: Who this person is and how they work, carried over from "
             "a previous Claude account or machine.", "metadata:", "  type: user",
             "---", ""]
    if profile.get("first_seen"):
        lines.append("History carried over spans %s to %s (%d days)."
                     % (profile["first_seen"], profile["last_seen"],
                        profile.get("span_days", 0)))
        lines.append("")
    if profile.get("identity"):
        lines.append("**About them**")
        for e in profile["identity"][:12]:
            lines.append("- %s" % e["text"].replace("\n", " ")[:300])
        lines.append("")
    if profile.get("preferences"):
        lines.append("**How they want work done**")
        for e in profile["preferences"][:12]:
            lines.append("- %s" % e["text"].replace("\n", " ")[:300])
        lines.append("")
    if profile.get("projects"):
        lines.append("**Projects they work in**")
        for p in profile["projects"][:20]:
            lines.append("- `%s` (%d session file(s)) - %s"
                         % (p["slug"], p["transcripts"], p["path"]))
        lines.append("")
    path = os.path.join(d, "who-i-am.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return path


def ensure_indexed(root, verbose=True):
    """Index now, not at the next session.

    Someone who installs and immediately migrates has never sent a message, so
    no hook has ever fired. Export must not hand them a bundle built from an
    index that does not exist yet - or one that predates transcripts written
    since. Cheap when already current: the build is incremental.
    """
    corpus = os.path.join(root, CORPUS)
    builder = os.path.join(root, "skills", "recall", "scripts", "recall_index.py")
    if not os.path.exists(builder):
        return False
    newest = 0.0
    base = os.path.join(root, PROJECTS)
    if os.path.isdir(base):
        for slug in os.listdir(base):
            d = os.path.join(base, slug)
            if not os.path.isdir(d):
                continue
            try:
                for name in os.listdir(d):
                    if name.endswith(".jsonl"):
                        newest = max(newest, os.path.getmtime(os.path.join(d, name)))
            except OSError:
                pass
    try:
        current = os.path.getmtime(corpus)
    except OSError:
        current = 0.0
    if current and newest <= current:
        return True
    if verbose:
        print("  index              %s - building it now ..."
              % ("not built yet" if not current else "older than your transcripts"))
    import subprocess
    import sys as _sys
    try:
        subprocess.run([_sys.executable, builder, "--build"], capture_output=True,
                       text=True, timeout=1800)
    except Exception:
        return False
    return os.path.exists(corpus)


def export(dest, root=None, verbose=True, with_transcripts=False):
    root = root or _home()
    ensure_indexed(root, verbose)
    corpus_path = os.path.join(root, CORPUS)
    events_path = os.path.join(root, EVENTS)
    notes = list(_iter_notes(root))
    context = list(_iter_context(root))
    registry = _project_registry(root)
    profile = build_profile(root)

    n_corpus = sum(1 for _ in _read_jsonl(corpus_path))
    n_events = sum(1 for _ in _read_jsonl(events_path))
    if not (n_corpus or n_events or notes or registry):
        print("  nothing to export yet - run: claude-rework install")
        return 1

    manifest = {
        "schema": SCHEMA,
        "tool": "claude-rework",
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_machine": _machine_id(root),
        "counts": {"corpus": n_corpus, "events": n_events, "notes": len(notes),
                   "projects": len(registry), "context_files": len(context)},
        "projects": registry,
        "profile": profile,
    }

    dest = os.path.abspath(dest)
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)

    n_tx = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        for name, path in ((CORPUS, corpus_path), (EVENTS, events_path),
                           (DF, os.path.join(root, DF))):
            if os.path.exists(path):
                z.write(path, name)
        for slug, name, path in notes:
            z.write(path, "notes/%s/%s" % (slug, name))
        for slug, name, path in context:
            z.write(path, "context/%s/%s" % (slug, name))
        if with_transcripts:
            base = os.path.join(root, PROJECTS)
            for p in registry:
                d = os.path.join(base, p["slug"])
                for name in sorted(os.listdir(d)):
                    if name.endswith(".jsonl"):
                        z.write(os.path.join(d, name),
                                "transcripts/%s/%s" % (p["slug"], name))
                        n_tx += 1

    if verbose:
        size = os.path.getsize(dest) / 1024.0 / 1024.0
        print("  wrote %s  (%.1f MB)" % (dest, size))
        print("    %d indexed entries across %d project(s)" % (n_corpus, len(registry)))
        print("    %d activity records, %d note(s), %d context file(s)"
              % (n_events, len(notes), len(context)))
        if with_transcripts:
            print("    %d raw transcript file(s)" % n_tx)
        else:
            print("    raw transcripts NOT included - add --with-transcripts for those")
        ident = len(profile.get("identity", [])) + len(profile.get("preferences", []))
        print("    profile: %d fact(s) about you, %d project path(s)"
              % (ident, len(profile.get("projects", []))))
        print()
        print("  On the other account or machine:")
        print("      pip install claude-rework && claude-rework install")
        print("      claude-rework import %s" % os.path.basename(dest))
        print()
        print("  It is a plain zip - open it and delete anything you would rather")
        print("  not carry across before importing.")
    return 0


def _merge_jsonl(z, member, target):
    """Union by (file, timestamp, text). Importing twice is a no-op."""
    try:
        raw = z.read(member).decode("utf-8", "replace")
    except Exception:
        return 0, 0
    incoming = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            incoming.append(json.loads(line))
        except Exception:
            continue
    seen = {_key(r) for r in _read_jsonl(target)}
    added = []
    for r in incoming:
        k = _key(r)
        if k in seen:
            continue
        seen.add(k)
        # Mark it as imported. The index builder keeps records whose source
        # transcript still exists locally; these came from another machine and
        # never will, so without this flag the first rebuild after an import
        # silently deletes everything that was just migrated.
        r["im"] = 1
        added.append(r)
    if added:
        with open(target, "a", encoding="utf-8", newline="\n") as fh:
            for r in added:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(added), len(incoming) - len(added)


def _safe_member(member, prefix, depth):
    """A path out of an archive is untrusted. Accept only
    <prefix>/<segment>/.../<name> with no separators, drive letters or dot-dots."""
    if not member.startswith(prefix + "/") or member.endswith("/"):
        return None
    parts = member.split("/")
    if len(parts) != depth + 1:
        return None
    for p in parts[1:]:
        if not p or p in (".", "..") or "\\" in p or ":" in p or os.path.isabs(p):
            return None
    return parts[1:]


def import_bundle(src, root=None, verbose=True):
    root = root or _home()
    if not os.path.exists(src):
        print("  no such file: %s" % src)
        return 1
    os.makedirs(root, exist_ok=True)
    try:
        z = zipfile.ZipFile(src)
    except Exception as exc:
        print("  not a readable bundle (%r)" % (exc,))
        return 1

    with z:
        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8", "replace"))
        except Exception:
            print("  bundle has no manifest - refusing to import an unknown archive")
            return 1
        if manifest.get("schema") not in (1, SCHEMA):
            print("  bundle schema %r, this build reads 1 and %d - refusing"
                  % (manifest.get("schema"), SCHEMA))
            return 1
        if verbose:
            print("  bundle from %s, created %s"
                  % (manifest.get("source_machine", "?"), manifest.get("created", "?")))

        added_c, dup_c = _merge_jsonl(z, CORPUS, os.path.join(root, CORPUS))
        added_e, dup_e = _merge_jsonl(z, EVENTS, os.path.join(root, EVENTS))

        notes_added = notes_kept = 0
        ctx_added = ctx_kept = 0
        tx_added = 0
        for member in z.namelist():
            parts = _safe_member(member, "notes", 2)
            if parts and member.endswith(".md"):
                slug, name = parts
                d = os.path.join(root, PROJECTS, slug, "memory")
                os.makedirs(d, exist_ok=True)
                dst = os.path.join(d, name)
                if os.path.exists(dst):
                    notes_kept += 1        # never overwrite a note written here
                    continue
                with open(dst, "wb") as fh:
                    fh.write(z.read(member))
                notes_added += 1
                continue

            parts = _safe_member(member, "context", 2)
            if parts:
                slug, name = parts
                d = root if slug == "__global__" else os.path.join(root, PROJECTS, slug)
                os.makedirs(d, exist_ok=True)
                dst = os.path.join(d, name)
                if os.path.exists(dst):
                    ctx_kept += 1
                    continue
                with open(dst, "wb") as fh:
                    fh.write(z.read(member))
                ctx_added += 1
                continue

            parts = _safe_member(member, "transcripts", 2)
            if parts and member.endswith(".jsonl"):
                slug, name = parts
                d = os.path.join(root, PROJECTS, slug)
                os.makedirs(d, exist_ok=True)
                dst = os.path.join(d, name)
                if os.path.exists(dst):
                    continue
                with open(dst, "wb") as fh:
                    fh.write(z.read(member))
                tx_added += 1

        # The project registry: which projects exist and where they lived. Kept
        # as data so `recall --stores` and the profile note can name real paths
        # even when the folders themselves are not on this machine yet.
        registry = manifest.get("projects") or []
        if registry:
            reg_path = os.path.join(root, REGISTRY)
            existing = {}
            try:
                existing = {p["slug"]: p for p in json.load(open(reg_path,
                                                                encoding="utf-8"))}
            except Exception:
                pass
            for p in registry:
                existing.setdefault(p["slug"], p)
            with open(reg_path, "w", encoding="utf-8") as fh:
                json.dump(sorted(existing.values(), key=lambda x: x["slug"]), fh,
                          indent=2)
            for p in registry:
                os.makedirs(os.path.join(root, PROJECTS, p["slug"]), exist_ok=True)

        profile = manifest.get("profile") or {}
        profile_path = ""
        if profile:
            profile_path = write_profile_note(root, profile)

    if verbose:
        print("  merged  %d new indexed entries (%d already present)" % (added_c, dup_c))
        print("          %d new activity records (%d already present)" % (added_e, dup_e))
        print("          %d new note(s), %d local note(s) left untouched"
              % (notes_added, notes_kept))
        print("          %d context file(s), %d left untouched" % (ctx_added, ctx_kept))
        if tx_added:
            print("          %d raw transcript file(s)" % tx_added)
        if registry:
            print("          %d project(s) registered with their original paths"
                  % len(registry))
        if profile_path:
            print("          profile written to %s" % profile_path)
            print("          Claude will know who you are from its next session.")
    return 0


def describe(src):
    """What is in a bundle, without importing it."""
    try:
        with zipfile.ZipFile(src) as z:
            manifest = json.loads(z.read("manifest.json").decode("utf-8", "replace"))
            names = z.namelist()
    except Exception as exc:
        print("  cannot read %s (%r)" % (src, exc))
        return 1
    c = manifest.get("counts", {})
    print("  created        %s  (schema %s, from %s)"
          % (manifest.get("created", "?"), manifest.get("schema", "?"),
             manifest.get("source_machine", "?")))
    print("  contents       %d indexed entries, %d activity records, %d notes"
          % (c.get("corpus", 0), c.get("events", 0), c.get("notes", 0)))
    print("                 %d project(s), %d context file(s)"
          % (c.get("projects", 0), c.get("context_files", 0)))
    tx = sum(1 for n in names if n.startswith("transcripts/"))
    print("                 %s"
          % ("%d raw transcript file(s)" % tx if tx else "no raw transcripts"))
    prof = manifest.get("profile") or {}
    if prof:
        print("  profile        %d fact(s) about the person, %d preference(s)"
              % (len(prof.get("identity", [])), len(prof.get("preferences", []))))
        if prof.get("first_seen"):
            print("                 history %s to %s"
                  % (prof["first_seen"], prof.get("last_seen", "?")))
    print()
    print("  projects in this bundle:")
    for p in (manifest.get("projects") or [])[:25]:
        print("    %-42s %s" % (p.get("slug", "?")[:42], p.get("path", "")))
    return 0
