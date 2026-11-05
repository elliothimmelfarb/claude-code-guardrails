"""PreToolUse hook: block process-kill commands that can hit far more than intended.

macOS pkill stops parsing options at the pattern, and -f matches inside every
process's full path, so a short -f pattern can match every app under /Applications.
Exit 2 blocks the Bash call and shows stderr to Claude.

To switch rules off, set GUARD_KILL_ALLOW to a comma-separated list of rule names:
pkill-full, pkill-late-option, killall-regex, kill-all. On Linux, pkill does read
options after the pattern, so pkill-late-option is safe to allow there.
"""
import json
import os
import re
import shlex
import sys

HINT = ("Find the exact PID first (`pgrep -fl <pattern>`, check the list), then `kill <pid>`. "
        "Or use an exact name with options before it: `pkill -x <name>` / `killall <name>`.")

KILLERS = {"pkill", "killall", "kill"}
SHELLS = {"sh", "bash", "zsh", "dash"}
# These run the command after them, and may have options of their own.
WRAPPERS = {"sudo", "env", "nohup", "exec", "command", "time", "timeout", "nice", "xargs"}
SHELL_WORDS = {"if", "then", "elif", "else", "while", "until", "do", "{", "!"}


def name(word):
    return word.rsplit("/", 1)[-1]


def segments(cmd):
    # Split compound commands into simple ones; good enough for the shapes agents write.
    # The split ignores quotes, so quoted text with a separator can be read as a command.
    # That errs toward blocking.
    for part in re.split(r"&&|\|\||[;|\n&()]|`", cmd):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        while words:
            if words[0] in SHELL_WORDS or "=" in words[0]:
                words = words[1:]
            elif name(words[0]) in WRAPPERS:
                inner = [i for i, w in enumerate(words) if i and name(w) in KILLERS | SHELLS]
                words = words[inner[0]:] if inner else []
            else:
                break
        if words and name(words[0]) in SHELLS:
            flag = next((i for i, w in enumerate(words) if re.fullmatch(r"-[a-z]*c", w)), None)
            if flag is not None and flag + 1 < len(words):
                yield from segments(words[flag + 1])
        elif words:
            yield words


def short_flags(arg, with_value):
    """Letters of a cluster like -lf, stopping at a flag whose value is attached (-Uroot)."""
    if not arg.startswith("-") or arg.startswith("--"):
        return ""
    letters = ""
    for ch in arg[1:]:
        letters += ch
        if ch in with_value:
            break
    return letters


def problems(words):
    prog, args = name(words[0]), words[1:]
    if prog == "pkill":
        with_value = "FGgPstUuJc"
        if "--full" in args or any("f" in short_flags(a, with_value) for a in args):
            yield "pkill-full", "`pkill -f` matches anywhere in every process's full command line"
        operand_seen = takes_value = False
        for a in args:
            if takes_value:
                takes_value = False
            elif a.startswith("-"):
                if operand_seen:
                    yield ("pkill-late-option",
                           "macOS pkill ignores options after the pattern, so `%s` would not apply" % a)
                flags = short_flags(a, with_value)
                takes_value = bool(flags) and flags[-1] in with_value and len(flags) == len(a) - 1
            else:
                operand_seen = True
    if prog == "killall":
        if "--regexp" in args or any(set("mr") & set(short_flags(a, "stuc")) for a in args):
            yield "killall-regex", "`killall -m` and `killall -r` treat the name as a regex"
    # A leading -1 is SIGHUP; -1 after a signal or `--` is "every process you own".
    if prog == "kill" and "-1" in args[1:]:
        yield "kill-all", "`kill -1` signals every process you own"


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return 0
    allowed = set(os.environ.get("GUARD_KILL_ALLOW", "").replace(" ", "").split(","))
    cmd = data.get("tool_input", {}).get("command", "")
    for words in segments(cmd):
        for rule, why in problems(words):
            if rule not in allowed:
                print(f"Blocked by guard-kill ({rule}): {why}. {HINT}", file=sys.stderr)
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
