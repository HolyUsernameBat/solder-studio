from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from studio import db
from studio.audit_flow import NOT_YET_TRIAGED
from studio.schema import DEFAULT_PROJECT_NAME, DEFAULT_RESEARCH_QUESTION, PaperCoverage
from studio.schema import PaperAudit
import solder_cli


@pytest.fixture
def cli_root(tmp_path: Path) -> Path:
    db.init_db(tmp_path)
    (tmp_path / "pdfs").mkdir()
    return tmp_path


def _run(argv: list[str], root: Path) -> tuple[int, str]:
    captured = StringIO()
    argv_full = ["solder_cli.py", "--root", str(root), *argv]
    with patch.object(sys, "argv", argv_full):
        with patch.object(sys, "stdout", captured):
            code = solder_cli.main(argv_full[1:])
    return code, captured.getvalue()


def test_question_read_defaults_to_seed_project(cli_root: Path):
    code, out = _run(["question-read"], cli_root)
    assert code == 0
    data = json.loads(out)
    assert data["project_name"] == DEFAULT_PROJECT_NAME
    assert data["research_question"] == DEFAULT_RESEARCH_QUESTION
    assert "screening_criteria" in data


def test_queue_list_hide_abstract_only_default(cli_root: Path):
    pid = db.get_default_project_id(cli_root)
    qid = db.default_question_id(cli_root, pid)
    assert qid is not None
    full_id = db.insert_paper(
        cli_root,
        PaperAudit(
            title="With PDF",
            project_id=pid,
            coverage=PaperCoverage.FULL_TEXT,
            pdf_path="x.pdf",
        ),
    )
    db.insert_paper(
        cli_root,
        PaperAudit(
            title="Abstract hit",
            project_id=pid,
            coverage=PaperCoverage.ABSTRACT_ONLY,
        ),
    )
    (cli_root / "pdfs" / "x.pdf").write_bytes(b"%PDF-1.4")
    code, out = _run(["queue-list"], cli_root)
    assert code == 0
    data = json.loads(out)
    ids = [p["paper_id"] for p in data["papers"]]
    assert full_id in ids
    assert len(ids) == 1
    assert data["filters"]["hide_abstract_only"] is True


def test_queue_list_respects_triage_filter(cli_root: Path):
    pid = db.get_default_project_id(cli_root)
    qid = db.default_question_id(cli_root, pid)
    assert qid is not None
    paper_id = db.insert_paper(
        cli_root,
        PaperAudit(
            title="Scored",
            project_id=pid,
            coverage=PaperCoverage.ABSTRACT_ONLY,
        ),
    )
    from studio.schema import TriageTier

    db.update_paper_audit(
        cli_root,
        paper_id,
        qid,
        tier=TriageTier.MUST_READ,
        relevance_score=5,
        relevance_justification="On topic",
        core_claim_and_mechanism="Claim",
        system_and_conditions="SAC-Bi",
        key_findings="Finding",
        limitations_and_caveats="Limit",
    )
    code_show, out_show = _run(
        ["queue-list", "--no-hide-abstract-only", "--triage", NOT_YET_TRIAGED],
        cli_root,
    )
    assert code_show == 0
    assert json.loads(out_show)["papers"] == []
    code_must, out_must = _run(
        ["queue-list", "--no-hide-abstract-only", "--triage", TriageTier.MUST_READ.value],
        cli_root,
    )
    assert code_must == 0
    assert len(json.loads(out_must)["papers"]) == 1


def test_search_openalex_blank_refused(cli_root: Path):
    with patch.object(solder_cli, "chatgpt_subscription_active", return_value=True):
        code, out = _run(["search-openalex", "   "], cli_root)
    assert code == 1
    err = json.loads(out)
    assert err["code"] == "blank_search"


def test_screening_draft_without_save_leaves_db(cli_root: Path):
    pid = db.get_default_project_id(cli_root)
    qid = db.default_question_id(cli_root, pid)
    assert qid is not None
    before = db.get_question(cli_root, qid)
    assert before is not None
    original = before.get("screening_criteria") or ""
    draft_text = "Cu joints; Bi addition; IMC thickness metrics."
    with patch.object(solder_cli, "chatgpt_subscription_active", return_value=True):
        with patch(
            "solder_cli.draft_screening_criteria", return_value=draft_text
        ):
            code, out = _run(["screening-draft"], cli_root)
    assert code == 0
    assert out.strip() == draft_text
    after = db.get_question(cli_root, qid)
    assert after is not None
    assert (after.get("screening_criteria") or "") == original


def test_screening_draft_with_save_writes_db(cli_root: Path):
    pid = db.get_default_project_id(cli_root)
    qid = db.default_question_id(cli_root, pid)
    assert qid is not None
    draft_text = "Saved criteria for SAC-Bi screening."
    with patch.object(solder_cli, "chatgpt_subscription_active", return_value=True):
        with patch(
            "solder_cli.draft_screening_criteria", return_value=draft_text
        ):
            code, out = _run(["screening-draft", "--save"], cli_root)
    assert code == 0
    assert out.strip() == draft_text
    after = db.get_question(cli_root, qid)
    assert after is not None
    assert after.get("screening_criteria") == draft_text