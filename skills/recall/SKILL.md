---
name: recall
description: Authority on remembering and on spending context. Use to recall past sessions ("what did we decide", "we discussed this", "did I fix that already"), to save a fact worth keeping, when context fills up or a rate limit appears, before adding a tool or MCP mid-session, or when asked to compact, budget tokens, or cut cost. Supersedes context-budget, token-budget-advisor, rescue-tokens, token-optimization, mem-search and smart-explore.
metadata:
  provenance: self-improving-skills

---
# recall

Memory and token spend are the same problem: **what is worth carrying, and what it
costs to carry it.** One skill, because "should I look this up?" and "can I afford
to?" are always decided together.

```bash
R=~/.claude/skills/recall/scripts/recall.py
python $R "<question>" --budget 2000    # search every store at once
python $R --stores                      # what exists
python $R --write "<fact>" --name <slug> --type project|user|feedback|reference

python $R --budget-report               # what a session costs before you type
python $R --estimate "@file.md"         # input tokens + expected response size
python $R --timeline --days 7           # what happened, by day, across projects
python $R --gc                          # stale/duplicate notes (never deletes)

python $R --show "<name>"               # full detail for ONE hit, after searching
python $R --brief --days 2              # what was asked, done, and still open
python $R --handoff                     # what must survive a compact
python $R --decisions --days 30         # decision ledger
python $R --digest --weeks 4            # per-week rollup
python $R --optimize [--apply]          # promote/demote skills from real usage
python $R --selftune                    # re-fit parameters (deliberate, never scheduled)
```

## 1. Recall - one command, four stores

One pass over all four, ranked together, stopping at the character budget:

| store | weight | why |
|---|---|---|
| curated notes `projects/<slug>/memory/*.md` | 1.6 | hand-written: highest value per token |
| code graph `graphify-out/graph.json` | 1.3 | structure without reading files |
| procedural `skills/*/SKILL.md` | 1.15 | distilled technique, already compressed |
| transcripts + captured events | 1.0 | what was said and done; verbose |

Store priority is a **weight, not an ordering** - searching notes first and
stopping lets a weak note displace the line holding the answer.

**Never** hand-grep transcripts or read a whole `memory/` folder to answer a
recall question. One call replaces both at a bounded cost.

`--brief` replaces scrolling a session back into context: ~0.5s and a few hundred
tokens against tens of thousands. Heuristic, and it says so. Its top open threads
are injected at every session start.

## 2. Write - where a fact belongs

| the fact is... | goes to | note |
|---|---|---|
| who the user is, a standing preference | `--type user` | |
| a correction, "do it this way from now on" | `--type feedback` | include **why** |
| project goal, constraint, decision not in the code | `--type project` | absolute dates |
| a URL, dashboard, ticket | `--type reference` | |
| a repeatable *procedure* | a skill, not a note | `/distill-skill` |
| anything the repo already records | **nowhere** | code and git history are the memory |

One fact per file, linked with `[[other-note]]`. A note restating the codebase is
negative value: it costs context on every recall and goes stale silently.

## 3. Token economy - the rules that move the number

### The cache rule (biggest single lever)

Claude Code caches system instructions, the tool/MCP list, and message history.
**Any mid-session change to that set invalidates the cache and re-bills everything
downstream.**

- Do not add a tool, MCP server, plugin or heavy skill mid-session.
- Configure in a setup session, or `/compact` first and start fresh.
- Treat it like an HTTP cache: change one header, everything below goes cold.

This is why the router surfaces skill *descriptions*, not bodies - 1,300+ library
skills cost nothing until one is routed.

### Where tokens actually go

1. **Cache misses** - above.
2. **Context bloat** - reading files whole when a graph query answers it.
3. **Wrong model or effort** - deep reasoning on a lookup.
4. **Verbose input** - pasting a whole log instead of the failing 10 lines.

Estimate: prose `words x 1.3`, code `chars / 4`; response `3-8x` input for simple,
`8-20x` moderate, `10-25x` code-with-context.

### Pressure: act, do not ask

Any **one** of these is sufficient - this is not a scoring system: a rate-limit
warning, context at or above 40%, ~90+ minutes of heavy session, or the user
saying "don't lose context".

| state | action |
|---|---|
| 40-70% full | `/compact`, keeping decisions and open threads; continue |
| above 70% | `--write` a note, then start fresh with a 3-sentence handoff |
| about to add an MCP or plugin | finish the session first |

Counter the two rationalisations: *"the user wants to keep context"* - most of a
long context is spent tool output, not decisions. *"I'll lose details"* - anything
that mattered should already be a note; if it is not, write it before compacting.

### Cheapest path to an answer

Stop at the first that answers:

