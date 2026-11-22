#!/usr/bin/env python3
"""Agent-driven CLI for Solder Studio (same DB and pdfs/ as the Streamlit app)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from studio import db
from studio.audit_flow import (
    NOT_YET_TRIAGED,
    QUEUE_ORDER_LIBRARY,
    QUEUE_ORDER_MUST_READ_FIRST,
    TAG_FILTER_ALL,
    TRIAGE_FILTER_ALL,
)
from studio.batch_audit import audit_queued_paper, create_and_audit_unlinked_pdf
from studio.codex_backend import CODEX_MODEL_EXTRACT, chatgpt_subscription_active
from studio.context_resolve import (
    ResolveError,
    question_target_metrics,
    resolve_paper_in_project,
    resolve_project_and_question,
)
from studio.openalex_workflow import store_openalex_search_results
from studio.pdfs_folder import (
    is_pdf_path_stored,
    list_folder_pdfs,
    stored_pdf_paths,
)
from studio.queue_cli import list_filtered_queue, triage_filter_choices
from studio.schema import PaperCoverage
from studio.screening_draft import draft_screening_criteria

CODE_ROOT = Path(__file__).resolve().parent
PDFS_DIR = CODE_ROOT / "pdfs"


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _print_error(message: str, *, code: str = "error") -> None:
    _print_json({"error": message, "code": code})


def _require_codex() -> None:
    if not chatgpt_subscription_active():
        raise RuntimeError(
            "Codex is not signed in with ChatGPT. Run Start_Research_Studio.bat or `codex login`."
        )


def _common_context(
    project: str | None,
    question: str | None,
) -> tuple[dict, dict, int, int]:
    project_row, question_row = resolve_project_and_question(
        CODE_ROOT, project, question
    )
    pid = int(project_row["project_id"])
    qid = int(question_row["question_id"])
    return project_row, question_row, pid, qid


def cmd_question_read(args: argparse.Namespace) -> int:
    try:
        project_row, question_row, pid, qid = _common_context(args.project, args.question)
    except ResolveError as exc:
        _print_error(str(exc), code="not_found")
        return 1
    _print_json(
        {
            "project_id": pid,
            "project_name": project_row["name"],
            "question_id": qid,
            "research_question": question_row["research_question"],
            "screening_criteria": question_row.get("screening_criteria") or "",
            "target_metrics": question_target_metrics(question_row),
        }
    )
    return 0


def cmd_queue_list(args: argparse.Namespace) -> int:
    try:
        project_row, question_row, pid, qid = _common_context(args.project, args.question)
    except ResolveError as exc:
        _print_error(str(exc), code="not_found")
        return 1
    if args.triage not in triage_filter_choices(CODE_ROOT, pid):
        _print_error(f"Invalid triage filter: {args.triage!r}", code="bad_arg")
        return 1
    tag_options = [TAG_FILTER_ALL] + db.list_distinct_tags_for_project(CODE_ROOT, pid)
    if args.tag not in tag_options:
        _print_error(f"Invalid tag filter: {args.tag!r}", code="bad_arg")
        return 1
    papers = list_filtered_queue(
        CODE_ROOT,
        pid,
        qid,
        PDFS_DIR,
        hide_abstract_only=args.hide_abstract_only,
        triage_filter=args.triage,
        only_relevance_gt_2=args.only_relevance_gt_2,
        order=args.order,
        tag_filter=args.tag,
    )
    _print_json(
        {
            "project_name": project_row["name"],
            "question_id": qid,
            "research_question": question_row["research_question"],
            "filters": {
                "hide_abstract_only": args.hide_abstract_only,
                "triage": args.triage,
                "only_relevance_gt_2": args.only_relevance_gt_2,
                "order": args.order,
                "tag": args.tag,
            },
            "papers": papers,
        }
    )
    return 0


def cmd_search_openalex(args: argparse.Namespace) -> int:
    if not args.query.strip():
        _print_error("Search query must not be blank.", code="blank_search")
        return 1
    try:
        project_row, question_row, pid, qid = _common_context(args.project, args.question)
    except ResolveError as exc:
        _print_error(str(exc), code="not_found")
        return 1
    try:
        _require_codex()
    except RuntimeError as exc:
        _print_error(str(exc), code="codex")
        return 1
    screening = question_row.get("screening_criteria") or ""
    research_q = question_row["research_question"]
    try:
        result = store_openalex_search_results(
            CODE_ROOT,
            pid,
            qid,
            args.query,
            PDFS_DIR,
            research_question=research_q,
            screening_criteria=screening,
            extract_model=args.model or CODEX_MODEL_EXTRACT,
        )
    except ValueError as exc:
        _print_error(str(exc), code="blank_search")
        return 1
    except RuntimeError as exc:
        _print_error(str(exc), code="codex")
        return 1
    result["project_name"] = project_row["name"]
    _print_json(result)
    return 0


def cmd_audit_papers(args: argparse.Namespace) -> int:
    try:
        project_row, question_row, pid, qid = _common_context(args.project, args.question)
    except ResolveError as exc:
        _print_error(str(exc), code="not_found")
        return 1
    if not args.paper:
        _print_error("Name at least one paper (id or exact title).", code="bad_arg")
        return 1
    try:
        _require_codex()
    except RuntimeError as exc:
        _print_error(str(exc), code="codex")
        return 1
    screening = question_row.get("screening_criteria") or ""
    research_q = question_row["research_question"]
    metrics = question_target_metrics(question_row)
    results: list[dict] = []
    for ref in args.paper:
        try:
            paper = resolve_paper_in_project(CODE_ROOT, pid, ref)
        except ResolveError as exc:
            results.append({"ref": ref, "fatal_error": str(exc)})
            continue
        if paper.get("coverage") != PaperCoverage.FULL_TEXT.value or not paper.get(
            "pdf_path"
        ):
            results.append(
                {
                    "ref": ref,
                    "paper_id": int(paper["id"]),
                    "fatal_error": "Paper has no local full-text PDF.",
                }
            )
            continue
        run = audit_queued_paper(
            CODE_ROOT,
            paper,
            project_id=pid,
            question_id=qid,
            pdfs_dir=PDFS_DIR,
            research_question=research_q,
            screening_criteria=screening,
            target_metrics=metrics,
            extract_model=args.model or CODEX_MODEL_EXTRACT,
        )
        results.append({"ref": ref, **run.to_dict()})
    _print_json({"project_name": project_row["name"], "results": results})
    return 0


def cmd_audit_unlinked_pdfs(args: argparse.Namespace) -> int:
    try:
        project_row, question_row, pid, qid = _common_context(args.project, args.question)
    except ResolveError as exc:
        _print_error(str(exc), code="not_found")
        return 1
    try:
        _require_codex()
    except RuntimeError as exc:
        _print_error(str(exc), code="codex")
        return 1
    screening = question_row.get("screening_criteria") or ""
    research_q = question_row["research_question"]
    metrics = question_target_metrics(question_row)
    papers_for_link = db.list_papers(CODE_ROOT, project_id=pid)
    linked_paths = stored_pdf_paths(papers_for_link)
    unlinked = [
        name
        for name in list_folder_pdfs(PDFS_DIR)
        if not is_pdf_path_stored(name, linked_paths)
    ]
    results: list[dict] = []
    for pdf_name in unlinked:
        run = create_and_audit_unlinked_pdf(
            CODE_ROOT,
            pdf_name,
            project_id=pid,
            question_id=qid,
            pdfs_dir=PDFS_DIR,
            research_question=research_q,
            screening_criteria=screening,
            target_metrics=metrics,
            extract_model=args.model or CODEX_MODEL_EXTRACT,
        )
        results.append({"pdf": pdf_name, **run.to_dict()})
    _print_json(
        {
            "project_name": project_row["name"],
            "unlinked_count": len(unlinked),
            "results": results,
        }
    )
    return 0


def cmd_screening_draft(args: argparse.Namespace) -> int:
    try:
        project_row, question_row, pid, qid = _common_context(args.project, args.question)
    except ResolveError as exc:
        _print_error(str(exc), code="not_found")
        return 1
    try:
        _require_codex()
    except RuntimeError as exc:
        _print_error(str(exc), code="codex")
        return 1
    research_q = question_row["research_question"]
    current = question_row.get("screening_criteria") or ""
    model = args.model or CODEX_MODEL_EXTRACT
    try:
        text = draft_screening_criteria(
            research_q,
            current_criteria=current,
            target_metrics=question_target_metrics(question_row),
            model=model,
        )
    except RuntimeError as exc:
        _print_error(str(exc), code="codex")
        return 1
    if args.save:
        db.update_question(CODE_ROOT, qid, screening_criteria=text)
    # Brief: draft prints criteria text (not JSON).
    print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Solder Studio agent CLI")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="App root (default: directory containing solder_cli.py)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_project_question(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project", default=None, help="Project name")
        p.add_argument("--question", default=None, help="Exact research question text")

    p_read = sub.add_parser("question-read", help="Read question and screening criteria")
    add_project_question(p_read)
    p_read.set_defaults(func=cmd_question_read)

    p_list = sub.add_parser("queue-list", help="List filtered paper queue")
    add_project_question(p_list)
    p_list.add_argument(
        "--hide-abstract-only",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    p_list.add_argument("--triage", default=TRIAGE_FILTER_ALL)
    p_list.add_argument("--only-relevance-gt-2", action="store_true", default=False)
    p_list.add_argument(
        "--order",
        default=QUEUE_ORDER_LIBRARY,
        choices=[QUEUE_ORDER_LIBRARY, QUEUE_ORDER_MUST_READ_FIRST],
    )
    p_list.add_argument("--tag", default=TAG_FILTER_ALL)
    p_list.set_defaults(func=cmd_queue_list)

    p_search = sub.add_parser("search-openalex", help="Run OpenAlex search for project")
    add_project_question(p_search)
    p_search.add_argument("query", help="OpenAlex search string")
    p_search.add_argument(
        "--model",
        default=None,
        help=f"Codex model slug (default {CODEX_MODEL_EXTRACT})",
    )
    p_search.set_defaults(func=cmd_search_openalex)

    p_audit = sub.add_parser("audit-papers", help="Audit papers with local PDFs")
    add_project_question(p_audit)
    p_audit.add_argument(
        "paper",
        nargs="+",
        help="Paper id(s) or exact title(s)",
    )
    p_audit.add_argument("--model", default=None)
    p_audit.set_defaults(func=cmd_audit_papers)

    p_unlinked = sub.add_parser(
        "audit-unlinked-pdfs", help="Create & audit unlinked files in pdfs/"
    )
    add_project_question(p_unlinked)
    p_unlinked.add_argument("--model", default=None)
    p_unlinked.set_defaults(func=cmd_audit_unlinked_pdfs)

    p_draft = sub.add_parser("screening-draft", help="Draft screening criteria via Codex")
    add_project_question(p_draft)
    p_draft.add_argument(
        "--save",
        action="store_true",
        help="Write screening_criteria to the database",
    )
    p_draft.add_argument(
        "--model",
        default=None,
        help=f"Codex slug (default {CODEX_MODEL_EXTRACT})",
    )
    p_draft.set_defaults(func=cmd_screening_draft)

    return parser


def main(argv: list[str] | None = None) -> int:
    global CODE_ROOT, PDFS_DIR
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.root is not None:
        CODE_ROOT = args.root.resolve()
        PDFS_DIR = CODE_ROOT / "pdfs"
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())