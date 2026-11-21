from pathlib import Path

from studio.pdfs_folder import sanitize_windows_filename, unique_pdf_dest


def test_sanitize_windows_filename_keeps_basename():
    assert sanitize_windows_filename(r"foo\bar:illegal?.pdf") == "bar-illegal-.pdf"


def test_existing_pdf_paths_not_renamed_by_unique_dest(tmp_path: Path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    legacy = pdfs / "W2951296256-the-role-of-intermetallic-compounds-in-controlling-the.pdf"
    legacy.write_bytes(b"%PDF-existing")
    new_path = unique_pdf_dest(pdfs, "Chen-New-download.pdf")
    new_path.write_bytes(b"%PDF-new")
    assert legacy.read_bytes() == b"%PDF-existing"
    assert legacy.name == "W2951296256-the-role-of-intermetallic-compounds-in-controlling-the.pdf"