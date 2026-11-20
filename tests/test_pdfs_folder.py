from pathlib import Path

from studio.pdfs_folder import (
    is_pdf_path_stored,
    list_folder_pdfs,
    stored_pdf_paths,
    title_from_pdf_filename,
)


def test_list_folder_pdfs_sorted(tmp_path: Path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "zebra.pdf").write_bytes(b"%PDF-1.4")
    (pdfs / "alpha.pdf").write_bytes(b"%PDF-1.4")
    assert list_folder_pdfs(pdfs) == ["alpha.pdf", "zebra.pdf"]


def test_is_pdf_path_stored_recognizes_linked_filename():
    paths = {"existing.pdf", "other.pdf"}
    assert is_pdf_path_stored("existing.pdf", paths)
    assert not is_pdf_path_stored("new-drop.pdf", paths)


def test_stored_pdf_paths_from_papers():
    papers = [
        {"id": 1, "pdf_path": "a.pdf"},
        {"id": 2, "pdf_path": None},
        {"id": 3, "pdf_path": "b.pdf"},
    ]
    assert stored_pdf_paths(papers) == {"a.pdf", "b.pdf"}


def test_title_from_pdf_filename():
    assert title_from_pdf_filename("my-paper copy.pdf") == "my-paper copy"