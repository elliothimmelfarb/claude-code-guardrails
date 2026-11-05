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
]
ALLOW = [
    "pkill -x vite",
    "pkill -U 501 -x cat",
    "pkill -Ufred -x cat",  # the f belongs to the user name
    "killall Spotify",
    "killall -u tim Spotify",
    "kill 12345",
    "kill -9 12345",
    "pgrep -f node",
    "git commit -m 'stop using pkill -f'",
    "echo pkill -f node",
    "sudo ls -la",
    "bash -c 'ls -la'",
    "ls -la",
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
        self.assertEqual(run("pkill node -u someuser", env).returncode, 0)
        self.assertEqual(run("pkill -f node", env).returncode, 2)

    def test_message_names_the_rule_and_the_way_out(self):
        err = run("pkill -f node").stderr
        self.assertIn("pkill-full", err)
        self.assertIn("pgrep", err)


if __name__ == "__main__":
    unittest.main()
