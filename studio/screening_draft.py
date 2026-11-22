"""Draft screening criteria through ChatGPT-login Codex."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from studio.codex_backend import CODEX_MODEL_EXTRACT, complete_structured


class ScreeningCriteriaDraft(BaseModel):
    screening_criteria: str = Field(
        description="Screening criteria for triaging metallurgy papers against the research question."
    )


def _draft_instructions() -> str:
    return """You help a metallurgy researcher write screening criteria for literature triage.
Screening criteria are concise, testable bullets: alloy systems, joint materials, metrics,
experimental vs review, and exclusions. They guide OpenAlex search and paper triage.
Do not write the research question again; write criteria only."""


def draft_screening_criteria(
    research_question: str,
    *,
    current_criteria: str = "",
    target_metrics: list[str] | None = None,
    model: str | None = None,
    on_status: Callable[[str], None] | None = None,
) -> str:
    metrics_block = ""
    if target_metrics:
        metrics_block = "\nTarget metrics to prioritize:\n" + "\n".join(
            f"- {m}" for m in target_metrics
        )
    current_block = ""
    if current_criteria.strip():
        current_block = f"\nCurrent screening criteria (revise or replace as needed):\n{current_criteria}\n"
    user = (
        f"Research question:\n{research_question}\n"
        f"{metrics_block}"
        f"{current_block}\n"
        "Draft screening criteria text for this question."
    )
    parsed = complete_structured(
        ScreeningCriteriaDraft,
        _draft_instructions(),
        user,
        on_status=on_status,
        model=model or CODEX_MODEL_EXTRACT,
    )
    if not isinstance(parsed, ScreeningCriteriaDraft):
        raise ValueError("Screening criteria draft parse failed.")
    return parsed.screening_criteria.strip()