"""Deterministic, offline-first command routing for common Windows tasks."""
from __future__ import annotations

import re
from typing import Optional


def route_local_command(command: str) -> Optional[tuple[str, str, str | None]]:
    """Return (acknowledgement, action, target) for a recognized local command.

    This router deliberately handles a small, explicit command vocabulary. It never
    interprets arbitrary text as a shell command.
    """
    raw = (command or "").strip()
    value = re.sub(r"\s+", " ", raw.casefold()).strip(" .!?؟،")
    if not value:
        return None

    settings = {
        "settings": "root",
        "setting": "root",
        "the settings": "root",
        "windows settings": "root",
        "system settings": "root",
        "windows system settings": "root",
        "control panel": "root",
        "الاعدادات": "root",
        "الإعدادات": "root",
        "اعدادات البلوتوث": "bluetooth",
        "إعدادات البلوتوث": "bluetooth",
        "اعدادات الصوت": "sound",
        "إعدادات الصوت": "sound",
        "اعدادات الشاشة": "display",
        "إعدادات الشاشة": "display",
        "اعدادات الشبكة": "network",
        "إعدادات الشبكة": "network",
        "اعدادات الخصوصية": "privacy",
        "إعدادات الخصوصية": "privacy",
        "bluetooth settings": "bluetooth",
        "open bluetooth": "bluetooth",
        "البلوتوث": "bluetooth",
        "sound settings": "sound",
        "audio settings": "sound",
        "display settings": "display",
        "screen settings": "display",
        "wifi settings": "network-wifi",
        "wi-fi settings": "network-wifi",
        "network settings": "network",
        "internet settings": "network",
        "apps settings": "appsfeatures",
        "installed apps settings": "appsfeatures",
        "personalization settings": "personalization",
        "wallpaper settings": "personalization-background",
        "background settings": "personalization-background",
        "windows update settings": "windowsupdate",
        "update settings": "windowsupdate",
        "privacy settings": "privacy",
        "accessibility settings": "easeofaccess",
        "time settings": "dateandtime",
        "date settings": "dateandtime",
        "storage settings": "storagesense",
        "power settings": "powersleep",
        "battery settings": "batterysaver",
    }
    open_prefixes = (
        "please open ", "show me ", "open ", "show ", "go to ", "launch ",
        "take me to ", "افتح ", "افتحي ", "اعرض ", "روح على ", "اذهب الى ",
        "افتحلي ", "وديني على ",
    )
    for prefix in open_prefixes:
        if value.startswith(prefix):
            target_original = raw[len(prefix):].strip()
            target = value[len(prefix):].strip()
            target = target.removesuffix(" page").removesuffix(" screen")
            target = target.strip()
            if target not in settings and target.endswith(" settings"):
                target = target.removesuffix(" settings").strip()
            # Match full setting names and short forms such as "bluetooth".
            setting_target = settings.get(target)
            if setting_target is None and target in {
                "bluetooth", "sound", "audio", "display", "wifi", "wi-fi",
                "network", "apps", "privacy", "personalization", "updates",
                "windows update", "the settings", "settings", "setting",
            }:
                setting_target = {
                    "bluetooth": "bluetooth", "sound": "sound", "audio": "sound",
                    "display": "display", "wifi": "network-wifi", "wi-fi": "network-wifi",
                    "network": "network", "apps": "appsfeatures", "privacy": "privacy",
                    "personalization": "personalization", "updates": "windowsupdate",
                    "windows update": "windowsupdate", "the settings": "root",
                    "settings": "root", "setting": "root",
                }[target]
            if setting_target is not None:
                if setting_target == "root":
                    return ("Opening Windows Settings.", "open_settings", "root")
                return (f"Opening Windows {target} settings.", "open_settings", setting_target)
            folders = {
                "downloads": "downloads", "download folder": "downloads",
                "documents": "documents", "documents folder": "documents",
                "desktop": "desktop", "pictures": "pictures", "music": "music",
                "videos": "videos", "this pc": "this_pc", "my computer": "this_pc",
                "التنزيلات": "downloads", "التنزيلات folder": "downloads",
                "المستندات": "documents", "سطح المكتب": "desktop",
                "الصور": "pictures", "الفيديوهات": "videos",
            }
            if target in folders:
                return (f"Opening {target}.", "open_folder", folders[target])
            if re.fullmatch(r"https?://[^\s]+", target, re.IGNORECASE) or re.fullmatch(
                r"[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?", target, re.IGNORECASE
            ):
                return (f"Opening {target} in your browser.", "open_url", target)
            if target in {"settings", "setting", "the settings", "windows settings"}:
                return ("Opening Windows Settings.", "open_settings", "root")
            app_aliases = {
                "الحاسبة": "Calculator", "الآلة الحاسبة": "Calculator",
                "المفكرة": "Notepad", "مدير المهام": "Task Manager",
                "مستكشف الملفات": "File Explorer", "المتصفح": "Microsoft Edge",
            }
            if target in app_aliases:
                app_name = app_aliases[target]
                return (f"Opening {app_name}.", "open_app", app_name)
            if target in {"system status", "system information", "pc status", "computer status", "معلومات الجهاز", "حالة الجهاز"}:
                return ("Here is your computer status.", "system_info", None)
            if target in {"installed apps", "all apps", "applications"}:
                return ("Here are the applications available from your Start Menu.", "list_apps", None)
            if target:
                return (f"Opening {target_original}.", "open_app", target_original)

    # Explicit local actions. Keep aliases intentionally unambiguous.
    exact_actions = {
        "volume up": ("Increasing the volume.", "volume_up", None),
        "increase volume": ("Increasing the volume.", "volume_up", None),
        "raise volume": ("Increasing the volume.", "volume_up", None),
        "ارفع الصوت": ("برفع مستوى الصوت.", "volume_up", None),
        "علي الصوت": ("برفع مستوى الصوت.", "volume_up", None),
        "volume down": ("Decreasing the volume.", "volume_down", None),
        "decrease volume": ("Decreasing the volume.", "volume_down", None),
        "lower volume": ("Decreasing the volume.", "volume_down", None),
        "وطي الصوت": ("بخفض مستوى الصوت.", "volume_down", None),
        "اخفض الصوت": ("بخفض مستوى الصوت.", "volume_down", None),
        "mute": ("Muting system audio.", "volume_mute", None),
        "mute volume": ("Muting system audio.", "volume_mute", None),
        "اكتم الصوت": ("تم كتم الصوت.", "volume_mute", None),
        "unmute": ("Unmuting system audio.", "volume_unmute", None),
        "الغاء كتم الصوت": ("تم إلغاء كتم الصوت.", "volume_unmute", None),
        "settings": ("Opening Windows Settings.", "open_settings", "root"),
        "open settings": ("Opening Windows Settings.", "open_settings", "root"),
        "open the settings": ("Opening Windows Settings.", "open_settings", "root"),
        "show settings": ("Opening Windows Settings.", "open_settings", "root"),
        "show windows settings": ("Opening Windows Settings.", "open_settings", "root"),
        "system status": ("Here is your computer status.", "system_info", None),
        "system information": ("Here is your computer status.", "system_info", None),
        "pc status": ("Here is your computer status.", "system_info", None),
        "computer status": ("Here is your computer status.", "system_info", None),
        "معلومات الجهاز": ("هاي معلومات جهازك.", "system_info", None),
        "حالة الجهاز": ("هاي حالة جهازك.", "system_info", None),
        "list apps": ("Here are the applications available from your Start Menu.", "list_apps", None),
        "show installed apps": ("Here are the applications available from your Start Menu.", "list_apps", None),
        "التطبيقات المثبتة": ("هاي التطبيقات الموجودة بقائمة ابدأ.", "list_apps", None),
    }
    if value in exact_actions:
        return exact_actions[value]

    patterns = (
        (r"^(?:set |change )?volume to (\d{1,3})%?$", "volume_set", "volume"),
        (r"^(?:set |change )?(?:brightness|screen brightness) to (\d{1,3})%?$", "brightness_set", "brightness"),
        (r"^(?:set )?الصوت على (\d{1,3})%?$", "volume_set", "volume"),
        (r"^(?:set )?السطوع على (\d{1,3})%?$", "brightness_set", "brightness"),
    )
    for pattern, action, label in patterns:
        match = re.fullmatch(pattern, value)
        if match:
            number = int(match.group(1))
            if number > 100:
                return (f"{label.capitalize()} must be between 0 and 100 percent.", "__local_error__", None)
            return (f"Setting {label} to {number} percent.", action, str(number))

    if value in {"lock pc", "lock computer", "lock screen", "قفل الكمبيوتر", "اقفل الشاشة"}:
        return ("Locking your Windows session.", "lock", None)
    if value in {"sleep", "put computer to sleep", "put the computer to sleep", "نام الكمبيوتر"}:
        return ("I need your confirmation before putting the computer to sleep.", "sleep", None)
    if value in {"shutdown", "shut down", "shut down computer", "اطفئ الكمبيوتر", "طفي الكمبيوتر"}:
        return ("I need your confirmation before shutting down the computer.", "shutdown", None)
    if value in {"restart", "restart computer", "اعادة تشغيل الكمبيوتر", "أعد تشغيل الكمبيوتر"}:
        return ("I need your confirmation before restarting the computer.", "restart", None)
    return None
