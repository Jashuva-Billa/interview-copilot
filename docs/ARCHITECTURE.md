# Architecture and refactoring guide

## Goals

Keep Interview Copilot small, explicit, and testable. Apply separation of concerns and KISS without introducing layers that only forward calls.

## Current runtime paths

### Windows interactive launcher

start_interview_copilot.bat starts app/run_app.py with the project virtual environment's pythonw.exe.

app/run_app.py adds project module directories to sys.path, validates the project environment, and starts the app/main.py InterviewApp. With that import order, the Windows path currently resolves several modules from wboxai_app/ and llm_project/, and audio capture from audio_processing/.

### macOS launcher

scripts/run.sh prepares the local virtual environment and root .env, then starts app/main.py directly. This uses the moved root-platform modules from app/core/, app/ui/, app/services/, and app/screen/.

### Packaged Windows build

packaging/main.spec packages app/main.py; scripts/watch_build.py invokes PyInstaller. installer.py contains the configuration wizard used by the active overlay's Configure action and also retains a legacy installation/build flow.

These paths are not yet a single canonical implementation. The similarly named root, wboxai_app/, and llm_project/ modules have meaningful behavioral differences. Do not delete or merge them solely because their names match.

## Organized repository layout

The root keeps the Windows launcher, repository metadata, documentation, and dependency manifests. Application modules are grouped by responsibility; the existing Windows-specific `wboxai_app/` and `llm_project/` implementations remain separate until platform behavior can be unified safely.

```text
interview-copilot/
  start_interview_copilot.bat
  app/
    main.py
    run_app.py
    core/          # config and bootstrap
    services/      # root-platform LLM service, coding detection, parsing
    ui/             # overlay and styling
    screen/         # capture, watcher, OS integration
    monitoring/     # latency and transcript reports
    setup/          # Configure/setup wizard
  audio_processing/ # audio capture and STT pipeline
  wboxai_app/       # Windows UI/platform implementation
  llm_project/      # Windows multi-provider LLM implementation
  scripts/          # macOS launcher and developer scripts
  packaging/        # PyInstaller spec
  tests/
  docs/
  local_data/       # local resume data (resume file ignored by Git)
  requirements*.txt
  .env.example
```

This layout is a mechanical organization step, not a claim that duplicate implementations have already been consolidated. Their import precedence remains platform-sensitive.

## Low-latency interviewer question flow

The Windows runtime still supports OpenAI snapshot transcription as a fallback. Capture frames are now 20 ms by default and interim snapshot requests are scheduled about every 300 ms. In fallback mode, endpointing defaults to 0.9 s of silence (up to 3.0 s for long or unfinished utterances) to reduce accidental splits at natural pauses. Each snapshot is still a separate HTTP transcription request, so that mode remains network-bound and is not true word-level streaming.

For lower-latency live text, set `DEEPGRAM_API_KEY` in the project `.env` and install `requirements.txt` so `deepgram-sdk` is available. With `AUDIO_STT_MODE=auto` (default) or `AUDIO_STT_MODE=streaming`, the active system-loopback recorder streams PCM16 frames over a persistent Deepgram WebSocket. Interim recognition updates go directly to the question panel; only the provider's `speech_final` event starts answer generation. In this mode the local batch VAD/snapshot path is skipped for system audio to avoid redundant CPU work. The mic remains separate for candidate speech logging.

`AUDIO_STT_MODE=snapshot` forces the OpenAI snapshot fallback. `AUDIO_PARTIAL_INTERVAL_MS`, `AUDIO_FRAME_MS`, `AUDIO_END_SILENCE_MS`, and `AUDIO_LONG_UTTERANCE_SILENCE_MS` tune capture and fallback behavior. End-to-end speech transcription cannot be nanosecond-latency: the default capture frame alone represents 20 ms of audio, and recognition, network transit, and UI scheduling add more. A live microphone/loopback measurement is required to characterize actual latency on the target machine.


## Model API path (not ChatGPT web)

The desktop app does not automate the ChatGPT website. The active Windows runner uses `app/run_app.py` and import-path precedence that resolves the Windows configuration/UI from `wboxai_app/`, the multi-provider generation service from `llm_project/openai_service.py`, and audio capture/STT from `audio_processing/`. The direct app/macOS path uses the migrated modules under `app/core/`, `app/services/`, and `app/ui/`; these implementations are not yet fully consolidated.

For OpenAI, the service creates an official Python `OpenAI` client from `OPENAI_API_KEY` and calls API endpoints for text generation, audio transcription, and screenshot/vision analysis. The Windows multi-provider service can additionally call Gemini's API and Anthropic's API when their keys are configured, or use a local Ollama endpoint when `USE_LOCAL_LLM=true`. For streaming interviewer transcription, the app can send PCM audio to Deepgram over a persistent WebSocket when `DEEPGRAM_API_KEY` and the active STT mode permit it; otherwise it uses the OpenAI snapshot-transcription path. These are provider API calls, not requests sent through a logged-in ChatGPT web session.

## Responsibility boundaries

- Entry point: bootstrap once, construct the application, start the event loop. It should not implement audio or LLM behavior.
- Runtime coordinator: wires signals and coordinates workers. Keep business logic out of UI widgets.
- UI: renders state and emits user intent. It should not resolve devices, call LLM APIs, or load secrets directly.
- Configuration: loads settings from the intended project-local file, validates values, and resolves project-contained paths.
- Audio: device discovery, capture, voice activity detection, transcript events, speaker roles, and question aggregation.
- AI services: API client lifecycle, transcription, generation, vision, and structured response parsing.
- Screen services: capture and change detection; OS-specific behavior stays at the boundary.
- Diagnostics: latency, token, and operational logs. No application logic should depend on report files.

## KISS rules

1. One authoritative implementation for each behavior.
2. Use explicit imports and package names; avoid relying on sys.path ordering to choose a module.
3. Keep public interfaces small and typed where it helps.
4. Prefer standard-library unittest and unittest.mock for tests already written in that style.
5. Do not add a dependency or abstraction unless it removes real duplication or enables meaningful testing.
6. Avoid broad exception swallowing; errors should be actionable and visible.
7. Do not mix configuration, network calls, UI updates, and device access in the same function when they can be separated cleanly.
8. Keep secrets, virtual environments, generated reports, caches, and build output out of source control.

## Safe refactoring sequence

1. Establish test and static-check baselines.
2. Put tests in a top-level test tree and add missing contract tests.
3. Record the import/entry-point map and determine which implementation is authoritative on each OS.
4. Unify module imports and launcher contracts without changing behavior.
5. Consolidate modules one responsibility at a time; retain compatibility wrappers only when a real consumer needs them.
6. Move modules into the final package layout and update packaging/data paths.
7. Run unit, integration, regression, static, and manual platform smoke tests after every slice.
8. Remove genuinely unreachable legacy files only after search, import-graph, packaging, and test checks show they are unused.

## Non-goals

- Do not rewrite the audio/STT pipeline from scratch.
- Do not introduce a service/container framework for a desktop application.
- Do not move or delete a module based only on filename similarity.
- Do not change user-facing behavior as part of a mechanical move.
