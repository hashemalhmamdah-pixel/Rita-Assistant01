# Rita — Personal AI Desktop Assistant for Windows

Rita is a Python desktop assistant for Windows 10/11. This build replaces the old-looking Tkinter window with a responsive CustomTkinter workspace and connects Gemini + Groq for conversational AI, structured desktop actions, and speech recognition.

## What this build does

- **Modern desktop interface:** maximized by default, dark navy/purple visual system, responsive assistant workspace, PC Control, Activity, and Settings pages. It follows Windows display scaling instead of forcing a fixed 100% scale.
- **Two AI providers:** Gemini (`gemini-2.5-flash`) is the primary reasoning/chat provider. Groq (`openai/gpt-oss-120b`) is the automatic fallback when Gemini is unavailable or its quota/key fails. Short conversation context is kept in memory and sent to the active provider.
- **AI voice recognition:** Groq Whisper (`whisper-large-v3-turbo`) transcribes microphone audio. If Groq fails, Rita reports the problem and resumes listening instead of silently sending microphone audio to another provider. An explicit Google recognizer option is available over HTTPS.
- **Direct voice commands:** pressing the microphone starts listening; by default, you can say `open settings` immediately. The wake phrase is optional. Turn on “Require wake phrase” in Settings if you want that behavior instead.
- **Windows integration:** open allow-listed Settings pages, Start Menu apps, known user folders, websites, volume, brightness, lock screen, list installed Start Menu apps, and display read-only system status.
- **Protected system actions:** sleep, shutdown, and restart always require a separate confirmation. The model cannot execute arbitrary shell or PowerShell commands.
- **Failure details:** errors are surfaced in Rita's conversation/activity rather than being hidden behind a generic “Something went wrong” message.

## First launch

1. Extract the archive into a normal folder inside your Windows user profile (for example, Documents or Desktop).
2. Double-click **`run_rita.bat`**. On the first launch it automatically calls `setup.bat`, creates `.venv`, installs the project dependencies, and then starts Rita. Do not run it from inside the ZIP preview.
3. The local `.env` is preconfigured for the API providers that were supplied for this build. No manual API-key editing should be needed for the first test. Keep the folder private and do not send the ZIP or `.env` to anyone.

Setup requires regular 64-bit CPython 3.15.x and an internet connection to download dependencies. Rita currently targets the user's Python 3.15.2 installation. The setup script validates that runtime and stops with a clear message if it cannot find it.

## First checks inside Rita

- Type or say `open settings` — this uses the local Windows command router and does not require an AI response.
- Try `open bluetooth settings` or `open sound settings`.
- Open **Settings** and use **Test AI connection** to test the provider path.
- Start microphone listening and say `open settings`. You do not need to say “Rita” first unless “Require wake phrase” is enabled.

## AI and speech configuration

The `.env` file contains these settings:

| Setting | Purpose |
|---|---|
| `GEMINI_API_KEYS` | Gemini key or comma-separated key list; Rita rotates keys after provider failures |
| `GEMINI_MODEL` | Gemini model ID; default `gemini-2.5-flash` |
| `GROQ_API_KEY` | Groq chat and transcription credential |
| `GROQ_MODEL` | Groq fallback chat model; default `openai/gpt-oss-120b` |
| `GROQ_STT_MODEL` | Voice transcription model; default `whisper-large-v3-turbo` |
| `RITA_STT_PROVIDER` | `auto`/`groq` uses Groq Whisper; `google` is an explicit HTTPS-only opt-in backup |
| `RITA_LANGUAGE` | Speech recognition language, e.g. `en-US` or `ar-JO` |
| `RITA_TTS_VOICE` | Microsoft Edge neural speech voice |
| `RITA_REQUIRE_WAKE_WORD` | `0` lets the microphone button submit commands directly; `1` requires the wake phrase |
| `RITA_AUTO_LISTEN` | `1` enables microphone listening at startup; default `0` |

Keys entered in Settings are saved in the local `.env` file. They are not embedded in Python source code. `.env` is excluded from Git by `.gitignore`, but this delivery intentionally includes the local file so the first run is configured; treat the entire archive as sensitive and do not share it.

## Verification

From the Rita folder, run `verify.bat` or execute `python verify.py` inside the activated environment. The suite checks syntax, dependency mappings, AI parsing/provider fallback, local command routing, action allow-lists, settings configuration writes, voice transcription routing, and worker-thread behavior.

The build container used for this packaging run has no outbound package-network access and is Linux-based. Consequently, it could not install the full Windows runtime or make live Gemini/Groq requests. The credentials are present locally in `.env`, but successful API authentication/model access must be confirmed with the in-app **Test AI connection** on the target PC. Real microphone, speaker, brightness, system-tray, and Windows Settings activation also require Windows hardware/runtime acceptance.

## Safety boundaries

Rita uses explicit local action codes and fixed Windows handlers. It does not pass model text into `cmd.exe`, PowerShell, `eval`, or `exec`. Arbitrary executable paths and non-HTTP(S) website schemes are rejected. Sleep, shutdown, and restart require a confirmation click. This keeps ordinary computer controls useful without granting a language model an unrestricted command shell.

## Project files

- `main.py` — desktop UI, command queue, local-first processing, settings.
- `ai_brain.py` — Gemini primary, key rotation, Groq fallback, structured response validation.
- `voice.py` — microphone capture, Groq Whisper / optional HTTPS Google recognition, Edge TTS.
- `local_commands.py` — deterministic English and Arabic command routing.
- `system_control.py` — allow-listed Windows action handlers.
- `setup.bat`, `run_rita.bat`, `verify.bat` — setup, launch, verification.
- `tests/` — hardware-independent regression tests.
- `SOURCES.md` — open-source and official API references used during the rebuild.
