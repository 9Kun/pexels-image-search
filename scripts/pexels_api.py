"""Pexels-only adapter derived from PPT Master provider_pexels.py (MIT)."""
from __future__ import annotations

import requests

from config import SkillError, validate_api_key
from http_auth import NoNetrcAuth

API_URL = "https://api.pexels.com/v1/search"
USER_AGENT = "pexels-image-search/1.1"


def orientation_matches(width, height, orientation):
    if orientation == "landscape":
        return width > height
    if orientation == "portrait":
        return height > width
    if orientation == "square":
        return width == height
    return True


def _photo(item):
    src = item.get("src") or {}
    return {
        "id": int(item["id"]),
        "title": str(item.get("alt") or "Pexels photo"),
        "width": int(item.get("width") or 0),
        "height": int(item.get("height") or 0),
        "photographer": str(item.get("photographer") or ""),
        "photographer_url": str(item.get("photographer_url") or ""),
        "source_url": str(item.get("url") or ""),
        "original_url": str(src.get("original") or ""),
        "preview_url": str(src.get("medium") or src.get("small") or ""),
    }


def search_photos(query, key, *, page=1, per_page=20, orientation="any",
                  min_width=0, min_height=0):
    query = query.strip()
    key = validate_api_key(key)
    if not query:
        raise SkillError("搜索词不能为空。")
    if page < 1 or not 1 <= per_page <= 80 or min_width < 0 or min_height < 0:
        raise SkillError("page 必须大于 0，per-page 为 1–80，最低尺寸不得为负数。")
    if orientation not in ("any", "landscape", "portrait", "square"):
        raise SkillError("图片方向参数无效。")
    params = {"query": query, "page": page, "per_page": per_page}
    if orientation != "any":
        params["orientation"] = orientation
    response = None
    try:
        response = requests.get(
            API_URL, params=params,
            headers={"Authorization": key, "User-Agent": USER_AGENT,
                     "Accept": "application/json"},
            timeout=(10, 30), allow_redirects=False, auth=NoNetrcAuth(),
        )
        status = response.status_code
        if status == 401:
            raise SkillError("Pexels 返回 401：API Key 无效或已撤销。")
        if status == 429:
            raise SkillError("Pexels 返回 429：请求额度已用尽，请稍后重试。")
        if status != 200:
            raise SkillError(f"Pexels 搜索失败（HTTP {status}），请稍后重试。")
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("photos"), list):
            raise SkillError("Pexels 返回了无效的搜索结果。")
        photos, seen = [], set()
        for item in data["photos"]:
            try:
                photo = _photo(item)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if (photo["id"] <= 0 or photo["id"] in seen or not photo["original_url"]
                    or photo["width"] <= 0 or photo["height"] <= 0):
                continue
            seen.add(photo["id"])
            if photo["width"] < min_width or photo["height"] < min_height:
                continue
            if orientation_matches(photo["width"], photo["height"], orientation):
                photos.append(photo)
        return {
            "version": 1, "provider": "pexels", "query": query,
            "page": page, "per_page": per_page,
            "total_results": int(data.get("total_results") or 0),
            "has_next_page": bool(data.get("next_page")),
            "returned_count": len(data["photos"]), "filtered_count": len(photos),
            "orientation": orientation, "min_width": min_width, "min_height": min_height,
            "photos": photos, "rate_limit": _rate_limit(response),
        }
    except requests.Timeout:
        raise SkillError("Pexels 搜索超时，请稍后重试。") from None
    except requests.RequestException:
        raise SkillError("无法连接 Pexels，请检查网络后重试。") from None
    except (ValueError, TypeError):
        raise SkillError("Pexels 返回了无法解析的响应。") from None
    finally:
        if response is not None:
            response.close()


def _rate_limit(response):
    """Successful API responses carry the authoritative quota headers."""
    headers = {str(name).lower(): value for name, value in response.headers.items()}
    values = {}
    for field in ("limit", "remaining", "reset"):
        try:
            value = int(headers[f"x-ratelimit-{field}"])
        except (KeyError, TypeError, ValueError):
            continue
        if value >= 0:
            values[field] = value
    return values
