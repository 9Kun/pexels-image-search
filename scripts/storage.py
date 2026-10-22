"""Atomic JSON and exclusive file publication, adapted from PPT Master (MIT)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from config import SkillError


def atomic_write_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.stem + "-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def read_json(path):
    try:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise SkillError("JSON 文件无法读取或已经损坏；请检查候选或来源清单。") from None


def publish_exclusive(source, target):
    target = Path(target)
    created = False
    try:
        with target.open("xb") as destination:
            created = True
            with Path(source).open("rb") as origin:
                shutil.copyfileobj(origin, destination)
            destination.flush()
            os.fsync(destination.fileno())
    except FileExistsError:
        raise SkillError(f"目标文件已存在，未覆盖：{target.name}") from None
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise
