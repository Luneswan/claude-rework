# Self-tuning, capture, and federation - the reasoning

Read this when changing `recall_tune.py`, `hooks/capture_events.py`, or
`recall_share.py`. Nothing here is needed to *use* the skill.

## It retunes itself as it is used

The corpus grows every session, so the right parameters drift. `--selftune`
regenerates known-item cases from the **current** corpus, sweeps the grid, and
keeps a change only when it beats the incumbent on generated questions **and**
does not regress the curated set. Either failure and the incumbent stands.

**Run it deliberately. It is not scheduled, and must not be.** One sweep launches
roughly a thousand child processes - 18 parameter combinations x 60 generated
cases x two suites. Wired into weekly maintenance it produced an unusable storm of
console windows on Windows and pinned the CPU until the processes were killed.

Unattended work has to be bounded and cheap: a single incremental pass, a few
seconds, one process. A grid search is none of those. The rule that fell out of
it: **never schedule anything whose cost scales with a parameter grid.**

Winners land in `recall_tuning.json`, never in the code, so a bad tune is one
`--reset` away. Environment variables still override everything, which is how the
test suite pins values while measuring.

### Hiding a console window on Windows is two separate fixes

`CREATE_NO_WINDOW` is **ignored** when combined with `DETACHED_PROCESS` or
`CREATE_NEW_CONSOLE` (documented, easily missed). And `python.exe` is a console
application, so Windows gives it a console whatever flags a windowless parent
passes. Both had to change: spawn through `pythonw.exe`, and pass
`CREATE_NO_WINDOW` plus a `STARTUPINFO` with `wShowWindow = SW_HIDE` to every
child a windowless parent creates.

The symptom outlived the fix by several minutes because an already-running sweep
kept spawning from the old code. **Verify a fix against a process started after
the fix**, or you will believe it failed and change something that was correct.

## Capture: what was DONE, not only what was said

A `PostToolUse` hook appends one line per real action to `events.jsonl`, and the
indexer groups bursts into activity records the corpus can search:

```
{"t": 1788259894, "k": "edit", "p": "webapp", "d": "src/net/fetcher.py"}
{"t": 1788259894, "k": "run",  "p": "webapp", "d": "pytest tests/ -q [redacted]"}
```

Transcripts hold the conversation, never the work. Ask "what did we change in the
router" of a transcript-only memory and it returns the *description* of a change.

Cost is a file append - no parsing, no model, no network - so this is capture
without capture overhead. Design constraints, in priority order:

1. **A hook must never break a turn.** Every path is wrapped; any exception exits
   0 and writes nothing. A memory feature that can fail a tool call is a bug
   generator, not a feature.
2. **Secrets never reach the log.** Commands are matched against a token pattern
   (`sk-`, `ghp_`, `hf_`, `xox*`, `AKIA`, `--password`, auth headers, and
   `*_TOKEN=`-style assignments) and the match is *replaced*, not escaped. Scrub
   before writing, never after.

   The header branch was `Authorization:\s*\S+`, which reads as obviously correct
   and leaked. In the standard `Authorization: Bearer <token>` form the single
   token it consumes is the **scheme**, and the credential survives verbatim; the
   `sk-` branch did not save it either, because the token began `sk9`. The pattern
   now consumes an optional known scheme *and* the credential.

   Two rules this produced: **a redaction pattern needs a test per credential
   FORM, not per credential type** - `Bearer`, `Basic`, `X-Api-Key`,
   `GITHUB_TOKEN=` are four shapes, and passing on three tells you nothing about
   the fourth. And **anchor keyword matching to the end of an identifier**
   (`*_TOKEN=` matches, `TOKENIZER_PATH=` does not), or the scrubber starts
   eating ordinary paths and people turn it off.
3. **Read-only shell noise is dropped** (`ls`, `cat`, `grep`, `echo`, ...). Those
   are how you look at work, not the work.
4. **The log is bounded** at 60k lines and 8 MB, oldest dropped first.
5. **Paths are relativised to the project** so a record stays meaningful when the
   tree moves, and the project name is the cwd basename - which is why events
   from a second, unrelated session appear tagged with that project's name.

## Learning across installations, without moving anyone's data

A card is about twenty numbers: parameters, benchmark scores, corpus and
vocabulary size, model name, a random per-install id. No prompts, answers, paths,
project names or note text - nothing from which any of it could be reconstructed.

Each install tunes on its own corpus; the cards let those results travel, so a
setting proven on a corpus unlike yours can be tried here and re-verified locally.
That is the training loop: **numbers travel, text stays home.**

### Three boundaries that are the point, not an oversight

**Publishing is a separate, explicit act.** `--export` writes a file and stops.
Nothing uploads on a schedule. A memory tool that phones home automatically is the
wrong tool no matter how good its retrieval is.

**A validator that can raise is not a boundary.** `card.get("params") or {}`
looks defensive and is not: a list is truthy, so it survives the `or` and the
next line calls `.get()` on it. One hostile card raised `AttributeError` from
inside the validator and aborted the entire pull, discarding the legitimate cards
alongside it - a denial of service written into the safety check. Check the
**type of every container** before reaching into it, and treat an exception at
the call site as a rejection rather than letting it propagate.

**A pulled card is untrusted input.** Every field is validated against expected
type and range before anything is read - `sem_weight` must be an `int` in `0..40`,
`first_div` in `1..10`, `taper` in `2..20`; not a string, not a bool, not a float
that happens to parse. A card whose parameter carries a shell fragment instead of
an integer is rejected outright, not coerced or "cleaned". Reject the whole card
on any bad field: partial acceptance is how a validator becomes a parser and a
parser becomes an exploit.

**Only numbers are ever adopted.** `--apply` writes integers into
`recall_tuning.json`. It cannot fetch or execute code. Code improvements travel
the ordinary way: a pull request a human reads. Auto-executing code pulled from
strangers is a supply-chain compromise wearing a helpful hat, and this skill will
not do it however convenient it sounds.

**Adopted is not trusted.** `--apply` prints the command to re-run the local
suite, because a parameter that won on someone else's corpus has proven nothing
about yours. Federation moves candidates, not conclusions.
