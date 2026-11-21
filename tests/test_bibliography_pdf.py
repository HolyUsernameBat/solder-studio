from pathlib import Path

from studio.openalex import bibliography_pdf_filename, try_fetch_pdf_for_work
from studio.pdfs_folder import unique_pdf_dest


def _fake_work() -> dict:
    return {
        "id": "https://openalex.org/W2951296256",
        "display_name": "The role of intermetallic compounds in controlling the properties of solder joints",
        "authorships": [
            {"author": {"display_name": "Liu Chen"}},
        ],
        "locations": [
            {"pdf_url": "https://example.org/paper.pdf"},
        ],
    }


def test_bibliography_pdf_filename_shape():
    name = bibliography_pdf_filename(_fake_work())
    assert name.startswith("Chen_")
    assert name.endswith(".pdf")
    assert "role-of-intermetallic" in name.lower() or "The-role" in name


def test_bibliography_pdf_filename_liu_et_al_uses_first_token():
    work = {
        "display_name": "Growth kinetics",
        "authorships": [{"author": {"display_name": "Liu et al"}}],
    }
    assert bibliography_pdf_filename(work) == "Liu_Growth-kinetics.pdf"


def test_bibliography_pdf_filename_liu_et_al_dot_uses_first_token():
    work = {
        "display_name": "IMC growth",
        "authorships": [{"author": {"display_name": "Liu et al."}}],
    }
    assert bibliography_pdf_filename(work) == "Liu_IMC-growth.pdf"


def test_unique_pdf_dest_collision_suffix(tmp_path: Path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    first = unique_pdf_dest(pdfs, "Chen-The-role-of-intermetallic.pdf")
    first.write_bytes(b"%PDF-1.4")
    second = unique_pdf_dest(pdfs, "Chen-The-role-of-intermetallic.pdf")
    assert second.name == "Chen-The-role-of-intermetallic-2.pdf"
    second.write_bytes(b"%PDF-1.4")
    third = unique_pdf_dest(pdfs, "Chen-The-role-of-intermetallic.pdf")
    assert third.name == "Chen-The-role-of-intermetallic-3.pdf"


def test_try_fetch_pdf_uses_bibliography_name_not_work_id(tmp_path: Path, monkeypatch):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    work = _fake_work()

    def fake_download(url, session=None, timeout=60):
        return b"%PDF-1.4\nfake"

    import studio.openalex as oa

    monkeypatch.setattr(oa, "download_pdf_candidate", fake_download)

    name, coverage = try_fetch_pdf_for_work(work, pdfs)
    assert name is not None
    assert not name.startswith("W2951296256")
    assert name.startswith("Chen_")
    assert (pdfs / name).is_file()