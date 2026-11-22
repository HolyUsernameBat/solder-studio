from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from studio import db
from studio.audit_flow import (
    NOT_YET_TRIAGED,
    QUEUE_ORDER_LIBRARY,
    QUEUE_ORDER_MUST_READ_FIRST,
    TAG_FILTER_ALL,
    TRIAGE_FILTER_ALL,
    active_research_question_display,
    apply_queue_paper_filters,
    eligible_queued_audit_paper_ids,
    paper_ids_for_audit_all,
    paper_ids_for_selected_audit,
    parse_comma_separated_tags,
    queue_papers_for_display,
    research_question_select_label,
    run_extract_and_triage,
)
from studio.charts import (
    filter_plot_points,
    plotter_metric_options,
    rows_to_dataframe,
    y_options_matching_x_unit,
)
from studio.codex_backend import (
    CODEX_MODEL_EXTRACT,
    CODEX_MODEL_SYNTH,
    chatgpt_subscription_active,
    fetch_codex_model_catalog,
    model_picker_options,
)
from studio.openalex import DEFAULT_OPENALEX_QUERY, search_openalex, try_fetch_pdf_for_work
from studio.pdfs_folder import (
    is_pdf_path_stored,
    list_folder_pdfs,
    paper_for_pdf_path,
    sanitize_windows_filename,
    stored_pdf_paths,
    title_from_pdf_filename,
    unique_pdf_dest,
)
from studio.schema import PaperCoverage, TriageTier
from studio.synthesize import run_synthesis
from studio.queue_table import (
    QUEUE_TABLE_DISPLAY_COLUMNS,
    audit_checked_ids_from_table,
    enforce_audit_eligibility,
    merge_audit_state,
    paper_ids_in_queue_table,
    queue_table_dataframe,
    queue_table_row_label_for_id,
    selection_default_row_index,
)
from studio.triage import run_triage

CODE_ROOT = Path(__file__).resolve().parent
PDFS_DIR = CODE_ROOT / "pdfs"
SIGN_IN_HELP = "Close this page and run Start_Research_Studio.bat to sign in with ChatGPT."
CODEX_LOG_MAX_LINES = 20
SESSION_CODEX_EXTRACT = "codex_model_extract"
SESSION_CODEX_PHYSICAL = "codex_model_physical"
SESSION_CODEX_INTERFACE = "codex_model_interface"
SESSION_CODEX_SKEPTIC = "codex_model_skeptic"
SESSION_CODEX_CATALOG = "codex_model_catalog_loaded"

st.set_page_config(page_title="Solder Studio", layout="wide")
st.title("Solder Studio")

default_pid = db.init_db(CODE_ROOT)
signed_in = chatgpt_subscription_active()

sidebar_log = st.sidebar.empty()

if "active_project_id" not in st.session_state:
    st.session_state.active_project_id = default_pid
if "active_question_id" not in st.session_state:
    st.session_state.active_question_id = db.default_question_id(
        CODE_ROOT, default_pid
    )


def _active_project() -> dict:
    pid = st.session_state.active_project_id
    row = db.get_project(CODE_ROOT, pid)
    if row is None:
        st.session_state.active_project_id = default_pid
        row = db.get_project(CODE_ROOT, default_pid)
    assert row is not None
    return row


def _active_question() -> dict:
    qid = st.session_state.active_question_id
    row = db.get_question(CODE_ROOT, qid) if qid else None
    pid = st.session_state.active_project_id
    if row is None or int(row["project_id"]) != int(pid):
        fallback = db.default_question_id(CODE_ROOT, pid)
        if fallback is None:
            raise RuntimeError("Project has no research questions.")
        st.session_state.active_question_id = fallback
        row = db.get_question(CODE_ROOT, fallback)
    assert row is not None
    return row


def _question_metrics(question: dict) -> list[str]:
    try:
        data = json.loads(question.get("target_metrics_json") or "[]")
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []


def _codex_log_init() -> None:
    if "codex_log" not in st.session_state:
        st.session_state.codex_log = []


def _codex_log_append(line: str) -> None:
    _codex_log_init()
    st.session_state.codex_log = (
        st.session_state.codex_log + [line]
    )[-CODEX_LOG_MAX_LINES:]


