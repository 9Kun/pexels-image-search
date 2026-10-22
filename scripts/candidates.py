"""Create an isolated preview set without fetching original images."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

from config import SkillError
from contact_sheet import create_contact_sheets
from image_io import download_image, FORMAT_EXTENSIONS
from storage import atomic_write_json


def create_candidates(result, output_dir):
    output = Path(output_dir).expanduser().resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = output / f"search-{stamp}-{uuid.uuid4().hex[:8]}"
    directory.mkdir(parents=True, exist_ok=False)
    previews = directory / "previews"
    previews.mkdir()
    photos = []
    for index, original in enumerate(result["photos"], 1):
        photo = dict(original, candidate_number=index)
        url = photo.get("preview_url")
        try:
            if not url or url == photo["original_url"]:
                raise SkillError("没有独立缩略图地址，无法生成预览。")
            temporary = previews / f"candidate_{index:02d}.image"
            info = download_image(url, temporary)
            actual = temporary.with_suffix(FORMAT_EXTENSIONS[info["format"]])
            temporary.rename(actual)
            photo["preview_file"] = actual.relative_to(directory).as_posix()
            photo["preview_sha256"] = info["sha256"]
        except (SkillError, OSError) as error:
            photo["preview_error"] = str(error) if isinstance(error, SkillError) else "无法写入缩略图。"
        photos.append(photo)
    data = {**result, "version": 1, "provider": "pexels", "photos": photos,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "selection_status": "needs-review" if photos else "no-results",
            "attribution": "Photos provided by Pexels — https://www.pexels.com"}
    data["contact_sheets"] = create_contact_sheets(photos, directory, result["page"])
    return atomic_write_json(directory / "candidates.json", data)
