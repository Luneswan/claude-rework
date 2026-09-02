# recall

**Claude forgets everything between sessions. This makes it remember, without burning your context window.**

Install it once. After that you never type a command: ask Claude a question about
your own past work, in plain English, and the answer is already in front of it.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/Luneswan/claude-recall/main/install.py | python3 -
```

**Windows (PowerShell)**

```powershell
iwr -useb https://raw.githubusercontent.com/Luneswan/claude-recall/main/install.py | python -
```

Or clone it and run `python install.py`, which is the same thing with the source
in front of you first.

No account, no API key, no server, nothing leaves your machine. It works
everywhere Claude Code runs - the terminal, the VS Code and JetBrains extensions,
and the desktop app - because it installs into `~/.claude`, which all of them
read.

---

## What actually happens after you install

Your transcripts are already on disk. Every decision, every bug you chased for two
hours, every "we tried that, it didn't work" sits in `~/.claude/projects/` in
files nobody reads. recall indexes them and wires four hooks so the index is used
on its own.

| when | what runs | what you get |
|---|---|---|
| you open a session | `SessionStart` | the threads still open from the last few days |
| you send a message | `UserPromptSubmit` | **only if you asked about the past**, the answer is looked up and handed to Claude |
| Claude edits or runs something | `PostToolUse` | a one-line record of the actual work |
| context fills and compaction fires | `PreCompact` | the decisions are saved to disk first, so the summary cannot lose them |

The second one is the point. You type:

> **you:** didn't we already fix the webhook timeout?

and before Claude sees your message, recall has searched 19,000 messages of your
own history locally and prepended the answer. Claude replies from what you
actually decided instead of guessing.

It only fires on prompts *shaped* like questions about the past. "Add a button"
triggers nothing, because injecting history into new work is exactly the waste
this tool exists to prevent. Output is capped at ~1,200 characters and debounced.

**Nothing to remember, nothing to type.** The commands further down still exist
if you want them, but the tool is designed so you never need one.

---

## The one thing worth understanding

There are two ways a tool can give Claude memory, and they cost very differently.

- **An MCP server** publishes tool schemas that load into your context **before
  you type a word**, every session, whether you use them or not.
- **A hook** costs nothing until it fires, and this one fires only on the prompts
  that need it.

recall uses hooks for Claude Code. That is the whole design argument: a memory
tool that permanently enlarges your context is charging you rent to save you
money. (The desktop app cannot run hooks, so for that there is an MCP server;
see below.)

---

## Using the Claude desktop app or Cowork

The desktop app cannot run hooks, so recall ships an MCP server. `install.py`
prints the exact config at the end, or:

```bash
python install.py --mcp-config
```

Paste it into `claude_desktop_config.json` and restart the app:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "recall": {
      "command": "/path/to/python",
      "args": ["/Users/you/.claude/recall_mcp/recall_mcp.py"]
    }
  }
}
```

Claude then calls these itself when you ask about the past: `recall_search`,
`recall_brief`, `recall_decisions`, `recall_timeline`, `recall_write`. Five tools,
kept terse on purpose, because their schemas are the context cost described above.

The server has no dependencies. MCP over stdio is newline-delimited JSON-RPC,
which is a page of standard library, and a memory tool that makes you
`pip install` a framework before it starts is a tool people abandon during setup.

---

## What it saves you, honestly

This is the question people actually have, so here is what is measured and what
is not.

**Measured on this machine:** answering one question about past work.

| approach | tokens | correct |
|---|---:|---|
| paste the session into context | 26,539,949 | yes, and impossible: it is a 101 MB transcript |
| `grep` your notes and transcripts | 211,627 | yes, and unaffordable |
| **recall** | **2,552** | yes |

Roughly **209,000 input tokens saved per history question.** The search itself
runs on your CPU and costs nothing.

**A worked estimate, assumption stated:** if you ask five "what did we decide" or
"did we already try" questions in a working day, and would otherwise answer them
by pasting files and grepping, that is on the order of **1M input tokens a day**
you no longer send. Change the five and the number moves with it.

**What I will not tell you:** how many extra messages that buys on Pro or Max.
Anthropic does not publish the formula, limits move with demand, and anyone
handing you "3-5x more coding hours" made it up. The token reduction above is
real and checkable. The effect on your specific limit is real but not something
anyone outside Anthropic can honestly put a multiplier on.

The second saving is less visible and probably bigger: **not re-reading the
session.** `--brief` reconstructs where you left off for about 600 tokens.
Scrolling the conversation back into context to get the same picture costs
30,000 to 80,000, and the `SessionStart` hook does the cheap version for you at
the start of every session.

