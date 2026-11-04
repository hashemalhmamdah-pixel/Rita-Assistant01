# Rita — engineering references

This project uses original code and an original visual layout. The repositories and documentation below were reviewed for architecture and design patterns; code was not copied wholesale.

## Open-source desktop assistants

- [Open.Jarvis](https://github.com/dmrr35/Open.Jarvis) — Windows-first assistant with local command routing, a provider fallback boundary, diagnostics, and an explicit permissions approach. Its MIT license was used as a reference for architectural study, not as a source of copied implementation.
- [Claire](https://github.com/Yukariii04/claire) — Windows voice-assistant pipeline combining sounddevice capture, voice activity detection, Groq Whisper transcription, an LLM stage, TTS, and a CustomTkinter interface. Reviewed for the separation of audio capture, transcription, reasoning, and tool execution.
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) — modern Tkinter widgets with Windows high-DPI support. Rita uses its public widget package rather than drawing a fake UI image.
- [pygame-ce 2.5.8 release](https://github.com/pygame-community/pygame-ce/releases/tag/2.5.8) — release notes list CPython 3.15 support; the distribution has a CPython 3.15 Windows x64 wheel.

## Official AI integrations

- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/) — `google-genai` client interface and Gemini Developer API.
- [Google Gen AI SDK releases](https://github.com/googleapis/python-genai/releases) — Python 3.15 support is listed in the 2.33.0 release notes.
- [Groq Python SDK](https://github.com/groq/groq-python) — official Python API client.
- [Groq structured outputs](https://console.groq.com/docs/structured-outputs) — JSON schema output used to keep the model response machine-readable.
- [Groq speech-to-text](https://console.groq.com/docs/speech-to-text) — Whisper model and audio transcription API.
- [SpeechRecognition Google recognizer implementation](https://github.com/Uberi/speech_recognition/blob/master/speech_recognition/recognizers/google.py) — optional Google backup is explicitly routed through the HTTPS endpoint only when selected.
- [GPT-OSS 120B on Groq](https://console.groq.com/docs/model/openai/gpt-oss-120b) — model details and JSON schema capability.

## Desktop platform references

- [Windows Settings URI scheme](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings) — official `ms-settings:` page activation.
- [Pycaw](https://pypi.org/project/pycaw/) — Windows Core Audio controls.
- [SoundDevice](https://python-sounddevice.readthedocs.io/) — microphone capture through PortAudio.

## Implementation decisions

- Common and deterministic requests go through `local_commands.py` before the LLM. A phrase like `open settings` therefore does not depend on an AI response.
- AI output is constrained to a structured response and an allow-list of action codes. The controller independently validates parameters.
- Gemini is the primary reasoning provider; Groq is used when Gemini cannot complete the request. Groq Whisper is also used for speech-to-text when configured.
- The UI uses CustomTkinter's actual widgets and DPI-aware windowing, not a screenshot or static mockup.
