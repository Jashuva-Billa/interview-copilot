"""Validated configuration for the audio-to-text module."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AudioSTTConfig:
    sample_rate: int = 16_000
    frame_ms: int = 32
    channels: int = 1
    queue_capacity: int = 256
    ring_buffer_seconds: float = 15.0
    pre_speech_ms: int = 350
    min_speech_ms: int = 100
    end_silence_ms: int = 400
    max_utterance_seconds: float = 45.0
    device_poll_seconds: float = 2.0
    recovery_initial_seconds: float = 0.25
    recovery_max_seconds: float = 5.0
    vad_threshold: float = 0.55
    vad_model_path: str = ""
    stt_provider: str = "sensevoice"
    stt_model: str = "iic/SenseVoiceSmall"
    language: str = "auto"
    partial_interval_ms: int = 500
    question_confidence_threshold: float = 0.55
    role_confidence_threshold: float = 0.58
    question_dedup_threshold: float = 0.86
    llm_trigger_confidence_threshold: float = 0.45
    context_turn_count: int = 5
    diarization_provider: str = "source_metadata"
    diarization_model: str = ""
    pyannote_auth_token: str = ""
    enable_aec: bool = True
    enable_ns: bool = True
    enable_agc: bool = True
    enable_high_pass: bool = True
    enable_normalization: bool = True
    allow_component_fallback: bool = True
    allow_openai_stt: bool = False
    speech_to_text_server_url: str = "ws://127.0.0.1:8000"
    speech_to_text_provider: str = "openai"
    speech_to_text_openai_key: str = ""
    speech_to_text_deepgram_key: str = ""
    disable_llm_cleaning: bool = True

    def __post_init__(self) -> None:
        if self.sample_rate != 16_000:
            raise ValueError("The pipeline output sample rate must be 16000 Hz")
        if self.channels != 1:
            raise ValueError("The pipeline output must be mono")
        if self.frame_ms not in (10, 20, 30, 32):
            raise ValueError("frame_ms must be 10, 20, 30, or 32")
        if self.queue_capacity < 8:
            raise ValueError("queue_capacity must be at least 8")
        if not 0.0 < self.vad_threshold < 1.0:
            raise ValueError("vad_threshold must be between 0 and 1")
        if self.partial_interval_ms < 100:
            raise ValueError("partial_interval_ms must be at least 100")
        if not 0.0 < self.question_confidence_threshold <= 1.0:
            raise ValueError("question_confidence_threshold must be between 0 and 1")
        if not 0.0 < self.role_confidence_threshold <= 1.0:
            raise ValueError("role_confidence_threshold must be between 0 and 1")
        if not 0.0 < self.question_dedup_threshold <= 1.0:
            raise ValueError("question_dedup_threshold must be between 0 and 1")
        if not 0.0 < self.llm_trigger_confidence_threshold <= 1.0:
            raise ValueError("llm_trigger_confidence_threshold must be between 0 and 1")
        if self.context_turn_count < 1:
            raise ValueError("context_turn_count must be at least 1")

    @property
    def frame_samples(self) -> int:
        return round(self.sample_rate * self.frame_ms / 1000)
