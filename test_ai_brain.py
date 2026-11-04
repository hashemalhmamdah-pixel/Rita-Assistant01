"""Tests for the currently supplied Gemini-key-rotation implementation."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import ai_brain
from ai_brain import AIBrain


def fake_types():
    return SimpleNamespace(
        Content=lambda role, parts: {"role": role, "parts": parts},
        Part=SimpleNamespace(from_text=lambda text: text),
        GenerateContentConfig=lambda **kwargs: kwargs,
    )


def client_with_response(response_text: str):
    models = SimpleNamespace(
        generate_content=Mock(return_value=SimpleNamespace(text=response_text))
    )
    return SimpleNamespace(models=models), models


class AIBrainTests(unittest.TestCase):
    def test_missing_api_key_returns_setup_message_without_calling_gemini(self):
        with patch.dict(os.environ, {}, clear=True):
            brain = AIBrain()

        response, action, target = brain.process_command("tell me a story")
        self.assertIn("API keys", response)
        self.assertIsNone(action)
        self.assertIsNone(target)

    def test_successful_response_is_parsed_and_kept_in_bounded_memory(self):
        client, models = client_with_response(
            '{"response":"Hello there.","action_code":null,"action_target":null}'
        )
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True),
            patch.object(ai_brain.genai, "Client", return_value=client),
            patch.object(ai_brain, "types", fake_types()),
        ):
            brain = AIBrain()
            brain.max_memory = 1
            response, action, target = brain.process_command("hello")
            self.assertEqual((response, action, target), ("Hello there.", None, None))
            brain.process_command("hello again")

        self.assertEqual(len(brain.memory), 2)
        self.assertEqual(brain.memory[-1]["role"], "model")
        self.assertEqual(models.generate_content.call_count, 2)
        kwargs = models.generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"], brain.model_name)
        self.assertEqual(kwargs["config"]["response_mime_type"], "application/json")
        self.assertEqual(kwargs["contents"][-1]["role"], "user")

    def test_quota_failure_rotates_to_next_api_key(self):
        first_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(side_effect=RuntimeError("429 quota exhausted"))
            )
        )
        second_client, second_models = client_with_response(
            '{"response":"Recovered.","action_code":"OPEN_APP",'
            '"action_target":"Calculator"}'
        )
        with (
            patch.dict(
                os.environ,
                {"GEMINI_API_KEYS": "first-key,second-key"},
                clear=True,
            ),
            patch.object(
                ai_brain.genai,
                "Client",
                side_effect=[first_client, second_client],
            ),
            patch.object(ai_brain, "types", fake_types()),
        ):
            brain = AIBrain()
            response, action, target = brain.process_command("open Calculator")

        self.assertEqual((response, action, target), ("Recovered.", "OPEN_APP", "Calculator"))
        self.assertEqual(brain.current_key_index, 1)
        self.assertEqual(second_models.generate_content.call_count, 1)

    def test_exhausted_quota_clears_client_until_settings_change(self):
        exhausted_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(side_effect=RuntimeError("429 quota exhausted")))
        )
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "one-key"}, clear=True),
            patch.object(ai_brain.genai, "Client", return_value=exhausted_client),
            patch.object(ai_brain, "types", fake_types()),
        ):
            brain = AIBrain()
            response, action, target = brain.process_command("hello")
        self.assertIn("all my API keys", response)
        self.assertIsNone(action)
        self.assertIsNone(target)
        self.assertIsNone(brain.client)

    def test_plain_prose_response_is_kept_without_action(self):
        client, _models = client_with_response("I can help with that.")
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True),
            patch.object(ai_brain.genai, "Client", return_value=client),
            patch.object(ai_brain, "types", fake_types()),
        ):
            brain = AIBrain()
            response, action, target = brain.process_command("hello")

        self.assertEqual(response, "I can help with that.")
        self.assertIsNone(action)
        self.assertIsNone(target)

    def test_model_update_resets_key_rotation_and_reinitializes_client(self):
        first_client, _first_models = client_with_response('{"response":"first","action_code":null,"action_target":null}')
        second_client, _second_models = client_with_response('{"response":"second","action_code":null,"action_target":null}')
        with (
            patch.dict(os.environ, {"GEMINI_API_KEYS": "first-key,second-key"}, clear=True),
            patch.object(ai_brain.genai, "Client", side_effect=[first_client, second_client]),
            patch.object(ai_brain, "types", fake_types()),
        ):
            brain = AIBrain()
            brain.current_key_index = 1
            brain.update_settings(model_name="gemini-2.5-flash")
        self.assertEqual(brain.current_key_index, 0)
        self.assertIs(brain.client, second_client)

    def test_clear_memory_removes_previous_turns(self):
        client, _models = client_with_response(
            '{"response":"Hello.","action_code":null,"action_target":null}'
        )
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True),
            patch.object(ai_brain.genai, "Client", return_value=client),
            patch.object(ai_brain, "types", fake_types()),
        ):
            brain = AIBrain()
            brain.process_command("hello")
            self.assertTrue(brain.memory)
            brain.clear_memory()
        self.assertEqual(brain.memory, [])

    def test_groq_is_used_when_no_gemini_key_is_configured(self):
        groq_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"response":"Groq is online.","action_code":null,"action_target":null}'
            ))]
        )
        create = Mock(return_value=groq_response)
        fake_groq = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        with (
            patch.dict(os.environ, {"GROQ_API_KEY": "groq-test-key"}, clear=True),
            patch.object(ai_brain, "Groq", return_value=fake_groq),
        ):
            brain = AIBrain()
            result = brain.process_command("hello")

        self.assertEqual(result, ("Groq is online.", None, None))
        self.assertEqual(brain.last_provider, "Groq")
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["model"], "openai/gpt-oss-120b")
        self.assertEqual(create.call_args.kwargs["response_format"]["type"], "json_schema")

    def test_groq_fallback_runs_after_gemini_quota_error(self):
        exhausted = SimpleNamespace(models=SimpleNamespace(
            generate_content=Mock(side_effect=RuntimeError("429 quota exhausted"))
        ))
        groq_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"response":"Recovered with Groq.","action_code":null,"action_target":null}'
        ))])
        fake_groq = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=groq_response)
        )))
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test-key", "GROQ_API_KEY": "groq-test-key"}, clear=True),
            patch.object(ai_brain.genai, "Client", return_value=exhausted),
            patch.object(ai_brain, "Groq", return_value=fake_groq),
            patch.object(ai_brain, "types", fake_types()),
        ):
            brain = AIBrain()
            result = brain.process_command("hello")

        self.assertEqual(result[0], "Recovered with Groq.")
        self.assertEqual(brain.last_provider, "Groq")

    def test_groq_action_is_limited_to_allowlisted_actions(self):
        response = AIBrain._parse_response(
            '{"response":"Done.","action_code":"RUN_POWERSHELL","action_target":"whoami"}'
        )
        self.assertEqual(response, ("Done.", None, None))


if __name__ == "__main__":
    unittest.main()
