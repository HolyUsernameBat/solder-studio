from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

import pdfplumber

from studio.codex_backend import CODEX_MODEL_EXTRACT, complete_structured
from studio.quote_gate import filter_rows_gates
from studio.schema import ExtractionList, MeasurementRow

KEYWORDS = (
    "thickness",
    "shear",
    "aging",
    "imc",
    "alloy",
    "mpa",
    "tensile",
    "bismuth",
    "solder",
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
    with pdfplumber.open(pdf_path) as pdf:
        indices = select_page_indices(pdf)
        if not indices:
            all_text = " ".join(
                (p.extract_text() or "") for p in pdf.pages[: min(3, len(pdf.pages))]
            )
            if not all_text.strip():
                return "", "Scanned or empty PDF: no extractable text."
            return all_text[:8000], None

        labeled = tables_as_labeled_text(pdf, indices)
        if not labeled.strip():
            return "", "Scanned or empty PDF: keyword pages have no table or text."
        return labeled, None


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


def _extraction_system(target_metrics: list[str]) -> str:
    metrics_line = ", ".join(target_metrics) if target_metrics else "(none specified)"
    return f"""You extract primary quantitative measurement rows from metallurgy paper text.
Prioritize target metrics: {metrics_line}. You may also capture other primary experimental numbers.
Each row needs: material_system, composition_or_variant, processing_or_aging_condition,
phase_or_microstructure, metric_name, metric_value (number), metric_unit (e.g. um, MPa, N, gf, %),
sample_size, source_section (Results, Table, Figure, Abstract — never use Introduction for new data),
source_page, verbatim_quote copied exactly from the source including every number on the row.
Never extract numbers from Introduction background citations (e.g. Liu et al.13)."""


def build_extraction_user_prompt(
    table_text: str, paper_title: str, research_question: str
) -> str:
    return f"""Paper: {paper_title}
Research context: {research_question}

Table and page text:
{table_text}

Extract all primary measurement rows you can support from this text only."""


def parse_extraction_response(content: str) -> list[MeasurementRow]:
    data = json.loads(content)
    if isinstance(data, dict) and "rows" in data:
        raw_rows = data["rows"]
    elif isinstance(data, list):
        raw_rows = data
    else:
        raw_rows = []
    return [MeasurementRow.model_validate(r) for r in raw_rows]


def extract_rows_from_pdf_with_model(
    pdf_path: Path,
    paper_title: str,
    *,
    research_question: str,
    target_metrics: list[str],
    on_status: Callable[[str], None] | None = None,
    model: str | None = None,
) -> tuple[list[MeasurementRow], Optional[str]]:
    table_text, err = audit_pdf_text(pdf_path)
    if err:
        return [], err

    capped = cap_labeled_text_for_codex(table_text)
    parsed = complete_structured(
        ExtractionList,
        _extraction_system(target_metrics),
        build_extraction_user_prompt(capped, paper_title, research_question),
        on_status=on_status,
        model=model or CODEX_MODEL_EXTRACT,
    )
    if not isinstance(parsed, ExtractionList):
        return [], "Model returned no parsed extraction."
    return filter_rows_gates(list(parsed.rows)), None