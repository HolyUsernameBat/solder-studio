from unittest.mock import MagicMock

import pytest

from studio.openalex import (
    build_user_agent,
    download_pdf_candidate,
    is_pdf_body,
    pdf_urls_from_locations,
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