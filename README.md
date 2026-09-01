# recall

**Claude Code forgets everything between sessions. This makes it remember, without burning your context window.**

Your transcripts are already on disk. Every decision, every bug you chased for two
hours, every "we tried that, it didn't work" is sitting in `~/.claude/projects/`
in files nobody can read. Ask Claude what you decided last Tuesday and it either
guesses or re-reads half a gigabyte to find out.

`recall` turns that pile into something searchable in about half a second, and
answers in roughly 2,000 characters instead of 200,000.

```bash
git clone https://github.com/Luneswan/claude-recall
cd claude-recall
python install.py
```

That's it. It reads the transcripts you already have, builds an index, and starts
answering. No account, no API key, no server, no data leaving your machine.

---

## What it looks like

```
$ python ~/.claude/skills/recall/scripts/recall.py "what timeout did we agree on for the payment webhook" --budget 1500

== WHAT YOU SAID ==
  [18.2] billing-api  2026-02-14 / transcript
      what timeout did we settle on for the payment webhook

== WHAT WAS CONCLUDED ==
  [22.7] billing-api  2026-02-14 / transcript
      We set the payment webhook timeout to 12 seconds after measuring the
      provider's p99 at 9.4 seconds.
```

Twelve seconds. Found in 0.7s, cost about 400 tokens, and you never had to
remember which project it was in.

---

## The numbers

Measured on a real installation: 1,421 transcript files, 7.4 GB, 19,426 indexed
messages.

### What an answer costs

Five questions with a known-correct answer, run three ways:

| approach | tokens | gets it right | verdict |
|---|---:|---|---|
| paste the session into context | 26,539,949 | yes | a 101 MB transcript. Not physically possible |
| `grep` notes and transcripts | 211,627 | yes | correct and unaffordable |
| **recall** | **2,552** | yes | **83× cheaper than grep** |

### Speed

| operation | time |
|---|---|
| a query | **0.63–0.75s** |
| first index build (7.4 GB, 1,421 files) | 33s |
| incremental refresh | under a second |
| embedding 19,426 chunks | 4s |
| encoding one query | 0.109s |

Before the index existed, a single query took **158 seconds** and a six-question
benchmark timed out at ten minutes. Extracting once and searching that is the
whole trick.

### Accuracy

Seven suites, each with a floor. The run fails if any of them drops below it.

| suite | result | what it proves |
|---|---|---|
| known-item | **300/300 (100%)** | retrieval on questions generated *from your corpus* |
| curated | **12/12** | hand-written cases, zero silent fallbacks |
| stress | **19/19** | empty input, CJK, RTL, shell metacharacters, a 3,000-character word |
| subcommands | **11/11** | every command runs clean |
| capture | **33/33** | the hook records work, drops noise, redacts secrets |
| vectors | **6/6** | a stale or misaligned index is refused, never guessed at |
| federation | **28/28** | hostile input rejected without crashing |
| foreign machines | **4/4 at 100%** | tiny, huge, non-English and sparse corpora |
| optimizer | **100/100 clean** | no file lost, no action below the evidence threshold |

Run them yourself: `python ~/.claude/skills/recall/tests/run_tests.py`

**The known-item suite is generated from your own data, not written by hand.** It
samples a chunk, builds a question out of that chunk's words, holds back the most
distinctive word so nothing passes by exact match, and demands the chunk back.
Twelve cases I wrote by hand scored 100% while sixty generated ones scored 76.7%.
The gap was me overfitting to my own imagination, and I only saw it because the
generated set existed.

---

## How it compares

### Against other memory and token skills

Every one of these was installed on the machine recall was built on. The counts
come from the filesystem, not from memory.

