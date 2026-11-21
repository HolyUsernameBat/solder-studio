from pathlib import Path

import pytest
from pydantic import BaseModel

from studio.codex_backend import (
    codex_compatible_json_schema,
    lint_codex_compatible_json_schema,
    status_from_event,
    subscription_from_status,
)
from studio.schema import (
    ExtractionList,
    ImcChemistLensOutput,
    MetallurgistLensOutput,
    ReliabilitySkepticLensOutput,
    AgingType,
)
from studio.triage import TriageResult


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
    from pydantic import BaseModel

    class WithEnumDefault(BaseModel):
        aging_type: AgingType = AgingType.UNSPECIFIED

    raw = WithEnumDefault.model_json_schema()
    prop = raw["properties"]["aging_type"]
    assert "$ref" in prop and "default" in prop

    schema = codex_compatible_json_schema(raw)
    cleaned = schema["properties"]["aging_type"]
    assert cleaned == {"$ref": prop["$ref"]}
    assert lint_codex_compatible_json_schema(schema) == []


@pytest.mark.parametrize(
    "model_cls",
    [
        ExtractionList,
        TriageResult,
        MetallurgistLensOutput,
        ImcChemistLensOutput,
        ReliabilitySkepticLensOutput,
    ],
)
def test_production_models_pass_codex_schema_lint(model_cls):
    schema = codex_compatible_json_schema(model_cls.model_json_schema())
    errors = lint_codex_compatible_json_schema(schema)
    assert errors == [], f"{model_cls.__name__}: {errors}"


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
