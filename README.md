# claude-rework

[![PyPI](https://img.shields.io/pypi/v/claude-rework)](https://pypi.org/project/claude-rework/)
[![CI](https://github.com/Luneswan/claude-rework/actions/workflows/ci.yml/badge.svg)](https://github.com/Luneswan/claude-rework/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Claude starts every session with no memory of the last one. Everything you
decided, tried, and ruled out is sitting in `~/.claude/projects` as raw JSON that
nothing reads. Ask about it and Claude either guesses or re-reads a few hundred
megabytes to find out.

claude-rework indexes those transcripts once and answers from the index. A
question about your own past work costs about 2,500 tokens and takes under a
second, instead of 211,000 tokens and a long wait.

```bash
pip install claude-rework
python -m claude_rework install
```

One line at a time, so it works the same in cmd, PowerShell and bash - see
[Install](#install) for the single-line form for your shell, and why the second
command is the module and not the `claude-rework` name.

After that you do not type anything. Ask Claude a question about the past in
plain English and the answer is already in front of it.

---

## Contents

- [What it saves](#what-it-saves)
- [Install](#install)
- [How it works](#how-it-works)
- [Asking it things](#asking-it-things)
- [Moving to a new machine or account](#moving-to-a-new-machine-or-account)
- [Saving facts yourself](#saving-facts-yourself)
- [Keeping it working](#keeping-it-working)
- [Every command](#every-command)
- [Privacy](#privacy)
- [How it compares](#how-it-compares)
- [Requirements](#requirements)
- [Limitations](#limitations)

---

## What it saves

One question about your past work, measured on a real installation of 1,421
transcript files totalling 7.4 GB:

| Answering *"what did we decide about X?"* | Input tokens |
|---|---:|
| `grep` your notes and transcripts | 211,627 |
| claude-rework | 2,552 |

That is **209,075 tokens saved per question**. Resuming a session works the same
way: re-reading a conversation to find where you left off costs 30,000–80,000
tokens, while `--brief` rebuilds the same picture from the index for about 600,
so **49,400 saved per resume**.

For one developer asking six questions and resuming twice a day, 22 days a month:

```
(6 × 22 × 209,075) + (2 × 22 × 49,400) = 29,771,500 tokens per month
```

At Anthropic's list price that is **$149/month** on Opus 5 ($5.00 per million
input tokens), or **$60** on Sonnet 5 ($2.00). Adjust the numbers to match how
you actually work.

On a Pro or Max plan you are not billed per token, so this is not money, it is
headroom. Those tokens are context you no longer spend re-deriving things you
already knew, which is work you get done before hitting a limit. How many extra
messages that buys depends on rate limits Anthropic does not publish, so this
README does not put a number on it.

---

## Install

Pick the line for the terminal you are in. Both do the same two things:
install the package, then connect it.

**Windows - Command Prompt (cmd):**

```bat
pip install claude-rework && python -m claude_rework install
```

**Windows - PowerShell:**

```powershell
pip install claude-rework; python -m claude_rework install
```

**macOS / Linux:**

```bash
pip3 install claude-rework && python3 -m claude_rework install
```

Three details worth knowing, because each one used to cost people an install:

- Windows PowerShell 5.1 - the blue one, still the default on many machines -
  has no `&&` operator. It answers `The token '&&' is not a valid statement
  separator in this version`. PowerShell 7 accepts it; the `;` above works in
  both.
- The second command is `python -m claude_rework`, not `claude-rework`. pip
  puts the `claude-rework` command in a scripts directory that a `--user`
  install leaves off PATH, so the shell you just ran pip in cannot see it yet.
  The module form always works.
- `install` then **adds that directory to your PATH for you**, so `claude-rework`
  works by name in every terminal you open afterwards. Nothing to edit, no
  administrator rights needed. Opt out with `--no-path`.

Re-running install later is always safe: it updates the files, clears out
anything stale or broken, and leaves your memory, notes and tuning untouched.

Without pip, one line, any operating system:

```bash
curl -fsSL https://raw.githubusercontent.com/Luneswan/claude-rework/main/install.py | python3 -
```

```powershell
iwr -useb https://raw.githubusercontent.com/Luneswan/claude-rework/main/install.py | python -
```

Without a terminal at all: [download the zip](https://github.com/Luneswan/claude-rework/archive/refs/heads/main.zip),
unzip it, and double-click the one for your machine:

| Machine | File |
|---|---|
| Windows | `install.cmd` - double-click it |
| Windows, if you prefer PowerShell | right-click `install.ps1` → *Run with PowerShell* |
| macOS | `install.command` - double-click it |
| Linux | `bash install.sh` |

On Windows either script offers to install Python for you if you do not have
it. All four end up running the same installer.

All of these run the same installer.

### What the installer does

It reads your machine rather than asking you questions. It finds your operating
system, locates your Claude directory, checks which Claude surfaces you have
installed, and connects each one:

| Surface | How it connects |
|---|---|
| Claude Code in the terminal | four hooks |
| VS Code and JetBrains extensions | the same hooks, since they drive the same CLI |
| Claude Desktop app | an MCP server, because the desktop app cannot run hooks |
| Claude Cowork | the same MCP server |

It then installs the optional semantic search libraries and builds your index
immediately. You do not have to open a session or send a message first, which
matters if you install it in order to migrate straight away.

It backs up any configuration file before changing it.

Running it again is safe. A second install updates the files that shipped with
the new version and leaves everything else alone, including anything you added
yourself and your generated test cases. Your index, notes, activity log and
tuning live outside the installed directory and are never touched by an install
or a reinstall. The output tells you what it did:

```
  updated   skill    ~/.claude/skills/recall
            0 new, 3 updated, 11 unchanged, 2 of your own file(s) left alone
```

### If the command is not found

`pip` puts the `claude-rework` executable in its scripts directory, and on some
setups that directory is not on your PATH, so a new terminal reports the command
as missing even though it installed correctly. Both the installer and
`claude-rework doctor` detect this and print the fix. You can always use:

```bash
python -m claude_rework status
```

which works from any directory on any machine where Python does.

---

## How it works

Four hooks run at four moments. Each one has a job and a cost.

**When you open a session,** it prints the threads still open from the last few
days, so the session starts oriented instead of blank. About 600 tokens, once.

**When you send a message,** it checks whether you are asking about the past.
Phrases like *"didn't we already"*, *"what did we decide"*, or *"where were we"*
trigger a local search, and the result is placed in front of Claude before it
answers. About 300 tokens, and only on those messages. "Add a button" triggers
nothing, because injecting history into new work is the waste this exists to
prevent.

**When Claude edits a file or runs a command,** it appends one line to an
activity log. Transcripts record the conversation but not the work, so without
this, asking "what did we change in the router" returns a description of a change
rather than the change. This costs a file append.

**When your context fills and compaction starts,** it writes the current
decisions to disk first, so the summary cannot lose them.

The desktop app cannot run hooks, so it gets an MCP server exposing the same
capability as five tools. The trade-off is worth stating plainly: an MCP server's
tool schemas load into your context before you type a word, every session, while
a hook costs nothing until it fires. That is why Claude Code uses hooks and MCP
is the fallback for surfaces that have no hooks.

Underneath, the index is built once from your transcripts. 7.4 GB of raw JSON
becomes 7.7 MB of the parts that answer questions: what people typed, plus the
minority of Claude's replies that state a conclusion. Searching that is fast
enough to do on every relevant message.

---

## Asking it things

Normally you just talk to Claude. If you want to query it directly:

```bash
claude-rework "what did we decide about the retry logic"
claude-rework "why did we drop the redis queue" --this-project
claude-rework --brief --days 2
```

`--brief` is the one people use most. It lists what was asked, what got done, and
what is still open, without re-reading a conversation.

Other views over the same index:

```bash
claude-rework --handoff              # what must survive a compaction
claude-rework --decisions --days 30  # decisions with their reasons
claude-rework --timeline --days 7    # what happened, by day, across projects
```

By default a search covers every project, because the decision you are looking
for is often in the repo you were in last week. `--this-project` narrows it when
a word means different things in two codebases.

---

## Moving to a new machine or account

This is the part that has no equivalent elsewhere, so it is worth explaining
fully.

When you switch Claude accounts you get a clean `~/.claude`. Your transcripts
stay with the old account, so Claude forgets every decision you made, every
project you work on, and everything it knew about how you work. The same happens
on a new laptop, after a reinstall, or when moving between work and personal
accounts.

**On the account you are leaving** - sign into it, then:

```bash
claude-rework scan
claude-rework export
```

`scan` reads that account's whole history in before you carry it, so nothing is
left behind because no hook happened to have fired for it yet. `export` then
writes a zip named after the account and the day:

```
claude-rework-alex-20260903.zip
```

That name matters once you have done this twice. Every export used to be called
`memory.zip`, and two of them in one folder were impossible to tell apart. You
can still choose the name yourself - `claude-rework export mine.zip` - and
`claude-rework whoami` shows which account is signed in and what the file would
be called.

**On the account you are moving to** - sign into it, install, then import:

```bash
pip install claude-rework
python -m claude_rework install
claude-rework import claude-rework-alex-20260903.zip
```

Not sure which zip is which? `claude-rework inspect FILE.zip` prints the
account it came from and what is inside, without importing anything.

That is the whole migration. The new account can immediately answer questions
about work that only ever happened on the old one. Importing twice is a no-op,
and an import merges - it never replaces what the new account already had.

### What the bundle contains

| Included | Detail |
|---|---|
| Your search index | every message and conclusion already extracted |
| Every project | its slug, its real path on disk, and how much history it has |
| Project context | each project's `CLAUDE.md`, `AGENTS.md`, and memory notes |
| The activity log | what was actually edited and run |
| A profile of you | written to a `who-i-am` note so the new account knows who it is talking to on its first message |
| Raw transcripts | only if you pass `--with-transcripts`; large, and rarely needed |

### What it never contains

Your `settings.json`, your hooks, credentials, API keys, and OAuth tokens are
never included. The bundle holds your content, not your configuration. That is
what makes it portable between accounts and operating systems, and it means a
bundle cannot leak a secret it never held.

### How import behaves

Import merges. It never replaces.

Records are matched on their source, timestamp, and text, so importing the same
bundle twice changes nothing the second time. Importing a colleague's bundle adds
their history to yours without destroying either. A note that already exists on
the destination is left alone, because the local copy is the one someone edited.

Before importing, you can look inside:

```bash
claude-rework inspect memory.zip
```

It prints when the bundle was made, what it holds, and which projects are in it.
The bundle itself is an ordinary zip file, so you can open it, read it, and
delete anything you would rather not carry across before importing.

### If your history is in the web or desktop app

Claude Code writes transcripts to disk, so they can be indexed directly. The web
app and the desktop app do not: that history lives on Anthropic's servers. You
can still bring it in.

In Claude, go to Settings, then Privacy, then Export data. Anthropic emails you
a zip containing `conversations.json`. Pass either the zip or the json:

```bash
claude-rework import-web conversations.json
```

Those conversations become searchable like anything else. They are tagged as
coming from the export, so they are never confused with transcripts written on
this machine, and importing the same file twice adds nothing.

Exported history is months old by definition, so a search that finds nothing in
the default 45-day window automatically widens to your whole history and says
so.

To see what the profile currently knows about you:

```bash
claude-rework profile
```

### Keeping internal names out of a bundle

Credentials are stripped automatically. Everything else that is sensitive is
sensitive only to you, so you say what it is. Create `~/.claude/.reworkignore`:

```
# one per line; blank lines and # comments ignored
Northwind Trading
re:ACME-\d{4,}
```

A plain line is matched literally and case-insensitively. Prefix a line with
`re:` for a regular expression. Check it before you rely on it:

```bash
claude-rework redact
```

That prints how many times each pattern matches your history, shows examples,
and names any pattern that matched nothing, because a rule you believe is active
but is not is worse than no rule at all.

Patterns apply to everything a bundle carries: message text, activity records,
notes and project context files. Your local index is never modified, since
redacting what you can already read on your own machine helps nobody. The
frequency map is left out of a redacted bundle entirely, so a removed term
cannot reappear as vocabulary.

---

## Saving facts yourself

Most of what claude-rework knows comes from your transcripts automatically. You
can also save something deliberately:

```bash
claude-rework --write "I prefer terse answers with no preamble" \
    --name how-i-like-answers --type user
```

The four types decide how a fact is treated and whether it travels with you:

| Type | For | Example |
|---|---|---|
| `user` | who you are, standing preferences | how you like answers written |
| `feedback` | a correction, "do it this way from now on" | include the reason |
| `project` | a goal, constraint, or decision not visible in the code | why you chose a library |
| `reference` | a URL, dashboard, or ticket | where the staging logs live |

Notes of type `user` and `feedback` are what build your profile, so they are the
ones that make a new account feel like it already knows you.

Anything the repository already records, how the code is structured, what git
history says, is better left unsaved. A note that restates the codebase costs
context on every search and goes stale silently.

---

## Keeping it working

```bash
claude-rework status     # what is connected, what is indexed
claude-rework doctor     # check every connection and report problems
claude-rework repair     # fix what doctor found
claude-rework update     # update and reconnect
claude-rework uninstall  # remove it, keep your memory
```

`doctor` exists because the failures that matter here are silent. A hook pointing
at a Python that has since been moved or upgraded does nothing and reports
nothing. A hook command containing a backslash is destroyed by the shell on
Windows before it ever runs. An MCP entry can be orphaned the same way. An index
may never have been built. `doctor` checks each connection the way it will
actually be used and names anything wrong; `repair` fixes all of it.

`uninstall` removes the hooks, the MCP entry, and the installed files, and leaves
your index and notes alone. It tells you exactly which files it left behind. If
you want your memory gone as well, delete those files, or export them first.

Every command works from any directory. Nothing needs you to be inside a
particular project, because the index lives in your home directory rather than
alongside your code. `--this-project` is the only flag that pays attention to
where you are.

---

## Every command

```
claude-rework install [--no-hooks] [--no-desktop] [--no-semantic] [--no-build] [--no-path]
claude-rework status
claude-rework doctor
claude-rework repair
claude-rework update
claude-rework uninstall
claude-rework mcp-config

claude-rework whoami
claude-rework scan [--full]
claude-rework export [FILE.zip] [--with-transcripts]
claude-rework import FILE.zip
claude-rework import-web conversations.json
claude-rework inspect FILE.zip
claude-rework redact
claude-rework profile

claude-rework "<question>" [--budget N] [--days N] [--this-project]
claude-rework --brief [--days N]
claude-rework --handoff
claude-rework --decisions [--days N]
claude-rework --timeline [--days N]
claude-rework --digest [--weeks N]
claude-rework --write "<fact>" --name <slug> --type user|feedback|project|reference
claude-rework --stores
claude-rework --budget-report
claude-rework --estimate "@file.md"
claude-rework --gc
claude-rework --optimize [--apply]
claude-rework test [--known N] [--quick]
```

`--budget-report` inventories what loads into context before you type anything:
skill descriptions, your `CLAUDE.md`, hooks. On the machine this was built on it
found four image-generation skills costing about 950 tokens every session for a
capability used monthly, and moving them cut the fixed cost of a session by 27%.

`--gc` lists stale and duplicate notes. It never deletes anything.

`--optimize` reads which skills the router actually surfaced and suggests moving
unused ones out of the always-loaded set. It refuses to act on fewer than 40
routed prompts, never judges a skill less than 14 days old, and never touches a
protected one. Add `--apply` only when you agree with what it proposes.

---

## Privacy

Nothing leaves your machine. There is no telemetry, no account, and no server.

Two things touch the network, and you trigger both by hand. The first is
installing the optional `numpy` and `model2vec` libraries and the one-time 36 MB
model download; after that, searching is entirely offline. The second is optional
parameter sharing, which sends about twenty integers describing how well the
ranking is tuned:

```json
{"schema": 1, "machine": "9f2c4a1b77de",
 "params": {"sem_weight": 12, "first_div": 2, "taper": 6},
 "scores": {"known_item": 0.99, "curated": 1.0},
 "corpus": {"chunks": 13074, "vocab": 84210}}
```

No prompts, answers, file paths, project names, or note contents. The machine id
is a random local value, not a hostname.

Commands written to the activity log are scrubbed before they are stored.
Anything matching a credential pattern (`sk-`, `ghp_`, `hf_`, `xox`, `AKIA`,
`--password`, authorisation headers, `*_TOKEN=` assignments) is replaced rather
than recorded.

---

## How it compares

Most Claude memory and token skills are documents. They tell Claude to be careful
with context, which is good advice, but a document cannot search your transcripts
or tell you whether it worked.

| | Executable code | Tests | Searches your history | Runs without being asked |
|---|---:|---:|---|---|
| `context-budget` | 0 files | none | no | no |
| `token-budget-advisor` | 0 files | none | no | no |
| `rescue-tokens` | 0 files | none | no | no |
| `mem-search` | 0 files | none | no | no |
| `smart-explore` | 0 files | none | no | no |
| `timeline-report` | 0 files | none | no | no |
| `claude-mem` | 7 files | none | yes, via MCP | yes, via MCP |
| **claude-rework** | **17 files** | **9 suites** | **yes** | **yes** |

claude-mem is the closest comparable project. It uses an MCP server for
everything, which means its tool schemas occupy context in every session whether
you use them or not.

Against the approaches you would otherwise take:

| | grep | a RAG service | `/compact` | `CLAUDE.md` | claude-rework |
|---|---|---|---|---|---|
| Finds a decision from months ago | yes, expensively | yes | no, it is gone | only what you typed | yes |
| Cost per answer | ~211k tokens | API calls | free but lossy | always in context | ~2.5k tokens |
| Data leaves your machine | no | yes | no | no | no |
| Needs an account or key | no | yes | no | no | no |
| Survives an account switch | n/a | yes | no | copy it by hand | yes, one command |

---

## Requirements

Python 3.9 or newer, and Claude. That is the hard requirement.

`numpy` and `model2vec` are installed automatically and add semantic search,
which finds answers that share no words with your question. If they cannot be
installed, on an offline or locked-down machine, everything still works using
keyword ranking and the installer says so rather than failing.

Windows, macOS, and Linux are all tested in CI on Python 3.10 and 3.12, on every
push. The test is a full install into a machine that has never seen the tool,
followed by using it and uninstalling it.

You can run the test suites yourself:

```bash
claude-rework test
```

Nine suites cover retrieval accuracy, adversarial input, the hooks, index
staleness, concurrent index builds, hostile parameter cards, and every
subcommand. Each has a floor and the run fails if any drops below it. Retrieval
is measured on questions generated from your own corpus, with the most
distinctive word removed so nothing passes by exact match.

---

## Limitations

It is only as good as the history you give it. A fresh Claude Code install has
no transcripts yet, so there is nothing to remember on day one. If your history
is elsewhere, bring it: `import` from another machine or account, or `import-web`
from a Claude data export.

`--brief` decides a request is finished by checking whether a later message reads
like a conclusion about the same thing. It is usually right, and it tells you it
is a heuristic.

The automatic lookup matches the grammar of a question about the past rather
than understanding intent. It was measured on 24 unconventional phrasings and 30
forward-looking prompts: it catches all 24 and fires on none of the 30. Ask in a
way it has no grammatical handle on and it stays quiet, and you can ask directly.

An embedding model was tried for this first and measurably failed. Averaged token
vectors encode topic, not intent, so "fix the bug I just introduced" scored
higher against the anchors than every genuine question about the past. There was
no threshold that separated them, so it was not shipped.

Every ranking threshold was tuned on one person's corpus. That is why the test
suite builds synthetic machines with unrelated vocabularies, in different
languages and sizes, and runs the real pipeline against them. It found a genuine
bug the first time it ran: a frequency floor that let a word appearing in every
record still count, which is invisible on a large diverse corpus and severe on a
small one.

---

MIT licensed. Issues and pull requests are welcome.
