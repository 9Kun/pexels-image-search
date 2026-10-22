"""Select originals and transactionally append provenance; derived from PPT Master."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile

from config import SkillError
from candidate_validation import validate_candidates, validate_manifest, validate_review_preview
from image_io import download_image, FORMAT_EXTENSIONS
from pexels_api import orientation_matches
from storage import atomic_write_json, publish_exclusive, read_json


@contextmanager
def _output_lock(directory):
    lock = directory / ".pexels-download.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SkillError("此输出目录已有下载任务或残留锁；确认旧任务结束后再处理锁文件。") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def _existing_manifest(path):
    if not path.exists():
        return {"version": 1, "images": []}
    data = read_json(path)
    validate_manifest(data, path.parent)
    return data


def _selected(candidates, ids):
    validate_candidates(candidates)
    if not isinstance(ids, (list, tuple)) or any(type(photo_id) is not int for photo_id in ids):
        raise SkillError("所选照片 ID 必须是正整数。")
    wanted = list(dict.fromkeys(ids))
    available = {photo["id"]: photo for photo in candidates["photos"]}
    if not wanted or any(photo_id <= 0 or photo_id not in available for photo_id in wanted):
        raise SkillError("所选照片 ID 不在候选文件中；请使用照片 ID，而非预览编号。")
    return [available[photo_id] for photo_id in wanted]


def _source_entry(photo, info, filename, candidates, method):
    result = {
        "photo_id": photo["id"], "filename": filename, "provider": "pexels",
        "title": photo.get("title", ""), "search_query": candidates.get("query", ""),
        "photographer": photo.get("photographer", ""),
        "photographer_url": photo.get("photographer_url", ""),
        "source_url": photo.get("source_url", ""), "original_url": photo["original_url"],
        "license": "Pexels License", "license_url": "https://www.pexels.com/license/",
        "api_guidelines_url": "https://www.pexels.com/api/documentation/#guidelines",
        "attribution_text": f"Photo by {photo.get('photographer', '')} on Pexels",
        "selection_method": method, "downloaded_at": datetime.now(timezone.utc).isoformat(),
        **info,
    }
    if (info["width"], info["height"]) != (photo.get("width"), photo.get("height")):
        result["metadata_dimensions"] = {"width": photo.get("width"), "height": photo.get("height")}
    return result


def download_selected(candidates_path, photo_ids, output_dir, selection_method="metadata-only"):
    if selection_method not in ("user-selected", "visual-reviewed", "metadata-only"):
        raise SkillError("selection-method 参数无效。")
    candidates = read_json(candidates_path)
    selected = _selected(candidates, photo_ids)
    if selection_method == "visual-reviewed":
        for photo in selected:
            validate_review_preview(photo, candidates_path)
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "image_sources.json"
    created, entries = [], []
    with _output_lock(output):
        manifest = _existing_manifest(manifest_path)
        for photo in selected:
            if list(output.glob(f"pexels_{photo['id']}.*")) or any(
                e.get("photo_id") == photo["id"] for e in manifest["images"]
            ):
                raise SkillError(f"照片 ID {photo['id']} 已存在，未覆盖；请使用另一个输出目录。")
        try:
            with tempfile.TemporaryDirectory(prefix=".pexels-stage-", dir=output) as staging:
                staged = []
                for photo in selected:
                    temporary = Path(staging) / f"{photo['id']}.image"
                    info = download_image(
                        photo["original_url"], temporary,
                        min_width=int(candidates.get("min_width", 0)),
                        min_height=int(candidates.get("min_height", 0)),
                    )
                    if not orientation_matches(info["width"], info["height"], candidates.get("orientation", "any")):
                        raise SkillError("原图的实际显示方向不符合搜索条件。")
                    name = f"pexels_{photo['id']}{FORMAT_EXTENSIONS[info['format']]}"
                    staged.append((temporary, output / name))
                    entries.append(_source_entry(photo, info, name, candidates, selection_method))
                for temporary, destination in staged:
                    publish_exclusive(temporary, destination)
                    created.append(destination)
            # Finish staging cleanup before committing the provenance manifest.
            atomic_write_json(manifest_path, {**manifest, "images": manifest["images"] + entries})
        except BaseException:
            for destination in created:
                destination.unlink(missing_ok=True)
            raise
    return entries
