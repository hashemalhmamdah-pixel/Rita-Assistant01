# Rita 2.0 — QA report

## Current result

<badge>Source verification passed</badge>

- `python verify.py`: **52 tests passed; 0 failures; 0 errors**.
- Python syntax compilation: passed.
- Static audit: passed for syntax, defined names, required package mappings, imports, and absence of dynamic `eval`/`exec` usage. Several long-line style warnings are non-blocking.

## Regression coverage

- Gemini response parsing, bounded conversation history, key rotation, and quota exhaustion.
- Groq-only response generation and Gemini-to-Groq fallback.
- AI action allow-list enforcement; arbitrary action strings are dropped.
- English and Arabic local Windows commands, including `open settings` without AI.
- Microphone phrase submission without wake word by default and optional wake-word enforcement.
- Groq Whisper request shape and language selection; optional Google STT uses the explicit HTTPS endpoint and is never a silent fallback.
- Settings `.env` writes preserve unrelated values and reject newline injection.
- Windows Settings URI allow-list, app path rejection, URL scheme/credential validation, numeric bounds, and destructive-action confirmation.
- Worker-thread startup/shutdown behavior.

## Not yet verified

- This container has no outbound package-network access; new third-party UI/AI libraries could not be installed for a runtime render test.
- No live requests were made to Gemini or Groq, so credential validity, quota, and model access remain unknown.
- This is not a Windows host. Windows 10/11 UI rendering, microphone permission, sound devices, Edge TTS, tray icon, settings URI activation, application discovery, volume, brightness, and power APIs need real-device testing.

The first-run script installs all dependencies and starts the app using the user's CPython 3.15.x installation. The archive contains a local `.env` by explicit request; keep that archive private.
