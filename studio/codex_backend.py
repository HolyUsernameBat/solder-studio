"""Structured answers through the local Codex CLI, using a ChatGPT subscription login."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import BaseModel

CODEX_CANDIDATES = (
    Path.home() / "AppData" / "Local" / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe",
)

CODEX_EXEC_TIMEOUT_SECONDS = 12 * 60
STATUS_TEXT_MAX = 160

# From this machine's `codex debug models` catalog (visibility=list), Nov 2026.
CODEX_MODEL_EXTRACT = "gpt-6.2-sol"  # paper audit + measurement extraction
CODEX_MODEL_SYNTH = "gpt-6-luna"  # three synthesis lenses

_SCHEMA_CONTAINER_KEYS = (
    "properties",
    "patternProperties",
    "$defs",
    "definitions",
    "dependentSchemas",
)
_SCHEMA_LIST_KEYS = ("anyOf", "oneOf", "allOf", "prefixItems")


def _is_object_schema(node: Mapping[str, Any]) -> bool:
    schema_type = node.get("type")
    if schema_type == "object":
        return True
    if isinstance(schema_type, list) and "object" in schema_type:
        return True
    return "properties" in node and schema_type is None


def _walk_schema_for_codex(node: Any) -> None:
    if not isinstance(node, dict):
        return

    for key in _SCHEMA_CONTAINER_KEYS:
        container = node.get(key)
        if isinstance(container, dict):
            for value in container.values():
                _walk_schema_for_codex(value)

    for key in _SCHEMA_LIST_KEYS:
        items = node.get(key)
        if isinstance(items, list):
            for item in items:
                _walk_schema_for_codex(item)

    items = node.get("items")
    if isinstance(items, dict):
        _walk_schema_for_codex(items)
    elif isinstance(items, list):
        for item in items:
            _walk_schema_for_codex(item)

    additional = node.get("additionalProperties")
    if isinstance(additional, dict):
        _walk_schema_for_codex(additional)

    for key in ("not", "if", "then", "else"):
        sub = node.get(key)
        if isinstance(sub, dict):
            _walk_schema_for_codex(sub)

    ref = node.get("$ref")
    if ref is not None:
        node.clear()
        node["$ref"] = ref
        return

    if _is_object_schema(node):
        node["additionalProperties"] = False
        props = node.get("properties")
        if isinstance(props, dict):
            node["required"] = list(props.keys())
        else:
            node["required"] = []


def codex_compatible_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Codex strict output schemas need additionalProperties: false and required on every object."""
    copy = deepcopy(schema)
    _walk_schema_for_codex(copy)
    return copy


def lint_codex_compatible_json_schema(
    schema: Any, *, path: str = "$"
) -> list[str]:
    """Return human-readable violations of Codex strict JSON Schema rules."""
    errors: list[str] = []
    _lint_codex_schema_node(schema, path, errors)
    return errors


def _lint_codex_schema_node(node: Any, path: str, errors: list[str]) -> None:
    if not isinstance(node, dict):
        return

    if "$ref" in node:
        siblings = [key for key in node if key != "$ref"]
        if siblings:
            errors.append(f"{path}: $ref has sibling keys {siblings}")
        return

    if _is_object_schema(node):
        if node.get("additionalProperties") is not False:
            errors.append(f"{path}: object missing additionalProperties: false")
        props = node.get("properties")
        if isinstance(props, dict):
            expected = list(props.keys())
            required = node.get("required")
            if not isinstance(required, list) or sorted(required) != sorted(expected):
                errors.append(
                    f"{path}: required must list all property keys "
                    f"{expected!r}, got {required!r}"
                )
        elif node.get("required") not in (None, []):
            errors.append(f"{path}: object without properties must have required []")

    for key in _SCHEMA_CONTAINER_KEYS:
        container = node.get(key)
        if isinstance(container, dict):
            for name, value in container.items():
                _lint_codex_schema_node(value, f"{path}/{key}/{name}", errors)

    for key in _SCHEMA_LIST_KEYS:
        items = node.get(key)
        if isinstance(items, list):
            for index, item in enumerate(items):
                _lint_codex_schema_node(item, f"{path}/{key}/{index}", errors)

    items = node.get("items")
    if isinstance(items, dict):
        _lint_codex_schema_node(items, f"{path}/items", errors)
    elif isinstance(items, list):
        for index, item in enumerate(items):
            _lint_codex_schema_node(item, f"{path}/items/{index}", errors)

    additional = node.get("additionalProperties")
    if isinstance(additional, dict):
        _lint_codex_schema_node(additional, f"{path}/additionalProperties", errors)

    for key in ("not", "if", "then", "else"):
        sub = node.get(key)
        if isinstance(sub, dict):
            _lint_codex_schema_node(sub, f"{path}/{key}", errors)