def _codex_model_options() -> list[str]:
    if SESSION_CODEX_CATALOG not in st.session_state:
        try:
            st.session_state[SESSION_CODEX_CATALOG] = fetch_codex_model_catalog()
        except Exception:
            st.session_state[SESSION_CODEX_CATALOG] = []
    return model_picker_options(st.session_state[SESSION_CODEX_CATALOG])


def _ensure_codex_model_selection(
    state_key: str, default: str, options: list[str]
) -> None:
    if state_key not in st.session_state:
        st.session_state[state_key] = default
    current = st.session_state[state_key]
    if current not in options:
        st.session_state[state_key] = (
            default if default in options else options[0]
        )


def _draw_codex_model_pickers() -> None:
    if not signed_in:
        return
    options = _codex_model_options()
    if not options:
        options = list(model_picker_options([]))
    defaults = (
        CODEX_MODEL_EXTRACT,
        CODEX_MODEL_SYNTH,
        CODEX_MODEL_SYNTH,
        CODEX_MODEL_SYNTH,
    )
    keys = (
        SESSION_CODEX_EXTRACT,
        SESSION_CODEX_PHYSICAL,
        SESSION_CODEX_INTERFACE,
        SESSION_CODEX_SKEPTIC,
    )
    labels = (
        "Extract / audit",
        "Physical Metallurgist",
        "Interface & Mechanisms",
        "Reliability Skeptic",
    )
    for state_key, default, label in zip(keys, defaults, labels):
        _ensure_codex_model_selection(state_key, default, options)
        st.sidebar.selectbox(label, options, key=state_key)


def _session_extract_model() -> str:
    return st.session_state.get(SESSION_CODEX_EXTRACT, CODEX_MODEL_EXTRACT)


def _session_lens_models() -> tuple[str, str, str]:
    return (
        st.session_state.get(SESSION_CODEX_PHYSICAL, CODEX_MODEL_SYNTH),
        st.session_state.get(SESSION_CODEX_INTERFACE, CODEX_MODEL_SYNTH),
        st.session_state.get(SESSION_CODEX_SKEPTIC, CODEX_MODEL_SYNTH),
    )


def _draw_codex_sidebar() -> None:
    _codex_log_init()
    lines = st.session_state.codex_log
    if lines:
        body = "\n".join(lines)
    elif signed_in:
        body = f"Codex idle.\nextract: {_session_extract_model()}"
    else:
        sidebar_log.empty()
        return
    sidebar_log.markdown(f"```\n{body}\n```")


def _codex_on_status() -> object:
    def on_status(line: str) -> None:
        _codex_log_append(line)
        _draw_codex_sidebar()

    return on_status


def _render_audit_brief(p: dict) -> None:
    tier = p.get("triage_tier")
    if tier:
        st.write(f"**Triage:** {tier} (relevance {p.get('triage_score')}/5)")
    if p.get("relevance_justification"):
        st.markdown(f"**Relevance:** {p['relevance_justification']}")
    if p.get("core_claim_and_mechanism"):
        st.markdown(f"**Core claim & mechanism:** {p['core_claim_and_mechanism']}")
    if p.get("system_and_conditions"):
        st.markdown(f"**System & conditions:** {p['system_and_conditions']}")
    if p.get("key_findings"):
        st.markdown(f"**Key findings:** {p['key_findings']}")
    if p.get("limitations_and_caveats"):
        st.markdown(f"**Limitations:** {p['limitations_and_caveats']}")
    elif p.get("triage_rationale"):
        st.caption(p.get("triage_rationale"))
    else:
        st.caption("Not audited yet.")


def _open_pdf(pdf_filename: str) -> None:
    pdf_path = PDFS_DIR / pdf_filename
    if pdf_path.is_file():
        os.startfile(str(pdf_path))
    else:
        st.error("PDF file missing on disk.")


def _audit_result_line(
    label: str,
    n: int,
    extract_err: str | None,
    triage_warn: str | None,
    *,
    fatal: str | None = None,
) -> str:
    if fatal:
        return f"**{label}** — failed: {fatal}"
    if extract_err:
        return f"**{label}** — {extract_err}"
    if n:
        line = f"**{label}** — stored {n} quote-verified row(s)."
    else:
        line = f"**{label}** — no rows passed the gates."
    if triage_warn:
        line += f" Triage: {triage_warn}"
    return line


