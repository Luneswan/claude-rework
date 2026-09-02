# Changelog

## 1.3.0

**One-click install across the whole Claude ecosystem, and memory that survives
an account switch.**

### Added

- **Surface detection** (`claude_rework/detect.py`). The installer no longer asks
  a question a filesystem probe can answer: it finds the OS, the Claude Code
  directory, the desktop app's config (per-OS path), which surfaces are already
  connected, whether the optional extras import, and whether the index exists.
- **Every surface connected automatically.** Claude Code and its VS Code and
  JetBrains extensions via four hooks; the desktop app and Cowork via the MCP
  server. Where a surface cannot take hooks, it falls back to MCP instead of
  documenting the limitation.
- **`doctor` and `repair`.** `doctor` checks each connection the way it will
  actually be used and catches the failures that are otherwise silent: a hook
  pointing at a Python that no longer exists, a backslash in a hook command
  (bash eats them), an MCP entry orphaned by a moved interpreter, an index that
  was never built. `repair` fixes all of them and is idempotent.
- **`status`**, what is connected, what is indexed, in one screen.
- **`update`**, pip upgrade when installed from pip, otherwise re-fetch, then
  reconnect.
- **Account and machine portability** (`claude_rework/portable.py`): `export`,
  `import`, `inspect`, `profile`. A bundle carries the search index, every
  project with its real path, each project's `CLAUDE.md` and notes, the activity
  log, and a generated `who-i-am` profile so a new account knows you on its first
  message. `--with-transcripts` adds the raw sessions. Import is a merge keyed on
  `(source, timestamp, text)`: importing twice changes nothing, and a note you
  already wrote is never overwritten.
- **Double-click installers**, `install.command` (macOS), `install.ps1`
  (Windows, offers to install Python via winget), `install.sh` (Linux).
- **Optional extras install automatically**, and the install never fails when
  they cannot be fetched, it falls back to lexical ranking and says so.
- **`hooks` test suite** (13 cases). The three automatic hooks are exercised the
  way Claude Code runs them: JSON on stdin, exit 0 no matter what, including
  garbage input and the debounce.

### Fixed

- **Imported history was erased by the first index rebuild.** The builder keeps
  records whose source transcript still exists locally; migrated records point at
  the *old* machine's paths, so a rebuild discarded them, which is exactly when
  someone has just migrated and is checking whether their memory survived.
  Imported records now carry an `im` flag and are preserved across both
  incremental and `--full` rebuilds. This is what makes account switching work at
  all, and there is a regression test for the full-rebuild case.
- **`export` could bundle a stale or missing index.** Someone who installs and
  immediately migrates has never sent a message, so no hook has ever fired.
  Export now indexes first when the corpus is missing or older than the
  transcripts.

### Changed

- Config files are backed up to `<file>.bak.<timestamp>` before any modification,
  including the desktop app's config.
- README rebuilt around what the tool costs and saves, with the arithmetic shown.
- Docs: `CONTRIBUTING.md`, `SECURITY.md`, this changelog.

## 1.2.0

- Packaged for PyPI as `claude-rework`; `claude-recall` kept as a command alias.
- Trusted Publishing via GitHub Actions, no API token exists anywhere.
- CI runs the clean-room install on Ubuntu, Windows and macOS × Python 3.10/3.12.
- `install.py` bootstraps itself when piped from `curl`, with no repo on disk.
- `--this-project` / `--all-projects` scoping.

## 1.1.0

- Four hooks: `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `PreCompact`.
- MCP server for the Claude desktop app and Cowork, dependency-free stdio JSON-RPC.
- Corpus build lock and full-text dedupe. Two open Claude windows previously
  produced an index that was 56% duplicates, with one record present 122 times.
- Output selection prints distinct evidence before continuations of the same
  message.

## 1.0.0

- Initial release: extract-once index over Claude transcripts, hybrid lexical and
  semantic ranking, budget-bounded output, notes, decision ledger, session brief,
  skill tier optimizer, and the test suites.
