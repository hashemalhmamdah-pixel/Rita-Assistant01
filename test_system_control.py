import unittest
from unittest.mock import patch

from system_control import SystemController


class SystemControlTests(unittest.TestCase):
    def setUp(self):
        self.controller = SystemController()

    def test_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            self.controller.execute_action("run_shell", "calc.exe")

    def test_application_lookup_rejects_arbitrary_executable_paths(self):
        for target in (r"C:\Windows\System32\cmd.exe", "/tmp/unknown.exe", "C:\\Windows"):
            with self.subTest(target=target):
                self.assertIsNone(self.controller._find_application(target))

    def test_power_action_requires_confirmation(self):
        self.controller.is_windows = True
        with self.assertRaises(PermissionError):
            self.controller.execute_action("shutdown")

    def test_volume_and_brightness_values_are_bounded(self):
        self.assertEqual(self.controller._bounded_number("55%", "volume"), 55)
        for value in ("-1", "101", "90; shutdown", "abc"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.controller._bounded_number(value, "volume")

    @patch("system_control.webbrowser.open_new_tab", return_value=True)
    def test_only_http_or_https_url_is_opened(self, open_url):
        result = self.controller._open_url("https://example.com/path")
        self.assertEqual(result, "Opened example.com.")
        open_url.assert_called_once_with("https://example.com/path")

    def test_plain_domain_is_upgraded_to_https(self):
        with patch("system_control.webbrowser.open_new_tab", return_value=True) as open_url:
            result = self.controller._open_url("example.com")
        self.assertEqual(result, "Opened example.com.")
        open_url.assert_called_once_with("https://example.com")

    def test_embedded_url_credentials_are_rejected(self):
        with self.assertRaises(ValueError):
            self.controller._open_url("https://user:password@example.com")

    def test_non_web_scheme_is_rejected(self):
        for value in ("javascript:alert(1)", "file:///C:/Windows/win.ini", "data:text/plain,hello"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.controller._open_url(value)

    def test_windows_settings_uri_uses_allowlisted_page(self):
        self.controller.is_windows = True
        with patch("system_control.os.startfile", create=True) as startfile:
            result = self.controller.execute_action("open_settings", "bluetooth")
        self.assertIn("bluetooth", result)
        startfile.assert_called_once_with("ms-settings:bluetooth")

    def test_windows_settings_rejects_unlisted_page(self):
        self.controller.is_windows = True
        with self.assertRaises(ValueError):
            self.controller.execute_action("open_settings", "powershell")

    def test_system_info_is_read_only_and_returns_basic_metrics(self):
        self.controller.is_windows = False
        result = self.controller.execute_action("system_info")
        self.assertIn("Operating system:", result)
        self.assertIn("free space", result)

    def test_numeric_target_must_be_present(self):
        with self.assertRaises(ValueError):
            self.controller._bounded_number(None, "brightness")


if __name__ == "__main__":
    unittest.main()