def _run_queued_paper_audit(
    p: dict,
    *,
    project_id: int,
    question_id: int,
    research_q: str,
    screening: str,
    target_metrics: list[str],
) -> tuple[int, str | None, str | None, str | None]:
    """Returns (rows, extract_err, triage_warn, fatal_error)."""
    pdf_path = PDFS_DIR / p["pdf_path"]
    if not pdf_path.is_file():
        return 0, None, None, "PDF file missing on disk."
    try:
        n, extract_err, triage_warn = run_extract_and_triage(
            CODE_ROOT,
            int(p["id"]),
            project_id,
            question_id,
            pdf_path,
            p["title"],
            research_question=research_q,
            screening_criteria=screening,
            target_metrics=target_metrics,
            on_status=_codex_on_status(),
            extract_model=_session_extract_model(),
        )
    except RuntimeError as exc:
        return 0, None, None, str(exc)
    except Exception as exc:
        return 0, None, None, str(exc)
    return n, extract_err, triage_warn, None


def _run_create_and_audit_pdf(
    pdf_name: str,
    *,
    project_id: int,
    question_id: int,
    research_q: str,
    screening: str,
    target_metrics: list[str],
) -> tuple[int, str | None, str | None, str | None]:
    pdf_path = PDFS_DIR / pdf_name
    if not pdf_path.is_file():
        return 0, None, None, "PDF file missing on disk."
    title = title_from_pdf_filename(pdf_name)
    paper_id = db.insert_folder_paper(CODE_ROOT, pdf_name, project_id)
    try:
        n, extract_err, triage_warn = run_extract_and_triage(
            CODE_ROOT,
            paper_id,
            project_id,
            question_id,
            pdf_path,
            title,
            research_question=research_q,
            screening_criteria=screening,
            target_metrics=target_metrics,
            on_status=_codex_on_status(),
            extract_model=_session_extract_model(),
        )
    except RuntimeError as exc:
        return 0, None, None, str(exc)
    except Exception as exc:
        return 0, None, None, str(exc)
    return n, extract_err, triage_warn, None


st.sidebar.subheader("Codex")
_draw_codex_model_pickers()
st.sidebar.caption("Codex activity")
_draw_codex_sidebar()

if not signed_in:
    st.error(SIGN_IN_HELP)

# --- Project Brief ---
st.subheader("Project Brief")
projects = db.list_projects(CODE_ROOT)
project_ids = [p["project_id"] for p in projects]
labels = [f"{p['name']} (#{p['project_id']})" for p in projects]
idx = (
    project_ids.index(st.session_state.active_project_id)
    if st.session_state.active_project_id in project_ids
    else 0
)
choice = st.radio(
    "Active project",
    options=range(len(projects)),
    format_func=lambda i: labels[i],
    index=idx,
    key="project_selector",
    horizontal=False,
)
st.session_state.active_project_id = projects[choice]["project_id"]
project = _active_project()
pid = project["project_id"]
st.markdown(f"**Project:** {project['name']}")

questions = db.list_questions(CODE_ROOT, pid)
if not questions:
    st.error("This project has no research questions.")
    st.stop()
q_ids = [q["question_id"] for q in questions]
q_labels = [
    research_question_select_label(int(q["question_id"]), q["research_question"])
    for q in questions
]
q_idx = (
    q_ids.index(st.session_state.active_question_id)
    if st.session_state.active_question_id in q_ids
    else 0
)
q_choice = st.radio(
    "Active research question",
    options=range(len(questions)),
    format_func=lambda i: q_labels[i],
    index=q_idx,
    key="question_selector",
    horizontal=False,
)
st.session_state.active_question_id = questions[q_choice]["question_id"]
question = _active_question()
qid = int(question["question_id"])
st.markdown("**Active research question**")
st.markdown(active_research_question_display(question["research_question"]))

col_proj, col_q = st.columns(2)
with col_proj:
    with st.expander("Edit project name", expanded=False):
        new_name = st.text_input("Project name", value=project["name"], key="edit_name")
        if st.button("Save project name", key="save_project_name"):
            db.update_project(
                CODE_ROOT, pid, name=new_name.strip() or project["name"]
            )
            st.success("Project name updated.")
            st.rerun()
