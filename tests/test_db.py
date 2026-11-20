from pathlib import Path

import pytest

from studio import db
from studio.schema import PaperAudit, PaperCoverage


@pytest.fixture
def db_root(tmp_path: Path) -> Path:
    db.init_db(tmp_path)
    return tmp_path


def test_upsert_openalex_id_does_not_duplicate(db_root: Path):
    paper = PaperAudit(
        openalex_id="https://openalex.org/W123",
        title="First title",
        year=2020,
        abstract="alpha",
        coverage=PaperCoverage.ABSTRACT_ONLY,
    )
    id1 = db.upsert_paper(db_root, paper)
    paper2 = PaperAudit(
        openalex_id="https://openalex.org/W123",
        title="Updated title",
        year=2021,
        abstract="beta",
        pdf_path="W123.pdf",
        coverage=PaperCoverage.FULL_TEXT,
    )
    id2 = db.upsert_paper(db_root, paper2, pdf_kept=True)
    assert id1 == id2
    papers = db.list_papers(db_root)
    assert len(papers) == 1
    row = papers[0]
    assert row["title"] == "Updated title"
    assert row["year"] == 2021
    assert row["abstract"] == "beta"
    assert row["pdf_path"] == "W123.pdf"
    assert row["coverage"] == PaperCoverage.FULL_TEXT.value


def test_upsert_without_pdf_kept_preserves_existing_pdf(db_root: Path):
    paper = PaperAudit(
        openalex_id="https://openalex.org/W456",
        title="With PDF",
        pdf_path="saved.pdf",
        coverage=PaperCoverage.FULL_TEXT,
    )
    pid = db.insert_paper(db_root, paper)
    refresh = PaperAudit(
        openalex_id="https://openalex.org/W456",
        title="Refreshed title",
        year=2022,
        abstract="new abstract",
        coverage=PaperCoverage.ABSTRACT_ONLY,
    )
    db.upsert_paper(db_root, refresh, pdf_kept=False)
    row = db.get_paper(db_root, pid)
    assert row is not None
    assert row["title"] == "Refreshed title"
    assert row["pdf_path"] == "saved.pdf"
    assert row["coverage"] == PaperCoverage.FULL_TEXT.value