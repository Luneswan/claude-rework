#!/usr/bin/env python3
"""recall - one query across every memory store this machine has.

  recall.py "<question>" [--budget 2000] [--project PATH] [--days 45]
  recall.py --write "<fact>" --name <slug> --type project|user|feedback|reference
  recall.py --stores                 what exists, how big

Stores searched, most valuable per token first:
  1. curated notes   ~/.claude/projects/<slug>/memory/*.md   hand-written facts
  2. procedural      ~/.claude/skills/*/SKILL.md             distilled technique
  3. code graph      <project>/graphify-out/graph.json       structure, via graphify
  4. transcripts     ~/.claude/projects/*/*.jsonl            what was actually said

Output is capped by --budget characters, spent in that order, so recall never
costs more context than the answer is worth.
"""
from __future__ import annotations
import argparse
import datetime
import glob
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
PROJECTS = os.path.join(CLAUDE, "projects")
SKILLS = os.path.join(CLAUDE, "skills")
STOP = set("""a an the and or of to in for on with is are was were be been do does did
what when where how why who which that this these those i we you it my our your their
about from into over under again more most some any all can could should would will
get got give gave make made made much many little few very really just still even
thing things stuff way ways use used using need needs want wants like also then than
happen happened happening said say says tell told ask asked new old good bad better""".split())


MAX_TERMS = 12

# A question has a SHAPE, and the shape says what an answer looks like. "why did X
# fail" is answered by causal language, not by the hundred chunks that merely
# mention X. Without this, a busy topic drowns its own explanation: the corpus
# gained hundreds of chunks about the skill router today, and the one chunk saying
# "bash ate the backslashes" was outranked by newer chatter on the same subject.
INTENT = {
    "cause": (("why", "cause", "reason", "fail", "failed", "broke", "broken",
               "not work", "didn't work", "wrong with"),
              ("because", "root cause", "the reason", "turns out", "caused by",
               "it was", "the bug", "the fix", "due to", "so it", "which is why")),
    "quantity": (("how much", "how many", "how fast", "how long", "cost", "size",
                  "speed", "faster", "slower"),
                 ("%", "tokens", "seconds", " ms", " mb", " gb", "x fewer",
                  "x faster", "->", "from", "to")),
    "decision": (("decide", "decided", "agree", "agreed", "chose", "chosen",
                  "settle", "conclusion", "concluded"),
                 ("decided", "we will", "going with", "instead of", "rather than",
                  "chose", "the plan", "agreed")),
}
INTENT_BOOST = 1.6


def intent_of(question):
    q = (question or "").lower()
    for name, (triggers, _markers) in INTENT.items():
        if any(t in q for t in triggers):
            return name
    return ""


def intent_bonus(text, kind):
    """How much this chunk looks like an ANSWER of the requested shape."""
    if not kind:
        return 1.0
    markers = INTENT[kind][1]
    low = text.lower()
    hits = sum(1 for m in markers if m in low)
    if not hits:
        return 1.0
    return 1.0 + min(hits, 3) * (INTENT_BOOST - 1.0) / 3.0


def terms(q):
    """Distinct, informative words - capped. A pasted 5,000-character question
    otherwise produces hundreds of terms and every one of them is scanned against
    every candidate line, turning a 0.3s query into 19s for no extra recall."""
    seen, out = set(), []
    for w in re.findall(r"[a-z0-9][a-z0-9_+-]{2,}", q.lower()):
        if w in STOP or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= MAX_TERMS:
            break
    return out


def slug_for(path):
    p = os.path.abspath(path).replace(":", "-").replace(os.sep, "-").replace("/", "-")
    return p.lstrip("-")


def score_text(text, tset):
    """Length-normalised. Raw counts let a long document win by being long: a
    6,000-character note matching two filler words scored 23 while the 600-char
    chunk holding the actual answer scored 13. Density, and distinct-term breadth,
    are what make scores comparable across stores of different sizes."""
    low = text.lower()
    raw = sum(min(low.count(t), 4) for t in tset)
    if not raw:
        return 0
    distinct = sum(1 for t in tset if t in low)
    density = raw / max(1.0, (len(low) / 600.0) ** 0.5)
    return round(density * (1 + 0.5 * (distinct - 1)), 1)


