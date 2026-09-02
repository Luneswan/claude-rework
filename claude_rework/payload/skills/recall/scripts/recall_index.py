#!/usr/bin/env python3
"""recall_index - extract once, search forever.

Raw transcripts on this machine total ~7 GB across 1,400 files, with single
sessions over 1.7 GB. Scanning them per query is why recall took minutes; the
answer only ever needed the human-typed messages, which are a rounding error of
that volume.

Builds ~/.claude/recall_corpus.jsonl - one line per user message - and refreshes
only files whose mtime or size changed. Same coverage, no quality loss, three
orders of magnitude less I/O per query.

  recall_index.py --build          incremental refresh (safe to run often)
  recall_index.py --build --full   ignore the manifest, re-extract everything
  recall_index.py --status         corpus size, coverage, staleness
"""
from __future__ import annotations
import argparse
import glob
import json
import math
import os
import sys
import re
import time

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
CORPUS = os.path.join(CLAUDE, "recall_corpus.jsonl")
MANIFEST = os.path.join(CLAUDE, "recall_corpus.manifest.json")
DF = os.path.join(CLAUDE, "recall_corpus.df.json")
EVENTS = os.path.join(CLAUDE, "events.jsonl")

MAX_MSG = 600          # characters per chunk
CHUNK_OVERLAP = 80     # so a fact spanning a boundary is still findable
MAX_CHUNKS = 6         # per message: enough for a long answer, bounded for size
MAX_PER_FILE = 4000    # messages kept from one session, newest wins
# Harness-injected text arrives on the "user" channel but is not a request:
# hook feedback, tool-permission notices, image placeholders, resume banners.
# Indexing it makes "what did I ask" answer with machine chatter.
SKIP_PREFIX = ("<", "[Image", "Caveat:", "[Request", "Stop hook feedback",
               "This session is being continued", "PreToolUse:", "PostToolUse:",
               "SessionStart", "UserPromptSubmit", "[SYSTEM NOTIFICATION",
               "Command running in background", "The user sent a new message")
SKIP_CONTAINS = ("hook additional context:", "hook feedback:",
                 "<task-notification>", "<system-reminder>")

# Assistant turns are mostly narration; the valuable minority states a finding,
# a cause, or a decision. Indexing everything would bloat the corpus for no
# recall gain, so keep only turns that carry one of these signals.
# Gate on the VERB and the NOUN of the same idea. The list held "decided" but not
# "decision", "confirmed" but not "conclusion" - so a turn recording a real
# decision in noun form was dropped. Volume hides this on a large corpus; on a new
# one the dropped turn is the answer. A clean-room install indexed 15 of 61
# assistant turns, and the one holding the answer was not among them.
FINDING = ("because", "root cause", "the cause", "caused by", "the reason",
           "turns out", "actually", "decided", "decision", "chose", "chosen",
           "settled on", "concluded", "conclusion", "instead of", "fixed",
           "verified", "measured", "confirmed", "the bug", "the fix", "so that",
           "which means", "caveat", "limitation", "trade-off", "tradeoff",
           "cannot", "does not", "never", "always")
MIN_ASSISTANT = 120


def _norm(t):
    return " ".join((t or "").split())


def _chunks(text):
    """Truncating at 600 chars silently lost 41% of message content - the detail
    that answers a question is usually NOT in the first paragraph. Chunk with a
    small overlap instead, so a fact spanning a boundary is still findable."""
    text = _norm(text)
    if len(text) <= MAX_MSG:
        return [text]
    out, start = [], 0
    while start < len(text) and len(out) < MAX_CHUNKS:
        out.append(text[start:start + MAX_MSG])
        start += MAX_MSG - CHUNK_OVERLAP
    return out


