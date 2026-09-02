# Contributing

Thanks for looking. This project has one unusual rule and everything else is ordinary.

## The one rule

**A change that cannot hold the test floors is the thing that is wrong.**

Every suite has a floor in `claude_rework/payload/skills/recall/tests/run_tests.py`.
Floors only ratchet up. If your change drops one, the fix is the change, not the
floor. The single exception is when a floor turns out to be measuring the wrong
thing, in which case replace the assertion, and say so in the PR.

That rule exists because the first instinct here was to lower a floor rather than
fix a regression, and the result was a benchmark that agreed with whatever it was
told.

## Running the tests

```bash
git clone https://github.com/Luneswan/claude-rework && cd claude-rework

# the real test: install into a machine that has never seen this
python tests/clean_room_test.py

# the retrieval and safety suites, against your own corpus
claude-rework test
claude-rework test --known 300      # bigger generated set
```

`tests/clean_room_test.py` builds a throwaway `~/.claude` with synthetic
transcripts, strips the optional binary from `PATH`, installs, uses, exports,
imports into a *second* fake account, and uninstalls. It is the test that
matters, because it is the only one that exercises what a stranger experiences.

CI runs it on Ubuntu, Windows and macOS × Python 3.10 and 3.12 on every push.
Windows is not optional: the hook-path bug that once killed everything silently
was Windows-only.

## Adding a test

Prefer generated cases to hand-written ones. Twelve cases written by hand scored
100% while sixty generated from the same corpus scored 76.7%. The gap was pure
overfitting, invisible until the generated set existed.

If you are testing something destructive, build the fixture under
`tempfile.mkdtemp()`, point `RECALL_HOME` at it, and delete it in a `finally`.
A suite that can reach the real `~/.claude` will eventually damage it.

## Code style

Match the file you are editing. Beyond that:

- **Comments explain why, never what.** If a constant has a number in it, the
  comment says what was measured to arrive at that number.
- **Record what did not work, with its measurement.** Three plausible ideas here
  are commented out with the numbers that killed them, so nobody re-adds them on
  intuition.
- **Hooks must fail open.** Any exception prints nothing and exits 0. A memory
  feature that can break a turn is a bug generator.
- **Forward slashes in hook commands, always.** Claude Code runs them through a
  shell; on Windows that shell is bash, which eats backslashes.
- Standard library only in the core. `numpy` and `model2vec` are optional extras
  and everything must still work without them.

## Pull requests

Say what you measured. "Feels faster" is not a result; "0.75s → 0.41s median over
150 generated queries" is. If a change is a judgement call rather than a
measurement, say that too; that is fine, it just needs to be visible.

Small PRs get read quickly. A PR that changes retrieval behaviour without a
number attached will get one question back, and it will be "what did it score?"

## Reporting a bug

`claude-rework doctor` first: it catches the common silent failures and prints
what is wrong. Include its output, your OS, and your Python version.

If it involves your own history, **do not paste transcripts**. The bug is almost
always reproducible from `claude-rework status` plus a description.
