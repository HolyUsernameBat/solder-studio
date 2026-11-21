from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from studio.schema import (
    DEFAULT_PROJECT_NAME,
    DEFAULT_RESEARCH_QUESTION,
    DEFAULT_SCREENING_CRITERIA,
    DEFAULT_TARGET_METRICS,
    MeasurementRow,
    PaperAudit,
    PaperCoverage,
    Project,
    ResearchQuestion,
    SourceSection,
    TriageTier,
)

DEFAULT_DB_NAME = "solder_lit.db"

_PAPER_AUDIT_COLS = (
    "triage_tier",
    "triage_score",
    "triage_rationale",
    "relevance_justification",
    "core_claim_and_mechanism",
    "system_and_conditions",
    "key_findings",
    "limitations_and_caveats",
)


def db_path(base: Path) -> Path:
    return base / DEFAULT_DB_NAME


def connect(base: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(base))
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r["name"] for r in rows}


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _ensure_column(conn: sqlite3.Connection, table: str, col_def: str) -> None:
    col_name = col_def.split()[0]
    cols = _column_names(conn, table)
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paper_has_legacy_audit(p: sqlite3.Row) -> bool:
    return any(p[c] for c in _PAPER_AUDIT_COLS if c in p.keys())


def _row_audit_payload(p: sqlite3.Row) -> dict:
    return {c: p[c] for c in _PAPER_AUDIT_COLS if c in p.keys()}


def _insert_question_from_project_row(
    conn: sqlite3.Connection, proj: sqlite3.Row
) -> int:
    created = proj["created_at"] if proj["created_at"] else _utc_now()
    rq = proj["research_question"] or DEFAULT_RESEARCH_QUESTION
    screen = proj["screening_criteria"] or ""
    metrics = proj["target_metrics_json"] or json.dumps(DEFAULT_TARGET_METRICS)
    cur = conn.execute(
        """
        INSERT INTO research_questions (
            project_id, research_question, screening_criteria,
            target_metrics_json, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (proj["project_id"], rq, screen, metrics, created),
    )
    return int(cur.lastrowid)


def _copy_legacy_paper_audits(
    conn: sqlite3.Connection, project_id: int, question_id: int
) -> None:
    papers = conn.execute(
        "SELECT * FROM papers WHERE project_id = ?", (project_id,)
    ).fetchall()
    for p in papers:
        if not _paper_has_legacy_audit(p):
            continue
        payload = _row_audit_payload(p)
        conn.execute(
            """
            INSERT OR REPLACE INTO paper_audits (
                paper_id, question_id, triage_tier, triage_score, triage_rationale,
                relevance_justification, core_claim_and_mechanism,
                system_and_conditions, key_findings, limitations_and_caveats
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p["id"],
                question_id,
                payload.get("triage_tier"),
                payload.get("triage_score"),
                payload.get("triage_rationale"),
                payload.get("relevance_justification"),
                payload.get("core_claim_and_mechanism"),
                payload.get("system_and_conditions"),
                payload.get("key_findings"),
                payload.get("limitations_and_caveats"),
            ),
        )


def _migrate_projects_to_questions(conn: sqlite3.Connection) -> None:
    projects = conn.execute("SELECT * FROM projects").fetchall()
    for proj in projects:
        pid = int(proj["project_id"])
        row = conn.execute(
            "SELECT question_id FROM research_questions WHERE project_id = ? LIMIT 1",
            (pid,),
        ).fetchone()
        if row:
            qid = int(row["question_id"])
        else:
            qid = _insert_question_from_project_row(conn, proj)
            _copy_legacy_paper_audits(conn, pid, qid)
        if "question_id" in _column_names(conn, "measurements"):
            conn.execute(
                """
                UPDATE measurements SET question_id = ?
                WHERE project_id = ? AND question_id IS NULL
                """,
                (qid, pid),
            )