---

## Speed and accuracy

Measured on 1,421 transcript files, 7.4 GB, 19,426 indexed messages.

| operation | time |
|---|---|
| a query | **0.63-0.75s** |
| first index build (7.4 GB) | 33s |
| incremental refresh | under a second |
| embedding 19,426 chunks | 4s |
| encoding one query | 0.109s |

Before the index existed a single query took **158 seconds**, and a six-question
benchmark timed out at ten minutes. Extracting once and searching that is the
whole trick.

Seven suites, each with a floor; the run fails if any drops below it.

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

```bash
python ~/.claude/skills/recall/tests/run_tests.py
```

**The known-item suite is generated from your data, not written by hand.** It
samples a chunk, builds a question from that chunk's own words, holds back the
most distinctive word so nothing passes by exact match, and demands the chunk
back. Twelve cases I wrote by hand scored 100% while sixty generated ones scored
76.7%. The gap was me overfitting to my own imagination, and I only saw it
because the generated set existed.

---

## How it compares

### Other memory and token skills

Every one of these was installed on the machine recall was built on. The counts
come from the filesystem.

| skill | files | executable code | tests | searches your transcripts | runs on its own |
|---|---:|---:|---:|---|---|
| `context-budget` | 1 | 0 | 0 | no | no |
| `token-budget-advisor` | 1 | 0 | 0 | no | no |
| `rescue-tokens` | 2 | 0 | 0 | no | no |
| `token-optimization` | 8 | 1 | 2 | no | no |
| `long-context-lost-in-the-middle` | 1 | 0 | 0 | no | no |
| `mem-search` | 1 | 0 | 0 | no | no |
| `smart-explore` | 1 | 0 | 0 | no | no |
| `timeline-report` | 1 | 0 | 0 | no | no |
| `mempalace` | 1 | 0 | 0 | no | no |
| `claude-mem` (plugin) | n/a | 7 | 0 | yes, via MCP | yes, via MCP |
| **recall** | **20** | **15** | **7 suites, 400+ cases** | **yes** | **yes, via hooks** |

Most of that list is advice: well-written documents telling Claude to be careful
with context. A document cannot search 7 GB of transcripts or tell you whether it
worked. `claude-mem` is the one genuinely comparable project, and it takes the
MCP bet described above.

**This is not a claim those skills are bad.** Several taught me things, and recall
absorbs what each did well: `--budget-report` is what `context-budget` did,
`--estimate` is `token-budget-advisor`, `--timeline` is `timeline-report`. The
argument is narrower. One tested program beats nine overlapping documents, because
loading several memory skills at once is precisely the waste each warns about.

### The obvious alternatives

| | grep | a RAG service | `/compact` | recall |
|---|---|---|---|---|
| finds a decision from 3 months ago | yes, unaffordably | yes | no, it is gone | yes |
| cost per answer | ~211k tokens | API calls | free but lossy | ~2.5k tokens |
| your data leaves the machine | no | **yes** | no | no |
| needs a key or an account | no | yes | no | no |
| runs without you asking | no | no | n/a | **yes** |
| tells you when it is wrong | no | rarely | n/a | yes, refuses stale indexes |
| works on a plane | yes | no | yes | yes |

---

## Why it works

Four ideas, each measured before it was kept.

**1. Extract once, search forever.** Raw transcripts are 7.4 GB of JSON, mostly
tool output. The part that answers a question is what people typed, plus the
minority of Claude's replies stating a conclusion. Pulled out once, that is
11.7 MB. Same answers, 158s down to 0.33s.

**2. Rank across stores, not one at a time.** recall searches your notes, your
skills, an optional code graph and your transcripts in one pass and ranks them
together. Searching notes first and stopping sounds principled and scored worse,
because a weak note from an unrelated project displaces the line holding the
answer. Store priority is a weight, not an order.

**3. Score density, not word count.** A 6,000-character note matching two filler
words used to beat the 600-character chunk holding the answer. Dividing by the
square root of length and capping per-term counts took accuracy from 42% to 75%
by itself.

**4. Semantic search that admits, but does not decide.** "Why was the router
broken" is answered by "bash ate the backslashes in the interpreter path", which
shares no words with the question. Static embeddings close that gap for a one-time
36 MB download, no GPU and no API. They let a chunk into the running without a
shared word, but it still has to win on the combined score.

---

## Commands, if you want them

You should not need these. They exist because sometimes you do.