with col_q:
    with st.expander("Edit active question", expanded=False):
        new_rq = st.text_area(
            "Research question / hypothesis",
            value=question["research_question"],
            key="edit_rq",
        )
        new_screen = st.text_area(
            "Screening criteria",
            value=question.get("screening_criteria") or "",
            key="edit_screen",
        )
        metrics_list = _question_metrics(question)
        metrics_text = st.text_area(
            "Target metrics (one per line)",
            value="\n".join(metrics_list),
            key="edit_metrics",
        )
        if st.button("Save question", key="save_question"):
            lines = [ln.strip() for ln in metrics_text.splitlines() if ln.strip()]
            db.update_question(
                CODE_ROOT,
                qid,
                research_question=new_rq.strip() or question["research_question"],
                screening_criteria=new_screen.strip(),
                target_metrics_json=json.dumps(lines),
            )
            st.success("Question updated.")
            st.rerun()

new_q_text = st.text_input(
    "Add another question under this project",
    key="new_question_text",
    placeholder="How does aging time affect Bi-doped SAC joint strength?",
)
if st.button("Add question", key="add_question"):
    if new_q_text.strip():
        new_qid = db.create_question(CODE_ROOT, pid, new_q_text.strip())
        st.session_state.active_question_id = new_qid
        st.success(f"Added question #{new_qid}.")
        st.rerun()

new_proj_name = st.text_input("New project name", key="new_proj_name", placeholder="Ni-doped SAC aging")
new_proj_rq = st.text_input(
    "First research question for new project",
    key="new_proj_rq",
    placeholder="How does Ni affect IMC growth in SAC305?",
)
if st.button("Create project", key="create_project"):
    if new_proj_name.strip() and new_proj_rq.strip():
        new_id = db.create_project(CODE_ROOT, new_proj_name.strip(), new_proj_rq.strip())
        st.session_state.active_project_id = new_id
        st.session_state.active_question_id = db.default_question_id(CODE_ROOT, new_id)
        st.success(f"Created project #{new_id}.")
        st.rerun()

tab_search, tab_data, tab_synth = st.tabs(["Search & triage", "Measurements", "Synthesis"])

target_metrics = _question_metrics(question)
screening = question.get("screening_criteria") or ""
research_q = question["research_question"]

ABSTRACT_ONLY_AUDIT_CAPTION = (
    "No local PDF — table extraction is unavailable (abstract-only or paywalled)."
)

