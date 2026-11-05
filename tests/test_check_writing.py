"""Run: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HOOK = os.path.join(ROOT, "hooks", "check-writing.py")
EM_DASH = "—"
RULES = {"banned": ["in order to", "game changer"]}


def run(tool_input, rules=RULES, args=()):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "rules.json")
        with open(path, "w") as f:
            f.write(rules if isinstance(rules, str) else json.dumps(rules))
        env = {**os.environ, "GUARDRAILS_WRITING_CONFIG": path}
        return subprocess.run([sys.executable, "-I", HOOK, *args], env=env, text=True,
                              input=json.dumps({"tool_input": tool_input}), capture_output=True)


class CheckWriting(unittest.TestCase):
    def test_blocks_em_dash_in_a_new_file(self):
        r = run({"file_path": "a.md", "content": f"one\ntwo {EM_DASH} three"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("line 2", r.stderr)

    def test_blocks_banned_phrase_in_an_edit(self):
        self.assertEqual(run({"file_path": "a.md", "new_string": "In order to win"}).returncode, 2)

    def test_phrase_split_across_a_line_wrap_still_counts(self):
        self.assertEqual(run({"file_path": "a.md", "content": "in order\nto win"}).returncode, 2)

    def test_phrase_only_matches_whole_words(self):
        rules = {"banned": ["art"]}
        self.assertEqual(run({"file_path": "a.md", "content": "a smart start"}, rules).returncode, 0)

    def test_em_dash_rule_can_be_turned_off(self):
        rules = {"em_dash": False}
        self.assertEqual(run({"file_path": "a.md", "content": EM_DASH}, rules).returncode, 0)

    def test_files_outside_include_are_skipped(self):
        self.assertEqual(run({"file_path": "a.py", "content": EM_DASH}).returncode, 0)

    def test_include_is_configurable(self):
        rules = {"include": ["*/docs/*.py"]}
        self.assertEqual(run({"file_path": "/x/docs/a.py", "content": EM_DASH}, rules).returncode, 2)
        self.assertEqual(run({"file_path": "/x/src/a.md", "content": EM_DASH}, rules).returncode, 0)

    def test_broken_config_blocks_instead_of_silently_passing(self):
        for rules in ("{not json", {"banned": "a single string"}, {"banned": [""]}):
            with self.subTest(rules):
                r = run({"file_path": "a.md", "content": "fine"}, rules)
                self.assertEqual(r.returncode, 2)
                self.assertIn("rules", r.stderr)

    def test_checks_named_files_from_the_command_line(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.txt")
            with open(bad, "w", encoding="utf-8") as f:
                f.write(f"x {EM_DASH} y")
            self.assertEqual(run({}, args=[bad]).returncode, 2)

    def test_example_rules_load(self):
        with open(os.path.join(ROOT, "examples", "writing-rules.json")) as f:
            rules = json.load(f)
        self.assertEqual(run({"file_path": "a.md", "content": rules["banned"][0]}, rules).returncode, 2)
        self.assertEqual(run({"file_path": "a.md", "content": "plain words"}, rules).returncode, 0)


if __name__ == "__main__":
    unittest.main()
