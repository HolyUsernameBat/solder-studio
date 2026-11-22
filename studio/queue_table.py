from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from studio.audit_flow import effective_triage_tier

QUEUE_TABLE_DISPLAY_COLUMNS = (
    "Year",
    "Title",
    "Coverage",
    "Triage",
    "Relevance",
    "Tags",
    "Audit",
)

_PAPER_ID_COL = "_paper_id"


def _relevance_display(paper: dict) -> str:
    val = paper.get("triage_score")
    if val is None or str(val).strip() == "":
        return ""
    return str(int(val)) if isinstance(val, (int, float)) or str(val).isdigit() else str(val)


def queue_table_dataframe(
    papers: Sequence[dict],
    *,
    tags_by_paper_id: Mapping[int, list[str]],
    eligible_audit_ids: set[int],
    audit_checked: Mapping[int, bool],
) -> pd.DataFrame:
    """Build the paper-queue table (includes hidden ``_paper_id`` column)."""
    rows: list[dict] = []
    for p in papers:
        pid = int(p["id"])
        eligible = pid in eligible_audit_ids
        rows.append(
            {
                _PAPER_ID_COL: pid,
                "Year": p.get("year") if p.get("year") is not None else "",
                "Title": (p.get("title") or "").strip(),
                "Coverage": p.get("coverage") or "",
                "Triage": effective_triage_tier(p),
                "Relevance": _relevance_display(p),
                "Tags": ", ".join(tags_by_paper_id.get(pid, [])),
                "Audit": bool(eligible and audit_checked.get(pid, False)),
            }
        )
    return pd.DataFrame(rows)


def paper_ids_in_queue_table(df: pd.DataFrame) -> list[int]:
    if df.empty or _PAPER_ID_COL not in df.columns:
        return []
    return [int(x) for x in df[_PAPER_ID_COL].tolist()]


def resolve_selected_paper_id(
    paper_ids: Sequence[int],
    current_id: int | None,
    selected_row_indices: Sequence[int],
) -> int | None:
    """Pick detail paper: selection row, else keep current if visible, else first."""
    if not paper_ids:
        return None
    visible = set(paper_ids)
    if selected_row_indices:
        idx = int(selected_row_indices[0])
        if 0 <= idx < len(paper_ids):
            return paper_ids[idx]
    if current_id is not None and current_id in visible:
        return int(current_id)
    return int(paper_ids[0])


def selection_default_row_index(paper_ids: Sequence[int], paper_id: int | None) -> int:
    if paper_id is None or not paper_ids:
        return 0
    try:
        return paper_ids.index(int(paper_id))
    except ValueError:
        return 0


def enforce_audit_eligibility(df: pd.DataFrame, eligible_audit_ids: set[int]) -> pd.DataFrame:
    """Force Audit=False for rows that cannot be batch-audited."""
    if df.empty or "Audit" not in df.columns or _PAPER_ID_COL not in df.columns:
        return df
    out = df.copy()
    for i, pid in enumerate(out[_PAPER_ID_COL]):
        if int(pid) not in eligible_audit_ids:
            out.at[out.index[i], "Audit"] = False
    return out


def audit_checked_ids_from_table(
    df: pd.DataFrame,
    eligible_audit_ids: set[int],
) -> set[int]:
    if df.empty or "Audit" not in df.columns or _PAPER_ID_COL not in df.columns:
        return set()
    checked: set[int] = set()
    for _, row in df.iterrows():
        pid = int(row[_PAPER_ID_COL])
        if pid in eligible_audit_ids and bool(row["Audit"]):
            checked.add(pid)
    return checked


def merge_audit_state(
    prior: Mapping[int, bool],
    df: pd.DataFrame,
    eligible_audit_ids: set[int],
) -> dict[int, bool]:
    """Persist Audit checkboxes keyed by paper id (ineligible always False)."""
    merged = {int(k): bool(v) for k, v in prior.items()}
    if not df.empty:
        for _, row in df.iterrows():
            pid = int(row[_PAPER_ID_COL])
            merged[pid] = bool(row["Audit"]) if pid in eligible_audit_ids else False
    return merged


def dataframe_selection_rows(selection_state: object) -> list[int]:
    """Row indices from ``st.dataframe(..., on_select=...)`` state or return value."""
    if selection_state is None:
        return []
    selection = getattr(selection_state, "selection", None)
    if selection is not None and getattr(selection, "rows", None):
        return [int(i) for i in selection.rows]
    if isinstance(selection_state, dict):
        rows = selection_state.get("selection", {}).get("rows", [])
        return [int(i) for i in rows]
    return []


def data_editor_edited_row_indices(editor_state: object) -> list[int]:
    """Row indices the user touched in ``st.data_editor`` on the last commit."""
    if editor_state is None:
        return []
    edited_rows = getattr(editor_state, "edited_rows", None)
    if edited_rows is None and isinstance(editor_state, dict):
        edited_rows = editor_state.get("edited_rows")
    if not edited_rows:
        return []
    indices = sorted(int(i) for i in edited_rows)
    return [indices[-1]]


def queue_table_row_label(row: pd.Series) -> str:
    year = row.get("Year")
    year_s = str(year) if year is not None and str(year).strip() != "" else "?"
    title = (row.get("Title") or "").strip()
    return f"{year_s} — {title[:100]}"


def queue_table_row_label_for_id(df: pd.DataFrame, paper_id: int) -> str:
    if df.empty or _PAPER_ID_COL not in df.columns:
        return str(paper_id)
    match = df.loc[df[_PAPER_ID_COL] == int(paper_id)]
    if match.empty:
        return str(paper_id)
    return queue_table_row_label(match.iloc[0])