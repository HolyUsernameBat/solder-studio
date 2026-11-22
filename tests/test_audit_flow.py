from pathlib import Path

from studio.audit_flow import (
    NOT_YET_TRIAGED,
    QUEUE_ORDER_MUST_READ_FIRST,
    TAG_FILTER_ALL,
    TRIAGE_FILTER_ALL,
    active_research_question_display,
    apply_queue_paper_filters,
    eligible_queued_audit_paper_ids,
    filter_queue_by_relevance_gt_2,
    filter_queue_by_tag,
    filter_queue_by_triage,
    paper_ids_for_audit_all,
    paper_ids_for_selected_audit,
    parse_comma_separated_tags,
    queue_papers_for_display,
    research_question_select_label,
    sort_queue_papers,
)
from studio.schema import PaperCoverage, TriageTier


def test_select_label_full_question_radio_display_untruncated():
    long_q = (
        "In a copper joint made with a Sn-Ag-Cu solder, what does a bismuth addition "
        "do to the intermetallic thickness and to the strength under extended aging?"
    )
    label = research_question_select_label(3, long_q)
    full = active_research_question_display(long_q)
    assert full == long_q
    assert label == long_q
    assert len(full) > 80


def test_eligible_queued_audit_paper_ids_full_text_and_file(tmp_path: Path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "on_disk.pdf").write_bytes(b"%PDF-1.4")
    papers = [
        {
            "id": 1,
            "coverage": PaperCoverage.FULL_TEXT.value,
            "pdf_path": "on_disk.pdf",
        },
        {
            "id": 2,
            "coverage": PaperCoverage.FULL_TEXT.value,
            "pdf_path": "missing.pdf",
        },
        {
            "id": 3,
            "coverage": PaperCoverage.ABSTRACT_ONLY.value,
            "pdf_path": "on_disk.pdf",
        },
        {"id": 4, "coverage": PaperCoverage.FULL_TEXT.value, "pdf_path": None},
    ]
    assert eligible_queued_audit_paper_ids(papers, pdfs) == [1]


def test_paper_ids_for_selected_audit_honors_checkboxes():
    eligible = [10, 20, 30]
    assert paper_ids_for_selected_audit(eligible, {20, 99}) == [20]
    assert paper_ids_for_selected_audit(eligible, set()) == []
    assert paper_ids_for_audit_all(eligible) == [10, 20, 30]


def _sample_papers_for_filter() -> list[dict]:
    return [
        {
            "id": 1,
            "title": "Full on disk",
            "coverage": PaperCoverage.FULL_TEXT.value,
            "pdf_path": "on_disk.pdf",
        },
        {
            "id": 2,
            "title": "Abstract only",
            "coverage": PaperCoverage.ABSTRACT_ONLY.value,
            "pdf_path": None,
        },
        {
            "id": 3,
            "title": "Full missing file",
            "coverage": PaperCoverage.FULL_TEXT.value,
            "pdf_path": "missing.pdf",
        },
    ]


def test_queue_papers_for_display_hide_off_returns_all(tmp_path: Path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "on_disk.pdf").write_bytes(b"%PDF-1.4")
    papers = _sample_papers_for_filter()
    assert queue_papers_for_display(papers, pdfs, False) == papers


def test_queue_papers_for_display_hide_on_keeps_eligible_only(tmp_path: Path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "on_disk.pdf").write_bytes(b"%PDF-1.4")
    papers = _sample_papers_for_filter()
    visible = queue_papers_for_display(papers, pdfs, True)
    assert [int(p["id"]) for p in visible] == [1]


def test_parse_comma_separated_tags():
    assert parse_comma_separated_tags(" Bi, SAC ,,review") == ["Bi", "SAC", "review"]
    assert parse_comma_separated_tags("") == []
    assert parse_comma_separated_tags(" preserveCase ") == ["preserveCase"]


def _papers_for_triage_filters() -> list[dict]:
    return [
        {"id": 1, "triage_tier": TriageTier.MUST_READ.value, "triage_score": 5},
        {"id": 2, "triage_tier": TriageTier.DATA_SOURCE.value, "triage_score": 2},
        {"id": 3, "triage_tier": TriageTier.LOW_PRIORITY.value, "triage_score": 4},
        {"id": 4, "triage_tier": None, "triage_score": None},
        {"id": 5, "triage_tier": "", "triage_score": 3},
    ]


def test_filter_queue_by_triage():
    papers = _papers_for_triage_filters()
    assert [int(p["id"]) for p in filter_queue_by_triage(papers, TRIAGE_FILTER_ALL)] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert [int(p["id"]) for p in filter_queue_by_triage(papers, NOT_YET_TRIAGED)] == [4, 5]
    assert [
        int(p["id"])
        for p in filter_queue_by_triage(papers, TriageTier.MUST_READ.value)
    ] == [1]


def test_filter_queue_by_relevance_gt_2():
    papers = _papers_for_triage_filters()
    assert [int(p["id"]) for p in filter_queue_by_relevance_gt_2(papers, False)] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert [int(p["id"]) for p in filter_queue_by_relevance_gt_2(papers, True)] == [1, 3, 5]


def test_filter_queue_by_tag():
    papers = [{"id": 10}, {"id": 20}, {"id": 30}]
    tags = {10: ["Bi", "IMC"], 20: ["SAC"], 30: []}
    assert [int(p["id"]) for p in filter_queue_by_tag(papers, TAG_FILTER_ALL, tags)] == [
        10,
        20,
        30,
    ]
    assert [int(p["id"]) for p in filter_queue_by_tag(papers, "Bi", tags)] == [10]


def test_sort_queue_must_read_first_stable_within_tier():
    papers = [
        {"id": 1, "triage_tier": TriageTier.LOW_PRIORITY.value},
        {"id": 2, "triage_tier": TriageTier.MUST_READ.value},
        {"id": 3, "triage_tier": None},
        {"id": 4, "triage_tier": TriageTier.MUST_READ.value},
        {"id": 5, "triage_tier": TriageTier.DATA_SOURCE.value},
    ]
    ordered = sort_queue_papers(papers, QUEUE_ORDER_MUST_READ_FIRST)
    assert [int(p["id"]) for p in ordered] == [2, 4, 5, 1, 3]


def test_apply_queue_paper_filters_compose(tmp_path: Path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    papers = _papers_for_triage_filters()
    tags = {3: ["focus"], 5: ["focus"]}
    out = apply_queue_paper_filters(
        papers,
        triage_filter=TriageTier.LOW_PRIORITY.value,
        only_relevance_gt_2=True,
        order=QUEUE_ORDER_MUST_READ_FIRST,
        tag_filter="focus",
        tags_by_paper_id=tags,
    )
    assert [int(p["id"]) for p in out] == [3]