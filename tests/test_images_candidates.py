"""Actual bytes, validation cleanup and thumbnail-only candidate review."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import Image, Response, candidate, image_bytes, requests, search_result
from candidates import create_candidates
from config import SkillError
from image_io import download_image


class ImageDownloadTests(unittest.TestCase):
    url = candidate()["original_url"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "中文图片"
        self.root.mkdir()

    @patch("image_io.requests.get")
    def test_original_download_preserves_exact_bytes_and_measures_format(self, get):
        content = image_bytes((180, 120), "PNG")
        get.return_value = Response(content=content)
        target = self.root / "原始图片.bin"
        result = download_image(self.url, target, min_width=180, min_height=120)
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual((result["width"], result["height"]), (180, 120))
        self.assertEqual(result["format"], "PNG")
        self.assertEqual(result["bytes"], len(content))
        self.assertTrue(get.call_args.kwargs["stream"])

    @patch("image_io.requests.get")
    def test_existing_file_is_not_overwritten_or_requested(self, get):
        target = self.root / "existing.jpg"
        target.write_bytes(b"previous user file")
        with self.assertRaises(SkillError):
            download_image(self.url, target)
        self.assertEqual(target.read_bytes(), b"previous user file")
        get.assert_not_called()

    def test_invalid_bytes_and_insufficient_measured_dimensions_leave_no_file(self):
        cases = [(b"not an image", 0, 0), (image_bytes((100, 80)), 120, 80)]
        for content, min_width, min_height in cases:
            with self.subTest(size=len(content)), patch("image_io.requests.get") as get:
                get.return_value = Response(content=content)
                target = self.root / "invalid.jpg"
                with self.assertRaises(SkillError):
                    download_image(self.url, target, min_width=min_width,
                                   min_height=min_height)
                self.assertFalse(target.exists())
                self.assertEqual(list(self.root.iterdir()), [])

    @patch("image_io.requests.get")
    def test_interrupted_stream_cleans_up_partial_file(self, get):
        class BrokenResponse(Response):
            def iter_content(self, chunk_size=8192):
                yield image_bytes()[:100]
                raise requests.ConnectionError("connection closed")

        get.return_value = BrokenResponse()
        target = self.root / "interrupted.jpg"
        with self.assertRaises(SkillError):
            download_image(self.url, target)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    @patch("image_io.requests.get")
    def test_exif_rotated_jpeg_is_measured_without_reencoding(self, get):
        exif = Image.Exif()
        exif[274] = 6
        content = image_bytes((180, 120), exif=exif)
        get.return_value = Response(content=content)
        target = self.root / "rotated.jpg"
        result = download_image(self.url, target)
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual((result["raw_width"], result["raw_height"]), (180, 120))
        self.assertEqual((result["width"], result["height"]), (120, 180))


class CandidatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "中文候选"

    @patch("image_io.requests.get")
    def test_only_previews_are_fetched_and_nine_candidates_get_two_sheets(self, get):
        photos = [candidate(photo_id) for photo_id in range(1, 10)]
        get.return_value = Response(content=image_bytes())
        metadata_path = create_candidates(search_result(photos, total_results=9), self.root)
        metadata = json.loads(metadata_path.read_text("utf-8"))
        requested = [call.args[0] for call in get.call_args_list]
        self.assertEqual(requested, [photo["preview_url"] for photo in photos])
        self.assertFalse(set(requested) & {photo["original_url"] for photo in photos})
        self.assertEqual([photo["candidate_number"] for photo in metadata["photos"]],
                         list(range(1, 10)))
        self.assertEqual(len(metadata["contact_sheets"]), 2)
        for sheet in metadata["contact_sheets"]:
            with Image.open(metadata_path.parent / sheet) as image:
                image.load()
                self.assertGreater(image.width, 0)
        self.assertTrue(all(photo.get("preview_file") for photo in metadata["photos"]))

    @patch("image_io.requests.get")
    def test_empty_search_has_metadata_and_no_downloads(self, get):
        metadata_path = create_candidates(search_result([], total_results=0), self.root)
        metadata = json.loads(metadata_path.read_text("utf-8"))
        self.assertEqual(metadata["photos"], [])
        self.assertEqual(metadata["contact_sheets"], [])
        get.assert_not_called()

    @patch("image_io.requests.get")
    def test_preview_failure_is_recorded_and_does_not_fall_back_to_original(self, get):
        get.side_effect = requests.Timeout("unavailable")
        metadata_path = create_candidates(search_result(), self.root)
        metadata = json.loads(metadata_path.read_text("utf-8"))
        self.assertTrue(metadata["photos"][0].get("preview_error"))
        self.assertTrue(get.called)
        self.assertNotIn(candidate()["original_url"],
                         [call.args[0] for call in get.call_args_list])

    @patch("image_io.requests.get")
    def test_new_page_does_not_overwrite_previous_search_files(self, get):
        get.return_value = Response(content=image_bytes())
        first = create_candidates(search_result(), self.root)
        saved = first.read_bytes()
        second = create_candidates(search_result([candidate(21)], page=2), self.root)
        self.assertNotEqual(first.parent, second.parent)
        self.assertEqual(first.read_bytes(), saved)
        self.assertEqual(json.loads(second.read_text("utf-8"))["page"], 2)


if __name__ == "__main__":
    unittest.main()
