# claude-code-guardrails

This repo holds three small checks you can wire into Claude Code as hooks. Each one is a single file with no runtime dependencies, except that the report check needs Playwright. A hook can block a tool call even in bypass permissions mode, so these rules hold when a written instruction would be forgotten.

| Hook | Runs on | Needs |
| --- | --- | --- |
| `hooks/guard-kill.py` | PreToolUse, Bash | Python 3 |
| `hooks/check-writing.py` | PreToolUse, Write and Edit | Python 3 |
| `hooks/check-report.cjs` | PostToolUse, Write and Edit | Node and Playwright |

## What each guard catches

### guard-kill

This hook blocks process-kill commands that can reach far more processes than intended. On macOS, `pkill` stops reading options at the pattern, and `-f` matches anywhere in a process's full path. A short pattern like "cat" therefore matches "Applications", which can quit every running app.

For example, `pkill -f cat -U 501` is blocked, and Claude is told to run `pgrep -fl cat`, check the list, and then `kill` the exact PID. `pkill -x cat` is allowed.

It looks inside `sudo`, `timeout`, `xargs`, subshells, loops and `bash -c`. Each rule has a name:

| Rule | Blocks |
| --- | --- |
| `pkill-full` | `pkill -f`, `pkill --full` |
| `pkill-late-option` | an option placed after the pattern, which macOS ignores |
| `killall-regex` | `killall -m`, `killall -r` |
| `kill-all` | `kill -9 -1`, which signals every process you own |

To turn a rule off, list it in the `GUARD_KILL_ALLOW` environment variable. Linux `pkill` does read options after the pattern, so Linux users can set `GUARD_KILL_ALLOW=pkill-late-option`.

### check-writing

This hook blocks em dashes and phrases you have banned from reaching prose files. It only checks the text being written, so old text in a file does not block an edit. Matching ignores case, needs whole words, and follows a phrase across a line wrap.

For example, with `"banned": ["in order to"]`, writing "In order to ship" to `notes.md` is blocked with `line 1: banned phrase "in order to"`.

Rules live in a JSON file. See `examples/writing-rules.json`.

```json
{
  "em_dash": true,
  "banned": ["in order to", "game changer"],
  "include": ["*.md", "*.mdx", "*.txt"]
}
```

The hook uses the first of these files that exists: the path in `GUARDRAILS_WRITING_CONFIG`, then `.claude/writing-rules.json` in the project, then `~/.claude/writing-rules.json`. With no file at all, it blocks em dashes in `.md`, `.mdx` and `.txt` files. If the rules file is broken, the hook blocks and says why, because a guard that silently stops working is worse than a loud one.

You can also run it on files from a pre-commit hook or CI: `python3 hooks/check-writing.py README.md`.

### check-report

This check opens an HTML page in a real browser at desktop and phone width. It fails if the page scrolls sideways or if text is squeezed to about one word per line, and it saves `check-desktop.png` and `check-phone.png` so you can look for yourself.

For example, a page with a fixed `width: 800px` block passes a glance on a laptop but fails with `[phone] page scrolls sideways (816px wide)`.

As a hook, it runs after Claude writes a file whose path matches `CHECK_REPORT_MATCH`, and sends any problems back to Claude. The default is every `.html` or `.htm` file. The example settings narrow it to a `reports` folder.

You can also run it directly: `node hooks/check-report.cjs report.html [outDir]`. It exits 0 when clean, 1 on layout problems, and 2 when the check could not run.

| Setting | Default | Purpose |
| --- | --- | --- |
| `CHECK_REPORT_MATCH` | `\.html?$` | Regex a path must match in hook mode |
| `CHECK_REPORT_WIDTHS` | `desktop=1440,phone=390` | Names and widths to test |
| `PLAYWRIGHT_PATH` | none | Where Playwright is, if Node cannot find it |

## Install

1. Clone this repo and copy the hooks you want:

   ```sh
   mkdir -p ~/.claude/hooks
   cp hooks/guard-kill.py hooks/check-writing.py hooks/check-report.cjs ~/.claude/hooks/
   ```

2. Merge the blocks you want from `examples/settings.json` into `~/.claude/settings.json`. Here is the guard-kill block on its own:

   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Bash",
           "hooks": [
             { "type": "command", "command": "python3 -I ~/.claude/hooks/guard-kill.py", "timeout": 10 }
           ]
         }
       ]
     }
   }
   ```

3. For check-writing, copy `examples/writing-rules.json` to `~/.claude/writing-rules.json` and edit the list.

4. For check-report, make Playwright available by running `npm install -g playwright` and pointing `PLAYWRIGHT_PATH` at it, or by adding it to the project you are working in. It uses Playwright's Chromium if installed, and otherwise your installed Chrome.

5. Start a new session and try it. `true || pkill -f zzq9x` should come back blocked, and it would not have killed anything if it had run.

## Limits

These checks catch common mistakes. They are not a security boundary, and a determined agent can get around them, for example by running a script file that calls `pkill`. guard-kill reads the command text, so a quoted string containing a separator, like `git commit -m 'a; pkill -f b'`, is blocked by mistake. It errs toward blocking on purpose.

## Tests

Run these from a clean clone:

```sh
npm ci
npx playwright install chromium   # skip if you have Chrome
npm test
```

The Python tests need only Python 3 and run on their own with `python3 -m unittest discover -s tests`.

## License

MIT. See `LICENSE`.
