from __future__ import annotations

import re
from pathlib import Path

_WINDOWS_ILLEGAL = re.compile(r'[<>:"/\\|?*]')


def sanitize_windows_filename(name: str) -> str:
    """Keep the uploaded basename; replace only illegal Windows path characters."""
    base = Path(name).name
    cleaned = _WINDOWS_ILLEGAL.sub("-", base)
    cleaned = cleaned.rstrip(". ").strip()
    return cleaned or "upload.pdf"


def unique_pdf_dest(pdfs_dir: Path, filename: str) -> Path:
    """Return a path under ``pdfs_dir`` that does not exist; suffix ``-2``, ``-3``, … on collision."""
    dest = pdfs_dir / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".pdf"
    n = 2
    while True:
        candidate = pdfs_dir / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


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