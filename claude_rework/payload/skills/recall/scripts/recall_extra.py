#!/usr/bin/env python3
"""recall_extra - the capabilities the superseded skills each had alone.

Imported by recall.py:
  budget_report()  what every session costs before you type      (context-budget)
  estimate(text)   input tokens + expected response size    (token-budget-advisor)
  timeline(days)   what happened, by day                        (timeline-report)
  gc_notes()       stale and duplicate curated notes                 (curation)

Read-only: nothing here deletes or rewrites a note.
"""
from __future__ import annotations
import datetime
import glob
import json
import os
import re

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


def _desc_of(path):
    try:
        head = open(path, encoding="utf-8", errors="replace").read(4000)
    except Exception:
        return ""
    m = re.search(r"^description:\s*(.*?)(?=\n[a-z_]+:|\n---)", head, re.S | re.M)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def budget_report():
    """Inventory of context spent before a single word is typed."""
    total = 0
    print("  PER-SESSION CONTEXT COST (estimated tokens)")

    active = []
    for f in glob.glob(os.path.join(SKILLS, "*", "SKILL.md")):
        d = _desc_of(f)
        if d:
            active.append((len(d), os.path.basename(os.path.dirname(f))))
    t = int(sum(n for n, _ in active) / 4)
    total += t
    print(f"  {t:6d}  auto-loaded skill descriptions ({len(active)} skills)")
    for n, name in sorted(active, reverse=True)[:6]:
        print(f"          {int(n / 4):4d}  {name}")

    # Agents and MCP tools are usually the largest fixed costs and the easiest to
    # miss: they are not skills, so a skills-only report understates the total by
    # an order of magnitude. Measured against a real context breakdown, agents
    # were 10.1k and MCP 8.4k while skill descriptions were under 3k.
    agents = {}
    for f in glob.glob(os.path.join(CLAUDE, "plugins", "cache", "**", "agents", "*.md"),
                       recursive=True):
        name = os.path.basename(f)
        if name not in agents:
            agents[name] = _desc_of(f) or ""
    if agents:
        t = int(sum(len(d) for d in agents.values()) / 4)
        total += t
        pack_count = {}
        for f in glob.glob(os.path.join(CLAUDE, "plugins", "cache", "**", "agents", "*.md"),
                           recursive=True):
            pack = f.split(os.sep)[f.split(os.sep).index("cache") + 1]
            pack_count[pack] = pack_count.get(pack, 0) + 1
        print(f"  {t:6d}  custom agent descriptions ({len(agents)} unique)")
        for pack, n in sorted(pack_count.items(), key=lambda kv: -kv[1])[:4]:
            print(f"          {n:4d}  from {pack}")

    mcp = set()
    for f in glob.glob(os.path.join(CLAUDE, "plugins", "cache", "**", ".mcp.json"),
                       recursive=True):
        try:
            for k in (json.load(open(f, encoding="utf-8")).get("mcpServers") or {}):
                mcp.add(k)
        except Exception:
            pass
    try:
        cfg = json.load(open(os.path.join(os.path.dirname(CLAUDE), ".claude.json"),
                             encoding="utf-8"))
        for k in (cfg.get("mcpServers") or {}):
            mcp.add(k)
    except Exception:
        pass
    if mcp:
        print(f"  {'':6s}  {len(mcp)} MCP server(s) configured: {', '.join(sorted(mcp))}")
        print(f"  {'':6s}  each connected server publishes its tool schemas into every")
        print(f"  {'':6s}  session - disconnect what you do not use, it is often the")
        print(f"  {'':6s}  single largest line in the context breakdown")

    path = os.path.join(CLAUDE, "CLAUDE.md")
    if os.path.exists(path):
        t = int(os.path.getsize(path) / 4)
        total += t
        print(f"  {t:6d}  CLAUDE.md (user-level)")

    try:
        pins = json.load(open(os.path.join(CLAUDE, "always_skills.json"),
                              encoding="utf-8"))["always"]
        block = sum(len(a.get("name", "")) + len(a.get("when", "")) +
                    len(a.get("run", "")) + 12 for a in pins)
        t = int(block / 4)
        total += t
        print(f"  {t:6d}  router ALWAYS block, on every prompt ({len(pins)} pins)")
    except Exception:
        pass

    try:
        settings = json.load(open(os.path.join(CLAUDE, "settings.json"), encoding="utf-8"))
        nh = sum(len(g.get("hooks", [])) for v in settings.get("hooks", {}).values() for g in v)
        print(f"  {'':6s}  {nh} hooks registered (per-turn output varies)")
    except Exception:
        pass

    print("  " + "-" * 6)
    print(f"  {total:6d}  estimated fixed cost per session")
    print()
    print("  Biggest lever: trim the longest descriptions above, or move a skill")
    print("  from skills/ to skills-library/ - library skills cost nothing until routed.")
    return 0


