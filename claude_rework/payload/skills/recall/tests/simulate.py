#!/usr/bin/env python3
"""simulate - prove recall is not fitted to one machine's data.

Every threshold in this skill was tuned on one corpus: one person, one vocabulary,
one language, one scale. That is the honest limit behind a 300/300 score. These
suites attack it by building throwaway .claude roots with deliberately different
data and running the real pipeline against them.

  simulate.py --machines        synthetic corpora: tiny, huge, non-English, sparse
  simulate.py --optimizer 200   randomised promote/demote scenarios
  simulate.py                   both

Nothing here touches the real corpus, notes, skills or plugins: each run gets its
own temporary root and deletes it in a finally block.
"""
from __future__ import annotations
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time


def _claude_root():
    d = os.path.dirname(os.path.abspath(__file__))
    while d and os.path.basename(d) != ".claude":
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.expanduser("~/.claude")
        d = parent
    return d


REAL = _claude_root()
SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "scripts"))

# Four vocabularies with nothing in common, so a threshold fitted to one cannot
# quietly carry the others.
PROFILES = {
    "tiny": dict(n=40, lang="en", vocab="""ledger invoice reconcile vendor payable
        accrual audit quarter fiscal remittance dunning chargeback""".split()),
    "huge": dict(n=4000, lang="en", vocab="""turbine bearing vibration lubricant
        torque alignment gearbox rotor stator winding thermal harmonic bushing
        shaft coupling flange impeller cavitation""".split()),
    "nonenglish": dict(n=400, lang="tr", vocab="""veriler sunucu guncelleme
        yedekleme cekirdek dizin katman onbellek kuyruk gunluk sifreleme
        dagitim""".split()),
    "sparse": dict(n=120, lang="en",
                   vocab="alpha bravo charlie delta echo foxtrot".split()),
}


def build_machine(root, profile, seed=1):
    rnd = random.Random(seed)
    os.makedirs(os.path.join(root, "projects", "sim"), exist_ok=True)
    vocab = profile["vocab"]
    corpus = os.path.join(root, "recall_corpus.jsonl")
    gold = []
    now = time.time()
    with open(corpus, "w", encoding="utf-8", newline="\n") as fh:
        for i in range(profile["n"]):
            words = [rnd.choice(vocab) for _ in range(rnd.randint(30, 70))]
            marker = "zq%04d" % i
            words.insert(rnd.randrange(len(words)), marker)
            fh.write(json.dumps({"f": "sim.jsonl", "p": "sim",
                                 "t": int(now - rnd.randint(1, 60) * 86400),
                                 "r": "u" if i % 3 else "a",
                                 "m": " ".join(words)}, ensure_ascii=False) + "\n")
            gold.append((i, marker, words))
    df, total = {}, 0
    with open(corpus, encoding="utf-8") as fh:
        for line in fh:
            total += 1
            for w in set(json.loads(line)["m"].split()):
                df[w] = df.get(w, 0) + 1
    json.dump({"n": total, "df": df},
              open(os.path.join(root, "recall_corpus.df.json"), "w", encoding="utf-8"))
    return gold


def run_recall(root, args, timeout=120):
    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8", "HOME": root, "USERPROFILE": root,
                "RECALL_HOME": root})
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "recall.py")] + args,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env, cwd=root)