def extract(path):
    """What was asked, and what was concluded. Returns (role, text) pairs.

    Indexing only user messages answers "what did I ask about X" but not "what did
    we conclude about X" - which is the question people actually have. Assistant
    turns are filtered to those carrying a finding, cause or decision."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"user"' not in line and '"assistant"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                kind = ev.get("type")
                if kind not in ("user", "assistant"):
                    continue
                m = (ev.get("message") or {}).get("content")
                if isinstance(m, list):
                    m = " ".join(c.get("text", "") for c in m
                                 if isinstance(c, dict) and c.get("type") == "text")
                if not isinstance(m, str):
                    continue
                if kind == "user":
                    if len(m) < 15 or m.lstrip().startswith(SKIP_PREFIX):
                        continue
                    low_head = m[:400].lower()
                    if any(k in low_head for k in SKIP_CONTAINS):
                        continue
                    for c in _chunks(m):
                        out.append(("u", c))
                else:
                    if len(m) < MIN_ASSISTANT:
                        continue
                    low = m.lower()
                    if not any(k in low for k in FINDING):
                        continue
                    for c in _chunks(m):
                        out.append(("a", c))
    except Exception:
        return []
    return out[-MAX_PER_FILE:]


def load_manifest():
    try:
        return json.load(open(MANIFEST, encoding="utf-8"))
    except Exception:
        return {}



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


LOCK = os.path.join(CLAUDE, "recall_corpus.lock")
LOCK_STALE = 600     # a lock older than this belongs to a builder that died


def acquire_lock():
    """One builder at a time, or the corpus fills with duplicates.

    Two concurrent builds each read the corpus into `keep`, each truncate the
    file, each append what they extracted - and every record lands twice. With a
    hook spawning a build on every session start, two open Claude windows is all
    it takes. Measured after one burst: 50,499 lines, 22,405 distinct, one record
    present 122 times, and two curated answers crowded out of the budget.

    Atomic create, so there is no check-then-create window. A lock older than
    LOCK_STALE is a crashed builder and is taken over rather than waited on.
    """
    for _ in range(2):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(LOCK) > LOCK_STALE:
                    os.remove(LOCK)
                    continue
            except OSError:
                pass
            return False
        except OSError:
            return False
    return False


def release_lock():
    try:
        os.remove(LOCK)
    except OSError:
        pass


def build(full=False, verbose=True):
    """Incremental and resumable: the corpus is appended per file and the manifest
    saved after each one, so a 7 GB first build is queryable while it runs and an
    interruption costs one file, not the whole extraction. Serialised by a lock;
    a second builder exits immediately rather than racing."""
    if not acquire_lock():
        if verbose:
            print("  another build is already running - skipped")
        return 0
    try:
        return _build(full, verbose)
    finally:
        release_lock()


def _build(full, verbose):
    NL = chr(10)
    files = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    manifest = {} if full else load_manifest()
    changed, total_msgs = 0, 0

    # Dedupe while keeping. A duplicate that ever got in used to be kept forever,
    # because `keep` preserved every line whose source was unchanged - including
    # the copies. Keying on (source, mtime, text) heals an already-duplicated
    # corpus on the next incremental build instead of enshrining it.
    keep, seen = [], set()
    # The scan runs even on --full: a full rebuild re-extracts every LOCAL
    # transcript, but imported records have no local transcript to re-extract
    # from, so they must be carried across or the rebuild erases a migration.
    if os.path.exists(CORPUS):
        try:
            with open(CORPUS, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if full and not r.get("im"):
                        continue
                    # Imported history has no local source file and never will:
                    # it came from another machine or account. Judging it by
                    # os.path.exists() deletes it on the first rebuild, which is
                    # exactly when someone has just migrated and is checking
                    # whether their memory survived.
                    if r.get("im"):
                        key = (r.get("f", ""), r.get("t"), r.get("m", ""))
                        if key not in seen:
                            seen.add(key)
                            keep.append(line.rstrip(NL))
                        continue
                    src = r.get("f")
                    if not src or src not in manifest or not os.path.exists(src):
                        continue
                    st = os.stat(src)
                    if manifest[src] != [int(st.st_mtime), st.st_size]:
                        continue
                    key = (src, r.get("t"), r.get("m", ""))
                    if key in seen:
                        continue
                    seen.add(key)
                    keep.append(line.rstrip(NL))
        except Exception:
            keep = []

    stale = []
    for f in files:
        try:
            st = os.stat(f)
        except OSError:
            continue
        sig = [int(st.st_mtime), st.st_size]
        if not full and manifest.get(f) == sig:
            continue
        stale.append((f, sig, st.st_size))

    stale.sort(key=lambda x: x[2])          # small files first: fast early wins
    with open(CORPUS, "w", encoding="utf-8", newline=NL) as fh:
        for line in keep:
            fh.write(line + NL)

    t0 = time.time()
    for i, (f, sig, size) in enumerate(stale, 1):
        proj = os.path.basename(os.path.dirname(f))
        msgs = extract(f)
        # Same key as `keep`, so a full build and an incremental one produce the
        # same corpus. This also collapses genuine within-file repeats: a skill
        # body re-injected on every loop iteration landed 61 times in one
        # session, and 2,628 such groups were a third of the corpus. Identical
        # text at an identical file mtime carries nothing extra to retrieve and
        # still costs index space, embedding time and candidate slots.
        with open(CORPUS, "a", encoding="utf-8", newline=NL) as fh:
            for role, m in msgs:
                key = (f, sig[0], m)
                if key in seen:
                    continue
                seen.add(key)
                fh.write(json.dumps({"f": f, "p": proj, "t": sig[0], "r": role,
                                     "m": m}, ensure_ascii=False) + NL)
        manifest[f] = sig
        json.dump(manifest, open(MANIFEST, "w", encoding="utf-8"))
        changed += 1
        total_msgs += len(msgs)
        if verbose and (i % 25 == 0 or size > 50 * 1024 * 1024):
            print("  %d/%d  %6.1f MB  %-34s +%d msgs"
                  % (i, len(stale), size / 1024 / 1024, proj[:34], len(msgs)), flush=True)

    # What was DONE joins what was said. Events are grouped into short windows so
    # a burst of edits becomes one searchable record ("edited fetcher.py,
    # scraper.py; ran pytest") rather than fifty rows nothing can match against.
    try:
        rows, window, last_t, last_p = [], [], 0, ""
        with open(EVENTS, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if window and (e.get("t", 0) - last_t > 900 or e.get("p") != last_p):
                    rows.append((last_t, last_p, window))
                    window = []
                window.append(e)
                last_t, last_p = e.get("t", 0), e.get("p", "")
        if window:
            rows.append((last_t, last_p, window))
        with open(CORPUS, "a", encoding="utf-8", newline=NL) as fh:
            for t, proj, evs in rows:
                edits = [e["d"] for e in evs if e.get("k") == "edit"]
                runs = [e["d"] for e in evs if e.get("k") == "run"]
                parts = []
                if edits:
                    parts.append("edited " + ", ".join(dict.fromkeys(edits))[:400])
                if runs:
                    parts.append("ran " + " ; ".join(dict.fromkeys(runs))[:400])
                if not parts:
                    continue
                fh.write(json.dumps({"f": "events", "p": proj, "t": t, "r": "d",
                                     "m": "; ".join(parts)[:MAX_MSG]},
                                    ensure_ascii=False) + NL)
        if verbose and rows:
            print("  + %d activity record(s) from events.jsonl" % len(rows))
    except FileNotFoundError:
        pass
    except Exception as exc:
        if verbose:
            print("  events not indexed: %r" % exc)

    # Document frequency, computed once at build time. Plain term counts let
    # "wrong" and "plan" outvote "composio" and "graphify"; the rare word is the
    # one that identifies the answer. Same fix that took the skill router from
    # 72% to 98%.
    df, total = {}, 0
    try:
        with open(CORPUS, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    m = json.loads(line).get("m", "")
                except Exception:
                    continue
                total += 1
                for w in set(re.findall(r"[a-z0-9][a-z0-9_.+-]{2,}", m.lower())):
                    df[w] = df.get(w, 0) + 1
        json.dump({"n": total, "df": df}, open(DF, "w", encoding="utf-8"))
    except Exception:
        pass

    # vectors must follow the corpus or semantic scoring silently goes stale
    if changed:
        try:
            import subprocess as _sp
            _sp.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "recall_embed.py"), "--build"],
                    capture_output=True, timeout=600, **_no_window())
        except Exception:
            pass

    if verbose:
        raw = sum(s for _, _, s in stale)
        lines = sum(1 for _ in open(CORPUS, encoding="utf-8", errors="replace"))
        print("  extracted %d file(s), %.0f MB scanned, %d messages, in %.0fs"
              % (changed, raw / 1024 / 1024, total_msgs, time.time() - t0))
        print("  corpus now %.1f MB (%d messages)"
              % (os.path.getsize(CORPUS) / 1024 / 1024, lines))
    return 0


_DF = {"n": 0, "df": {}}
def _idf(term):
    """Rare word, strong signal. Loaded once from the df map built at index time."""
    if not _DF["n"]:
        try:
            _DF.update(json.load(open(DF, encoding="utf-8")))
        except Exception:
            _DF["n"] = -1
    if _DF["n"] <= 0:
        return 1.0
    d = _DF["df"].get(term, 0)
    if not d:
        return 2.5
    # Floor near zero, not 0.3. A word in every record carries no information, but
    # a 0.3 floor let six ubiquitous words (6 x 3 x 0.3 = 5.4) outvote a unique
    # marker (1.23) - found by simulating corpora with tiny vocabularies, where
    # almost every word is ubiquitous. Invisible on a naturally diverse corpus.
    return max(0.02, min(3.5, math.log(_DF["n"] / d) / math.log(20)))


def search_corpus(terms, days, limit=6, sem=None, sem_weight=None, project=None):
    """Same contract as the old live scan, against the extract - but each term is
    weighted by how rare it is, so a distinctive word carries the match.

    `project` restricts hits to one project name (the basename a record was
    tagged with). Left None, every project is searched, which is the useful
    default: the answer is often in the repo you were in last week, not this one.
    """
    if not os.path.exists(CORPUS):
        return []
    weights = {t: _idf(t) for t in terms}
    cutoff = time.time() - days * 86400
    if sem_weight is None:
        # measured on the 12-case set: 0 -> 83%, 12 -> 92%, 25 -> 58%.
        # recall_tuning.json can move it as the corpus grows; env still wins.
        _dflt = 12
        try:
            import importlib.util as _il
            _sp = _il.spec_from_file_location(
                "rtune", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "recall_tune.py"))
            _m = _il.module_from_spec(_sp)
            _sp.loader.exec_module(_m)
            _dflt = _m.load()[0]["sem_weight"]
        except Exception:
            pass
        sem_weight = float(os.environ.get("RECALL_SEM_WEIGHT", _dflt))
    sem = sem or {}
    hits = []
    try:
        with open(CORPUS, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                low = line.lower()
                # a semantically close chunk is a candidate even with no shared word
                if not any(t in low for t in terms) and i not in sem:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("t", 0) < cutoff:
                    continue
                if project and r.get("p", "") != project:
                    continue
                m = r.get("m", "")
                ml = m.lower()
                score = sum(min(ml.count(t), 3) * weights[t] for t in terms)
                distinct = sum(1 for t in terms if t in ml)
                score *= (1 + 0.35 * (distinct - 1))
                score += sem_weight * sem.get(i, 0.0)
                if score:
                    when = time.strftime("%Y-%m-%d", time.localtime(r.get("t", 0)))
                    role = r.get("r", "u")
                    # a stated conclusion outranks the question that prompted it
                    if role == "a":
                        score *= 1.4
                    score = round(score, 1)
                    label = {"u": "said", "a": "concluded"}.get(role, "did")
                    hits.append((score, label,
                                 (r.get("p", "")[:28] + " " + when), "transcript", m))
    except Exception:
        return []
    hits.sort(key=lambda r: -r[0])
    seen, uniq = set(), []
    for h in hits:
        k = h[4][:80].lower()
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return uniq[:limit]


def corpus_messages(days=45, role=None, project=None):
    """Every corpus message in the window - what the ledger commands need, without
    touching a single raw transcript."""
    if not os.path.exists(CORPUS):
        return []
    cutoff = time.time() - days * 86400 if days else 0
    out = []
    try:
        with open(CORPUS, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("t", 0) < cutoff:
                    continue
                if role and r.get("r", "u") != role:
                    continue
                if project and project.lower() not in (r.get("p") or "").lower():
                    continue
                out.append(r)
    except Exception:
        return []
    return out


def status():
    if not os.path.exists(CORPUS):
        print("  no corpus yet - run: recall_index.py --build")
        return 1
    n = sum(1 for _ in open(CORPUS, encoding="utf-8", errors="replace"))
    manifest = load_manifest()
    files = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    raw = sum(os.path.getsize(f) for f in files)
    stale = 0
    for f in files:
        try:
            st = os.stat(f)
        except OSError:
            continue
        if manifest.get(f) != [int(st.st_mtime), st.st_size]:
            stale += 1
    size = os.path.getsize(CORPUS)
    print("  corpus    %8.1f MB   %d messages" % (size / 1024 / 1024, n))
    print("  raw       %8.0f MB   %d transcripts" % (raw / 1024 / 1024, len(files)))
    print("  ratio     %8.0fx less to scan per query" % (raw / max(size, 1)))
    print("  stale     %d file(s) awaiting extraction" % stale)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        return status()
    if a.build:
        return build(full=a.full)
    return status()


if __name__ == "__main__":
    sys.exit(main())
