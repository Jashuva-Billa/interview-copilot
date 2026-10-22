from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT, ROOT / "wboxai_app", ROOT / "audio_processing", ROOT / "llm_project"):
    value = str(entry.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)
from audio_processing import audio_capture


class DualAudioRoutingTests(unittest.TestCase):
    def test_endpoint_timeout_grows_for_longer_questions(self):
        with patch.dict("os.environ", {
            "AUDIO_END_SILENCE_MS": "900",
            "AUDIO_LONG_UTTERANCE_SILENCE_MS": "1700",
        }):
            self.assertEqual(audio_capture.adaptive_end_silence_ms(1000), 900)
            self.assertGreater(audio_capture.adaptive_end_silence_ms(5000), 900)
            self.assertEqual(audio_capture.adaptive_end_silence_ms(9000), 1700)

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

    def test_partial_transcript_chunks_are_separate_from_final_chunks(self):
        partials = []
        finals = []
        recorder = audio_capture.SpeechRecorder(
            on_chunk=finals.append,
            on_partial=partials.append,
            source="system",
        )
        audio = [np.ones(int(audio_capture.SAMPLE_RATE * 0.7), dtype=np.float32)]

        recorder._emit(audio, utterance_id="utterance-1", partial=True)
        recorder._emit(audio, speech_end_at=10.0, utterance_id="utterance-1")

        self.assertEqual(len(partials), 1)
        self.assertEqual(len(finals), 1)
        self.assertTrue(partials[0].is_partial)
        self.assertFalse(finals[0].is_partial)
        self.assertEqual(partials[0].utterance_id, finals[0].utterance_id)
        self.assertEqual(partials[0].utterance_id, "utterance-1")

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
