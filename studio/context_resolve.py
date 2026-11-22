"""Resolve project and research question for CLI (no Streamlit session)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from studio import db
from studio.schema import DEFAULT_PROJECT_NAME


class ResolveError(LookupError):
    pass


def find_project_by_name(base: Path, name: str) -> Optional[dict]:
    for row in db.list_projects(base):
        if row.get("name") == name:
            return row
    return None


def find_question_by_text(base: Path, project_id: int, text: str) -> Optional[dict]:
    for row in db.list_questions(base, project_id):
        if row.get("research_question") == text:
            return row
    return None


def resolve_project(base: Path, project_name: str | None) -> dict:
    db.init_db(base)
    if project_name is None:
        project_name = DEFAULT_PROJECT_NAME
    row = find_project_by_name(base, project_name)
    if row is None:
        raise ResolveError(f"Project not found: {project_name!r}")
    return row


def resolve_question(
    base: Path, project_id: int, question_text: str | None
) -> dict:
    if question_text is None:
        qid = db.default_question_id(base, project_id)
        if qid is None:
            raise ResolveError("Project has no research questions.")
        row = db.get_question(base, qid)
        if row is None:
            raise ResolveError("Default question missing.")
        return row
    row = find_question_by_text(base, project_id, question_text)
    if row is None:
        raise ResolveError(f"Research question not found in project: {question_text!r}")
    return row


def resolve_project_and_question(
    base: Path,
    project_name: str | None,
    question_text: str | None,
) -> tuple[dict, dict]:
    project = resolve_project(base, project_name)
    pid = int(project["project_id"])
    question = resolve_question(base, pid, question_text)
    return project, question


def question_target_metrics(question: dict) -> list[str]:
    try:
        data = json.loads(question.get("target_metrics_json") or "[]")
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []


def resolve_paper_in_project(base: Path, project_id: int, ref: str) -> dict:
    """Match paper id (decimal string) or exact title within the project."""
    if ref.isdigit():
        paper = db.get_paper(base, int(ref))
        if paper is not None and int(paper.get("project_id") or 0) == project_id:
            return paper
    for paper in db.list_papers(base, project_id=project_id):
        if (paper.get("title") or "") == ref:
            return paper
    raise ResolveError(f"Paper not found in project: {ref!r}")