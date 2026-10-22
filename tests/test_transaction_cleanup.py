"""Keep published files and provenance in sync on cleanup or interruption."""
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from support import Response, candidate, image_bytes, search_result
from provenance import download_selected
from storage import publish_exclusive


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.candidates = self.root / "candidates.json"
        self.candidates.write_text(json.dumps(search_result(
            [candidate(101), candidate(202)], version=1, provider="pexels")), "utf-8")
        self.output = self.root / "selected"
        self.output.mkdir()
        self.manifest = self.output / "image_sources.json"
        self.previous = b'{"version": 1, "images": []}\n'
        self.manifest.write_bytes(self.previous)

    @patch("image_io.requests.get")
    def test_staging_cleanup_failure_happens_before_manifest_commit(self, get):
        real_temporary_directory = tempfile.TemporaryDirectory

        @contextmanager
        def failed_cleanup(*args, **kwargs):
            with real_temporary_directory(*args, **kwargs) as directory:
                yield directory
            raise OSError("staging cleanup failed")

        get.return_value = Response(content=image_bytes())
        with patch("provenance.tempfile.TemporaryDirectory", failed_cleanup):
            with self.assertRaises(OSError):
                download_selected(self.candidates, [101], self.output)
        self.assertEqual(self.manifest.read_bytes(), self.previous)
        self.assertEqual(list(self.output.iterdir()), [self.manifest])

    @patch("image_io.requests.get")
    def test_user_interrupt_rolls_back_the_batch(self, get):
        get.side_effect = [Response(content=image_bytes()), KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            download_selected(self.candidates, [101, 202], self.output)
        self.assertEqual(self.manifest.read_bytes(), self.previous)
        self.assertEqual(list(self.output.iterdir()), [self.manifest])

    def test_user_interrupt_during_publication_removes_partial_file(self):
        source = self.root / "source.bin"
        source.write_bytes(b"verified image bytes")
        target = self.root / "target.bin"
        with patch("storage.shutil.copyfileobj", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                publish_exclusive(source, target)
        self.assertFalse(target.exists())
        self.assertEqual(source.read_bytes(), b"verified image bytes")


if __name__ == "__main__":
    unittest.main()
