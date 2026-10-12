# Interview Copilot

AI-powered interview assistant with a **transparent overlay** that shows suggested answers while you are on a video call. On Windows, the overlay uses **capture exclusion** so it stays **visible to you** but is **not included** when you share your screen in Zoom, Teams, or Google Meet.

## Features

- Listens to **interviewer audio** via system loopback (WASAPI) — what plays through your speakers from the call
- Transcribes speech with **OpenAI Whisper**
- Generates concise, speakable answers with **GPT** using your resume context
- **Coding interview mode** for CoderPad / HackerRank / LeetCode-style problems:
  - Auto-detects coding questions from speech
  - Shows **what to say** (approach) + **copy-paste code** in a separate panel
# Interview Copilot

AI-powered interview assistant with a **transparent overlay** that shows suggested answers while you are on a video call. On Windows, the overlay uses **capture exclusion** so it stays **visible to you** but is **not included** when you share your screen in Zoom, Teams, or Google Meet.

## Features

- Listens to **interviewer audio** via system loopback (WASAPI) — what plays through your speakers from the call
- Transcribes speech with **OpenAI Whisper**
- Generates concise, speakable answers with **GPT** using your resume context
- **Coding interview mode** for CoderPad / HackerRank / LeetCode-style problems:
  - Auto-detects coding questions from speech
  - Shows **what to say** (approach) + **copy-paste code** in a separate panel
  - **Paste problem** button when the prompt is only on screen
- **Transparent, draggable** always-on-top window
- **Hidden from screen share** on Windows 10 version 2004+ (`SetWindowDisplayAffinity`)

## Requirements

| Platform | Supported |
|----------|-----------|
| **Windows 10/11** | Full — screen-share invisible overlay, WASAPI loopback audio |
| Python 3.10+ | Supported |
| OpenAI / Gemini / Claude API key | Supported |

Headphones recommended on Windows loopback.

## Isolated project (not Outreach)

Interview Copilot is **self-contained** in `interview-copilot/`:

| Resource | Location only |
|----------|-----------------|
| Config | `interview-copilot/.env` |
| Virtual env | `interview-copilot/venv/` |
| Resume | `interview-copilot/resume_context.txt` |

It does **not** read Outreach `.env`, Outreach `venv`, or parent folders.

**Always start with:**

```powershell
cd interview-copilot
.\scripts\run.ps1
```

Do not run `python main.py` from another project's activated venv.

## Quick start

1. Copy environment file and add your API key:

   ```powershell
   cd interview-copilot
   copy .env.example .env
   # Edit .env — set OPENAI_API_KEY=sk-...
   ```

2. Paste your resume into `resume_context.txt` (plain text).

3. Run:

   ```powershell
   .\run.bat
   # or: .\venv\Scripts\python.exe run_app.py
   ```

4. Join your interview on the laptop. Position the overlay on a second monitor or corner of the screen.

5. Click **Start listening** when the interviewer speaks.

## Performance (small laptops)

Default **lightweight mode** avoids “Not responding” on Windows:

```env
LIGHTWEIGHT_MODE=true
MAX_WORKERS=1
SCREEN_CAPTURE_MAX_WIDTH=1280
SCREEN_WATCH_INTERVAL_SEC=30
```

Heavy work (screenshots, OpenAI) runs in a **background thread**. The UI thread only updates the overlay.

## Audio setup (Google Meet / Zoom / Teams)

**You must click Start listening** — the app does not answer until listening is on.

| Mode | `.env` | Use when |
|------|--------|----------|
| Loopback | `AUDIO_SOURCE=loopback` | **Default on Windows** — captures interviewer from **speakers** (WASAPI / PC Speaker) |
| Microphone | `AUDIO_SOURCE=microphone` | Captures through microphone input |

**For Meet interviews on Windows:**

1. Use **speakers** (or earbuds as speaker output) so system audio is captured — not headphones-only with no loopback.
2. Keep Meet volume up; status should show `Listening — system audio (PC Speaker ...)`.
3. Wait until the interviewer **finishes** a sentence (~1s pause) — then you should see `Transcribing...` → `Generating answer...`.

If loopback is not detected:

1. Open **Sound settings → More sound settings → Recording** → enable **Stereo Mix** if available, or
2. Set `AUDIO_SOURCE=microphone` in `.env` and let the mic hear your speakers (quiet room)

List devices:

```powershell
python -c "import sounddevice as sd; print(sd.query_devices())"
```

## Enterprise audio-to-text (modular pipeline)

This repo now includes a dedicated `audio_stt/` module that focuses only on
converting microphone audio into transcript events.

Pipeline:

```text
Microphone -> 16 kHz mono framing -> enhancement (APM/fallback DSP) -> VAD
-> streaming STT provider -> partial/final transcript events
```

Key properties:

- Robust capture path for Windows 10/11
- Automatic microphone recovery on device changes
- Bounded queues and buffers to prevent unbounded memory growth
- Pluggable components (capture, enhancement, VAD, STT provider)
- Periodic operational metrics and recoverable error events

Enable in `.env`:

```env
ENTERPRISE_AUDIO=true
AUDIO_STT_PROVIDER=sensevoice
AUDIO_STT_MODEL=iic/SenseVoiceSmall
AUDIO_LANGUAGE=auto
AUDIO_ALLOW_FALLBACK=true
AUDIO_ALLOW_OPENAI_STT=false
```

