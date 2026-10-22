"""Smoke/regression checks for the supported launcher contracts."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LaunchContractTests(unittest.TestCase):
    def test_windows_launcher_uses_current_runner(self):
        launcher = (ROOT / "start_interview_copilot.bat").read_text(encoding="utf-8")
        self.assertIn('"%~dp0app\\run_app.py"', launcher)
        self.assertIn("pythonw.exe", launcher)
        self.assertNotIn("run_setup", launcher.lower())

    def test_macos_launcher_uses_project_venv_and_env(self):
        launcher = (ROOT / "scripts" / "run.sh").read_text(encoding="utf-8")
        self.assertIn('"$ROOT/venv/bin/python"', launcher)
        self.assertIn('"$ROOT/.env"', launcher)
        self.assertIn('"$ROOT/app/main.py"', launcher)

    def test_moved_modules_exist_and_application_sources_are_not_at_root(self):
        expected = (
            "app/main.py",
            "app/run_app.py",
            "app/core/config.py",
            "app/core/project_bootstrap.py",
            "app/services/openai_service.py",
            "app/services/coding_detector.py",
            "app/services/response_parser.py",
            "app/ui/overlay.py",
            "app/screen/screen_capture.py",
            "app/screen/screen_watcher.py",
            "app/monitoring/latency_tracker.py",
            "app/setup/installer.py",
            "packaging/main.spec",
        )
        for relative in expected:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file(), relative)

        for old_root_module in (
            "main.py", "run_app.py", "config.py", "project_bootstrap.py",
            "openai_service.py", "coding_detector.py", "response_parser.py",
            "overlay.py", "screen_capture.py", "screen_watcher.py",
            "latency_tracker.py", "installer.py", "main.spec",
            "resume_context.txt",
        ):
            with self.subTest(root_module=old_root_module):
                self.assertFalse((ROOT / old_root_module).exists(), old_root_module)

    def test_resume_context_is_git_ignored(self):
        self.assertTrue((ROOT / "local_data").is_dir())
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("local_data/resume_context.txt", ignore)

    def test_standalone_setup_runner_stays_removed(self):
        self.assertFalse((ROOT / "run_setup.bat").exists())
        self.assertFalse((ROOT / "run_setup.py").exists())
        for path in (ROOT / "README.md", ROOT / "wboxai_app" / "README.md", ROOT / "start_interview_copilot.bat"):
            self.assertNotIn("run_setup", path.read_text(encoding="utf-8").lower())

    def test_logout_control_stays_removed_from_active_overlay(self):
        overlay = (ROOT / "wboxai_app" / "overlay.py").read_text(encoding="utf-8")
        theme = (ROOT / "wboxai_app" / "glass_theme.py").read_text(encoding="utf-8")
        self.assertNotIn("btn_logout", overlay)
        self.assertNotIn("logout_requested", overlay)
        self.assertNotIn("QPushButton#logout", theme)


if __name__ == "__main__":
    unittest.main()
