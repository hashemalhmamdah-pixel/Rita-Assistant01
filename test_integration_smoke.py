"""Hardware-independent integration and worker-thread regression tests."""
from __future__ import annotations

import asyncio
import queue
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_brain
import main
import system_control
import voice
from ai_brain import AIBrain


class ImportSmokeTests(unittest.TestCase):
    def test_all_application_modules_import(self):
        self.assertTrue(hasattr(main, "RitaAssistant"))
        self.assertTrue(hasattr(voice, "AssistantVoice"))
        self.assertTrue(hasattr(system_control, "SystemController"))
        self.assertTrue(hasattr(ai_brain, "AIBrain"))

    def test_brain_without_api_key_does_not_request_external_actions(self):
        from unittest.mock import patch
        import os

        with patch.dict(os.environ, {}, clear=True):
            brain = AIBrain()
        response, action, target = brain.process_command("open Calculator")
        self.assertIn("API keys", response)
        self.assertIsNone(action)
        self.assertIsNone(target)


class RitaWorkerTests(unittest.TestCase):
    class FakeVoice:
        def __init__(self, on_error=None):
            self.on_error = on_error
            self.spoken = []
            self.started = False
            self.stopped = False

        def start_speaking(self):
            self.started = True

        def speak(self, text):
            self.spoken.append(text)

        def stop_speaking(self):
            self.stopped = True

        def listen_loop(self, *_args):
            return None

        @staticmethod
        def extract_wake_command(text, wake_word="Rita"):
            return voice.AssistantVoice.extract_wake_command(text, wake_word)

    class FakeBrain:
        def __init__(self, result=None):
            self.result = result or ("Processed successfully", None, None)
            self.cleared = False

        def process_command(self, _command):
            return self.result

        def clear_memory(self):
            self.cleared = True

    class FakeSystemController:
        def __init__(self):
            self.calls = []

        def execute_action(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return "Action completed."

    def _make_assistant(self, brain_result=None, confirmation=False):
        captured = queue.Queue()
        fake_voice = self.FakeVoice()
        fake_brain = self.FakeBrain(brain_result)
        fake_system = self.FakeSystemController()
        assistant = None
        with patch.object(main, "AssistantVoice", return_value=fake_voice), patch.object(
            main, "AIBrain", return_value=fake_brain
        ), patch.object(main, "SystemController", return_value=fake_system):
            assistant = main.RitaAssistant(
                lambda kind, payload: captured.put((kind, payload)),
                lambda _action: confirmation,
            )
        return assistant, captured, fake_voice, fake_brain, fake_system


    def test_open_settings_is_submitted_from_voice_without_wake_word(self):
        with patch.dict("os.environ", {"RITA_REQUIRE_WAKE_WORD": "0"}):
            assistant, captured, _voice, brain, system = self._make_assistant()
        try:
            with patch.dict("os.environ", {"RITA_REQUIRE_WAKE_WORD": "0"}):
                assistant._handle_recognized_text("open settings")
            deadline = time.monotonic() + 2
            seen_user = False
            seen_assistant = False
            while time.monotonic() < deadline and not seen_assistant:
                try:
                    kind, payload = captured.get(timeout=0.1)
                except queue.Empty:
                    continue
                seen_user |= kind == "user" and payload == "open settings"
                seen_assistant |= kind == "assistant" and "Opening Windows Settings" in payload
            self.assertTrue(seen_user)
            self.assertTrue(seen_assistant)
            self.assertEqual(system.calls[0][0], ("open_settings", "root"))
            self.assertEqual(brain.result, ("Processed successfully", None, None))
        finally:
            assistant.shutdown()
            assistant._processor_thread.join(timeout=2)

    def test_wake_word_can_be_required_as_an_explicit_setting(self):
        with patch.dict("os.environ", {"RITA_REQUIRE_WAKE_WORD": "1"}):
            assistant, captured, _voice, brain, system = self._make_assistant()
        try:
            with patch.dict("os.environ", {"RITA_REQUIRE_WAKE_WORD": "1"}):
                assistant._handle_recognized_text("open settings")
            seen = []
            while not captured.empty():
                seen.append(captured.get_nowait())
            self.assertIn(("heard", "open settings"), seen)
            self.assertFalse(any(kind == "user" for kind, _ in seen))
            self.assertEqual(brain.result, ("Processed successfully", None, None))
            self.assertEqual(system.calls, [])
        finally:
            assistant.shutdown()
            assistant._processor_thread.join(timeout=2)

    def test_processor_thread_consumes_queue_and_shuts_down(self):
        assistant, captured, fake_voice, _brain, _system = self._make_assistant()
        try:
            assistant.submit_text("test command")
            seen = []
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    kind, payload = captured.get(timeout=0.1)
                except queue.Empty:
                    continue
                seen.append((kind, payload))
                if kind == "assistant":
                    break
            self.assertIn(("assistant", "Processed successfully"), seen)
        finally:
            assistant.shutdown()
            assistant._processor_thread.join(timeout=2)
        self.assertFalse(assistant._processor_thread.is_alive())
        self.assertTrue(fake_voice.stopped)

    def test_local_windows_settings_command_works_without_calling_ai_brain(self):
        assistant, captured, _voice, brain, system = self._make_assistant()
        try:
            assistant.submit_text("open bluetooth settings")
            deadline = time.monotonic() + 2
            messages = []
            while time.monotonic() < deadline:
                try:
                    kind, payload = captured.get(timeout=0.1)
                except queue.Empty:
                    continue
                if kind == "assistant":
                    messages.append(payload)
                    break
            self.assertTrue(messages)
            self.assertIn("Opening Windows bluetooth settings", messages[0])
            self.assertEqual(brain.result, ("Processed successfully", None, None))
            self.assertEqual(system.calls[0][0], ("open_settings", "bluetooth"))
        finally:
            assistant.shutdown()
            assistant._processor_thread.join(timeout=2)

    def test_settings_writer_preserves_unrelated_env_values(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            module_path = Path(folder) / "main.py"
            module_path.write_text("", encoding="utf-8")
            env_path = Path(folder) / ".env"
            env_path.write_text("OTHER_SETTING=keep\nGEMINI_MODEL=old\n", encoding="utf-8")
            with patch.object(main, "__file__", str(module_path)):
                main.RitaWindow._write_env_values({"GEMINI_MODEL": "new-model"})
            content = env_path.read_text(encoding="utf-8")
            self.assertIn("OTHER_SETTING=keep", content)
            self.assertIn('GEMINI_MODEL="new-model"', content)

    def test_settings_writer_rejects_newline_injection(self):
        with self.assertRaises(ValueError):
            main.RitaWindow._write_env_values({"GEMINI_MODEL": "model\nOTHER=value"})

    def test_ai_action_names_are_normalized_to_controller_contract(self):
        self.assertEqual(main.RitaAssistant._normalize_ai_action("OPEN_APP"), "open_app")
        self.assertEqual(main.RitaAssistant._normalize_ai_action("SET_VOLUME"), "volume_set")
        self.assertEqual(main.RitaAssistant._normalize_ai_action(None), None)

    def test_declined_power_confirmation_never_calls_system_controller(self):
        assistant, captured, _voice, _brain, system = self._make_assistant(
            ("Please confirm.", "shutdown", None), confirmation=False
        )
        try:
            assistant.submit_text("shutdown")
            deadline = time.monotonic() + 2
            messages = []
            while time.monotonic() < deadline:
                try:
                    kind, payload = captured.get(timeout=0.1)
                except queue.Empty:
                    continue
                if kind == "assistant":
                    messages.append(payload)
                    break
            self.assertTrue(messages)
            self.assertIn("Cancelled", messages[0])
            self.assertEqual(system.calls, [])
        finally:
            assistant.shutdown()
            assistant._processor_thread.join(timeout=2)


    def test_speech_worker_cleans_up_and_can_restart(self):
        class FakeMusic:
            def __init__(self):
                self.loaded = []

            def load(self, path):
                self.loaded.append(path)

            def play(self):
                return None

            def get_busy(self):
                return False

            def stop(self):
                return None

        class FakeMixer:
            def __init__(self):
                self.music = FakeMusic()
                self.initialized = False

            def init(self):
                self.initialized = True

            def get_init(self):
                return self.initialized

            def quit(self):
                self.initialized = False

        mixer = FakeMixer()
        fake_pygame = types.SimpleNamespace(mixer=mixer)

        class FakeCommunicate:
            def __init__(self, _text, _voice):
                pass

            async def save(self, path):
                await asyncio.sleep(0)
                Path(path).write_bytes(b"mock audio")

        fake_edge_tts = types.SimpleNamespace(Communicate=FakeCommunicate)
        with patch.dict(sys.modules, {"pygame": fake_pygame, "edge_tts": fake_edge_tts}):
            speaker = voice.AssistantVoice()
            speaker.speak("first message")
            self.assertTrue(speaker.wait_until_idle(timeout=2))
            self.assertEqual(len(mixer.music.loaded), 1)
            self.assertFalse(Path(mixer.music.loaded[0]).exists())

            speaker.stop_speaking()
            self.assertIsNotNone(speaker._speech_thread)
            speaker._speech_thread.join(timeout=2)
            self.assertFalse(speaker._speech_thread.is_alive())
            self.assertEqual(speaker._speech_queue.unfinished_tasks, 0)

            speaker.speak("second message")
            self.assertTrue(speaker.wait_until_idle(timeout=2))
            self.assertEqual(len(mixer.music.loaded), 2)
            speaker.stop_speaking()
            speaker._speech_thread.join(timeout=2)
            self.assertFalse(speaker._speech_thread.is_alive())
            self.assertEqual(speaker._speech_queue.unfinished_tasks, 0)

    def test_approved_power_confirmation_executes_with_confirmation_flag(self):
        assistant, captured, _voice, _brain, system = self._make_assistant(
            ("Please confirm.", "shutdown", None), confirmation=True
        )
        try:
            assistant.submit_text("shutdown")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    kind, _payload = captured.get(timeout=0.1)
                except queue.Empty:
                    continue
                if kind == "assistant":
                    break
            self.assertEqual(len(system.calls), 1)
            self.assertEqual(system.calls[0][0], ("shutdown", None))
            self.assertTrue(system.calls[0][1]["confirmed"])
        finally:
            assistant.shutdown()
            assistant._processor_thread.join(timeout=2)

    def test_window_exit_interrupts_a_pending_confirmation_wait(self):
        window = main.RitaWindow.__new__(main.RitaWindow)
        window.confirmations = queue.Queue()
        window._exiting = True
        started = time.monotonic()
        self.assertFalse(window._confirm_from_worker("shutdown"))
        self.assertLess(time.monotonic() - started, 0.5)


if __name__ == "__main__":
    unittest.main()