```
recall.py         already known?          bounded, ~1k chars
graphify query    structure of the code?  ~600 tokens, no file reads
find_skill.py     is there a tool?        one line per candidate
read the file     only now                unbounded
```

Reading source to answer "where is X" when a graph exists is the most common
avoidable spend in this setup.

## 4. `--budget-report`: know the number before arguing about it

Inventories what loads before you type: auto-loaded skill descriptions, CLAUDE.md,
the pinned ALWAYS block, hook count. It names the six most expensive descriptions,
because that is where the fat always is.

Real result here: four image-generation skills cost ~950 tokens **every session**
for an occasional capability. Moving them to `skills-library/` cut fixed cost
3,624 -> 2,644 tokens (27%), fully reachable through the router. Measure, then
move; never guess which skill is expensive.

## 5. `--optimize`: acting on the report

A report that cannot act is a nag. This reads what the router **actually did**
(`hooks/skill_usage.jsonl`) and moves skills between tiers:

| verdict | meaning | effect |
|---|---|---|
| DEMOTE | loaded, zero routes in the window | moved to `skills-library/demoted/` |
| PROMOTE | in the library, routed 4+ times | moved to `skills/`, loaded every session |
| GAP | a topic that repeatedly matched nothing | proposes `/skill-creator` or `acquire.py gap` |

**Demotion is not deletion.** Both tiers are fully routable; a demoted skill keeps
working and stops charging rent. Every move is a directory rename in a git repo.

The guards matter more than the verdicts - on a 3-prompt sample the first version
wanted to demote seven skills, including ones written that hour:

- **`MIN_SAMPLE = 40`** routed prompts before any demotion is advised.
- **`MIN_AGE_DAYS = 14`** - a skill younger than the window never had a fair chance.
- **`PROTECTED`** - graphify, deep-scrape, skill-acquire and this skill, always.
- Pinned skills in `always_skills.json` are exempt by definition.

Run it to see the verdict; add `--apply` only when you accept it.

## 6. Capture, self-tuning, federation

- **Capture** - a `PostToolUse` hook logs one line per real edit or command to
  `events.jsonl`, searchable like any other store. Transcripts hold the
  conversation, never the work. Secrets are scrubbed before writing; the hook
  cannot fail a turn.
- **`--selftune`** - re-fits parameters against fresh cases generated from the
  *current* corpus, keeping a change only if it beats the incumbent and does not
  regress the curated set. **Never scheduled**: one sweep is ~1,000 processes.
- **`recall_share.py`** - `--show`/`--export`/`--pull URL`/`--apply`. Twenty
  numbers leave, no text. Nothing uploads on a schedule, pulled cards are
  validated field by field, and only integers are ever adopted.

## 7. What this replaces

`ecc:context-budget`, `ecc:token-budget-advisor`, `valorisa/rescue-tokens`,
`valorisa/token-optimization`, `valorisa/long-context-lost-in-the-middle`,
`claude-mem:mem-search`, `claude-mem:smart-explore`, `claude-mem:timeline-report`.

Those still exist in the library and go deeper on their own topic. Read one only
when this skill points at it - loading several overlapping memory skills is itself
the waste each of them warns about.

## 8. Verify it, and go deeper

```bash
python ~/.claude/skills/recall/tests/run_tests.py       # 8 suites, each with a floor
python ~/.claude/skills/recall/tests/simulate.py        # foreign machines + optimizer
```

| suite | what it proves |
|---|---|
| known-item | retrieval on questions generated FROM the corpus, gold term held out |
| curated | the hand-written cases still pass, `fallbacks=0` |
| stress | adversarial input (empty, CJK, shell meta, 3k-char word) neither crashes nor hangs |
| subcommands | every command runs clean |
| capture | the hook records work, drops noise, redacts secrets, and cannot fail a turn |
| vectors | a stale or misaligned matrix is refused; a verified prefix is reused |
| federation | hostile cards are rejected without crashing the pull or injecting keys |
| concurrency | three simultaneous builds yield zero duplicates and leave no lock behind |

Non-zero exit if any suite drops below its floor. **Floors only ratchet up** - a
change that cannot hold one is the thing that is wrong.

Everything lives in one folder (`SKILL.md`, `scripts/`, `tests/`, `reference/`)
and paths resolve by walking up to `.claude`, so the directory is copyable to
another machine as-is. `RECALL_HOME` overrides the root.

Read these only when changing the machinery, never to use it:

| file | when |
|---|---|
| `reference/retrieval-design.md` | changing the ranker, corpus, or budget allocator |
| `reference/benchmarks.md` | changing a floor, adding a suite, quoting a score |
| `reference/operations.md` | changing self-tuning, capture, or federation |
