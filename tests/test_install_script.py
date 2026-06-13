from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "install.sh"


class InstallScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.install_dir = Path(self.tmp.name) / "skills" / "codex-session-recovery"

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(
        self, *, source_dir: Path | None = REPO_ROOT, raw_base: str | None = None
    ):
        env = os.environ.copy()
        env["CODEX_SESSION_RECOVERY_SKILL_DIR"] = str(self.install_dir)
        if source_dir is not None:
            env["CODEX_SESSION_RECOVERY_SOURCE_DIR"] = str(source_dir)
        else:
            env.pop("CODEX_SESSION_RECOVERY_SOURCE_DIR", None)
        if raw_base is not None:
            env["CODEX_SESSION_RECOVERY_RAW_BASE"] = raw_base
        env["CODEX_HOME"] = str(Path(self.tmp.name) / "unused-codex-home")
        return subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            text=True,
            capture_output=True,
            env=env,
        )

    def test_installs_only_skill_files_from_local_source(self):
        completed = self.run_install()

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue((self.install_dir / "SKILL.md").is_file())
        self.assertTrue((self.install_dir / "agents" / "openai.yaml").is_file())
        scanner = self.install_dir / "scripts" / "scan_codex_sessions.py"
        self.assertTrue(scanner.is_file())
        self.assertTrue(scanner.stat().st_mode & stat.S_IXUSR)
        self.assertFalse((self.install_dir / "README.md").exists())
        self.assertFalse((self.install_dir / "docs").exists())
        self.assertFalse((self.install_dir / "tests").exists())
        self.assertIn(str(self.install_dir), completed.stdout)

    def test_installs_from_raw_base_with_curl(self):
        completed = self.run_install(
            source_dir=None, raw_base=REPO_ROOT.as_uri()
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue((self.install_dir / "SKILL.md").is_file())
        self.assertTrue(
            (self.install_dir / "scripts" / "scan_codex_sessions.py").is_file()
        )

    def test_replaces_existing_install_without_leaving_old_files(self):
        self.install_dir.mkdir(parents=True)
        (self.install_dir / "old-file.txt").write_text("old\n", encoding="utf-8")

        completed = self.run_install()

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertFalse((self.install_dir / "old-file.txt").exists())
        self.assertTrue((self.install_dir / "SKILL.md").is_file())

    def test_failed_install_keeps_existing_target(self):
        self.install_dir.mkdir(parents=True)
        sentinel = self.install_dir / "sentinel.txt"
        sentinel.write_text("keep\n", encoding="utf-8")

        completed = self.run_install(source_dir=Path(self.tmp.name) / "missing-source")

        self.assertNotEqual(0, completed.returncode)
        self.assertTrue(sentinel.is_file())
        self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
