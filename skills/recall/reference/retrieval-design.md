# Why recall retrieves the way it does

Read this when changing the ranker, the corpus, or the budget allocator. It is the
measurement trail behind every constant in `recall.py` and `recall_index.py`.
Nothing here is needed to *use* the skill.

## Extract once, search forever

A recall tool that scans raw history per query does not scale and will quietly
become unusable. Measured here: 7.4 GB of transcripts across 1,400 files, two
single sessions over 1.7 GB each, up to 6.6 GB touched per question. One query
took 158 seconds; a six-question benchmark timed out at 600.

The content that answers a recall question is a rounding error of that volume -
human-typed messages only. Extract them once into a flat corpus and search that:

- one line per message, capped length, keyed by source file and mtime
- refresh incrementally by comparing `(mtime, size)` against a manifest
- **append per file and save the manifest each time**: a first build over
  gigabytes must be resumable and queryable *while it runs*, not only after
- keep a capped live-scan fallback so a missing corpus degrades speed, not use

Result on this machine: 1.2 MB corpus, 158s -> 0.33s, identical output. Verify
that last part - if the extract changes the answers, the filter is wrong, not the
approach.

### Cap the query too

A pasted 5,000-character question produced hundreds of search terms, each scanned
against every candidate line: 18.6s for zero extra recall. Deduplicate terms, drop
stopwords, and cap the list (12 works). More terms is not more recall.

### Measure your own tool before claiming it is efficient

The report that found a 950-token skill was itself counting only ~5% of the real
fixed cost - it measured skill descriptions and ignored custom agents and MCP tool
schemas, which a real context breakdown showed were 10.1k and 8.4k against 9.8k of
skills. An optimizer blind to the largest line item will confidently trim the
smallest one. Compare against ground truth from the host before trusting it.

## Index both sides, and only the human side

A corpus of user messages answers "what did I ask about X" but not "what did we
conclude about X" - which is the question people actually have. Index assistant
turns too, but filtered: most are narration, and the valuable minority states a
finding, a cause, or a decision. Keyword-gate on that vocabulary, tag the role,
and weight a conclusion above the question that prompted it (1.4x works).

Result here: 3,018 -> 9,742 messages, corpus 1.2 -> 5.2 MB, recall time unchanged.

### The user channel is not all user

Hook feedback, tool-permission notices, resume banners and task notifications all
arrive on the "user" channel. Indexed naively, "what did I ask for" answers with
machine chatter - it surfaced Korean Stop-hook text as a top open thread here.
Filter by prefix *and* by substring over the first few hundred characters
("hook additional context:", "<task-notification>", "<system-reminder>"). 102 of
9,844 messages were noise; all 102 were machine text.

### Derive the brief, do not re-read the chat

Re-reading a session to answer "where were we" costs 30k-80k tokens. The same
answer from the corpus costs ~600 tokens in half a second: classify each request
in the window as addressed or open by checking whether a later conclusion echoes
its distinctive words *and* reads as completion. Say plainly that it is heuristic.
Inject the top few open threads at session start so every session begins oriented.

Every derived view - decisions, digest, timeline, handoff, brief - must read the
corpus, never the raw files. Leaving one on raw transcripts cost 10-17s per call
while the search path next to it ran in 0.3s.

## Measured against the alternatives

Five questions with a known-correct term, run against every realistic method:

| method | tokens | correct | note |
|---|---|---|---|
| read the session | 26,539,949 | 5/5 | a 101 MB transcript; not actually possible |
| grep notes + transcripts | 211,627 | 5/5 | correct and unaffordable |
| **recall.py** | **2,552** | **4/5** | 83x fewer tokens than grep, 2.6s total |

A 5-question set flattered it. On **12 questions** the same build scored **5/12
(42%)**. Small eval sets do not measure, they reassure - if each case is worth
20% of the score, a lucky pair looks like success.

Report the accuracy number, not only the savings. A retrieval tool that is 100x
cheaper and half as accurate is worse, and the first version of this one was
exactly that (2/5). Three changes moved it 2/5 -> 4/5:

1. **Rank across stores, not by store.** Spending the budget on curated notes
   first sounds principled and measured badly - a weak note from an unrelated
   project displaced the line holding the answer. Store priority is a weight
   (1.6 notes, 1.3 graph, 1.15 skills, 1.0 transcripts), not an ordering.
2. **Chunk, do not truncate.** A 600-char cap silently discarded content in 41%
   of messages, and the detail that answers a question is rarely in the first
   paragraph. Chunking with an 80-char overlap took one term from 0 occurrences
   to 14. Corpus 5.2 -> 11.3 MB; query time unchanged.
3. **Reverting what did not work.** Pseudo-relevance feedback - expand the query
   with vocabulary from the top hits - is a standard trick and made this *worse*
   (4/5 -> 2/5): common feedback words outvoted the rare term that mattered. It
   is commented out in the code with the measurement, so nobody adds it again.

### Normalise scores before comparing across stores

The largest single accuracy fix, worth **42% -> 75%** on the 12-case set, was not
a ranking idea at all - it was noticing that the scores being compared were not
comparable. Raw term counts reward length: a 6,000-character note matching two
filler words scored 23, while the 600-character chunk holding the answer scored
13, so an unrelated note won every query.

Score density, not count:

```
raw      = sum(min(count(term), 4) for term in query)
density  = raw / max(1, (len(text) / 600) ** 0.5)
score    = density * (1 + 0.5 * (distinct_terms - 1))
```

Cap per-term counts so one repeated word cannot dominate, divide by the square
root of length so long documents stop winning by being long, and reward breadth
of distinct terms over depth of one. Whenever two stores hold items of different
sizes, check that their scores are on the same scale before tuning anything else.

