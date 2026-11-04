"""Allow-listed Windows system actions. Never executes model-provided shell text."""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ALLOWED_ACTIONS = {
    "open_app", "open_url", "volume_up", "volume_down", "volume_mute",
    "volume_unmute", "volume_set", "brightness_up", "brightness_down",
    "brightness_set", "open_settings", "open_folder", "system_info", "list_apps",
    "lock", "sleep", "shutdown", "restart",
}
CONFIRMATION_ACTIONS = {"sleep", "shutdown", "restart"}


class SystemController:
    """Execute only explicitly supported actions on Windows 10/11."""

    def __init__(self) -> None:
        self.is_windows = os.name == "nt"

    def execute_action(
        self,
        action_code: str,
        action_target: str | None = None,
        *,
        confirmed: bool = False,
    ) -> str:
        if action_code not in ALLOWED_ACTIONS:
            raise ValueError("That system action is not supported.")
        if action_code in CONFIRMATION_ACTIONS and not confirmed:
            raise PermissionError("This action requires explicit user confirmation.")
        if action_code == "system_info":
            return self._system_info()
        if not self.is_windows:
            raise OSError("Rita's system controls are available on Windows 10/11 only.")

        handlers = {
            "open_app": self._open_app,
            "open_url": self._open_url,
            "volume_up": lambda _: self._volume_step(1),
            "volume_down": lambda _: self._volume_step(-1),
            "volume_mute": lambda _: self._set_mute(True),
            "volume_unmute": lambda _: self._set_mute(False),
            "volume_set": self._set_volume,
            "brightness_up": lambda _: self._brightness_step(10),
            "brightness_down": lambda _: self._brightness_step(-10),
            "brightness_set": self._set_brightness,
            "open_settings": self._open_settings,
            "open_folder": self._open_folder,
            "system_info": lambda _: self._system_info(),
            "list_apps": lambda _: self._list_apps(),
            "lock": lambda _: self._lock(),
            "sleep": lambda _: self._sleep(),
            "shutdown": lambda _: self._power_action("/s"),
            "restart": lambda _: self._power_action("/r"),
        }
        return handlers[action_code](action_target)

    def _open_url(self, target: str | None) -> str:
        if not target or len(target) > 2048:
            raise ValueError("Please provide a valid website address.")
        candidate = target.strip()
        explicit_scheme = re.match(r"^([a-z][a-z0-9+.-]*):", candidate, re.IGNORECASE)
        if explicit_scheme and explicit_scheme.group(1).casefold() not in {"http", "https"}:
            raise ValueError("Only valid HTTP or HTTPS websites can be opened.")
        if not re.match(r"^https?://", candidate, re.IGNORECASE):
            candidate = "https://" + candidate
        parsed = urlparse(candidate)
        try:
            hostname = parsed.hostname
            _ = parsed.port  # Force urllib to validate the supplied port number.
        except ValueError as exc:
            raise ValueError("That website address is invalid.") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname:
            raise ValueError("Only valid HTTP or HTTPS websites can be opened.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Website addresses containing embedded credentials are not allowed.")
        if any(ch.isspace() for ch in parsed.netloc):
            raise ValueError("That website address is invalid.")
        if not webbrowser.open_new_tab(candidate):
            raise RuntimeError("Windows could not open the default web browser.")
        return f"Opened {parsed.netloc}."

    def _open_app(self, target: str | None) -> str:
        if not target:
            raise ValueError("Tell me the name of the app to open.")
        name = target.strip().strip('"\'')
        if not name or len(name) > 128 or any(ord(ch) < 32 for ch in name):
            raise ValueError("That application name is invalid.")
        resolved = self._find_application(name)
        if resolved is None:
            raise FileNotFoundError(f"I couldn't find an installed app named {name}.")
        if resolved.suffix.casefold() == ".lnk":
            os.startfile(str(resolved))  # Windows shell resolves the shortcut target.
        else:
            subprocess.Popen([str(resolved)], shell=False, close_fds=True)
        return f"Opened {name}."

    def _find_application(self, name: str) -> Path | None:
        # Resolve installed app names only. Never let model output turn into an
        # arbitrary executable path (or a command line) on the local machine.
        if (
            Path(name).is_absolute()
            or any(separator in name for separator in ("/", "\\", ":"))
        ):
            return None
        requested = name.casefold().strip()
        aliases = {
            "chrome": "chrome.exe", "google chrome": "chrome.exe",
            "edge": "msedge.exe", "microsoft edge": "msedge.exe",
            "firefox": "firefox.exe", "notepad": "notepad.exe",
            "calculator": "calc.exe", "calc": "calc.exe",
            "file explorer": "explorer.exe", "explorer": "explorer.exe",
            "paint": "mspaint.exe", "task manager": "taskmgr.exe",
        }
        default_executable = (
            name if name.lower().endswith(".exe") else f"{name}.exe"
        )
        executable_name = aliases.get(requested, default_executable)

        on_path = shutil.which(executable_name) or shutil.which(name)
        if on_path:
            return Path(on_path)

        for shortcut in self._start_menu_shortcuts():
            stem = shortcut.stem.casefold()
            if stem == requested or stem == Path(requested).stem:
                return shortcut

        registered = self._find_app_path(executable_name)
        if registered:
            return registered

        # A limited substring match is useful for display names such as "Visual Studio Code".
        candidates = list(self._start_menu_shortcuts())
        matches = [p for p in candidates if requested in p.stem.casefold()]
        if len(matches) == 1:
            return matches[0]
        return None

    @staticmethod
    def _start_menu_shortcuts() -> list[Path]:
        roots = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        shortcuts: list[Path] = []
        for root in roots:
            if root.is_dir():
                try:
                    shortcuts.extend(p for p in root.rglob("*.lnk") if p.is_file())
                except OSError:
                    continue
        return shortcuts

    @staticmethod
    def _find_app_path(executable_name: str) -> Path | None:
        try:
            import winreg
        except ImportError:
            return None

        locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
            ),
        )
        for hive, base_key in locations:
            try:
                with winreg.OpenKey(hive, base_key) as key:
                    index = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, index)
                            index += 1
                        except OSError:
                            break
                        if subkey_name.casefold() != executable_name.casefold():
                            continue
                        try:
                            with winreg.OpenKey(key, subkey_name) as app_key:
                                value, _ = winreg.QueryValueEx(app_key, None)
                            expanded = os.path.expandvars(str(value))
                            quoted = re.match(r'\s*"([^"]+)"', expanded)
                            executable = quoted.group(1) if quoted else expanded.split()[0]
                            path = Path(executable)
                            if path.is_file():
                                return path
                        except OSError:
                            continue
            except OSError:
                continue
        return None

    _SETTINGS_PAGES = {
        "root": "ms-settings:",
        "bluetooth": "ms-settings:bluetooth",
        "sound": "ms-settings:sound",
        "display": "ms-settings:display",
        "network": "ms-settings:network-status",
        "network-wifi": "ms-settings:network-wifi",
        "appsfeatures": "ms-settings:appsfeatures",
        "personalization": "ms-settings:personalization",
        "personalization-background": "ms-settings:personalization-background",
        "windowsupdate": "ms-settings:windowsupdate",
        "privacy": "ms-settings:privacy",
        "easeofaccess": "ms-settings:easeofaccess",
        "dateandtime": "ms-settings:dateandtime",
        "storagesense": "ms-settings:storagesense",
        "powersleep": "ms-settings:powersleep",
        "batterysaver": "ms-settings:batterysaver",
    }

    _KNOWN_FOLDERS = {
        "downloads": "Downloads", "documents": "Documents", "desktop": "Desktop",
        "pictures": "Pictures", "music": "Music", "videos": "Videos",
    }

    def _open_settings(self, target: str | None) -> str:
        page = (target or "root").strip().casefold()
        uri = self._SETTINGS_PAGES.get(page)
        if uri is None:
            raise ValueError("That Windows Settings page is not supported.")
        try:
            # ShellExecute is the native path for ms-settings URIs. A fixed
            # Explorer fallback covers machines where the protocol handler is slow.
            os.startfile(uri)  # type: ignore[attr-defined]
        except Exception:
            try:
                subprocess.Popen(["explorer.exe", uri], shell=False, close_fds=True)
            except Exception as fallback_error:
                raise RuntimeError(
                    "Windows could not launch Settings. Check that the Windows Settings app is available."
                ) from fallback_error
        return f"Opened Windows Settings: {page.replace('-', ' ')}."

    def _open_folder(self, target: str | None) -> str:
        folder = (target or "").strip().casefold()
        if folder == "this_pc":
            subprocess.Popen(["explorer.exe", "shell:MyComputerFolder"], shell=False)
            return "Opened This PC."
        known = self._KNOWN_FOLDERS.get(folder)
        if known is None:
            raise ValueError("That folder shortcut is not supported.")
        path = Path.home() / known
        if not path.is_dir():
            raise FileNotFoundError(f"The {known} folder was not found.")
        os.startfile(str(path))  # type: ignore[attr-defined]
        return f"Opened {known}."

    def _system_info(self) -> str:
        import platform
        import shutil

        home = Path.home()
        disk = shutil.disk_usage(home)
        total_ram = available_ram = None
        if self.is_windows:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            memory = MEMORYSTATUSEX()
            memory.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                total_ram = memory.ullTotalPhys
                available_ram = memory.ullAvailPhys
        gib = 1024 ** 3
        parts = [
            f"Operating system: {platform.system()} {platform.release()}",
            f"Processor threads: {os.cpu_count() or 'unknown'}",
            f"Home drive free space: {disk.free / gib:.1f} GB of {disk.total / gib:.1f} GB",
        ]
        if total_ram is not None and available_ram is not None:
            parts.append(f"Memory: {(total_ram - available_ram) / gib:.1f} GB used of {total_ram / gib:.1f} GB")
        return "\n".join(parts)

    def _list_apps(self) -> str:
        shortcuts = sorted({p.stem for p in self._start_menu_shortcuts()}, key=str.casefold)
        if not shortcuts:
            return "I couldn't find any Start Menu application shortcuts."
        shown = shortcuts[:30]
        suffix = f"\n…and {len(shortcuts) - len(shown)} more." if len(shortcuts) > len(shown) else ""
        return "Installed Start Menu apps (first 30):\n" + "\n".join(f"• {name}" for name in shown) + suffix

    @staticmethod
    def _lock() -> str:
        result = ctypes.windll.user32.LockWorkStation()
        if not result:
            raise OSError("Windows did not accept the lock request.")
        return "Windows session locked."

    def _get_endpoint_volume(self) -> Any:
        try:
            from pycaw.pycaw import AudioUtilities

            device = AudioUtilities.GetSpeakers()
            return device.EndpointVolume
        except Exception as exc:
            raise RuntimeError(
                "Windows audio control is unavailable. Check the default audio "
                "device and pycaw installation."
            ) from exc

    def _volume_step(self, direction: int) -> str:
        try:
            endpoint = self._get_endpoint_volume()
            current = float(endpoint.GetMasterVolumeLevelScalar())
            updated = max(0.0, min(1.0, current + direction * 0.05))
            endpoint.SetMasterVolumeLevelScalar(updated, None)
        except Exception:
            try:
                # Native multimedia-key fallback; no command shell is involved.
                vk = 0xAF if direction > 0 else 0xAE
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
            except Exception as fallback_error:
                raise RuntimeError("Windows volume control is unavailable. Check the default audio device and pycaw installation.") from fallback_error
        return "Volume increased." if direction > 0 else "Volume decreased."

    def _set_mute(self, muted: bool) -> str:
        endpoint = self._get_endpoint_volume()
        endpoint.SetMute(1 if muted else 0, None)
        return "System audio muted." if muted else "System audio unmuted."

    def _set_volume(self, target: str | None) -> str:
        value = self._bounded_number(target, "volume")
        endpoint = self._get_endpoint_volume()
        endpoint.SetMasterVolumeLevelScalar(value / 100.0, None)
        return f"Volume set to {value}%."

    def _brightness_step(self, delta: int) -> str:
        try:
            import screen_brightness_control as sbc

            current = sbc.get_brightness(display=0)
            if isinstance(current, list):
                current = current[0]
            updated = max(0, min(100, int(current) + delta))
            sbc.set_brightness(updated, display=0)
            return f"Screen brightness set to {updated}%."
        except Exception as exc:
            raise RuntimeError("I couldn't change this display's brightness.") from exc

    def _set_brightness(self, target: str | None) -> str:
        value = self._bounded_number(target, "brightness")
        try:
            import screen_brightness_control as sbc

            sbc.set_brightness(value, display=0)
        except Exception as exc:
            raise RuntimeError("I couldn't change this display's brightness.") from exc
        return f"Screen brightness set to {value}%."

    @staticmethod
    def _bounded_number(target: str | None, label: str) -> int:
        if target is None or not re.fullmatch(r"\s*\d{1,3}\s*%?\s*", str(target)):
            raise ValueError(f"Please provide a number from 0 to 100 for {label}.")
        value = int(re.sub(r"\D", "", str(target)))
        if not 0 <= value <= 100:
            raise ValueError(f"{label.capitalize()} must be between 0 and 100.")
        return value

    @staticmethod
    def _sleep() -> str:
        # SetSuspendState(FALSE, TRUE, FALSE): suspend, force critical, disable wake events.
        result = ctypes.windll.powrprof.SetSuspendState(False, False, False)
        if result == 0:
            raise OSError("Windows did not accept the sleep request.")
        return "The computer is going to sleep."

    @staticmethod
    def _power_action(flag: str) -> str:
        subprocess.run(["shutdown", flag, "/t", "0"], check=True, shell=False)
        return "Shutdown started." if flag == "/s" else "Restart started."
