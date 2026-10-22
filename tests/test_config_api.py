"""Configuration isolation and real Pexels pagination semantics."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import Response, api_photo, requests
from config import SkillError, load_api_key
from pexels_api import search_photos


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "中文技能目录"
        self.root.mkdir()
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_missing_key_is_actionable_error(self):
        with self.assertRaises(SkillError) as caught:
            load_api_key(skill_dir=self.root)
        self.assertIn("PEXELS_API_KEY", str(caught.exception))

    def test_process_key_wins_without_opening_explicit_file(self):
        os.environ["PEXELS_API_KEY"] = "process-only-test-key"
        self.assertEqual(load_api_key(self.root / "absent.env", self.root),
                         "process-only-test-key")

    def test_explicit_file_wins_over_skill_file(self):
        (self.root / ".env").write_text("PEXELS_API_KEY=local-test-key\n", "utf-8")
        explicit = self.root / "指定配置.env"
        explicit.write_text('# comment\nPEXELS_API_KEY="explicit-test-key"\n', "utf-8")
        self.assertEqual(load_api_key(explicit, self.root), "explicit-test-key")

    def test_skill_file_is_default(self):
        (self.root / ".env").write_text("PEXELS_API_KEY=local-test-key\n", "utf-8")
        self.assertEqual(load_api_key(skill_dir=self.root), "local-test-key")

    def test_explicit_invalid_configuration_does_not_fall_back(self):
        (self.root / ".env").write_text("PEXELS_API_KEY=local-test-key\n", "utf-8")
        empty = self.root / "empty.env"
        empty.write_text("UNRELATED=value\n", "utf-8")
        for env_file in (empty, self.root / "missing.env"):
            with self.subTest(env_file=env_file.name), self.assertRaises(SkillError):
                load_api_key(env_file, self.root)


class PexelsApiTests(unittest.TestCase):
    key = "test-key-must-never-appear-in-errors"

    @patch("pexels_api.requests.get")
    def test_query_page_and_count_are_forwarded_and_order_is_preserved(self, get):
        get.return_value = Response({
            "page": 3, "per_page": 20, "total_results": 100,
            "next_page": "https://api.pexels.com/v1/search?page=4",
            "photos": [api_photo(90), api_photo(2)],
        })
        result = search_photos("offshore wind farm", self.key, page=3, per_page=20)
        arguments = get.call_args.kwargs
        self.assertEqual(arguments["params"]["query"], "offshore wind farm")
        self.assertEqual(arguments["params"]["page"], 3)
        self.assertEqual(arguments["params"]["per_page"], 20)
        self.assertEqual(arguments["headers"]["Authorization"], self.key)
        self.assertEqual(result["page"], 3)
        self.assertTrue(result["has_next_page"])
        self.assertEqual([photo["id"] for photo in result["photos"]], [90, 2])
        self.assertEqual(result["photos"][0]["original_url"],
                         api_photo(90)["src"]["original"])
        get.assert_called_once()

    @patch("pexels_api.requests.get")
    def test_dimensions_and_orientation_are_enforced_locally(self, get):
        get.return_value = Response({"total_results": 4, "photos": [
            api_photo(1, 2400, 1600), api_photo(2, 800, 500),
            api_photo(3, 1800, 2600), api_photo(4, 1800, 1000),
        ]})
        result = search_photos("coast", self.key, orientation="landscape",
                               min_width=1600, min_height=1200)
        self.assertEqual([photo["id"] for photo in result["photos"]], [1])
        self.assertEqual(result["total_results"], 4)

    @patch("pexels_api.requests.get")
    def test_empty_results_remain_an_honest_empty_search(self, get):
        get.return_value = Response({"total_results": 0, "photos": []})
        result = search_photos("exact unusual phrase", self.key)
        self.assertEqual(result["photos"], [])
        self.assertFalse(result["has_next_page"])
        self.assertEqual(result["query"], "exact unusual phrase")
        get.assert_called_once()

    def test_auth_rate_limit_and_server_failures_hide_key(self):
        for status in (401, 429, 503):
            with self.subTest(status=status), patch("pexels_api.requests.get") as get:
                get.return_value = Response(status=status)
                with self.assertRaises(SkillError) as caught:
                    search_photos("coast", self.key)
                self.assertNotIn(self.key, str(caught.exception))

    @patch("pexels_api.requests.get")
    def test_timeout_does_not_echo_underlying_sensitive_exception(self, get):
        get.side_effect = requests.Timeout("diagnostic contains " + self.key)
        with self.assertRaises(SkillError) as caught:
            search_photos("coast", self.key)
        self.assertNotIn(self.key, str(caught.exception))

    @patch("pexels_api.requests.get")
    def test_invalid_pagination_is_rejected_before_network(self, get):
        for page, per_page in ((0, 20), (1, 0), (1, 81)):
            with self.subTest(page=page, per_page=per_page), self.assertRaises(SkillError):
                search_photos("coast", self.key, page=page, per_page=per_page)
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
