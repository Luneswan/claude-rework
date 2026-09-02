<div align="center">

# claude-rework

**Claude forgets everything between sessions. This makes it remember - without burning your context window.**

[![PyPI](https://img.shields.io/pypi/v/claude-rework?color=f4b23e&label=pypi)](https://pypi.org/project/claude-rework/)
[![Downloads](https://img.shields.io/pypi/dm/claude-rework?color=5ddb9a&label=installs%2Fmonth)](https://pypi.org/project/claude-rework/)
[![Stars](https://img.shields.io/github/stars/Luneswan/claude-rework?style=flat&color=f4b23e)](https://github.com/Luneswan/claude-rework/stargazers)
[![CI](https://github.com/Luneswan/claude-rework/actions/workflows/ci.yml/badge.svg)](https://github.com/Luneswan/claude-rework/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/claude-rework)](https://pypi.org/project/claude-rework/)
[![License](https://img.shields.io/github/license/Luneswan/claude-rework?color=blue)](LICENSE)

```bash
pip install claude-rework && claude-rework install
```

</div>

---

## 💸 See how much you save

Every number here is **measured on a real 7.4 GB installation**, not estimated
from industry averages. One question about your own past work:

| Answering *"what did we decide about X?"* | Input tokens | Right answer? |
|---|---:|:-:|
| Paste the session into context | 26,539,949 | yes - and impossible, it's a 101 MB transcript |
| `grep` your notes and transcripts | 211,627 | yes - and unaffordable |
| **claude-rework** | **2,552** | **yes** |
| | **↓ 209,075 saved** | |

Resuming a session costs the same way: re-reading the conversation to find where
you left off runs 30,000–80,000 tokens. `--brief` rebuilds the same picture from
the index for **~600**. Call it **49,400 saved** per resume.

### One developer, one month

<sub>22 working days. Pick the row that looks like your week - then multiply by your team.</sub>

| Your usage | Per day | Tokens never sent | Opus 5 | Sonnet 5 | Haiku 4.5 |
|---|---|---:|---:|---:|---:|
| Light | 2 lookups, 1 resume | 10.3M | **$51** | $21 | $10 |
| **Typical** | 6 lookups, 2 resumes | **29.8M** | **$149** | $60 | $30 |
| Heavy | 15 lookups, 4 resumes | 73.3M | **$367** | $147 | $73 |

Ten typical developers is the same row × 10 - **297.7M tokens and $1,489 a month**,
$17,863 a year.

<details>
<summary><b>On a Pro or Max subscription instead of the API?</b></summary>

<br>

You aren't billed per token, so the saving isn't an invoice line - it's **headroom**.
Those 29.8M tokens a month are context you no longer spend re-deriving things you
already knew, which is work you get done before hitting a limit.

How many extra messages that buys is not something anyone outside Anthropic can
compute. Rate limits move with demand and the formula isn't published. So this
README won't hand you a "3× more coding hours" figure - anyone who does made it up.

What's true and checkable: **the token reduction above is measured**, and the
dollar column is that reduction times Anthropic's published input price.

</details>

<details>
<summary><b>Show me the arithmetic</b></summary>

<br>

```
per lookup saved  = 211,627 (grep)      -  2,552 (indexed)  = 209,075 tokens
per resume saved  =  50,000 (re-read)   -    600 (--brief)  =  49,400 tokens

typical developer = (6 × 22 × 209,075) + (2 × 22 × 49,400)
                  =     27,597,900      +      2,173,600
                  =     29,771,500 tokens / month

at Opus 5 input   = 29.77 M × $5.00 / M = $148.86 / developer / month
```

Prices are Anthropic list: Opus 5 `$5.00`, Sonnet 5 `$2.00`, Haiku 4.5 `$1.00`
per million input tokens. The search itself runs on your CPU and costs nothing.

</details>

---

## Install

**One line. Any OS. It finds everything itself.**

```bash
pip install claude-rework && claude-rework install
```

<details>
<summary><b>No pip? No terminal? Other ways in →</b></summary>

<br>

**One line, without pip:**

```bash
curl -fsSL https://raw.githubusercontent.com/Luneswan/claude-rework/main/install.py | python3 -
```
```powershell
iwr -useb https://raw.githubusercontent.com/Luneswan/claude-rework/main/install.py | python -
```

**No terminal at all** - [download the zip](https://github.com/Luneswan/claude-rework/archive/refs/heads/main.zip), unzip it, then:

| Your machine | Do this |
|---|---|
| **macOS** | Double-click `install.command` |
| **Windows** | Right-click `install.ps1` → *Run with PowerShell* - it installs Python for you if you don't have it |
| **Linux** | `bash install.sh` |

All five routes run the same installer.

</details>

It detects your OS, finds every Claude surface you have, connects each one the
only way it can be reached, installs the semantic-search extras, and **builds
your index immediately** - no session, no first message, no waiting.

```
claude-rework 1.3.0 - install
  system   Darwin 24.3.0 (arm64), Python 3.12.7
  claude_code      found, not connected
  claude_desktop   found, not connected
  index    not built, 1,421 transcript file(s)

  installed skill    ~/.claude/skills/recall
  installed hooks    ~/.claude/hooks (4 scripts)
  claude code        connected via hooks:
      + SessionStart      start each session knowing what is still open
      + UserPromptSubmit  answer 'did we already do this?' before Claude guesses
      + PostToolUse       record what was actually edited and run
      + PreCompact        save decisions before compaction drops them
  desktop app        connected via mcp - restart the app to load it
  ranking            lexical + semantic
  index              corpus now 7.7 MB (13,074 messages)
  vectors            13,074 vectors, dim 512, 25.5 MB, in 6s

  Done. Nothing else to configure.
```

**You never type a recall command again.** Ask Claude in plain English.

---

## What it feels like

> **you:** didn't we already fix the webhook timeout?

Before Claude sees that message, claude-rework searched 13,000 messages of your
own history locally and put the answer in front of it:

> **Claude:** From your history on Feb 14 - you set it to **12 seconds** after
> measuring the provider's p99 at 9.4s.

About 400 tokens, 0.7 seconds, answered from what you *actually decided*.

**"Add a button" triggers nothing.** History is only fetched when you ask about
the past - injecting it into new work is exactly the waste this exists to prevent.

---

## Every Claude surface, connected automatically

| Surface | How it connects | Auto-detected |
|---|---|:-:|
| **Claude Code** (terminal) | 4 hooks | ✅ |
| **VS Code extension** | same hooks - it drives the same CLI | ✅ |
| **JetBrains extension** | same hooks | ✅ |
| **Claude Desktop app** | MCP server - desktop can't run hooks | ✅ |
| **Claude Cowork** | same MCP server | ✅ |

Where a surface *can't* take hooks, it falls back to MCP rather than documenting
the limitation and leaving you to solve it.

**The design argument in one line:** an MCP server's tool schemas load into your
context *before you type a word*, every session. A hook costs nothing until it
fires.

| | Hooks (Claude Code) | MCP (desktop app) |
|---|:-:|:-:|
| Context cost while idle | **zero** | tool schemas, every session |
| Fires on | only past-shaped prompts | whenever Claude decides |
| Records what you *did* | ✅ | ✗ |
| Survives compaction | ✅ writes to disk first | ✗ |

---

## What runs, and when

| When | What happens | Cost |
|---|---|---|
| You open a session | Prints the threads still open from the last few days | ~600 tokens, once |
| You ask about the past | Looks it up locally, hands the answer to Claude | ~300 tokens, only those prompts |
| Claude edits or runs something | Logs one line of what actually happened | a file append |
| Compaction starts | Writes the decisions to disk **first** | ~600 tokens |

---

## 🧳 Switching accounts or machines

New Claude account? New laptop? Your history stays behind and Claude forgets you.

```bash
claude-rework export memory.zip     # old account

pip install claude-rework && claude-rework install
claude-rework import memory.zip     # new account, new machine, any OS
```

Everything comes with you, automatically:

| Carried across | What that means |
|---|---|
| **Your whole search index** | every message and conclusion already extracted |
| **Every project** | slug, real path on disk, how much history each has |
| **Project context** | each project's `CLAUDE.md`, `AGENTS.md`, memory notes |
| **The activity log** | what was actually edited and run |
| **Who you are** | a `who-i-am` profile, so the new account knows you on day one |
| Raw transcripts | only with `--with-transcripts` - large, exact |

**Never carried:** `settings.json`, hooks, credentials, API keys, OAuth tokens.
It's your *content*, not your configuration - so a bundle can't leak a secret it
never contained.

Import is a **merge, never a replace**. Import the same bundle twice and nothing
changes. Import a colleague's and it adds to yours. A note you already wrote is
never overwritten.

```bash
claude-rework inspect memory.zip   # look before you import
claude-rework profile              # what Claude knows about you
```

---

## How it compares

### Against other memory & token skills

Every one of these was installed on the machine this was built on. Counts come
from the filesystem, not from memory.

| | Files | Code | Tests | Searches your history | Runs itself | Offline |
|---|---:|---:|---:|:-:|:-:|:-:|
| `context-budget` | 1 | 0 | 0 | ✗ | ✗ | n/a |
| `token-budget-advisor` | 1 | 0 | 0 | ✗ | ✗ | n/a |
| `rescue-tokens` | 2 | 0 | 0 | ✗ | ✗ | n/a |
| `token-optimization` | 8 | 1 | 2 | ✗ | ✗ | n/a |
| `long-context-lost-in-the-middle` | 1 | 0 | 0 | ✗ | ✗ | n/a |
| `mem-search` | 1 | 0 | 0 | ✗ | ✗ | n/a |
| `smart-explore` | 1 | 0 | 0 | ✗ | ✗ | n/a |
| `timeline-report` | 1 | 0 | 0 | ✗ | ✗ | n/a |
| `mempalace` | 1 | 0 | 0 | ✗ | ✗ | n/a |
| `claude-mem` (plugin) | - | 7 | 0 | ✅ via MCP | ✅ via MCP | ✗ |
| **claude-rework** | **34** | **17** | **9 suites, 400+ cases** | **✅** | **✅ hooks + MCP** | **✅** |

Most of that list is *advice* - well-written documents telling Claude to be
careful with context. A document cannot search 7 GB of transcripts or tell you
whether it worked. `claude-mem` is the one genuinely comparable project, and it
takes the MCP-only bet.

**This is not a claim those skills are bad.** Several taught me things, and
claude-rework absorbs what each did well: `--budget-report` is what
`context-budget` did, `--estimate` is `token-budget-advisor`, `--timeline` is
`timeline-report`. The argument is narrower - one tested program beats nine
overlapping documents, because loading several memory skills at once is precisely
the waste each of them warns about.

### Against the obvious alternatives

| | grep | RAG service | `/compact` | CLAUDE.md | **claude-rework** |
|---|---|---|---|---|---|
| Finds a decision from 3 months ago | yes, unaffordably | yes | no, it's gone | only what you typed | **yes** |
| Cost per answer | ~211k tokens | API calls | free but lossy | in context always | **~2.5k tokens** |
| Your data leaves the machine | no | **yes** | no | no | **no** |
| Needs a key or account | no | yes | no | no | **no** |
| Runs without you asking | no | no | n/a | n/a | **yes** |
| Survives an account switch | n/a | yes | no | manual copy | **yes, one command** |
| Tells you when it's wrong | no | rarely | n/a | n/a | **yes, refuses stale indexes** |
| Works on a plane | yes | no | yes | yes | **yes** |

---

## Why it works

Four ideas. Each measured before it was kept.

**1. Extract once, search forever.** Raw transcripts are 7.4 GB of JSON, mostly
tool output. What answers a question is what people typed, plus the minority of
Claude's replies that state a conclusion. Pulled out once: 7.7 MB. Same answers,
158s → 0.33s.

**2. Rank across stores, not one at a time.** Notes, skills, an optional code
graph and your transcripts are searched in one pass and ranked together.
Searching notes first and stopping *sounds* principled and scored worse - a weak
note from an unrelated project displaces the line holding the answer. Store
priority is a weight, not an order.

**3. Score density, not word count.** A 6,000-character note matching two filler
words used to beat the 600-character chunk holding the answer. Dividing by the
square root of length took accuracy from 42% → 75% on its own.

**4. Semantic search that admits, but doesn't decide.** *"Why was the router
broken"* is answered by *"bash ate the backslashes in the interpreter path"* -
which shares no words with the question. Static embeddings close that gap for a
one-time 36 MB download, no GPU, no API. A chunk can enter the running without a
shared word, but it still has to win on the combined score.

---

## Proof

Nine suites, each with a floor. The run fails if any drops below it.

| Suite | Result | What it proves |
|---|---|---|
| known-item | **300/300** | retrieval on questions generated *from your corpus*, gold term held out |
| curated | **12/12** | hand-written cases, zero silent fallbacks |
| stress | **19/19** | empty input, CJK, RTL, shell metacharacters, a 3,000-char word |
| subcommands | **11/11** | every command runs clean |
| capture | **33/33** | the hook records work, drops noise, redacts secrets |
| vectors | **6/6** | a stale or misaligned index is refused, never guessed at |
| federation | **28/28** | hostile input rejected without crashing |
| concurrency | **5/5** | three builds at once → zero duplicates, no lock left behind |
| hooks | **13/13** | all four hooks under Claude Code's real calling convention |
| foreign machines | **4/4 at 100%** | tiny, huge, non-English and sparse corpora |
| optimizer | **100/100** | no file lost, no action below the evidence threshold |

```bash
claude-rework test
```

**CI runs a clean-room install on Ubuntu, Windows and macOS × Python 3.10 and
3.12 on every push** - a machine that has never seen this, synthetic transcripts,
the optional binary stripped from `PATH`, install → use → uninstall.

**The known-item suite is generated from your own data, not written by hand.** It
samples a chunk, builds a question from that chunk's own words, holds back the
most distinctive word so nothing passes by exact match, and demands the chunk
back. Twelve cases I wrote by hand scored 100% while sixty generated ones scored
76.7%. The gap was me overfitting to my own imagination - and I only saw it
because the generated set existed.

---

## Keeping it working

```bash
claude-rework status     # what's connected, what's indexed
claude-rework doctor     # check every connection; say what's wrong
claude-rework repair     # fix what doctor found
claude-rework update     # newest version, reconnected
claude-rework uninstall  # remove everything; keep your memory
```

`doctor` catches the failures that are otherwise silent: a hook pointing at a
Python that no longer exists, a backslash in a hook path (bash eats them - that
one cost hours), an MCP entry orphaned by a moved interpreter, an index that was
never built. `repair` fixes all of them.

<details>
<summary><b>Commands, if you want them</b> - you shouldn't need these</summary>

<br>

```bash
claude-rework "<question>"           # ask your history
claude-rework "<q>" --this-project   # only this project
claude-rework --brief --days 2       # asked / done / still open
claude-rework --handoff              # what must survive a compact
claude-rework --decisions --days 30  # a decision ledger
claude-rework --timeline --days 7    # by day, across projects
claude-rework --write "<fact>" --name <slug> --type project|user|feedback|reference
claude-rework --budget-report        # what a session costs before you type
claude-rework --estimate "@file.md"  # input tokens and likely response size
claude-rework --gc                   # stale/duplicate notes (never deletes)
claude-rework --optimize [--apply]   # promote/demote skills from measured usage
```

`--budget-report` found four image-generation skills on my machine costing ~950
tokens *every session* for something used monthly. Moving them to a library tier
cut fixed session cost by 27%, and they stayed one search away.

</details>

---

## Privacy

Nothing leaves your machine. No telemetry, no account, no server.

The only networked feature is opt-in parameter sharing, and it sends about twenty
integers:

```json
{"schema": 1, "machine": "9f2c4a1b77de",
 "params": {"sem_weight": 12, "first_div": 2, "taper": 6},
 "scores": {"known_item": 0.99, "curated": 1.0},
 "corpus": {"chunks": 13074, "vocab": 84210}}
```

No prompts, answers, paths, project names or note text. The machine id is a
random local salt, not a hostname.

- **`--export` writes a file and stops.** Nothing uploads on a schedule.
- **A pulled card is untrusted input.** Every field is range-checked, the whole
  card is rejected on any bad field, and a hostile card can't crash the import.
- **Only integers are adopted.** It cannot fetch or run code. Code travels the
  ordinary way - a pull request a human reads - because auto-executing code
  pulled from strangers is a supply-chain compromise wearing a helpful hat.

**Secrets never reach the activity log.** Commands are scrubbed before writing.
That scrubber had a real bug, found by the test suite here:
`Authorization:\s*\S+` eats one token after the colon, and in
`Authorization: Bearer <token>` that token is the word *"Bearer"* - so the
credential went to disk in the clear. It now takes the scheme *and* the value,
with a test per credential shape.

---

## Requirements

- **Python 3.9+ and Claude.** That's the hard requirement.
- **`numpy` + `model2vec`** install automatically for semantic ranking. If that
  can't happen (offline, locked-down machine), it falls back to lexical scoring
  and still works - the install never fails over an optional extra.
- **graphify is not required.** If a project happens to have a code graph, it's
  used as one more store; if not, that store is skipped. *Tested, not asserted:*
  the suite runs with graphify absent from `PATH`, then again with a graph
  directory present but no binary, and both must come back clean.
- Windows, macOS, Linux - all three in CI.

---

## Honest limitations

- **Only as good as your transcripts.** A fresh Claude install has nothing to
  remember, and it says so rather than inventing something.
- **`--brief` is a heuristic.** It decides a request is "done" by checking
  whether a later message reads like a conclusion about the same thing. Usually
  right, and it says out loud that it's guessing.
- **The auto-recall hook fires on phrasing, not understanding.** Ask about the
  past in an unusual way and it stays silent; the tool is still one question away.
- **Parameter sharing has never met a second real machine.** The validator is
  tested against 28 hostile cards. Two installs converging is unproven.
- **Every threshold was fitted on one person's corpus.** That's why `simulate.py`
  builds synthetic machines with alien vocabularies. It found a real bug on its
  first honest run: an IDF floor of `0.3` let a word appearing in *every* record
  still score - invisible on a diverse corpus, ruinous on a small one. Four
  synthetic machines went from 44/64/88/92% → 100%.

---

## Contributing

Issues and PRs welcome. The bar is simple: **a change that can't hold the test
floors is the thing that's wrong.** Floors only ratchet up.

```bash
git clone https://github.com/Luneswan/claude-rework && cd claude-rework
python tests/clean_room_test.py     # the real test: install into a fresh machine
```

[CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md)

---

<div align="center">

**If this saved you tokens, [⭐ star it](https://github.com/Luneswan/claude-rework) - it's the only signal that tells me whether to keep building.**

[![Star History Chart](https://api.star-history.com/svg?repos=Luneswan/claude-rework&type=Date)](https://star-history.com/#Luneswan/claude-rework&Date)

MIT · Built because Claude kept asking me things I'd already answered.

</div>
