from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from pydantic import BaseModel, Field

from studio.codex_backend import CODEX_MODEL_EXTRACT, complete_structured
from studio.schema import TriageTier

TRIAGE_TEXT_MAX_CHARS = 12000


class PaperTriageAudit(BaseModel):
    triage_tier: TriageTier
    relevance_score: int = Field(ge=1, le=5)
    relevance_justification: str = Field(
        description="How this paper relates to the active research question."
    )
    core_claim_and_mechanism: str
    system_and_conditions: str
    key_findings: str
    limitations_and_caveats: str


def _triage_system(research_question: str, screening_criteria: str) -> str:
    criteria_block = ""
    if screening_criteria.strip():
        criteria_block = f"\nScreening criteria: {screening_criteria}\n"
    return f"""You audit a metallurgy paper for an active research program.
Active research question: {research_question}
{criteria_block}
Assign triage_tier: Must Read (Deep Dive), Data Source Only, or Low Priority.
relevance_score 1-5 (5 = essential). Tie relevance_justification to the research question.
Fill core_claim_and_mechanism, system_and_conditions, key_findings, limitations_and_caveats.
Do not extract measurements; analyze relevance and content only."""


def run_triage(
    title: str,
    text: Optional[str],
    *,
    research_question: str,
    screening_criteria: str = "",
    on_status: Callable[[str], None] | None = None,
    model: str | None = None,
) -> PaperTriageAudit:
    snippet = (text or "(none)")[:TRIAGE_TEXT_MAX_CHARS]
    user = f"Title: {title}\n\nText:\n{snippet}"
    parsed = complete_structured(
        PaperTriageAudit,
        _triage_system(research_question, screening_criteria),
        user,
        on_status=on_status,
        model=model or CODEX_MODEL_EXTRACT,
    )
    if not isinstance(parsed, PaperTriageAudit):
        raise ValueError("Triage parse failed.")
    return parsed