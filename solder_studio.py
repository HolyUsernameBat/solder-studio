from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from studio import db
from studio.audit_flow import run_extract_and_triage
from studio.charts import rows_to_dataframe, shear_mpa_chart_frame, uts_chart_frame
from studio.codex_backend import chatgpt_subscription_active
from studio.openalex import search_openalex, try_fetch_pdf_for_work
from studio.pdfs_folder import (
    is_pdf_path_stored,
    list_folder_pdfs,
    paper_for_pdf_path,
    stored_pdf_paths,
    title_from_pdf_filename,
)
from studio.schema import PaperCoverage
from studio.synthesize import run_synthesis
from studio.triage import run_triage

CODE_ROOT = Path(__file__).resolve().parent
PDFS_DIR = CODE_ROOT / "pdfs"
SIGN_IN_HELP = "Close this page and run Start_Research_Studio.bat to sign in with ChatGPT."
CODEX_LOG_MAX_LINES = 20

st.set_page_config(page_title="Solder Studio", layout="wide")
st.title("Solder Studio")

db.init_db(CODE_ROOT)
signed_in = chatgpt_subscription_active()

sidebar_log = st.sidebar.empty()


def _codex_log_init() -> None:
    if "codex_log" not in st.session_state:
        st.session_state.codex_log = []


def _codex_log_append(line: str) -> None:
    _codex_log_init()
    st.session_state.codex_log = (
        st.session_state.codex_log + [line]
    )[-CODEX_LOG_MAX_LINES:]


def _draw_codex_sidebar() -> None:
    _codex_log_init()
    lines = st.session_state.codex_log
    if lines:
        body = "\n".join(lines)
    elif signed_in:
        body = "Codex idle."
    else:
        sidebar_log.empty()
        return
    sidebar_log.markdown(f"```\n{body}\n```")


def _codex_on_status() -> object:
    def on_status(line: str) -> None:
        _codex_log_append(line)
        _draw_codex_sidebar()

    return on_status


_draw_codex_sidebar()

if not signed_in:
    st.error(SIGN_IN_HELP)


tab_search, tab_data, tab_synth = st.tabs(["Search & triage", "Measurements", "Synthesis"])

with tab_search:
    st.subheader("OpenAlex search")
    query = st.text_input("Search query", placeholder="solder IMC shear aging SAC305")
    if st.button("Search OpenAlex", key="btn_search"):
        if not signed_in:
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
                    if pdf_name:
                        paper.pdf_path = pdf_name
                    pid = db.upsert_paper(CODE_ROOT, paper, pdf_kept=bool(pdf_name))
                    try:
                        tri = run_triage(
                            paper.title, paper.abstract, on_status=status_cb
                        )
                        db.update_paper_triage(
                            CODE_ROOT, pid, tri.tier, tri.score, tri.rationale
                        )
                    except RuntimeError as exc:
                        st.error(str(exc))
                        break
                    except Exception as exc:
                        st.warning(f"Triage failed for {paper.title}: {exc}")
                    saved += 1
                st.success(f"Stored {saved} paper(s). Search does not write solder rows.")

    st.subheader("PDFs in the folder")
    folder_pdfs = list_folder_pdfs(PDFS_DIR)
    papers_for_link = db.list_papers(CODE_ROOT)
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
                            pid = db.insert_folder_paper(CODE_ROOT, pdf_name)
                            try:
                                with st.spinner("Extracting tables…"):
                                    n, extract_err, triage_warn = run_extract_and_triage(
                                        CODE_ROOT,
                                        pid,
                                        pdf_path,
                                        title,
                                        on_status=_codex_on_status(),
                                    )
                            except RuntimeError as exc:
                                st.error(str(exc))
                                n, extract_err, triage_warn = 0, None, None
                            if extract_err:
                                st.warning(extract_err)
                            elif n:
                                st.success(f"Stored {n} quote-verified row(s).")
                            elif extract_err is None:
                                st.info("No rows passed the quote gate.")
                            if triage_warn:
                                st.warning(f"Triage failed (rows kept): {triage_warn}")

    st.subheader("Paper queue")
    papers = db.list_papers(CODE_ROOT)
    if not papers:
        st.info("No papers yet. Search above, or audit a PDF from the folder.")
    for p in papers:
        with st.expander(f"{p.get('year') or '?'} — {p['title'][:120]}"):
            st.write(f"Coverage: **{p['coverage']}**")
            if p.get("pdf_path"):
                st.write(f"PDF: `{p['pdf_path']}`")
            tier = p.get("triage_tier")
            if tier:
                st.write(f"Triage: **{tier}** ({p.get('triage_score')}/5)")
                st.caption(p.get("triage_rationale") or "")
            else:
                st.caption("Not triaged yet.")
            if p.get("coverage") == PaperCoverage.FULL_TEXT.value and p.get("pdf_path"):
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
                                        pdf_path,
                                        p["title"],
                                        on_status=_codex_on_status(),
                                    )
                            except RuntimeError as exc:
                                st.error(str(exc))
                                n, extract_err, triage_warn = 0, None, None
                            if extract_err:
                                st.warning(extract_err)
                            elif n:
                                st.success(f"Stored {n} quote-verified row(s).")
                            elif extract_err is None:
                                st.info("No rows passed the quote gate.")
                            if triage_warn:
                                st.warning(f"Triage failed (rows kept): {triage_warn}")

