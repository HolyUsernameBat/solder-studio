"""Build filtered queue payloads for CLI JSON output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from studio import db
from studio.audit_flow import (
    TAG_FILTER_ALL,
    TRIAGE_FILTER_ALL,
    apply_queue_paper_filters,
    effective_triage_tier,
    queue_papers_for_display,
)
from studio.schema import TriageTier


def list_filtered_queue(
    base: Path,
    project_id: int,
    question_id: int,
    pdfs_dir: Path,
    *,
    hide_abstract_only: bool = True,
    triage_filter: str = TRIAGE_FILTER_ALL,
    only_relevance_gt_2: bool = False,
    order: str = "Library order",
    tag_filter: str = TAG_FILTER_ALL,
) -> list[dict[str, Any]]:
    papers = db.list_papers_for_question(base, project_id, question_id)
    tags_by_paper = db.tags_by_paper_for_project(base, project_id)
    after_hide = queue_papers_for_display(papers, pdfs_dir, hide_abstract_only)
    filtered = apply_queue_paper_filters(
        after_hide,
        triage_filter=triage_filter,
        only_relevance_gt_2=only_relevance_gt_2,
        order=order,
        tag_filter=tag_filter,
        tags_by_paper_id=tags_by_paper,
    )
    out: list[dict[str, Any]] = []
    for p in filtered:
        pid = int(p["id"])
        score = p.get("triage_score")
        out.append(
            {
                "paper_id": pid,
                "year": p.get("year"),
                "title": p.get("title") or "",
                "coverage": p.get("coverage") or "",
                "triage": effective_triage_tier(p),
                "relevance": int(score) if score is not None else None,
                "tags": tags_by_paper.get(pid, []),
                "pdf_path": p.get("pdf_path"),
            }
        )
    return out


def triage_filter_choices(base: Path, project_id: int) -> list[str]:
    del base, project_id
    return [
        TRIAGE_FILTER_ALL,
        TriageTier.MUST_READ.value,
        TriageTier.DATA_SOURCE.value,
        TriageTier.LOW_PRIORITY.value,
        "Not yet triaged",
    ]