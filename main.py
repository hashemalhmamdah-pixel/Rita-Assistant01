"""Rita Windows desktop assistant: Tkinter UI, tray icon and worker threads."""

from __future__ import annotations

import os
import queue
import threading
import time
from tkinter import messagebox
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

load_dotenv(override=True)

from ai_brain import AIBrain
from system_control import CONFIRMATION_ACTIONS, SystemController
from local_commands import route_local_command
from voice import AssistantVoice


class RitaAssistant:
    """Threaded assistant core; UI interaction is delegated through callbacks."""

    def __init__(self, emit: Any, request_confirmation: Any) -> None:
        self.emit = emit
        self.request_confirmation = request_confirmation
        self.voice = AssistantVoice(on_error=lambda message: self.emit("error", message))
        self.voice.start_speaking()
        self.sys_ctrl = SystemController()
        self.brain = AIBrain()
        self._commands: queue.Queue[str | None] = queue.Queue()
        self._listener_stop = threading.Event()
        self._listener_thread: threading.Thread | None = None
        self._processor_thread = threading.Thread(
            target=self._processing_loop, name="Rita-Command-Worker", daemon=True
        )
        self._processor_stop = threading.Event()
        self._wake_word = os.getenv("RITA_WAKE_WORD", "Rita").strip() or "Rita"
        self._wake_armed_until = 0.0
        self._processor_thread.start()

    def start_listening(self) -> None:
        if self._listener_thread and self._listener_thread.is_alive():
            return
        self._listener_stop.clear()
        self._listener_thread = threading.Thread(
            target=self.voice.listen_loop,
            args=(self._listener_stop, self._handle_recognized_text, self._listener_status),
            name="Rita-Microphone-Worker",
            daemon=True,
        )
        self._listener_thread.start()
        self.emit("status", "Starting microphone…")

    def stop_listening(self) -> None:
        self._listener_stop.set()
        self.emit("status", "Stopping microphone…")

    def submit_text(self, text: str) -> None:
        cleaned = (text or "").strip()
        if cleaned:
            self.emit("user", cleaned)
            self._commands.put(cleaned)

    def _listener_status(self, message: str) -> None:
        self.emit("status", message)

    def _handle_recognized_text(self, text: str) -> None:
        self.emit("heard", text)
        activated, command = self.voice.extract_wake_command(text, self._wake_word)
        if activated:
            if command:
                self._wake_armed_until = 0.0
                self.submit_text(command)
            else:
                self._wake_armed_until = time.monotonic() + 8.0
                self.voice.speak("Yes? I'm listening.")
                self.emit("status", "Wake word heard — waiting for your command…")
            return

        if time.monotonic() <= self._wake_armed_until:
            self._wake_armed_until = 0.0
            self.submit_text(text)
            return

        # The microphone button is an explicit user action. By default, every
        # recognized phrase is a command; a wake word can be required in Settings.
        if os.getenv("RITA_REQUIRE_WAKE_WORD", "0").strip().lower() not in {"1", "true", "yes"}:
            self.submit_text(text)

    def _processing_loop(self) -> None:
        while not self._processor_stop.is_set():
            try:
                command = self._commands.get(timeout=0.25)
            except queue.Empty:
                continue
            if command is None:
                self._commands.task_done()
                break
            try:
                if command.casefold() in {"stop listening", "pause listening"}:
                    self.stop_listening()
                    self._deliver_response("Okay, microphone listening is paused.")
                    continue
                # Deterministic Windows commands are handled locally first, so
                # common PC controls work even when Gemini is not configured.
                local = route_local_command(command)
                if local is not None:
                    response, action_code, action_target = local
                    if action_code == "__local_error__":
                        self._deliver_response(response)
                        continue
                else:
                    response, action_code, action_target = self.brain.process_command(command)
                    action_code = self._normalize_ai_action(action_code)

                if action_code:
                    if action_code in CONFIRMATION_ACTIONS:
                        approved = self.request_confirmation(action_code)
                        if not approved:
                            self._deliver_response("Cancelled. I did not change the power state.")
                            continue
                    try:
                        result = self.sys_ctrl.execute_action(
                            action_code, action_target,
                            confirmed=(action_code in CONFIRMATION_ACTIONS),
                        )
                        response = f"{response}\n{result}".strip()
                    except Exception as exc:
                        response = f"I couldn't complete that action: {exc}"
                self._deliver_response(response)
            except Exception as exc:
                detail = str(exc).strip() or type(exc).__name__
                self.emit("error", f"Command failed: {detail}")
                self._deliver_response(f"I couldn't complete that command: {detail}")
            finally:
                self._commands.task_done()

    @staticmethod
    def _normalize_ai_action(action_code: str | None) -> str | None:
        aliases = {
            "OPEN_APP": "open_app", "OPEN_URL": "open_url",
            "SET_VOLUME": "volume_set", "VOLUME_UP": "volume_up",
            "VOLUME_DOWN": "volume_down", "MUTE": "volume_mute",
            "UNMUTE": "volume_unmute", "SET_BRIGHTNESS": "brightness_set",
            "BRIGHTNESS_UP": "brightness_up", "BRIGHTNESS_DOWN": "brightness_down",
            "OPEN_SETTINGS": "open_settings", "OPEN_FOLDER": "open_folder",
            "SYSTEM_INFO": "system_info", "LIST_APPS": "list_apps", "LOCK": "lock",
            "SLEEP": "sleep", "SHUTDOWN": "shutdown", "RESTART": "restart",
        }
        if action_code is None:
            return None
        cleaned = str(action_code).strip()
        return aliases.get(cleaned.upper(), cleaned.casefold())

    def _deliver_response(self, response: str) -> None:
        self.emit("assistant", response)
        self.voice.speak(response)

    def shutdown(self) -> None:
        self.stop_listening()
        self._processor_stop.set()
        self._commands.put(None)
        self.voice.stop_speaking()