IDF weighting was added at the same time and moved the number **not at all**
(5/12 both before and after). Worth keeping - it is correct - but the lesson is
that fixing the wrong layer produces a clean, principled, useless change.

### Breaking the lexical ceiling with static embeddings

75% was the lexical wall. Static embeddings (model2vec) cross it for a 36 MB
one-time download, no GPU, no API, no per-query model call - token vectors are
looked up and averaged, so encoding is a numpy operation.

Measured, and model size decided it:

| model | dim | sem weight 0 | 12 | 20-25 |
|---|---|---|---|---|
| potion-base-8M | 256 | 83% | 83% | 58% |
| **potion-base-32M** | 512 | 83% | **92%** | 92% |

The 8M model produced *no gain at any weight* - it was not that hybrid ranking
was wrong, it was that the model was too weak to carry signal. Do not conclude an
approach fails until you have tried a model that can actually do the task. And do
not over-weight it: at 25 the 8M model dropped accuracy to 58%, because semantic
similarity untethered from term matching retrieves things that are *about* the
topic instead of things that *answer* the question.

Two rules that made it safe:

- **Semantic admits candidates, lexical still scores them.** A chunk with no
  shared word can enter the pool on similarity alone, but it competes on the
  combined score.
- **Vectors are addressed by corpus line index, so a rebuild reorders them.**
  A stale vector file is worse than none: it silently scores against text that no
  longer exists. See "Trusting a partial matrix" below.

Also tried and rejected: a term co-occurrence model built from this corpus. It
learned that "router" travels with one project's client name and "recall" with another's internal jargon,
because the corpus spans unrelated projects. Cross-project co-occurrence is noise,
not meaning.

### The encoder does not need the library

`model2vec`'s own `encode()` took 5.18s per query, almost all of it import and
model construction. The model is a lookup table: a vocabulary and an embedding
matrix. Memory-mapping `embedding.npy` and reading `tokenizer.json` directly gives
the same vectors - verified cosine **1.000000** against the library - in **0.109s**.

When a dependency is slow, check whether you are paying for machinery you do not
use. Keep the library path as the fallback, and keep a test that asserts the two
agree, or the fast path will silently drift.

### Trusting a partial matrix

The first alignment guard compared matrix rows against corpus lines: equal or
nothing. Correct, and wasteful - the corpus is append-mostly (records from
unchanged files are written first, changed ones re-extracted onto the tail), so
growth alone does not invalidate the rows already embedded. Capture made the
corpus churn faster than the heal window, and all-or-nothing meant semantic
scoring was off most of the time.

`_coverage()` replaces the boolean with three states, and *verifies* prefix
stability rather than assuming it:

```
current  size and sha match the build       -> use every row
prefix   first `bytes` bytes still hash to sha, and hold exactly `n` lines
                                            -> use those rows, tail is lexical
stale    anything else                      -> use nothing, queue a rebuild
```

Two measurements decided the design. Hashing the whole 12 MB corpus costs
**0.020s**, so exactness was never worth trading for a length check. And the
check as a whole costs **21ms**, about 3% of a 700ms query.

**The line count is a separate invariant from the hash.** A prefix can hash
correctly and still contain a different number of lines than the matrix has rows,
and then row i no longer describes line i. Assert both.

**Deriving the digest from a second read is a race, not a style choice.**
Embedding takes ~5s and maintenance rebuilds the corpus every few minutes. When
`build()` read the corpus for `_texts()` and re-read it for the digest, a rebuild
landing in between wrote a meta describing a corpus the vectors were not built
from - which `_coverage()` then certified as *current*. Observed live: 17,901 rows
carrying the digest of a 19,179-line corpus. The old row-count check had been
protecting against this by accident; the optimisation removed the accident.

Fix: one read, and both the texts and the digest derived from the same bytes.
Whenever a file's content and a fingerprint of that content must agree, compute
them from a single read or they will eventually disagree.

### Parallel work must not fork

`model2vec.encode()` defaults to joblib multiprocessing. Under `pythonw.exe` there
is no console for the workers to attach to, so they die with `TerminatedWorkerError`
- and the parent still **exits 0**. A self-healing rebuild "ran" hourly for hours
and healed nothing, silently. `use_multiprocessing=False` fixed it and was also
faster on this workload (4.6s), because the corpus is small enough that fork
overhead dominates.

Any background task must fail loudly or be checked by its effect, never by its
exit code.

### The honest ceiling

**12/12 (100%)** with hybrid ranking plus a per-item output cap.

The last case was not a retrieval failure at all. The chunk holding the answer was
being retrieved at semantic rank 16 - correctly - and then never printed, because
four verbose items ahead of it consumed the entire 2,000-character budget. The fix
was in *selection*, not search: cap any single item at `budget // 5` and skip
near-duplicate chunks, so the budget buys breadth of distinct evidence instead of
depth of the first hit.

Diagnose where a miss actually happens before tuning the ranker. "Not in the
answer" can mean not retrieved, not ranked, or not printed - and only one of those
is a search problem.

**A fail-open import will hide all of this.** A syntax error in the corpus module
made every command still print "ok" - the try/except fell back to a capped live
scan and said nothing. Any fallback path must announce itself, or your benchmark
measures the fallback while you believe you are tuning the real thing.

### Question shape is a ranking signal

A "why did X happen" question and a "how many X" question want different chunks
even when they share every content word. Detect the shape from the interrogative
and boost chunks carrying the matching vocabulary (`because`, `cause`, `reason`
for cause; digits and units for quantity; `decided`, `chose`, `instead` for
decision). Worth 1.6x on the matching class, and it is what closed the last gap on
the generated set without touching the lexical scorer.
