#!/usr/bin/env python3
"""recall_embed - semantic scoring for recall, offline and free.

Lexical matching tops out near 75% on this machine's benchmark because the answer
often shares almost no words with the question: "why was the skill router not
working" is answered by "the hook was dead because bash ate the backslashes".

Static embeddings (model2vec potion-base-8M, 256-dim) close that gap without a
GPU, an API, or a per-query model call: token vectors are looked up and averaged,
so encoding is a numpy operation. One ~30 MB download, then everything is local.

  recall_embed.py --build      embed the corpus (skips when already current)
  recall_embed.py --status     vectors, dimensions, staleness
  recall_embed.py --test "q"   nearest chunks for a query

Degrades to silence: if the model or vectors are missing, semantic_scores()
returns an empty mapping and recall falls back to pure lexical ranking.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
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
CORPUS = os.path.join(CLAUDE, "recall_corpus.jsonl")
VECS = os.path.join(CLAUDE, "recall_corpus.vec.npy")
META = os.path.join(CLAUDE, "recall_corpus.vec.meta.json")
MODEL = os.environ.get("RECALL_EMBED_MODEL", "minishlab/potion-base-32M")
FAST_DIR = os.path.join(CLAUDE, "recall_model")
FAST_EMB = os.path.join(FAST_DIR, "embedding.npy")
FAST_TOK = os.path.join(FAST_DIR, "tokenizer.json")

_model = None
_matrix = None


def get_model():
    global _model
    if _model is None:
        from model2vec import StaticModel
        _model = StaticModel.from_pretrained(MODEL)
    return _model


def export_fast():
    """Loading the full StaticModel costs ~5s per process - it reads a 129 MB
    embedding matrix into RAM to encode one short query. Export the matrix and the
    tokenizer once; queries then memory-map the matrix and touch only the rows for
    their own tokens. Verified to reproduce model2vec's own output exactly
    (cosine 1.000000), because encoding here is mean-pooling of token vectors."""
    import numpy as np
    m = get_model()
    os.makedirs(FAST_DIR, exist_ok=True)
    np.save(FAST_EMB, np.asarray(m.embedding, dtype="float32"))
    m.tokenizer.save(FAST_TOK)
    print("  fast path: %s (%.0f MB) + tokenizer"
          % (os.path.basename(FAST_EMB), os.path.getsize(FAST_EMB) / 1024 / 1024))
    return 0


_fast = None


def _fast_encode(text):
    """Query vector without loading the model. None if the fast path is missing."""
    global _fast
    if _fast is False:
        return None
    if _fast is None:
        try:
            import numpy as np
            from tokenizers import Tokenizer
            _fast = (np.load(FAST_EMB, mmap_mode="r"), Tokenizer.from_file(FAST_TOK))
        except Exception:
            _fast = False
            return None
    import numpy as np
    emb, tok = _fast
    ids = tok.encode(text, add_special_tokens=False).ids
    if not ids:
        return None
    v = np.asarray(emb[ids], dtype="float32").mean(axis=0)
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _read_corpus():
    """Read the corpus ONCE and derive both the texts and the digest from the same
    bytes.

    Reading it twice is a race, not a style choice. Embedding takes ~5s and
    maintenance rebuilds the corpus every few minutes; a rebuild landing in that
    window produced a meta file describing a corpus the vectors were not built
    from, which _coverage() then certified as current - misaligned vectors scoring
    the wrong chunks, silently. Observed live: 17,901 rows carrying a digest for a
    19,179-line corpus.

    Returns (texts, size_bytes, sha256) where len(texts) is exactly the number of
    lines in those bytes, so row i always describes line i.
    """
    import hashlib
    with open(CORPUS, "rb") as fh:
        raw = fh.read()
    sha = hashlib.sha256(raw).hexdigest()
    lines = raw.decode("utf-8", "replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()                 # exactly reproduces text-mode line iteration
    out = []
    for line in lines:
        try:
            out.append(json.loads(line).get("m", ""))
        except Exception:
            out.append("")
    return out, len(raw), sha


def _texts():
    return _read_corpus()[0]


def build(force=False):
    import numpy as np
    if not os.path.exists(CORPUS):
        print("  no corpus - run recall_index.py --build first")
        return 1
    cm = os.path.getmtime(CORPUS)
    if not force and os.path.exists(META) and os.path.exists(VECS):
        try:
            meta = json.load(open(META, encoding="utf-8"))
            if abs(meta.get("corpus_mtime", 0) - cm) < 1:
                print("  vectors already current (%d)" % meta.get("n", 0))
                return 0
        except Exception:
            pass
    texts, size, sha = _read_corpus()
    print("  embedding %d chunks with %s ..." % (len(texts), MODEL))
    t0 = time.time()
    # use_multiprocessing=False is required, not an optimisation: model2vec farms
    # batches out through joblib, and joblib workers cannot spawn under
    # pythonw.exe (no console) - every windowless background rebuild died with
    # TerminatedWorkerError while reporting success. Single-process embeds 19k
    # chunks in ~6s anyway, so the pool bought nothing at this size.
    vecs = np.asarray(get_model().encode(texts, show_progress_bar=False,
                                         use_multiprocessing=False),
                      dtype="float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    np.save(VECS, vecs / norms)
    json.dump({"n": len(texts), "model": MODEL, "corpus_mtime": cm,
               "bytes": size, "sha": sha},
              open(META, "w", encoding="utf-8"))
    export_fast()
    print("  %d vectors, dim %d, %.1f MB, in %.0fs"
          % (vecs.shape[0], vecs.shape[1],
             os.path.getsize(VECS) / 1024 / 1024, time.time() - t0))
    return 0


def _load():
    global _matrix
    if _matrix is None:
        import numpy as np
        try:
            _matrix = np.load(VECS)
        except Exception:
            _matrix = False
    return _matrix


def _digest(nbytes=None):
    """(size, sha256) of the corpus, or of its first nbytes. Hashing all 12 MB
    measures at 0.02s, so the exactness is close to free - there is no reason to
    settle for a length check and hope."""
    try:
        size = os.path.getsize(CORPUS)
        want = size if nbytes is None else min(nbytes, size)
        import hashlib
        h = hashlib.sha256()
        read = 0
        with open(CORPUS, "rb") as fh:
            while read < want:
                block = fh.read(min(1 << 20, want - read))
                if not block:
                    break
                read += len(block)
                h.update(block)
        return size, h.hexdigest()
    except Exception:
        return -1, ""


def _digest_prefix(want):
    """(sha256, line_count) of the corpus's first `want` bytes. The line count is
    the invariant that matters: vectors are addressed by line index, so a matching
    hash over a prefix holding a different number of lines is still unusable."""
    try:
        import hashlib
        h = hashlib.sha256()
        lines = 0
        read = 0
        with open(CORPUS, "rb") as fh:
            while read < want:
                block = fh.read(min(1 << 20, want - read))
                if not block:
                    break
                read += len(block)
                h.update(block)
                lines += block.count(b"\n")
        return h.hexdigest(), lines
    except Exception:
        return "", -1


def _coverage(matrix):
    """How much of the corpus these vectors can still be trusted for.

    Vectors are addressed BY LINE INDEX, so a stale file does not merely miss -
    it scores the wrong chunk. But the corpus is built prefix-stable: records
    from unchanged files are written first and new ones appended, so growth
    alone does not invalidate the rows already embedded.

    Verify that rather than assume it. If the first `bytes` bytes still hash to
    what was recorded at build time, every embedded row still describes the line
    it is indexed by, and the un-embedded tail simply competes on lexical score.
    Partial semantic beats none, which is what an all-or-nothing check gave
    during the minutes between maintenance passes.

      ("current", rows)  vectors describe the whole corpus
      ("prefix",  rows)  first `rows` lines verified; tail is lexical-only
      ("stale",   0)     prefix changed or shrank - trust nothing
    """
    try:
        meta = json.load(open(META, encoding="utf-8"))
        rows, want, sha = meta["n"], meta["bytes"], meta["sha"]
    except Exception:
        return "stale", 0                      # pre-digest meta, or none at all
    if rows != matrix.shape[0]:
        return "stale", 0                      # matrix and meta disagree
    size, _ = _digest(0)
    if size < want:
        return "stale", 0                      # corpus shrank: full rebuild
    head, nlines = _digest_prefix(want)
    if head != sha:
        return "stale", 0                      # the covered prefix changed
    if nlines != rows:
        return "stale", 0                      # row i must describe line i
    return ("current" if size == want else "prefix"), rows


def semantic_scores(query, top=400):
    """{corpus_line_index: cosine} for the most similar chunks. Empty when the
    model or vectors are unavailable or stale, so callers degrade to lexical."""
    m = _load()
    if m is False or m is None:
        return {}
    state, rows = _coverage(m)
    if state == "stale":
        # Heal instead of degrade. The corpus is rebuilt by maintenance every few
        # minutes, so "stale" is the normal state between passes, not an error -
        # warning about it forever means semantic scoring is quietly off most of
        # the time. One bounded background rebuild (~6s, one process), rate-limited
        # so a burst of queries cannot start a swarm.
        _heal()
        print("  (vectors stale - semantic scoring skipped this query; a rebuild "
              "was queued)", file=sys.stderr)
        return {}
    if state == "prefix":
        # The embedded rows still describe the lines they index; only the appended
        # tail is uncovered, and it competes on lexical score alone. Queue the
        # rebuild, but answer this query with the semantics we can prove.
        _heal()
    try:
        import numpy as np
        q = _fast_encode(query)
        if q is None:
            q = np.asarray(get_model().encode([query]), dtype="float32")[0]
            q = q / (float(np.linalg.norm(q)) or 1.0)
        sims = m @ q
        k = min(top, sims.shape[0])
        idx = np.argpartition(-sims, k - 1)[:k]
        return {int(i): float(sims[i]) for i in idx if sims[i] > 0.02}
    except Exception:
        return {}


_HEAL_STAMP = os.path.join(CLAUDE, "recall_corpus.vec.healing")


def _heal():
    """Queue exactly one background re-embed, at most once every few minutes."""
    try:
        last = os.path.getmtime(_HEAL_STAMP) if os.path.exists(_HEAL_STAMP) else 0
    except OSError:
        last = 0
    if time.time() - last < 240:
        return
    try:
        open(_HEAL_STAMP, "w").write(str(time.time()))
    except Exception:
        return
    try:
        import subprocess
        exe = sys.executable
        if os.name == "nt":
            cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(cand):
                exe = cand
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        subprocess.Popen([exe, os.path.abspath(__file__), "--build"],
                         creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, close_fds=True)
    except Exception:
        pass


def status():
    if not os.path.exists(VECS):
        print("  vectors: missing - run recall_embed.py --build")
        return 1
    import numpy as np
    m = np.load(VECS, mmap_mode="r")
    try:
        meta = json.load(open(META, encoding="utf-8"))
    except Exception:
        meta = {}
    corpus_n = (sum(1 for _ in open(CORPUS, encoding="utf-8", errors="replace"))
                if os.path.exists(CORPUS) else 0)
    print("  shape  : %s   %.1f MB" % (m.shape, os.path.getsize(VECS) / 1024 / 1024))
    print("  model  : %s" % meta.get("model", "?"))
    state, rows = _coverage(m)
    label = {"current": "(current)",
             "prefix": "(prefix verified - tail is lexical-only until rebuild)",
             "stale": "(STALE - not used; rebuild)"}[state]
    print("  corpus : %d lines; vectors cover %d %s"
          % (corpus_n, rows if state != "stale" else meta.get("n", 0), label))
    return 0


def test(q):
    scores = semantic_scores(q, top=6)
    if not scores:
        print("  no vectors available")
        return 1
    lines = open(CORPUS, encoding="utf-8", errors="replace").read().splitlines()
    for i, s in sorted(scores.items(), key=lambda kv: -kv[1])[:6]:
        try:
            m = json.loads(lines[i]).get("m", "")
        except Exception:
            m = ""
        print("  %.3f  %s" % (s, m[:150]))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--test")
    ap.add_argument("--export-fast", action="store_true")
    a = ap.parse_args()
    if a.build:
        return build(force=a.force)
    if a.export_fast:
        return export_fast()
    if a.test:
        return test(a.test)
    return status()


if __name__ == "__main__":
    sys.exit(main())
