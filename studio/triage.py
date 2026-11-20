from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from pydantic import BaseModel, Field

from studio.codex_backend import complete_structured
from studio.schema import TriageTier


class TriageResult(BaseModel):
    tier: TriageTier
    score: int = Field(ge=1, le=5)
    rationale: str = Field(
        description="Exactly two sentences explaining the tier and score."
    )


TRIAGE_SYSTEM = """You triage a metallurgy paper for a solder/IMC research program.
Assign one tier: Must Read (Deep Dive), Data Source Only, or Low Priority.
Score 1-5 (5 = essential). Rationale must be exactly two sentences.
Do not extract measurements; judge relevance to solder alloying, IMC, and aging."""


def run_triage(
    title: str,
    abstract: Optional[str],
    on_status: Callable[[str], None] | None = None,
) -> TriageResult:
    user = f"Title: {title}\n\nAbstract: {abstract or '(none)'}"
    parsed = complete_structured(
        TriageResult, TRIAGE_SYSTEM, user, on_status=on_status
    )
    if not isinstance(parsed, TriageResult):
        raise ValueError("Triage parse failed.")
    return parsed