try:
    import customtkinter as ctk
except ImportError:  # Import-safe for tests; setup.bat installs the desktop UI package.
    ctk = None  # type: ignore[assignment]


class RitaWindow:
    """Premium, responsive desktop workspace for the Rita assistant core."""

    BG = "#0B1018"
    SIDEBAR = "#101824"
    SURFACE = "#121C29"
    CARD = "#172333"
    CARD_HOVER = "#203149"
    INPUT = "#0E1723"
    TEXT = "#F0F4FA"
    MUTED = "#91A0B4"
    ACCENT = "#A78BFA"
    ACCENT_HOVER = "#BBA8FF"
    TEAL = "#5EEAD4"
    GREEN = "#63D6A5"
    AMBER = "#F5C478"
    RED = "#F18488"
    BORDER = "#2A3A4E"
    FONT = "Segoe UI"

    def __init__(self, root: Any) -> None:
        if ctk is None:
            raise RuntimeError(
                "The modern Rita interface is not installed. Run setup.bat to install requirements."
            )
        self.root = root
        self.root.title("Rita | Personal AI Workspace")
        self.root.configure(fg_color=self.BG)
        # Keep the layout usable on common 1366×768 laptop screens while
        # allowing the maximized workspace to use larger displays naturally.
        self.root.minsize(900, 580)
        self.root.geometry("1180x760")
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.confirmations: queue.Queue[
            tuple[str, threading.Event, dict[str, bool]]
        ] = queue.Queue()
        self.tray_icon = None
        self._exiting = False
        self._activity: list[str] = []
        self.pages: dict[str, Any] = {}
        self.nav_buttons: dict[str, Any] = {}
        self.assistant = RitaAssistant(self._emit, self._confirm_from_worker)
        self._build_sidebar()
        self._build_workspace()
        self._build_pages()
        self.show_page("assistant")
        self._start_tray()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-Return>", lambda _event: self._send_message())
        self.root.bind("<Escape>", lambda _event: self.chat_entry.focus_set())
        self.root.after(100, self._drain_queues)
        self._append_message(
            "Rita",
            "Welcome back. I can help with questions and work directly with supported "
            "Windows settings, apps, folders, audio, display and system tools. "
            "Try saying ‘open settings’ or ask me anything.",
        )
        self.assistant.voice.speak("Hello. Rita is ready.")
        if os.getenv("RITA_AUTO_LISTEN", "0").strip().lower() in {"1", "true", "yes"}:
            self.assistant.start_listening()

    # ------------------------------ visual system -----------------------------
    def _font(self, size: int = 13, weight: str = "normal") -> Any:
        return ctk.CTkFont(family=self.FONT, size=size, weight=weight)

    def _panel(self, parent: Any, *, color: str | None = None, radius: int = 18,
               border: bool = False) -> Any:
        return ctk.CTkFrame(
            parent, fg_color=color or self.CARD, corner_radius=radius,
            border_width=1 if border else 0,
            border_color=self.BORDER if border else color or self.CARD,
        )

    def _label(self, parent: Any, text: str, *, size: int = 13,
               color: str | None = None, weight: str = "normal",
               wrap: int = 0, **kwargs: Any) -> Any:
        return ctk.CTkLabel(
            parent, text=text, font=self._font(size, weight),
            text_color=color or self.TEXT, wraplength=wrap, **kwargs,
        )

    def _action_button(self, parent: Any, text: str, command: Any, *,
                       primary: bool = False, compact: bool = False,
                       color: str | None = None, width: int | None = None) -> Any:
        background = color or (self.ACCENT if primary else self.CARD_HOVER)
        foreground = "#171327" if primary else self.TEXT
        return ctk.CTkButton(
            parent, text=text, command=command, width=width or 0,
            height=36 if compact else 44, corner_radius=11 if compact else 13,
            fg_color=background, hover_color=self.ACCENT_HOVER if primary else "#2A405A",
            text_color=foreground, font=self._font(12 if compact else 13, "bold" if primary else "normal"),
            border_width=0,
        )

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self.root, width=244, corner_radius=0, fg_color=self.SIDEBAR)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(8, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=22, pady=(26, 34))
        mark = ctk.CTkFrame(brand, width=45, height=45, corner_radius=15, fg_color=self.ACCENT)
        mark.pack(side="left")
        mark.pack_propagate(False)
        self._label(mark, "R", size=25, color="#171327", weight="bold").place(relx=.5, rely=.48, anchor="center")
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", padx=12)
        self._label(brand_text, "RITA", size=19, weight="bold").pack(anchor="w")
        self._label(brand_text, "PERSONAL AI", size=9, color=self.MUTED, weight="bold").pack(anchor="w", pady=(2, 0))

        self._label(sidebar, "WORKSPACE", size=10, color=self.MUTED, weight="bold").pack(anchor="w", padx=23, pady=(0, 10))
        nav_items = [
            ("assistant", "◈", "Assistant"),
            ("controls", "▦", "PC Control"),
            ("activity", "◷", "Activity"),
            ("settings", "⚙", "Settings"),
        ]
        for key, symbol, title in nav_items:
            button = ctk.CTkButton(
                sidebar, text=f"   {symbol}     {title}", anchor="w", height=47,
                corner_radius=12, fg_color="transparent", hover_color=self.CARD_HOVER,
                text_color=self.MUTED, font=self._font(13, "bold"),
                command=lambda name=key: self.show_page(name),
            )
            button.pack(fill="x", padx=13, pady=3)
            self.nav_buttons[key] = button

        spacer = ctk.CTkFrame(sidebar, fg_color="transparent", height=10)
        spacer.pack(fill="both", expand=True)
        system_card = self._panel(sidebar, color="#172638", radius=16, border=True)
        system_card.pack(fill="x", padx=14, pady=(10, 15))
        self._label(system_card, "YOUR DEVICE", size=9, color=self.MUTED, weight="bold").pack(anchor="w", padx=14, pady=(13, 6))
        self._label(system_card, "Windows workspace", size=13, weight="bold").pack(anchor="w", padx=14)
        self.sidebar_status = self._label(system_card, "●  Assistant is ready", size=10, color=self.GREEN)
        self.sidebar_status.pack(anchor="w", padx=14, pady=(7, 13))
        self._label(sidebar, "Rita Desktop  ·  2.0", size=9, color="#65758B").pack(anchor="w", padx=22, pady=(0, 18))

    def _build_workspace(self) -> None:
        workspace = ctk.CTkFrame(self.root, fg_color=self.BG, corner_radius=0)
        workspace.grid(row=0, column=1, sticky="nsew", padx=(0, 0))
        workspace.grid_columnconfigure(0, weight=1)
        workspace.grid_rowconfigure(1, weight=1)
        self.workspace = workspace

        header = ctk.CTkFrame(workspace, fg_color="transparent", height=82)
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(22, 12))
        header.grid_columnconfigure(0, weight=1)
        self.page_title = self._label(header, "Assistant", size=25, weight="bold")
        self.page_title.grid(row=0, column=0, sticky="w")
        self.page_subtitle = self._label(header, "Your desktop, understood.", size=11, color=self.MUTED)
        self.page_subtitle.grid(row=1, column=0, sticky="w", pady=(3, 0))
        header_right = ctk.CTkFrame(header, fg_color="transparent")
        header_right.grid(row=0, column=1, rowspan=2, sticky="e")
        self.ai_badge = ctk.CTkLabel(
            header_right, text=self._provider_text(), height=34, corner_radius=17,
            fg_color="#172D2C" if self._has_ai_key() else "#302A20",
            text_color=self.GREEN if self._has_ai_key() else self.AMBER,
            font=self._font(10, "bold"), padx=14,
        )
        self.ai_badge.pack(side="left", padx=(0, 10))
        self._action_button(header_right, "Settings", lambda: self.show_page("settings"), compact=True).pack(side="left")

        self.page_host = ctk.CTkFrame(workspace, fg_color="transparent")
        self.page_host.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 25))
        self.page_host.grid_rowconfigure(0, weight=1)
        self.page_host.grid_columnconfigure(0, weight=1)

    def _provider_text(self) -> str:
        providers = []
        if os.getenv("GEMINI_API_KEYS", "").strip() or os.getenv("GEMINI_API_KEY", "").strip():
            providers.append("Gemini")
        if os.getenv("GROQ_API_KEY", "").strip():
            providers.append("Groq")
        return "●  AI CONFIGURED  ·  " + " + ".join(providers) if providers else "●  AI SETUP NEEDED"

    def _has_ai_key(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEYS", "").strip() or os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GROQ_API_KEY", "").strip())

    def _new_page(self, key: str) -> Any:
        frame = ctk.CTkFrame(self.page_host, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        self.pages[key] = frame
        return frame

    def _build_pages(self) -> None:
        self._build_assistant_page()
        self._build_controls_page()
        self._build_activity_page()
        self._build_settings_page()

    # -------------------------------- assistant -------------------------------
    def _build_assistant_page(self) -> None:
        page = self._new_page("assistant")
        page.grid_columnconfigure(0, weight=1)
        page.grid_columnconfigure(1, weight=0, minsize=255)
        page.grid_rowconfigure(0, weight=1)

        conversation = self._panel(page, color=self.SURFACE, radius=20, border=True)
        conversation.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        conversation.grid_columnconfigure(0, weight=1)
        conversation.grid_rowconfigure(1, weight=1)
        conversation_header = ctk.CTkFrame(conversation, fg_color="transparent")
        conversation_header.grid(row=0, column=0, sticky="ew", padx=20, pady=(17, 9))
        avatar = ctk.CTkFrame(conversation_header, width=36, height=36, corner_radius=13, fg_color="#30294D")
        avatar.pack(side="left")
        avatar.pack_propagate(False)
        self._label(avatar, "R", size=18, color=self.ACCENT, weight="bold").place(relx=.5, rely=.5, anchor="center")
        heading = ctk.CTkFrame(conversation_header, fg_color="transparent")
        heading.pack(side="left", padx=11)
        self._label(heading, "Rita", size=14, weight="bold").pack(anchor="w")
        self._label(heading, "Your personal AI assistant", size=10, color=self.MUTED).pack(anchor="w")
        self._action_button(conversation_header, "Clear chat", self._clear_chat, compact=True).pack(side="right")

        self.chat_feed = ctk.CTkScrollableFrame(
            conversation, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=self.BORDER, scrollbar_button_hover_color=self.MUTED,
        )
        self.chat_feed.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 10))
        self.chat_feed.grid_columnconfigure(0, weight=1)

        composer = ctk.CTkFrame(conversation, fg_color=self.CARD, corner_radius=16)
        composer.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        composer.grid_columnconfigure(0, weight=1)
        self.message_var = ctk.StringVar()
        self.chat_entry = ctk.CTkEntry(
            composer, textvariable=self.message_var, placeholder_text="Ask Rita anything…",
            height=48, corner_radius=13, fg_color=self.INPUT, border_width=0,
            text_color=self.TEXT, placeholder_text_color="#708098", font=self._font(13),
        )
        self.chat_entry.grid(row=0, column=0, sticky="ew", padx=(9, 7), pady=9)
        self.chat_entry.bind("<Return>", lambda _event: self._send_message())
        self.listen_button = ctk.CTkButton(
            composer, text="●", width=44, height=44, corner_radius=13,
            fg_color="#24334A", hover_color="#314764", text_color=self.TEAL,
            font=self._font(17, "bold"), command=self._toggle_listening,
        )
        self.listen_button.grid(row=0, column=1, padx=(0, 7), pady=9)
        self._action_button(composer, "Send  ↗", self._send_message, primary=True).grid(
            row=0, column=2, padx=(0, 9), pady=9
        )
        self.status_var = ctk.StringVar(value="Ready · Microphone is off")
        self.status_line = self._label(conversation, "", size=10, color=self.MUTED)
        self.status_line.grid(row=3, column=0, sticky="w", padx=22, pady=(0, 10))

        rail = ctk.CTkFrame(page, fg_color="transparent")
        rail.grid(row=0, column=1, sticky="nsew")
        rail.grid_columnconfigure(0, weight=1)
        welcome = self._panel(rail, color="#1B2440", radius=18, border=True)
        welcome.pack(fill="x", pady=(0, 13))
        self._label(welcome, "GOOD TO HAVE YOU HERE", size=9, color=self.ACCENT, weight="bold").pack(anchor="w", padx=16, pady=(16, 7))
        self._label(welcome, "A smarter way\nto use your PC.", size=20, weight="bold", wrap=210, justify="left").pack(anchor="w", padx=16)
        self._label(welcome, "Ask naturally. Rita handles supported Windows tasks locally and uses AI for the rest.", size=10, color="#B0BDD0", wrap=210, justify="left").pack(anchor="w", padx=16, pady=(9, 17))

        quick = self._panel(rail, color=self.CARD, radius=18, border=True)
        quick.pack(fill="x", pady=(0, 13))
        self._label(quick, "QUICK ACCESS", size=9, color=self.MUTED, weight="bold").pack(anchor="w", padx=15, pady=(15, 8))
        for label, command in [
            ("Windows Settings  ↗", "open settings"),
            ("Bluetooth settings", "open bluetooth settings"),
            ("Sound settings", "open sound settings"),
            ("Open Downloads", "open Downloads"),
            ("System status", "system status"),
        ]:
            self._action_button(quick, label, lambda cmd=command: self._quick_command(cmd), compact=True).pack(fill="x", padx=11, pady=4)
        ctk.CTkFrame(quick, fg_color="transparent", height=5).pack()

        voice = self._panel(rail, color=self.CARD, radius=18, border=True)
        voice.pack(fill="x")
        self._label(voice, "VOICE CONTROL", size=9, color=self.MUTED, weight="bold").pack(anchor="w", padx=15, pady=(15, 7))
        self._label(voice, "Talk to Rita", size=14, weight="bold").pack(anchor="w", padx=15)
        self._label(voice, "Press the microphone to start listening. You can say ‘open settings’ directly.", size=10, color=self.MUTED, wrap=215, justify="left").pack(anchor="w", padx=15, pady=(6, 13))
        self._action_button(voice, "Start listening", self._toggle_listening, primary=True).pack(fill="x", padx=12, pady=(0, 13))

    def _append_message(self, speaker: str, message: str, system: bool = False) -> None:
        if not hasattr(self, "chat_feed"):
            return
        mine = speaker.casefold() in {"you", "user"}
        row = ctk.CTkFrame(self.chat_feed, fg_color="transparent")
        row.pack(fill="x", padx=5, pady=5)
        bubble_color = "#292344" if mine else ("#302024" if system else self.CARD)
        bubble = ctk.CTkFrame(row, fg_color=bubble_color, corner_radius=16, border_width=1,
                              border_color="#514276" if mine else ("#63363A" if system else self.BORDER))
        bubble.pack(side="right" if mine else "left", anchor="e" if mine else "w", padx=(45, 0) if mine else (0, 45))
        title_color = self.ACCENT if mine else (self.RED if system else self.TEAL)
        self._label(bubble, speaker.upper(), size=9, color=title_color, weight="bold").pack(anchor="w", padx=14, pady=(10, 3))
        self._label(bubble, str(message), size=12, color=self.TEXT, wrap=650, justify="left").pack(anchor="w", padx=14, pady=(0, 12))
        try:
            self.chat_feed.after(80, lambda: self.chat_feed._parent_canvas.yview_moveto(1.0))
        except Exception:
            pass

    # ---------------------------------- controls ------------------------------
    def _build_controls_page(self) -> None:
        page = self._new_page("controls")
        page.grid_rowconfigure(1, weight=1)
        self._label(page, "Take control of your workspace", size=21, weight="bold").pack(anchor="w")
        self._label(page, "Shortcuts run through Windows directly; they do not need an AI response.", size=11, color=self.MUTED).pack(anchor="w", pady=(5, 17))
        scroller = ctk.CTkScrollableFrame(page, fg_color="transparent", corner_radius=0)
        scroller.pack(fill="both", expand=True)
        groups = [
            ("WINDOWS SETTINGS", "Native Windows configuration pages", [
                ("All settings", "open settings"), ("Bluetooth", "open bluetooth settings"),
                ("Sound", "open sound settings"), ("Display", "open display settings"),
                ("Wi-Fi & Network", "open wifi settings"), ("Windows Update", "open windows update settings"),
                ("Personalization", "open personalization settings"), ("Installed apps", "open apps settings"),
                ("Privacy", "open privacy settings"), ("Power & Sleep", "open power settings"),
            ]),
            ("APPS & FILES", "Your everyday desktop destinations", [
                ("Calculator", "open Calculator"), ("Notepad", "open Notepad"),
                ("Task Manager", "open Task Manager"), ("File Explorer", "open File Explorer"),
                ("Downloads", "open Downloads"), ("Documents", "open Documents"),
                ("Desktop", "open Desktop"), ("This PC", "open This PC"),
            ]),
            ("SYSTEM", "Quick diagnostics and session controls", [
                ("System status", "system status"), ("Installed app list", "list apps"),
                ("Lock screen", "lock screen"), ("Sleep…", "sleep"),
                ("Restart…", "restart"), ("Shut down…", "shutdown"),
            ]),
        ]
        for title, subtitle, actions in groups:
            card = self._panel(scroller, color=self.CARD, radius=18, border=True)
            card.pack(fill="x", pady=(0, 13))
            self._label(card, title, size=10, color=self.MUTED, weight="bold").pack(anchor="w", padx=18, pady=(16, 3))
            self._label(card, subtitle, size=11, color=self.TEXT).pack(anchor="w", padx=18, pady=(0, 10))
            grid = ctk.CTkFrame(card, fg_color="transparent")
            grid.pack(fill="x", padx=14, pady=(0, 14))
            for col in range(4):
                grid.grid_columnconfigure(col, weight=1)
            for index, (label, command) in enumerate(actions):
                row, col = divmod(index, 4)
                self._action_button(grid, label, lambda cmd=command: self._quick_command(cmd), compact=True).grid(
                    row=row, column=col, sticky="ew", padx=4, pady=4
                )

    # ---------------------------------- activity ------------------------------
    def _build_activity_page(self) -> None:
        page = self._new_page("activity")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x", pady=(0, 16))
        self._label(top, "Your recent interactions", size=21, weight="bold").pack(side="left")
        self._action_button(top, "Clear activity", self._clear_activity, compact=True).pack(side="right")
        self.activity_feed = ctk.CTkScrollableFrame(page, fg_color="transparent", corner_radius=0)
        self.activity_feed.pack(fill="both", expand=True)
        self.activity_feed.grid_columnconfigure(0, weight=1)
        self._label(self.activity_feed, "Your actions and conversations will appear here.", size=12, color=self.MUTED).pack(anchor="w", padx=12, pady=15)

    def _record_activity(self, item: str) -> None:
        stamp = time.strftime("%H:%M")
        self._activity.append(f"{stamp}   {item}")
        self._activity = self._activity[-100:]
        if hasattr(self, "activity_feed"):
            self._refresh_activity()

    def _refresh_activity(self) -> None:
        if not hasattr(self, "activity_feed"):
            return
        for child in self.activity_feed.winfo_children():
            child.destroy()
        if not self._activity:
            self._label(self.activity_feed, "No activity yet.", size=12, color=self.MUTED).pack(anchor="w", padx=12, pady=15)
            return
        for item in reversed(self._activity):
            card = self._panel(self.activity_feed, color=self.CARD, radius=12, border=True)
            card.pack(fill="x", pady=4)
            self._label(card, item, size=11, color=self.TEXT, wrap=900, justify="left").pack(anchor="w", padx=15, pady=12)

    def _clear_activity(self) -> None:
        self._activity.clear()
        self._refresh_activity()

    # ---------------------------------- settings ------------------------------
    def _build_settings_page(self) -> None:
        page = self._new_page("settings")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        self._label(page, "Make Rita yours", size=21, weight="bold").pack(anchor="w")
        self._label(page, "Configure AI providers, voice input and how Rita interacts with Windows.", size=11, color=self.MUTED).pack(anchor="w", pady=(5, 16))
        scroller = ctk.CTkScrollableFrame(page, fg_color="transparent", corner_radius=0)
        scroller.pack(fill="both", expand=True)
        columns = ctk.CTkFrame(scroller, fg_color="transparent")
        columns.pack(fill="x")
        columns.grid_columnconfigure(0, weight=1)
        columns.grid_columnconfigure(1, weight=1)

        ai = self._panel(columns, color=self.CARD, radius=18, border=True)
        ai.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 13))
        self._label(ai, "AI PROVIDERS", size=10, color=self.MUTED, weight="bold").pack(anchor="w", padx=18, pady=(17, 3))
        self._label(ai, "Gemini · Primary", size=15, weight="bold").pack(anchor="w", padx=18, pady=(0, 9))
        self.gemini_key_var = ctk.StringVar()
        self.gemini_model_var = ctk.StringVar(value=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
        self.groq_key_var = ctk.StringVar()
        self.groq_model_var = ctk.StringVar(value=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
        self._settings_field(ai, "Gemini API key(s) · comma separated", self.gemini_key_var, secret=True,
                             placeholder="Leave blank to keep the saved key")
        self._settings_field(ai, "Gemini model", self.gemini_model_var)
        self._label(ai, "Groq · Automatic fallback", size=15, weight="bold").pack(anchor="w", padx=18, pady=(12, 5))
        self._settings_field(ai, "Groq API key", self.groq_key_var, secret=True,
                             placeholder="Leave blank to keep the saved key")
        self._settings_field(ai, "Groq chat model", self.groq_model_var)
        self.ai_config_status = self._label(ai, self._provider_text(), size=10, color=self.GREEN if self._has_ai_key() else self.AMBER, wrap=430)
        self.ai_config_status.pack(anchor="w", padx=18, pady=(8, 17))

        voice = self._panel(columns, color=self.CARD, radius=18, border=True)
        voice.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 13))
        self._label(voice, "VOICE & LISTENING", size=10, color=self.MUTED, weight="bold").pack(anchor="w", padx=18, pady=(17, 3))
        self._label(voice, "Talk naturally", size=15, weight="bold").pack(anchor="w", padx=18, pady=(0, 9))
        self.wake_var = ctk.StringVar(value=os.getenv("RITA_WAKE_WORD", "Rita"))
        self.language_var = ctk.StringVar(value=os.getenv("RITA_LANGUAGE", "en-US"))
        self.tts_var = ctk.StringVar(value=os.getenv("RITA_TTS_VOICE", "en-US-AriaNeural"))
        self.stt_var = ctk.StringVar(value=os.getenv("RITA_STT_PROVIDER", "auto"))
        self.auto_listen_var = ctk.BooleanVar(value=os.getenv("RITA_AUTO_LISTEN", "0").lower() in {"1", "true", "yes"})
        self.require_wake_var = ctk.BooleanVar(value=os.getenv("RITA_REQUIRE_WAKE_WORD", "0").lower() in {"1", "true", "yes"})
        self._settings_field(voice, "Wake phrase", self.wake_var)
        self._settings_field(voice, "Speech language (en-US / ar-JO)", self.language_var)
        self._settings_field(voice, "Neural voice (Edge TTS)", self.tts_var)
        self._settings_field(voice, "Speech recognition provider (auto / groq / google)", self.stt_var)
        ctk.CTkCheckBox(
            voice, text="Start microphone automatically on launch", variable=self.auto_listen_var,
            fg_color=self.ACCENT, hover_color=self.ACCENT_HOVER, text_color=self.TEXT,
            border_color=self.BORDER, font=self._font(11), checkbox_width=19, checkbox_height=19,
        ).pack(anchor="w", padx=18, pady=(14, 8))
        ctk.CTkCheckBox(
            voice, text="Require wake phrase before each command", variable=self.require_wake_var,
            fg_color=self.ACCENT, hover_color=self.ACCENT_HOVER, text_color=self.TEXT,
            border_color=self.BORDER, font=self._font(11), checkbox_width=19, checkbox_height=19,
        ).pack(anchor="w", padx=18, pady=(0, 17))

        footer = ctk.CTkFrame(scroller, fg_color="transparent")
        footer.pack(fill="x", pady=(2, 15))
        self._action_button(footer, "Save changes", self._save_settings, primary=True).pack(side="left")
        self._action_button(footer, "Test AI connection", self._test_ai, compact=True).pack(side="left", padx=8)
        self._action_button(footer, "Clear saved keys", self._remove_api_key, compact=True, color="#482B36").pack(side="left")
        self.settings_status = ctk.StringVar(value="Credentials are stored on this PC in the local .env file.")
        self._label(scroller, "", size=1).pack()
        ctk.CTkLabel(scroller, textvariable=self.settings_status, font=self._font(10),
                     text_color=self.MUTED, anchor="w").pack(anchor="w", pady=(0, 12))

    def _settings_field(self, parent: Any, label: str, variable: Any, *,
                        secret: bool = False, placeholder: str = "") -> Any:
        self._label(parent, label, size=10, color=self.TEXT, weight="bold").pack(anchor="w", padx=18, pady=(9, 5))
        entry = ctk.CTkEntry(
            parent, textvariable=variable, height=39, corner_radius=10,
            fg_color=self.INPUT, border_color=self.BORDER, border_width=1,
            text_color=self.TEXT, placeholder_text=placeholder,
            placeholder_text_color="#74849A", font=self._font(11),
            show="•" if secret else "",
        )
        entry.pack(fill="x", padx=18, pady=(0, 2))
        return entry

    # -------------------------------- navigation ------------------------------
    def show_page(self, name: str) -> None:
        if name not in self.pages:
            return
        self.pages[name].tkraise()
        titles = {
            "assistant": ("Assistant", "Your desktop, understood."),
            "controls": ("PC Control", "Your Windows tools, one click away."),
            "activity": ("Activity", "A clear history of what Rita has done."),
            "settings": ("Settings", "Configure the AI and voice experience."),
        }
        title, subtitle = titles[name]
        self.page_title.configure(text=title)
        self.page_subtitle.configure(text=subtitle)
        for key, button in self.nav_buttons.items():
            active = key == name
            button.configure(
                fg_color=self.CARD_HOVER if active else "transparent",
                text_color=self.TEXT if active else self.MUTED,
            )
        if name == "activity":
            self._refresh_activity()

    # -------------------------------- interaction -----------------------------
    def _emit(self, kind: str, payload: Any) -> None:
        self.events.put((kind, payload))

    def _send_message(self) -> None:
        message = self.message_var.get().strip()
        if not message:
            return
        self.message_var.set("")
        self.assistant.submit_text(message)
        self.chat_entry.focus_set()

    def _quick_command(self, command: str) -> None:
        self.show_page("assistant")
        self.assistant.submit_text(command)

    def _toggle_listening(self) -> None:
        worker = self.assistant._listener_thread
        if worker and worker.is_alive() and not self.assistant._listener_stop.is_set():
            self.assistant.stop_listening()
        else:
            self.assistant.start_listening()
        self.chat_entry.focus_set()

    def _clear_chat(self) -> None:
        for child in self.chat_feed.winfo_children():
            child.destroy()
        self.assistant.brain.clear_memory()
        self._append_message("Rita", "Conversation cleared. What would you like to do next?")

    @staticmethod
    def _write_env_values(updates: dict[str, str]) -> None:
        allowed_keys = {
            "GEMINI_API_KEY", "GEMINI_API_KEYS", "GEMINI_MODEL",
            "GROQ_API_KEY", "GROQ_MODEL", "GROQ_STT_MODEL",
            "RITA_WAKE_WORD", "RITA_LANGUAGE", "RITA_TTS_VOICE",
            "RITA_AUTO_LISTEN", "RITA_REQUIRE_WAKE_WORD", "RITA_STT_PROVIDER",
        }
        if not set(updates).issubset(allowed_keys):
            raise ValueError("Unsupported settings key.")
        if any(not isinstance(value, str) or any(ch in value for ch in "\r\n\0")
               for value in updates.values()):
            raise ValueError("Settings values cannot contain newlines or null bytes.")
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        existing: list[str] = []
        if os.path.isfile(env_path):
            with open(env_path, "r", encoding="utf-8") as handle:
                existing = handle.read().splitlines()
        remaining = dict(updates)
        output: list[str] = []
        for line in existing:
            stripped = line.strip()
            key = stripped.split("=", 1)[0].removeprefix("export ").strip() if "=" in stripped else ""
            if key in remaining:
                value = remaining.pop(key)
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                output.append(f'{key}="{escaped}"')
            else:
                output.append(line)
        for key, value in remaining.items():
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            output.append(f'{key}="{escaped}"')
        temp_path = env_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(output).rstrip() + "\n")
        os.replace(temp_path, env_path)

    def _save_settings(self) -> None:
        updates = {
            "GEMINI_MODEL": self.gemini_model_var.get().strip() or "gemini-2.5-flash",
            "GROQ_MODEL": self.groq_model_var.get().strip() or "openai/gpt-oss-120b",
            "RITA_WAKE_WORD": self.wake_var.get().strip() or "Rita",
            "RITA_LANGUAGE": self.language_var.get().strip() or "en-US",
            "RITA_TTS_VOICE": self.tts_var.get().strip() or "en-US-AriaNeural",
            "RITA_STT_PROVIDER": self.stt_var.get().strip().lower() or "auto",
            "RITA_AUTO_LISTEN": "1" if self.auto_listen_var.get() else "0",
            "RITA_REQUIRE_WAKE_WORD": "1" if self.require_wake_var.get() else "0",
        }
        gemini_key = self.gemini_key_var.get().strip()
        groq_key = self.groq_key_var.get().strip()
        if gemini_key:
            updates["GEMINI_API_KEY"] = gemini_key
            updates["GEMINI_API_KEYS"] = gemini_key
        if groq_key:
            updates["GROQ_API_KEY"] = groq_key
        try:
            self._write_env_values(updates)
            os.environ.update(updates)
            self.assistant.brain.update_settings(
                api_key=gemini_key if gemini_key else None,
                model_name=updates["GEMINI_MODEL"],
                groq_api_key=groq_key if groq_key else None,
                groq_model=updates["GROQ_MODEL"],
            )
            self.assistant.voice.voice_name = updates["RITA_TTS_VOICE"]
            self.assistant.voice.language = updates["RITA_LANGUAGE"]
            self.assistant.voice.stt_provider = updates["RITA_STT_PROVIDER"]
            self.assistant.voice.groq_model = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
            self.assistant.voice._groq_client = None
            self.assistant.voice._groq_error_reported = False
            self.assistant._wake_word = updates["RITA_WAKE_WORD"]
            self.gemini_key_var.set("")
            self.groq_key_var.set("")
            self.settings_status.set("Saved. Both AI providers and voice preferences are active.")
            self.ai_config_status.configure(text=self._provider_text(), text_color=self.GREEN if self._has_ai_key() else self.AMBER)
            self.ai_badge.configure(text=self._provider_text(), text_color=self.GREEN if self._has_ai_key() else self.AMBER)
            if self.auto_listen_var.get():
                self.assistant.start_listening()
            else:
                self.assistant.stop_listening()
            self._record_activity("Updated AI and voice settings")
        except Exception as exc:
            self.settings_status.set(f"Could not save settings: {type(exc).__name__}: {exc}")

    def _test_ai(self) -> None:
        self.show_page("assistant")
        self.assistant.submit_text("Reply with a short confirmation that Rita's AI connection is working.")

    def _remove_api_key(self) -> None:
        try:
            self._write_env_values({
                "GEMINI_API_KEY": "", "GEMINI_API_KEYS": "", "GROQ_API_KEY": "",
            })
            for key in ("GEMINI_API_KEY", "GEMINI_API_KEYS", "GROQ_API_KEY"):
                os.environ.pop(key, None)
            self.assistant.brain.update_settings(api_key="", groq_api_key="")
            self.gemini_key_var.set("")
            self.groq_key_var.set("")
            self.settings_status.set("Saved credentials removed. Local Windows controls remain available.")
            self.ai_config_status.configure(text=self._provider_text(), text_color=self.AMBER)
            self.ai_badge.configure(text=self._provider_text(), text_color=self.AMBER)
            self._record_activity("Removed saved AI credentials")
        except Exception as exc:
            self.settings_status.set(f"Could not remove keys: {type(exc).__name__}")

    def _confirm_from_worker(self, action_code: str) -> bool:
        event = threading.Event()
        result = {"approved": False}
        self.confirmations.put((action_code, event, result))
        deadline = time.monotonic() + 120.0
        while not event.is_set():
            if self._exiting:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            event.wait(min(0.25, remaining))
        return result.get("approved", False)

    def _drain_queues(self) -> None:
        if self._exiting:
            return
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "user":
                self._append_message("You", str(payload))
                self._record_activity(f"You: {payload}")
            elif kind == "heard":
                if hasattr(self, "status_var"):
                    self.status_var.set(f"Heard: {payload}")
                    self.status_line.configure(text=self.status_var.get())
            elif kind == "assistant":
                self._append_message("Rita", str(payload))
                self._record_activity(str(payload).splitlines()[-1])
            elif kind == "status":
                if hasattr(self, "status_var"):
                    self.status_var.set(str(payload))
                    self.status_line.configure(text=str(payload))
                lower = str(payload).lower()
                if any(word in lower for word in ("stopped", "paused", "unavailable")):
                    self.listen_button.configure(text="●")
                    self.sidebar_status.configure(text="●  Assistant is ready", text_color=self.GREEN)
                elif "listening" in lower or "calibrating" in lower:
                    self.listen_button.configure(text="Ⅱ")
                    self.sidebar_status.configure(text="●  Listening for you", text_color=self.TEAL)
            elif kind == "error":
                self._append_message("Rita · NOTICE", str(payload), system=True)
                self._record_activity(f"Notice: {payload}")

        while True:
            try:
                action_code, event, result = self.confirmations.get_nowait()
            except queue.Empty:
                break
            labels = {
                "sleep": "put this computer to sleep",
                "shutdown": "shut down this computer",
                "restart": "restart this computer",
            }
            if self.root.state() == "withdrawn":
                self.root.deiconify()
            approved = messagebox.askyesno(
                "Confirm system action",
                "Rita is asking permission to "
                f"{labels.get(action_code, 'perform this action')}.\n\nContinue?",
                parent=self.root,
            )
            result["approved"] = bool(approved)
            event.set()
        self.root.after(100, self._drain_queues)

    # -------------------------------- system tray -----------------------------
    def _start_tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
            image = Image.new("RGBA", (64, 64), (15, 21, 32, 255))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((4, 4, 60, 60), radius=17, fill=(167, 139, 250, 255))
            draw.text((23, 18), "R", fill=(23, 19, 39, 255))
            menu = pystray.Menu(
                pystray.MenuItem("Open Rita", lambda _icon, _item: self.root.after(0, self._show_window), default=True),
                pystray.MenuItem("Start listening", lambda _icon, _item: self.root.after(0, self._start_from_tray)),
                pystray.MenuItem("Pause listening", lambda _icon, _item: self.root.after(0, self._pause_from_tray)),
                pystray.MenuItem("Exit", lambda _icon, _item: self.root.after(0, self._exit)),
            )
            self.tray_icon = pystray.Icon("RitaAssistant", image, "Rita | Personal AI", menu)
            threading.Thread(target=self.tray_icon.run, name="Rita-System-Tray", daemon=True).start()
        except Exception as exc:
            self._append_message("Rita", f"System tray is unavailable ({type(exc).__name__}); the window will remain available.", system=True)
            self.tray_icon = None

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _start_from_tray(self) -> None:
        self.assistant.start_listening()
        if hasattr(self, "listen_button"):
            self.listen_button.configure(text="Ⅱ")

    def _pause_from_tray(self) -> None:
        self.assistant.stop_listening()
        if hasattr(self, "listen_button"):
            self.listen_button.configure(text="●")

    def _on_close(self) -> None:
        if self.tray_icon is not None:
            self.root.withdraw()
            if hasattr(self, "status_line"):
                self.status_line.configure(text="Rita is running in the system tray")
        else:
            self._exit()

    def _exit(self) -> None:
        if self._exiting:
            return
        self._exiting = True
        self.assistant.shutdown()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()


def _set_windows_dpi_awareness() -> None:
    """Ask Windows for per-monitor DPI before Tk creates its first window."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def main() -> None:
    if ctk is None:
        raise RuntimeError("CustomTkinter is missing. Run setup.bat to install the Rita desktop dependencies.")
    _set_windows_dpi_awareness()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    # Do not force a 1.0 scale: CustomTkinter automatically follows Windows
    # display scaling after per-monitor DPI awareness has been enabled.
    root = ctk.CTk()
    try:
        root.state("zoomed")
    except Exception:
        pass
    RitaWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
