from __future__ import annotations

from pathlib import Path
from collections.abc import Callable, Sequence
from typing import Optional

from studio import db
from studio.pdf_tables import audit_pdf_text, extract_rows_from_pdf_with_model
from studio.schema import PaperCoverage
from studio.triage import run_triage

def research_question_select_label(
    question_id: int, research_question: str, *, preview_chars: int | None = None
) -> str:
    """Full question text for Streamlit radio labels (wrapping in the UI)."""
    del question_id, preview_chars
    return (research_question or "").strip() or "Untitled question"


def active_research_question_display(research_question: str) -> str:
    """Full question text for read-only display (never truncated)."""
    return research_question or ""


def eligible_queued_audit_paper_ids(
    papers: Sequence[dict], pdfs_dir: Path
) -> list[int]:
    """Queued full-text papers with a pdf_path file on disk."""
    out: list[int] = []
    for p in papers:
        if p.get("coverage") != PaperCoverage.FULL_TEXT.value:
            continue
        pdf_name = p.get("pdf_path")
        if not pdf_name:
            continue
        if (pdfs_dir / pdf_name).is_file():
            out.append(int(p["id"]))
    return out


def paper_ids_for_selected_audit(
    eligible_ids: Sequence[int], checked_ids: set[int]
) -> list[int]:
    """Checked papers that are eligible, in stable eligible order."""
    checked = set(checked_ids)
    return [pid for pid in eligible_ids if pid in checked]


def paper_ids_for_audit_all(eligible_ids: Sequence[int]) -> list[int]:
    """Every eligible queued paper."""
    return list(eligible_ids)


def run_extract_and_triage(
    base: Path,
    paper_id: int,
    project_id: int,
    question_id: int,
    pdf_path: Path,
    paper_title: str,
    *,
    research_question: str,
    screening_criteria: str,
    target_metrics: list[str],
    on_status: Callable[[str], None] | None = None,
) -> tuple[int, Optional[str], Optional[str]]:
    """
    Delete prior measurements for paper, extract quote-verified rows, then structured triage.

    Returns (rows_stored, extract_warning, triage_warning).
    """
    db.delete_measurements_for_paper(base, paper_id, question_id)
    rows, err = extract_rows_from_pdf_with_model(
        pdf_path,
        paper_title,
        research_question=research_question,
        target_metrics=target_metrics,
        on_status=on_status,
    )
    if err:
        return 0, err, None

    n = 0
    if rows:
        for row in rows:
            row.paper_id = paper_id
            row.project_id = project_id
        n = db.insert_measurements(base, project_id, question_id, paper_id, rows)

    triage_warning: Optional[str] = None
    text_for_triage, triage_err = audit_pdf_text(pdf_path)
    if triage_err:
        triage_warning = f"Triage skipped: {triage_err}"
    else:
        try:
            tri = run_triage(
                paper_title,
                text_for_triage,
                research_question=research_question,
                screening_criteria=screening_criteria,
                on_status=on_status,
            )
            db.update_paper_audit(
                base,
                paper_id,
                question_id,
                tier=tri.triage_tier,
                relevance_score=tri.relevance_score,
                relevance_justification=tri.relevance_justification,
                core_claim_and_mechanism=tri.core_claim_and_mechanism,
                system_and_conditions=tri.system_and_conditions,
                key_findings=tri.key_findings,
                limitations_and_caveats=tri.limitations_and_caveats,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            triage_warning = str(exc)

    return n, None, triage_warning