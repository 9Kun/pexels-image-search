"""User-visible JSON CLI and complete mocked boundary flow."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from support import Response, api_photo, candidate, image_bytes, search_result
from config import SkillError
import pexels_search


class CliTests(unittest.TestCase):
    key = "test-cli-key-never-print"

    def call_cli(self, arguments):
        stream = io.StringIO()
        with redirect_stdout(stream):
            exit_code = pexels_search.main(arguments)
        self.assertNotIn(self.key, stream.getvalue())
        return exit_code, json.loads(stream.getvalue())

    @patch("pexels_api.requests.get")
    def test_default_doctor_checks_configuration_without_api_request(self, get):
        with patch.dict(os.environ, {"PEXELS_API_KEY": self.key}):
            status, result = self.call_cli(["doctor"])
        self.assertEqual(status, 0)
        self.assertTrue(result["key_configured"])
        self.assertFalse(result["live_verified"])
        get.assert_not_called()

    @patch("pexels_api.requests.get")
    def test_live_doctor_uses_real_search_path_with_one_result(self, get):
        get.return_value = Response({"total_results": 1, "photos": [api_photo()]})
        with patch.dict(os.environ, {"PEXELS_API_KEY": self.key}):
            status, result = self.call_cli(["doctor", "--live"])
        self.assertEqual(status, 0)
        self.assertTrue(result["live_verified"])
        self.assertEqual(get.call_args.kwargs["params"]["per_page"], 1)

    def test_missing_key_has_failure_exit_code_and_machine_readable_error(self):
        with patch("pexels_search.load_api_key", side_effect=SkillError("missing PEXELS_API_KEY")):
            status, result = self.call_cli(["doctor"])
        self.assertEqual(status, 1)
        self.assertFalse(result["ok"])
        self.assertFalse(result["key_configured"])
        self.assertIn("PEXELS_API_KEY", result["error"])

    @patch("pexels_api.requests.get")
    def test_search_then_download_returns_usable_json_paths_and_source_record(self, get):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "搜索结果"
            get.side_effect = [
                Response({"total_results": 1, "photos": [api_photo(47)]}),
                Response(content=image_bytes()),
            ]
            with patch.dict(os.environ, {"PEXELS_API_KEY": self.key}):
                status, found = self.call_cli([
                    "search", "ocean coast", "--output", str(output), "--page", "2",
                ])
            self.assertEqual(status, 0)
            candidates = Path(found["candidates"])
            self.assertTrue(candidates.exists())
            self.assertEqual(json.loads(candidates.read_text("utf-8"))["page"], 2)
            self.assertTrue(all(Path(sheet).exists() for sheet in found["contact_sheets"]))
            get.side_effect = None
            original = image_bytes((180, 120), "PNG")
            get.return_value = Response(content=original)
            status, downloaded = self.call_cli([
                "download", "--candidates", str(candidates), "--id", "47",
                "--output", str(output / "原图"), "--selection-method", "visual-reviewed",
            ])
            self.assertEqual(status, 0)
            self.assertEqual(Path(downloaded["files"][0]).read_bytes(), original)
            self.assertTrue(Path(downloaded["sources"]).exists())
            self.assertEqual(downloaded["images"][0]["photo_id"], 47)
            self.assertEqual(downloaded["images"][0]["selection_method"], "visual-reviewed")

    @patch("pexels_api.requests.get")
    def test_tilde_output_links_match_files_inside_temporary_home(self, get):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_home = Path(temporary).resolve()
            candidates_path = temporary_home / "candidates.json"
            candidates_path.write_text(json.dumps(search_result(
                [candidate(81)], version=1, provider="pexels",
            )), encoding="utf-8")
            original = image_bytes((180, 120), "PNG")
            get.return_value = Response(content=original)
            with patch.dict(os.environ, {"USERPROFILE": temporary, "HOME": temporary}):
                # Assert containment before the CLI can write; never use the real home.
                self.assertEqual(Path("~/selected").expanduser().resolve(),
                                 temporary_home / "selected")
                status, downloaded = self.call_cli([
                    "download", "--candidates", str(candidates_path),
                    "--id", "81", "--output", "~/selected",
                ])
            self.assertEqual(status, 0)
            expected_image = temporary_home / "selected" / "pexels_81.png"
            expected_manifest = temporary_home / "selected" / "image_sources.json"
            self.assertEqual(downloaded["files"], [str(expected_image)])
            self.assertEqual(downloaded["sources"], str(expected_manifest))
            self.assertEqual(expected_image.read_bytes(), original)
            self.assertEqual(json.loads(expected_manifest.read_text("utf-8"))["images"][0]["photo_id"], 81)


if __name__ == "__main__":
    unittest.main()
