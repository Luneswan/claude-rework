#!/usr/bin/env python3
"""recall_ledger - the layers rival memory skills had that a budgeted search lacks.

Imported by recall.py:
  show(needle)      full detail for ONE hit            (mem-search layer 3: fetch)
  digest(weeks)     per-ISO-week rollup                (claude-mem weekly-digests)
  decisions(days)   ledger from notes + transcripts (recursive-decision-ledger)
  handoff(project)  what must survive a compact           (strategic-compact)

Read-only.
"""
from __future__ import annotations
import datetime
import glob
import json
import os
import re
import sys

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
PROJECTS = os.path.join(CLAUDE, "projects")
SKILLS = os.path.join(CLAUDE, "skills")

DECISION_MARKERS = [
    "we decided", "decision:", "let's use", "lets use", "instead of", "from now on",
    "always ", "never ", "do not ", "dont ", "must ", "the plan is", "going with",
    "switch to", "stop using", "i want", "make sure",
]


def _norm(t):
    return " ".join((t or "").split())


def _corpus(days=3650, role=None, project=None):
    """The extracted corpus. Scanning raw transcripts for these views cost 10-17s
    each; the corpus answers the same questions in well under a second."""
    try:
        from recall_index import corpus_messages
        return corpus_messages(days=days, role=role, project=project)
    except Exception:
        return []