| skill | files | executable code | tests | searches your transcripts | works offline |
|---|---:|---:|---:|---|---|
| `context-budget` | 1 | 0 | 0 | no | n/a |
| `token-budget-advisor` | 1 | 0 | 0 | no | n/a |
| `rescue-tokens` | 2 | 0 | 0 | no | n/a |
| `token-optimization` | 8 | 1 | 2 | no | n/a |
| `long-context-lost-in-the-middle` | 1 | 0 | 0 | no | n/a |
| `mem-search` | 1 | 0 | 0 | no | n/a |
| `smart-explore` | 1 | 0 | 0 | no | n/a |
| `timeline-report` | 1 | 0 | 0 | no | n/a |
| `mempalace` | 1 | 0 | 0 | no | n/a |
| `claude-mem` (plugin) | n/a | 7 | 0 | yes, via MCP | needs its server |
| **recall** | **15** | **10** | **7 suites, 400+ cases** | **yes** | **yes** |

Most of that list is advice. They are well-written documents telling Claude to be
careful with context, and a document cannot search 7 GB of transcripts or tell you
whether it worked. `claude-mem` is the one genuinely comparable project and it
takes a different bet: an MCP server, which is real engineering but also a
permanent line item in your context window, because MCP tool schemas load before
you type a word.

**This is not a claim that those skills are bad.** Several of them taught me
things, and recall absorbs what each did well: `--budget-report` is what
`context-budget` did, `--estimate` is `token-budget-advisor`, `--timeline` is
`timeline-report`. The argument is narrower. One tested program beats nine
overlapping documents, because loading several memory skills at once is precisely
the waste each of them warns you about.

### Against the obvious alternatives

| | grep | a RAG service | `/compact` | recall |
|---|---|---|---|---|
| finds a decision from 3 months ago | yes, unaffordably | yes | no, it is gone | yes |
| cost per answer | ~211k tokens | API calls | free but lossy | ~2.5k tokens |
| your data leaves the machine | no | **yes** | no | no |
| needs a key or an account | no | yes | no | no |
| tells you when it is wrong | no | rarely | n/a | yes, refuses stale indexes |
| works on a plane | yes | no | yes | yes |

---

## Why it works

Four ideas, each measured before it was kept.

**1. Extract once, search forever.** Raw transcripts are 7.4 GB of JSON, most of
it tool output. The part that answers a question is what people typed, plus the
minority of Claude's replies that state a conclusion. Pulled out once, that is
11.7 MB. Same answers, 158s down to 0.33s.

**2. Rank across stores, not one at a time.** recall searches your notes, your
skills, an optional code graph and your transcripts in a single pass and ranks
them together. Searching notes first and stopping sounds principled and scored
worse, because a weak note from an unrelated project displaces the line that
actually holds the answer. Store priority is a weight, not an order.

**3. Score density, not word count.** A 6,000-character note matching two filler
words used to beat the 600-character chunk holding the answer. Dividing by the
square root of length and capping per-term counts took accuracy from 42% to 75%
by itself. Whenever two things of different sizes compete, check the scores are
even comparable before tuning anything else.

**4. Semantic search that admits, but does not decide.** "Why was the router
broken" is answered by "bash ate the backslashes in the interpreter path", which
shares no words with the question. Static embeddings close that gap for a one-time
36 MB download, no GPU and no API. They let a chunk into the running without a
shared word, but it still has to win on the combined score. Weighted too heavily,
semantic similarity returns things *about* your topic instead of things that
*answer* the question.

---

## What you get

```bash
R=~/.claude/skills/recall/scripts/recall.py

python $R "<question>" --budget 2000   # search everything, ranked, bounded
python $R --brief --days 2             # what was asked, what got done, what is open
python $R --handoff                    # what must survive a compact
python $R --decisions --days 30        # a decision ledger
python $R --digest --weeks 4           # per-week rollup
python $R --timeline --days 7          # by day, across projects

python $R --write "<fact>" --name <slug> --type project|user|feedback|reference

python $R --budget-report              # what every session costs before you type
python $R --estimate "@file.md"        # input tokens and likely response size
python $R --gc                         # stale and duplicate notes (never deletes)
python $R --optimize [--apply]         # promote/demote skills from measured usage
```

`--brief` is the one people keep. Re-reading a session to work out where you were
costs 30,000–80,000 tokens. Deriving it from the index costs about 600 and half a
second, and it says plainly that it is a heuristic rather than pretending to
certainty.

`--budget-report` found four image-generation skills on my machine costing about
950 tokens *every session* for something I used monthly. Moving them to a library
tier cut the fixed cost of a session by 27%, and they stayed one search away.

