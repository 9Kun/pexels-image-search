"""Verified downloads; original bytes are never re-encoded or resized."""
from __future__ import annotations

import hashlib
import os
import tempfile
import warnings
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image

from config import SkillError
from http_auth import NoNetrcAuth
from storage import publish_exclusive

FORMAT_EXTENSIONS = {"JPEG": ".jpg", "MPO": ".mpo", "PNG": ".png",
                     "WEBP": ".webp", "TIFF": ".tiff", "GIF": ".gif",
                     "BMP": ".bmp", "AVIF": ".avif"}
MAX_IMAGE_BYTES = 256 * 1024 * 1024
MAX_IMAGE_FRAMES = 64
MAX_TOTAL_PIXELS = Image.MAX_IMAGE_PIXELS or 89_478_485


def validate_image_url(url):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname == "images.pexels.com"
                 and not parsed.username and not parsed.password
                 and parsed.port in (None, 443))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise SkillError("图片地址必须是 Pexels 官方 HTTPS 图片地址。")


def inspect_image(path):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as picture:
                image_format = picture.format
                picture.verify()
            with Image.open(path) as picture:
                raw_width, raw_height = picture.size
                rotation = picture.getexif().get(274, 1)
                total_pixels = 0
                for index in range(MAX_IMAGE_FRAMES + 1):
                    try:
                        picture.seek(index)
                    except EOFError:
                        break
                    total_pixels += picture.width * picture.height
                    if index >= MAX_IMAGE_FRAMES or total_pixels > MAX_TOTAL_PIXELS:
                        raise SkillError("图片帧数或累计像素超过验证上限，未保存最终文件。")
                    picture.load()
        if image_format not in FORMAT_EXTENSIONS:
            raise SkillError("图片格式不受支持，未保存最终文件。")
        width, height = (raw_height, raw_width) if rotation in (5, 6, 7, 8) else (raw_width, raw_height)
        return {"width": width, "height": height, "raw_width": raw_width,
                "raw_height": raw_height, "format": image_format}
    except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise SkillError("下载内容无法解码为完整图片，未保存最终文件。") from None


def download_image(url, target, *, min_width=0, min_height=0):
    validate_image_url(url)
    target = Path(target)
    if target.exists():
        raise SkillError(f"目标文件已存在，未覆盖：{target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pexels-", suffix=".part", dir=target.parent)
    response = None
    try:
        with os.fdopen(fd, "wb") as handle:
            # No API key is sent to the image CDN, and redirects are not followed.
            response = requests.get(url, stream=True, timeout=(10, 60),
                                    allow_redirects=False, auth=NoNetrcAuth())
            if response.status_code != 200:
                raise SkillError(f"图片下载失败（HTTP {response.status_code}）。")
            digest, size = hashlib.sha256(), 0
            for block in response.iter_content(chunk_size=65536):
                if not block:
                    continue
                size += len(block)
                if size > MAX_IMAGE_BYTES:
                    raise SkillError("图片超过 256 MiB 下载上限，未保存最终文件。")
                handle.write(block)
                digest.update(block)
        info = inspect_image(temporary)
        if info["width"] < min_width or info["height"] < min_height:
            raise SkillError("下载图片的实际尺寸小于要求，未保存最终文件。")
        publish_exclusive(temporary, target)
        return {**info, "bytes": size, "sha256": digest.hexdigest()}
    except requests.Timeout:
        raise SkillError("图片下载超时，未保存最终文件。") from None
    except requests.RequestException:
        raise SkillError("图片下载连接中断，未保存最终文件。") from None
    finally:
        if response is not None:
            response.close()
        Path(temporary).unlink(missing_ok=True)
