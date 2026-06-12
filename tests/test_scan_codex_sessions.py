from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER_PATH = REPO_ROOT / "codex-session-recovery" / "scripts" / "scan_codex_sessions.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "codex_home"
PROJECT_CWD = "/Users/example/project"


def load_scanner():
    spec = importlib.util.spec_from_file_location("scan_codex_sessions", SCANNER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ScanCodexSessionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.codex_home = Path(self.tmp.name) / "codex_home_copy"
        shutil.copytree(FIXTURE_ROOT, self.codex_home)
        self.scanner = load_scanner()

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self, **kwargs):
        defaults = {
            "codex_home": self.codex_home,
            "cwd": PROJECT_CWD,
            "since": None,
            "until": None,
            "timezone": "Asia/Shanghai",
            "query": None,
            "include_archived": False,
            "include_subagents": False,
            "limit": 20,
            "show_prompts": False,
        }
        defaults.update(kwargs)
        return self.scanner.scan(defaults)

    def ids(self, result):
        return [record["thread_id"] for record in result["records"]]

    def test_default_scan_excludes_archived_and_subagent_sessions(self):
        result = self.scan()
        self.assertIn("active-main", self.ids(result))
        self.assertIn("duplicate-main", self.ids(result))
        self.assertNotIn("archived-main", self.ids(result))
        self.assertNotIn("subagent-main", self.ids(result))

    def test_include_archived_adds_archived_sessions(self):
        result = self.scan(include_archived=True)
        self.assertIn("archived-main", self.ids(result))

    def test_include_subagents_adds_subagent_sessions(self):
        result = self.scan(include_subagents=True)
        self.assertIn("subagent-main", self.ids(result))

    def test_malformed_lines_are_reported_without_failing_scan(self):
        result = self.scan()
        warnings = "\n".join(result["warnings"])
        self.assertIn("malformed JSON", warnings)
        self.assertIn("active-main", self.ids(result))

    def test_duplicate_active_and_archived_id_is_reported(self):
        result = self.scan(include_archived=True)
        duplicate = next(record for record in result["records"] if record["thread_id"] == "duplicate-main")
        self.assertIn("appears in active and archived sources", "\n".join(duplicate["warnings"]))

    def test_date_filter_uses_configured_timezone(self):
        result = self.scan(since="2026-06-12", include_archived=True)
        self.assertIn("active-main", self.ids(result))
        self.assertNotIn("archived-main", self.ids(result))

    def test_query_filter_matches_user_prompt_text(self):
        result = self.scan(query="keepsake")
        self.assertEqual(["active-main"], self.ids(result))

    def test_json_output_contains_recovery_commands(self):
        result = self.scan()
        active = next(record for record in result["records"] if record["thread_id"] == "active-main")
        self.assertEqual("codex resume active-main", active["resume_command"])
        self.assertEqual("codex fork active-main", active["fork_command"])
        self.assertEqual("codex://threads/active-main", active["deep_link"])

    def test_table_output_mentions_confidence_and_commands(self):
        result = self.scan()
        table = self.scanner.format_table(result)
        self.assertIn("active-main", table)
        self.assertIn("confidence", table.lower())
        self.assertIn("codex resume active-main", table)

    def test_fixture_copy_is_not_real_codex_home(self):
        self.assertNotEqual(Path.home() / ".codex", self.codex_home)
        env_home = self.scanner.default_codex_home()
        self.assertNotEqual(env_home.resolve(), self.codex_home.resolve())


if __name__ == "__main__":
    unittest.main()
