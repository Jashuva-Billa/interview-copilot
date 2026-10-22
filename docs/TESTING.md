# Test strategy

## Run tests

From the repository root:

    python -m unittest discover -s tests -v
    python -m compileall -q .
    python -m ruff check --select F,E7,E9 .
    python -m coverage run --source=audio_processing,main,run_app,wboxai_app,llm_project -m unittest discover -s tests
    python -m coverage report -m
    git diff --check

The existing test suite uses unittest. Keep it that way unless there is a concrete benefit to introducing another test runner.

## Test layers

### Unit tests

Test deterministic functions and classes in isolation. Mock external services, OS APIs, devices, timers, and filesystem boundaries.

Coverage areas:
- Configuration parsing, defaults, and project-contained paths.
- Structured response parsing, code fences, missing sections, and malformed output.
- Audio conversion, buffers, VAD, question aggregation, deduplication, and role assignment.
- Audio device selection and the rule that interviewer audio must not silently fall back to the candidate microphone.
- Screen capture crop/resize/JPEG behavior.
- Screen change detection and noise thresholds.
- Error formatting and latency calculations.

### Integration tests

Test collaboration between modules while replacing real external systems with deterministic fakes.

Coverage areas:
- Audio source → enhancement/VAD → STT event → transcript.
- Interviewer transcript → question eligibility → generation call.
- Candidate microphone transcript → display/history only, never LLM question generation.
- Generation streaming callbacks → response contract → overlay/history.
- Screenshot capture result → vision service → parsed response → overlay.
- Configuration bootstrap → active runner wiring.
- UI signals and worker completion, including error paths and cleanup.

### Regression tests

Every fixed bug should gain a test that fails before the fix and passes afterward.

Current regression coverage includes:
- Candidate speech does not trigger LLM generation.
- Interviewer question detection, including fragments and no-question-mark phrasing.
- Duplicate question suppression.
- Speaker role calibration stability.
- Provider response and streamed response contracts.
- Multi-file code response parsing.
- Active launcher paths, removed setup runner, and removed logout control.

### Smoke tests

Run on each supported OS and on the packaged build:
- Application opens with the project-local environment.
- Missing .env shows an actionable error.
- Overlay can be shown, moved, closed, and toggled without a crash.
- Start/stop listening releases audio resources.
- System audio and microphone are identified and routed separately.
- Screen capture returns a valid image.
- Screen scan and Watch work on a real desktop.
- Configure opens and saves settings.
- App exits cleanly and can be relaunched.

Smoke tests requiring a real audio device, desktop capture, or GUI must be labelled manual unless a stable virtual-device/GUI runner exists.

### End-to-end tests

Use a controlled fixture transcript and mocked AI provider for CI. Test the full flow from a final interviewer transcript to a visible response. Do not require paid API calls in normal CI. Keep a separate opt-in live-provider check for API connectivity.

### Security and resilience tests

- No secrets are logged or included in exception text.
- Resume/config paths cannot escape the intended project root unless explicitly supported.
- Network/API errors produce a useful status and do not leave the app permanently busy.
- Audio source failure does not silently switch speaker roles.
- Worker exceptions do not crash the UI thread.
- Empty, malformed, oversized, and partial provider responses are handled safely.

### Performance tests

Track, but avoid brittle machine-specific hard limits in unit tests:
- Audio endpointing delay.
- Transcription latency.
- First-token and total generation latency.
- UI responsiveness while capture and API requests run in worker threads.
- Queue/buffer bounds during long sessions.

## CI quality gates

Recommended initial gates:
- All unit/integration/regression tests pass.
- Python compilation succeeds.
- Ruff errors selected for correctness are clean.
- No whitespace errors in diffs.
- Coverage is reported and trends upward.

Set a numeric coverage threshold only after the current baseline and platform-specific modules are understood. Increase it incrementally rather than adding a misleading repository-wide target before untested OS code can be exercised.

## Current known limitations

- The current coverage baseline is approximately 36% for the selected application modules with tests excluded from the coverage source; this is a measurement baseline, not a quality score by itself.
- Tests mock network providers and do not prove live API availability.
- Automated tests do not prove real hardware audio capture, Windows/macOS screen capture, or packaged executable behavior. These require platform smoke testing.
