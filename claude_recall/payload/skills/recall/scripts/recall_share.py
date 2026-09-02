#!/usr/bin/env python3
"""recall_share - learn from other installations without shipping anyone's data.

Every machine tunes itself locally. This lets those results travel: an install
publishes a *tuning card* - parameters and benchmark scores, nothing else - and
pulls other people's cards to see which settings win on corpora unlike its own.
Better settings spread; text never does.

  recall_share.py --export            write the local card (review before sharing)
  recall_share.py --show              print the card that would be shared
  recall_share.py --pull <url|path>   fetch cards, compare, recommend
  recall_share.py --apply             adopt the recommended PARAMETERS (numbers)

In a card: parameter values, benchmark scores, corpus size, vocabulary size,
model name, a random per-install id, a date. About twenty numbers.

Never in a card: prompts, answers, file paths, project names, note contents, the
corpus, the vectors, or anything from which they could be reconstructed.

Two boundaries, deliberate rather than incidental:

  - **Publishing is a separate, explicit act.** --export writes a local file and
    stops. Nothing is uploaded by this tool, ever, on any schedule.
  - **Only numbers are adopted.** --apply writes parameters into
    recall_tuning.json. It cannot fetch or execute code: a skill that auto-runs
    code pulled from strangers is a supply-chain compromise wearing a helpful hat.
    Code updates go through git and get read by a human first.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import os
import secrets
import sys
import urllib.request


def _claude_root():
    env = os.environ.get("RECALL_HOME")
    if env and os.path.isdir(env):
        return env
    d = os.path.dirname(os.path.abspath(__file__))
    while d and os.path.basename(d) != ".claude":
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.expanduser("~/.claude")
        d = parent
    return d


CLAUDE = _claude_root()
HERE = os.path.dirname(os.path.abspath(__file__))
CARD = os.path.join(CLAUDE, "recall_card.json")
SALT = os.path.join(CLAUDE, "recall_card.salt")
TUNING = os.path.join(CLAUDE, "recall_tuning.json")
DF = os.path.join(CLAUDE, "recall_corpus.df.json")
CORPUS = os.path.join(CLAUDE, "recall_corpus.jsonl")
PULLED = os.path.join(CLAUDE, "recall_cards_pulled.json")
SCHEMA = 1


def _install_id():
    """Random and local. Not a machine name, not a user, not derivable from one -
    it exists only so several cards from one install can be de-duplicated."""
    try:
        if os.path.exists(SALT):
            salt = open(SALT, encoding="utf-8").read().strip()
        else:
            salt = secrets.token_hex(16)
            open(SALT, "w", encoding="utf-8").write(salt)
        return hashlib.sha256(salt.encode()).hexdigest()[:12]
    except Exception:
        return "anonymous"


def _params():
    try:
        d = json.load(open(TUNING, encoding="utf-8"))
        return {k: d[k] for k in ("sem_weight", "first_div", "taper") if k in d}
    except Exception:
        return {"sem_weight": 12, "first_div": 2, "taper": 6}


def _corpus_shape():
    chunks = vocab = 0
    try:
        chunks = sum(1 for _ in open(CORPUS, encoding="utf-8", errors="replace"))
    except Exception:
        pass
    try:
        vocab = len(json.load(open(DF, encoding="utf-8")).get("df", {}))
    except Exception:
        pass
    return {"chunks": chunks, "vocab": vocab}


def build_card(scores=None):
    return {"schema": SCHEMA, "machine": _install_id(), "params": _params(),
            "scores": scores or {}, "corpus": _corpus_shape(),
            "model": "potion-base-32M",
            "at": datetime.date.today().isoformat()}


def cmd_export(run_tests=True):
    scores = {}
    if run_tests:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "rt", os.path.abspath(os.path.join(HERE, "..", "tests", "run_tests.py")))
            rt = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(rt)
            k = rt.suite_known_item(40)
            c = rt.suite_curated()
            scores = {"known_item": round(k or 0, 3), "curated": round(c or 0, 3)}
        except Exception as exc:
            print("  scores unavailable (%r) - card carries parameters only" % exc)
    card = build_card(scores)
    json.dump(card, open(CARD, "w", encoding="utf-8"), indent=2)
    print("  wrote " + CARD)
    print(json.dumps(card, indent=2))
    print()
    print("  Nothing was uploaded. Review the file, then share it deliberately -")
    print("  this tool has no publish step and no schedule.")
    return 0


def cmd_show():
    print(json.dumps(build_card(), indent=2))
    return 0


def _load_source(src):
    if src.startswith("http://") or src.startswith("https://"):
        with urllib.request.urlopen(src, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    with open(src, encoding="utf-8") as fh:
        return json.load(fh)


def _sane(card):
    """A card is untrusted input. Accept only the expected shape, with values in
    ranges the code can actually use.

    Check the TYPE of every container before reaching into it. `card.get("params")
    or {}` looks defensive and is not: a list is truthy, so it survives the `or`
    and then `p.get(k)` raises AttributeError from inside the validator - which
    crashed the whole pull and discarded the legitimate cards alongside the
    hostile one. A validator that can throw is not a boundary.
    """
    if not isinstance(card, dict) or card.get("schema") != SCHEMA:
        return None
    p = card.get("params")
    if not isinstance(p, dict):
        return None
    ok = {}
    for k, lo, hi in (("sem_weight", 0, 40), ("first_div", 1, 10), ("taper", 2, 20)):
        v = p.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or not (lo <= v <= hi):
            return None
        ok[k] = v
    s = card.get("scores")
    if s is None:
        s = {}
    if not isinstance(s, dict):
        return None
    for v in s.values():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        if not (0 <= v <= 1):
            return None
    corpus = card.get("corpus")
    if not isinstance(corpus, dict):
        corpus = {}
    return {"machine": str(card.get("machine", ""))[:16], "params": ok,
            "scores": s, "corpus": corpus,
            "at": str(card.get("at", ""))[:10]}


def cmd_pull(src):
    try:
        raw = _load_source(src)
    except Exception as exc:
        print("  could not read %s: %r" % (src, exc))
        return 1
    cards = raw if isinstance(raw, list) else [raw]
    good, rejected = [], 0
    for c in cards:
        # _sane is the boundary and is written not to raise, but one hostile card
        # must never be able to abort the pull and take the good ones with it.
        try:
            v = _sane(c)
        except Exception:
            v = None
        if v:
            good.append(v)
        else:
            rejected += 1
    if not good:
        print("  no usable cards (%d rejected as malformed or out of range)" % rejected)
        return 1
    json.dump(good, open(PULLED, "w", encoding="utf-8"), indent=2)
    print("  %d card(s) accepted, %d rejected" % (len(good), rejected))
    print()
    ranked = sorted(good, key=lambda c: -(c["scores"].get("known_item", 0)))
    for c in ranked[:8]:
        p = c["params"]
        print("  sem=%-3s first=%-2s taper=%-2s   known=%-6s curated=%-6s %s chunks"
              % (p["sem_weight"], p["first_div"], p["taper"],
                 c["scores"].get("known_item", "-"),
                 c["scores"].get("curated", "-"),
                 (c.get("corpus") or {}).get("chunks", "?")))
    best, mine = ranked[0], _params()
    print()
    if best["params"] == mine:
        print("  your settings already match the best-performing card")
    else:
        print("  best card differs: %s vs yours %s" % (best["params"], mine))
        print("  adopt with:  recall_share.py --apply   (numbers only)")
    return 0


def cmd_apply():
    try:
        cards = json.load(open(PULLED, encoding="utf-8"))
    except Exception:
        print("  nothing pulled yet - run --pull <url|path> first")
        return 1
    ranked = sorted(cards, key=lambda c: -(c["scores"].get("known_item", 0)))
    if not ranked:
        print("  no cards to apply")
        return 1
    params = ranked[0]["params"]
    try:
        cur = json.load(open(TUNING, encoding="utf-8"))
    except Exception:
        cur = {}
    cur.update(params)
    cur["adopted_from"] = ranked[0].get("machine", "")
    cur["adopted_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    json.dump(cur, open(TUNING, "w", encoding="utf-8"), indent=2)
    print("  adopted %s" % params)
    print("  verify on YOUR corpus before trusting it:")
    print("     python ~/.claude/skills/recall/tests/run_tests.py")
    print("  revert with: recall_tune.py --reset")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--pull")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.export:
        return cmd_export(run_tests=not a.no_tests)
    if a.show:
        return cmd_show()
    if a.pull:
        return cmd_pull(a.pull)
    if a.apply:
        return cmd_apply()
    return cmd_show()


if __name__ == "__main__":
    sys.exit(main())
