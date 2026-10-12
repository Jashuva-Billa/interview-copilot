from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT, ROOT / "wboxai_app", ROOT / "audio_processing", ROOT / "llm_project"):
    value = str(entry.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)
from audio_processing import audio_capture


class DualAudioRoutingTests(unittest.TestCase):
    def test_system_audio_does_not_fall_back_to_working_microphone(self):
        with patch.object(audio_capture, "_find_loopback_device", return_value=None), patch.object(
            audio_capture, "_probe_input_device", return_value=True
        ) as probe:
            with self.assertRaisesRegex(RuntimeError, "will not fall back to your microphone"):
                audio_capture.resolve_input_device("system")
        probe.assert_not_called()

    def test_microphone_source_uses_default_input_only(self):
        with patch.object(audio_capture, "_probe_input_device", return_value=True) as probe, patch.object(
            audio_capture, "_find_loopback_device"
        ) as loopback:
            device, is_loopback, label = audio_capture.resolve_input_device("microphone")
        self.assertIsNone(device)
        self.assertFalse(is_loopback)
        self.assertTrue(label)
        probe.assert_called_once_with(None)
        loopback.assert_not_called()

    def test_source_aliases_resolve_to_expected_streams(self):
        with patch.object(audio_capture, "_find_loopback_device", return_value=7), patch.object(
            audio_capture, "_device_name", return_value="Loopback input"
        ):
            self.assertEqual(audio_capture.resolve_input_device("system"), (7, True, "Loopback input"))
            self.assertEqual(audio_capture.resolve_input_device("loopback"), (7, True, "Loopback input"))

        with patch.object(audio_capture, "_probe_input_device", return_value=True):
            device, is_loopback, _ = audio_capture.resolve_input_device("candidate")
        self.assertIsNone(device)
        self.assertFalse(is_loopback)


if __name__ == "__main__":
    unittest.main()