def estimate(text):
    words = len(text.split())
    prose = int(words * 1.3)
    code = int(len(text) / 4)
    dense = (sum(c in "{}();=<>[]" for c in text) / max(len(text), 1)) > 0.02
    pick = code if dense else prose
    print(f"  {len(text)} chars, {words} words")
    print(f"  prose heuristic (words x 1.3) : {prose}")
    print(f"  code heuristic  (chars / 4)   : {code}")
    print(f"  -> {'code' if dense else 'prose'} content: ~{pick} input tokens")
    print(f"  expected response: simple {pick * 3}-{pick * 8}, "
          f"moderate {pick * 8}-{pick * 20}, code-with-context {pick * 10}-{pick * 25}")
    return 0


def _count_user_messages(path):
    n, first = 0, ""
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
                msg = (ev.get("message") or {}).get("content")
                if isinstance(msg, list):
                    msg = " ".join(c.get("text", "") for c in msg
                                   if isinstance(c, dict) and c.get("type") == "text")
                if not isinstance(msg, str) or len(msg) < 15:
                    continue
                if msg.lstrip().startswith(("<", "[Image", "Caveat:")):
                    continue
                n += 1
                if not first:
                    first = re.sub(r"\s+", " ", msg)[:110]
    except Exception:
        pass
    return n, first


def timeline(days, project=None):
    """What actually happened, by day - from the corpus, not raw transcripts."""
    try:
        from recall_index import corpus_messages
        rows = corpus_messages(days=days, project=project)
    except Exception:
        rows = []
    per_day = {}
    for r in rows:
        day = datetime.datetime.fromtimestamp(r.get("t", 0)).strftime("%Y-%m-%d")
        d = per_day.setdefault(day, {})
        proj = r.get("p", "")
        entry = d.setdefault(proj, [0, ""])
        entry[0] += 1
        if not entry[1] and r.get("r", "u") == "u":
            entry[1] = r.get("m", "")[:110]
    for day in sorted(per_day, reverse=True):
        print("")
        print("  " + day)
        for proj, pair in sorted(per_day[day].items(), key=lambda kv: -kv[1][0])[:6]:
            print("    %4d msgs  %-36s %s" % (pair[0], proj[:36], pair[1]))
    if not per_day:
        print("  nothing in that window")
    return 0


def gc_notes():
    """Curation: notes that duplicate each other, or have gone cold."""
    notes = [f for f in glob.glob(os.path.join(PROJECTS, "*", "memory", "*.md"))
             if os.path.basename(f).upper() != "MEMORY.MD"]
    now = datetime.datetime.now().timestamp()
    stale, dupes, seen = [], [], {}
    for f in notes:
        try:
            body = open(f, encoding="utf-8", errors="replace").read()
            age = (now - os.path.getmtime(f)) / 86400
        except Exception:
            continue
        key = re.sub(r"[^a-z0-9]+", "", body.lower())[:400]
        if key in seen:
            dupes.append((f, seen[key]))
        else:
            seen[key] = f
        if age > 120:
            stale.append((int(age), f))
    print(f"  {len(notes)} curated notes")
    if dupes:
        print(f"  {len(dupes)} near-duplicate(s):")
        for a, b in dupes[:8]:
            print(f"    {os.path.basename(a)}  ==  {os.path.basename(b)}")
    if stale:
        print(f"  {len(stale)} untouched for 120+ days:")
        for age, f in sorted(stale, reverse=True)[:8]:
            print(f"    {age:4d}d  {os.path.relpath(f, PROJECTS)}")
    if not dupes and not stale:
        print("  clean - nothing stale or duplicated")
    print()
    print("  Nothing was deleted. Review before removing: a note is cheap to keep")
    print("  and expensive to lose.")
    return 0