Install optional local speech dependencies:

```powershell
.\venv\Scripts\pip install -r requirements-audio-enterprise.txt
```

Notes:

- If local SenseVoice or Silero packages are missing and
  `AUDIO_ALLOW_FALLBACK=true`, the app falls back to simpler components and
  remains usable.
- True acoustic echo cancellation needs synchronized speaker render audio as a
  reference stream. Microphone-only input cannot deliver full AEC quality.
- Additional technical details are documented in `AUDIO_STT.md`.

## Screen sharing behavior

The overlay is **invisible in screen share** on **Windows 10/11** (Zoom, Teams, Meet).

With `OVERLAY_TRANSPARENT=true` (default), the overlay uses a **semi-transparent** panel so you can see through to your screen. Share-hide (`INVISIBLE_IN_SHARE=true`) is applied without stripping the layered window style. If the overlay still appears in a screen share on your PC, set `OVERLAY_TRANSPARENT=false` for an opaque panel (more reliable on some Windows builds).

```env
INVISIBLE_IN_SHARE=true
OVERLAY_TRANSPARENT=true
```

- **Ctrl+H** hide overlay · **Ctrl+Shift+H** show · **Esc** quit

### HackerRank / CoderPad / LeetCode (focus detection)

With `STEALTH_FOCUS=true` (default), the overlay **does not steal focus** from the coding tab:

- **Hover + mouse wheel** scrolls answers/code (no click needed)
- Use **Ctrl+Shift+S** to scan screen, **Ctrl+Shift+C** for coding mode (keyboard, no click)
- Drag only via the **top bar** when you need to move the window

> Requires Windows 10 version 2004+. Works with most meeting apps.

## Coding interviews (White-box Learning / CoderPad / LeetCode)

When the interviewer gives a coding problem, the app switches to **coding mode**:

| Section | Use |
|--------|-----|
| **What to say** | Approach bullets, complexity — say these while thinking |
| **Code** | Full solution — click **Copy code** and paste into CoderPad |

**Ways to get the problem (no copy-paste):**

1. **Scan screen** — `Ctrl+Shift+S` or **Scan screen**: hides overlay briefly, screenshots desktop, Vision reads the problem (left panel) + function stub (right editor). Works with **White-box Learning** split layout and returns approach + copy-paste code.
2. **Watch** — toggle **Watch**: every ~18s checks if the screen changed; when the interviewer opens a new problem, auto-scans.
3. **Voice** — auto-detects coding questions from interviewer speech (loopback).
4. **Force coding** — `Ctrl+Shift+C` on the last voice question.

Set in `.env`:

```env
CODE_LANGUAGE=python    # python | javascript | java | cpp
CODING_MODE=auto      # auto | always
OPENAI_CHAT_MODEL=gpt-4o   # recommended for harder problems
```

**Typical flow (White-box / CoderPad):**

1. Open the coding tab full screen (problem + editor visible).
2. Press **Scan screen** or `Ctrl+Shift+S`.
3. Wait for `Coding solution ready` — use **What to say** + **Copy code**.

**Typical flow on CoderPad:**

1. Interviewer shares CoderPad with the problem visible → press **Ctrl+Shift+S** (or enable **Watch** before they share).
2. Overlay hides for a split second (so it is not in the screenshot), captures the screen, Vision reads the problem.
3. Talk through **What to say**, then **Copy code** into CoderPad.
4. Optional: **Start listening** for follow-up questions (“can you optimize space?”).

## Customization

Edit `.env`:

- `JOB_ROLE` — target role for answers
- `JOB_DESCRIPTION` — optional job posting text
- `CODE_LANGUAGE` — language for CoderPad solutions
- `CODING_MODE` — `auto` or `always`
- `OPENAI_VISION_MODEL` — `gpt-4o` for screen reading (required for Scan/Watch)
- `SCREEN_WATCH_INTERVAL_SEC` — auto-scan interval when Watch is on
- `OPENAI_CHAT_MODEL` — e.g. `gpt-4o` for stronger coding answers
- `OPENAI_TRANSCRIBE_MODEL` — default `whisper-1`

## Privacy & ethics

This tool is for **personal practice and accessibility**. Using hidden overlays in real interviews may violate employer policies and interview integrity rules. Use responsibly and in line with each company’s rules.

## Project layout

```
interview-copilot/
  main.py              # App entry
  overlay.py           # Transparent PyQt6 UI + code panel
  audio_capture.py     # Loopback + VAD recording
  openai_service.py    # Whisper + GPT (behavioral + coding)
  audio_stt/           # Enterprise audio-to-text module (capture->VAD->STT)
  AUDIO_STT.md         # Audio pipeline design and operations notes
  coding_detector.py   # Auto-detect coding questions
  screen_capture.py    # Screenshot for Vision API
  screen_watcher.py    # Auto-scan on screen change
  response_parser.py   # Split approach / code sections
  capture_exclude.py   # Windows screen-share hide
  win_capture_exclude.py
  requirements-audio-enterprise.txt
  config.py
  resume_context.txt
  run.bat              # Windows launcher
  run_setup.bat        # Windows setup wizard
```
