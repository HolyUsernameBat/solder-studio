"""Shared audit runners for Streamlit and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from studio import db
from studio.audit_flow import run_extract_and_triage
from studio.pdfs_folder import title_from_pdf_filename


@dataclass
class AuditRunResult:
    paper_id: int
    label: str
    rows_stored: int
    extract_error: Optional[str]
    triage_warning: Optional[str]
    fatal_error: Optional[str]

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "label": self.label,
            "rows_stored": self.rows_stored,
            "extract_error": self.extract_error,
            "triage_warning": self.triage_warning,
            "fatal_error": self.fatal_error,
        }


def audit_queued_paper(
    base: Path,
    paper: dict,
    *,
    project_id: int,
    question_id: int,
    pdfs_dir: Path,
    research_question: str,
    screening_criteria: str,
    target_metrics: list[str],
    extract_model: str | None = None,
    on_status=None,
) -> AuditRunResult:
    paper_id = int(paper["id"])
    pdf_name = paper.get("pdf_path")
    if not pdf_name:
        return AuditRunResult(
            paper_id, paper.get("title") or "", 0, None, None, "No local PDF."
        )
    pdf_path = pdfs_dir / pdf_name
    if not pdf_path.is_file():
        return AuditRunResult(
            paper_id,
            paper.get("title") or "",
            0,
            None,
            None,
            "PDF file missing on disk.",
        )
    try:
        n, extract_err, triage_warn = run_extract_and_triage(
            base,
            paper_id,
            project_id,
            question_id,
            pdf_path,
            paper.get("title") or "",
            research_question=research_question,
            screening_criteria=screening_criteria,
            target_metrics=target_metrics,
            on_status=on_status,
            extract_model=extract_model,
        )
    except RuntimeError as exc:
        return AuditRunResult(
            paper_id, paper.get("title") or "", 0, None, None, str(exc)
        )
    except Exception as exc:
        return AuditRunResult(
            paper_id, paper.get("title") or "", 0, None, None, str(exc)
        )
    return AuditRunResult(
        paper_id,
        paper.get("title") or "",
        n,
        extract_err,
        triage_warn,
        None,
    )


def create_and_audit_unlinked_pdf(
    base: Path,
    pdf_name: str,
    *,
    project_id: int,
    question_id: int,
    pdfs_dir: Path,
    research_question: str,
    screening_criteria: str,
    target_metrics: list[str],
    extract_model: str | None = None,
    on_status=None,
) -> AuditRunResult:
    pdf_path = pdfs_dir / pdf_name
    if not pdf_path.is_file():
        return AuditRunResult(
            0, title_from_pdf_filename(pdf_name), 0, None, None, "PDF file missing on disk."
        )
    title = title_from_pdf_filename(pdf_name)
    paper_id = db.insert_folder_paper(base, pdf_name, project_id)
    try:
        n, extract_err, triage_warn = run_extract_and_triage(
            base,
            paper_id,
            project_id,
            question_id,
            pdf_path,
            title,
            research_question=research_question,
            screening_criteria=screening_criteria,
            target_metrics=target_metrics,
            on_status=on_status,
            extract_model=extract_model,
        )
    except RuntimeError as exc:
        return AuditRunResult(paper_id, title, 0, None, None, str(exc))
    except Exception as exc:
        return AuditRunResult(paper_id, title, 0, None, None, str(exc))
    return AuditRunResult(paper_id, title, n, extract_err, triage_warn, None)