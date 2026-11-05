# Agent instructions

This repo is a set of standalone Claude Code hooks. People copy single files out of `hooks/`, so each hook must work alone: one file, no imports from this repo, and no runtime dependencies beyond Python 3 or Node (plus Playwright for `check-report.cjs`).

## Layout

- `hooks/`: the hooks. Each one documents its settings in its header comment.
- `tests/`: `test_*.py` use stdlib `unittest`, `*.test.cjs` use `node:test`. `tests/fixtures/` holds the HTML pages for check-report.
- `examples/`: `settings.json` wires every hook, and `writing-rules.json` is a sample rules file. A change to how a hook is wired or configured must update these and the README.

## How hooks behave

- PreToolUse hooks read the tool call as JSON on stdin. Exit 2 blocks the call and sends stderr to Claude. Exit 0 allows it.
- Error messages tell Claude what to do instead, not just what was wrong.
- A guard that cannot read its config should block and say so, not silently pass.
- Anything specific to one machine or person (paths, phrases, widths) is a setting, never a constant.

## Testing

Run `npm ci`, then `npm test`. The Python side also runs alone with `python3 -m unittest discover -s tests`. Fix a bug by adding a failing case first. Add a test only if it would catch a real bug, and keep it small. For guard-kill, add a line to the `BLOCK` or `ALLOW` table for any command shape you change.

## Before committing

- Run `gitleaks detect --source .`.
- Keep personal names, home paths and secrets out of the repo.
- Write docs in plain sentences, with no em dashes. `python3 hooks/check-writing.py README.md AGENTS.md CLAUDE.md` checks this.
