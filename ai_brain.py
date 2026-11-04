"""Rita's multi-provider AI brain: Gemini primary, Groq failover."""
from __future__ import annotations

import json
import os
import re
from typing import Any

try:
    from google import genai
    from google.genai import types
except ImportError:  # Local commands remain usable when the SDK is absent.
    class _UnavailableGenAI:
        @staticmethod
        def Client(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("google-genai is not installed")

    genai = _UnavailableGenAI()
    types = None

try:
    from groq import Groq
except ImportError:  # pragma: no cover - covered through mocked clients
    Groq = None  # type: ignore[assignment,misc]


ACTION_CODES = {
    "OPEN_APP", "OPEN_URL", "SET_VOLUME", "VOLUME_UP", "VOLUME_DOWN",
    "MUTE", "UNMUTE", "SET_BRIGHTNESS", "BRIGHTNESS_UP", "BRIGHTNESS_DOWN",
    "OPEN_SETTINGS", "OPEN_FOLDER", "SYSTEM_INFO", "LIST_APPS", "LOCK",
    "SLEEP", "SHUTDOWN", "RESTART",
}

SYSTEM_INSTRUCTION = """You are Rita, a polished personal AI desktop assistant for Windows.
LANGUAGE AND STYLE
- Reply in the same language as the user (Arabic, English, or another language).
- Be warm, composed, accurate, and direct. Avoid canned filler and needless repetition.
- Use conversation history for context, but do not invent facts about the PC or the user.
- If a request is ambiguous, ask one short clarifying question instead of guessing.

DESKTOP ACTIONS
Return exactly one JSON object with these keys: response, action_code, action_target.
The response field is user-facing text. action_code must be one of the supported codes below
or null. action_target is a short string or null.

Supported actions and targets:
- OPEN_APP: an installed application display name, e.g. "Calculator" or "Notepad".
- OPEN_URL: a normal http:// or https:// website address.
- OPEN_SETTINGS: one of root, bluetooth, sound, display, network, network-wifi,
  appsfeatures, personalization, personalization-background, windowsupdate, privacy,
  easeofaccess, dateandtime, storagesense, powersleep, batterysaver.
- OPEN_FOLDER: one of downloads, documents, desktop, pictures, music, videos, this_pc.
- SET_VOLUME / SET_BRIGHTNESS: an integer percentage from 0 to 100.
- VOLUME_UP, VOLUME_DOWN, MUTE, UNMUTE, BRIGHTNESS_UP, BRIGHTNESS_DOWN,
  SYSTEM_INFO, LIST_APPS, LOCK: action_target must be null.
- SLEEP, SHUTDOWN, RESTART: action_target must be null. The app asks for a separate
  confirmation before any of these actions runs.

IMPORTANT SAFETY AND RELIABILITY
- Only request an action when the user clearly asks you to perform it.
- Never generate shell commands, PowerShell, scripts, arbitrary executable paths,
  registry changes, file deletion, or arbitrary code as a computer action.
- Never claim an action succeeded unless the app confirms it in a later message.
- For general questions and ordinary conversation, set action_code and action_target to null.
- Do not create an action merely because a question mentions an app or Windows setting.
- Always return valid JSON. Do not include Markdown fences or extra text outside the object.
"""


class AIBrain:
    """Gemini-first provider with key rotation and Groq fallback."""

    def __init__(self) -> None:
        self.api_keys = self._split_keys(
            os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY", "")
        )
        self.current_key_index = 0
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
        self.groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
        self.memory: list[dict[str, str]] = []
        self.max_memory = 14
        self.client: Any = None
        self.groq_client: Any = None
        self.initialization_error: str | None = None
        self.last_provider = "none"
        self._init_clients()

    @staticmethod
    def _split_keys(value: str) -> list[str]:
        return [item.strip().strip('"\'') for item in re.split(r"[,;\n]+", value) if item.strip()]

    def _init_clients(self) -> None:
        self.client = None
        self.initialization_error = None
        if self.api_keys and self.current_key_index < len(self.api_keys):
            try:
                self.client = genai.Client(api_key=self.api_keys[self.current_key_index])
            except Exception as exc:  # SDK import/config errors are shown without secrets.
                self.initialization_error = type(exc).__name__
        self.groq_client = None
        if self.groq_api_key and Groq is not None:
            try:
                self.groq_client = Groq(api_key=self.groq_api_key, timeout=35.0, max_retries=1)
            except Exception:
                self.groq_client = None

    def update_settings(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        groq_api_key: str | None = None,
        groq_model: str | None = None,
    ) -> None:
        if api_key is not None:
            self.api_keys = self._split_keys(api_key)
            self.current_key_index = 0
        if model_name:
            self.model_name = model_name.strip() or "gemini-2.5-flash"
            self.current_key_index = 0
        if groq_api_key is not None:
            self.groq_api_key = groq_api_key.strip()
        if groq_model:
            self.groq_model = groq_model.strip() or "openai/gpt-oss-120b"
        self._init_clients()

    def _switch_key(self) -> bool:
        self.current_key_index += 1
        if self.current_key_index < len(self.api_keys):
            self._init_clients()
            return self.client is not None
        self.client = None
        return False

    def _history_for_gemini(self, command: str) -> list[Any]:
        if types is None:
            raise RuntimeError("google-genai SDK is not installed")
        contents = []
        for message in self.memory:
            role = "model" if message["role"] in {"assistant", "model"} else "user"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(message["text"])]))
        contents.append(types.Content(role="user", parts=[types.Part.from_text(command)]))
        return contents

    def _call_gemini(self, command: str) -> str:
        if not self.client:
            raise RuntimeError("Gemini client is unavailable")
        if types is None:
            raise RuntimeError("google-genai SDK is not installed")
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.45,
            max_output_tokens=1800,
        )
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=self._history_for_gemini(command),
            config=config,
        )
        return str(getattr(response, "text", "") or "").strip()

    def _call_groq(self, command: str) -> str:
        if not self.groq_client:
            raise RuntimeError("Groq client is unavailable")
        messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
        messages.extend(
            {
                "role": "assistant" if item["role"] in {"assistant", "model"} else "user",
                "content": item["text"],
            }
            for item in self.memory
        )
        messages.append({"role": "user", "content": command})
        response_schema = {
            "type": "object",
            "properties": {
                "response": {"type": "string"},
                "action_code": {
                    "anyOf": [
                        {"type": "string", "enum": sorted(ACTION_CODES)},
                        {"type": "null"},
                    ]
                },
                "action_target": {"type": ["string", "null"]},
            },
            "required": ["response", "action_code", "action_target"],
            "additionalProperties": False,
        }
        result = self.groq_client.chat.completions.create(
            model=self.groq_model,
            messages=messages,
            temperature=0.45,
            max_completion_tokens=1600,
            reasoning_effort="low",
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "rita_desktop_response",
                    "strict": True,
                    "schema": response_schema,
                },
            },
        )
        return str(result.choices[0].message.content or "").strip()

    @staticmethod
    def _parse_response(raw: str) -> tuple[str, str | None, str | None]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Keep the assistant useful if a provider returns plain prose;
            # prose must never be interpreted as a local action.
            if text and not text.startswith("{"):
                return text, None, None
            raise
        if not isinstance(data, dict):
            raise ValueError("AI response must be a JSON object")
        response = str(data.get("response") or "I am here. ").strip()
        action = str(data.get("action_code") or "").strip().upper() or None
        target = data.get("action_target")
        if action not in ACTION_CODES:
            action = None
            target = None
        if target is not None:
            target = str(target).strip()[:256] or None
        if action is None:
            target = None
        return response[:8000], action, target

    def _remember(self, command: str, response: str) -> None:
        self.memory.extend([
            {"role": "user", "text": command},
            # Gemini's content API expects the provider role name "model".
            # Groq maps this role back to "assistant" when building messages.
            {"role": "model", "text": response},
        ])
        self.memory = self.memory[-self.max_memory * 2 :]

    @staticmethod
    def _short_error(exc: Exception) -> str:
        message = str(exc).lower()
        if "429" in message or "rate limit" in message or "quota" in message:
            return "rate limit or quota"
        if "401" in message or "403" in message or "api key" in message or "unauthorized" in message:
            return "API key or permission"
        if "timeout" in message or "connection" in message or "network" in message:
            return "network connection"
        return type(exc).__name__

    def process_command(self, command: str) -> tuple[str, str | None, str | None]:
        cleaned = (command or "").strip()
        if not cleaned:
            return "Tell me what you need.", None, None

        errors: list[str] = []
        # Gemini is primary. Rotate through all supplied keys when quota/auth fails.
        if self.api_keys:
            if self.client is None and self.current_key_index >= len(self.api_keys):
                self.current_key_index = 0
                self._init_clients()
            for _ in range(max(1, len(self.api_keys))):
                if not self.client:
                    if not self._switch_key():
                        break
                try:
                    raw = self._call_gemini(cleaned)
                    parsed = self._parse_response(raw)
                    self.last_provider = "Gemini"
                    self._remember(cleaned, parsed[0])
                    return parsed
                except Exception as exc:
                    errors.append(f"Gemini: {self._short_error(exc)}")
                    if not self._switch_key():
                        break

        # Groq is a full secondary provider, not just a health indicator.
        if self.groq_client:
            try:
                parsed = self._parse_response(self._call_groq(cleaned))
                self.last_provider = "Groq"
                self._remember(cleaned, parsed[0])
                return parsed
            except Exception as exc:
                errors.append(f"Groq: {self._short_error(exc)}")

        if not self.api_keys and not self.groq_api_key:
            return "No AI provider API keys are configured. Add a Gemini or Groq key in Settings. Windows quick actions still work locally.", None, None
        if not self.client and self.api_keys and not self.groq_client:
            return "I couldn't use all my API keys or reach the fallback provider. Check Gemini and Groq credentials, model availability, quota, and internet connection in Settings.", None, None
        details = "; ".join(errors) or "provider unavailable"
        return f"I couldn't reach an AI provider ({details}). Check your connection and provider settings, then try again.", None, None

    def clear_memory(self) -> None:
        self.memory.clear()
