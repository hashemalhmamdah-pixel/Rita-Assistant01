import struct
import sys
import unittest
from unittest.mock import patch

from voice import AssistantVoice


class WakeWordTests(unittest.TestCase):
    def test_wake_word_with_inline_command(self):
        activated, command = AssistantVoice.extract_wake_command("Rita, open Calculator")
        self.assertTrue(activated)
        self.assertEqual(command, "open Calculator")

    def test_wake_word_alone_arms_followup(self):
        activated, command = AssistantVoice.extract_wake_command("Hey Rita")
        self.assertTrue(activated)
        self.assertEqual(command, "")

    def test_arabic_wake_word(self):
        activated, command = AssistantVoice.extract_wake_command("يا ريتا افتحي المتصفح")
        self.assertTrue(activated)
        self.assertEqual(command, "افتحي المتصفح")

    def test_unrelated_phrase_does_not_activate(self):
        activated, _ = AssistantVoice.extract_wake_command("I saw Rita yesterday")
        self.assertFalse(activated)


class MicrophoneCaptureTests(unittest.TestCase):
    def test_pcm16_rms_uses_signed_sample_magnitudes(self):
        samples = struct.pack("<hhhh", 0, 100, -100, 200)
        self.assertAlmostEqual(AssistantVoice._pcm16_rms(samples), 15000 ** 0.5)

    def test_pcm16_rms_handles_empty_and_odd_input(self):
        self.assertEqual(AssistantVoice._pcm16_rms(b""), 0.0)
        self.assertEqual(AssistantVoice._pcm16_rms(b"\x64\x00\xff"), 100.0)

    def test_removed_audio_modules_receive_narrow_compatibility_shims(self):
        previous = {
            name: sys.modules.pop(name, None)
            for name in ("audioop", "aifc")
        }
        try:
            with patch(
                "voice.importlib.import_module",
                side_effect=ModuleNotFoundError,
            ):
                AssistantVoice._install_removed_audio_module_shims()
            import audioop
            import aifc

            with self.assertRaises(audioop.error):
                audioop.rms(b"\x00\x00", 2)
            with self.assertRaises(aifc.Error):
                aifc.open("unused.aiff", "rb")
        finally:
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    def test_google_backup_uses_explicit_https_endpoint(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        recognize_legacy = Mock(return_value="open settings")
        fake_google = SimpleNamespace(recognize_legacy=recognize_legacy)
        voice_instance = AssistantVoice()
        voice_instance._recognizer = object()
        audio_data = object()
        with patch.dict(
            sys.modules,
            {"speech_recognition.recognizers.google": fake_google},
        ):
            result = voice_instance._transcribe_with_google_https(audio_data)

        self.assertEqual(result, "open settings")
        self.assertEqual(recognize_legacy.call_args.args, (voice_instance._recognizer, audio_data))
        self.assertEqual(
            recognize_legacy.call_args.kwargs["endpoint"],
            "https://www.google.com/speech-api/v2/recognize",
        )

    def test_groq_transcription_uses_selected_language_and_model(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        fake_create = Mock(return_value="open settings")

        class FakeGroq:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=fake_create))

        fake_module = SimpleNamespace(Groq=FakeGroq)
        voice_instance = AssistantVoice()
        voice_instance.language = "ar-JO"
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}), patch.dict(
            sys.modules, {"groq": fake_module}
        ):
            result = voice_instance._transcribe_with_groq(b"wav-audio")

        self.assertEqual(result, "open settings")
        self.assertEqual(fake_create.call_args.kwargs["model"], "whisper-large-v3-turbo")
        self.assertEqual(fake_create.call_args.kwargs["language"], "ar")
        self.assertEqual(fake_create.call_args.kwargs["response_format"], "text")


if __name__ == "__main__":
    unittest.main()