with tab_search:
    st.subheader("OpenAlex search")
    if "openalex_search_query" not in st.session_state:
        st.session_state.openalex_search_query = DEFAULT_OPENALEX_QUERY
    query = st.text_input(
        "Search query",
        key="openalex_search_query",
        placeholder=DEFAULT_OPENALEX_QUERY,
    )
    if st.button("Search OpenAlex", key="btn_search"):
        if not query.strip():
            st.error("Enter a search query.")
        elif not signed_in:
            st.error(SIGN_IN_HELP)
        else:
            with st.spinner("Searching…"):
                try:
                    hits = search_openalex(query)
                except Exception as exc:
                    st.error(str(exc))
                    hits = []
                saved = 0
                status_cb = _codex_on_status()
                for hit in hits:
                    work = hit.raw
                    pdf_name, coverage = try_fetch_pdf_for_work(work, PDFS_DIR)
                    paper = hit.paper
                    paper.coverage = coverage
                    paper.project_id = pid
                    if pdf_name:
                        paper.pdf_path = pdf_name
                    paper_id = db.upsert_paper(CODE_ROOT, paper, pdf_kept=bool(pdf_name))
                    try:
                        tri = run_triage(
                            paper.title,
                            paper.abstract,
                            research_question=research_q,
                            screening_criteria=screening,
                            on_status=status_cb,
                            model=_session_extract_model(),
                        )
                        db.update_paper_audit(
                            CODE_ROOT,
                            paper_id,
                            qid,
                            tier=tri.triage_tier,
                            relevance_score=tri.relevance_score,
                            relevance_justification=tri.relevance_justification,
                            core_claim_and_mechanism=tri.core_claim_and_mechanism,
                            system_and_conditions=tri.system_and_conditions,
                            key_findings=tri.key_findings,
                            limitations_and_caveats=tri.limitations_and_caveats,
                        )
                    except RuntimeError as exc:
                        st.error(str(exc))
                        break
                    except Exception as exc:
                        st.warning(f"Triage failed for {paper.title}: {exc}")
                    saved += 1
                st.success(f"Stored {saved} paper(s) for this project. Search does not write measurements.")

    batch_report = st.session_state.pop("last_batch_audit_report", None)
    if batch_report:
        st.markdown("**Last batch run**")
        for line in batch_report:
            st.markdown(f"- {line}")

    st.subheader("PDFs in the folder")
    uploaded_pdfs = st.file_uploader(
        "Upload PDFs",
        accept_multiple_files=True,
        type=["pdf"],
        key="upload_pdfs",
    )
    if "uploaded_pdf_ids" not in st.session_state:
        st.session_state.uploaded_pdf_ids = set()
    if uploaded_pdfs:
        saved_names: list[str] = []
        for upl in uploaded_pdfs:
            file_id = getattr(upl, "file_id", None) or f"{upl.name}:{upl.size}"
            if file_id in st.session_state.uploaded_pdf_ids:
                continue
            safe_name = sanitize_windows_filename(upl.name)
            if not safe_name.lower().endswith(".pdf"):
                safe_name = f"{Path(safe_name).stem}.pdf"
            dest = unique_pdf_dest(PDFS_DIR, safe_name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(upl.getvalue())
            st.session_state.uploaded_pdf_ids.add(file_id)
            saved_names.append(dest.name)
        if saved_names:
            st.success(f"Saved {len(saved_names)} PDF(s) to `pdfs/`: " + ", ".join(f"`{n}`" for n in saved_names))
            st.rerun()
    folder_pdfs = list_folder_pdfs(PDFS_DIR)
    papers_for_link = db.list_papers(CODE_ROOT, project_id=pid)
    linked_paths = stored_pdf_paths(papers_for_link)
    if not folder_pdfs:
        st.info("Drop PDF files into the `pdfs/` folder next to this app, then continue here.")
    else:
        for pdf_name in folder_pdfs:
            col_name, col_action = st.columns([3, 2])
            with col_name:
                linked = paper_for_pdf_path(papers_for_link, pdf_name)
                if is_pdf_path_stored(pdf_name, linked_paths):
                    label = linked["title"] if linked else pdf_name
                    st.write(f"`{pdf_name}` — linked to **{label[:100]}**")
                else:
                    st.write(f"`{pdf_name}` — not in the paper queue")
            with col_action:
                if not is_pdf_path_stored(pdf_name, linked_paths):
                    if st.button("Create paper & audit", key=f"folder_audit_{pdf_name}"):
                        if not signed_in:
                            st.error(SIGN_IN_HELP)
                        else:
                            pdf_path = PDFS_DIR / pdf_name
                            title = title_from_pdf_filename(pdf_name)
                            paper_id = db.insert_folder_paper(CODE_ROOT, pdf_name, pid)
                            try:
                                with st.spinner("Extracting tables…"):
                                    n, extract_err, triage_warn = run_extract_and_triage(
                                        CODE_ROOT,
                                        paper_id,
                                        pid,
                                        qid,
                                        pdf_path,
                                        title,
                                        research_question=research_q,
                                        screening_criteria=screening,
                                        target_metrics=target_metrics,
                                        on_status=_codex_on_status(),
                                        extract_model=_session_extract_model(),
                                    )
                            except RuntimeError as exc:
                                st.error(str(exc))
                                n, extract_err, triage_warn = 0, None, None
                            if extract_err:
                                st.warning(extract_err)
                            elif n:
                                st.success(f"Stored {n} quote-verified row(s).")
                            elif extract_err is None:
                                st.info("No rows passed the gates.")
                            if triage_warn:
                                st.warning(f"Triage failed (rows kept): {triage_warn}")
        unlinked_pdfs = [
            name for name in folder_pdfs if not is_pdf_path_stored(name, linked_paths)
        ]
        if unlinked_pdfs and st.button(
            "Create & audit all unlinked PDFs", key="batch_unlinked_pdfs"
        ):
            if not signed_in:
                st.error(SIGN_IN_HELP)
            else:
                batch_lines: list[str] = []
                with st.spinner(f"Create & audit {len(unlinked_pdfs)} PDF(s)…"):
                    for pdf_name in unlinked_pdfs:
                        n, extract_err, triage_warn, fatal = _run_create_and_audit_pdf(
                            pdf_name,
                            project_id=pid,
                            question_id=qid,
                            research_q=research_q,
                            screening=screening,
                            target_metrics=target_metrics,
                        )
                        label = title_from_pdf_filename(pdf_name)
                        batch_lines.append(
                            _audit_result_line(
                                label, n, extract_err, triage_warn, fatal=fatal
                            )
                        )
                st.session_state["last_batch_audit_report"] = batch_lines
                st.rerun()

    st.subheader("Paper queue")
    hide_abstract_only = st.checkbox(
        "Hide abstract-only",
        value=True,
        key="hide_abstract_only",
    )
    papers = db.list_papers_for_question(CODE_ROOT, pid, qid)
    if not papers:
        st.info("No papers yet for this project. Search above, or audit a PDF from the folder.")
    else:
        tag_options = [TAG_FILTER_ALL] + db.list_distinct_tags_for_project(
            CODE_ROOT, pid
        )
        triage_options = [
            TRIAGE_FILTER_ALL,
            TriageTier.MUST_READ.value,
            TriageTier.DATA_SOURCE.value,
            TriageTier.LOW_PRIORITY.value,
            NOT_YET_TRIAGED,
        ]
        order_options = [QUEUE_ORDER_LIBRARY, QUEUE_ORDER_MUST_READ_FIRST]
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            triage_filter = st.selectbox(
                "Triage", triage_options, index=0, key="queue_triage_filter"
            )
        with f2:
            only_relevance_gt_2 = st.checkbox(
                "Only relevance > 2", value=False, key="queue_relevance_gt_2"
            )
        with f3:
            order_filter = st.selectbox(
                "Order", order_options, index=0, key="queue_order_filter"
            )
        with f4:
            tag_filter = st.selectbox(
                "Tag", tag_options, index=0, key="queue_tag_filter"
            )

        tags_by_paper = db.tags_by_paper_for_project(CODE_ROOT, pid)
        after_hide = queue_papers_for_display(papers, PDFS_DIR, hide_abstract_only)
        queue_papers = apply_queue_paper_filters(
            after_hide,
            triage_filter=triage_filter,
            only_relevance_gt_2=only_relevance_gt_2,
            order=order_filter,
            tag_filter=tag_filter,
            tags_by_paper_id=tags_by_paper,
        )
        if not queue_papers:
            if hide_abstract_only and not after_hide:
                st.info(
                    "Abstract-only papers are hidden. Uncheck **Hide abstract-only** to triage them."
                )
            else:
                st.info(
                    "No papers match the current filters. Loosen **Triage**, "
                    "**Only relevance > 2**, **Tag**, or **Order**."
                )
        if queue_papers:
            papers_by_id = {int(p["id"]): p for p in papers}
            eligible_ids = eligible_queued_audit_paper_ids(papers, PDFS_DIR)
            eligible_set = set(eligible_ids)
            if "queue_audit_by_id" not in st.session_state:
                st.session_state.queue_audit_by_id = {}
            queue_df = queue_table_dataframe(
                queue_papers,
                tags_by_paper_id=tags_by_paper,
                eligible_audit_ids=eligible_set,
                audit_checked=st.session_state.queue_audit_by_id,
            )
            queue_col_config = {
                "Year": st.column_config.NumberColumn("Year", width="small"),
                "Title": st.column_config.TextColumn("Title", width="large"),
                "Coverage": st.column_config.TextColumn("Coverage", width="medium"),
                "Triage": st.column_config.TextColumn("Triage", width="medium"),
                "Relevance": st.column_config.TextColumn("Relevance", width="small"),
                "Tags": st.column_config.TextColumn("Tags", width="medium"),
                "Audit": st.column_config.CheckboxColumn(
                    "Audit",
                    help="Include in **Audit selected** (full-text with local PDF only).",
                    default=False,
                ),
            }
            edited_df = st.data_editor(
                queue_df,
                column_config=queue_col_config,
                column_order=list(QUEUE_TABLE_DISPLAY_COLUMNS),
                disabled=["Year", "Title", "Coverage", "Triage", "Relevance", "Tags"],
                hide_index=True,
                use_container_width=True,
                num_rows="fixed",
                key="paper_queue_editor",
            )
            edited_df = enforce_audit_eligibility(edited_df, eligible_set)
            st.session_state.queue_audit_by_id = merge_audit_state(
                st.session_state.queue_audit_by_id,
                edited_df,
                eligible_set,
            )
            checked_ids = audit_checked_ids_from_table(edited_df, eligible_set)
            paper_ids = paper_ids_in_queue_table(edited_df)
            queue_paper_id = st.selectbox(
                "Paper detail",
                options=paper_ids,
                format_func=lambda pid: queue_table_row_label_for_id(edited_df, pid),
                index=selection_default_row_index(
                    paper_ids, st.session_state.get("queue_paper_id")
                ),
                key="queue_paper_focus",
            )
            st.session_state.queue_paper_id = queue_paper_id
            if eligible_ids:
                st.markdown("**Batch audit**")
                btn_sel, btn_all = st.columns(2)
                with btn_sel:
                    run_selected = st.button("Audit selected", key="batch_audit_selected")
                with btn_all:
                    run_all = st.button("Audit all PDFs", key="batch_audit_all_pdfs")
                if run_selected or run_all:
                    if not signed_in:
                        st.error(SIGN_IN_HELP)
                    else:
                        if run_all:
                            ids_to_run = paper_ids_for_audit_all(eligible_ids)
                        else:
                            ids_to_run = paper_ids_for_selected_audit(
                                eligible_ids, checked_ids
                            )
                        if not ids_to_run:
                            st.warning("No papers selected.")
                        else:
                            batch_lines = []
                            with st.spinner(f"Auditing {len(ids_to_run)} paper(s)…"):
                                for paper_id in ids_to_run:
                                    paper = papers_by_id[paper_id]
                                    n, extract_err, triage_warn, fatal = _run_queued_paper_audit(
                                        paper,
                                        project_id=pid,
                                        question_id=qid,
                                        research_q=research_q,
                                        screening=screening,
                                        target_metrics=target_metrics,
                                    )
                                    batch_lines.append(
                                        _audit_result_line(
                                            paper["title"],
                                            n,
                                            extract_err,
                                            triage_warn,
                                            fatal=fatal,
                                        )
                                    )
                            st.session_state["last_batch_audit_report"] = batch_lines
                            st.rerun()

            p = papers_by_id[st.session_state.queue_paper_id]
            st.markdown(f"### {p['title']}")
            st.write(f"Coverage: **{p['coverage']}**")
            saved_tags = db.list_tags_for_paper(CODE_ROOT, int(p["id"]))
            tags_value = ", ".join(saved_tags)
            tags_input = st.text_input(
                "Tags (comma-separated)",
                value=tags_value,
                key=f"paper_tags_input_{p['id']}",
            )
            if st.button("Save tags", key=f"save_paper_tags_{p['id']}"):
                db.replace_tags_for_paper(
                    CODE_ROOT,
                    int(p["id"]),
                    parse_comma_separated_tags(tags_input),
                )
                st.rerun()
            if p.get("pdf_path"):
                st.write(f"PDF: `{p['pdf_path']}`")
                if st.button("Open PDF", key=f"open_pdf_{p['id']}"):
                    _open_pdf(p["pdf_path"])
            _render_audit_brief(p)
            if int(p["id"]) in eligible_queued_audit_paper_ids([p], PDFS_DIR):
                if st.button("Audit PDF (extract rows)", key=f"audit_{p['id']}"):
                    if not signed_in:
                        st.error(SIGN_IN_HELP)
                    else:
                        pdf_path = PDFS_DIR / p["pdf_path"]
                        if not pdf_path.is_file():
                            st.error("PDF file missing on disk.")
                        else:
                            try:
                                with st.spinner("Extracting tables…"):
                                    n, extract_err, triage_warn = run_extract_and_triage(
                                        CODE_ROOT,
                                        p["id"],
                                        pid,
                                        qid,
                                        pdf_path,
                                        p["title"],
                                        research_question=research_q,
                                        screening_criteria=screening,
                                        target_metrics=target_metrics,
                                        on_status=_codex_on_status(),
                                        extract_model=_session_extract_model(),
                                    )
                            except RuntimeError as exc:
                                st.error(str(exc))
                                n, extract_err, triage_warn = 0, None, None
                            if extract_err:
                                st.warning(extract_err)
                            elif n:
                                st.success(f"Stored {n} quote-verified row(s).")
                            elif extract_err is None:
                                st.info("No rows passed the gates.")
                            if triage_warn:
                                st.warning(f"Triage failed (rows kept): {triage_warn}")
            else:
                st.caption(ABSTRACT_ONLY_AUDIT_CAPTION)

with tab_data:
    st.subheader("Extracted measurements")
    all_rows = db.list_measurements(CODE_ROOT, question_id=qid)
    papers = {p["id"]: p["title"] for p in db.list_papers(CODE_ROOT, project_id=pid)}
    df = rows_to_dataframe(all_rows, papers)
    if df.empty:
        st.info("No rows yet. Audit a PDF from tab 1.")
    else:
        paper_opts = ["(all)"] + sorted(papers.values())
        mat_opts = ["(all)"] + sorted(df["material_system"].dropna().unique().tolist())
        metric_opts = ["(all)"] + sorted(df["metric_name"].dropna().unique().tolist())
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            fp = st.selectbox("Filter paper", paper_opts, key="filt_paper")
        with fc2:
            fm = st.selectbox("Filter material system", mat_opts, key="filt_mat")
        with fc3:
            fmet = st.selectbox("Filter metric name", metric_opts, key="filt_metric")
        view = df.copy()
        if fp != "(all)":
            ids = [k for k, v in papers.items() if v == fp]
            view = view[view["paper_id"].isin(ids)]
        if fm != "(all)":
            view = view[view["material_system"] == fm]
        if fmet != "(all)":
            view = view[view["metric_name"] == fmet]
        st.dataframe(view, use_container_width=True)
        csv = view.to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", csv, "measurements.csv", "text/csv")

        st.markdown("**Interactive plotter**")
        options = plotter_metric_options(view)
        if not options:
            st.caption("No plottable metrics yet.")
        else:
            x_labels = [o[0] for o in options]
            x_idx = st.selectbox("X axis", range(len(options)), format_func=lambda i: x_labels[i], key="plot_x")
            _, x_name, x_unit = options[x_idx]
            y_opts = y_options_matching_x_unit(options, x_unit)
            y_opts = [o for o in y_opts if not (o[1] == options[x_idx][1] and o[2] == options[x_idx][2])]
            if not y_opts:
                st.caption("Pick a different X metric, or extract another variable with the same unit.")
            else:
                y_labels = [o[0] for o in y_opts]
                y_idx = st.selectbox(
                    "Y axis", range(len(y_opts)), format_func=lambda i: y_labels[i], key="plot_y"
                )
                y_name, _, y_unit = y_opts[y_idx]
                plot_df = filter_plot_points(view, x_name, x_unit, y_name, y_unit)
                if plot_df.empty:
                    st.caption("No rows pair these metrics on the same sample.")
                else:
                    fig = px.scatter(
                        plot_df,
                        x="x_value",
                        y="y_value",
                        hover_data=["paper_title", "source_page"],
                        labels={"x_value": x_labels[x_idx], "y_value": y_labels[y_idx]},
                    )
                    st.plotly_chart(fig, use_container_width=True)

with tab_synth:
    st.subheader("Synthesis")
    all_rows = db.list_measurements(CODE_ROOT, question_id=qid)
    if st.button("Run synthesis", key="btn_synth"):
        if not signed_in:
            st.error(SIGN_IN_HELP)
        else:
            papers_by_id = {p["id"]: p["title"] for p in db.list_papers(CODE_ROOT, project_id=pid)}
            try:
                phys, iface, skeptic = _session_lens_models()
                briefing, stop, used = run_synthesis(
                    all_rows,
                    research_q,
                    paper_titles=papers_by_id,
                    on_status=_codex_on_status(),
                    physical_model=phys,
                    interface_model=iface,
                    skeptic_model=skeptic,
                )
            except RuntimeError as exc:
                st.error(str(exc))
                briefing, stop = None, None
            else:
                if stop:
                    st.warning(stop)
                elif briefing:
                    st.session_state["last_briefing"] = briefing
    briefing = st.session_state.get("last_briefing")
    if briefing:
        st.markdown("### Executive summary")
        st.markdown(briefing.executive_summary)
        st.markdown("### Findings")
        st.markdown(briefing.findings_markdown)
        st.markdown("### Direct contradictions")
        st.markdown(briefing.contradictions_markdown)
        st.markdown("### What the table failed to capture")
        st.markdown(briefing.table_gaps_markdown)
        st.markdown("### Assertion buckets")
        st.markdown(briefing.buckets_markdown)
        st.download_button(
            "Download HTML briefing",
            briefing.html,
            file_name="solder_studio_briefing.html",
            mime="text/html",
            key="btn_briefing_html",
        )
    if all_rows:
        st.markdown("**Quote-verified rows in database**")
        st.caption(f"{len(all_rows)} row(s) stored for this question.")