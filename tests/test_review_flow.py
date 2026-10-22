"""Observable preview integrity, cautious selection defaults and quota reporting."""
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from support import Response, api_photo, image_bytes, search_result
from candidates import create_candidates
import pexels_search


class ReviewFlowTests(unittest.TestCase):
    @patch("image_io.requests.get")
    def test_preview_hash_matches_bytes_and_default_does_not_claim_user_choice(self, get):
        with tempfile.TemporaryDirectory() as temporary:
            content = image_bytes()
            get.return_value = Response(content=content)
            candidate_path = create_candidates(search_result(), Path(temporary))
            data = json.loads(candidate_path.read_text("utf-8"))
            photo = data["photos"][0]
            preview = candidate_path.parent / photo["preview_file"]
            self.assertEqual(photo["preview_sha256"], hashlib.sha256(preview.read_bytes()).hexdigest())
            args = pexels_search.parser().parse_args([
                "download", "--candidates", str(candidate_path), "--id", "1",
                "--output", str(Path(temporary) / "selected"),
            ])
            result = pexels_search.run(args)
            self.assertEqual(result["images"][0]["selection_method"], "metadata-only")

    @patch("pexels_api.requests.get")
    def test_live_doctor_exposes_only_valid_quota_numbers(self, get):
        response = Response({"total_results": 1, "photos": [api_photo()]})
        response.headers.update({"X-Ratelimit-Limit": "20000",
                                 "X-Ratelimit-Remaining": "17000",
                                 "X-Ratelimit-Reset": "1800000000"})
        get.return_value = response
        stream = io.StringIO()
        with patch.dict(os.environ, {"PEXELS_API_KEY": "test-secret-never-print"}), redirect_stdout(stream):
            status = pexels_search.main(["doctor", "--live"])
        self.assertEqual(status, 0)
        self.assertNotIn("test-secret-never-print", stream.getvalue())
        result = json.loads(stream.getvalue())
        self.assertEqual(result["rate_limit"], {"limit": 20000, "remaining": 17000, "reset": 1800000000})


if __name__ == "__main__":
    unittest.main()
