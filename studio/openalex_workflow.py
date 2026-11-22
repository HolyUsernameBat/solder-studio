"""OpenAlex search + store workflow shared by Streamlit and CLI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from studio import db
from studio.openalex import search_openalex, try_fetch_pdf_for_work
from studio.triage import run_triage


def store_openalex_search_results(
    base: Path,
    project_id: int,
    question_id: int,
    query: str,
    pdfs_dir: Path,
    *,
    research_question: str,
    screening_criteria: str,
    extract_model: str | None = None,
    on_status: Callable[[str], None] | None = None,
    search_fn=search_openalex,
) -> dict[str, Any]:
    """
    Run OpenAlex search like Search & triage: blank blocked by search_openalex,
    PDF gate and naming via try_fetch_pdf_for_work, triage per hit.
    """
    hits = search_fn(query)
    stored: list[dict[str, Any]] = []
    for hit in hits:
        work = hit.raw
        pdf_name, coverage = try_fetch_pdf_for_work(work, pdfs_dir)
        paper = hit.paper
        paper.coverage = coverage
        paper.project_id = project_id
        if pdf_name:
            paper.pdf_path = pdf_name
        paper_id = db.upsert_paper(base, paper, pdf_kept=bool(pdf_name))
        triage_error: str | None = None
        try:
            tri = run_triage(
                paper.title,
                paper.abstract,
                research_question=research_question,
                screening_criteria=screening_criteria,
                on_status=on_status,
                model=extract_model,
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
            triage_error = str(exc)
        stored.append(
            {
                "paper_id": paper_id,
                "title": paper.title,
                "coverage": paper.coverage.value,
                "pdf_path": paper.pdf_path,
                "triage_error": triage_error,
            }
        )
    return {"query": query.strip(), "stored_count": len(stored), "papers": stored}