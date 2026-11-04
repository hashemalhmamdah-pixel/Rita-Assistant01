"""Microphone wake-word loop and Edge-TTS speech queue."""

from __future__ import annotations

import asyncio
from collections import deque
import importlib
import math
import os
import queue
import sys
import types
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable


class AssistantVoice:
    """Voice services run on dedicated daemon threads, never on the GUI thread."""

    def __init__(self, on_error: Callable[[str], None] | None = None) -> None:
        self.on_error = on_error or (lambda _message: None)
        self._speech_queue: queue.Queue[str | None] = queue.Queue()
        self._speech_stop = threading.Event()
        self._speaking = threading.Event()
        self._speech_thread: threading.Thread | None = None
        self._recognizer = None
        self._recognition_error_reported = False
        self._speech_unavailable = False
        self._speech_error_reported = False
        self.voice_name = os.getenv("RITA_TTS_VOICE", "en-US-AriaNeural")
        self.language = os.getenv("RITA_LANGUAGE", "en-US")
        self.stt_provider = os.getenv("RITA_STT_PROVIDER", "auto").strip().lower()
        self.groq_model = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo").strip()
        self._groq_client = None
        self._groq_error_reported = False

    @property
    def is_speaking(self) -> bool:
        return self._speaking.is_set() or not self._speech_queue.empty()

    def start_speaking(self) -> None:
        if self._speech_unavailable:
            return
        if self._speech_thread and self._speech_thread.is_alive():
            return
        self._speech_stop.clear()
        self._speech_thread = threading.Thread(
            target=self._speech_worker, name="Rita-TTS", daemon=True
        )
        self._speech_thread.start()

    def speak(self, text: str) -> None:
        message = str(text or "").strip()
        if not message or self._speech_unavailable:
            return
        self.start_speaking()
        if self._speech_thread and self._speech_thread.is_alive():
            self._speech_queue.put(message[:2000])

    def wait_until_idle(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_speaking:
                return True
            time.sleep(0.1)
        return not self.is_speaking

    def stop_speaking(self) -> None:
        # The worker polls the queue at a short interval, so an extra sentinel is
        # unnecessary and cannot be stranded if shutdown races with thread exit.
        self._speech_stop.set()

    def _discard_pending_speech(self) -> None:
        """Drop queued messages while keeping Queue's unfinished-task count sound."""
        while True:
            try:
                self._speech_queue.get_nowait()
            except queue.Empty:
                return
            else:
                self._speech_queue.task_done()

    def _speech_worker(self) -> None:
        try:
            import pygame

            pygame.mixer.init()
        except Exception as exc:
            self._speech_unavailable = True
            if not self._speech_error_reported:
                self.on_error(f"Audio playback is unavailable: {type(exc).__name__}.")
                self._speech_error_reported = True
            self._discard_pending_speech()
            return

        try:
            while not self._speech_stop.is_set():
                try:
                    message = self._speech_queue.get(timeout=0.25)
                except queue.Empty:
                    continue
                if message is None:
                    self._speech_queue.task_done()
                    break

                temp_path: str | None = None
                self._speaking.set()
                try:
                    import edge_tts

                    handle = tempfile.NamedTemporaryFile(
                        prefix="rita-", suffix=".mp3", delete=False
                    )
                    temp_path = handle.name
                    handle.close()
                    communicate = edge_tts.Communicate(message, self.voice_name)
                    asyncio.run(communicate.save(temp_path))

                    # Do not begin audible playback if shutdown happened while TTS
                    # was still downloading the generated audio.
                    if self._speech_stop.is_set():
                        continue

                    pygame.mixer.music.load(temp_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy() and not self._speech_stop.wait(0.1):
                        pass
                    if self._speech_stop.is_set():
                        pygame.mixer.music.stop()
                except Exception as exc:
                    self.on_error(f"Speech playback failed: {type(exc).__name__}.")
                finally:
                    self._speaking.clear()
                    if temp_path:
                        try:
                            Path(temp_path).unlink(missing_ok=True)
                        except OSError:
                            pass
                    self._speech_queue.task_done()
        finally:
            # This also removes messages left behind when stop_speaking() races
            # with active playback; a later start cannot consume stale work.
            self._discard_pending_speech()
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.quit()
            except Exception:
                pass

    @staticmethod
    def _install_removed_audio_module_shims() -> None:
        """Allow SpeechRecognition's unused legacy imports on Python 3.13+.

        Rita records mono 16 kHz / 16-bit PCM itself with sounddevice and passes
        that exact format to AudioData. The retired audioop conversion routines
        and AIFF reader are therefore not used by Rita's recognition path.
        """
        try:
            importlib.import_module("audioop")
        except ModuleNotFoundError:
            audioop_module = types.ModuleType("audioop")

            class AudioOpUnavailable(RuntimeError):
                pass

            def unsupported_audio_conversion(*_args: object, **_kwargs: object) -> None:
                raise AudioOpUnavailable(
                    "Audio conversion is not used by Rita's fixed PCM recording path."
                )

            audioop_module.error = AudioOpUnavailable
            for name in (
                "add", "bias", "byteswap", "lin2lin", "mul", "ratecv",
                "rms", "tomono", "tostereo", "reverse",
            ):
                setattr(audioop_module, name, unsupported_audio_conversion)
            sys.modules["audioop"] = audioop_module

        try:
            importlib.import_module("aifc")
        except ModuleNotFoundError:
            aifc_module = types.ModuleType("aifc")

            class AifcUnavailable(RuntimeError):
                pass

            def unsupported_aiff_access(*_args: object, **_kwargs: object) -> None:
                raise AifcUnavailable(
                    "AIFF files are not used by Rita's microphone recording path."
                )

            aifc_module.Error = AifcUnavailable
            aifc_module.open = unsupported_aiff_access
            sys.modules["aifc"] = aifc_module

    @staticmethod
    def _pcm16_rms(audio_data: bytes) -> float:
        """Return the root-mean-square level of little-endian 16-bit PCM."""
        usable_length = len(audio_data) - (len(audio_data) % 2)
        if usable_length <= 0:
            return 0.0
        samples = memoryview(audio_data[:usable_length]).cast("h")
        squared_total = sum(int(sample) * int(sample) for sample in samples)
        return math.sqrt(squared_total / len(samples))

    def _transcribe_with_groq(self, wav_data: bytes) -> str:
        """Transcribe microphone audio through Groq Whisper when configured."""
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not configured")
        if self._groq_client is None:
            from groq import Groq
            self._groq_client = Groq(api_key=api_key, timeout=25.0, max_retries=1)
        language = (self.language or "en").split("-")[0].split("_")[0].lower()
        response = self._groq_client.audio.transcriptions.create(
            file=("rita-microphone.wav", wav_data, "audio/wav"),
            model=self.groq_model,
            language=language if language in {"ar", "en", "es", "fr", "de", "it", "pt", "tr"} else None,
            response_format="text",
            temperature=0.0,
        )
        if isinstance(response, str):
            return response.strip()
        return str(getattr(response, "text", "") or "").strip()

    def _transcribe_with_google_https(self, audio_data: object) -> str:
        """Use SpeechRecognition's legacy recognizer with an explicit HTTPS endpoint.

        This path is opt-in only. The default and automatic path uses the user's
        configured Groq Whisper API, so microphone audio is not silently sent to
        a second provider when Groq is unavailable.
        """
        if self._recognizer is None:
            raise RuntimeError("Speech recognizer is not initialized")
        from speech_recognition.recognizers.google import recognize_legacy

        result = recognize_legacy(
            self._recognizer,
            audio_data,
            language=self.language,
            endpoint="https://www.google.com/speech-api/v2/recognize",
        )
        return str(result or "").strip()

    def listen_loop(
        self,
        stop_event: threading.Event,
        on_text: Callable[[str], None],
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        """Capture microphone PCM with PortAudio and transcribe completed phrases."""
        status = on_status or (lambda _message: None)
        sample_rate = 16_000
        block_frames = 1_600  # 100 ms at 16 kHz
        block_bytes = block_frames * 2  # mono, signed 16-bit PCM
        silence_limit = 8  # 800 ms of silence ends a phrase
        max_phrase_blocks = 80  # cap a single request at 8 seconds

        try:
            import sounddevice as sd

            self._install_removed_audio_module_shims()
            import speech_recognition as sr

            recognizer = self._recognizer or sr.Recognizer()
            self._recognizer = recognizer
            recognizer.operation_timeout = 15

            status("Calibrating microphone…")
            with sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=block_frames,
                channels=1,
                dtype="int16",
            ) as stream:
                noise_samples: list[float] = []
                for _ in range(7):
                    if stop_event.is_set():
                        status("Microphone stopped.")
                        return
                    raw_block, _ = stream.read(block_frames)
                    noise_samples.append(self._pcm16_rms(bytes(raw_block)))

                noise_level = sum(noise_samples) / max(1, len(noise_samples))
                threshold = max(260.0, noise_level * 2.8)
                pre_roll = deque(maxlen=3)
                phrase_parts: list[bytes] = []
                recording = False
                silence_blocks = 0
                needs_wake_word = os.getenv("RITA_REQUIRE_WAKE_WORD", "0").strip().lower() in {"1", "true", "yes"}
                status("Listening for the wake word…" if needs_wake_word else "Listening… say a command.")

                while not stop_event.is_set():
                    raw_block, _ = stream.read(block_frames)
                    block = bytes(raw_block)
                    if len(block) < block_bytes:
                        continue

                    # Ignore Rita's own speaker output and clear the pre-roll so
                    # the end of TTS cannot be mistaken for a user command.
                    if self.is_speaking:
                        pre_roll.clear()
                        phrase_parts.clear()
                        recording = False
                        silence_blocks = 0
                        continue

                    level = self._pcm16_rms(block)
                    if not recording:
                        noise_level = (noise_level * 0.97) + (min(level, threshold) * 0.03)
                        threshold = max(260.0, noise_level * 2.8)
                        pre_roll.append(block)
                        if level >= threshold:
                            recording = True
                            phrase_parts = list(pre_roll)
                            silence_blocks = 0
                        continue

                    phrase_parts.append(block)
                    if level < threshold * 0.72:
                        silence_blocks += 1
                    else:
                        silence_blocks = 0

                    if silence_blocks < silence_limit and len(phrase_parts) < max_phrase_blocks:
                        continue

                    captured_audio = b"".join(phrase_parts)
                    phrase_parts.clear()
                    pre_roll.clear()
                    recording = False
                    silence_blocks = 0
                    if len(captured_audio) < block_bytes * 3:
                        continue

                    try:
                        audio = sr.AudioData(captured_audio, sample_rate, 2)
                        text = ""
                        if self.stt_provider in {"auto", "groq"}:
                            if not os.getenv("GROQ_API_KEY", "").strip():
                                raise RuntimeError(
                                    "Groq voice recognition is selected, but GROQ_API_KEY is missing."
                                )
                            try:
                                text = self._transcribe_with_groq(audio.get_wav_data())
                                self._groq_error_reported = False
                            except Exception as groq_exc:
                                if not self._groq_error_reported:
                                    self.on_error(
                                        "Groq voice recognition failed: "
                                        f"{type(groq_exc).__name__}. Check the Groq key, quota, "
                                        "model, and internet connection."
                                    )
                                    self._groq_error_reported = True
                                status("Groq voice recognition unavailable; listening again…")
                                continue
                        elif self.stt_provider == "google":
                            text = self._transcribe_with_google_https(audio)
                        else:
                            raise RuntimeError(
                                "Unknown RITA_STT_PROVIDER. Choose auto, groq, or google."
                            )
                    except sr.UnknownValueError:
                        continue
                    except sr.RequestError as exc:
                        status("Speech recognition service unavailable; retrying…")
                        if not self._recognition_error_reported:
                            self.on_error(
                                "Voice recognition could not reach its speech service: "
                                f"{type(exc).__name__}. Check the internet connection or API key."
                            )
                            self._recognition_error_reported = True
                        stop_event.wait(1.5)
                        continue
                    except Exception as exc:
                        status("Could not transcribe this phrase; listening again…")
                        if not self._recognition_error_reported:
                            self.on_error(f"Voice transcription failed: {type(exc).__name__}.")
                            self._recognition_error_reported = True
                        continue

                    if text and str(text).strip():
                        self._recognition_error_reported = False
                        on_text(str(text).strip())

            status("Microphone stopped.")
        except Exception as exc:
            status("Microphone unavailable.")
            self.on_error(
                "Microphone could not start. Check Windows microphone permission, "
                "the selected input device, and sounddevice/PortAudio installation "
                f"({type(exc).__name__})."
            )

    @staticmethod
    def extract_wake_command(text: str, wake_word: str = "Rita") -> tuple[bool, str]:
        """Return whether the wake phrase is present at the start and its remaining command."""
        value = (text or "").strip()
        if not value:
            return False, ""
        phrases = [wake_word, f"hey {wake_word}", f"hi {wake_word}", "ريتا", "يا ريتا"]
        lowered = value.casefold()
        for phrase in sorted(phrases, key=len, reverse=True):
            phrase = phrase.strip()
            if lowered == phrase.casefold():
                return True, ""
            if lowered.startswith(phrase.casefold()):
                boundary = len(phrase)
                if boundary == len(value) or not value[boundary].isalnum():
                    remainder = value[boundary:].lstrip(" ,:؛،.!؟-\t")
                    return True, remainder
        return False, value
