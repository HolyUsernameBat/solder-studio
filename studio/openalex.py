from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

from studio.schema import PaperAudit, PaperCoverage

OPENALEX_WORKS = "https://api.openalex.org/works"


@dataclass
class SearchHit:
    paper: PaperAudit
    raw: dict[str, Any]


def build_user_agent() -> str:
    return "SolderStudio/0.1"


def pdf_urls_from_locations(locations: list[dict[str, Any]]) -> list[str]:
    """Collect pdf_url values from OpenAlex locations; ignore landing pages without pdf_url."""
    urls: list[str] = []
    seen: set[str] = set()
    for loc in locations or []:
        pdf_url = loc.get("pdf_url")
        if not pdf_url:
            continue
        if pdf_url in seen:
            continue
        seen.add(pdf_url)
        urls.append(pdf_url)
    return urls


def work_pdf_locations(work: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge ``locations`` with ``best_oa_location`` and ``primary_location``."""
    locations: list[dict[str, Any]] = list(work.get("locations") or [])
    seen_ids: set[int] = {id(loc) for loc in locations}
    for key in ("primary_location", "best_oa_location"):
        loc = work.get(key)
        if not loc:
            continue
        if id(loc) in seen_ids:
            continue
        locations.append(loc)
        seen_ids.add(id(loc))
    return locations


def is_pdf_body(content: bytes) -> bool:
    return content[:4] == b"%PDF"


def download_pdf_candidate(
    url: str,
    session: Optional[requests.Session] = None,
    timeout: int = 60,
) -> Optional[bytes]:
    sess = session or requests.Session()
    headers = {"User-Agent": build_user_agent()}
    resp = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    body = resp.content
    if not is_pdf_body(body):
        return None
    return body


def save_pdf(body: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)


def _authors_string(authorships: list[dict]) -> str:
    names = []
    for a in authorships or []:
        author = a.get("author") or {}
        name = author.get("display_name")
        if name:
            names.append(name)
    return "; ".join(names)


def work_to_paper(work: dict[str, Any], pdf_path: Optional[str], coverage: PaperCoverage) -> PaperAudit:
    year = work.get("publication_year")
    doi = None
    for ident in work.get("ids") or {}:
        if ident == "doi":
            doi = work["ids"]["doi"]
            break
    if doi is None and work.get("doi"):
        doi = work["doi"]
    return PaperAudit(
        openalex_id=work.get("id"),
        title=work.get("title") or work.get("display_name") or "Untitled",
        authors=_authors_string(work.get("authorships") or []),
        year=year,
        abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
        doi=doi,
        pdf_path=pdf_path,
        coverage=coverage,
    )


def _reconstruct_abstract(inverted_index: Optional[dict]) -> Optional[str]:
    if not inverted_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort()
    return " ".join(w for _, w in positions)


def search_openalex(
    query: str,
    per_page: int = 10,
    session: Optional[requests.Session] = None,
) -> list[SearchHit]:
    sess = session or requests.Session()
    headers = {"User-Agent": build_user_agent()}
    params = {"search": query, "per_page": per_page}
    resp = sess.get(OPENALEX_WORKS, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    hits: list[SearchHit] = []
    for work in data.get("results") or []:
        paper = work_to_paper(work, pdf_path=None, coverage=PaperCoverage.ABSTRACT_ONLY)
        hits.append(SearchHit(paper=paper, raw=work))
    return hits


def try_fetch_pdf_for_work(
    work: dict[str, Any],
    pdfs_dir: Path,
    session: Optional[requests.Session] = None,
) -> tuple[Optional[str], PaperCoverage]:
    locations = work_pdf_locations(work)
    urls = pdf_urls_from_locations(locations)
    openalex_id = work.get("id") or "unknown"
    safe_id = openalex_id.rsplit("/", 1)[-1].replace("/", "_")
    for url in urls:
        try:
            body = download_pdf_candidate(url, session=session)
        except requests.RequestException:
            continue
        if body is None:
            continue
        dest = pdfs_dir / f"{safe_id}.pdf"
        save_pdf(body, dest)
        return str(dest.name), PaperCoverage.FULL_TEXT
    return None, PaperCoverage.ABSTRACT_ONLY