#!/usr/bin/env python3
"""run_tests - one command that re-verifies every claim this skill makes.

  run_tests.py                 everything (known-item, curated, stress, smoke)
  run_tests.py --known 300     known-item retrieval only, N sampled chunks
  run_tests.py --quick         skip the large known-item sweep

Why known-item retrieval
------------------------
A hand-written benchmark measures the author's imagination. These cases are
generated FROM the corpus: sample a random chunk, build a query out of its own
content words, and require that exact chunk back. The corpus writes the test, so
it scales to hundreds of questions and cannot be tuned toward.

Two rules keep it honest:
  - the single most distinctive word of the chunk is REMOVED from the query, so a
    trivial exact-term match cannot pass it
  - queries are drawn from chunks older than today, so the test is not about work
    done in the current session

Exit code is non-zero if any suite regresses below its floor.
"""
from __future__ import annotations
import argparse
import json
import os
import random
import re
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


CLAUDE = _claude_root()
HERE = os.path.dirname(os.path.abspath(__file__))
RECALL = os.path.abspath(os.path.join(HERE, "..", "scripts", "recall.py"))
CORPUS = os.path.join(CLAUDE, "recall_corpus.jsonl")
DF = os.path.join(CLAUDE, "recall_corpus.df.json")
CURATED = os.path.join(CLAUDE, "recall_cases.json")
GENERATED = os.path.join(HERE, "known_item_cases.json")

STOP = set("""a an the and or of to in for on with is are was were be been do does did
what when where how why who which that this these those i we you it my our your their
about from into over under again more most some any all can could should would will
just like get got make made much many very really then than there here out up down
one two use used using need needs want wants thing things way ways not no yes ok""".split())

# The curated set is 12 questions about work done on specific days. As the corpus
# grows with newer content on the SAME topics, an old answer can be legitimately
# outranked - that is drift, not regression, and demanding 100% forever would
# force tuning toward twelve questions the author wrote. The generated suite is
# the real gate: it regenerates from the current corpus every run, so it measures
# retrieval rather than memory of one afternoon.
FLOORS = {"known_item": 0.95, "curated": 1.0, "stress": 1.0, "smoke": 1.0,
          "capture": 1.0, "vectors": 1.0, "federation": 1.0, "concurrency": 1.0,
          "hooks": 1.0}


