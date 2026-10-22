# Module audit

This inventory records why files exist before moving or deleting them. It reflects static imports and launcher/build references found during the current audit; hardware paths still need manual confirmation.

## Entrypoints and build tools

| File | Current role | Decision |
|---|---|---|
| start_interview_copilot.bat | Windows development launcher; starts app/run_app.py with pythonw | Keep |
| app/run_app.py | Windows runner; configures import paths and starts InterviewApp | Keep; simplify import behavior in a later phase |
| scripts/run.sh | macOS launcher; creates venv/.env and starts app/main.py | Keep; currently starts a different module implementation |
| app/main.py | Runtime coordinator used by macOS launcher and packaging/main.spec | Keep |
| packaging/main.spec | PyInstaller build definition | Keep until packaged-build validation is available |
| scripts/watch_build.py | Developer utility that rebuilds the packaged Windows executable | Optional tool; keep until user confirms packaged builds are no longer used |
| app/core/project_bootstrap.py | Project-root and .env validation used by app/main.py and app/run_app.py | Keep; add isolated tests |
| app/setup/installer.py | SetupWizard used by the overlay Configure action; also includes older install and web-login pages | Keep for now; split or simplify only after configuration-page behavior is covered |

## Active implementation groups

### Audio capture and speech

- audio_processing/audio_capture.py: system loopback and microphone recording used by the current runtime.
- audio_processing/audio_stt/: modular capture, enhancement, VAD, STT, speaker role resolution, question aggregation, and event pipeline. The current app/main.py runtime does not instantiate AudioToTextPipeline; it uses SpeechRecorder from audio_processing/audio_capture.py. The modular pipeline is tested in isolation but is not yet wired into the live application.
- audio_processing/audio_processing_backend/: provider adapters and transcript-cleaning helpers referenced by the modular STT implementation. The FastAPI entry file audio_processing/audio_processing_backend/main.py has no in-repository launcher/reference found, but the provider/service modules are imported by audio_stt/stt.py. Do not delete the entire folder; decide separately whether the standalone WebSocket server is still supported.
- requirements-audio-enterprise.txt and audio_processing/requirements-audio-enterprise.txt: similar optional dependency lists; compare and consolidate after confirming which setup instructions are supported.

### Windows-oriented runtime

- wboxai_app/config.py, overlay.py, screen_capture.py, screen_watcher.py, capture_exclude.py, glass_effect.py, and glass_theme.py are resolved by the current Windows runner's sys.path setup.
- wboxai_app/win_ocr.py is called by llm_project/openai_service.py as an optional Windows OCR fallback.
- wboxai_app/token_tracker.py is imported by llm_project/openai_service.py for model-call reporting.
- wboxai_app/login_dialog.py and whitebox_auth.py support the older browser login/session flow. They are not used by app/run_app.py's normal startup, but app/setup/installer.py still references session helpers and SetupWizard remains active for Configure. Audit this path before deleting it.

### Root-level implementation

- app/core/config.py, app/ui/overlay.py, app/services/openai_service.py, app/services/response_parser.py, app/screen/screen_capture.py, app/screen/screen_watcher.py, app/screen/capture_exclude.py, app/ui/glass_effect.py, and app/ui/glass_theme.py are parallel implementations used when app/main.py is started directly with the root directory first on sys.path, including the current macOS launcher.
- app/services/coding_detector.py and app/services/response_parser.py are related to app/services/openai_service.py implementation.
- These are not proven dead code: scripts/run.sh and packaging/main.spec now point at app/main.py. The Windows development launcher still intentionally prioritizes wboxai_app/ and llm_project/; do not merge those variants without platform smoke tests.

### LLM and response processing

- llm_project/openai_service.py: current Windows runner's multi-provider generation/transcription/vision service.
- llm_project/interview_prompt.py and coding_detector.py: prompt construction and coding-question detection used by that service.
- llm_project/response_parser.py: structured output parsing used by the Windows runtime.
- llm_project/pdf_loader.py: called from the generation path for supplemental PDF context; test it or remove the feature and reference together.

### Verification and tests

- scripts/verify_full_pipeline.py and scripts/verify_speaker_roles.py are developer verification scripts, not normal app startup modules. Keep them until their scenarios are represented in automated tests.
- tests/unit/: deterministic component tests.
- tests/integration/: multiple components with external systems mocked.
- tests/regression/: bug-specific behavior contracts.
- tests/smoke/: startup/bootstrap contracts; hardware and packaged-build smoke checks still require a real supported OS.

## Confirmed cleanup in this phase

- Moved the existing six test modules out of wboxai_app/tests/ into the top-level tests tree.
- Added unit tests for configuration path safety, response parsing, screen capture, and screen-change detection.
- Added startup/bootstrap and launcher contract checks.
- Added docs/ARCHITECTURE.md and docs/TESTING.md.
- Removed standalone run_setup.bat and run_setup.py in the previous cleanup. Remaining mentions are limited to this historical audit note and regression assertions; no executable startup path depends on them.

## Next consolidation steps

1. Decide whether the modular audio_stt pipeline is intended to replace SpeechRecorder in the live app or remain an experimental standalone subsystem; align ENTERPRISE_AUDIO configuration with that decision.
2. Use the tests to decide a single authoritative runtime per OS, or explicitly keep platform-specific implementations in named packages.
3. Replace sys.path-based module selection with explicit package imports.
4. Consolidate duplicated config, response parsing, screen capture, overlay styling, and watcher code only after platform behavior has tests.
5. Separate the active Configure form from the legacy web-login/install workflow inside installer.py.
6. Test token/reporting and PDF context paths; add coverage for audio device lifecycle and worker error cleanup.
7. Validate Windows and macOS startup and the packaged executable before deleting any platform-specific implementation.