```bash
R=~/.claude/skills/recall/scripts/recall.py

python $R "<question>"                 # search everything, ranked and bounded
python $R "<question>" --this-project  # only this project's history
python $R "<question>" --all-projects  # every project (the default), skip the code graph

python $R --brief --days 2             # asked / done / still open
python $R --handoff                    # what must survive a compact
python $R --decisions --days 30        # a decision ledger
python $R --digest --weeks 4           # per-week rollup
python $R --timeline --days 7          # by day, across projects

python $R --write "<fact>" --name <slug> --type project|user|feedback|reference

python $R --budget-report              # what a session costs before you type
python $R --estimate "@file.md"        # input tokens and likely response size
python $R --gc                         # stale and duplicate notes (never deletes)
python $R --optimize [--apply]         # promote/demote skills from measured usage
```

`--budget-report` found four image-generation skills on my machine costing ~950
tokens *every session* for something I used monthly. Moving them to a library tier
cut the fixed cost of a session by 27%, and they stayed one search away.

---

## Capture: what you did, not just what you said

Transcripts record the conversation, not the work. Ask "what did we change in the
router" and a transcript-only memory hands you the *description* of a change.

```json
{"t": 1788259894, "k": "edit", "p": "webapp", "d": "src/net/fetcher.py"}
{"t": 1788259894, "k": "run",  "p": "webapp", "d": "pytest tests/ -q [redacted]"}
```

A file append. No parsing, no model, no network. Read-only noise like `ls` and
`cat` is dropped, the log is capped, and commands are scrubbed before writing.

That scrubber had a real bug, found by the test suite here.
`Authorization:\s*\S+` eats one token after the colon, and in
`Authorization: Bearer <token>` that token is the word "Bearer", so the credential
went to disk in the clear. It now takes the scheme *and* the value, with a test
per credential shape.

---

## Privacy

Nothing leaves your machine. No telemetry, no account.

The only networked feature is opt-in parameter sharing, and it sends about twenty
integers:

```json
{"schema": 1, "machine": "9f2c4a1b77de",
 "params": {"sem_weight": 12, "first_div": 2, "taper": 6},
 "scores": {"known_item": 0.99, "curated": 1.0},
 "corpus": {"chunks": 19426, "vocab": 84210}}
```

No prompts, answers, paths, project names or note text. The machine id is a random
local salt, not a hostname.

- **`--export` writes a file and stops.** Nothing uploads on a schedule.
- **A pulled card is untrusted input.** Every field is range-checked, the whole
  card is rejected on any bad field, and a hostile card cannot crash the import.
- **Only integers are adopted.** It cannot fetch or run code. Code travels as a
  pull request a human reads, because auto-executing code pulled from strangers is
  a supply-chain compromise wearing a helpful hat.

---

## Requirements

- **Python 3.9+ and Claude Code.** That is the hard requirement.
- **`numpy` and `model2vec` are optional** and buy semantic ranking. Without them
  recall falls back to lexical scoring and still works.
  `pip install numpy model2vec`
- **graphify is not required.** If a project happens to have a code graph, recall
  uses it as one more store; if not, that store is skipped. Tested, not asserted:
  the suite runs with graphify absent from `PATH`, then again with a graph
  directory present but no binary, and both must come back clean.
- Windows, macOS and Linux. Built and tested on Windows, which is the fussiest
  about hook paths.

---

## Turning it off

```bash
python install.py --no-hooks    # install, but nothing runs automatically
python install.py --uninstall   # remove the skill, hooks and MCP server
```

Uninstall restores `settings.json`, leaves your index and notes alone, and prints
exactly what it left behind. `settings.json` is backed up before it is ever
touched, existing hooks are untouched, and installing twice changes nothing.

---

## Honest limitations

- **Only as good as your transcripts.** A fresh Claude Code install has nothing to
  remember, and recall says so rather than inventing something.
- **`--brief` is a heuristic.** It decides a request is "done" by checking whether
  a later message reads like a conclusion about the same thing. Usually right, and
  it says out loud that it is guessing.
- **The auto-recall hook fires on phrasing, not understanding.** Ask about the past
  in an unusual way and it stays silent; the tool is still one question away.
- **Parameter sharing has never met a second real machine.** The validator is
  tested against 28 hostile cards. Two installs converging is unproven.
- **Every threshold was fitted on one person's corpus.** That is why `simulate.py`
  builds synthetic machines with alien vocabularies. It found a real bug on its
  first honest run: an IDF floor of `0.3` let a word appearing in *every* record
  still score, invisible on a diverse corpus and ruinous on a small one. Four
  synthetic machines went from 44/64/88/92% to 100%.

---

## License

MIT. See [LICENSE](LICENSE).
