import json
import sqlite3
from pathlib import Path

import pytest

from studio import db
from studio.schema import (
    DEFAULT_PROJECT_NAME,
    DEFAULT_RESEARCH_QUESTION,
    MeasurementRow,
    PaperAudit,
    PaperCoverage,
    SourceSection,
    TriageTier,
)


@pytest.fixture
def db_root(tmp_path: Path) -> Path:
    db.init_db(tmp_path)
    return tmp_path


def test_seeds_default_project(db_root: Path):
    projects = db.list_projects(db_root)
    assert len(projects) == 1
    p = projects[0]
    assert p["name"] == DEFAULT_PROJECT_NAME
    questions = db.list_questions(db_root, p["project_id"])
    assert len(questions) == 1
    q = questions[0]
    assert q["research_question"] == DEFAULT_RESEARCH_QUESTION
    metrics = json.loads(q["target_metrics_json"])
    assert "IMC thickness (um)" in metrics
    assert any("shear" in m.lower() or "UTS" in m for m in metrics)


def test_papers_and_measurements_scoped_to_project(db_root: Path):
    pid = db.get_default_project_id(db_root)
    qid = db.default_question_id(db_root, pid)
    assert qid is not None
    paper = PaperAudit(
        title="Bi SAC study",
        project_id=pid,
        coverage=PaperCoverage.ABSTRACT_ONLY,
    )
    paper_id = db.insert_paper(db_root, paper)
    row = MeasurementRow(
        metric_name="IMC thickness",
        metric_value=2.5,
        metric_unit="um",
        source_section=SourceSection.RESULTS,
        verbatim_quote="IMC 2.5 um",
    )
    db.insert_measurements(db_root, pid, qid, paper_id, [row])
    scoped = db.list_measurements(db_root, question_id=qid)
    assert len(scoped) == 1
    papers = db.list_papers(db_root, project_id=pid)
    assert len(papers) == 1
    pid2 = db.create_project(db_root, "Other", "Different question?")
    qid2 = db.default_question_id(db_root, pid2)
    assert qid2 is not None
    assert db.list_measurements(db_root, question_id=qid2) == []
    assert db.list_papers(db_root, project_id=pid2) == []


