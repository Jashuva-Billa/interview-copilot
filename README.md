# WboxAI — Interview Copilot (Windows 10/11)

WboxAI is an AI-powered real-time interview assistant designed and built specifically for **Windows 10/11**. It provides an undetectable, screen-share-invisible overlay window, system WASAPI audio loopback transcription, and instant AI problem solving.

## Project Structure

1. **[wboxai_app](file:///c:/Users/Jashuva/Desktop/interview-copilot/wboxai_app)**: Contains PyQt6 transparent/glass overlay window components, native Windows capture exclusion (`WDA_EXCLUDEFROMCAPTURE`), acrylic/blur effects, screen capture/watcher, configuration, and session authentication.
2. **[audio_processing](file:///c:/Users/Jashuva/Desktop/interview-copilot/audio_processing)**: Contains the Windows WASAPI system audio loopback recorder (`pyaudiowpatch`), microphone capture (`sounddevice`), and speech-to-text pipeline (`audio_stt`).
3. **[llm_project](file:///c:/Users/Jashuva/Desktop/interview-copilot/llm_project)**: Contains LLM reasoning services (OpenAI / Gemini / Claude), coding detector, prompt generators, and multi-file code parsers.

## Setup & Running on Windows

### 1. Prerequisites
- **Windows 10 or 11**
- **Python 3.10+ (64-bit)** installed and available on your PATH

### 2. Quick Setup
Open PowerShell or Command Prompt in the project folder:
```powershell
# Create Windows virtual environment
python -m venv venv

# Install Windows dependencies
.\venv\Scripts\pip.exe install -r requirements.txt
```

### 3. Configuration
Run the setup wizard to configure API keys, interview role, and settings:
```powershell
.\run_setup.bat
# or: .\venv\Scripts\python.exe run_setup.py
```

### 4. Running the Application
Launch the copilot overlay:
```powershell
.\run.bat
# or: .\venv\Scripts\python.exe run_app.py
```
Or run directly with dev flags:
```powershell
.\venv\Scripts\python.exe run_app.py --no-login --no-resume
```
