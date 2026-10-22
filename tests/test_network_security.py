"""Exercise Requests' real preparation without network or private credentials."""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import Image, Response, api_photo, candidate, image_bytes
from config import SkillError
from image_io import download_image, inspect_image
from pexels_api import search_photos


class NetworkIsolationTests(unittest.TestCase):
    def test_explicit_key_survives_netrc_and_environment_transport_is_preserved(self):
        reply = Response({"photos": [api_photo()], "total_results": 1})
        environment = {"HTTPS_PROXY": "http://proxy.invalid:8080",
                       "REQUESTS_CA_BUNDLE": "synthetic-ca.pem"}
        with patch.dict(os.environ, environment, clear=True), \
                patch("requests.sessions.get_netrc_auth", return_value=("test", "test")) as netrc, \
                patch("requests.sessions.Session.send", return_value=reply) as send:
            search_photos("nature", "synthetic-pexels-key")
        prepared = send.call_args.args[0]
        self.assertEqual(prepared.headers["Authorization"], "synthetic-pexels-key")
        self.assertEqual(send.call_args.kwargs["proxies"]["https"], environment["HTTPS_PROXY"])
        self.assertEqual(send.call_args.kwargs["verify"], "synthetic-ca.pem")
        self.assertFalse(send.call_args.kwargs["allow_redirects"])
        netrc.assert_not_called()

    def test_cdn_does_not_receive_ambient_netrc_credentials(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch("requests.sessions.get_netrc_auth", return_value=("test", "test")) as netrc, \
                patch("requests.sessions.Session.send", return_value=Response(content=image_bytes())) as send:
            download_image(candidate()["original_url"], Path(temporary) / "photo.jpg")
        self.assertNotIn("Authorization", send.call_args.args[0].headers)
        self.assertFalse(send.call_args.kwargs["allow_redirects"])
        netrc.assert_not_called()

    def test_redirects_are_rejected_without_a_followup_request(self):
        reply = Response(status=302)
        reply.headers["Location"] = "https://example.invalid/private"
        with patch("requests.sessions.Session.send", return_value=reply) as send:
            with self.assertRaises(SkillError):
                search_photos("nature", "synthetic-pexels-key")
            send.assert_called_once()
        with tempfile.TemporaryDirectory() as temporary, \
                patch("requests.sessions.Session.send", return_value=reply) as send:
            with self.assertRaises(SkillError):
                download_image(candidate()["original_url"], Path(temporary) / "photo.jpg")
            send.assert_called_once()
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_invalid_cdn_urls_are_rejected_before_network(self):
        urls = ["http://images.pexels.com/photo.jpg", "https://localhost/photo.jpg",
                "https://images.pexels.com.evil.invalid/photo.jpg",
                "https://user:pass@images.pexels.com/photo.jpg",
                "https://images.pexels.com:444/photo.jpg"]
        with tempfile.TemporaryDirectory() as temporary, patch("image_io.requests.get") as get:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(SkillError):
                    download_image(url, Path(temporary) / "photo.jpg")
            get.assert_not_called()


class ApiMetadataTests(unittest.TestCase):
    def test_aspect_preserving_medium_preview_and_quota_headers_are_recorded(self):
        reply = Response({"photos": [api_photo()], "total_results": 1})
        reply.headers.update({"X-Ratelimit-Limit": "200", "x-ratelimit-remaining": "198",
                              "X-RateLimit-Reset": "1800000000"})
        with patch("pexels_api.requests.get", return_value=reply):
            result = search_photos("nature", "synthetic-pexels-key")
        self.assertEqual(result["photos"][0]["preview_url"], api_photo()["src"]["medium"])
        self.assertEqual(result["rate_limit"], {"limit": 200, "remaining": 198, "reset": 1800000000})

    def test_missing_or_invalid_quota_headers_do_not_invent_values(self):
        reply = Response({"photos": [], "total_results": 0})
        reply.headers.update({"X-Ratelimit-Limit": "invalid", "X-Ratelimit-Remaining": "-1"})
        with patch("pexels_api.requests.get", return_value=reply):
            result = search_photos("nature", "synthetic-pexels-key")
        self.assertEqual(result["rate_limit"], {})


class MultiframeValidationTests(unittest.TestCase):
    @staticmethod
    def gif_bytes(count=2):
        frames = [Image.new("RGB", (100, 100), (index * 3 % 256, index * 7 % 256, 120))
                  for index in range(count)]
        buffer = io.BytesIO()
        try:
            frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])
            return buffer.getvalue()
        finally:
            for frame in frames:
                frame.close()

    def test_truncated_later_frame_is_rejected_and_not_published(self):
        good = self.gif_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "complete.gif"
            path.write_bytes(good)
            self.assertEqual(inspect_image(path)["format"], "GIF")
            path.unlink()
            with patch("image_io.requests.get", return_value=Response(content=good[:-3])):
                with self.assertRaises(SkillError):
                    download_image(candidate()["original_url"], path)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_excessive_frame_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "many.gif"
            path.write_bytes(self.gif_bytes(65))
            with self.assertRaises(SkillError):
                inspect_image(path)

    def test_cumulative_frame_pixels_are_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "two.gif"
            path.write_bytes(self.gif_bytes())
            with patch("image_io.MAX_TOTAL_PIXELS", 15000), self.assertRaises(SkillError):
                inspect_image(path)


if __name__ == "__main__":
    unittest.main()
