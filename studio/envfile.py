"""Read and write OPENAI_API_KEY. Never print or log the value."""

from __future__ import annotations

import os
from pathlib import Path

KEY_NAME = "OPENAI_API_KEY"


def read_openai_key(directory: Path) -> str:
    """Return the key in directory/.env, or empty when that file is missing."""
    path = directory / ".env"
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != KEY_NAME:
            continue
        return _unquote(value.strip())
    return ""


def write_openai_key(directory: Path, key: str) -> None:
    """Write OPENAI_API_KEY into directory/.env, replacing a previous assignment."""
    cleaned = key.strip()
    if not cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError("OPENAI_API_KEY is empty or not a single line.")
    path = directory / ".env"
    assignment = f"{KEY_NAME}={_quote(cleaned)}"
    lines: list[str] = []
    replaced = False
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if _line_name(raw) == KEY_NAME:
                if not replaced:
                    lines.append(assignment)
                    replaced = True
                continue
            lines.append(raw)
    if not replaced:
        lines.append(assignment)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_openai_api_key(directory: Path) -> str:
    """Process environment first, then .env in directory."""
    from_env = (os.environ.get(KEY_NAME) or "").strip()
    if from_env:
        return from_env
    return read_openai_key(directory)


def _line_name(raw: str) -> str:
    line = raw.strip()
    if line.startswith("export "):
        line = line[len("export ") :].strip()
    if "=" not in line:
        return ""
    return line.split("=", 1)[0].strip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        if value[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return value


def _quote(value: str) -> str:
    if any(ch in value for ch in ' \t#"\'\\'):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
