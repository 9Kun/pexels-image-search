"""Selected IDs, attributable originals and transactional failure recovery."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import Response, candidate, image_bytes, requests, search_result
from config import SkillError
from provenance import download_selected


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "中文交付"
        self.root.mkdir()
        self.candidates_path = self.root / "candidates.json"
        self.output = self.root / "selected"
        self.output.mkdir()
        self.save_candidates([candidate(101), candidate(202)])

    def save_candidates(self, photos, **kwargs):
        self.candidates_path.write_text(
            json.dumps(search_result(photos, version=1, provider="pexels", **kwargs)),
            "utf-8",
        )

    @patch("image_io.requests.get")
    def test_selected_photo_id_downloads_exact_source_and_records_provenance(self, get):
        content = image_bytes((180, 120), "PNG")
        get.return_value = Response(content=content)
        records = download_selected(self.candidates_path, [202], self.output,
                                    selection_method="user-selected")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["photo_id"], 202)
        self.assertEqual(get.call_args.args[0], candidate(202)["original_url"])
        self.assertEqual(record["filename"], "pexels_202.png")
        self.assertEqual((self.output / record["filename"]).read_bytes(), content)
        self.assertEqual(record["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual((record["width"], record["height"]), (180, 120))
        for field in ("photographer", "photographer_url", "source_url", "original_url"):
            self.assertEqual(record[field], candidate(202)[field])
        self.assertEqual(record["selection_method"], "user-selected")
        self.assertIn("pexels.com", record["license_url"])
        manifest = json.loads((self.output / "image_sources.json").read_text("utf-8"))
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["images"], records)

    @patch("image_io.requests.get")
    def test_unknown_id_is_rejected_before_any_download(self, get):
        with self.assertRaises(SkillError):
            download_selected(self.candidates_path, [999], self.output)
        get.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    @patch("image_io.requests.get")
    def test_duplicate_ids_do_not_produce_duplicate_downloads(self, get):
        get.return_value = Response(content=image_bytes())
        try:
            records = download_selected(self.candidates_path, [101, 101], self.output)
        except SkillError:
            self.assertEqual(list(self.output.iterdir()), [])
        else:
            self.assertEqual([record["photo_id"] for record in records], [101])
            get.assert_called_once()

    @patch("image_io.requests.get")
    def test_metadata_dimensions_do_not_override_actual_file_requirements(self, get):
        self.save_candidates([candidate(101, 4000, 3000)], min_width=1200, min_height=800)
        get.return_value = Response(content=image_bytes((100, 80)))
        with self.assertRaises(SkillError):
            download_selected(self.candidates_path, [101], self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    @patch("image_io.requests.get")
    def test_repeated_selected_download_preserves_existing_image_and_manifest(self, get):
        get.return_value = Response(content=image_bytes())
        records = download_selected(self.candidates_path, [101], self.output)
        original_image = (self.output / records[0]["filename"]).read_bytes()
        manifest = self.output / "image_sources.json"
        original_manifest = manifest.read_bytes()
        get.reset_mock()
        with self.assertRaises(SkillError):
            download_selected(self.candidates_path, [101], self.output)
        self.assertEqual(manifest.read_bytes(), original_manifest)
        self.assertEqual((self.output / records[0]["filename"]).read_bytes(), original_image)
        get.assert_not_called()

    @patch("image_io.requests.get")
    def test_corrupt_existing_manifest_is_preserved(self, get):
        manifest = self.output / "image_sources.json"
        original = b"{broken user manifest"
        manifest.write_bytes(original)
        with self.assertRaises(SkillError):
            download_selected(self.candidates_path, [101], self.output)
        self.assertEqual(manifest.read_bytes(), original)
        get.assert_not_called()

    @patch("image_io.requests.get")
    def test_manifest_write_failure_rolls_back_images_and_preserves_previous_manifest(self, get):
        get.return_value = Response(content=image_bytes())
        manifest = self.output / "image_sources.json"
        original = b'{"version": 1, "images": []}\n'
        manifest.write_bytes(original)
        with patch("provenance.atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises((SkillError, OSError)):
                download_selected(self.candidates_path, [101], self.output)
        self.assertEqual(manifest.read_bytes(), original)
        self.assertEqual(list(self.output.iterdir()), [manifest])

    @patch("image_io.requests.get")
    def test_second_download_failure_leaves_no_partial_batch(self, get):
        get.side_effect = [Response(content=image_bytes()), requests.Timeout("network timeout")]
        with self.assertRaises(SkillError):
            download_selected(self.candidates_path, [101, 202], self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    @patch("image_io.requests.get")
    def test_an_existing_untracked_target_is_not_overwritten(self, get):
        target = self.output / "pexels_101.jpg"
        target.write_bytes(b"user original")
        get.return_value = Response(content=image_bytes())
        with self.assertRaises(SkillError):
            download_selected(self.candidates_path, [101], self.output)
        self.assertEqual(target.read_bytes(), b"user original")
        self.assertFalse((self.output / "image_sources.json").exists())

    @patch("image_io.requests.get")
    def test_actual_portrait_cannot_pass_a_landscape_metadata_claim(self, get):
        self.save_candidates([candidate(101, 2400, 1600)], orientation="landscape")
        get.return_value = Response(content=image_bytes((100, 180)))
        with self.assertRaises(SkillError):
            download_selected(self.candidates_path, [101], self.output)
        self.assertEqual(list(self.output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
