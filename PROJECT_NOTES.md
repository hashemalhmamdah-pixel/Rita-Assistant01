# Build notes

- The initial skeleton has been replaced with working modules and tests.
- All AI-proposed actions are constrained by `ALLOWED_ACTIONS` in both the brain and controller.
- The controller rejects unknown actions, rejects non-HTTP(S) URL schemes, and requires explicit confirmation for sleep, shutdown, and restart.
- The app intentionally keeps the microphone off until the user starts listening, unless `RITA_AUTO_LISTEN=1` is set.
- Windows hardware integration is optional at import/test time; actual controls require Windows 10/11 and supported devices.

- Common Windows actions are routed by `local_commands.py` before Gemini; local controls remain usable without an AI key.
- Windows Settings pages use an explicit `ms-settings:` allow-list; arbitrary shell commands are not exposed to the model.
- The UI now has Assistant, System Controls, and scrollable Settings pages. API keys are stored in the local `.env` file, which must not be shared.
- Sleep, shutdown, and restart still require explicit confirmation.
- App launching resolves known installed application names; arbitrary executable paths and shell command strings are rejected.
