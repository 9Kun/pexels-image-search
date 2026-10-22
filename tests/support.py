"""Deterministic network and image fixtures, used only by tests."""

import io
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
if (SKILL_DIR / "_vendor").is_dir():
    sys.path.insert(0, str(SKILL_DIR / "_vendor"))

import requests
from PIL import Image


class Response:
    def __init__(self, payload=None, content=b"", status=200):
        self.payload = payload
        self.content = content
        self.status_code = status
        self.headers = {"Content-Length": str(len(content))}
        self.url = "https://images.pexels.com/photos/1/pexels-photo-1.jpeg"

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def iter_content(self, chunk_size=8192):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def image_bytes(size=(160, 100), image_format="JPEG", exif=None):
    buffer = io.BytesIO()
    options = {"exif": exif} if exif is not None else {}
    Image.new("RGB", size, (30, 120, 200)).save(
        buffer, format=image_format, **options
    )
    return buffer.getvalue()


def api_photo(photo_id=1, width=2400, height=1600):
    base = f"https://images.pexels.com/photos/{photo_id}/pexels-photo-{photo_id}.jpeg"
    return {
        "id": photo_id, "width": width, "height": height,
        "alt": f"Coastal scene {photo_id}",
        "photographer": "Test Photographer",
        "photographer_url": "https://www.pexels.com/@test-photographer/",
        "url": f"https://www.pexels.com/photo/{photo_id}/",
        "src": {"original": base, "medium": base + "?w=350",
                "large": base + "?w=940", "small": base + "?w=130"},
    }


def candidate(photo_id=1, width=2400, height=1600):
    photo = api_photo(photo_id, width, height)
    return {
        "id": photo_id, "title": photo["alt"], "width": width,
        "height": height, "photographer": photo["photographer"],
        "photographer_url": photo["photographer_url"],
        "source_url": photo["url"], "original_url": photo["src"]["original"],
        "preview_url": photo["src"]["medium"],
    }


def search_result(photos=None, **overrides):
    result = {
        "query": "coastal landscape", "page": 1, "per_page": 20,
        "total_results": 1, "has_next_page": False, "min_width": 0,
        "min_height": 0, "orientation": "any",
        "photos": [candidate()] if photos is None else photos,
    }
    result.update(overrides)
    return result
