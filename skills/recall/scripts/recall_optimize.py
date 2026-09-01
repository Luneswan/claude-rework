#!/usr/bin/env python3
"""recall_optimize - act on the budget report instead of only printing it.

Skills live in two tiers:
  ~/.claude/skills/           auto-loaded; costs its description every session
  ~/.claude/skills-library/   stored; costs nothing until the router picks it

Both tiers are fully routable, so demotion is **not** removal - the skill keeps
working, it just stops charging rent on every session. Nothing is ever deleted,
and every move is a directory rename that git can undo.

Decisions come from measured routing (~/.claude/hooks/skill_usage.jsonl), never
from taste:

  DEMOTE   loaded, zero routes in the window, and costs real tokens
  PROMOTE  library, routed repeatedly - it earned a place in the loaded set
  GAP      prompts that repeatedly match nothing -> worth a new skill

Imported by recall.py as --optimize / --optimize --apply.
"""
from __future__ import annotations
import collections
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

def _claude_root():
    """RECALL_HOME wins when set: the tool resolves its data directory from its own
    location, which is right for normal use and wrong for testing - pointing HOME
    at another machine still read the real corpus. An explicit override makes the
    data directory a parameter, so a foreign corpus can actually be exercised."""
    env = os.environ.get("RECALL_HOME")
    if env and os.path.isdir(env):
        return env
    """Walk up to the .claude directory. Depth-independent, so this file keeps
    working whether it lives in ~/.claude/scripts or inside a skill folder."""
    d = os.path.dirname(os.path.abspath(__file__))
    while d and os.path.basename(d) != ".claude":
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.expanduser("~/.claude")
        d = parent
    return d


CLAUDE = _claude_root()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.dirname(CLAUDE)
SKILLS = os.path.join(CLAUDE, "skills")
LIBRARY = os.path.join(CLAUDE, "skills-library")
DEMOTED = os.path.join(LIBRARY, "demoted")
USAGE = os.path.join(CLAUDE, "hooks", "skill_usage.jsonl")
PINNED = os.path.join(CLAUDE, "always_skills.json")
INDEX = os.path.join(CLAUDE, "skill_index.json")
BUILDER = os.path.join(CLAUDE, "scripts", "build_skill_index.py")

# never demote: this is the machinery, not content
PROTECTED = {"graphify", "skill-acquire", "deep-scrape", "recall",
             "skill-library", "task-observer", "human-text", "writing-style"}
# Thresholds are env-overridable so the destructive path can be exercised in a
# test without waiting 40 real prompts. Defaults are the safe values.
MIN_COST = int(os.environ.get("OPT_MIN_COST", "25"))
MIN_SAMPLE = int(os.environ.get("OPT_MIN_SAMPLE", "40"))
MIN_AGE_DAYS = int(os.environ.get("OPT_MIN_AGE_DAYS", "14"))
PROMOTE_AT = int(os.environ.get("OPT_PROMOTE_AT", "4"))
GAP_AT = 3             # repeated misses that justify proposing a new skill

STOP = set("""the a an and or of to in for on with is are was be do does did this that
it my our your i we you can could should would please make sure want need help""".split())


def _desc(path):
    try:
        head = open(path, encoding="utf-8", errors="replace").read(4000)
    except Exception:
        return ""
    m = re.search(r"^description:\s*(.*?)(?=\n[a-z_]+:|\n---)", head, re.S | re.M)
    return " ".join(m.group(1).split()) if m else ""


def _pinned_names():
    try:
        return {a["name"] for a in json.load(open(PINNED, encoding="utf-8"))["always"]}
    except Exception:
        return set()


def _usage(days):
    cutoff = time.time() - days * 86400
    hits = collections.Counter()
    misses = []
    total = 0
    try:
        with open(USAGE, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("t", 0) < cutoff:
                    continue
                total += 1
                names = r.get("hits") or []
                for n in names:
                    hits[n.lower()] += 1
                if not names:
                    misses.append(r.get("prompt", ""))
    except FileNotFoundError:
        pass
    return hits, misses, total


def _gaps(misses):
    counter = collections.Counter()
    for m in misses:
        words = [w for w in re.findall(r"[a-z]{4,}", (m or "").lower()) if w not in STOP]
        for w in set(words):
            counter[w] += 1
    return [(w, c) for w, c in counter.most_common(8) if c >= GAP_AT]



def _no_window():
    """A console child spawned from a windowless parent creates its own console.
    The tuner launches hundreds of these during a sweep, so each one must be told
    explicitly to stay hidden."""
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            "startupinfo": si}


