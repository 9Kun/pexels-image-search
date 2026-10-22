"""Portable Pexels photo search, preview, and original-download CLI."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from config import SkillError, configure_runtime, load_api_key

configure_runtime()


def _dependencies():
    found = {}
    for module in ("requests", "PIL"):
        try:
            loaded = importlib.import_module(module)
            found[module] = getattr(loaded, "__version__", "available")
        except ImportError:
            found[module] = None
    return found


def parser():
    root = argparse.ArgumentParser(description="Pexels 图片搜索、预览与原图下载")
    commands = root.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="检查依赖和本机 Key 配置")
    doctor.add_argument("--live", action="store_true", help="进行一次真实 API 搜索")
    doctor.add_argument("--env-file", type=Path)
    search = commands.add_parser("search", help="搜索照片并生成候选预览")
    search.add_argument("query")
    search.add_argument("--output", type=Path, required=True)
    search.add_argument("--orientation", choices=("any", "landscape", "portrait", "square"), default="any")
    search.add_argument("--min-width", type=int, default=0)
    search.add_argument("--min-height", type=int, default=0)
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--per-page", type=int, default=20)
    search.add_argument("--env-file", type=Path)
    download = commands.add_parser("download", help="按候选照片 ID 下载原图")
    download.add_argument("--candidates", type=Path, required=True)
    download.add_argument("--id", action="append", type=int, required=True, dest="photo_ids")
    download.add_argument("--output", type=Path, required=True)
    download.add_argument("--selection-method", choices=("user-selected", "visual-reviewed", "metadata-only"), default="metadata-only")
    return root


def run(args):
    dependencies = _dependencies()
    missing = [name for name, version in dependencies.items() if version is None]
    if args.command == "doctor":
        result = {"ok": not missing, "python": sys.version.split()[0], "dependencies": dependencies,
                  "key_configured": False, "live_verified": False}
        try:
            key = load_api_key(args.env_file)
            result["key_configured"] = True
        except SkillError as error:
            result.update(ok=False, error=str(error))
            return result
        if args.live and not missing:
            from pexels_api import search_photos
            photos = search_photos("nature", key, per_page=1)
            result.update(live_verified=True, result_count=len(photos["photos"]),
                          rate_limit=photos.get("rate_limit", {}))
        return result
    if missing:
        raise SkillError("缺少运行依赖，请用 python -m pip install --target <技能目录>/_vendor -r <技能目录>/requirements.txt 安装。")
    if args.command == "search":
        from pexels_api import search_photos
        from candidates import create_candidates
        result = search_photos(
            args.query, load_api_key(args.env_file), page=args.page, per_page=args.per_page,
            orientation=args.orientation, min_width=args.min_width, min_height=args.min_height,
        )
        candidate_path = create_candidates(result, args.output)
        saved = json.loads(candidate_path.read_text(encoding="utf-8"))
        return {"ok": True, "candidates": str(candidate_path),
                "photo_count": len(saved["photos"]), "has_next_page": result["has_next_page"],
                "rate_limit": result.get("rate_limit", {}),
                "preview_failures": sum("preview_error" in p for p in saved["photos"]),
                "contact_sheets": [str(candidate_path.parent / f) for f in saved["contact_sheets"]]}
    from provenance import download_selected
    entries = download_selected(args.candidates, args.photo_ids, args.output, args.selection_method)
    output = args.output.expanduser().resolve()
    return {"ok": True, "files": [str(output / e["filename"]) for e in entries],
            "sources": str(output / "image_sources.json"), "images": entries}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = run(args)
    except SkillError as error:
        result = {"ok": False, "error": str(error)}
    except OSError:
        result = {"ok": False, "error": "本地文件操作失败，请检查路径、权限和磁盘空间。"}
    except Exception as error:
        # Do not print exception bodies or HTTP payloads that may contain credentials.
        result = {"ok": False, "error": "操作失败，请检查输入文件和依赖。", "error_type": type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
