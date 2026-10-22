"""Unit tests for project-local configuration and path safety."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("interview_copilot_root_config", ROOT / "app" / "core" / "config.py")
assert _spec and _spec.loader
root_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(root_config)


class RootConfigSafetyTests(unittest.TestCase):
    def test_boolean_values_are_parsed_consistently(self):
        with patch.object(root_config, "_FILE_ENV", {"FLAG": " YES "}):
            self.assertTrue(root_config._env_bool("FLAG", "false"))
        with patch.object(root_config, "_FILE_ENV", {"FLAG": "off"}):
            self.assertFalse(root_config._env_bool("FLAG", "true"))

    def test_relative_resume_path_stays_inside_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            resume = root / "resume.txt"
            resume.write_text("candidate context", encoding="utf-8")
            with patch.object(root_config, "ROOT", root), patch.object(
                root_config, "_FILE_ENV", {"RESUME_CONTEXT_PATH": "resume.txt"}
            ):
                self.assertEqual(root_config.resume_path(), resume)

    def test_resume_path_traversal_falls_back_to_project_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            default_resume = root / "local_data" / "resume_context.txt"
            default_resume.parent.mkdir(parents=True, exist_ok=True)
            default_resume.write_text("local resume", encoding="utf-8")
            with patch.object(root_config, "ROOT", root), patch.object(
                root_config, "_FILE_ENV", {"RESUME_CONTEXT_PATH": "../outside.txt"}
            ):
                self.assertEqual(root_config.resume_path(), default_resume)

    def test_api_key_check_rejects_empty_or_wrong_prefix(self):
        with patch.object(root_config, "OPENAI_API_KEY", ""):
            self.assertFalse(root_config.openai_key_configured())
        with patch.object(root_config, "OPENAI_API_KEY", "not-a-key"):
            self.assertFalse(root_config.openai_key_configured())
        with patch.object(root_config, "OPENAI_API_KEY", "sk-test-placeholder"):
            self.assertTrue(root_config.openai_key_configured())


if __name__ == "__main__":
    unittest.main()
