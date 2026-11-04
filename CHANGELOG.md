# Changelog

## 2.0.0 — 2026-11-04

- Replaced old Tk UI with responsive CustomTkinter desktop workspace and DPI-aware maximized startup.
- Added Gemini-first reasoning with Gemini key rotation and Groq GPT-OSS fallback.
- Added Groq Whisper transcription as the default speech-to-text provider.
- Changed microphone push-to-talk behavior so phrases such as `open settings` work directly by default without a wake word.
- Improved common local command aliases and fixed the Settings root acknowledgement.
- Added clearer processing errors, AI provider settings, provider test action, and updated launch/setup flow.
- Added regression coverage for provider fallback, structured action allow-lists, and voice-direct local commands.

- Prevented silent fallback of microphone audio to a second provider when Groq fails; the optional Google recognizer uses its explicit HTTPS endpoint only when selected.
