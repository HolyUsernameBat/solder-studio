from __future__ import annotations

from pathlib import Path
from collections.abc import Callable, Sequence
from typing import Optional

from studio import db
from studio.pdf_tables import audit_pdf_text, extract_rows_from_pdf_with_model
from studio.schema import PaperCoverage, TriageTier
from studio.triage import run_triage

NOT_YET_TRIAGED = "Not yet triaged"

TRIAGE_FILTER_ALL = "All"
QUEUE_ORDER_LIBRARY = "Library order"
QUEUE_ORDER_MUST_READ_FIRST = "Must Read first"
TAG_FILTER_ALL = "All tags"

_TRIAGE_SORT_RANK: dict[str, int] = {
    TriageTier.MUST_READ.value: 0,
    TriageTier.DATA_SOURCE.value: 1,
    TriageTier.LOW_PRIORITY.value: 2,
    NOT_YET_TRIAGED: 3,
}

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


def queue_papers_for_display(
    papers: Sequence[dict], pdfs_dir: Path, hide_abstract_only: bool
) -> list[dict]:
    """Papers shown in the paper queue table (hide-abstract-only step only)."""
    if not hide_abstract_only:
        return list(papers)
    eligible = set(eligible_queued_audit_paper_ids(papers, pdfs_dir))
    return [p for p in papers if int(p["id"]) in eligible]


def parse_comma_separated_tags(text: str) -> list[str]:
    """Split comma-separated tags; strip; drop empties; preserve case."""
    return [part.strip() for part in (text or "").split(",") if part.strip()]


def effective_triage_tier(paper: dict) -> str:
    tier = paper.get("triage_tier")
    if tier is None or str(tier).strip() == "":
        return NOT_YET_TRIAGED
    return str(tier)


def _paper_relevance_score(paper: dict) -> Optional[int]:
    val = paper.get("triage_score")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def filter_queue_by_triage(
    papers: Sequence[dict], triage_filter: str
) -> list[dict]:
    if triage_filter == TRIAGE_FILTER_ALL:
        return list(papers)
    if triage_filter == NOT_YET_TRIAGED:
        return [p for p in papers if effective_triage_tier(p) == NOT_YET_TRIAGED]
    return [p for p in papers if p.get("triage_tier") == triage_filter]


def filter_queue_by_relevance_gt_2(
    papers: Sequence[dict], only_gt_2: bool
) -> list[dict]:
    if not only_gt_2:
        return list(papers)
    out: list[dict] = []
    for p in papers:
        score = _paper_relevance_score(p)
        if score is not None and score > 2:
            out.append(p)
    return out


def filter_queue_by_tag(
    papers: Sequence[dict],
    tag_filter: str,
    tags_by_paper_id: dict[int, list[str]],
) -> list[dict]:
    if tag_filter == TAG_FILTER_ALL:
        return list(papers)
    out: list[dict] = []
    for p in papers:
        pid = int(p["id"])
        if tag_filter in tags_by_paper_id.get(pid, []):
            out.append(p)
    return out


def sort_queue_papers(papers: Sequence[dict], order: str) -> list[dict]:
    if order != QUEUE_ORDER_MUST_READ_FIRST:
        return list(papers)
    indexed = list(enumerate(papers))

    def rank(p: dict) -> int:
        tier = effective_triage_tier(p)
        return _TRIAGE_SORT_RANK.get(tier, _TRIAGE_SORT_RANK[NOT_YET_TRIAGED])

    indexed.sort(key=lambda pair: (rank(pair[1]), pair[0]))
    return [p for _, p in indexed]


def apply_queue_paper_filters(
    papers: Sequence[dict],
    *,
    triage_filter: str = TRIAGE_FILTER_ALL,
    only_relevance_gt_2: bool = False,
    order: str = QUEUE_ORDER_LIBRARY,
    tag_filter: str = TAG_FILTER_ALL,
    tags_by_paper_id: dict[int, list[str]] | None = None,
) -> list[dict]:
    """Triage, relevance, tag filters and optional tier sort after hide-abstract-only."""
    tags_map = tags_by_paper_id or {}
    step = filter_queue_by_triage(papers, triage_filter)
    step = filter_queue_by_relevance_gt_2(step, only_relevance_gt_2)
    step = filter_queue_by_tag(step, tag_filter, tags_map)
    return sort_queue_papers(step, order)


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
    extract_model: str | None = None,
) -> tuple[int, Optional[str], Optional[str]]:
    """
    Delete prior measurements for paper, extract quote-verified rows, then structured triage.

    Returns (rows_stored, extract_warning, triage_warning).
    """
    model = extract_model
    db.delete_measurements_for_paper(base, paper_id, question_id)
    rows, err = extract_rows_from_pdf_with_model(
        pdf_path,
        paper_title,
        research_question=research_question,
        target_metrics=target_metrics,
        on_status=on_status,
        model=model,
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
                model=model,
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