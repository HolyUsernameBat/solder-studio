from pathlib import Path

from studio.audit_flow import (
    active_research_question_display,
    eligible_queued_audit_paper_ids,
    paper_ids_for_audit_all,
    paper_ids_for_selected_audit,
    research_question_select_label,
)
from studio.schema import PaperCoverage


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