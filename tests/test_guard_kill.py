"""Run: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import unittest

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks", "guard-kill.py")

BLOCK = [
    'pkill -f "cat" -U $(id -u) -x',  # "cat" matches inside "Applications"
    "pkill -f node",
    "pkill -fl node",
    "pkill --full node",
    "sleep 1; pkill -f vite && echo done",
    "pkill node -u someuser",  # option after the pattern is ignored on macOS
    "killall -m 'Chrome.*'",
    "killall -r 'Chrome.*'",
    "kill -9 -1",
    "kill -- -1",
    "sudo pkill -f python",
    "sudo -u root pkill -f python",  # the wrapper has its own options
    "timeout 5 pkill -f python",
    "pgrep node | xargs -r pkill -f python",
    "(pkill -f python)",
    "for p in a b; do pkill -f $p; done",
    "if true; then pkill -f python; fi",
    "{ pkill -f python; }",
    "bash -c 'pkill -f python'",
    "sudo bash -lc 'pkill -f python'",
    'echo "$(pkill -f python)"',
    # A line continuation joins the words back together.
    "pkill \\\n  -f node",
    # Shell flags can cluster around c, and -- ends them.
    "bash -ce 'pkill -f node'",
    "bash -c -- 'pkill -f node'",
    "bash -euc 'pkill -f node'",
    "sh -xec 'pkill -f node'",
    "ksh -c 'pkill -f node'",
    "csh -c 'pkill -f node'",
    "tcsh -c 'pkill -f node'",
    # "kill" here is an option value, and the real command comes later.
    "timeout -s kill 5 pkill -f node",
    "timeout --signal kill 5 pkill -f node",
    "sudo -u kill pkill -f node",
    "gtimeout 5 pkill -f node",
    "caffeinate pkill -f node",
    # Text handed to a shell another way.
    "echo 'pkill -f node' | bash",
    "echo 'pkill -f node' | sudo sh",
    "printf 'pkill -f node' | sh",
    "bash <<< 'pkill -f node'",
    "bash <<<'pkill -f node'",
    "eval 'pkill -f node'",
    "eval pkill -f node",
    "sudo eval pkill -f node",
    "env -S 'pkill -f node'",
    "builtin kill -9 -1",
    "find . -maxdepth 0 -exec pkill -f node \\;",
    "find . -exec bash -c 'pkill -f node' \\;",
    "2>&1 pkill -f node",
    ">/dev/null pkill -f node",
    "coproc pkill -f node",
    "function f { pkill -f node; }; f",
    "pkill --fu node",  # Linux accepts an abbreviated long option
    "pkill -cf node",  # -c takes no value on Linux, so the f still counts
    # An inverted match kills everything else.
    "pkill -v -x node",
    "pkill -vx node",
    "pkill --inverse -x node",
    # Selecting by user with no exact name reaches every process that user runs.
    "pkill -U 501",
    "pkill -U 501 node",
    "pkill -u someuser node",
    "pkill --euid 501",
    "killall -u someuser",
    # A pattern this short matches inside almost anything.
    "pkill a",
    "pkill .",
    "pkill '.*'",
    "pkill -x '.*'",
    # pgrep output is only a list once somebody has read it.
    "kill -9 $(pgrep -f cat)",
    "kill $(pgrep node)",
    "kill `pgrep node`",
    "pgrep -f cat | xargs kill -9",
    "pgrep node | sudo xargs -r kill",
    # A pid is a number, however it is written.
    "kill -9 -01",
    "kill -9 -0001",
    "kill -KILL -1",
    "kill -s KILL -1",
]
ALLOW = [
    "pkill -x vite",
    "pkill -x ls",  # exact, so a short name is safe
    "pkill vite",
    "kill -1 12345",  # SIGHUP to one process
    "kill -1",
    "killall -v Spotify",
    "pkill -U 501 -x cat",
    "pkill -Ufred -x cat",  # the f belongs to the user name
    "killall Spotify",
    "killall -u tim Spotify",
    "kill 12345",
    "kill -9 12345",
    "pgrep -f node",
    "git commit -m 'stop using pkill -f'",
    "echo pkill -f node",
    "echo 'pkill -f node' | tee note.txt",
    "sudo ls -la",
    "bash -c 'ls -la'",
    "ls -la",
    "timeout -s kill 5 ls",
    "find . -name kill",
    "env -S 'ls -la'",
    "echo hi | bash",
    "bash script.sh",
    "eval ls -la",
    "2>&1 ls",
    "while kill -0 $(pgrep -f vitest | head -1); do sleep 1; done",  # signal 0 only checks it exists
]


def run(cmd, env=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    return subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(payload),
                          capture_output=True, text=True, env={**os.environ, **(env or {})})


class GuardKill(unittest.TestCase):
    def test_blocks_dangerous_shapes(self):
        for cmd in BLOCK:
            with self.subTest(cmd):
                self.assertEqual(run(cmd).returncode, 2)

    def test_allows_safe_shapes(self):
        for cmd in ALLOW:
            with self.subTest(cmd):
                self.assertEqual(run(cmd).returncode, 0)

    def test_ignores_other_tools(self):
        payload = {"tool_name": "Write", "tool_input": {"command": "pkill -f node"}}
        r = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(payload),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)

    def test_allow_list_turns_off_only_the_named_rule(self):
        env = {"GUARD_KILL_ALLOW": "pkill-late-option"}
        self.assertEqual(run("pkill node -n", env).returncode, 0)
        self.assertEqual(run("pkill -f node", env).returncode, 2)

    def test_broken_input_blocks_instead_of_passing(self):
        for raw in ("not json", "[]", '{"tool_name":"Bash","tool_input":"x"}',
                    '{"tool_name":"Bash","tool_input":{"command":null}}',
                    '{"tool_name":"Bash","tool_input":{"command":123}}'):
            with self.subTest(raw):
                r = subprocess.run([sys.executable, "-I", GUARD], input=raw, capture_output=True, text=True)
                self.assertEqual(r.returncode, 2)
                self.assertIn("guard-kill", r.stderr)

    def test_message_names_the_rule_and_the_way_out(self):
        err = run("pkill -f node").stderr
        self.assertIn("pkill-full", err)
        self.assertIn("pgrep", err)


if __name__ == "__main__":
    unittest.main()
