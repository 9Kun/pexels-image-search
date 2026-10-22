"""Independent configuration, adapted from PPT Master (MIT, Hugo He)."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


class SkillError(Exception):
    """An actionable error whose message is safe to display."""


def configure_runtime() -> None:
    vendor = SKILL_DIR / "_vendor"
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
        elif hasattr(stream, "buffer"):
            setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8"))


def _env_value(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SkillError("PEXELS_API_KEY 配置包含控制字符，请在本机重新填写。")
    value = value.strip()
    if value.startswith(("'", '"')):
        end = value.find(value[0], 1)
        if end < 0:
            raise SkillError("PEXELS_API_KEY 的引号配置无效。")
        tail = value[end + 1:].strip()
        if tail and not tail.startswith("#"):
            raise SkillError("PEXELS_API_KEY 的引号后存在无效内容。")
        return value[1:end].strip()
    return value.split("#", 1)[0].strip()


def validate_api_key(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SkillError("PEXELS_API_KEY 包含控制字符，请在本机重新填写。")
    key = value.strip()
    if not key or key.lower().startswith(("your_", "your-", "replace_", "replace-", "<")):
        raise SkillError("缺少有效的 PEXELS_API_KEY，请在本机配置。")
    if any(not 33 <= ord(char) <= 126 for char in key):
        raise SkillError("PEXELS_API_KEY 格式无效，请在本机检查是否误加了空格或其他字符。")
    return key


def load_api_key(env_file=None, skill_dir=None) -> str:
    key = os.environ.get("PEXELS_API_KEY", "")
    if key.strip() or any(ord(char) < 32 or ord(char) == 127 for char in key):
        return validate_api_key(key)
    path = Path(env_file).expanduser() if env_file is not None else Path(skill_dir or SKILL_DIR) / ".env"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = handle.read().split("\n")
    except (OSError, UnicodeError):
        raise SkillError("无法读取 Pexels 配置文件；请配置 PEXELS_API_KEY 或 --env-file。") from None
    values = []
    for raw in lines:
        line = raw.removesuffix("\r").strip(" ")
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if separator and name.strip() == "PEXELS_API_KEY":
            values.append(_env_value(value))
    if len(values) > 1:
        raise SkillError("配置中重复定义了 PEXELS_API_KEY，请保留一个值。")
    key = values[0] if values else ""
    return validate_api_key(key)
