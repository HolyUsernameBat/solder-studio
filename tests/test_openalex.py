from unittest.mock import MagicMock

import pytest

from studio.openalex import (
    arxiv_pdf_url_for_work,
    build_user_agent,
    download_pdf_candidate,
    is_pdf_body,
    normalize_arxiv_id,
    normalize_pmcid,
    pdf_candidate_urls,
    pdf_urls_from_locations,
    pmc_pdf_url_for_work,
    search_openalex,
    try_fetch_pdf_for_work,
    work_pdf_locations,
)


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_search_openalex_blank_query_does_not_hit_network(blank: str):
    session = MagicMock()
    with pytest.raises(ValueError, match="must not be blank"):
        search_openalex(blank, session=session)
    session.get.assert_not_called()


def test_user_agent_is_solder_studio_without_email():
    assert build_user_agent() == "SolderStudio/0.1"
    assert "contact_email" not in search_openalex.__code__.co_varnames
    assert "contact_email" not in download_pdf_candidate.__code__.co_varnames
    assert "contact_email" not in try_fetch_pdf_for_work.__code__.co_varnames


def test_pdf_urls_from_locations_uses_pdf_url_only():
    locations = [
        {"landing_page_url": "https://publisher.example/article/123", "pdf_url": None},
        {"pdf_url": "https://oa.example/paper.pdf", "is_oa": True},
        {"pdf_url": "https://mirror.example/paper.pdf"},
    ]
    urls = pdf_urls_from_locations(locations)
    assert urls == [
        "https://oa.example/paper.pdf",
        "https://mirror.example/paper.pdf",
    ]
    assert "https://publisher.example/article/123" not in urls


def test_is_pdf_body_accepts_pdf_header():
    assert is_pdf_body(b"%PDF-1.4\n%...")


def test_is_pdf_body_rejects_html():
    assert not is_pdf_body(b"<!DOCTYPE html><html>")


def test_work_pdf_locations_includes_primary_and_best_oa():
    primary = {"pdf_url": "https://publisher.example/full.pdf"}
    best_oa = {"pdf_url": "https://oa.example/mirror.pdf"}
    work = {
        "locations": [],
        "primary_location": primary,
        "best_oa_location": best_oa,
    }
    urls = pdf_urls_from_locations(work_pdf_locations(work))
    assert urls == [
        "https://publisher.example/full.pdf",
        "https://oa.example/mirror.pdf",
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2301.01234", "2301.01234"),
        ("https://arxiv.org/abs/2301.01234", "2301.01234"),
        ("https://arxiv.org/pdf/2301.01234", "2301.01234"),
        ("arxiv:2301.01234v2", "2301.01234v2"),
        ("https://arxiv.org/abs/1706.03762v5", "1706.03762v5"),
    ],
)
def test_normalize_arxiv_id(raw: str, expected: str):
    assert normalize_arxiv_id(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PMC1234567", "PMC1234567"),
        ("pmc1234567", "PMC1234567"),
        ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9876543/", "PMC9876543"),
    ],
)
def test_normalize_pmcid(raw: str, expected: str):
    assert normalize_pmcid(raw) == expected


def test_pdf_candidate_urls_order_oa_arxiv_pmc():
    work = {
        "locations": [{"pdf_url": "https://loc.example/a.pdf"}],
        "primary_location": {"pdf_url": "https://loc.example/a.pdf"},
        "open_access": {"oa_url": "https://oa.example/landing"},
        "ids": {
            "arxiv": "https://arxiv.org/abs/2301.01234",
            "pmcid": "PMC555",
        },
    }
    assert pdf_candidate_urls(work) == [
        "https://loc.example/a.pdf",
        "https://oa.example/landing",
        "https://arxiv.org/pdf/2301.01234",
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC555/pdf/",
    ]


def test_arxiv_and_pmc_url_helpers():
    work = {
        "ids": {
            "arxiv": "https://arxiv.org/abs/1801.00001v3",
            "pmcid": "pmc42",
        }
    }
    assert arxiv_pdf_url_for_work(work) == "https://arxiv.org/pdf/1801.00001v3"
    assert pmc_pdf_url_for_work(work) == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC42/pdf/"


def test_try_fetch_pdf_skips_non_pdf_tries_next_url(tmp_path, monkeypatch):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    work = {
        "display_name": "Second wins",
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "locations": [{"pdf_url": "https://bad.example/html"}],
        "open_access": {"oa_url": "https://oa.example/good.pdf"},
    }
    calls: list[str] = []

    def fake_download(url, session=None, timeout=60):
        calls.append(url)
        if url == "https://bad.example/html":
            return None
        if url == "https://oa.example/good.pdf":
            return b"%PDF-1.7\nok"
        return None

    import studio.openalex as oa

    monkeypatch.setattr(oa, "download_pdf_candidate", fake_download)

    name, coverage = try_fetch_pdf_for_work(work, pdfs)
    assert calls == ["https://bad.example/html", "https://oa.example/good.pdf"]
    assert name is not None
    assert name.startswith("Lovelace_")
    assert (pdfs / name).read_bytes().startswith(b"%PDF")