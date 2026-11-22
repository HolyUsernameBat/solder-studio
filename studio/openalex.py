from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

from studio.pdfs_folder import unique_pdf_dest

from studio.schema import PaperAudit, PaperCoverage

OPENALEX_WORKS = "https://api.openalex.org/works"
DEFAULT_OPENALEX_QUERY = "solder IMC shear aging SAC305 bismuth"


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


_ARXIV_URL_PREFIX = re.compile(
    r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/",
    re.IGNORECASE,
)
_PMCID_RE = re.compile(r"(PMC\d+)", re.IGNORECASE)


def normalize_arxiv_id(raw: str) -> Optional[str]:
    """Strip OpenAlex-style arXiv URLs/prefixes to an id suitable for arxiv.org/pdf/."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    s = _ARXIV_URL_PREFIX.sub("", s)
    if s.lower().startswith("arxiv:"):
        s = s[6:]
    s = s.strip().strip("/")
    return s or None


def arxiv_ids_on_work(work: dict[str, Any]) -> list[str]:
    ids = work.get("ids") or {}
    found: list[str] = []
    seen: set[str] = set()
    arxiv_val = ids.get("arxiv")
    if isinstance(arxiv_val, str) and arxiv_val.strip():
        found.append(arxiv_val)
        seen.add(arxiv_val)
    for key, val in ids.items():
        if not isinstance(val, str) or not val.strip():
            continue
        if key == "arxiv":
            continue
        if "arxiv" in key.lower() or "arxiv" in val.lower():
            if val not in seen:
                seen.add(val)
                found.append(val)
    return found


def arxiv_pdf_url_for_work(work: dict[str, Any]) -> Optional[str]:
    for raw in arxiv_ids_on_work(work):
        aid = normalize_arxiv_id(raw)
        if aid:
            return f"https://arxiv.org/pdf/{aid}"
    return None


def normalize_pmcid(raw: str) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    match = _PMCID_RE.search(raw.strip())
    if not match:
        return None
    return match.group(1).upper()


def pmc_pdf_url_for_work(work: dict[str, Any]) -> Optional[str]:
    ids = work.get("ids") or {}
    for key in ("pmcid", "pmc"):
        val = ids.get(key)
        if isinstance(val, str):
            pmcid = normalize_pmcid(val)
            if pmcid:
                return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
    for val in ids.values():
        if isinstance(val, str):
            pmcid = normalize_pmcid(val)
            if pmcid:
                return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
    return None


def pdf_candidate_urls(work: dict[str, Any]) -> list[str]:
    """Ordered, deduplicated PDF download candidates from unauthenticated work JSON."""
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: Optional[str]) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        urls.append(url)

    for url in pdf_urls_from_locations(work_pdf_locations(work)):
        add(url)

    oa = work.get("open_access") or {}
    oa_url = oa.get("oa_url") if isinstance(oa, dict) else None
    if isinstance(oa_url, str):
        add(oa_url.strip() or None)

    add(arxiv_pdf_url_for_work(work))
    add(pmc_pdf_url_for_work(work))
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


def _ascii_letters_digits(token: str) -> str:
    normalized = unicodedata.normalize("NFKD", token)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "", ascii_text)


def _display_name_ends_with_et_al(tokens: list[str]) -> bool:
    if len(tokens) < 2:
        return False
    if tokens[-2].lower() != "et":
        return False
    return tokens[-1].lower().rstrip(".") == "al"


def first_author_family_name(work: dict[str, Any]) -> str:
    authorships = work.get("authorships") or []
    if not authorships:
        return "Unknown"
    author = (authorships[0].get("author") or {})
    display_name = (author.get("display_name") or "").strip()
    if not display_name:
        return "Unknown"
    tokens = display_name.split()
    if _display_name_ends_with_et_al(tokens) and len(tokens) >= 3:
        family_token = tokens[0]
    else:
        family_token = tokens[-1]
    safe = _ascii_letters_digits(family_token)
    return safe or "Unknown"


def title_slug_for_pdf(work: dict[str, Any], *, max_chars: int = 60) -> str:
    raw = (work.get("display_name") or work.get("title") or "Untitled").strip()
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", ascii_text)
    if not words:
        return "Untitled"
    parts: list[str] = []
    length = 0
    for word in words:
        add = len(word) if not parts else len(word) + 1
        if length + add > max_chars and parts:
            break
        parts.append(word)
        length += add
    slug = "-".join(parts)
    if len(slug) > max_chars:
        slug = slug[:max_chars].rstrip("-")
    return slug or "Untitled"


def bibliography_pdf_filename(work: dict[str, Any]) -> str:
    family = first_author_family_name(work)
    slug = title_slug_for_pdf(work)
    return f"{family}_{slug}.pdf"


def search_openalex(
    query: str,
    per_page: int = 10,
    session: Optional[requests.Session] = None,
) -> list[SearchHit]:
    if not (query or "").strip():
        raise ValueError("OpenAlex search query must not be blank.")
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
    urls = pdf_candidate_urls(work)
    for url in urls:
        try:
            body = download_pdf_candidate(url, session=session)
        except requests.RequestException:
            continue
        if body is None:
            continue
        dest = unique_pdf_dest(pdfs_dir, bibliography_pdf_filename(work))
        save_pdf(body, dest)
        return str(dest.name), PaperCoverage.FULL_TEXT
    return None, PaperCoverage.ABSTRACT_ONLY