def search_notes(tset, limit=6):
    out = []
    for f in glob.glob(os.path.join(PROJECTS, "*", "memory", "*.md")):
        if os.path.basename(f).upper() == "MEMORY.MD":
            continue
        try:
            body = open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        s = score_text(body, tset)
        if s:
            proj = f.split(os.sep)[-3]
            out.append((s, "note", proj, os.path.basename(f), body.strip()))
    out.sort(key=lambda r: -r[0])
    return out[:limit]


def search_skills(tset, limit=5):
    out = []
    for f in glob.glob(os.path.join(SKILLS, "*", "SKILL.md")):
        try:
            body = open(f, encoding="utf-8", errors="replace").read(20000)
        except Exception:
            continue
        s = score_text(body, tset)
        if s:
            name = os.path.basename(os.path.dirname(f))
            head = re.sub(r"^---.*?---", "", body, flags=re.S).strip()
            out.append((s, "skill", name, f, head[:600]))
    out.sort(key=lambda r: -r[0])
    return out[:limit]


def search_graph(project, question):
    graph = os.path.join(project or ".", "graphify-out", "graph.json")
    if not os.path.exists(graph):
        return []
    import subprocess
    try:
        r = subprocess.run(["graphify", "query", question, "--budget", "600"],
                           cwd=project, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=90)
        if r.returncode == 0 and (r.stdout or "").strip():
            return [(99, "graph", os.path.basename(os.path.abspath(project)),
                     "graphify query", r.stdout.strip()[:1200])]
    except Exception:
        pass
    return []


def search_transcripts(tset, days, limit=6, question="", project=None):
    """Search the extracted corpus, not 7 GB of raw transcripts. Falls back to a
    hard-capped live scan only while the corpus is still being built.

    `project` is a project NAME, not a path, and is normally None: history is
    searched across every project because that is where the answer usually is.
    --this-project narrows it when a word means different things in two repos.
    """
    try:
        from recall_index import search_corpus, CORPUS
        if os.path.exists(CORPUS):
            sem = {}
            if question:
                try:
                    from recall_embed import semantic_scores
                    sem = semantic_scores(question)
                except Exception:
                    sem = {}
            return search_corpus(tset, days, limit, sem=sem, project=project)
    except Exception as exc:
        print("  (corpus unavailable: %r - falling back to a capped live scan)" % exc,
              file=sys.stderr)
    # fallback: newest few files only, so a missing corpus degrades speed, not use
    hits = []
    cutoff = datetime.datetime.now().timestamp() - days * 86400
    files = sorted(glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")),
                   key=lambda f: -os.path.getmtime(f))
    budget_bytes = 200 * 1024 * 1024
    for f in files[:12]:
        try:
            size = os.path.getsize(f)
            if os.path.getmtime(f) < cutoff or size > budget_bytes:
                continue
        except OSError:
            continue
        budget_bytes -= size
        proj = os.path.basename(os.path.dirname(f))
        when = datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d")
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    low = line.lower()
                    if not any(t in low for t in tset):
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
                    if not isinstance(msg, str) or len(msg) < 12:
                        continue
                    if msg.lstrip().startswith(("<", "[Image", "Caveat:")):
                        continue
                    sc = score_text(msg, tset)
                    if sc:
                        hits.append((sc, "said", proj + " " + when, "transcript",
                                     re.sub(r"\s+", " ", msg)[:400]))
        except Exception:
            continue
        if budget_bytes <= 0:
            break
    hits.sort(key=lambda r: -r[0])
    seen, uniq = set(), []
    for h in hits:
        k = h[4][:80].lower()
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return uniq[:limit]


def write_note(fact, name, kind, project):
    slug = slug_for(project or os.getcwd())
    mem = os.path.join(PROJECTS, slug, "memory")
    os.makedirs(mem, exist_ok=True)
    path = os.path.join(mem, name + ".md")
    first = fact.strip().splitlines()[0][:100]
    body = ("---\nname: " + name + "\ndescription: " + first +
            "\nmetadata:\n  type: " + kind + "\n---\n\n" + fact.strip() +
            "\n\n_Recorded " + datetime.date.today().isoformat() + "._\n")
    open(path, "w", encoding="utf-8", newline="\n").write(body)
    index = os.path.join(mem, "MEMORY.md")
    prev = open(index, encoding="utf-8").read() if os.path.exists(index) else ""
    if "(" + name + ".md)" not in prev:
        with open(index, "a", encoding="utf-8", newline="\n") as fh:
            fh.write("- [" + name + "](" + name + ".md) - " + first + "\n")
    print("wrote " + path)
    return 0