with tab_data:
    st.subheader("Extracted measurements")
    all_rows = db.list_solder_rows(CODE_ROOT)
    papers = {p["id"]: p["title"] for p in db.list_papers(CODE_ROOT)}
    for row in all_rows:
        if row.paper_id is not None:
            row.paper_id = row.paper_id

    df = rows_to_dataframe(all_rows, papers)
    if df.empty:
        st.info("No rows yet. Audit a PDF from tab 1.")
    else:
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", csv, "solder_rows.csv", "text/csv")

        col1, col2 = st.columns(2)
        shear_df = shear_mpa_chart_frame(df)
        with col1:
            st.markdown("**Shear (MPa) vs IMC thickness (µm)**")
            if shear_df.empty:
                st.caption("No MPa shear points (N and gf values stay in the table only).")
            else:
                fig = px.scatter(
                    shear_df,
                    x="imc_thickness_um",
                    y="shear_value",
                    hover_data=["alloy", "source_page", "paper_title"],
                    labels={"imc_thickness_um": "IMC thickness (µm)", "shear_value": "Shear (MPa)"},
                )
                st.plotly_chart(fig, use_container_width=True)
        uts_df = uts_chart_frame(df)
        with col2:
            st.markdown("**UTS (MPa) vs IMC thickness (µm)**")
            if uts_df.empty:
                st.caption("No UTS + thickness pairs yet.")
            else:
                fig2 = px.scatter(
                    uts_df,
                    x="imc_thickness_um",
                    y="uts_mpa",
                    hover_data=["alloy", "source_page", "paper_title"],
                    labels={"imc_thickness_um": "IMC thickness (µm)", "uts_mpa": "UTS (MPa)"},
                )
                st.plotly_chart(fig2, use_container_width=True)

with tab_synth:
    st.subheader("Benchmark synthesis")
    all_rows = db.list_solder_rows(CODE_ROOT)
    if st.button("Run synthesis", key="btn_synth"):
        if not signed_in:
            st.error(SIGN_IN_HELP)
        else:
            papers_by_id = {p["id"]: p["title"] for p in db.list_papers(CODE_ROOT)}
            try:
                briefing, stop, used = run_synthesis(
                    all_rows,
                    paper_titles=papers_by_id,
                    on_status=_codex_on_status(),
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
    all_rows = db.list_solder_rows(CODE_ROOT)
    if all_rows:
        st.markdown("**Quote-verified rows in database**")
        st.caption(f"{len(all_rows)} row(s) stored for synthesis.")