def _user_messages(path, min_len=20):
    """Retained for callers that still hold a transcript path."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"user"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("type") != "user":
                    continue
                m = (ev.get("message") or {}).get("content")
                if isinstance(m, list):
                    m = " ".join(c.get("text", "") for c in m
                                 if isinstance(c, dict) and c.get("type") == "text")
                if not isinstance(m, str) or len(m) < min_len:
                    continue
                if m.lstrip().startswith(("<", "[Image", "Caveat:")):
                    continue
                out.append(_norm(m))
    except Exception:
        pass
    return out


def show(needle):
    """Layer 3 of search/timeline/fetch: full detail for ONE hit, only after the
    budgeted search said which one is worth the tokens."""
    cands = glob.glob(os.path.join(PROJECTS, "*", "memory", "*.md"))
    cands += glob.glob(os.path.join(SKILLS, "*", "SKILL.md"))
    low = needle.lower()
    hits = [f for f in cands if low in f.lower()]
    if not hits:
        for f in cands:
            try:
                if low in open(f, encoding="utf-8", errors="replace").read(4000).lower():
                    hits.append(f)
            except Exception:
                pass
    if not hits:
        print("  no note or skill matching " + repr(needle))
        return 1
    if len(hits) > 1:
        print("  " + str(len(hits)) + " matches; showing the first. Others:")
        for f in hits[1:6]:
            print("    " + os.path.relpath(f, CLAUDE))
    f = hits[0]
    print("  == " + os.path.relpath(f, CLAUDE) + " ==")
    try:
        print(open(f, encoding="utf-8", errors="replace").read())
    except Exception as exc:
        print("  unreadable: " + repr(exc))
        return 1
    return 0


def digest(weeks=4, project=None):
    """Per-ISO-week rollup: what each week was actually about."""
    rows = _corpus(days=weeks * 7, project=project)
    per_week = {}
    for r in rows:
        iso = datetime.datetime.fromtimestamp(r.get("t", 0)).isocalendar()
        key = str(iso[0]) + "-W" + str(iso[1]).zfill(2)
        w = per_week.setdefault(key, {"msgs": 0, "projects": {}, "samples": []})
        w["msgs"] += 1
        proj = r.get("p", "")
        w["projects"][proj] = w["projects"].get(proj, 0) + 1
        if r.get("r", "u") == "u":
            w["samples"].append((r.get("t", 0), proj, r.get("m", "")[:110]))
    for key in sorted(per_week, reverse=True):
        w = per_week[key]
        print("")
        print("  " + key + "   " + str(w["msgs"]) + " messages across "
              + str(len(w["projects"])) + " project(s)")
        for proj, c in sorted(w["projects"].items(), key=lambda kv: -kv[1])[:4]:
            print("     " + str(c).rjust(5) + "  " + proj[:44])
        for _, proj, first in sorted(w["samples"], reverse=True)[:3]:
            print("        - " + first[:100])
    if not per_week:
        print("  nothing in that window")
    return 0


def decisions(days=30, limit=25, quiet=False):
    """A decision ledger from notes, what was asked, and what was concluded."""
    out = []
    for f in glob.glob(os.path.join(PROJECTS, "*", "memory", "*.md")):
        if os.path.basename(f).upper() == "MEMORY.MD":
            continue
        try:
            body = open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for line in body.splitlines():
            low = line.lower()
            if any(m in low for m in DECISION_MARKERS) and len(line.strip()) > 25:
                out.append(("note", os.path.basename(f)[:28], _norm(line)[:200]))

    for r in _corpus(days=days):
        tag = "said" if r.get("r", "u") == "u" else "concluded"
        for part in r.get("m", "").split(". "):
            pl = part.lower()
            if any(m in pl for m in DECISION_MARKERS) and len(part) > 25:
                out.append((tag, r.get("p", "")[:28], _norm(part)[:200]))

    seen, uniq = set(), []
    for kind, where, text in out:
        k = text[:70].lower()
        if k not in seen:
            seen.add(k)
            uniq.append((kind, where, text))
    for kind, where, text in uniq[:limit]:
        print("  [" + kind + "] " + where)
        print("       " + text)
    if not uniq and not quiet:
        print("  no decisions matched")
    return 0


def handoff(project=None, days=3):
    """What must survive a compact or a fresh session. Paste into the new one."""
    print("  HANDOFF")
    print("")
    print("  Recent decisions:")
    decisions(days=days, limit=6, quiet=True)
    rows = _corpus(days=days, role="u", project=project)
    rows.sort(key=lambda r: r.get("t", 0))
    print("")
    print("  Most recent asks:")
    if rows:
        for r in rows[-3:]:
            print("     - " + r.get("m", "")[:160])
    else:
        print("     (no recent user messages found)")
    concl = _corpus(days=days, role="a", project=project)
    if concl:
        concl.sort(key=lambda r: r.get("t", 0))
        print("")
        print("  Most recent conclusions:")
        for r in concl[-3:]:
            print("     - " + r.get("m", "")[:160])
    print("")
    print("  Anything above that must not be lost, write it down:")
    print("     recall.py --write <fact> --name <slug> --type project")
    return 0

DONE_SIGNALS = ("done", "fixed", "committed", "works", "verified", "passing",
                "shipped", "resolved", "installed", "built", "landed", "merged")
OPEN_SIGNALS = ("still open", "still need", "not yet", "remaining", "left to",
                "todo", "unproven", "deferred", "next step", "not done",
                "have not", "haven't", "outstanding")


def _first_chunks(rows):
    """The corpus stores chunks; a brief is about MESSAGES. Keep the first chunk
    of each message - without this the same request appeared eight times because
    a long message became eight chunks."""
    seen, out = set(), []
    for r in rows:
        # (file, time) is not enough: a resumed session re-records the same
        # message in a new transcript, so dedupe on the text itself as well
        key = re.sub(r"[^a-z0-9]+", "", (r.get("m") or "").lower())[:90]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# A chunk that begins mid-sentence is a fragment, and skill bodies injected on the
# user channel are documentation, not requests.
_FRAGMENT = re.compile(r"^[a-z]{1,3}[.)]\s|^[a-z]+ing|^\*\*|^\d+\.\s\*\*")
_NOT_REQUEST = ("skill should be used", "use this skill", "---", "name:",
                "description:", "trigger:", "## ", "```")


def _looks_like_request(text):
    t = text.strip()
    if _FRAGMENT.match(t):
        return False
    head = t[:160].lower()
    return not any(k in head for k in _NOT_REQUEST)


def _semantic_done(asks, concl):
    """Match each request to the most similar later conclusion using the same
    vectors recall already has. Word-echo called 334 of 407 requests done because
    any shared vocabulary counted; similarity asks the real question - does a
    later answer actually correspond to this request?"""
    try:
        import numpy as np
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from recall_embed import _fast_encode
    except Exception:
        return None
    if not concl:
        return None
    try:
        cv = [_fast_encode(c.get("m", "")) for c in concl]
        keep = [(c, v) for c, v in zip(concl, cv) if v is not None]
        if not keep:
            return None
        M = np.vstack([v for _, v in keep])
        times = np.array([c.get("t", 0) for c, _ in keep])
        out = []
        for a in asks:
            q = _fast_encode(a.get("m", ""))
            if q is None:
                out.append((a, 0.0, ""))
                continue
            sims = M @ q
            # only conclusions at or after the request can answer it
            sims = np.where(times >= a.get("t", 0) - 60, sims, -1.0)
            j = int(np.argmax(sims))
            out.append((a, float(sims[j]), keep[j][0].get("m", "")))
        return out
    except Exception:
        return None


def brief(days=2, project=None, limit=14, threshold=0.45):
    """What was asked, what got done, what is still open - without re-reading the
    chat. Semantic where vectors exist, word-echo only as a fallback."""
    asks = _first_chunks(_corpus(days=days, role="u", project=project))
    concl = _corpus(days=days, role="a", project=project)
    asks.sort(key=lambda r: r.get("t", 0))
    concl.sort(key=lambda r: r.get("t", 0))
    asks = [a for a in asks if len(a.get("m", "")) >= 20 and _looks_like_request(a["m"])]

    if not asks:
        print("  nothing in the last " + str(days) + " day(s)")
        return 0

    scored = _semantic_done(asks, concl)
    mode = "semantic"
    done, open_ = [], []
    if scored:
        for a, sim, answer in scored:
            low = answer.lower()
            says_done = any(d in low for d in DONE_SIGNALS)
            says_open = any(o in low for o in OPEN_SIGNALS)
            if sim >= threshold and says_done and not says_open:
                done.append((sim, _norm(a["m"])[:150]))
            else:
                open_.append((sim, _norm(a["m"])[:150]))
    else:
        mode = "word-overlap (no vectors)"
        blob = " ".join(c.get("m", "").lower() for c in concl)
        for a in asks:
            words = [w for w in _norm(a["m"]).lower().split() if len(w) > 5][:6]
            echoed = sum(1 for w in words if w in blob)
            looks_done = echoed >= 2 and any(d in blob for d in DONE_SIGNALS)
            (done if looks_done else open_).append((0.0, _norm(a["m"])[:150]))

    print("  BRIEF - last %d day(s), %d request(s), matched %s"
          % (days, len(asks), mode))
    print("")
    print("  LIKELY DONE (%d):" % len(done))
    for sim, m in done[-limit:]:
        print("     + [%.2f] %s" % (sim, m) if sim else "     + " + m)
    if not done:
        print("     (none matched a completion signal)")
    print("")
    print("  STILL OPEN OR UNCONFIRMED (%d):" % len(open_))
    for sim, m in open_[-limit:]:
        print("     - [%.2f] %s" % (sim, m) if sim else "     - " + m)
    if not open_:
        print("     (nothing outstanding matched)")

    flagged = [_norm(r.get("m", ""))[:150]
               for r in _first_chunks(concl[-120:])
               if any(k in r.get("m", "").lower() for k in OPEN_SIGNALS)
               and _looks_like_request(r.get("m", ""))]
    if flagged:
        print("")
        print("  I FLAGGED AS UNFINISHED:")
        for m in flagged[-6:]:
            print("     ! " + m)
    print("")
    print("  Scores are cosine similarity between the request and the closest later")
    print("  answer. Below %.2f, or no completion wording, counts as open." % threshold)
    return 0
