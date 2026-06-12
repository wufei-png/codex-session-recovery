from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
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

    def test_date_filter_defaults_to_local_timezone(self):
        local_midnight = datetime(2026, 6, 12, tzinfo=self.scanner.local_timezone())
        before_local_midnight = local_midnight - timedelta(minutes=30)
        path = (
            self.codex_home
            / "sessions"
            / "2026"
            / "06"
            / "11"
            / "rollout-2026-06-11T23-30-00-before-local-midnight.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    (
                        '{"timestamp":"%s","type":"session_meta",'
                        '"payload":{"id":"before-local-midnight","cwd":"%s","source":"cli"}}'
                    )
                    % (before_local_midnight.isoformat(), PROJECT_CWD),
                    (
                        '{"timestamp":"%s","type":"response_item",'
                        '"payload":{"type":"message","role":"user",'
                        '"content":[{"type":"input_text","text":"timezone boundary session"}]}}'
                    )
                    % (before_local_midnight.isoformat(),),
                ]
            ),
            encoding="utf-8",
        )

        result = self.scan(since="2026-06-12", timezone=None)

        self.assertNotIn("before-local-midnight", self.ids(result))
        self.assertEqual(str(self.scanner.local_timezone()), result["filters"]["timezone"])

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

    def test_table_output_includes_recovery_details_and_prompt_snippets(self):
        result = self.scan(query="keepsake", show_prompts=True)
        table = self.scanner.format_table(result)

        self.assertIn("matching reasons:", table)
        self.assertIn("source paths:", table)
        self.assertIn("codex fork active-main", table)
        self.assertIn("codex://threads/active-main", table)
        self.assertIn("first prompt: restore keepsake quest main session", table)
        self.assertIn("last prompt: restore keepsake quest main session", table)

    def test_missing_identity_fields_are_reported_without_failing_scan(self):
        session_index = self.codex_home / "session_index.jsonl"
        with session_index.open("a", encoding="utf-8") as handle:
            handle.write('\n{"cwd":"/Users/example/project","updated_at":"2026-06-12T12:00:00+08:00"}\n')

        nameless_path = self.codex_home / "sessions" / "bad" / "nameless.jsonl"
        nameless_path.parent.mkdir(parents=True, exist_ok=True)
        nameless_path.write_text(
            "\n".join(
                [
                    '{"timestamp":"2026-06-12T12:00:00+08:00","type":"session_meta","payload":{"cwd":"/Users/example/project"}}',
                    '{"timestamp":"2026-06-12T12:01:00+08:00","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"nameless event"}]}}',
                ]
            ),
            encoding="utf-8",
        )

        result = self.scan()
        warnings = "\n".join(result["warnings"])

        self.assertIn("missing thread id", warnings)
        self.assertIn("session_index.jsonl", warnings)
        self.assertIn("nameless.jsonl", warnings)
        self.assertIn("active-main", self.ids(result))

    def test_fixture_copy_is_not_real_codex_home(self):
        self.assertNotEqual(Path.home() / ".codex", self.codex_home)
        env_home = self.scanner.default_codex_home()
        self.assertNotEqual(env_home.resolve(), self.codex_home.resolve())


if __name__ == "__main__":
    unittest.main()
