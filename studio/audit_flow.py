from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Optional

from studio import db
from studio.pdf_tables import audit_pdf_text, extract_rows_from_pdf_with_model
from studio.triage import run_triage

TRIAGE_TEXT_MAX_CHARS = 6000


def run_extract_and_triage(
    base: Path,
    paper_id: int,
    pdf_path: Path,
    paper_title: str,
    on_status: Callable[[str], None] | None = None,
) -> tuple[int, Optional[str], Optional[str]]:
    """
    Delete prior rows, extract quote-verified rows, then triage on table text.

    Returns (rows_stored, extract_warning, triage_warning).
    """
    db.delete_solder_rows_for_paper(base, paper_id)
    rows, err = extract_rows_from_pdf_with_model(
        pdf_path, paper_title, on_status=on_status
    )
    if err:
        return 0, err, None

    n = 0
    if rows:
        for row in rows:
            row.paper_id = paper_id
        n = db.insert_solder_rows(base, paper_id, rows)

    triage_warning: Optional[str] = None
    table_text, triage_err = audit_pdf_text(pdf_path)
    if triage_err:
        triage_warning = f"Triage skipped: {triage_err}"
    else:
        snippet = table_text[:TRIAGE_TEXT_MAX_CHARS]
        try:
            tri = run_triage(paper_title, snippet, on_status=on_status)
            db.update_paper_triage(base, paper_id, tri.tier, tri.score, tri.rationale)
        except RuntimeError:
            raise
        except Exception as exc:
            triage_warning = str(exc)

    return n, None, triage_warning