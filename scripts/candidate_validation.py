"""Validate local metadata structure and file integrity, not authorship authenticity."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qsl, unquote, urlsplit

from config import SkillError
from image_io import FORMAT_EXTENSIONS, inspect_image, validate_image_url


def _integer(value, minimum=1):
    return type(value) is int and value >= minimum


def _unsafe_characters(text):
    return any(char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\"
               for char in text)


def _check_page_path(path):
    current = path
    while True:
        if _unsafe_characters(current) or any(part in (".", "..") for part in current.split("/")):
            raise SkillError("来源链接含不安全的路径。")
        decoded = unquote(current)
        if decoded == current:
            return
        if decoded.count("/") != current.count("/"):
            raise SkillError("来源链接含隐藏的路径分隔符。")
        current = decoded


def _official_page(url):
    if not isinstance(url, str) or _unsafe_characters(url):
        raise SkillError("来源链接必须是 Pexels 官方 HTTPS 页面。")
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname == "www.pexels.com"
                 and parsed.port in (None, 443) and not parsed.username
                 and not parsed.password and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise SkillError("来源链接必须是 Pexels 官方 HTTPS 页面。")
    _check_page_path(parsed.path)
    return parsed.path


def validate_photo(photo):
    if not isinstance(photo, dict) or not _integer(photo.get("id")):
        raise SkillError("候选照片 ID 必须是正整数。")
    if any(not _integer(photo.get(field)) for field in ("width", "height")):
        raise SkillError("候选照片宽高必须是正整数。")
    if not isinstance(photo.get("title"), str) or not isinstance(photo.get("photographer"), str):
        raise SkillError("候选标题和摄影师必须是文本。")
    if not photo["photographer"].strip():
        raise SkillError("候选照片缺少摄影师，无法保留来源归属。")
    original = photo.get("original_url")
    if not isinstance(original, str) or _unsafe_characters(original):
        raise SkillError("候选原图链接无效。")
    validate_image_url(original)
    parsed_original = urlsplit(original)
    basename = parsed_original.path.rsplit("/", 1)[-1]
    if (not re.fullmatch(rf"/photos/{photo['id']}/[^/]+", parsed_original.path)
            or "%" in basename or basename in (".", "..") or parsed_original.fragment):
        raise SkillError("原图链接与候选照片 ID 不一致。")
    transforms = {"w", "h", "width", "height", "fit", "crop", "rect", "ar", "dpr"}
    if any(key.lower() in transforms for key, _ in parse_qsl(parsed_original.query, keep_blank_values=True)):
        raise SkillError("原图链接含尺寸或裁切变换参数，不能将缩略图记录为原图。")
    source_path = _official_page(photo.get("source_url"))
    if not re.fullmatch(rf"/photo/(?:[^/]+-)?{photo['id']}/?", source_path):
        raise SkillError("来源页面与候选照片 ID 不一致。")
    if not re.fullmatch(r"/@[^/]+/?", _official_page(photo.get("photographer_url"))):
        raise SkillError("摄影师链接不是有效的 Pexels 个人页。")
    for field in ("preview_file", "preview_url", "preview_error", "preview_sha256"):
        if field in photo and not isinstance(photo[field], str):
            raise SkillError("候选预览字段必须是文本。")
    if "preview_sha256" in photo and not re.fullmatch(r"[0-9a-f]{64}", photo["preview_sha256"]):
        raise SkillError("候选预览 SHA-256 无效。")


def validate_candidates(data):
    if (not isinstance(data, dict) or type(data.get("version")) is not int
            or data["version"] != 1 or data.get("provider") != "pexels"
            or not isinstance(data.get("photos"), list)):
        raise SkillError("候选文件结构或版本无效，请重新搜索生成候选。")
    if not isinstance(data.get("query"), str):
        raise SkillError("候选搜索词必须是文本。")
    if data.get("orientation", "any") not in ("any", "landscape", "portrait", "square"):
        raise SkillError("候选文件中的方向筛选无效。")
    if any(not _integer(data.get(field, 0), 0) for field in ("min_width", "min_height")):
        raise SkillError("候选文件中的最低宽高必须是非负整数。")
    seen = set()
    for photo in data["photos"]:
        validate_photo(photo)
        if photo["id"] in seen:
            raise SkillError("候选文件包含重复照片 ID，无法确定所选照片。")
        seen.add(photo["id"])


def file_sha256(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate_review_preview(photo, candidates_path):
    name = photo.get("preview_file")
    if (not name or Path(name).is_absolute() or PureWindowsPath(name).drive
            or PureWindowsPath(name).is_absolute()):
        raise SkillError("所选照片没有有效的目录内预览，不能记录为视觉确认。")
    root = Path(candidates_path).expanduser().resolve().parent
    preview = (root / name.replace("\\", "/")).resolve()
    if not preview.is_relative_to(root) or not preview.is_file():
        raise SkillError("所选照片预览缺失或超出候选目录，不能记录为视觉确认。")
    inspect_image(preview)
    expected = photo.get("preview_sha256")
    if expected and file_sha256(preview) != expected:
        raise SkillError("所选照片预览已改变，不能继续记录为视觉确认。")


def validate_manifest(data, directory):
    if (not isinstance(data, dict) or type(data.get("version")) is not int
            or data["version"] != 1 or not isinstance(data.get("images"), list)):
        raise SkillError("已有来源清单结构无效，未修改任何图片。")
    ids, names = set(), set()
    root = Path(directory).resolve()
    for entry in data["images"]:
        if not isinstance(entry, dict):
            raise SkillError("已有来源清单条目无效，未修改任何图片。")
        validate_photo({**entry, "id": entry.get("photo_id")})
        photo_id, name = entry["photo_id"], entry.get("filename")
        image_format = entry.get("format")
        extension = FORMAT_EXTENSIONS.get(image_format) if isinstance(image_format, str) else None
        if (entry.get("provider") != "pexels" or extension is None
                or name != f"pexels_{photo_id}{extension}"
                or photo_id in ids or name.casefold() in names):
            raise SkillError("已有来源清单含无效或重复照片，未修改任何图片。")
        if not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise SkillError("已有来源清单 SHA-256 无效，未修改任何图片。")
        if not _integer(entry.get("bytes")):
            raise SkillError("已有来源清单字节数无效，未修改任何图片。")
        target = (root / name).resolve()
        if (not target.is_relative_to(root) or not target.is_file()
                or target.stat().st_size != entry["bytes"]
                or file_sha256(target) != entry["sha256"]):
            raise SkillError("已有图片缺失或与来源清单不一致，未修改任何图片。")
        ids.add(photo_id)
        names.add(name.casefold())
