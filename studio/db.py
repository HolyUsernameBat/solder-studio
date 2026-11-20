from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from studio.schema import (
    AgingType,
    ImcPhase,
    PaperAudit,
    PaperCoverage,
    ShearUnit,
    SolderRow,
    TriageTier,
)

DEFAULT_DB_NAME = "solder_lit.db"


def db_path(base: Path) -> Path:
    return base / DEFAULT_DB_NAME


def connect(base: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(base))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(base: Path) -> None:
    with connect(base) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                openalex_id TEXT,
                title TEXT NOT NULL,
                authors TEXT,
                year INTEGER,
                abstract TEXT,
                doi TEXT,
                pdf_path TEXT,
                coverage TEXT NOT NULL DEFAULT 'abstract-only',
                triage_tier TEXT,
                triage_score INTEGER,
                triage_rationale TEXT
            );

            CREATE TABLE IF NOT EXISTS solder_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id INTEGER NOT NULL,
                alloy TEXT,
                addition_name TEXT,
                addition_weight_percent REAL,
                substrate TEXT,
                reflow_temp_c REAL,
                aging_condition TEXT,
                aging_type TEXT,
                imc_phase TEXT,
                imc_thickness_um REAL,
                shear_value REAL,
                shear_unit TEXT,
                uts_mpa REAL,
                elongation_percent REAL,
                fracture_mode TEXT,
                sample_size TEXT,
                source_page INTEGER,
                verbatim_quote TEXT,
                FOREIGN KEY (paper_id) REFERENCES papers(id)
            );
            """
        )


def get_paper_id_by_openalex_id(base: Path, openalex_id: str) -> Optional[int]:
    if not openalex_id:
        return None
    with connect(base) as conn:
        row = conn.execute(
            "SELECT id FROM papers WHERE openalex_id = ?", (openalex_id,)
        ).fetchone()
    return int(row["id"]) if row else None


def insert_paper(base: Path, paper: PaperAudit) -> int:
    with connect(base) as conn:
        cur = conn.execute(
            """
            INSERT INTO papers (
                openalex_id, title, authors, year, abstract, doi,
                pdf_path, coverage, triage_tier, triage_score, triage_rationale
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper.openalex_id,
                paper.title,
                paper.authors,
                paper.year,
                paper.abstract,
                paper.doi,
                paper.pdf_path,
                paper.coverage.value,
                paper.triage_tier.value if paper.triage_tier else None,
                paper.triage_score,
                paper.triage_rationale,
            ),
        )
        return int(cur.lastrowid)


