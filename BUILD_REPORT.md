# Rita 2.0 — build report

## Source and runtime target

- Based on the latest Rita project archive in the user's Library: `Rita_Assistant_Python3152_Full_Upgrade.zip`.
- Target runtime remains regular 64-bit CPython 3.15.x (the intended target is Python 3.15.2 on Windows).
- Main UI: CustomTkinter 6.x, with automatic Windows DPI scaling and maximized startup.
- AI: Gemini `gemini-2.5-flash` primary; Groq `openai/gpt-oss-120b` fallback; Groq Whisper `whisper-large-v3-turbo` speech transcription.

## Changes delivered

- Modernized the desktop pages and adjusted minimum dimensions for laptop screens; removed forced 1.0 scaling so CustomTkinter can respect Windows display scaling.
- Enabled direct voice command submission by default from the microphone button; wake phrase can be required through Settings.
- Improved English command aliases including `open settings`, `open the settings`, `please open settings`, and `show me settings`.
- Added Gemini key rotation, Groq failover, strict structured Groq responses, and action allow-list validation.
- Added Groq Whisper transcription with language selection; Google recognition is an explicit opt-in HTTPS-only alternative, not an automatic fallback.
- Updated first-run launcher so a missing `.venv` triggers setup automatically.
- Included user's local `.env` only in this sensitive, private delivery archive so no manual API-key entry is necessary.

## Verification results

- Python compilation: passed on the available container interpreter (CPython 3.13.5).
- Static dependency/security audit: passed; non-blocking long-line style warnings remain.
- Hardware-independent regression suite: **52 tests passed, 0 failures, 0 errors**.
- Tests include mocked Gemini quota/key rotation, Groq-only mode, Gemini-to-Groq fallback, Groq speech transcription arguments, explicit HTTPS Google transcription routing, invalid model action rejection, local Windows routing, direct voice command behavior, and wake-word opt-in behavior.

## Not verified in this build environment

- The container has no package-network access, so CustomTkinter, Groq SDK, and the live Google Gen AI SDK were not installed here.
- The build host is Linux, not Windows. Real UI rendering, CPython 3.15.2 package installation, mic capture, Edge TTS playback, API authentication, Windows Settings activation, Start Menu lookup, system tray, volume, brightness, and power actions require acceptance on the target Windows machine.
- Live Gemini and Groq API requests could not be made because network access was unavailable. The keys are present in the local `.env`, but authentication is not claimed as tested.

The deliverable is a source ZIP with automatic setup/launch scripts, not a compiled or digitally signed `.exe` installer.
