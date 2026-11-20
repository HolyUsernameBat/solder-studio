from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

import pdfplumber

from studio.codex_backend import complete_structured
from studio.quote_gate import filter_rows_quote_gate
from studio.schema import ExtractionList, SolderRow

KEYWORDS = (
    "thickness",
    "shear",
    "aging",
    "imc",
    "alloy",
)


def page_matches_keywords(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in KEYWORDS)


def select_page_indices(pdf: pdfplumber.PDF) -> list[int]:
    indices: list[int] = []
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if page_matches_keywords(text):
            indices.append(i)
    return indices


def page_extraction_block(page: pdfplumber.PDFPage, page_num: int) -> str:
    page_text = (page.extract_text() or "").strip()
    tables = page.extract_tables() or []
    parts = [f"--- Page {page_num} ---", "Page text (captions and body):", page_text]
    if tables:
        parts.append("\nTables on this page:")
        for ti, table in enumerate(tables):
            rows_text = []
            for row in table:
                cells = [str(c) if c is not None else "" for c in row]
                rows_text.append(" | ".join(cells))
            parts.append(f"Table {ti + 1}:\n" + "\n".join(rows_text))
    return "\n\n".join(parts)


def tables_as_labeled_text(pdf: pdfplumber.PDF, page_indices: list[int]) -> str:
    blocks: list[str] = []
    for i in page_indices:
        blocks.append(page_extraction_block(pdf.pages[i], i + 1))
    return "\n\n".join(blocks)


def audit_pdf_text(pdf_path: Path) -> tuple[str, Optional[str]]:
    """Return (table_text, error_message). error_message set when no usable text."""
    with pdfplumber.open(pdf_path) as pdf:
        indices = select_page_indices(pdf)
        if not indices:
            all_text = " ".join(
                (p.extract_text() or "") for p in pdf.pages[: min(3, len(pdf.pages))]
            )
            if not all_text.strip():
                return "", "Scanned or empty PDF: no extractable text."
            return "", "No keyword-matching pages found for extraction."

        labeled = tables_as_labeled_text(pdf, indices)
        if not labeled.strip():
            return "", "Scanned or empty PDF: keyword pages have no table or text."
        return labeled, None


EXTRACTION_SYSTEM = """You extract solder joint measurement rows from table text.
Return only facts present in the text. Use null for missing fields.
aging_type must be one of: as-reflowed, isothermal, thermal cycling, unspecified.
imc_phase must be one of: Cu6Sn5, Cu3Sn, mixed, unspecified.
shear_unit must be one of: MPa, N, gf, unspecified. Do not guess the unit when the paper is silent.
Each row needs a verbatim_quote copied from the source text that includes every number you set on that row.
"""


PDF_TEXT_CODEX_MAX_CHARS = 12000
PDF_TEXT_OMITTED_LINE = "The rest of the pages were omitted."


def cap_labeled_text_for_codex(text: str, max_chars: int = PDF_TEXT_CODEX_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    suffix = f"\n\n{PDF_TEXT_OMITTED_LINE}"
    cut_at = max_chars - len(suffix)
    if cut_at < 1:
        return text[:max_chars]
    return text[:cut_at].rstrip() + suffix


def build_extraction_user_prompt(table_text: str, paper_title: str) -> str:
    return f"""Paper: {paper_title}

Table and page text:
{table_text}

Extract all solder measurement rows you can support from this text only."""


def parse_extraction_response(content: str) -> list[SolderRow]:
    data = json.loads(content)
    if isinstance(data, dict) and "rows" in data:
        raw_rows = data["rows"]
    elif isinstance(data, list):
        raw_rows = data
    else:
        raw_rows = []
    return [SolderRow.model_validate(r) for r in raw_rows]


def extract_rows_from_pdf_with_model(
    pdf_path: Path,
    paper_title: str,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[SolderRow], Optional[str]]:
    table_text, err = audit_pdf_text(pdf_path)
    if err:
        return [], err

    capped = cap_labeled_text_for_codex(table_text)
    parsed = complete_structured(
        ExtractionList,
        EXTRACTION_SYSTEM,
        build_extraction_user_prompt(capped, paper_title),
        on_status=on_status,
    )
    if not isinstance(parsed, ExtractionList):
        return [], "Model returned no parsed extraction."
    return filter_rows_quote_gate(list(parsed.rows)), None