# Interview Copilot

A local desktop interview assistant for GenAI, machine learning, AI engineering, and coding interviews. It captures interviewer audio, transcribes questions, sends the completed question to a configured model API, and displays a concise answer in a floating PyQt overlay. It can also analyze a screenshot for coding or assessment tasks.

> **Important:** This application uses model APIs directly. It does **not** automate ChatGPT in a browser and does not send questions through the ChatGPT website. For OpenAI, it uses the OpenAI API with an API key from the saved application settings.

## Install

- **Windows x64** — Open `Interview-Copilot.exe`.
- **Apple Silicon Mac, macOS 14 or later** — Open `Interview-Copilot.dmg`, drag Interview Copilot to Applications, and launch it. Allow access to the microphone and Screen & System Audio Recording when prompted.

Enter an OpenAI API key the first time. The app stores it in your per-user app data and reuses it at later launches. A confirmed credit exhaustion error offers key replacement. Temporary rate limits and network errors do not open setup.

Native packages are produced by the **Build desktop packages** workflow. Tagged releases publish both files as release downloads.

## Windows audio setup

Run Interview Copilot on the same Windows PC as your meeting. Set Meet or your other meeting app to play through the Windows default output device, and set your headset microphone as the Windows default input. Click **Start listening**. System playback drives the **Question** box, and the microphone goes to the spoken-answer transcript. Keep unrelated playback muted because system capture includes other apps using the same output.

## Interview modes

- **Technical and behavioral Q&A.** Start listening to capture interviewer audio. Follow-ups use recent exchanges, and questions that revisit a topic can pull in an older matching exchange. The candidate microphone is recorded separately and does not trigger answers.
- **Coding.** Spoken implementation requests use the coding prompt. Use **Scan screen** for a visible coding problem or a single multiple-choice question.
- **Multi-screen coding assessments.** Enable **Assessment**, capture the relevant problem and code screens, then click **Submit**. Screens stay queued for retry until you click **Clear**.

The audio pipeline waits longer when a transcript ends mid-clause. It filters common filler and transcription noise markers, and suppresses immediate duplicate finals.

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
## Key configuration

Packaged installations store settings in the user's app data folder. Source development reads the repository-root `.env`.

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
