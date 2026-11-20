"""Structured answers through the local Codex CLI, using a ChatGPT subscription login."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

CODEX_CANDIDATES = (
    Path.home() / "AppData" / "Local" / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe",
)

CODEX_EXEC_TIMEOUT_SECONDS = 12 * 60
STATUS_TEXT_MAX = 160


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
) -> BaseModel:
    executable = find_codex()
    if not executable:
        raise RuntimeError("Codex CLI is not installed.")
    if not chatgpt_subscription_active():
        raise RuntimeError("Codex is not signed in with a ChatGPT subscription.")

    schema = model_cls.model_json_schema()
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
            [
                executable,
                "exec",
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
                str(root),
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
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