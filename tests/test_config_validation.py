"""Validate keys identically at every configuration entry point."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import support  # Establish the skill's script and dependency import paths.
from config import SkillError, load_api_key
from pexels_api import search_photos


class KeyValidationTests(unittest.TestCase):
    def test_process_placeholders_fail_without_reading_another_key_file(self):
        for value in ("YOUR_API_KEY", "replace_me", "<actual-key>", "your-api-key"):
            with self.subTest(value=value), patch.dict(os.environ, {"PEXELS_API_KEY": value}, clear=True), \
                    patch.object(Path, "open") as read:
                with self.assertRaises(SkillError) as caught:
                    load_api_key("never-read.env")
                self.assertNotIn(value, str(caught.exception))
                read.assert_not_called()

    def test_control_characters_fail_for_process_and_file_configuration(self):
        for control in ("\t", "\r", "\v", "\x00", "\x7f"):
            value = "synthetic" + control + "secret"
            with self.subTest(control=repr(control)), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "test.env"
                path.write_bytes(("PEXELS_API_KEY=" + value + "\n").encode("utf-8"))
                with patch.dict(os.environ, {}, clear=True), self.assertRaises(SkillError):
                    load_api_key(path)
                with patch("config.os.environ", {"PEXELS_API_KEY": value}), \
                        self.assertRaises(SkillError):
                    load_api_key(path)

    def test_direct_api_calls_validate_key_before_network(self):
        with patch("pexels_api.requests.get") as get:
            for value in ("YOUR_API_KEY", "secret\nInjected: x", "secret\t", "secret value"):
                with self.subTest(value=value), self.assertRaises(SkillError):
                    search_photos("nature", value)
            get.assert_not_called()

    def test_windows_line_endings_quoted_key_and_bom_still_work(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            path = Path(temporary) / "test.env"
            path.write_bytes('\ufeff# comment\r\nPEXELS_API_KEY="synthetic-key" # comment\r\n'.encode("utf-8"))
            self.assertEqual(load_api_key(path), "synthetic-key")


if __name__ == "__main__":
    unittest.main()