def suite_machines(verbose=False):
    rates = []
    for name, profile in PROFILES.items():
        tmp = tempfile.mkdtemp(prefix="simclaude-")
        root = os.path.join(tmp, ".claude")
        os.makedirs(root, exist_ok=True)
        try:
            gold = build_machine(root, profile)
            rnd = random.Random(5)
            sample = rnd.sample(gold, min(25, len(gold)))
            hits = 0
            for idx, marker, words in sample:
                content = [w for w in dict.fromkeys(words) if w != marker]
                q = " ".join(rnd.sample(content, min(6, len(content))))
                # recall defaults to a 45-day window; synthetic records span 60,
                # so a quarter were unreachable by construction, not by failure
                p = run_recall(root, [q + " " + marker, "--budget", "1200",
                                      "--days", "3650"])
                if marker in (p.stdout or ""):
                    hits += 1
            rate = hits / len(sample)
            rates.append(rate)
            print("    %-11s n=%-5d %2d/%-2d  %5.1f%%   lang=%s"
                  % (name, profile["n"], hits, len(sample), 100 * rate, profile["lang"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return sum(rates) / len(rates) if rates else None


def build_optimizer_machine(root, n_active, n_library, rnd):
    for tier, count, prefix in (("skills", n_active, "act"),
                                (os.path.join("skills-library", "pack"), n_library, "lib")):
        for i in range(count):
            name = "%s-skill-%03d" % (prefix, i)
            d = os.path.join(root, tier, name)
            os.makedirs(d, exist_ok=True)
            desc = " ".join(rnd.choice(["alpha", "beta", "gamma", "delta"])
                            for _ in range(rnd.randint(20, 60)))
            open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8",
                 newline="\n").write("---\nname: %s\ndescription: %s\n---\nbody\n"
                                     % (name, desc))
    os.makedirs(os.path.join(root, "hooks"), exist_ok=True)
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    for f in os.listdir(SCRIPTS):
        if f.endswith(".py"):
            shutil.copy(os.path.join(SCRIPTS, f), os.path.join(root, "scripts", f))
    real_builder = os.path.join(REAL, "scripts", "build_skill_index.py")
    if os.path.exists(real_builder):
        shutil.copy(real_builder, os.path.join(root, "scripts", "build_skill_index.py"))
    json.dump({"always": [{"name": "pinned-one", "when": "x"}]},
              open(os.path.join(root, "always_skills.json"), "w", encoding="utf-8"))


def suite_optimizer(rounds, verbose=False):
    """Invariants: never lose a file, never act below the evidence gate, never
    crash, never leave the active set changed when the gate says withhold."""
    violations = []
    rnd = random.Random(11)
    for r in range(rounds):
        tmp = tempfile.mkdtemp(prefix="simopt-")
        root = os.path.join(tmp, ".claude")
        os.makedirs(root, exist_ok=True)
        try:
            build_optimizer_machine(root, rnd.randint(1, 8), rnd.randint(1, 8), rnd)
            prompts = rnd.choice([0, 5, 30, 45, 120])
            names = os.listdir(os.path.join(root, "skills-library", "pack"))
            with open(os.path.join(root, "hooks", "skill_usage.jsonl"), "w",
                      encoding="utf-8", newline="\n") as fh:
                for i in range(prompts):
                    hit = [rnd.choice(names)] if names and rnd.random() < 0.5 else []
                    fh.write(json.dumps({"t": int(time.time()), "hits": hit,
                                         "origins": ["library"] * len(hit),
                                         "top": 20.0, "prompt": "p%d" % i}) + "\n")
            env = dict(os.environ)
            env.update({"PYTHONIOENCODING": "utf-8", "HOME": root,
                        "USERPROFILE": root, "RECALL_HOME": root})
            builder = os.path.join(root, "scripts", "build_skill_index.py")
            if os.path.exists(builder):
                subprocess.run([sys.executable, builder], capture_output=True,
                               env=env, cwd=root, timeout=180)
            before_files = sum(len(fs) for _, _, fs in os.walk(root))
            before_active = len(os.listdir(os.path.join(root, "skills")))

            p = subprocess.run([sys.executable, os.path.join(root, "scripts", "recall.py"),
                                "--optimize", "--days", "30", "--apply"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env, cwd=root, timeout=180)
            out = p.stdout or ""
            after_files = sum(len(fs) for _, _, fs in os.walk(root))
            after_active = len(os.listdir(os.path.join(root, "skills")))

            if "Traceback" in (p.stderr or ""):
                violations.append("r%d crashed" % r)
            if after_files < before_files:
                violations.append("r%d FILES LOST %d->%d" % (r, before_files, after_files))
            if prompts < 40 and ("demoted " in out or "promoted " in out):
                violations.append("r%d acted on %d prompts" % (r, prompts))
            if prompts < 40 and after_active != before_active:
                violations.append("r%d active set moved below gate" % r)
        except subprocess.TimeoutExpired:
            violations.append("r%d timeout" % r)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    ok = rounds - len(violations)
    print("    optimizer   %3d/%-3d rounds clean   %s"
          % (ok, rounds, "; ".join(violations[:4]) if violations else ""))
    return ok / rounds if rounds else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--machines", action="store_true")
    ap.add_argument("--optimizer", type=int, default=0)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    run_all = not a.machines and not a.optimizer
    rc = 0
    if a.machines or run_all:
        print("  foreign machines (synthetic corpora, real pipeline)")
        r = suite_machines(a.verbose)
        if r is not None and r < 0.9:
            rc = 1
    if a.optimizer or run_all:
        print("  optimizer invariants")
        r = suite_optimizer(a.optimizer or 100, a.verbose)
        if r is not None and r < 1.0:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
