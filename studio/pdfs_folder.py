from __future__ import annotations

from pathlib import Path


def list_folder_pdfs(pdfs_dir: Path) -> list[str]:
    """Return sorted basenames of every ``*.pdf`` in ``pdfs_dir``."""
    if not pdfs_dir.is_dir():
        return []
    return sorted(p.name for p in pdfs_dir.glob("*.pdf") if p.is_file())


def title_from_pdf_filename(filename: str) -> str:
    return Path(filename).stem


def is_pdf_path_stored(pdf_filename: str, stored_pdf_paths: set[str]) -> bool:
    """True when ``pdf_filename`` is already a ``papers.pdf_path`` value."""
    return pdf_filename in stored_pdf_paths


def stored_pdf_paths(papers: list[dict]) -> set[str]:
    paths: set[str] = set()
    for p in papers:
        path = p.get("pdf_path")
        if path:
            paths.add(path)
    return paths


def paper_for_pdf_path(papers: list[dict], pdf_filename: str) -> dict | None:
    for p in papers:
        if p.get("pdf_path") == pdf_filename:
            return p
    return None