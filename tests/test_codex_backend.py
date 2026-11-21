from pathlib import Path

import pytest
from pydantic import BaseModel

from studio.codex_backend import (
    CODEX_MODEL_EXTRACT,
    CODEX_MODEL_SYNTH,
    build_codex_exec_argv,
    codex_compatible_json_schema,
    complete_structured,
    lint_codex_compatible_json_schema,
    status_from_event,
    subscription_from_status,
)
from studio.schema import (
    ExtractionList,
    InterfaceMechanismsLensOutput,
    MeasurementRow,
    MetallurgistLensOutput,
    ReliabilitySkepticLensOutput,
)
from studio.triage import PaperTriageAudit


def test_chatgpt_subscription_status_is_recognized():
    assert subscription_from_status("Logged in using ChatGPT\n")


def test_api_key_login_is_not_the_subscription():
    assert not subscription_from_status("Logged in using an API key\n")
    assert not subscription_from_status("Not logged in\n")


def test_codex_pipe_accepts_greek_delta():
    source = Path("studio/codex_backend.py").read_text(encoding="utf-8")
    assert 'encoding="utf-8"' in source
    text = "Cu6Sn5 \u0394 1.2"
    text.encode("utf-8")
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return
    raise AssertionError("delta should not fit in the Windows console encoding")


def test_codex_compatible_schema_sets_additional_properties_on_objects():
    class Inner(BaseModel):
        count: int

    class Outer(BaseModel):
        label: str
        inner: Inner

    schema = codex_compatible_json_schema(Outer.model_json_schema())
    assert schema.get("additionalProperties") is False
    assert schema["$defs"]["Inner"].get("additionalProperties") is False
    assert schema.get("required") == ["label", "inner"]
    assert schema["$defs"]["Inner"].get("required") == ["count"]


def test_codex_compatible_schema_walks_combinators():
    raw = {
        "type": "object",
        "properties": {
            "choice": {
                "anyOf": [
                    {"type": "object", "properties": {"a": {"type": "string"}}},
                    {"type": "string"},
                ]
            }
        },
        "items": {"type": "object", "properties": {"id": {"type": "integer"}}},
        "additionalProperties": {"type": "object", "properties": {"extra": {"type": "boolean"}}},
    }
    schema = codex_compatible_json_schema(raw)
    assert schema["additionalProperties"] is False
    assert schema.get("required") == ["choice"]
    assert schema["properties"]["choice"]["anyOf"][0]["additionalProperties"] is False
    assert schema["properties"]["choice"]["anyOf"][0].get("required") == ["a"]
    assert schema["items"]["additionalProperties"] is False
    assert schema["items"].get("required") == ["id"]


def test_codex_compatible_schema_strips_ref_siblings():
    from studio.schema import SourceSection

    class WithEnumDefault(BaseModel):
        source_section: SourceSection = SourceSection.RESULTS

    raw = WithEnumDefault.model_json_schema()
    prop = raw["properties"]["source_section"]
    assert "$ref" in prop and "default" in prop

    schema = codex_compatible_json_schema(raw)
    cleaned = schema["properties"]["source_section"]
    assert cleaned == {"$ref": prop["$ref"]}
    assert lint_codex_compatible_json_schema(schema) == []


@pytest.mark.parametrize(
    "model_cls",
    [
        ExtractionList,
        PaperTriageAudit,
        MeasurementRow,
        MetallurgistLensOutput,
        InterfaceMechanismsLensOutput,
        ReliabilitySkepticLensOutput,
    ],
)
def test_production_models_pass_codex_schema_lint(model_cls):
    schema = codex_compatible_json_schema(model_cls.model_json_schema())
    errors = lint_codex_compatible_json_schema(schema)
    assert errors == [], f"{model_cls.__name__}: {errors}"


def test_build_codex_exec_argv_omits_m_without_model(tmp_path):
    schema_path = tmp_path / "schema.json"
    output_path = tmp_path / "out.txt"
    argv = build_codex_exec_argv(
        "/bin/codex",
        schema_path=schema_path,
        output_path=output_path,
        work_dir=tmp_path,
    )
    assert "-m" not in argv
    assert "--ignore-user-config" in argv
    assert str(schema_path) in argv


@pytest.mark.parametrize(
    ("slug", "constant"),
    [
        ("gpt-6.2-sol", CODEX_MODEL_EXTRACT),
        ("gpt-6-luna", CODEX_MODEL_SYNTH),
    ],
)
def test_build_codex_exec_argv_pins_model_slug(tmp_path, slug, constant):
    assert slug == constant
    argv = build_codex_exec_argv(
        "codex.exe",
        schema_path=tmp_path / "schema.json",
        output_path=tmp_path / "out.txt",
        work_dir=tmp_path,
        model=slug,
    )
    idx = argv.index("-m")
    assert argv[idx + 1] == slug
    assert argv[1:4] == ["exec", "-m", slug]


def test_complete_structured_passes_model_to_exec_argv(monkeypatch, tmp_path):
    class Tiny(BaseModel):
        value: int

    captured: dict[str, list[str]] = {}

    class FakeProc:
        stdin = None
        stdout = None
        stderr = None

        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            self.stdin = type("W", (), {"write": lambda s, x: None, "close": lambda s: None})()
            self.stdout = type(
                "R",
                (),
                {"readline": lambda s: "",},
            )()
            self.stderr = type("E", (), {"read": lambda s: ""})()

        def poll(self):
            return 0

        def kill(self):
            pass

        def wait(self):
            return 0

    def fake_tempdir():
        root = tmp_path / "work"
        root.mkdir()
        (root / "last.txt").write_text('{"value": 1}', encoding="utf-8")
        return root

    monkeypatch.setattr("studio.codex_backend.find_codex", lambda: "codex.exe")
    monkeypatch.setattr("studio.codex_backend.chatgpt_subscription_active", lambda: True)

    class FakeTempDir:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return str(fake_tempdir())

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("studio.codex_backend.tempfile.TemporaryDirectory", FakeTempDir)
    monkeypatch.setattr("studio.codex_backend.subprocess.Popen", FakeProc)

    complete_structured(Tiny, "sys", "user", model=CODEX_MODEL_EXTRACT)
    argv = captured["argv"]
    assert argv[argv.index("-m") + 1] == CODEX_MODEL_EXTRACT


def test_status_from_event_maps_known_types():
    assert status_from_event({"type": "turn.started"}) == "Turn started."
    assert status_from_event({"type": "turn.completed"}) == "Turn finished."
    msg = status_from_event(
        {
            "type": "item.completed",
            "item": {"id": "1", "type": "agent_message", "text": "Extracting rows."},
        }
    )
    assert msg == "Extracting rows."
    assert status_from_event({"type": "thread.started", "thread_id": "abc"}) is None
    assert status_from_event({"type": "item.started", "item": {"type": "reasoning"}}) is None