def sh(args, timeout=180):
    return subprocess.run([sys.executable, RECALL] + args, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def load_df():
    try:
        d = json.load(open(DF, encoding="utf-8"))
        return d.get("df", {}), max(d.get("n", 1), 1)
    except Exception:
        return {}, 1


def generate(n, seed=7):
    """Known-item cases straight out of the corpus."""
    if not os.path.exists(CORPUS):
        return []
    df, total = load_df()
    rows = []
    with open(CORPUS, encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            try:
                r = json.loads(line)
            except Exception:
                continue
            r["_i"] = i
            rows.append(r)
    if not rows:
        return []

    today = time.strftime("%Y-%m-%d")
    pool = [r for r in rows
            if len(r.get("m", "")) > 260
            and time.strftime("%Y-%m-%d", time.localtime(r.get("t", 0))) != today]
    if len(pool) < n:
        pool = [r for r in rows if len(r.get("m", "")) > 260]

    rnd = random.Random(seed)
    rnd.shuffle(pool)
    cases = []
    for r in pool:
        words = [w for w in re.findall(r"[a-z][a-z0-9_-]{3,}", r["m"].lower())
                 if w not in STOP]
        uniq = list(dict.fromkeys(words))
        if len(uniq) < 10:
            continue
        uniq.sort(key=lambda w: df.get(w, 1))
        gold = uniq[0]
        rest = [w for w in uniq[1:] if df.get(w, 0) < total * 0.25]
        if len(rest) < 6:
            continue
        query = " ".join(rnd.sample(rest, min(8, len(rest))))
        cases.append({"id": r["_i"], "query": query, "gold": gold,
                      "snippet": r["m"][:90]})
        if len(cases) >= n:
            break
    return cases


def suite_known_item(n, verbose=False):
    cases = generate(n)
    if not cases:
        print("  known-item: no corpus, skipped")
        return None
    json.dump(cases, open(GENERATED, "w", encoding="utf-8"), indent=1)
    hits = 0
    misses = []
    t0 = time.time()
    for c in cases:
        p = sh([c["query"], "--budget", "1600"])
        if c["gold"].lower() in (p.stdout or "").lower():
            hits += 1
        elif len(misses) < 6:
            misses.append(c)
    dt = time.time() - t0
    rate = hits / len(cases)
    print("  known-item      %3d/%3d  %5.1f%%   %.2fs/query   (generated)"
          % (hits, len(cases), 100 * rate, dt / len(cases)))
    if verbose:
        for m in misses:
            print("      miss gold=%-18s q=%s" % (m["gold"], m["query"][:60]))
    return rate


def suite_curated():
    try:
        cases = json.load(open(CURATED, encoding="utf-8"))
    except Exception:
        print("  curated: no case file, skipped")
        return None
    hits = fb = 0
    for c in cases:
        p = sh([c["q"], "--budget", "2000"])
        if "corpus unavailable" in (p.stderr or ""):
            fb += 1
        if any(e.lower() in (p.stdout or "").lower() for e in c["expect"]):
            hits += 1
    rate = hits / len(cases)
    print("  curated         %3d/%3d  %5.1f%%   fallbacks=%d"
          % (hits, len(cases), 100 * rate, fb))
    if fb:
        print("      ! fallbacks>0 means the corpus path failed silently")
        return 0.0
    return rate


STRESS = [
    ("empty", [""]), ("one char", ["a"]), ("stopwords", ["the and of to"]),
    ("huge query", ["hook backslash " * 550]),
    ("cjk emoji", ["훅이 왜 안 될까 🔥 スキル"]),
    ("rtl", ["لماذا فشل الخطاف"]),
    ("shell meta", ["`id`; $(whoami) && echo x | cat"]),
    ("traversal", ["../../../../etc/passwd"]),
    ("sql", ["'; DROP TABLE notes;--"]),
    ("regex bomb", ["(a+)+$ ((((((.*))))))"]),
    ("format str", ["%s %d %(x)s {0}"]),
    ("long word", ["z" * 3000]),
    ("budget 0", ["x", "--budget", "0"]),
    ("budget neg", ["x", "--budget", "-500"]),
    ("budget huge", ["x", "--budget", "9999999"]),
    ("days 0", ["x", "--days", "0"]),
    ("days neg", ["x", "--days", "-5"]),
    ("bad project", ["x", "--project", "Z:/nope"]),
    ("project is file", ["x", "--project", __file__]),
]


def suite_stress():
    bad = []
    for name, args in STRESS:
        try:
            p = sh(args, timeout=120)
            if "Traceback" in (p.stderr or ""):
                bad.append(name)
        except subprocess.TimeoutExpired:
            bad.append(name + " (hang)")
    rate = 1 - len(bad) / len(STRESS)
    print("  stress          %3d/%3d  %5.1f%%   %s"
          % (len(STRESS) - len(bad), len(STRESS), 100 * rate,
             ("failed: " + ", ".join(bad)) if bad else ""))
    return rate


SMOKE = [["--stores"], ["--budget-report"], ["--gc"], ["--brief", "--days", "2"],
         ["--decisions", "--days", "2"], ["--digest", "--weeks", "1"],
         ["--handoff"], ["--timeline", "--days", "2"],
         ["--optimize", "--days", "7"], ["--show", "recall"],
         ["--estimate", "hello world"]]


def suite_smoke():
    bad = []
    for args in SMOKE:
        p = sh(args)
        if "Traceback" in (p.stderr or ""):
            bad.append(args[0])
    rate = 1 - len(bad) / len(SMOKE)
    print("  subcommands     %3d/%3d  %5.1f%%   %s"
          % (len(SMOKE) - len(bad), len(SMOKE), 100 * rate,
             ("failed: " + ", ".join(bad)) if bad else ""))
    return rate


# ---------------------------------------------------------------- capture ----
# capture_events.py is a PostToolUse hook: it resolves events.jsonl from its own
# __file__, so copying it into a throwaway .claude/hooks/ is what makes this suite
# physically unable to append to the real log. Nothing here touches live data.
#
# What is asserted, in the order the design cares about:
#   1. a hook must never fail a turn - exit 0 on anything, including garbage stdin
#   2. secrets never reach the log
#   3. real work is recorded, read-only noise is not
#   4. the record is well-formed and bounded

def _pay(tool, cwd, **ti):
    return json.dumps({"tool_name": tool, "tool_input": ti, "cwd": cwd})


def _events(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except Exception:
        return []


def _one(new, kind=None):
    if len(new) != 1:
        return None, "wrote %d lines, expected 1" % len(new)
    if kind and new[0].get("k") != kind:
        return None, "k=%r expected %r" % (new[0].get("k"), kind)
    return new[0], ""


def capture_cases(cwd):
    """(name, stdin, check) - check returns (ok, why)."""
    def none(new, p):
        return (len(new) == 0, "wrote %d lines, expected 0" % len(new))

    def edit_of(rel):
        def check(new, p):
            e, why = _one(new, "edit")
            if not e:
                return False, why
            if e.get("d") != rel:
                return False, "d=%r expected %r" % (e.get("d"), rel)
            if e.get("p") != os.path.basename(cwd):
                return False, "p=%r expected %r" % (e.get("p"), os.path.basename(cwd))
            return True, ""
        return check

    def redacted(*leaks):
        def check(new, p):
            e, why = _one(new, "run")
            if not e:
                return False, why
            d = e.get("d", "")
            for leak in leaks:
                if leak in d:
                    return False, "SECRET LEAKED: %r in %r" % (leak, d)
            if "[redacted]" not in d:
                return False, "nothing was redacted: %r" % d
            return True, ""
        return check

    abs_edit = os.path.join(cwd, "pkg", "mod.py")
    long_cmd = "python train.py " + ("--flag x " * 60)

    return [
        # 1. never fail a turn
        ("empty stdin", "", none),
        ("not json", "{{{not json at all", none),
        ("null fields", json.dumps({"tool_name": None, "tool_input": None,
                                    "cwd": None}), none),
        ("tool_input wrong type", json.dumps({"tool_name": "Bash",
                                              "tool_input": "a string", "cwd": cwd}), none),
        ("no cwd", json.dumps({"tool_name": "Write",
                               "tool_input": {"file_path": "a.py"}}),
         lambda new, p: (len(new) == 1 and new[0].get("p") == "",
                         "expected 1 line with empty project, got %r" % new)),

        # 2. secrets never reach the log
        ("secret: github pat", _pay("Bash", cwd,
            command="git push https://ghp_ABCDEFGH12345678IJKLMNOP@github.com/x/y"),
         redacted("ghp_ABCDEFGH12345678IJKLMNOP")),
        ("secret: openai key", _pay("Bash", cwd,
            command="export OPENAI_API_KEY=sk-proj0000111122223333444455556666"),
         redacted("sk-proj0000111122223333444455556666")),
        ("secret: aws", _pay("Bash", cwd,
            command="aws configure set k AKIAIOSFODNN7EXAMPLE"),
         redacted("AKIAIOSFODNN7EXAMPLE")),
        ("secret: --password", _pay("Bash", cwd,
            command="mysql --password hunter2trustno1 -e 'select 1'"),
         redacted("hunter2trustno1")),
        ("secret: bearer token", _pay("Bash", cwd,
            command="curl -H 'Authorization: Bearer sk9QWERTYUIOPASDFGH' https://api.x"),
         redacted("sk9QWERTYUIOPASDFGH")),
        ("secret: hf token", _pay("Bash", cwd,
            command="huggingface-cli login --token hf_ZZZZYYYYXXXXWWWWVVVV"),
         redacted("hf_ZZZZYYYYXXXXWWWWVVVV")),
        ("secret: x-api-key", _pay("Bash", cwd,
            command="curl -H 'X-Api-Key: 9f8e7d6c5b4a3210' https://api.x"),
         redacted("9f8e7d6c5b4a3210")),
        ("secret: env assignment", _pay("Bash", cwd,
            command="GITHUB_TOKEN=abcdef0123456789 python deploy.py"),
         redacted("abcdef0123456789")),
        ("secret: basic auth", _pay("Bash", cwd,
            command="curl -H 'Authorization: Basic dXNlcjpwYXNzd29yZA==' https://api.x"),
         redacted("dXNlcjpwYXNzd29yZA==")),
        # the anchor that keeps the env branch from eating ordinary paths
        ("tokenizer path kept", _pay("Bash", cwd,
            command="TOKENIZER_PATH=/models/tok.json python encode.py"),
         lambda new, p: (bool(new) and "/models/tok.json" in new[0].get("d", ""),
                         "over-redacted: %r" % (new[0].get("d") if new else None))),

        # 3. real work in, noise out
        ("edit relative", _pay("Edit", cwd, file_path="pkg/mod.py"),
         edit_of("pkg/mod.py")),
        ("edit absolute", _pay("Edit", cwd, file_path=abs_edit),
         edit_of("pkg/mod.py")),
        ("write", _pay("Write", cwd, file_path="docs/readme.md"),
         edit_of("docs/readme.md")),
        ("notebook", _pay("NotebookEdit", cwd, notebook_path="nb/run.ipynb"),
         edit_of("nb/run.ipynb")),
        ("bash recorded", _pay("Bash", cwd, command="pytest tests/ -q"),
         lambda new, p: (_one(new, "run")[0] is not None
                         and new[0].get("d") == "pytest tests/ -q",
                         "got %r" % new)),
        ("noise: ls", _pay("Bash", cwd, command="ls -la src/"), none),
        ("noise: cat", _pay("Bash", cwd, command="cat setup.py"), none),
        ("noise: grep", _pay("Bash", cwd, command="grep -rn TODO ."), none),
        ("noise: echo", _pay("Bash", cwd, command="echo hello"), none),
        ("empty command", _pay("Bash", cwd, command="   "), none),
        ("read tool ignored", _pay("Read", cwd, file_path="a.py"), none),
        ("glob ignored", _pay("Glob", cwd, pattern="**/*.py"), none),
        ("edit without path", _pay("Edit", cwd, old_string="a"), none),

        # 4. well-formed and bounded
        ("whitespace collapsed", _pay("Bash", cwd,
            command="python  -m\tpytest   -q"),
         lambda new, p: (new and new[0].get("d") == "python -m pytest -q",
                         "got %r" % (new[0].get("d") if new else None))),
        ("detail truncated", _pay("Bash", cwd, command=long_cmd),
         lambda new, p: (new and len(new[0].get("d", "")) <= 200,
                         "len=%d exceeds MAX_D" % len(new[0].get("d", "")) if new
                         else "no line")),
        ("unicode command", _pay("Bash", cwd, command="python -c 'print(\"훅 🔥 スキル\")'"),
         lambda new, p: (len(new) == 1, "got %r" % new)),
        ("foreign drive path", _pay("Edit", cwd, file_path="Z:/elsewhere/x.py"),
         lambda new, p: (len(new) == 1 and "\\" not in new[0].get("d", ""),
                         "got %r" % new)),
        ("timestamp sane", _pay("Bash", cwd, command="make build"),
         lambda new, p: (new and abs(new[0].get("t", 0) - time.time()) < 120,
                         "t=%r" % (new[0].get("t") if new else None))),
    ]


def suite_capture(verbose=False):
    src = os.path.join(CLAUDE, "hooks", "capture_events.py")
    if not os.path.exists(src):
        print("  capture: hook not installed, skipped")
        return None
    tmp = tempfile.mkdtemp(prefix="caphook-")
    root = os.path.join(tmp, ".claude")
    hooks = os.path.join(root, "hooks")
    os.makedirs(hooks)
    hook = os.path.join(hooks, "capture_events.py")
    shutil.copy(src, hook)
    log = os.path.join(root, "events.jsonl")
    cases = capture_cases(root)
    bad = []
    try:
        for name, stdin, check in cases:
            before = len(_events(log))
            try:
                p = subprocess.run([sys.executable, hook], input=stdin,
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=60, cwd=root)
            except subprocess.TimeoutExpired:
                bad.append(name + " (hang)")
                continue
            if p.returncode != 0:
                bad.append("%s (exit %d - a hook must never fail a turn)"
                           % (name, p.returncode))
                continue
            new = _events(log)[before:]
            try:
                ok, why = check(new, p)
            except Exception as exc:
                ok, why = False, repr(exc)
            if not ok:
                bad.append("%s [%s]" % (name, why))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rate = 1 - len(bad) / len(cases)
    print("  capture         %3d/%3d  %5.1f%%   %s"
          % (len(cases) - len(bad), len(cases), 100 * rate,
             ("failed: " + "; ".join(bad[:3])) if bad else ""))
    if verbose:
        for b in bad:
            print("      %s" % b)
    return rate


# ---------------------------------------------------------------- vectors ----
# Vectors are addressed by corpus line index, so trusting a stale file does not
# merely miss - it scores the wrong chunk. _coverage() decides how much of the
# matrix is still believable. The case that matters is #3: a byte changed INSIDE
# the covered prefix must be refused, or the optimisation becomes a correctness
# bug that only shows up as slightly worse answers.

def suite_vectors(verbose=False):
    try:
        import numpy  # noqa: F401
    except Exception:
        print("  vectors: numpy unavailable, skipped")
        return None
    embed = os.path.abspath(os.path.join(HERE, "..", "scripts", "recall_embed.py"))
    if not os.path.exists(embed) or not os.path.exists(CORPUS):
        print("  vectors: no corpus or module, skipped")
        return None

    tmp = tempfile.mkdtemp(prefix="covtest-")
    root = os.path.join(tmp, ".claude")
    os.makedirs(root)
    bad = []
    try:
        # Take up to 400 lines, however many exist. `[next(fh) for _ in range(400)]`
        # raises StopIteration on a corpus smaller than that - which is every new
        # install, so the suite failed for exactly the people who had done nothing
        # wrong. Never size a fixture to a number your data is not required to have.
        lines = []
        with open(CORPUS, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                lines.append(line)
                if len(lines) >= 400:
                    break
        if len(lines) < 40:
            print("  vectors: corpus too small to exercise, skipped")
            return None
        n = len(lines)
        with open(os.path.join(root, "recall_corpus.jsonl"), "w",
                  encoding="utf-8", newline="") as fh:
            fh.writelines(lines)

        env = os.environ.get("RECALL_HOME")
        os.environ["RECALL_HOME"] = root
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"   # keep suite output clean
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("re_cov", embed)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            if m.CLAUDE != root:
                return _vec_report(["RECALL_HOME ignored - suite cannot isolate"], 1)
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                m.build(force=True)
            import numpy as np
            mat = np.load(m.VECS)

            def expect(name, want):
                got = m._coverage(mat)
                if got[0] != want:
                    bad.append("%s -> %r expected %r" % (name, got, want))

            expect("untouched", "current")
            with open(m.CORPUS, "a", encoding="utf-8", newline="") as fh:
                for i in range(25):
                    fh.write(json.dumps({"f": "new.jsonl", "p": "sim",
                                         "t": int(time.time()), "r": "u",
                                         "m": "appended record %d" % i}) + "\n")
            expect("append is reusable", "prefix")
            data = open(m.CORPUS, "rb").read()
            open(m.CORPUS, "wb").write(data[:50] + b"X" + data[51:])
            expect("mutated prefix refused", "stale")
            with open(m.CORPUS, "w", encoding="utf-8", newline="") as fh:
                fh.writelines(lines[:max(1, n // 4)])
            expect("shrunk corpus refused", "stale")
            os.remove(m.META)
            expect("missing meta refused", "stale")

            # The invariant the byte digest alone does NOT give you: a prefix can
            # hash correctly and still hold a different number of lines than the
            # matrix has rows. Forge exactly that - meta agrees with the matrix on
            # row count, and its sha genuinely matches the prefix it names, but
            # that prefix contains 410 lines for 400 vectors.
            import hashlib
            with open(os.path.join(root, "recall_corpus.jsonl"), "w",
                      encoding="utf-8", newline="") as fh:
                fh.writelines(lines)
                for i in range(30):
                    fh.write(json.dumps({"f": "n.jsonl", "p": "s",
                                         "t": int(time.time()), "r": "u",
                                         "m": "tail %d" % i}) + "\n")
            raw = open(m.CORPUS, "rb").read()
            cut = 0
            for _ in range(n + 10):          # a prefix 10 lines longer than the matrix
                cut = raw.index(b"\n", cut) + 1
            json.dump({"n": n, "model": "x", "corpus_mtime": 0, "bytes": cut,
                       "sha": hashlib.sha256(raw[:cut]).hexdigest()},
                      open(m.META, "w", encoding="utf-8"))
            expect("line-count mismatch refused", "stale")
        finally:
            if env is None:
                os.environ.pop("RECALL_HOME", None)
            else:
                os.environ["RECALL_HOME"] = env
    except Exception as exc:
        bad.append("crashed: %r" % (exc,))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return _vec_report(bad, 6, verbose)


def _vec_report(bad, total, verbose=False):
    rate = max(0.0, 1 - len(bad) / total)
    print("  vectors         %3d/%3d  %5.1f%%   %s"
          % (total - len(bad), total, 100 * rate,
             ("failed: " + "; ".join(bad[:2])) if bad else ""))
    if verbose:
        for b in bad:
            print("      %s" % b)
    return rate


# ------------------------------------------------------------- federation ----
# A pulled card is the only untrusted input this skill accepts. It arrives as
# JSON from a URL someone else controls, and its numbers are written into the
# tuning file. Everything here is an attempt to get a bad value past _sane() or
# an unexpected key into recall_tuning.json.

def _card(**over):
    c = {"schema": 1, "machine": "abc123", "model": "potion-base-32M",
         "params": {"sem_weight": 16, "first_div": 3, "taper": 8},
         "scores": {"known_item": 0.99, "curated": 1.0},
         "corpus": {"chunks": 5000, "vocab": 20000}, "at": "2026-01-01"}
    c.update(over)
    return c


def _p(**over):
    p = {"sem_weight": 16, "first_div": 3, "taper": 8}
    p.update(over)
    return _card(params=p)


FED_REJECT = [
    ("wrong schema", _card(schema=2)),
    ("no schema", _card(schema=None)),
    ("params missing", _card(params={})),
    ("params not a dict", _card(params=[1, 2, 3])),
    ("sem_weight as string", _p(sem_weight="16")),
    ("sem_weight as float", _p(sem_weight=16.0)),
    ("sem_weight as bool", _p(sem_weight=True)),      # bool is an int in Python
    ("sem_weight negative", _p(sem_weight=-1)),
    ("sem_weight over range", _p(sem_weight=41)),
    ("first_div zero", _p(first_div=0)),              # would divide by zero
    ("taper under range", _p(taper=1)),
    ("taper enormous", _p(taper=10 ** 9)),
    ("param is shell", _p(sem_weight="12; rm -rf /")),
    ("param is a dict", _p(taper={"$ne": None})),
    ("param is null", _p(first_div=None)),
    ("scores not a dict", _card(scores="perfect")),
    ("score above 1", _card(scores={"known_item": 1.5})),
    ("score negative", _card(scores={"known_item": -0.1})),
    ("score is a string", _card(scores={"known_item": "1.0"})),
    ("card is a string", "not a card at all"),
    ("card is a number", 42),
    ("card is null", None),
]


def suite_federation(verbose=False):
    share = os.path.abspath(os.path.join(HERE, "..", "scripts", "recall_share.py"))
    if not os.path.exists(share):
        print("  federation: module missing, skipped")
        return None
    tmp = tempfile.mkdtemp(prefix="fedtest-")
    root = os.path.join(tmp, ".claude")
    os.makedirs(root)
    tuning = os.path.join(root, "recall_tuning.json")
    bad = []
    env = dict(os.environ)
    env.update({"RECALL_HOME": root, "PYTHONIOENCODING": "utf-8"})

    def run(args, timeout=90):
        return subprocess.run([sys.executable, share] + args, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env, cwd=root)

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("rs", share)
        rs = importlib.util.module_from_spec(spec)
        os.environ["RECALL_HOME"] = root
        spec.loader.exec_module(rs)

        total = len(FED_REJECT) + 6
        for name, card in FED_REJECT:
            try:
                if rs._sane(card) is not None:
                    bad.append("ACCEPTED bad card: " + name)
            except Exception as exc:
                bad.append("%s crashed the validator: %r" % (name, exc))

        if rs._sane(_card()) is None:
            bad.append("rejected a valid card")

        # a long machine id must be truncated, not trusted
        v = rs._sane(_card(machine="A" * 5000))
        if not v or len(v["machine"]) > 16:
            bad.append("machine id not truncated")

        # a mixed feed keeps the good and drops the bad
        feed = os.path.join(root, "feed.json")
        json.dump([_card(), _p(sem_weight="x"), _card(schema=9)],
                  open(feed, "w", encoding="utf-8"))
        p = run(["--pull", feed])
        if "1 card(s) accepted, 2 rejected" not in (p.stdout or ""):
            bad.append("mixed feed miscounted: %r" % (p.stdout or "")[:90])

        # --apply writes ONLY the three integers; no key from the card rides along
        json.dump([_card(params={"sem_weight": 16, "first_div": 3, "taper": 8,
                                 "evil": "payload", "__proto__": "x"})],
                  open(feed, "w", encoding="utf-8"))
        run(["--pull", feed])
        run(["--apply"])
        try:
            got = json.load(open(tuning, encoding="utf-8"))
        except Exception as exc:
            got = {}
            bad.append("apply wrote no tuning file: %r" % exc)
        if "evil" in got or "__proto__" in got:
            bad.append("KEY INJECTION: extra card keys reached recall_tuning.json")
        if got.get("sem_weight") != 16:
            bad.append("apply did not adopt the winning parameter")

        # a feed of only-bad cards must refuse, not half-apply
        json.dump([_card(schema=3)], open(feed, "w", encoding="utf-8"))
        p = run(["--pull", feed])
        if p.returncode == 0:
            bad.append("pull of all-bad feed reported success")

        # missing source is an error, never a traceback
        p = run(["--pull", os.path.join(root, "nope.json")])
        if "Traceback" in (p.stderr or ""):
            bad.append("missing source crashed")
    except Exception as exc:
        bad.append("suite crashed: %r" % (exc,))
        total = len(FED_REJECT) + 6
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    rate = max(0.0, 1 - len(bad) / total)
    print("  federation      %3d/%3d  %5.1f%%   %s"
          % (total - len(bad), total, 100 * rate,
             ("failed: " + "; ".join(bad[:2])) if bad else ""))
    if verbose:
        for b in bad:
            print("      %s" % b)
    return rate


# ------------------------------------------------------------ concurrency ----
# A hook starts a corpus build on every session open, so two Claude windows is
# two builds at once. Before the lock that produced a corpus that was 56%
# duplicates on the real machine. Three builders, one root, zero duplicates.

def suite_concurrency(verbose=False):
    indexer = os.path.abspath(os.path.join(HERE, "..", "scripts", "recall_index.py"))
    if not os.path.exists(indexer):
        print("  concurrency: indexer missing, skipped")
        return None
    tmp = tempfile.mkdtemp(prefix="conc-")
    root = os.path.join(tmp, ".claude")
    proj = os.path.join(root, "projects", "sim")
    os.makedirs(proj)
    bad = []
    try:
        rnd = random.Random(3)
        for fno in range(3):
            with open(os.path.join(proj, "s%d.jsonl" % fno), "w",
                      encoding="utf-8", newline="\n") as fh:
                for i in range(60):
                    words = " ".join("w%d" % rnd.randint(0, 400) for _ in range(40))
                    fh.write(json.dumps({"type": "user", "message": {
                        "content": "file %d message %d %s" % (fno, i, words)}}) + "\n")
        env = dict(os.environ)
        env.update({"RECALL_HOME": root, "PYTHONIOENCODING": "utf-8"})
        procs = [subprocess.Popen([sys.executable, indexer, "--build"], env=env,
                                  cwd=root, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE) for _ in range(3)]
        outs = [p.communicate(timeout=300)[0].decode("utf-8", "replace") for p in procs]
        skipped = sum("already running" in o for o in outs)

        corpus = os.path.join(root, "recall_corpus.jsonl")
        n, seen = 0, set()
        with open(corpus, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                n += 1
                r = json.loads(line)
                seen.add((r.get("f"), r.get("t"), r.get("m", "")[:200]))
        if n == 0:
            bad.append("no corpus produced")
        if n != len(seen):
            bad.append("DUPLICATES: %d lines, %d distinct" % (n, len(seen)))
        if skipped < 1:
            bad.append("no builder reported skipping - lock not taken")
        if os.path.exists(os.path.join(root, "recall_corpus.lock")):
            bad.append("lock file left behind")

        # a second, sequential build must be a no-op that still dedupes cleanly
        subprocess.run([sys.executable, indexer, "--build"], env=env, cwd=root,
                       capture_output=True, timeout=300)
        n2 = sum(1 for _ in open(corpus, encoding="utf-8", errors="replace"))
        if n2 != n:
            bad.append("sequential rebuild changed line count %d -> %d" % (n, n2))
    except Exception as exc:
        bad.append("crashed: %r" % (exc,))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    total = 5
    rate = max(0.0, 1 - len(bad) / total)
    print("  concurrency     %3d/%3d  %5.1f%%   %s"
          % (total - len(bad), total, 100 * rate,
             ("failed: " + "; ".join(bad[:2])) if bad else "3 builders, 0 duplicates"))
    if verbose:
        for b in bad:
            print("      %s" % b)
    return rate


# ------------------------------------------------------------------ hooks ----
# The three hooks that make recall automatic, run the way Claude Code runs them:
# a JSON payload on stdin, output on stdout, exit 0 no matter what. They resolve
# ~/.claude from their own location, so they are copied into a throwaway root
# beside a copy of the scripts and a synthetic corpus with a known marker.
# Skipped where the hooks are not installed (a machine running its own
# equivalents); exercised on every installed machine and in CI.

def suite_hooks(verbose=False):
    names = ["recall_auto.py", "recall_session_start.py", "recall_precompact.py"]
    src_hooks = os.path.join(CLAUDE, "hooks")
    absent = [n for n in names if not os.path.exists(os.path.join(src_hooks, n))]
    if absent:
        print("  hooks: not installed here (%s), skipped" % ", ".join(absent))
        return None
    tmp = tempfile.mkdtemp(prefix="hooks-")
    root = os.path.join(tmp, ".claude")
    hooks = os.path.join(root, "hooks")
    scripts = os.path.join(root, "skills", "recall", "scripts")
    os.makedirs(hooks)
    os.makedirs(scripts)
    bad = []
    total = 13
    try:
        for n in names:
            shutil.copy(os.path.join(src_hooks, n), hooks)
        src_scripts = os.path.abspath(os.path.join(HERE, "..", "scripts"))
        for f in os.listdir(src_scripts):
            if f.endswith(".py"):
                shutil.copy(os.path.join(src_scripts, f), scripts)

        now = int(time.time())
        marker = "zebraquokka"
        rows = []
        for i in range(40):
            rows.append({"f": "sim.jsonl", "p": "sim", "t": now - i * 3600, "r": "u",
                         "m": "how should we handle retries on the upload endpoint "
                              "round %d with backoff and jitter please" % i})
            rows.append({"f": "sim.jsonl", "p": "sim", "t": now - i * 3600, "r": "a",
                         "m": "Decided on exponential backoff capped at thirty seconds "
                              "round %d because the provider rate-limits per minute." % i})
        rows.append({"f": "sim.jsonl", "p": "sim", "t": now - 60, "r": "u",
                     "m": "what did we settle on for the payment webhook timeout"})
        rows.append({"f": "sim.jsonl", "p": "sim", "t": now - 30, "r": "a",
                     "m": "We decided the payment webhook timeout is twelve seconds "
                          "after measuring the provider p99; marker %s." % marker})
        with open(os.path.join(root, "recall_corpus.jsonl"), "w", encoding="utf-8",
                  newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        df = {}
        for r in rows:
            for w in set(re.findall(r"[a-z][a-z0-9_-]{2,}", r["m"].lower())):
                df[w] = df.get(w, 0) + 1
        json.dump({"n": len(rows), "df": df},
                  open(os.path.join(root, "recall_corpus.df.json"), "w",
                       encoding="utf-8"))

        env = dict(os.environ)
        env.update({"RECALL_HOME": root, "PYTHONIOENCODING": "utf-8",
                    "HF_HUB_DISABLE_PROGRESS_BARS": "1"})

        def hook(name, stdin):
            p = subprocess.run([sys.executable, os.path.join(hooks, name)],
                               input=stdin, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=180,
                               env=env, cwd=root)
            return p.returncode, (p.stdout or ""), (p.stderr or "")

        def expect(label, cond, detail=""):
            if not cond:
                bad.append("%s [%s]" % (label, str(detail)[:110]))

        pay = lambda **k: json.dumps(dict(k))

        rc, out, err = hook("recall_auto.py",
                            pay(prompt="didn't we already decide the payment webhook "
                                       "timeout?", cwd=root))
        expect("auto fires on a past-shaped prompt", rc == 0 and "RECALLED" in out,
               err[-90:] or out[:90])
        expect("auto surfaces the answer", marker in out.lower(), out[:110])
        rc, out, _ = hook("recall_auto.py",
                          pay(prompt="create a new endpoint for uploads", cwd=root))
        expect("auto silent on new work", rc == 0 and out.strip() == "", out[:70])
        rc, out, _ = hook("recall_auto.py", pay(prompt="hi there", cwd=root))
        expect("auto silent on a short prompt", rc == 0 and out.strip() == "", out[:70])
        rc, out, _ = hook("recall_auto.py", "garbage{{{")
        expect("auto survives garbage stdin", rc == 0 and out.strip() == "", out[:70])
        rc, out, _ = hook("recall_auto.py",
                          pay(prompt="what did we decide about the upload retries?",
                              cwd=root))
        expect("auto debounced on an immediate repeat", rc == 0 and out.strip() == "",
               out[:70])

        rc, out, err = hook("recall_session_start.py", pay(cwd=root))
        expect("session start exits 0", rc == 0 and "Traceback" not in err, err[-90:])
        expect("session start prints a banner or nothing",
               out.strip() == "" or out.startswith("WHERE YOU LEFT OFF"), out[:70])
        rc, out, _ = hook("recall_session_start.py", "garbage{{{")
        expect("session start survives garbage stdin", rc == 0, rc)

        rc, out, err = hook("recall_precompact.py",
                            pay(cwd=root, trigger="manual",
                                transcript_path="/x/sess-42.jsonl"))
        expect("precompact exits 0", rc == 0 and "Traceback" not in err, err[-90:])
        expect("precompact prints the handoff", "RECALL HANDOFF" in out, out[:70])
        expect("precompact writes the handoff to disk",
               os.path.exists(os.path.join(root, "recall_handoffs", "sess-42.md")))
        rc, out, _ = hook("recall_precompact.py", "garbage{{{")
        expect("precompact survives garbage stdin", rc == 0, rc)
    except Exception as exc:
        bad.append("suite crashed: %r" % (exc,))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rate = max(0.0, 1 - len(bad) / total)
    print("  hooks           %3d/%3d  %5.1f%%   %s"
          % (total - len(bad), total, 100 * rate,
             ("failed: " + "; ".join(bad[:2])) if bad else ""))
    if verbose:
        for b in bad:
            print("      %s" % b)
    return rate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--known", type=int, default=200)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    print("recall test suite")
    print("  corpus: %s" % ("present" if os.path.exists(CORPUS) else "MISSING"))
    print()
    results = {}
    if not a.quick:
        results["known_item"] = suite_known_item(a.known, a.verbose)
    results["curated"] = suite_curated()
    results["stress"] = suite_stress()
    results["smoke"] = suite_smoke()
    results["capture"] = suite_capture(a.verbose)
    results["vectors"] = suite_vectors(a.verbose)
    results["federation"] = suite_federation(a.verbose)
    results["concurrency"] = suite_concurrency(a.verbose)
    results["hooks"] = suite_hooks(a.verbose)

    print()
    failed = []
    for name, rate in results.items():
        if rate is None:
            continue
        floor = FLOORS.get(name, 1.0)
        if rate < floor:
            failed.append("%s %.0f%% < floor %.0f%%" % (name, 100 * rate, 100 * floor))
    if failed:
        print("  FAIL: " + "; ".join(failed))
        return 1
    print("  PASS - every suite at or above its floor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
