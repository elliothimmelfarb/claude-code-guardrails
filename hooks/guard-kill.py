"""PreToolUse hook: block process-kill commands that can hit far more than intended.

macOS pkill stops parsing options at the pattern, and -f matches inside every
process's full path, so a short -f pattern can match every app under /Applications.
Exit 2 blocks the Bash call and shows stderr to Claude.

To switch rules off, set GUARD_KILL_ALLOW to a comma-separated list of rule names:
pkill-full, pkill-late-option, pkill-invert, pkill-user, pkill-short-pattern,
killall-regex, killall-user, kill-all, pgrep-into-kill. On Linux, pkill does read
options after the pattern, so pkill-late-option is safe to allow there.

This hook only sees the Bash tool, and it reads command text. It catches mistakes
and is not a security boundary. If it cannot understand its input, it blocks.
"""
import json
import os
import re
import shlex
import sys

HINT = ("Find the exact PID first (`pgrep -fl <pattern>`, check the list), then `kill <pid>`. "
        "Or use an exact name with options before it: `pkill -x <name>` / `killall <name>`.")

KILLERS = {"pkill", "killall", "kill"}
SHELLS = {"sh", "bash", "zsh", "dash", "ash", "ksh", "mksh", "csh", "tcsh", "fish"}
# These run the command after them, and may have options of their own.
WRAPPERS = {"sudo", "doas", "env", "nohup", "exec", "command", "builtin", "time", "timeout", "gtimeout",
            "nice", "ionice", "stdbuf", "setsid", "caffeinate", "coproc", "xargs", "find"}
SHELL_WORDS = {"if", "then", "elif", "else", "while", "until", "do", "{", "!"}
SEPARATORS = r"&&|\|\||[;\n&()]|`"


PGREP_INTO_KILL = re.compile(
    r"\bp?kill\b(?!\s+-0\b)[^;&|\n]*(?:\$\(|`)\s*(?:\S*/)?pgrep\b"  # kill $(pgrep ...), but not signal 0
    r"|\bpgrep\b[^;&\n]*\|[^|;&\n]*\bxargs\b[^|;&\n]*\bp?kill\b"  # pgrep ... | xargs kill
)


def name(word):
    return word.rsplit("/", 1)[-1]


def parse(text):
    text = text.rstrip().removesuffix("\\")  # What is left of `\;` after the split on `;`.
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def commands(words):
    """The simple commands inside one parsed segment, looking through wrappers and shells."""
    while words and (words[0] in SHELL_WORDS or "=" in words[0] or re.match(r"\d*[<>]", words[0])):
        words = words[1:]
    if words[:1] == ["function"]:
        words = words[2:]
        yield from commands(words)
    elif not words:
        return
    elif name(words[0]) == "eval":
        yield from segments(" ".join(words[1:]))
    elif name(words[0]) in WRAPPERS:
        # Try every later word, because the first match can be an option value (`timeout -s kill 5 ...`).
        for i, word in enumerate(words):
            if i and name(word) in KILLERS | SHELLS | {"eval"}:
                yield from commands(words[i:])
            elif word in ("-S", "--split-string") and "env" in map(name, words[:i]):
                yield from segments(" ".join(words[i + 1:]))
    elif name(words[0]) in SHELLS:
        for i, word in enumerate(words):
            if word.startswith("<<<"):
                yield from segments(word[3:] or " ".join(words[i + 1:i + 2]))
        flag = next((i for i, w in enumerate(words) if re.fullmatch(r"[-+][a-zA-Z]*c[a-zA-Z]*", w)), None)
        if flag is not None:
            script = next((w for w in words[flag + 1:] if not w.startswith(("-", "+"))), None)
            if script:
                yield from segments(script)
    else:
        yield words


def piped_text(left, right):
    """Commands in the text of `echo '...' | bash`."""
    sink = parse(re.split(SEPARATORS, right)[0])
    source = parse(re.split(SEPARATORS, left)[-1])
    if source and name(source[0]) in ("echo", "printf") and SHELLS & set(map(name, sink)):
        yield from segments(" ".join(w for w in source[1:] if not w.startswith("-")))


def segments(cmd):
    # Split compound commands into simple ones; good enough for the shapes agents write.
    # The split ignores quotes, so quoted text with a separator can be read as a command.
    # That errs toward blocking.
    cmd = re.sub(r"\d*[<>]&\d+", " ", cmd.replace("\\\n", ""))
    stages = re.split(r"(?<!\|)\|(?!\|)", cmd)
    for left, right in zip(stages, stages[1:]):
        yield from piped_text(left, right)
    for part in re.split(SEPARATORS + r"|\|", cmd):
        yield from commands(parse(part))


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


def parse_options(args, with_value):
    """The short option letters and the operands of a command line."""
    letters, operands, takes_value = "", [], False
    for a in args:
        if takes_value:
            takes_value = False
        elif a.startswith("-"):
            flags = short_flags(a, with_value)
            letters += flags
            takes_value = bool(flags) and flags[-1] in with_value and len(flags) == len(a) - 1
        else:
            operands.append(a)
    return letters, operands


def problems(words):
    prog, args = name(words[0]), words[1:]
    if prog == "pkill":
        with_value = "FGgPstUuJc"
        full = any(len(a) > 3 and "--full".startswith(a) for a in args)
        if full or any("f" in short_flags(a, with_value.replace("c", "")) for a in args):
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
        letters, operands = parse_options(args, with_value)
        exact = "x" in letters or "--exact" in args
        if "v" in letters or "--inverse" in args:
            yield "pkill-invert", "`pkill -v` signals every process that does not match"
        by_user = set("Uu") & set(letters) or any(a.split("=")[0] in ("--euid", "--uid") for a in args)
        if by_user and not (exact and operands):
            yield "pkill-user", "selecting by user without `-x <name>` reaches every process that user runs"
        for pattern in operands:
            size = len(re.sub(r"\W", "", pattern))
            if size == 0 or (size < 3 and not exact):
                yield "pkill-short-pattern", "a pattern this short matches inside almost every process name"
    if prog == "killall":
        if "--regexp" in args or any(set("mr") & set(short_flags(a, "stuc")) for a in args):
            yield "killall-regex", "`killall -m` and `killall -r` treat the name as a regex"
        letters, operands = parse_options(args, "stuc")
        if "u" in letters and not operands:
            yield "killall-user", "`killall -u` with no name signals every process that user runs"
    # A leading -1 is SIGHUP; -1 after a signal or `--` is "every process you own".
    if prog == "kill" and any(re.fullmatch(r"-0*1", a) for a in args[1:]):
        yield "kill-all", "`kill -1` signals every process you own"


def findings(cmd):
    if PGREP_INTO_KILL.search(cmd.replace("\\\n", "")):
        yield "pgrep-into-kill", "this kills whatever pgrep matches, with nobody reading the list first"
    for words in segments(cmd):
        yield from problems(words)


def main():
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "Bash":
            return 0
        allowed = set(os.environ.get("GUARD_KILL_ALLOW", "").replace(" ", "").split(","))
        cmd = data.get("tool_input", {}).get("command", "")
        for rule, why in findings(cmd):
            if rule not in allowed:
                print(f"Blocked by guard-kill ({rule}): {why}. {HINT}", file=sys.stderr)
                return 2
        return 0
    except Exception as e:  # A guard that cannot read its input must not let the call through.
        print(f"Blocked by guard-kill: it could not read this command ({type(e).__name__}). "
              "Rewrite it as one plain command.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