def test_migration_attaches_legacy_papers_to_default(tmp_path: Path):
    """Simulate old schema: papers without project_id, solder_rows present."""
    old_db = tmp_path / "solder_lit.db"
    conn = sqlite3.connect(old_db)
    conn.executescript(
        """
        CREATE TABLE papers (
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
        CREATE TABLE solder_rows (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER,
            alloy TEXT,
            imc_thickness_um REAL
        );
        INSERT INTO papers (title, coverage) VALUES ('Legacy paper', 'full-text');
        """
    )
    conn.close()

    default_pid = db.init_db(tmp_path)
    papers = db.list_papers(tmp_path)
    assert len(papers) == 1
    assert papers[0].get("project_id") == default_pid
    conn2 = sqlite3.connect(old_db)
    tables = {
        r[0]
        for r in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn2.close()
    assert "solder_rows" not in tables
    assert "measurements" in tables
    assert "research_questions" in tables


def test_migration_legacy_project_becomes_question_and_paper_audits(tmp_path: Path):
    old_db = tmp_path / "solder_lit.db"
    conn = sqlite3.connect(old_db)
    conn.executescript(
        """
        CREATE TABLE projects (
            project_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            research_question TEXT NOT NULL,
            screening_criteria TEXT NOT NULL DEFAULT '',
            target_metrics_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        INSERT INTO projects (name, research_question, screening_criteria, target_metrics_json, created_at)
        VALUES ('Old lab', 'Does Bi thicken IMC?', 'SAC on Cu', '["IMC (um)"]', '2020-01-01T00:00:00+00:00');

        CREATE TABLE papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            coverage TEXT NOT NULL DEFAULT 'abstract-only',
            project_id INTEGER,
            triage_tier TEXT,
            triage_score INTEGER,
            relevance_justification TEXT,
            core_claim_and_mechanism TEXT
        );
        INSERT INTO papers (title, coverage, project_id, triage_tier, triage_score, relevance_justification, core_claim_and_mechanism)
        VALUES ('Migrated paper', 'full-text', 1, 'Must Read (Deep Dive)', 4, 'On topic', 'Bi refines IMC');
        """
    )
    conn.close()

    db.init_db(tmp_path)
    questions = db.list_questions(tmp_path, 1)
    assert len(questions) == 1
    assert questions[0]["research_question"] == "Does Bi thicken IMC?"
    assert questions[0]["screening_criteria"] == "SAC on Cu"
    qid = questions[0]["question_id"]
    merged = db.list_papers_for_question(tmp_path, 1, qid)
    assert len(merged) == 1
    assert merged[0]["triage_tier"] == "Must Read (Deep Dive)"
    assert merged[0]["triage_score"] == 4
    assert merged[0]["relevance_justification"] == "On topic"
    assert merged[0]["core_claim_and_mechanism"] == "Bi refines IMC"
    conn3 = sqlite3.connect(old_db)
    audit_count = conn3.execute("SELECT COUNT(*) FROM paper_audits").fetchone()[0]
    conn3.close()
    assert audit_count == 1


def test_two_questions_isolate_audits_and_measurements(db_root: Path):
    pid = db.get_default_project_id(db_root)
    q_a = db.default_question_id(db_root, pid)
    q_b = db.create_question(db_root, pid, "Secondary hypothesis about aging?")
    paper = PaperAudit(
        title="Shared corpus paper",
        project_id=pid,
        coverage=PaperCoverage.FULL_TEXT,
    )
    paper_id = db.insert_paper(db_root, paper)

    db.update_paper_audit(
        db_root,
        paper_id,
        q_a,
        tier=TriageTier.MUST_READ,
        relevance_score=5,
        relevance_justification="A fit",
        core_claim_and_mechanism="Claim A",
        system_and_conditions="SAC-Bi",
        key_findings="Finding A",
        limitations_and_caveats="Limit A",
    )
    db.update_paper_audit(
        db_root,
        paper_id,
        q_b,
        tier=TriageTier.LOW_PRIORITY,
        relevance_score=2,
        relevance_justification="B weak",
        core_claim_and_mechanism="Claim B",
        system_and_conditions="aged",
        key_findings="Finding B",
        limitations_and_caveats="Limit B",
    )

    row_a = MeasurementRow(
        metric_name="IMC thickness",
        metric_value=1.0,
        metric_unit="um",
        source_section=SourceSection.RESULTS,
        verbatim_quote="1.0 um",
    )
    row_b = MeasurementRow(
        metric_name="lap shear",
        metric_value=40.0,
        metric_unit="MPa",
        source_section=SourceSection.TABLE,
        verbatim_quote="40 MPa",
    )
    db.insert_measurements(db_root, pid, q_a, paper_id, [row_a])
    db.insert_measurements(db_root, pid, q_b, paper_id, [row_b])

    papers_a = db.list_papers_for_question(db_root, pid, q_a)
    papers_b = db.list_papers_for_question(db_root, pid, q_b)
    assert len(papers_a) == len(papers_b) == 1
    assert papers_a[0]["core_claim_and_mechanism"] == "Claim A"
    assert papers_b[0]["core_claim_and_mechanism"] == "Claim B"
    assert db.list_measurements(db_root, question_id=q_a)[0].metric_name == "IMC thickness"
    assert db.list_measurements(db_root, question_id=q_b)[0].metric_name == "lap shear"


def test_upsert_openalex_id_does_not_duplicate(db_root: Path):
    pid = db.get_default_project_id(db_root)
    paper = PaperAudit(
        openalex_id="https://openalex.org/W123",
        title="First title",
        year=2020,
        abstract="alpha",
        coverage=PaperCoverage.ABSTRACT_ONLY,
        project_id=pid,
    )
    id1 = db.upsert_paper(db_root, paper)
    paper2 = PaperAudit(
        openalex_id="https://openalex.org/W123",
        title="Updated title",
        year=2021,
        abstract="beta",
        pdf_path="W123.pdf",
        coverage=PaperCoverage.FULL_TEXT,
        project_id=pid,
    )
    id2 = db.upsert_paper(db_root, paper2, pdf_kept=True)
    assert id1 == id2
    papers = db.list_papers(db_root, project_id=pid)
    assert len(papers) == 1
    row = papers[0]
    assert row["title"] == "Updated title"
    assert row["pdf_path"] == "W123.pdf"