def upsert_paper(
    base: Path, paper: PaperAudit, *, pdf_kept: bool = False
) -> int:
    """
    Insert a paper, or update an existing row when ``openalex_id`` matches.
    When ``pdf_kept`` is true, also refresh ``pdf_path`` and ``coverage``.
    """
    existing_id = get_paper_id_by_openalex_id(base, paper.openalex_id or "")
    if existing_id is None:
        return insert_paper(base, paper)

    with connect(base) as conn:
        if pdf_kept and paper.pdf_path:
            conn.execute(
                """
                UPDATE papers SET
                    title = ?, year = ?, abstract = ?,
                    pdf_path = ?, coverage = ?
                WHERE id = ?
                """,
                (
                    paper.title,
                    paper.year,
                    paper.abstract,
                    paper.pdf_path,
                    paper.coverage.value,
                    existing_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE papers SET title = ?, year = ?, abstract = ?
                WHERE id = ?
                """,
                (paper.title, paper.year, paper.abstract, existing_id),
            )
    return existing_id


def insert_folder_paper(base: Path, pdf_filename: str) -> int:
    """Create a full-text paper row for a hand-dropped PDF (filename stem as title)."""
    from studio.pdfs_folder import title_from_pdf_filename

    paper = PaperAudit(
        title=title_from_pdf_filename(pdf_filename),
        pdf_path=pdf_filename,
        coverage=PaperCoverage.FULL_TEXT,
    )
    return insert_paper(base, paper)


def update_paper_triage(
    base: Path,
    paper_id: int,
    tier: TriageTier,
    score: int,
    rationale: str,
) -> None:
    with connect(base) as conn:
        conn.execute(
            """
            UPDATE papers SET triage_tier = ?, triage_score = ?, triage_rationale = ?
            WHERE id = ?
            """,
            (tier.value, score, rationale, paper_id),
        )


def update_paper_pdf(base: Path, paper_id: int, pdf_path: str) -> None:
    with connect(base) as conn:
        conn.execute(
            """
            UPDATE papers SET pdf_path = ?, coverage = ?
            WHERE id = ?
            """,
            (pdf_path, PaperCoverage.FULL_TEXT.value, paper_id),
        )


def list_papers(base: Path) -> list[dict]:
    with connect(base) as conn:
        rows = conn.execute(
            "SELECT * FROM papers ORDER BY year DESC, title"
        ).fetchall()
    return [dict(r) for r in rows]


def get_paper(base: Path, paper_id: int) -> Optional[dict]:
    with connect(base) as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return dict(row) if row else None


def _row_to_solder(r: sqlite3.Row) -> SolderRow:
    return SolderRow(
        paper_id=r["paper_id"],
        alloy=r["alloy"],
        addition_name=r["addition_name"],
        addition_weight_percent=r["addition_weight_percent"],
        substrate=r["substrate"],
        reflow_temp_c=r["reflow_temp_c"],
        aging_condition=r["aging_condition"],
        aging_type=AgingType(r["aging_type"]) if r["aging_type"] else AgingType.UNSPECIFIED,
        imc_phase=ImcPhase(r["imc_phase"]) if r["imc_phase"] else ImcPhase.UNSPECIFIED,
        imc_thickness_um=r["imc_thickness_um"],
        shear_value=r["shear_value"],
        shear_unit=ShearUnit(r["shear_unit"]) if r["shear_unit"] else ShearUnit.UNSPECIFIED,
        uts_mpa=r["uts_mpa"],
        elongation_percent=r["elongation_percent"],
        fracture_mode=r["fracture_mode"],
        sample_size=r["sample_size"],
        source_page=r["source_page"],
        verbatim_quote=r["verbatim_quote"],
    )


def insert_solder_rows(base: Path, paper_id: int, rows: list[SolderRow]) -> int:
    count = 0
    with connect(base) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO solder_rows (
                    paper_id, alloy, addition_name, addition_weight_percent,
                    substrate, reflow_temp_c, aging_condition, aging_type,
                    imc_phase, imc_thickness_um, shear_value, shear_unit,
                    uts_mpa, elongation_percent, fracture_mode, sample_size,
                    source_page, verbatim_quote
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    row.alloy,
                    row.addition_name,
                    row.addition_weight_percent,
                    row.substrate,
                    row.reflow_temp_c,
                    row.aging_condition,
                    row.aging_type.value,
                    row.imc_phase.value,
                    row.imc_thickness_um,
                    row.shear_value,
                    row.shear_unit.value,
                    row.uts_mpa,
                    row.elongation_percent,
                    row.fracture_mode,
                    row.sample_size,
                    row.source_page,
                    row.verbatim_quote,
                ),
            )
            count += 1
    return count


def list_solder_rows(base: Path, paper_id: Optional[int] = None) -> list[SolderRow]:
    with connect(base) as conn:
        if paper_id is not None:
            rows = conn.execute(
                "SELECT * FROM solder_rows WHERE paper_id = ? ORDER BY source_page",
                (paper_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM solder_rows ORDER BY paper_id, source_page"
            ).fetchall()
    return [_row_to_solder(r) for r in rows]


def delete_solder_rows_for_paper(base: Path, paper_id: int) -> None:
    with connect(base) as conn:
        conn.execute("DELETE FROM solder_rows WHERE paper_id = ?", (paper_id,))