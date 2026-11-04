import unittest
from local_commands import route_local_command


class LocalCommandTests(unittest.TestCase):
    def test_windows_settings_shortcuts(self):
        cases = {
            "open settings": ("open_settings", "root"),
            "open the settings": ("open_settings", "root"),
            "please open settings": ("open_settings", "root"),
            "show me settings": ("open_settings", "root"),
            "open Bluetooth settings": ("open_settings", "bluetooth"),
            "open sound settings": ("open_settings", "sound"),
            "open Wi-Fi settings": ("open_settings", "network-wifi"),
            "open Windows Update settings": ("open_settings", "windowsupdate"),
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                result = route_local_command(command)
                self.assertIsNotNone(result)
                self.assertEqual(result[1:], expected)

    def test_folder_and_app_commands(self):
        self.assertEqual(route_local_command("open Downloads")[1:], ("open_folder", "downloads"))
        self.assertEqual(route_local_command("open This PC")[1:], ("open_folder", "this_pc"))
        self.assertEqual(route_local_command("open Calculator")[1:], ("open_app", "Calculator"))

    def test_open_website_is_routed_to_browser_not_app_lookup(self):
        self.assertEqual(route_local_command("open https://example.com")[1:], ("open_url", "https://example.com"))
        self.assertEqual(route_local_command("open example.com")[1:], ("open_url", "example.com"))

    def test_volume_and_brightness_commands(self):
        self.assertEqual(route_local_command("volume up")[1:], ("volume_up", None))
        self.assertEqual(route_local_command("set volume to 45%")[1:], ("volume_set", "45"))
        self.assertEqual(route_local_command("set brightness to 101")[1], "__local_error__")

    def test_arabic_settings_shortcuts(self):
        self.assertEqual(route_local_command("افتح إعدادات البلوتوث")[1:], ("open_settings", "bluetooth"))
        self.assertEqual(route_local_command("افتح الاعدادات")[1:], ("open_settings", "root"))

    def test_arabic_apps_and_folders(self):
        self.assertEqual(route_local_command("افتح الحاسبة")[1:], ("open_app", "Calculator"))
        self.assertEqual(route_local_command("افتح التنزيلات")[1:], ("open_folder", "downloads"))

    def test_arabic_volume_aliases(self):
        self.assertEqual(route_local_command("ارفع الصوت")[1], "volume_up")
        self.assertEqual(route_local_command("اكتم الصوت")[1], "volume_mute")

    def test_unknown_or_ambiguous_text_is_not_executed(self):
        self.assertIsNone(route_local_command("run this PowerShell script"))
        self.assertIsNone(route_local_command("delete all files"))


if __name__ == "__main__":
    unittest.main()
