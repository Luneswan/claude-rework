# How recall is measured, and why the numbers are believable

Read this before changing a floor, adding a suite, or quoting a score. Nothing
here is needed to *use* the skill.

```bash
python ~/.claude/skills/recall/tests/run_tests.py              # everything
python ~/.claude/skills/recall/tests/run_tests.py --known 300  # bigger generated set
python ~/.claude/skills/recall/tests/simulate.py --machines
python ~/.claude/skills/recall/tests/simulate.py --optimizer 100
```

## The benchmark writes itself, on purpose

A hand-written benchmark measures the author's imagination. Twelve self-written
cases scored 100% while 60 generated ones scored **76.7%** - the gap was pure
overfitting, and only visible because the generated set exists.

Generation: sample a chunk, build the query from its own content words, require
that chunk back. Two rules keep it honest - the single most distinctive word is
**held out** of the query so no trivial exact match can pass, and cases are drawn
from chunks older than today so the test is not about work just done.

## What the generated set taught that hand-written cases could not

Sweeping the per-item output cap:

| cap | generated (150) | curated (12) |
|---|---|---|
| budget/5 | 76.7% | 12/12 |
| budget/3 | 97.3% | 11/12 |
| budget/2 | 100% | 11/12 |

The two sets wanted opposite things: generated questions wanted **depth** (one
complete hit), hand-written ones wanted **breadth**. A flat cap has to pick a
loser. Graduated allocation - the top hit gets `budget/2`, later ones taper to
`budget/6` - satisfies both: **300/300 generated and 12/12 curated**.

When two benchmarks disagree, trust the one you did not write, then find the
design that serves both rather than tuning toward whichever is louder.

## A floor is a ratchet, not a dial

The first response to a suite dropping below its floor was to lower the floor.
That is not a test, it is a mood ring. Floors only move up. If a change cannot
hold the floor, the change is wrong - or the floor was measuring the wrong thing
and needs replacing with a different assertion, not a softer one.

## Portability, proven on machines that do not exist

Every threshold here was fitted to one corpus, which is the honest limit behind
any score. `simulate.py` builds throwaway `.claude` roots with deliberately alien
data - four vocabularies with nothing in common, 40 to 4,000 records, one
non-English - and runs the real pipeline against them.

It found a real bug on the first honest run:

| corpus | before | after |
|---|---|---|
| tiny (40 records, 12-word vocabulary) | 44% | **100%** |
| huge (4,000 records) | 64% | **100%** |
| non-English | 88% | **100%** |
| sparse (6-word vocabulary) | 92% | **100%** |

The cause was one constant: the IDF floor was `0.3`, so a word appearing in
*every* record still scored. Six ubiquitous words (6 x 3 x 0.3 = 5.4) outvoted a
unique identifying term (1.23). On a naturally diverse corpus this is invisible -
almost nothing is ubiquitous - so it survived 300 real questions at 100%. Floor
lowered to `0.02`; the real corpus stayed at 100%.

**A parameter that never hurts on your data can still be wrong.** Simulating a
different corpus is how you find out.

`--optimizer N` runs randomised promote/demote rounds against synthetic skill
trees and asserts the invariants: no file ever disappears, nothing moves below the
evidence gate, no crash. **100/100 clean.**

### Three test bugs came first

Worth recording, because each looked exactly like a product failure:

1. Pointing `HOME` at a fake machine changed nothing - the tool resolves its data
   directory from `__file__`. Everything scored **0%**. Fixed by adding an explicit
   `RECALL_HOME` override, which is also the feature that makes a second machine
   possible at all.
2. Synthetic records spanned 60 days while recall defaults to a 45-day window, so
   a quarter were unreachable by construction.
3. Only after both did the real defect surface.

When a new test reports catastrophe, suspect the test first - but keep going until
you have found something real, because the third run is where the bug was.

### A test that damages real data is a bug in the test

An early optimizer test lowered `MIN_SAMPLE` against the **live** `~/.claude` and
demoted a real skill. Every suite that exercises destructive behaviour must build
its own root under `tempfile.mkdtemp()`, point `RECALL_HOME` at it, and delete it
in a `finally` block. If a test can reach the real tree, assume one day it will.