---

## Capture: what you did, not just what you said

Transcripts record the conversation. They do not record the work. Ask "what did we
change in the router" and a transcript-only memory hands you the *description* of
a change.

An optional hook appends one line per real edit or command:

```json
{"t": 1788259894, "k": "edit", "p": "webapp", "d": "src/net/fetcher.py"}
{"t": 1788259894, "k": "run",  "p": "webapp", "d": "pytest tests/ -q [redacted]"}
```

It costs a file append. No parsing, no model, no network. Read-only noise like
`ls` and `cat` is dropped, the log is capped, and commands are scrubbed against a
secret pattern before anything is written.

That scrubber had a real bug, found by the test suite in this repo.
`Authorization:\s*\S+` eats one token after the colon, and in
`Authorization: Bearer <token>` that token is the word "Bearer", so the
credential went to disk in the clear. It now takes the scheme *and* the value, and
there is a test per credential shape so the next form does not slip through.

Skip the hook entirely with `python install.py --no-hooks`.

---

## Privacy

Your data does not move. No telemetry, no phone-home, no account.

The only feature that touches the network is opt-in parameter sharing, and it
sends about twenty integers:

```json
{"schema": 1, "machine": "9f2c4a1b77de",
 "params": {"sem_weight": 12, "first_div": 2, "taper": 6},
 "scores": {"known_item": 0.99, "curated": 1.0},
 "corpus": {"chunks": 19426, "vocab": 84210}}
```

No prompts, no answers, no file paths, no project names, no note text. The machine
id is a random local salt, not a hostname or a username.

Three boundaries that are the point rather than an oversight:

- **`--export` writes a file and stops.** Nothing uploads on a schedule. A memory
  tool that phones home automatically is the wrong tool no matter how good its
  retrieval is.
- **A pulled card is untrusted input.** Every field is checked against a type and
  a range, the whole card is rejected on any bad field, and a hostile card cannot
  crash the import and take the good ones down with it.
- **Only integers are ever adopted.** It cannot fetch or run code. Code travels
  the ordinary way, as a pull request a human reads, because auto-executing code
  pulled from strangers is a supply-chain compromise wearing a helpful hat.

---

## Requirements

- **Python 3.9+ and Claude Code.** That is the hard requirement.
- **`numpy` and `model2vec` are optional.** With them you get semantic ranking.
  Without them recall falls back to lexical scoring and still works. Install with
  `pip install numpy model2vec`. The model is a one-time 36 MB download and
  everything after that is offline.
- **graphify is not required.** If you happen to keep a code graph in a project,
  recall uses it as one more store. If you do not, that store is skipped and
  nothing else changes. This is tested rather than asserted: the suite runs with
  graphify absent from `PATH`, then again with a graph directory present but no
  binary installed, and both have to come back clean.
- Windows, macOS and Linux. Built and tested on Windows, which is the fussiest of
  the three about hook paths.

---

## Uninstall

```bash
python install.py --uninstall
```

Removes the skill and the hook, restores `settings.json`, and leaves your index
and notes alone so you can reinstall without rebuilding. It prints exactly which
files it left behind.

---

## Honest limitations

- **The corpus is only as good as your transcripts.** A fresh Claude Code install
  has nothing to remember, and recall will tell you so rather than inventing
  something.
- **`--brief` is a heuristic.** It decides a request is "done" by checking whether
  a later message reads like a conclusion about the same thing. It is right most
  of the time and it says out loud that it is guessing.
- **Parameter sharing has never met a second real machine.** The validator is
  tested against 28 hostile cards. Two installs actually converging is unproven.
- **Every threshold was fitted on one person's corpus.** That is why
  `simulate.py` exists: it builds synthetic machines whose vocabularies share
  nothing with mine. It found a real bug on its first honest run. An IDF floor of
  `0.3` meant a word appearing in *every* record still scored, which is invisible
  on a diverse corpus and ruinous on a small one. Four synthetic machines went from
  44/64/88/92% to 100%.

If you find something wrong, the tests are in the repo and they take about four
minutes.

---

## License

MIT. See [LICENSE](LICENSE).
