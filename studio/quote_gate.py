from __future__ import annotations

import re
from typing import Optional

from studio.schema import MeasurementRow, SourceSection

_CITATION_BACKGROUND = re.compile(
    r"et\s+al\.?\s*\d+",
    re.IGNORECASE,
)
_CITATION_SECTION = re.compile(
    r"\b(background|cited|literature|reference)\b",
    re.IGNORECASE,
)


def collapse_quote_whitespace(quote: str) -> str:
    flattened = quote.replace("\r\n", "").replace("\r", "").replace("\n", "")
    return re.sub(r"[ \t]+", " ", flattened).strip()


def _format_number(value: float) -> list[str]:
    variants = []
    if value == int(value):
        variants.append(str(int(value)))
    variants.append(str(value))
    s = f"{value:g}"
    if s not in variants:
        variants.append(s)
    return variants


def numeric_measurements_on_row(row: MeasurementRow) -> list[float]:
    if row.metric_value is None:
        return []
    return [float(row.metric_value)]


def number_in_quote(value: float, quote: Optional[str]) -> bool:
    if not quote:
        return False
    text = collapse_quote_whitespace(quote)
    for variant in _format_number(value):
        if variant in text:
            return True
        err_pattern = re.escape(variant) + r"\s*[±]\s*[\d.]+"
        if re.search(err_pattern, text):
            return True
    pattern = re.escape(f"{value:g}")
    return re.search(pattern, text) is not None


def row_passes_quote_gate(row: MeasurementRow) -> bool:
    quote = row.verbatim_quote
    nums = numeric_measurements_on_row(row)
    if not nums:
        return False
    return all(number_in_quote(n, quote) for n in nums)


def is_background_citation_row(row: MeasurementRow) -> bool:
    quote = row.verbatim_quote or ""
    section = row.source_section.value if row.source_section else ""
    if _CITATION_BACKGROUND.search(quote):
        return True
    if section and _CITATION_SECTION.search(section):
        return True
    return False


def row_passes_source_gate(row: MeasurementRow) -> bool:
    if row.metric_value is None:
        return False
    if row.source_section == SourceSection.INTRODUCTION:
        return False
    if is_background_citation_row(row):
        return False
    return True


def row_passes_all_gates(row: MeasurementRow) -> bool:
    return row_passes_source_gate(row) and row_passes_quote_gate(row)


def filter_rows_gates(rows: list[MeasurementRow]) -> list[MeasurementRow]:
    return [r for r in rows if row_passes_all_gates(r)]


# Back-compat alias used by pdf_tables
def filter_rows_quote_gate(rows: list[MeasurementRow]) -> list[MeasurementRow]:
    return filter_rows_gates(rows)