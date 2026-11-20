from __future__ import annotations

import re
from typing import Optional

from studio.schema import SolderRow

_NUMERIC_FIELDS = (
    "addition_weight_percent",
    "reflow_temp_c",
    "imc_thickness_um",
    "shear_value",
    "uts_mpa",
    "elongation_percent",
)


def collapse_quote_whitespace(quote: str) -> str:
    """Remove newlines, then collapse remaining whitespace before matching."""
    flattened = quote.replace("\r\n", "").replace("\r", "").replace("\n", "")
    return re.sub(r"[ \t]+", " ", flattened).strip()


def _format_number(value: float) -> list[str]:
    """Variants that might appear in a quote."""
    variants = []
    if value == int(value):
        variants.append(str(int(value)))
    variants.append(str(value))
    s = f"{value:g}"
    if s not in variants:
        variants.append(s)
    return variants


def numeric_measurements_on_row(row: SolderRow) -> list[float]:
    values: list[float] = []
    for field in _NUMERIC_FIELDS:
        v = getattr(row, field)
        if v is not None:
            values.append(float(v))
    return values


def number_in_quote(value: float, quote: Optional[str]) -> bool:
    if not quote:
        return False
    text = collapse_quote_whitespace(quote)
    for variant in _format_number(value):
        if variant in text:
            return True
        # Match center value inside an error bar, e.g. 42.3 ± 3.1
        err_pattern = re.escape(variant) + r"\s*[±]\s*[\d.]+"
        if re.search(err_pattern, text):
            return True
    return _fuzzy_number_in_quote(value, text)


def _fuzzy_number_in_quote(value: float, quote: str) -> bool:
    pattern = re.escape(f"{value:g}")
    return re.search(pattern, quote) is not None


def row_passes_quote_gate(row: SolderRow) -> bool:
    quote = row.verbatim_quote
    nums = numeric_measurements_on_row(row)
    if not nums:
        return False
    return all(number_in_quote(n, quote) for n in nums)


def filter_rows_quote_gate(rows: list[SolderRow]) -> list[SolderRow]:
    return [r for r in rows if row_passes_quote_gate(r)]