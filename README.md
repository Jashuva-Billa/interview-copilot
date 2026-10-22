# Interview Copilot

A local desktop interview assistant for GenAI, machine learning, AI engineering, and coding interviews. It captures interviewer audio, transcribes questions, sends the completed question to a configured model API, and displays a concise answer in a floating PyQt overlay. It can also analyze a screenshot for coding or assessment tasks.

> **Important:** This application uses model APIs directly. It does **not** automate ChatGPT in a browser and does not send questions through the ChatGPT website. For OpenAI, it uses the OpenAI API with an API key from this project's local `.env`.

## Architecture

```text
Interviewer audio / optional screen capture
              |
              v
Audio capture and question transcription
  |                           |
  | DEEPGRAM_API_KEY          | snapshot fallback
  v                           v
Deepgram streaming STT      OpenAI Audio Transcriptions API
  |                           |
  +-------------+-------------+
                |
                v
      Question finalization / routing
                |
                v
       InterviewApp coordinator
                |
                v
          LLM API service
     /             |              \
    v              v               v
OpenAI API      Gemini API      Anthropic API
(optional)       (optional)      (optional)
    \              |              /
     +-------------+--------------+
                   |
                   v
       Parse response / provider result
                   |
                   v
       PyQt floating overlay + history
```

The exact providers used depend on keys and settings in `.env`. OpenAI is enabled when `OPENAI_API_KEY` is configured (or local-LLM mode is enabled); Gemini and Claude are enabled when their respective API keys are configured. The app can run multiple configured providers and displays the primary configured provider's answer.

## Current runtime entry points

### Windows

Double-click `start_interview_copilot.bat`. It launches `app/run_app.py` using `venv\\Scripts\\pythonw.exe` so the UI runs without an attached console. The runner bootstraps the project-root `.env`, constructs `InterviewApp`, and starts the overlay.

The Windows runner deliberately adds `wboxai_app/`, `llm_project/`, and `audio_processing/` to the import path. Consequently, Windows currently uses the Windows-oriented configuration/UI and multi-provider LLM implementation from `wboxai_app/` and `llm_project/`, plus audio modules from `audio_processing/`. The root `app/services/` and `app/ui/` modules are alternate/migrated implementations, not yet a single unified runtime.

### macOS / direct app entry

`scripts/run.sh` prepares the project virtual environment and root `.env`, then runs `app/main.py`. That path uses the moved modules under `app/core/`, `app/services/`, `app/ui/`, and `app/screen/`. Keep platform-specific differences in mind when changing shared behavior.

## API usage: ChatGPT website vs OpenAI API

- **OpenAI answer generation:** direct HTTPS/API calls through the official Python `openai` SDK to OpenAI's API, using `OPENAI_API_KEY` and `OPENAI_CHAT_MODEL`.
- **OpenAI audio transcription fallback:** direct OpenAI API transcription requests using `OPENAI_TRANSCRIBE_MODEL`.
- **OpenAI screenshot analysis:** direct OpenAI API vision/chat-completion requests using `OPENAI_VISION_MODEL`.
- **Live streaming transcription:** when `DEEPGRAM_API_KEY` is available and streaming mode is selected/available, audio is streamed to Deepgram over a WebSocket. This is not ChatGPT web audio capture.
- **Optional other answer providers:** Gemini uses its API with `GEMINI_API_KEY`; Claude uses Anthropic's API with `CLAUDE_API_KEY` (or `ANTHROPIC_API_KEY`).
- **No ChatGPT browser automation:** there is no ChatGPT web login/session flow in the current launcher. No ChatGPT website cookies or browser session are used to generate answers.

API usage may incur provider charges and is governed by the relevant provider account, API pricing, and data policies. Do not put API keys in source control or share them in screenshots/logs.

## Setup

1. Install Python 3.10+ and Git if needed.
2. From the repository root, create the virtual environment:
   ```powershell
   python -m venv venv
   .\\venv\\Scripts\\python.exe -m pip install --upgrade pip
   .\\venv\\Scripts\\python.exe -m pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` if it exists; otherwise create `.env` in the repository root.
