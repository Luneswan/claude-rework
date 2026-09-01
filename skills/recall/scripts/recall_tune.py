#!/usr/bin/env python3
"""recall_tune - the skill retunes itself as the corpus grows.

Retrieval parameters were fitted to one corpus at one moment. The corpus changes
every session, so the right values drift. This regenerates fresh known-item cases
from the CURRENT corpus, sweeps the parameters, and keeps a new value only when it
beats the incumbent on questions nobody wrote by hand.

  recall_tune.py --run [--cases 80]   sweep and write the winner
  recall_tune.py --show               current tuning and when it was set
  recall_tune.py --reset              back to shipped defaults

Two guards, the same discipline the optimizer uses:
  - a candidate must beat the incumbent on generated cases AND not regress the
    curated set; either failure and the incumbent stands
  - the winner is written to recall_tuning.json, never into the code, so a bad
    tune is one file deletion away from gone
"""
from __future__ import annotations
import argparse
import datetime
import itertools
import json
import os
import subprocess
import sys


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
RECALL = os.path.join(HERE, "recall.py")
TESTS = os.path.abspath(os.path.join(HERE, "..", "tests"))
TUNING = os.path.join(CLAUDE, "recall_tuning.json")
CURATED = os.path.join(CLAUDE, "recall_cases.json")

DEFAULTS = {"sem_weight": 12, "first_div": 2, "taper": 6}
GRID = {"sem_weight": [8, 12, 16], "first_div": [2, 3], "taper": [5, 6, 8]}


def load():
    try:
        d = json.load(open(TUNING, encoding="utf-8"))
        return {k: d.get(k, v) for k, v in DEFAULTS.items()}, d
    except Exception:
        return dict(DEFAULTS), {}


def _env(params):
    e = dict(os.environ)
    e.update({"PYTHONIOENCODING": "utf-8",
              "RECALL_SEM_WEIGHT": str(params["sem_weight"]),
              "RECALL_FIRST_DIV": str(params["first_div"]),
              "RECALL_TAPER": str(params["taper"])})
    return e


def _gen(n):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rt", os.path.join(TESTS, "run_tests.py"))
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)
    return rt.generate(n, seed=int(datetime.date.today().strftime("%j")))



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


def _score(cases, params, budget="1600"):
    hits = 0
    for c in cases:
        p = subprocess.run([sys.executable, RECALL, c["query"], "--budget", budget],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=_env(params), timeout=120, **_no_window())
        if c["gold"].lower() in (p.stdout or "").lower():
            hits += 1
    return hits / max(len(cases), 1)


def _curated(params):
    try:
        cases = json.load(open(CURATED, encoding="utf-8"))
    except Exception:
        return 1.0
    hits = 0
    for c in cases:
        p = subprocess.run([sys.executable, RECALL, c["q"], "--budget", "2000"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=_env(params), timeout=120, **_no_window())
        if any(e.lower() in (p.stdout or "").lower() for e in c["expect"]):
            hits += 1
    return hits / max(len(cases), 1)


def run(n_cases=80, verbose=True):
    cases = _gen(n_cases)
    if len(cases) < 20:
        print("  corpus too small to tune on (%d cases) - keeping current settings"
              % len(cases))
        return 0
    current, _meta = load()
    base = _score(cases, current)
    base_cur = _curated(current)
    if verbose:
        print("  incumbent %s -> generated %.1f%%  curated %.1f%%  (%d fresh cases)"
              % (current, 100 * base, 100 * base_cur, len(cases)))

    best, best_score = dict(current), base
    tried = 0
    for combo in itertools.product(*GRID.values()):
        cand = dict(zip(GRID.keys(), combo))
        if cand == current:
            continue
        tried += 1
        s = _score(cases, cand)
        if s <= best_score:
            continue
        c = _curated(cand)
        if c < base_cur:
            if verbose:
                print("    %s generated %.1f%% but curated regressed to %.1f%% - rejected"
                      % (cand, 100 * s, 100 * c))
            continue
        best, best_score = cand, s
        if verbose:
            print("    %s -> generated %.1f%%  curated %.1f%%  ACCEPTED"
                  % (cand, 100 * s, 100 * c))

    if best == current:
        print("  no candidate beat the incumbent across %d combination(s)" % tried)
        return 0
    out = dict(best)
    out.update({"tuned_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "score": round(best_score, 4), "cases": len(cases),
                "previous": current, "previous_score": round(base, 4)})
    json.dump(out, open(TUNING, "w", encoding="utf-8"), indent=2)
    print("  retuned: %s -> %s   generated %.1f%% -> %.1f%%"
          % (current, best, 100 * base, 100 * best_score))
    return 0


def show():
    cur, meta = load()
    print("  current: %s" % cur)
    if meta.get("tuned_at"):
        print("  tuned  : %s on %d generated cases (%.1f%%)"
              % (meta["tuned_at"], meta.get("cases", 0), 100 * meta.get("score", 0)))
        if meta.get("previous"):
            print("  was    : %s (%.1f%%)"
                  % (meta["previous"], 100 * meta.get("previous_score", 0)))
    else:
        print("  never tuned - shipped defaults")
    return 0


def reset():
    if os.path.exists(TUNING):
        os.remove(TUNING)
        print("  tuning removed, shipped defaults restored")
    else:
        print("  already on shipped defaults")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--cases", type=int, default=80)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    if a.reset:
        return reset()
    if a.run:
        return run(a.cases)
    return show()


if __name__ == "__main__":
    sys.exit(main())