def optimize(days=14, apply_it=False):
    hits, misses, total = _usage(days)
    if total == 0:
        print("  no routing recorded in the last %d days." % days)
        print("  The router appends to ~/.claude/hooks/skill_usage.jsonl on every")
        print("  prompt; after real use this will have data to act on.")
        return 0

    pinned = _pinned_names()
    print("  %d routed prompts in the last %d days" % (total, days))
    print("")

    # Absence of evidence is not evidence of absence. A skill that simply had no
    # matching prompt yet must not be demoted for it, and a skill younger than the
    # window never had a fair chance to be routed.
    enough = total >= MIN_SAMPLE
    demote = []
    now = time.time()
    for f in glob.glob(os.path.join(SKILLS, "*", "SKILL.md")):
        name = os.path.basename(os.path.dirname(f))
        if name in PROTECTED or name in pinned:
            continue
        try:
            age_days = (now - os.path.getmtime(f)) / 86400
        except OSError:
            age_days = 0
        if age_days < MIN_AGE_DAYS:
            continue
        cost = int(len(_desc(f)) / 4)
        if hits.get(name.lower(), 0) == 0 and cost >= MIN_COST:
            demote.append((cost, name))
    demote.sort(reverse=True)
    if not enough:
        held = demote
        demote = []

    promote = []
    try:
        idx = json.load(open(INDEX, encoding="utf-8"))["skills"]
    except Exception:
        idx = []
    for e in idx:
        if e.get("origin") != "library":
            continue
        used = hits.get(e["name"].lower(), 0)
        # Promotion needs evidence too. Four routes out of five total prompts is
        # not a pattern, and promoting costs context in every future session.
        if used >= PROMOTE_AT and enough:
            promote.append((used, e["name"], e.get("path", "")))
    promote.sort(reverse=True)

    if not enough:
        print("  DEMOTE: withheld - only %d routed prompts, need %d for a verdict."
              % (total, MIN_SAMPLE))
        if held:
            print("     (%d candidate(s) are being watched, none acted on)" % len(held))
        print("     Too small a sample would demote a skill that simply had no")
        print("     matching prompt yet. Come back after more real use.")
    elif demote:
        print("  DEMOTE (loaded, zero routes in %d days) - saves ~%d tokens/session:"
              % (days, sum(c for c, _ in demote)))
        for cost, name in demote:
            print("     %4d  %s" % (cost, name))
    else:
        print("  DEMOTE: nothing - every loaded skill earned its place this window")

    if promote:
        print("")
        print("  PROMOTE (routed %d+ times from the library):" % PROMOTE_AT)
        for used, name, _ in promote:
            print("     %4dx  %s" % (used, name))
    else:
        print("")
        if not enough:
            print("  PROMOTE: withheld - %d routed prompts, need %d" % (total, MIN_SAMPLE))
        else:
            print("  PROMOTE: nothing - no library skill is being pulled often enough")

    gaps = _gaps(misses)
    if gaps:
        print("")
        print("  GAP (%d prompts matched nothing; recurring topics):" % len(misses))
        for w, c in gaps:
            print("     %3dx  %s" % (c, w))
        print("     -> a real gap becomes a skill: /skill-creator, or first check")
        print("        acquire.py gap \"<capability>\" for one that already exists")
    elif misses:
        print("")
        print("  GAP: %d unmatched prompt(s), no recurring topic yet" % len(misses))

    if not apply_it:
        if demote or promote:
            print("")
            print("  Nothing moved. Re-run with --apply to act on this.")
        return 0

    moved = 0
    os.makedirs(DEMOTED, exist_ok=True)
    for cost, name in demote:
        src, dst = os.path.join(SKILLS, name), os.path.join(DEMOTED, name)
        if os.path.isdir(src) and not os.path.exists(dst):
            try:
                shutil.move(src, dst)
                print("  demoted %s -> skills-library/demoted/  (still routable)" % name)
                moved += 1
            except Exception as exc:
                print("  could not demote %s: %r" % (name, exc))
    for used, name, path in promote:
        src = os.path.dirname(os.path.join(HOME, path)) if path else ""
        dst = os.path.join(SKILLS, name)
        if src and os.path.isdir(src) and not os.path.exists(dst):
            try:
                shutil.move(src, dst)
                print("  promoted %s -> skills/  (loaded every session)" % name)
                moved += 1
            except Exception as exc:
                print("  could not promote %s: %r" % (name, exc))

    if moved:
        subprocess.run([sys.executable, BUILDER], capture_output=True, text=True, **_no_window())
        print("")
        print("  %d skill(s) moved, index rebuilt. Nothing was deleted - every" % moved)
        print("  move is reversible with a directory rename or git checkout.")
    else:
        print("")
        print("  nothing to move")
    return 0
