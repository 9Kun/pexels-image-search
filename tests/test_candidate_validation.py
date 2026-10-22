"""Reject tampered metadata before downloads; verify review and existing files."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import Response, candidate, image_bytes, search_result
from config import SkillError
from provenance import download_selected


class CandidateValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "candidates.json"
        self.output = self.root / "selected"

    def save(self, photo=None, **updates):
        data = search_result([photo or candidate(101)], version=1, provider="pexels")
        data.update(updates)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def rejected(self, *, method="metadata-only"):
        with patch("image_io.requests.get") as get, self.assertRaises(SkillError):
            download_selected(self.path, [101], self.output, method)
        get.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_schema_and_filter_types_are_strict(self):
        cases = [{"version": 999}, {"version": True}, {"photos": {}},
                 {"orientation": "diagonal"}, {"min_width": -1},
                 {"min_width": True}, {"min_width": "1"},
                 {"min_height": 1.5}, {"query": ["coast"]}]
        for update in cases:
            with self.subTest(update=update):
                self.save(**update)
                self.rejected()

    def test_candidate_id_and_metadata_types_are_strict(self):
        cases = [("id", True), ("id", 101.9), ("id", "101"),
                 ("width", True), ("height", 0), ("photographer", {}),
                 ("photographer", ""), ("title", []), ("preview_file", 9)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                photo = candidate(101)
                photo[key] = value
                self.save(photo)
                self.rejected()

    def test_duplicate_candidate_ids_cannot_silently_select_the_last_photo(self):
        first, second = candidate(101), candidate(101)
        second["original_url"] = candidate(202)["original_url"]
        self.save(photos=[first, second])
        self.rejected()

    def test_original_and_attribution_urls_must_match_the_photo(self):
        cases = [("original_url", candidate(202)["original_url"]),
                 ("source_url", "https://www.pexels.com/photo/202/"),
                 ("source_url", "https://example.com/photo/101/"),
                 ("source_url", "https://www.pexels.com.evil.test/photo/101/"),
                 ("source_url", "https://user@www.pexels.com/photo/101/"),
                 ("photographer_url", "https://example.com/@person/"),
                 ("photographer_url", "https://www.pexels.com/photo/101/")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                photo = candidate(101)
                photo[key] = value
                self.save(photo)
                self.rejected()

    def test_false_visual_review_rejects_missing_invalid_and_escaped_previews(self):
        (self.root / "broken.jpg").write_bytes(b"not an image")
        for name in (None, "previews/missing.jpg", "broken.jpg", "../outside.jpg",
                     str(self.root / "broken.jpg")):
            with self.subTest(name=name):
                photo = candidate(101)
                if name is not None:
                    photo["preview_file"] = name
                self.save(photo)
                self.rejected(method="visual-reviewed")

    def test_original_path_bypasses_and_resizing_queries_are_rejected(self):
        root = "https://images.pexels.com/photos/101/"
        suffixes = ["../../photos/202/pexels-photo-202.jpeg", "..", ".",
                    "a\\b.jpeg", "image%2F..%2Fother.jpeg", "%2e%2e",
                    "image.jpeg#fragment", "image.jpeg?w=20", "image.jpeg?%77=20",
                    "image.jpeg?h=20", "image.jpeg?fit=crop", "image.jpeg?rect=0,0,10,10",
                    "image\t.jpeg", "image\x00.jpeg"]
        for suffix in suffixes:
            with self.subTest(suffix=suffix):
                self.save(dict(candidate(101), original_url=root + suffix))
                self.rejected()

    def test_attribution_urls_reject_hidden_path_separators_and_traversal(self):
        cases = [("source_url", "/photo/evil%2Fpath-101/"),
                 ("source_url", "/photo/evil%252Fpath-101/"),
                 ("source_url", "/photo/evil\\path-101/"),
                 ("source_url", "/photo/../photo/101/"),
                 ("photographer_url", "/@person%2F..%2Fother/"),
                 ("photographer_url", "/@person%5Cother/"),
                 ("photographer_url", "/@person/../other/"),
                 ("photographer_url", "/@person%00/")]
        for field, path in cases:
            with self.subTest(field=field, path=path):
                photo = candidate(101)
                photo[field] = "https://www.pexels.com" + path
                self.save(photo)
                self.rejected()

    def test_preview_hash_mismatch_is_rejected_before_download(self):
        (self.root / "preview.jpg").write_bytes(image_bytes())
        photo = dict(candidate(101), preview_file="preview.jpg", preview_sha256="0" * 64)
        self.save(photo)
        self.rejected(method="visual-reviewed")

    @patch("image_io.requests.get")
    def test_valid_review_supports_legacy_files_and_hash_checked_files(self, get):
        content = image_bytes()
        get.return_value = Response(content=content)
        (self.root / "preview.jpg").write_bytes(content)
        for with_hash in (False, True):
            with self.subTest(with_hash=with_hash):
                photo = dict(candidate(101), preview_file="preview.jpg")
                photo["source_url"] = "https://www.pexels.com/photo/ocean-view-101/"
                if with_hash:
                    photo["preview_sha256"] = hashlib.sha256(content).hexdigest()
                self.save(photo)
                records = download_selected(self.path, [101], self.root / str(with_hash),
                                            "visual-reviewed")
                self.assertEqual(records[0]["selection_method"], "visual-reviewed")

    @patch("image_io.requests.get")
    def test_default_selection_is_metadata_only(self, get):
        self.save()
        get.return_value = Response(content=image_bytes())
        records = download_selected(self.path, [101], self.output)
        self.assertEqual(records[0]["selection_method"], "metadata-only")

    @patch("image_io.requests.get")
    def test_changed_existing_file_prevents_manifest_append(self, get):
        self.save()
        get.return_value = Response(content=image_bytes())
        records = download_selected(self.path, [101], self.output)
        (self.output / records[0]["filename"]).write_bytes(image_bytes((70, 60)))
        original_manifest = (self.output / "image_sources.json").read_bytes()
        self.save(candidate(202))
        get.reset_mock()
        with self.assertRaises(SkillError):
            download_selected(self.path, [202], self.output)
        get.assert_not_called()
        self.assertEqual((self.output / "image_sources.json").read_bytes(), original_manifest)

    @patch("image_io.requests.get")
    def test_duplicate_manifest_photo_ids_are_rejected(self, get):
        self.save()
        get.return_value = Response(content=image_bytes())
        download_selected(self.path, [101], self.output)
        manifest_path = self.output / "image_sources.json"
        manifest = json.loads(manifest_path.read_text("utf-8"))
        manifest["images"].append(dict(manifest["images"][0], filename="other.jpg"))
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.save(candidate(202))
        get.reset_mock()
        with self.assertRaises(SkillError):
            download_selected(self.path, [202], self.output)
        get.assert_not_called()

    @patch("image_io.requests.get")
    def test_missing_existing_image_prevents_manifest_append(self, get):
        self.save()
        get.return_value = Response(content=image_bytes())
        first = download_selected(self.path, [101], self.output)
        (self.output / first[0]["filename"]).unlink()
        self.save(candidate(202))
        get.reset_mock()
        with self.assertRaises(SkillError):
            download_selected(self.path, [202], self.output)
        get.assert_not_called()

    @patch("image_io.requests.get")
    def test_valid_existing_manifest_and_original_are_preserved_on_append(self, get):
        self.save()
        content = image_bytes()
        get.return_value = Response(content=content)
        first = download_selected(self.path, [101], self.output)
        self.save(candidate(202))
        second = download_selected(self.path, [202], self.output)
        manifest = json.loads((self.output / "image_sources.json").read_text("utf-8"))
        self.assertEqual(manifest["images"], first + second)
        self.assertEqual((self.output / first[0]["filename"]).read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