4. Add at least `OPENAI_API_KEY` for OpenAI responses and transcription fallback. For streaming transcription, also configure `DEEPGRAM_API_KEY`.
5. Add your resume/context to the configured local resume file (default: `local_data/resume_context.txt`). This local context should remain untracked.
6. Launch `start_interview_copilot.bat`.

For macOS, run `./scripts/run.sh` after configuring the local `.env`.

## Key configuration

All runtime configuration should be in the repository-root `.env`; never commit it.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Enables OpenAI API answer generation and OpenAI transcription/vision paths |
| `OPENAI_CHAT_MODEL` | OpenAI text-answer model (default depends on the active platform config; commonly `gpt-4o-mini`) |
| `OPENAI_TRANSCRIBE_MODEL` | OpenAI snapshot transcription model (commonly `gpt-4o-mini-transcribe`) |
| `OPENAI_VISION_MODEL` | Model used for screenshot analysis (commonly `gpt-4o`) |
| `DEEPGRAM_API_KEY` | Enables Deepgram streaming transcription when the SDK and mode permit |
| `AUDIO_STT_MODE` | `auto`, `streaming`, or `snapshot`, depending on the active platform implementation |
| `GEMINI_API_KEY` | Optional Gemini API provider |
| `GEMINI_MODEL` | Gemini model name |
| `CLAUDE_API_KEY` / `ANTHROPIC_API_KEY` | Optional Anthropic API provider |
| `CLAUDE_MODEL` | Anthropic model name |
| `USE_LOCAL_LLM` | In the Windows implementation, optionally use a locally running Ollama model through its local HTTP API |
| `CODING_MODE` | `auto`, `always`, or `never` coding-mode selection |
| `CODE_LANGUAGE` | Language for generated coding solutions (default: Python) |
| `RESUME_CONTEXT_PATH` | Optional path to the resume context file, subject to project path rules |

The platform implementations have some configuration differences; check the active runtime path above before adding or changing a variable.

## Main request flow

1. Capture interviewer system audio/loopback; the microphone is kept separate for candidate-speech logging.
2. Transcribe audio. Deepgram can provide interim/final WebSocket transcripts; the OpenAI snapshot path submits audio chunks to the OpenAI transcription API.
3. Finalize and route the interviewer question. Partial transcripts update the question preview; they should not trigger answer generation until finalized.
4. Build the prompt from the resume, project context, role, and recent conversation.
5. Call configured model API provider(s), stream the primary answer when available, and parse the result.
6. Display the answer and, when appropriate, code/assessment details in the floating overlay.

## Repository layout

```text
interview-copilot/
  app/
    main.py                 # runtime coordinator
    run_app.py              # Windows runner / bootstrap
    core/                   # alternate platform config/bootstrap
    services/               # alternate LLM service and parsing
    ui/                     # alternate overlay
    screen/                 # screenshot capture / screen watcher
    monitoring/             # latency and transcript reports
    setup/                  # setup/configuration UI
  wboxai_app/               # active Windows configuration and UI
  llm_project/              # active Windows LLM providers, prompts, parsing
  audio_processing/         # capture, endpointing, STT provider adapters
  scripts/                  # platform launcher and developer utilities
  packaging/                # PyInstaller configuration
  tests/                    # unit, integration, regression, smoke tests
  docs/ARCHITECTURE.md      # architecture and refactoring notes
  local_data/               # local resume/context data (keep private)
  requirements.txt
  start_interview_copilot.bat
```

## Testing

Run the test suite from the repository root using the project's virtual environment:

```powershell
.\\venv\\Scripts\\python.exe -m unittest discover -s tests -v
```

Or, if the environment is activated:

```powershell
python -m unittest discover -s tests -v
```

Tests use mocks for provider calls; passing tests do not prove that live API credentials, audio devices, or end-to-end transcription are working on the current machine.

## Security and privacy

- Keep `.env`, API keys, resume files, and interview transcripts out of Git.
- Audio/transcripts sent to a provider are processed according to that provider's API terms and data policies.
- Do not use a real interview or personal data in tests unless you understand where it is sent.
- Review screenshots before sharing them; they may contain private or employer information.
- This desktop app is not a ChatGPT web client and does not inherit ChatGPT website subscription access or limits.