def _seed_default_project(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
    if row:
        return int(row["project_id"])
    metrics_json = json.dumps(DEFAULT_TARGET_METRICS)
    created = _utc_now()
    cur = conn.execute(
        """
        INSERT INTO projects (name, research_question, screening_criteria, target_metrics_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            DEFAULT_PROJECT_NAME,
            DEFAULT_RESEARCH_QUESTION,
            DEFAULT_SCREENING_CRITERIA,
            metrics_json,
            created,
        ),
    )
    return int(cur.lastrowid)


def _migrate_legacy(conn: sqlite3.Connection, default_project_id: int) -> None:
    if "solder_rows" in _table_names(conn):
        conn.execute("DROP TABLE IF EXISTS solder_rows")
    paper_cols = _column_names(conn, "papers")
    if "project_id" in paper_cols:
        conn.execute(
            "UPDATE papers SET project_id = ? WHERE project_id IS NULL",
            (default_project_id,),
        )


def init_db(base: Path) -> int:
    """Create schema, migrate legacy DB, seed default project. Returns default project id."""
    with connect(base) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                research_question TEXT NOT NULL,
                screening_criteria TEXT NOT NULL DEFAULT '',
                target_metrics_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_questions (
                question_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                research_question TEXT NOT NULL,
                screening_criteria TEXT NOT NULL DEFAULT '',
                target_metrics_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(project_id)
            );

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
                project_id INTEGER,
                triage_tier TEXT,
                triage_score INTEGER,
                triage_rationale TEXT,
                relevance_justification TEXT,
                core_claim_and_mechanism TEXT,
                system_and_conditions TEXT,
                key_findings TEXT,
                limitations_and_caveats TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS paper_audits (
                paper_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                triage_tier TEXT,
                triage_score INTEGER,
                triage_rationale TEXT,
                relevance_justification TEXT,
                core_claim_and_mechanism TEXT,
                system_and_conditions TEXT,
                key_findings TEXT,
                limitations_and_caveats TEXT,
                PRIMARY KEY (paper_id, question_id),
                FOREIGN KEY (paper_id) REFERENCES papers(id),
                FOREIGN KEY (question_id) REFERENCES research_questions(question_id)
            );

            CREATE TABLE IF NOT EXISTS measurements (
                measurement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                question_id INTEGER,
                paper_id INTEGER NOT NULL,
                material_system TEXT,
                composition_or_variant TEXT,
                processing_or_aging_condition TEXT,
                phase_or_microstructure TEXT,
                metric_name TEXT,
                metric_value REAL NOT NULL,
                metric_unit TEXT,
                sample_size TEXT,
                source_section TEXT,
                source_page INTEGER,
                verbatim_quote TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                FOREIGN KEY (question_id) REFERENCES research_questions(question_id),
                FOREIGN KEY (paper_id) REFERENCES papers(id)
            );
            """
        )
        for col in (
            "openalex_id TEXT",
            "authors TEXT",
            "year INTEGER",
            "abstract TEXT",
            "doi TEXT",
            "pdf_path TEXT",
            "project_id INTEGER",
            "triage_tier TEXT",
            "triage_score INTEGER",
            "triage_rationale TEXT",
            "relevance_justification TEXT",
            "core_claim_and_mechanism TEXT",
            "system_and_conditions TEXT",
            "key_findings TEXT",
            "limitations_and_caveats TEXT",
        ):
            _ensure_column(conn, "papers", col)
        _ensure_column(conn, "measurements", "question_id INTEGER")
        default_pid = _seed_default_project(conn)
        _migrate_legacy(conn, default_pid)
        _migrate_projects_to_questions(conn)
        conn.commit()
        return default_pid


def get_default_project_id(base: Path) -> int:
    with connect(base) as conn:
        return _seed_default_project(conn)


def default_question_id(base: Path, project_id: int) -> Optional[int]:
    with connect(base) as conn:
        row = conn.execute(
            """
            SELECT question_id FROM research_questions
            WHERE project_id = ? ORDER BY question_id LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    return int(row["question_id"]) if row else None


def list_projects(base: Path) -> list[dict]:
    with connect(base) as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY project_id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_project(base: Path, project_id: int) -> Optional[dict]:
    with connect(base) as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
    return dict(row) if row else None


def project_from_row(row: dict) -> Project:
    return Project(
        project_id=row["project_id"],
        name=row["name"],
        research_question=row.get("research_question") or "",
        screening_criteria=row.get("screening_criteria") or "",
        target_metrics_json=row.get("target_metrics_json") or "[]",
        created_at=row.get("created_at"),
    )


def question_from_row(row: dict) -> ResearchQuestion:
    return ResearchQuestion(
        question_id=row["question_id"],
        project_id=row["project_id"],
        research_question=row["research_question"],
        screening_criteria=row.get("screening_criteria") or "",
        target_metrics_json=row.get("target_metrics_json") or "[]",
        created_at=row.get("created_at"),
    )


def list_questions(base: Path, project_id: int) -> list[dict]:
    with connect(base) as conn:
        rows = conn.execute(
            """
            SELECT * FROM research_questions
            WHERE project_id = ? ORDER BY question_id
            """,
            (project_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_question(base: Path, question_id: int) -> Optional[dict]:
    with connect(base) as conn:
        row = conn.execute(
            "SELECT * FROM research_questions WHERE question_id = ?",
            (question_id,),
        ).fetchone()
    return dict(row) if row else None


def create_project(base: Path, name: str, research_question: str) -> int:
    created = _utc_now()
    metrics_json = json.dumps(DEFAULT_TARGET_METRICS)
    with connect(base) as conn:
        cur = conn.execute(
            """
            INSERT INTO projects (name, research_question, screening_criteria, target_metrics_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, research_question, "", metrics_json, created),
        )
        pid = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO research_questions (
                project_id, research_question, screening_criteria,
                target_metrics_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (pid, research_question, "", metrics_json, created),
        )
        return pid


def create_question(
    base: Path,
    project_id: int,
    research_question: str,
    *,
    screening_criteria: str = "",
    target_metrics_json: Optional[str] = None,
) -> int:
    created = _utc_now()
    metrics_json = target_metrics_json or json.dumps(DEFAULT_TARGET_METRICS)
    with connect(base) as conn:
        cur = conn.execute(
            """
            INSERT INTO research_questions (
                project_id, research_question, screening_criteria,
                target_metrics_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, research_question, screening_criteria, metrics_json, created),
        )
        return int(cur.lastrowid)


def update_project(
    base: Path,
    project_id: int,
    *,
    name: Optional[str] = None,
    research_question: Optional[str] = None,
    screening_criteria: Optional[str] = None,
    target_metrics_json: Optional[str] = None,
) -> None:
    fields: list[str] = []
    values: list[object] = []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if research_question is not None:
        fields.append("research_question = ?")
        values.append(research_question)
    if screening_criteria is not None:
        fields.append("screening_criteria = ?")
        values.append(screening_criteria)
    if target_metrics_json is not None:
        fields.append("target_metrics_json = ?")
        values.append(target_metrics_json)
    if not fields:
        return
    values.append(project_id)
    with connect(base) as conn:
        conn.execute(
            f"UPDATE projects SET {', '.join(fields)} WHERE project_id = ?",
            values,
        )


def update_question(
    base: Path,
    question_id: int,
    *,
    research_question: Optional[str] = None,
    screening_criteria: Optional[str] = None,
    target_metrics_json: Optional[str] = None,
) -> None:
    fields: list[str] = []
    values: list[object] = []
    if research_question is not None:
        fields.append("research_question = ?")
        values.append(research_question)
    if screening_criteria is not None:
        fields.append("screening_criteria = ?")
        values.append(screening_criteria)
    if target_metrics_json is not None:
        fields.append("target_metrics_json = ?")
        values.append(target_metrics_json)
    if not fields:
        return
    values.append(question_id)
    with connect(base) as conn:
        conn.execute(
            f"UPDATE research_questions SET {', '.join(fields)} WHERE question_id = ?",
            values,
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
                pdf_path, coverage, project_id, triage_tier, triage_score,
                triage_rationale, relevance_justification, core_claim_and_mechanism,
                system_and_conditions, key_findings, limitations_and_caveats
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                paper.project_id,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ),
        )
        return int(cur.lastrowid)


def upsert_paper(
    base: Path, paper: PaperAudit, *, pdf_kept: bool = False
) -> int:
    existing_id = get_paper_id_by_openalex_id(base, paper.openalex_id or "")
    if existing_id is None:
        return insert_paper(base, paper)

    with connect(base) as conn:
        if pdf_kept and paper.pdf_path:
            conn.execute(
                """
                UPDATE papers SET
                    title = ?, year = ?, abstract = ?,
                    pdf_path = ?, coverage = ?, project_id = COALESCE(?, project_id)
                WHERE id = ?
                """,
                (
                    paper.title,
                    paper.year,
                    paper.abstract,
                    paper.pdf_path,
                    paper.coverage.value,
                    paper.project_id,
                    existing_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE papers SET title = ?, year = ?, abstract = ?,
                    project_id = COALESCE(?, project_id)
                WHERE id = ?
                """,
                (paper.title, paper.year, paper.abstract, paper.project_id, existing_id),
            )
    return existing_id


def insert_folder_paper(
    base: Path, pdf_filename: str, project_id: int
) -> int:
    from studio.pdfs_folder import title_from_pdf_filename

    paper = PaperAudit(
        title=title_from_pdf_filename(pdf_filename),
        pdf_path=pdf_filename,
        coverage=PaperCoverage.FULL_TEXT,
        project_id=project_id,
    )
    return insert_paper(base, paper)


def update_paper_triage_legacy(
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


def update_paper_audit(
    base: Path,
    paper_id: int,
    question_id: int,
    *,
    tier: TriageTier,
    relevance_score: int,
    relevance_justification: str,
    core_claim_and_mechanism: str,
    system_and_conditions: str,
    key_findings: str,
    limitations_and_caveats: str,
) -> None:
    with connect(base) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO paper_audits (
                paper_id, question_id, triage_tier, triage_score, triage_rationale,
                relevance_justification, core_claim_and_mechanism,
                system_and_conditions, key_findings, limitations_and_caveats
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                question_id,
                tier.value,
                relevance_score,
                relevance_justification,
                relevance_justification,
                core_claim_and_mechanism,
                system_and_conditions,
                key_findings,
                limitations_and_caveats,
            ),
        )


def get_paper_audit_fields(
    base: Path, paper_id: int, question_id: int
) -> dict:
    with connect(base) as conn:
        row = conn.execute(
            "SELECT * FROM paper_audits WHERE paper_id = ? AND question_id = ?",
            (paper_id, question_id),
        ).fetchone()
    if not row:
        return {}
    return dict(row)


def paper_with_audit_for_question(
    paper: dict, audit: dict
) -> dict:
    merged = dict(paper)
    for c in _PAPER_AUDIT_COLS:
        if c in audit and audit[c] is not None:
            merged[c] = audit[c]
    return merged


def update_paper_pdf(base: Path, paper_id: int, pdf_path: str) -> None:
    with connect(base) as conn:
        conn.execute(
            """
            UPDATE papers SET pdf_path = ?, coverage = ?
            WHERE id = ?
            """,
            (pdf_path, PaperCoverage.FULL_TEXT.value, paper_id),
        )


def list_papers(
    base: Path, project_id: Optional[int] = None
) -> list[dict]:
    with connect(base) as conn:
        if project_id is not None:
            rows = conn.execute(
                "SELECT * FROM papers WHERE project_id = ? ORDER BY year DESC, title",
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM papers ORDER BY year DESC, title"
            ).fetchall()
    return [dict(r) for r in rows]


def list_papers_for_question(
    base: Path, project_id: int, question_id: int
) -> list[dict]:
    papers = list_papers(base, project_id=project_id)
    out: list[dict] = []
    for p in papers:
        audit = get_paper_audit_fields(base, int(p["id"]), question_id)
        out.append(paper_with_audit_for_question(p, audit))
    return out


def get_paper(base: Path, paper_id: int) -> Optional[dict]:
    with connect(base) as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return dict(row) if row else None


def _row_to_measurement(r: sqlite3.Row) -> MeasurementRow:
    sec = r["source_section"]
    keys = r.keys()
    return MeasurementRow(
        measurement_id=r["measurement_id"],
        project_id=r["project_id"],
        question_id=r["question_id"] if "question_id" in keys else None,
        paper_id=r["paper_id"],
        material_system=r["material_system"],
        composition_or_variant=r["composition_or_variant"],
        processing_or_aging_condition=r["processing_or_aging_condition"],
        phase_or_microstructure=r["phase_or_microstructure"],
        metric_name=r["metric_name"],
        metric_value=r["metric_value"],
        metric_unit=r["metric_unit"],
        sample_size=r["sample_size"],
        source_section=SourceSection(sec) if sec else None,
        source_page=r["source_page"],
        verbatim_quote=r["verbatim_quote"],
    )


def insert_measurements(
    base: Path,
    project_id: int,
    question_id: int,
    paper_id: int,
    rows: list[MeasurementRow],
) -> int:
    count = 0
    with connect(base) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO measurements (
                    project_id, question_id, paper_id, material_system, composition_or_variant,
                    processing_or_aging_condition, phase_or_microstructure,
                    metric_name, metric_value, metric_unit, sample_size,
                    source_section, source_page, verbatim_quote
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    question_id,
                    paper_id,
                    row.material_system,
                    row.composition_or_variant,
                    row.processing_or_aging_condition,
                    row.phase_or_microstructure,
                    row.metric_name,
                    row.metric_value,
                    row.metric_unit,
                    row.sample_size,
                    row.source_section.value if row.source_section else None,
                    row.source_page,
                    row.verbatim_quote,
                ),
            )
            count += 1
    return count


def list_measurements(
    base: Path,
    project_id: Optional[int] = None,
    question_id: Optional[int] = None,
    paper_id: Optional[int] = None,
) -> list[MeasurementRow]:
    clauses: list[str] = []
    params: list[object] = []
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    if question_id is not None:
        clauses.append("question_id = ?")
        params.append(question_id)
    if paper_id is not None:
        clauses.append("paper_id = ?")
        params.append(paper_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM measurements{where} ORDER BY paper_id, source_page, measurement_id"
    with connect(base) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_measurement(r) for r in rows]


def delete_measurements_for_paper(
    base: Path, paper_id: int, question_id: int
) -> None:
    with connect(base) as conn:
        conn.execute(
            "DELETE FROM measurements WHERE paper_id = ? AND question_id = ?",
            (paper_id, question_id),
        )