"""PreToolUse hook: block banned phrases and em dashes from reaching prose files.

Wire it to Write and Edit. Only the text being written is checked, so old text
in a file does not block an edit. Exit 2 blocks the call and shows stderr to Claude.

Rules are a JSON file, read from the first of these that exists:
  $GUARDRAILS_WRITING_CONFIG
  $CLAUDE_PROJECT_DIR/.claude/writing-rules.json
  ~/.claude/writing-rules.json

  {"em_dash": true, "banned": ["in order to"], "include": ["*.md", "*.mdx", "*.txt"]}

Also works on named files, for a pre-commit hook or CI:
  python3 check-writing.py README.md docs/guide.md
"""
import fnmatch
import json
import os
import re
import sys

DEFAULTS = {"em_dash": True, "banned": [], "include": ["*.md", "*.mdx", "*.txt"]}


def config_path():
    return next((p for p in (
        os.environ.get("GUARDRAILS_WRITING_CONFIG"),
        os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", ""), ".claude", "writing-rules.json"),
        os.path.expanduser("~/.claude/writing-rules.json"),
    ) if p and os.path.exists(p)), None)


def load_config():
    path = config_path()
    if not path:
        return DEFAULTS
    with open(path, encoding="utf-8") as f:
        rules = json.load(f)
    if not isinstance(rules, dict):
        raise ValueError("the rules file must hold a JSON object")
    config = {**DEFAULTS, **rules}
    if not isinstance(config["em_dash"], bool):
        raise ValueError("`em_dash` must be true or false")
    for key in ("banned", "include"):
        items = config[key]
        if not isinstance(items, list) or not all(isinstance(i, str) and i.strip() for i in items):
            raise ValueError(f"`{key}` must be a list of non-empty strings")
    return config


def find_problems(text, config):
    found = []
    if config["em_dash"]:
        found += [(m.start(), "em dash") for m in re.finditer("—", text)]
    for phrase in config["banned"]:
        words = r"\s+".join(re.escape(w) for w in phrase.split())
        for m in re.finditer(rf"(?<!\w){words}(?!\w)", text, re.IGNORECASE):
            found.append((m.start(), f'banned phrase "{phrase}"'))
    return [f"line {text.count(chr(10), 0, at) + 1}: {what}" for at, what in sorted(found)]


def included(path, patterns):
    # Lowered by hand, because fnmatch only ignores case on Windows and macOS files do too.
    path = path.lower()
    return any(fnmatch.fnmatchcase(path, p.lower()) or fnmatch.fnmatchcase(os.path.basename(path), p.lower())
               for p in patterns)


def report(label, problems):
    print(f"Blocked by check-writing, {label}: " + "; ".join(problems) +
          ". Rewrite the text in plain words.", file=sys.stderr)
    return 2


def check_tool_call(config):
    tool_input = json.load(sys.stdin).get("tool_input", {})
    path = tool_input.get("file_path", "")
    if not path or not included(path, config["include"]):
        return 0
    parts = [tool_input.get(k) or "" for k in ("content", "new_string")]
    parts += [edit.get("new_string") or "" for edit in tool_input.get("edits") or []]
    problems = find_problems("\n".join(parts), config)
    return report(path, problems) if problems else 0


def main():
    try:
        config = load_config()
    except (OSError, ValueError, TypeError, RecursionError) as e:
        print(f"check-writing could not read its rules at {config_path()}: {e}", file=sys.stderr)
        return 2

    if sys.argv[1:]:
        status = 0
        for path in sys.argv[1:]:
            with open(path, encoding="utf-8") as f:
                problems = find_problems(f.read(), config)
            if problems:
                status = report(path, problems)
        return status

    try:
        return check_tool_call(config)
    except (ValueError, AttributeError, TypeError) as e:
        print(f"check-writing could not read this tool call: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
