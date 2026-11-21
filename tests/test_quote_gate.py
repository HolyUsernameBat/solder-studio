from studio.quote_gate import (
    filter_rows_gates,
    row_passes_all_gates,
    row_passes_quote_gate,
    row_passes_source_gate,
)
from studio.schema import MeasurementRow, SourceSection


def test_row_dropped_when_value_not_in_quote():
    row = MeasurementRow(
        metric_name="IMC thickness",
        metric_value=12.5,
        metric_unit="um",
        source_section=SourceSection.RESULTS,
        verbatim_quote="The interfacial layer was examined by SEM.",
    )
    assert row_passes_source_gate(row)
    assert not row_passes_quote_gate(row)
    assert filter_rows_gates([row]) == []


def test_row_kept_when_value_in_quote():
    row = MeasurementRow(
        metric_name="IMC thickness",
        metric_value=12.5,
        metric_unit="um",
        source_section=SourceSection.RESULTS,
        verbatim_quote="IMC thickness was 12.5 um after 1000 h aging.",
    )
    assert row_passes_all_gates(row)
    assert len(filter_rows_gates([row])) == 1


def test_error_bar_center_value_matches():
    row = MeasurementRow(
        metric_name="shear strength",
        metric_value=42.3,
        metric_unit="MPa",
        source_section=SourceSection.TABLE,
        verbatim_quote="Ball shear strength was 42.3 ± 3.1 MPa after aging.",
    )
    assert row_passes_quote_gate(row)


def test_newline_inside_number_still_matches():
    row = MeasurementRow(
        metric_name="shear strength",
        metric_value=42.3,
        metric_unit="MPa",
        source_section=SourceSection.RESULTS,
        verbatim_quote="Strength reached 42.\n3 MPa under load.",
    )
    assert row_passes_quote_gate(row)


def test_introduction_section_rejected():
    row = MeasurementRow(
        metric_name="IMC thickness",
        metric_value=2.0,
        metric_unit="um",
        source_section=SourceSection.INTRODUCTION,
        verbatim_quote="IMC thickness was 2.0 um.",
    )
    assert not row_passes_source_gate(row)
    assert filter_rows_gates([row]) == []


def test_liu_et_al_citation_rejected():
    row = MeasurementRow(
        metric_name="IMC thickness",
        metric_value=3.1,
        metric_unit="um",
        source_section=SourceSection.RESULTS,
        verbatim_quote="Prior work (Liu et al.13) reported IMC thickness of 3.1 um.",
    )
    assert not row_passes_source_gate(row)
    assert filter_rows_gates([row]) == []


def test_results_row_with_number_kept():
    row = MeasurementRow(
        metric_name="IMC thickness",
        metric_value=4.2,
        metric_unit="um",
        source_section=SourceSection.RESULTS,
        verbatim_quote="After reflow the Cu6Sn5 IMC thickness measured 4.2 um.",
    )
    assert row_passes_all_gates(row)