def show_stores():
    rows = [
        ("curated notes", len(glob.glob(os.path.join(PROJECTS, "*", "memory", "*.md"))),
         os.path.join(PROJECTS, "<project>", "memory")),
        ("procedural skills", len(glob.glob(os.path.join(SKILLS, "*", "SKILL.md"))), SKILLS),
        ("transcripts", len(glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))), PROJECTS),
        ("code graphs", len(glob.glob(os.path.join(PROJECTS, "*", "graphify-out", "graph.json"))),
         "<project>/graphify-out"),
    ]
    for name, n, where in rows:
        print(f"  {n:5d}  {name:22s} {where}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question", nargs="?")
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--project", default=os.getcwd())
    # Transcript search spans every project by default, because the decision you
    # are looking for is often in the repo you were in last week. These make that
    # explicit and give you the narrow case when a word means two things.
    ap.add_argument("--all-projects", action="store_true",
                    help="search every project and ignore this directory's code "
                         "graph (transcripts are already global by default)")
    ap.add_argument("--this-project", action="store_true",
                    help="restrict history to the current project only")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--stores", action="store_true")
    ap.add_argument("--budget-report", action="store_true",
                    help="what every session costs before you type")
    ap.add_argument("--estimate", help="token estimate for a string, or @file")
    ap.add_argument("--timeline", action="store_true", help="what happened, by day")
    ap.add_argument("--gc", action="store_true", help="stale and duplicate notes")
    ap.add_argument("--show", help="full detail for one note or skill")
    ap.add_argument("--digest", action="store_true", help="per-ISO-week rollup")
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--decisions", action="store_true", help="decision ledger")
    ap.add_argument("--handoff", action="store_true", help="what must survive a compact")
    ap.add_argument("--brief", action="store_true",
                    help="what was asked, what is done, what is left")
    ap.add_argument("--selftune", action="store_true",
                    help="retune retrieval on fresh cases from the current corpus")
    ap.add_argument("--optimize", action="store_true",
                    help="promote/demote skills from measured routing")
    ap.add_argument("--apply", action="store_true", help="with --optimize: actually move")
    ap.add_argument("--write")
    ap.add_argument("--name")
    ap.add_argument("--type", default="project",
                    choices=["user", "feedback", "project", "reference"])
    a = ap.parse_args()

    from recall_extra import budget_report, estimate, timeline, gc_notes
    from recall_ledger import show, digest, decisions, handoff, brief
    from recall_optimize import optimize
    if a.stores:
        return show_stores()
    if a.budget_report:
        return budget_report()
    if a.estimate:
        txt = a.estimate
        if txt.startswith("@") and os.path.exists(txt[1:]):
            txt = open(txt[1:], encoding="utf-8", errors="replace").read()
        return estimate(txt)
    if a.timeline:
        return timeline(a.days)
    if a.gc:
        return gc_notes()
    if a.show:
        return show(a.show)
    if a.digest:
        return digest(a.weeks)
    if a.decisions:
        return decisions(a.days)
    if a.handoff:
        return handoff()
    if a.brief:
        return brief(days=a.days)
    if a.selftune:
        from recall_tune import run as _tune
        return _tune()
    if a.optimize:
        return optimize(days=a.days, apply_it=a.apply)
    if a.write:
        if not a.name:
            print("--write needs --name <slug>")
            return 1
        return write_note(a.write, a.name, a.type, a.project)
    if not a.question:
        print(__doc__)
        return 1

    tset = terms(a.question)
    if not tset:
        print("query too generic")
        return 1

    # Query expansion was tried here and measured worse (4/5 -> 2/5 correct):
    # feedback terms from the top hits diluted the query and let common words
    # outvote the rare one that mattered. Kept out deliberately.

    # Rank ACROSS stores, not strictly by store. Spending the budget on curated
    # notes first sounds principled and measured badly: a weakly-matching note
    # from an unrelated project displaced the transcript line that actually held
    # the answer (2/5 correct vs grep's 5/5). Store priority becomes a weight, not
    # an ordering, so a strong hit anywhere wins its slot.
    WEIGHT = {"CURATED NOTES": 1.6, "PROCEDURAL (skills)": 1.15,
              "CODE GRAPH": 1.3, "WHAT YOU SAID": 1.0}
    kind = intent_of(a.question)
    only = (os.path.basename(os.path.normpath(a.project))
            if getattr(a, "this_project", False) else None)
    graph_rows = ([] if getattr(a, "all_projects", False)
                  else search_graph(a.project, a.question))

    def build_pool(days):
        out = []
        for label, rows in (("CURATED NOTES", search_notes(tset)),
                            ("PROCEDURAL (skills)", search_skills(tset)),
                            ("CODE GRAPH", graph_rows),
                            ("WHAT YOU SAID",
                             search_transcripts(
                                 tset, days,
                                 limit=int(os.environ.get("RECALL_TX_LIMIT", "12")),
                                 question=a.question, project=only))):
            for row in rows:
                out.append((row[0] * WEIGHT[label] * intent_bonus(row[4], kind),
                            label, row))
        return out

    pool = build_pool(a.days)
    # Nothing in the window is not the same as nothing at all. History imported
    # from a web export is months old by definition, and anyone returning to a
    # project after a break is outside a 45-day default too - both would be told
    # "nothing found" while the answer sat just past the cutoff. Widen once and
    # say so, rather than leaving the user to guess that --days exists.
    if not pool and a.days < 3650:
        pool = build_pool(36500)
        if pool:
            print("  (nothing in the last %d days; searched all history instead)"
                  % a.days, file=sys.stderr)
    pool.sort(key=lambda x: -x[0])

    # One long item must not eat the whole budget. Diagnosed: the chunk holding
    # the answer sat at rank 16, retrieved correctly, but four verbose items ahead
    # of it consumed all 2000 characters. Cap per item and skip near-duplicates so
    # the budget buys BREADTH of distinct evidence, not depth of the first hit.
    # Graduated allocation. A flat cap forces one trade-off for every query:
    # 150 generated known-item questions wanted DEPTH (one long, complete hit -
    # 100% at budget//2, 77% at budget//5), while hand-written questions wanted
    # BREADTH. Give the best hit room to be complete, then taper, so a strong
    # single answer is never truncated and weaker follow-ups still get a slot.
    try:
        from recall_tune import load as _load_tuning
        _tuned = _load_tuning()[0]
    except Exception:
        _tuned = {"first_div": 2, "taper": 6}
    _first = int(os.environ.get("RECALL_FIRST_DIV", _tuned["first_div"]))
    _taper = int(os.environ.get("RECALL_TAPER", _tuned["taper"]))

    def room_for(rank, remaining):
        cap = a.budget // (_first + rank * (_taper - _first) // 3) if rank < 3             else a.budget // _taper
        return max(180, min(cap, remaining))
    state = {"spent": 0, "printed": False, "rank": 0}
    shown = set()
    seen_heads = []
    printed_norm = []     # full normalised text of everything already printed
    deferred = []         # continuations of an item already printed

    def emit(label, score, kind, where, what, body):
        if label not in shown:
            print("")
            print("== " + label + " ==")
            shown.add(label)
        chunk = body.strip()
        room = room_for(state["rank"], a.budget - state["spent"])
        state["rank"] += 1
        if len(chunk) > room:
            chunk = chunk[:room].rstrip() + " ..."
        tag = " (concluded)" if kind == "concluded" else ""
        print("  [%s] %s / %s%s" % (score, where, what, tag))
        for line in chunk.splitlines()[:14]:
            print("      " + line)
        state["spent"] += len(chunk)
        state["printed"] = True

    # Distinct evidence first, continuations second. Long messages are chunked
    # with an 80-character overlap, so chunk k+1 opens with the tail of chunk k.
    # The head filter above cannot see that - each chunk starts differently - and
    # one long answer took ranks 2, 3 and 6-12 while a distinct answer at rank 5
    # never printed. A continuation is not skipped (the generated suite's gold
    # chunk is sometimes one); it is printed after everything distinct, if budget
    # remains. Breadth first, then depth.
    for entry in pool:
        if state["spent"] >= a.budget:
            break
        weighted, label, (score, kind, where, what, body) = entry
        norm = re.sub(r"[^a-z0-9]+", "", body.lower())
        head = norm[:60]
        if any(head and head == h for h in seen_heads):
            continue
        if norm[:40] and any(norm[:40] in p for p in printed_norm):
            deferred.append(entry)
            continue
        seen_heads.append(head)
        printed_norm.append(norm)
        emit(label, score, kind, where, what, body)
    for weighted, label, (score, kind, where, what, body) in deferred:
        if state["spent"] >= a.budget:
            break
        emit(label, score, kind, where, what, body)
    spent, printed = state["spent"], state["printed"]

    if not printed:
        print("nothing found in any store")
    else:
        print(f"\n({spent} chars of {a.budget} budget)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
