# Security

## Reporting a vulnerability

Open a [private security advisory](https://github.com/Luneswan/claude-rework/security/advisories/new).
Please do not open a public issue for anything exploitable.

Include what you did, what happened, and what you expected. A proof of concept
helps. You will get a reply within a few days.

## What this software touches

Worth being precise, because this is a tool that reads your entire Claude history.

**Reads:** `~/.claude/projects/**/*.jsonl` (your transcripts), your notes, and
per-project `CLAUDE.md` files.

**Writes:** an extracted index and vectors under `~/.claude/`, an activity log,
and, only when you run the installer, hook entries in `settings.json` and one
MCP entry in `claude_desktop_config.json`. Every config file is copied to
`<file>.bak.<timestamp>` before it is modified.

**Network:** none, with two exceptions, both of which you trigger by hand:

1. `pip install` of the optional `numpy` / `model2vec` extras, and the one-time
   ~36 MB model download. After that, searching is fully offline.
2. `recall_share.py --pull <url>`, which fetches tuning integers. It is opt-in
   and never runs on its own.

**Never transmitted:** your prompts, answers, file paths, project names, note
contents, or corpus. There is no telemetry and no account.

## Design decisions that are security decisions

**Secrets are scrubbed before they are written, not after.** The activity log
matches commands against a pattern covering `sk-`, `ghp_`, `hf_`, `xox*`, `AKIA`,
`--password`, auth headers, and `*_TOKEN=` assignments, and replaces the match.

This had a real bug, found by this repository's own tests: `Authorization:\s*\S+`
consumes exactly one token after the colon, and in the standard
`Authorization: Bearer <token>` form that token is the word "Bearer", so the
credential reached disk in the clear. It now consumes the scheme *and* the value,
and there is a test per credential shape, because passing on three shapes tells
you nothing about the fourth.

**A pulled tuning card is untrusted input.** Every field is checked against a
type and a range; the whole card is rejected on any bad field; a hostile card
cannot crash the import and take the good ones with it. Only integers are ever
adopted; the code cannot fetch or execute anything it pulls.

**An imported bundle is untrusted input.** Archive member paths are validated
before use: no absolute paths, no `..`, no separators inside a segment. A bundle
cannot write outside `~/.claude`.

**Code travels through review, never automatically.** There is no self-update
that executes downloaded code without you asking. `claude-rework update` is a
command you run.

**Hooks fail open.** Every hook wraps its work and exits 0 on any error. A
failure in this tool must never break your session.

## Scope

In scope: path traversal, code execution, credential leakage into logs or
bundles, and anything that lets a crafted transcript, bundle, or tuning card
affect execution.

Out of scope: the contents of your own transcripts (that is your data, on your
machine), and the security of Claude itself.