def find_codex() -> str | None:
    found = shutil.which("codex")
    if found:
        return found
    for candidate in CODEX_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return None


def subscription_from_status(text: str) -> bool:
    return "Logged in using ChatGPT" in text


def chatgpt_subscription_active() -> bool:
    executable = find_codex()
    if not executable:
        return False
    completed = subprocess.run(
        [executable, "login", "status"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return subscription_from_status(completed.stdout + completed.stderr)


def status_from_event(obj: dict) -> str | None:
    """Map one Codex JSONL event to a short human status line, or None to skip."""
    event_type = obj.get("type")
    if event_type == "turn.started":
        return "Turn started."
    if event_type == "turn.completed":
        return "Turn finished."
    if event_type == "error":
        raw = obj.get("message") or obj.get("error")
        if isinstance(raw, dict):
            raw = raw.get("message") or str(raw)
        if not raw:
            return "Error."
        return f"Error: {str(raw)[:STATUS_TEXT_MAX]}"
    if event_type == "turn.failed":
        err = obj.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or str(err)
        else:
            msg = str(err) if err else "Turn failed."
        return f"Error: {msg[:STATUS_TEXT_MAX]}"
    if event_type in ("item.completed", "item.updated"):
        item = obj.get("item") or {}
        item_type = item.get("type") or item.get("item_type")
        if item_type in ("agent_message", "assistant_message"):
            text = (item.get("text") or "").strip()
            if text:
                return text[:STATUS_TEXT_MAX]
        return None
    return None


def build_codex_exec_argv(
    executable: str,
    *,
    schema_path: Path,
    output_path: Path,
    work_dir: Path,
    model: str | None = None,
) -> list[str]:
    """Argv for `codex exec` structured output; optional ``-m`` when model is set."""
    argv: list[str] = [
        executable,
        "exec",
    ]
    if model is not None:
        argv.extend(["-m", model])
    argv.extend(
        [
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--ignore-user-config",
            "--json",
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            "-C",
            str(work_dir),
            "-",
        ]
    )
    return argv


def _handle_stdout_line(line: str, on_status: Callable[[str], None] | None) -> None:
    if on_status is None:
        return
    stripped = line.strip()
    if not stripped:
        return
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        on_status(stripped[:STATUS_TEXT_MAX])
        return
    msg = status_from_event(obj)
    if msg:
        on_status(msg)


def complete_structured(
    model_cls: type[BaseModel],
    instructions: str,
    user: str,
    on_status: Callable[[str], None] | None = None,
    *,
    model: str | None = None,
) -> BaseModel:
    executable = find_codex()
    if not executable:
        raise RuntimeError("Codex CLI is not installed.")
    if not chatgpt_subscription_active():
        raise RuntimeError("Codex is not signed in with a ChatGPT subscription.")

    schema = codex_compatible_json_schema(model_cls.model_json_schema())
    prompt = (
        f"{instructions}\n\n{user}\n\n"
        "Return only the JSON object described by the output schema. "
        "Do not run tools, browse, or edit files."
    )
    with tempfile.TemporaryDirectory(prefix="solder-codex-") as tmp:
        root = Path(tmp)
        schema_path = root / "schema.json"
        output_path = root / "last.txt"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        deadline = time.monotonic() + CODEX_EXEC_TIMEOUT_SECONDS
        proc = subprocess.Popen(
            build_codex_exec_argv(
                executable,
                schema_path=schema_path,
                output_path=output_path,
                work_dir=root,
                model=model,
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdin is not None
        proc.stdin.write(prompt)
        proc.stdin.close()
        assert proc.stdout is not None
        timed_out = False
        while True:
            if time.monotonic() > deadline:
                timed_out = True
                proc.kill()
                break
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            _handle_stdout_line(line, on_status)
        if timed_out:
            raise RuntimeError(
                "Codex produced no finished answer within 12 minutes."
            )
        stderr_text = ""
        if proc.stderr is not None:
            stderr_text = proc.stderr.read()
        returncode = proc.wait()
        if returncode != 0:
            detail = (stderr_text or "Codex exec failed.").strip()
            raise RuntimeError(detail[-500:])
        if not output_path.is_file():
            raise RuntimeError("Codex returned no message.")
        raw = output_path.read_text(encoding="utf-8").strip()
    return model_cls.model_validate_json(raw)