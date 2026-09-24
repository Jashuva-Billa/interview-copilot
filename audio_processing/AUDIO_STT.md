# Enterprise Audio-to-Text Module

`audio_stt` has one responsibility: convert microphone audio into transcript
events. It does not import interview prompts or perform LLM reasoning.

## Runtime pipeline

```text
PortAudio microphone
  -> 16 kHz mono float frames
  -> WebRTC APM (when native binding is installed)
  -> HPF / AGC / peak protection fallback
  -> bounded ring buffer
  -> Silero VAD
  -> endpoint detector
  -> pluggable STT provider
  -> partial/final AudioEvent callbacks
  -> speaker-aware question processor
  -> finalized interviewer-question LLM input
```

Capture uses `sounddevice` and `pyaudiowpatch`, supporting Windows WASAPI loopback and microphone inputs.
The supervisor polls the selected/default device and reopens it with exponential
backoff when a USB, wired, built-in, or Bluetooth microphone changes.

## Install local speech models

The base application remains usable with its OpenAI final-transcript fallback.
For local Silero and SenseVoice:

```powershell
.\venv\Scripts\pip install -r requirements-audio-enterprise.txt
```

The first SenseVoice start downloads its model. Production deployments should
pre-download and pin model artifacts in an internal cache.

## Configuration

```env
ENTERPRISE_AUDIO=true
AUDIO_STT_PROVIDER=sensevoice
AUDIO_STT_MODEL=iic/SenseVoiceSmall
AUDIO_LANGUAGE=auto
AUDIO_ALLOW_FALLBACK=true
AUDIO_ALLOW_OPENAI_STT=false
AUDIO_DIARIZATION_PROVIDER=source_metadata
AUDIO_DIARIZATION_MODEL=
PYANNOTE_AUTH_TOKEN=
QUESTION_CONFIDENCE_THRESHOLD=0.55
ROLE_CONFIDENCE_THRESHOLD=0.58
QUESTION_DEDUP_THRESHOLD=0.86
LLM_TRIGGER_CONFIDENCE_THRESHOLD=0.45
LLM_CONTEXT_TURN_COUNT=5
```

Set `AUDIO_ALLOW_FALLBACK=false` in controlled deployments to fail fast when a
required native/model component is missing.
Set `AUDIO_ALLOW_OPENAI_STT=false` to guarantee no OpenAI-based STT fallback.

`AUDIO_DIARIZATION_PROVIDER=source_metadata` is the default low-latency fallback.
It preserves the speaker-aware contract and uses separate source metadata as a
strong signal without claiming to separate mixed speakers. Set
`AUDIO_DIARIZATION_PROVIDER=pyannote`, install `pyannote.audio`, and provide
`PYANNOTE_AUTH_TOKEN` when you want local diarization for combined audio.

## Public API

```python
from audio_stt import AudioSTTConfig, AudioToTextPipeline, EventKind

pipeline = AudioToTextPipeline(AudioSTTConfig())

def handle(event):
    if event.kind in (EventKind.PARTIAL_TRANSCRIPT, EventKind.FINAL_TRANSCRIPT):
        print(event.transcript.text)

pipeline.subscribe(handle)
pipeline.start()
# ...
pipeline.stop()
```

For real AEC, feed synchronized speaker/render frames through
`pipeline.push_far_end(...)`. Microphone-only input cannot cancel acoustic echo.
If no native WebRTC binding is installed, the module logs the downgrade and
uses its deterministic HPF/AGC/normalization fallback.

## Reliability behavior

- Every real-time queue and audio buffer is bounded.
- Partial inference is shed first under backpressure; final jobs are retained.
- Capture errors trigger automatic device reopening.
- Subscriber failures are isolated from capture and inference threads.
- Metrics are available through `pipeline.metrics()` and emitted periodically.
- Model, capture, DSP, VAD, and STT implementations are independently replaceable.

## Latency note

The event path itself is frame-based and non-blocking. End-to-end partial
latency depends on the selected provider and hardware. SenseVoice snapshot
inference is not guaranteed to remain below 200 ms on every CPU. A strict
sub-200 ms service-level objective requires benchmarking the deployment machine
and, if necessary, plugging a native session-based streaming provider into the
`StreamingSTTProvider` contract.

## Speaker-aware question flow

Final STT events are converted into structured `TranscriptSegment` objects with
source metadata, aligned word timestamps, speaker IDs, role confidence, question
detection, aggregation, deduplication, and a compact LLM input:

```json
{
  "session_id": "session-...",
  "question_id": "question-...",
  "question": "How would you design a scalable RAG pipeline?",
  "speaker": "INTERVIEWER",
  "confidence": 0.78,
  "question_type": "system_design",
  "recent_context": [
    {"speaker": "INTERVIEWER", "text": "Tell me about your RAG system."},
    {"speaker": "CANDIDATE", "text": "We used hybrid retrieval..."}
  ]
}
```

Only finalized, non-duplicate interviewer questions above the configured
confidence thresholds are sent to the LLM. Candidate speech is retained in the
conversation window but does not trigger answer generation.

## Local testing

Pure speaker/question tests:

```powershell
.\venv\Scripts\python.exe -m unittest wboxai_app.tests.test_speaker_aware_pipeline
```

Live audio tests also require `sounddevice` and an operational project venv:

```powershell
.\venv\Scripts\python.exe -m unittest wboxai_app.tests.test_audio_stt
```

To test with a prerecorded two-person interview, feed final transcript fragments
into `InterviewQuestionProcessor.process_transcript()` with `source_metadata()`
for system, microphone, or combined source metadata. For true mixed-audio
speaker separation, configure the pyannote provider and pass provider-generated
speaker intervals through the same alignment path.

To test live system + microphone audio, set `ENTERPRISE_AUDIO=true`, start the
app, enable listening, and watch for `Listening - question ready` transitions.
Loopback audio and microphone audio are both processed by the same
speaker-aware question boundary before LLM generation.
