import pandas as pd

from studio.audit_flow import NOT_YET_TRIAGED
from studio.queue_table import (
    audit_checked_ids_from_table,
    data_editor_edited_row_indices,
    dataframe_selection_rows,
    enforce_audit_eligibility,
    merge_audit_state,
    paper_ids_in_queue_table,
    queue_table_dataframe,
    queue_table_row_label,
    queue_table_row_label_for_id,
    resolve_selected_paper_id,
    selection_default_row_index,
)
from studio.schema import PaperCoverage


def test_queue_table_dataframe_columns_and_audit_eligibility():
    papers = [
        {
            "id": 1,
            "year": 2020,
            "title": "Eligible full text",
            "coverage": PaperCoverage.FULL_TEXT.value,
            "triage_tier": None,
            "triage_score": 4,
        },
        {
            "id": 2,
            "year": 2019,
            "title": "Abstract only",
            "coverage": PaperCoverage.ABSTRACT_ONLY.value,
            "triage_tier": None,
            "triage_score": None,
        },
    ]
    df = queue_table_dataframe(
        papers,
        tags_by_paper_id={1: ["Bi"], 2: []},
        eligible_audit_ids={1},
        audit_checked={1: True, 2: True},
    )
    assert list(df.columns) == [
        "_paper_id",
        "Year",
        "Title",
        "Coverage",
        "Triage",
        "Relevance",
        "Tags",
        "Audit",
    ]
    assert df.loc[0, "Triage"] == NOT_YET_TRIAGED
    assert df.loc[0, "Tags"] == "Bi"
    assert bool(df.loc[0, "Audit"]) is True
    assert bool(df.loc[1, "Audit"]) is False


def test_enforce_audit_eligibility_clears_ineligible_rows():
    df = pd.DataFrame(
        [
            {"_paper_id": 1, "Audit": True},
            {"_paper_id": 2, "Audit": True},
        ]
    )
    out = enforce_audit_eligibility(df, {1})
    assert bool(out.loc[0, "Audit"]) is True
    assert bool(out.loc[1, "Audit"]) is False


def test_resolve_selected_paper_id_prefers_click_then_visible_current():
    paper_ids = [10, 20, 30]
    assert resolve_selected_paper_id(paper_ids, 20, [2]) == 30
    assert resolve_selected_paper_id(paper_ids, 20, []) == 20
    assert resolve_selected_paper_id(paper_ids, 99, []) == 10


def test_selection_default_row_index():
    assert selection_default_row_index([5, 6, 7], 6) == 1
    assert selection_default_row_index([5, 6, 7], 99) == 0


def test_audit_checked_ids_and_merge_audit_state():
    df = queue_table_dataframe(
        [{"id": 3, "title": "t", "coverage": "full_text"}],
        tags_by_paper_id={},
        eligible_audit_ids={3},
        audit_checked={},
    )
    df.loc[0, "Audit"] = True
    assert audit_checked_ids_from_table(df, {3}) == {3}
    merged = merge_audit_state({}, df, {3})
    assert merged[3] is True
    assert paper_ids_in_queue_table(df) == [3]


def test_dataframe_selection_rows_dict_and_object():
    assert dataframe_selection_rows({"selection": {"rows": [2]}}) == [2]
    assert dataframe_selection_rows(None) == []

    class _Sel:
        rows = [1]

    class _State:
        selection = _Sel()

    assert dataframe_selection_rows(_State()) == [1]


def test_data_editor_edited_row_indices_latest_row():
    assert data_editor_edited_row_indices(None) == []
    assert data_editor_edited_row_indices({"edited_rows": {1: {}, 4: {}}}) == [4]

    class _State:
        edited_rows = {0: {"Audit": True}, 2: {"Audit": False}}

    assert data_editor_edited_row_indices(_State()) == [2]


def test_queue_table_row_labels():
    row = pd.Series({"Year": 2021, "Title": "Solder joints in microelectronics"})
    assert queue_table_row_label(row) == "2021 — Solder joints in microelectronics"
    df = queue_table_dataframe(
        [{"id": 9, "title": "T", "coverage": "full_text", "year": None}],
        tags_by_paper_id={},
        eligible_audit_ids=set(),
        audit_checked={},
    )
    assert queue_table_row_label_for_id(df, 9) == "? — T"
    assert queue_table_row_label_for_id(df, 99) == "99"