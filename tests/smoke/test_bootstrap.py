"""Smoke tests for startup bootstrap failures and project isolation."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT, ROOT / "app", ROOT / "app" / "core"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import project_bootstrap


class BootstrapSmokeTests(unittest.TestCase):
    def test_missing_env_fails_with_actionable_message(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env_file = root / ".env"
            with patch.object(project_bootstrap, "ROOT", root), patch.object(
                project_bootstrap, "ENV_FILE", env_file
            ):
                with self.assertRaises(SystemExit) as caught:
                    project_bootstrap.assert_env_file()
        self.assertIn("Missing", str(caught.exception))
        self.assertIn(".env", str(caught.exception))

    def test_bootstrap_checks_env_and_returns_project_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env_file = root / ".env"
            env_file.write_text("OPENAI_API_KEY=test-placeholder\n", encoding="utf-8")
            with patch.object(project_bootstrap, "ROOT", root), patch.object(
                project_bootstrap, "ENV_FILE", env_file
            ), patch.object(project_bootstrap, "ensure_project_root") as ensure_root:
                result = project_bootstrap.bootstrap()
        self.assertEqual(result, root)
        ensure_root.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
